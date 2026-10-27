"""AgriTwin AI - digital twin engine: simulated weather/soil physics, sensor simulation,
data cleaning, ML moisture prediction, what-if scenarios and recommendations.
All values are SIMULATED. Thresholds are illustrative, not validated agronomy."""
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

# low = crop stress below this (% vol. moisture); lo..hi = comfortable range; use = relative water use
CROPS = {
    "wheat":  dict(low=22, lo=25, hi=40, use=0.90),
    "tomato": dict(low=25, lo=30, hi=45, use=1.15),
    "maize":  dict(low=22, lo=28, hi=42, use=1.10),
    "cotton": dict(low=20, lo=25, hi=40, use=1.00),
    "potato": dict(low=26, lo=30, hi=44, use=1.05),
}
STAGES = {"seedling": 0.5, "vegetative": 0.9, "flowering": 1.15, "maturity": 0.7}
# drain = relative drying speed, fc = field capacity (%), gain = % moisture gained per mm of water
SOILS = {
    "sandy": dict(drain=1.3, fc=32, gain=0.90),
    "loam":  dict(drain=1.0, fc=42, gain=0.70),
    "clay":  dict(drain=0.8, fc=48, gain=0.55),
}
FEATS = ["moisture", "temp", "humidity", "hs", "hc", "kc", "sf"]
HOR = 48          # forecast horizon (hours)
HIST = 168        # initial simulated history (hours)
MAX_MM = 30       # max irrigation per event (mm)


def kc_of(crop, stage):
    return CROPS[crop]["use"] * STAGES[stage]


# ---------- simulated environment ----------
def weather(seed, h):
    """Deterministic simulated weather for absolute hour h -> (temp C, humidity %, rain mm)."""
    day, hr = divmod(int(h), 24)
    r = np.random.default_rng(seed * 7919 + day)
    base = 24 + r.normal(0, 4)
    wet = r.random() < 0.18
    rs, ra = int(r.integers(0, 21)), r.uniform(4, 18)
    temp = base + 7 * math.sin(2 * math.pi * (hr - 9) / 24)
    hum = min(max(80 - 2 * (temp - 20), 25), 95)
    rain = ra / 3 if wet and rs <= hr < rs + 3 else 0.0
    return temp, hum, rain


def base_loss(t, hu, hr):
    dl = 0.15 + max(0.0, math.sin(math.pi * (hr - 6) / 12))
    return 0.22 * dl * (1 + 0.05 * max(t - 15, 0)) * (1.3 - 0.8 * hu / 100)


def step(m, t, hu, hr, kc, S, rain, irr):
    """One hour of 'true' soil physics inside the twin."""
    m = m - base_loss(t, hu, hr) * kc * S["drain"] + (rain * 0.85 + irr) * S["gain"]
    if m > S["fc"]:
        m -= 0.25 * (m - S["fc"])
    return float(min(max(m, 5), 60))


def run(seed, m, kc, soil, h0, steps, irr_map):
    S, rows = SOILS[soil], []
    for i in range(steps + 1):
        h = h0 + i
        t, hu, rain = weather(seed, h)
        irr = irr_map.get(i, 0.0) if i < steps else 0.0
        rows.append(dict(ts=h, m=m, temp=t, hum=hu, rain=rain, irr=irr))
        if i < steps:
            m = step(m, t, hu, h % 24, kc, S, rain, irr)
    return rows


def history(seed, target, kc, soil, n=HIST):
    start = target
    for _ in range(3):
        rows = run(seed, start, kc, soil, 0, n, {})
        start = float(np.clip(start + target - rows[-1]["m"], 8, 58))
    shift = target - rows[-1]["m"]
    for r in rows:
        r["m"] = float(np.clip(r["m"] + shift, 5, 60))
    return rows


def sensor(rng, m, t, hu):
    """Simulated IoT sensor: noise, 3% missing, 1% abnormal spikes."""
    raw, u = m + rng.normal(0, 0.15), rng.random()
    if u < 0.03:
        raw = None
    elif u < 0.04:
        raw = m + rng.choice([-1, 1]) * rng.uniform(15, 25)
    return raw, t + rng.normal(0, 0.3), float(min(max(hu + rng.normal(0, 1.5), 0), 100))


# ---------- data processing ----------
def clean(raw):
    s = pd.Series(raw, dtype=float)
    flag = np.where(s.isna(), "missing", "ok").astype(object)
    med = s.rolling(5, center=True, min_periods=2).median()
    bad = ((s < 0) | (s > 70) | ((s - med).abs() > 8)) & s.notna()
    flag[bad.values] = "abnormal"
    s[bad] = np.nan
    return s.interpolate(limit_direction="both").values, flag


# ---------- AI prediction ----------
def train(df):
    """Learn hourly drying rate from dry-hour history (random forest)."""
    d = df.sort_values(["plot_id", "ts"]).copy()
    g = d.groupby("plot_id")
    d["hs"] = np.sin(2 * np.pi * (d.ts % 24) / 24)
    d["hc"] = np.cos(2 * np.pi * (d.ts % 24) / 24)
    d["y"] = (d.moisture - g.moisture.shift(-3)) / 3
    for c in ("rain", "irrigation"):
        d["w_" + c] = g[c].transform(lambda s: s.rolling(3).sum().shift(-2))
    d = d[(d.w_rain == 0) & (d.w_irrigation == 0) & d.y.notna() & (d.moisture < d.fc)]
    d = d.sort_values("ts")
    cut = int(len(d) * 0.75)
    tr, te = d.iloc[:cut], d.iloc[cut:]
    mk = lambda: RandomForestRegressor(80, min_samples_leaf=3, random_state=0)
    mae = base = None
    if len(te) > 10:
        rf = mk().fit(tr[FEATS].values, tr.y.values)
        mae = float(np.abs(rf.predict(te[FEATS].values) - te.y.values).mean())
        base = float(np.abs(tr.y.mean() - te.y.values).mean())
    rf = mk().fit(d[FEATS].values, d.y.values)
    return rf, mae, base, len(d)


def rollout(rf, S, now, seed, m0, kc, sf, fc, gain, irr):
    """Batch-simulate N (plot, scenario) states for HOR hours using the ML drying rate."""
    N = len(m0)
    m, traj = m0.copy(), np.zeros((N, HOR + 1))
    traj[:, 0] = m
    for i in range(HOR):
        h = now + i
        t, hu, rain = weather(seed, h)
        a = 2 * np.pi * (h % 24) / 24
        X = np.column_stack([m, np.full(N, t), np.full(N, hu),
                             np.full(N, math.sin(a)), np.full(N, math.cos(a)), kc, sf])
        loss = np.clip(rf.predict(X), 0, 0.8)
        m = m - loss + (rain * 0.85 + irr[:, i]) * gain
        m = m - np.where(m > fc, 0.25 * (m - fc), 0)
        m = np.clip(m, 5, 60)
        traj[:, i + 1] = m
    return traj


# ---------- digital twin + recommendation ----------
def analyze(farm, plots, rd):
    seed, n = farm["seed"], len(plots)
    area = farm["size_ha"] * 10000 / n
    frames = {}
    for p in plots:
        d = rd[rd.plot_id == p["id"]].sort_values("ts").reset_index(drop=True)
        d["moisture"], d["flag"] = clean(d.raw.values)
        sl = SOILS[p["soil"]]
        d["kc"], d["sf"], d["fc"] = kc_of(p["crop"], p["stage"]), sl["drain"], sl["fc"]
        frames[p["id"]] = d
    rf, mae, base, nrows = train(pd.concat(frames.values()))
    now = int(max(d.ts.max() for d in frames.values()))
    rain24 = sum(weather(seed, now + i)[2] for i in range(24))

    names = ["none", "now", "delay", "reduce"]
    meta, m0, kc, sf, fc, gain, irr = [], [], [], [], [], [], []
    for p in plots:
        d, C, sl = frames[p["id"]], CROPS[p["crop"]], SOILS[p["soil"]]
        cur = float(d.moisture.iloc[-1])
        target = (C["lo"] + C["hi"]) / 2
        need = max(0.0, (target - cur) / sl["gain"] - 0.85 * rain24)
        need = min(need, MAX_MM) if need >= 0.5 else 0.0
        sched = {"none": {}, "now": {0: need}, "delay": {12: need}, "reduce": {0: need * 0.5}}
        meta.append((p, d, C, sl, cur, need))
        for nm in names:
            a = np.zeros(HOR)
            for k, v in sched[nm].items():
                a[k] = v
            m0.append(cur); kc.append(d.kc.iloc[0]); sf.append(sl["drain"])
            fc.append(sl["fc"]); gain.append(sl["gain"]); irr.append(a)
    traj = rollout(rf, None, now, seed, np.array(m0), np.array(kc), np.array(sf),
                   np.array(fc), np.array(gain), np.array(irr))

    out, alerts = [], []
    for j, (p, d, C, sl, cur, need) in enumerate(meta):
        sc = {}
        for k, nm in enumerate(names):
            i = j * 4 + k
            tr, mm = traj[i], float(irr[i].sum())
            stress = int((tr[1:] < C["low"]).sum())
            over = int((tr[1:] > min(C["hi"], sl["fc"])).sum())
            sc[nm] = dict(traj=[round(float(v), 2) for v in tr], mm=round(mm, 1),
                          liters=round(mm * area), stress_hours=stress, over_hours=over,
                          min=round(float(tr.min()), 1), final=round(float(tr[-1]), 1),
                          score=3 * stress + over + 0.15 * mm)
        best = min(names, key=lambda k: (round(sc[k]["score"], 3), sc[k]["mm"]))
        status = ("critical" if cur < C["low"] else "low" if cur < C["lo"]
                  else "adequate" if cur <= C["hi"] else "excess")
        out.append(dict(id=p["id"], name=p["name"], crop=p["crop"], soil=p["soil"], stage=p["stage"],
                        area_m2=round(area), current=round(cur, 1), status=status,
                        thr=dict(low=C["low"], lo=C["lo"], hi=C["hi"]),
                        history=[round(float(v), 2) for v in d.moisture.tail(72)],
                        scenarios=sc, best=best, need_mm=round(need, 1)))
        bad = int((d.flag.tail(72) != "ok").sum())
        if bad:
            alerts.append(dict(level="info", text=f"{p['name']}: {bad} missing/abnormal sensor readings in last 72 h were cleaned."))

    # water-budget allocation: most urgent plots first
    budget = float(farm["water_l_day"])
    left, requested, allocated = budget, 0.0, 0.0
    order = sorted([o for o in out if o["best"] != "none"],
                   key=lambda o: (-o["scenarios"]["none"]["stress_hours"], o["current"] - o["thr"]["lo"]))
    prio = {o["id"]: r + 1 for r, o in enumerate(order)}
    label = {"none": "MONITOR", "now": "IRRIGATE NOW", "delay": "IRRIGATE IN ~12 HOURS", "reduce": "IRRIGATE LIGHTLY (50%)"}
    for o in order:
        req = o["scenarios"][o["best"]]["liters"]
        give = min(req, left); left -= give
        requested += req; allocated += give
        o["req_l"], o["alloc_l"] = req, round(give)
        o["alloc_mm"] = round(o["scenarios"][o["best"]]["mm"] * (give / req if req else 0), 1)
        o["offset"] = 12 if o["best"] == "delay" else 0
    for o in out:
        sn, bs = o["scenarios"]["none"], o["scenarios"][o["best"]]
        action = label[o["best"]]
        if o["best"] == "none" and o["need_mm"] > 0 and rain24 > 2:
            action = "HOLD - rain expected"
        why = [f"Moisture is {o['current']}% ({o['status']}); stress below {o['thr']['low']}%, comfortable {o['thr']['lo']}-{o['thr']['hi']}%.",
               f"Without irrigation the AI predicts a minimum of {sn['min']}% in {HOR} h ({sn['stress_hours']} stress hours)."]
        if rain24 > 1:
            why.append(f"About {rain24:.0f} mm of rain is forecast in the next 24 h (already counted).")
        if o["best"] != "none":
            why.append(f"Best what-if: {bs['mm']} mm ({bs['liters']} L) -> stress hours {bs['stress_hours']}, over-wet hours {bs['over_hours']}, final {bs['final']}%.")
            why.append(f"Priority #{prio[o['id']]}; allocated {o['alloc_l']} of {o['req_l']} L." + (" Water is limited - this plot is only partly covered." if o["alloc_l"] < o["req_l"] else ""))
        else:
            why.append("No irrigation scores best: moisture stays acceptable. Reassess next cycle.")
        o["action"], o["why"], o["priority"] = action, why, prio.get(o["id"])
        if o["status"] == "critical":
            alerts.insert(0, dict(level="crit", text=f"{o['name']} ({o['crop']}) is below its stress threshold at {o['current']}%."))
    if requested > budget:
        alerts.insert(0, dict(level="warn", text=f"Water shortage: {requested:.0f} L requested but only {budget:.0f} L available."))
    return dict(farm=farm, plots=out, alerts=alerts, now=now,
                budget=dict(available=budget, requested=requested, allocated=allocated),
                weather=[dict(t=round(w[0],1),h=round(w[1]),r=round(w[2],1)) for w in (weather(seed, now + i) for i in range(24))],
                model=dict(mae=mae, baseline_mae=base, rows=nrows, rain24=round(rain24, 1)))