"""AgriTwin AI - Flask backend + SQLite storage.  Run: python app.py"""
import os, sqlite3
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template
import twin

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agritwin.db")
app = Flask(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS farms(id INTEGER PRIMARY KEY, name TEXT, size_ha REAL, water_l_day REAL, seed INTEGER);
CREATE TABLE IF NOT EXISTS plots(id INTEGER PRIMARY KEY, farm_id INT, name TEXT, crop TEXT, soil TEXT, stage TEXT);
CREATE TABLE IF NOT EXISTS readings(plot_id INT, ts INT, raw REAL, true REAL, temp REAL, humidity REAL,
  rain REAL, irrigation REAL, PRIMARY KEY(plot_id, ts));
"""


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with db() as _c:
    _c.executescript(SCHEMA)


def insert(c, pid, rows, rng):
    for r in rows:
        raw, t, hu = twin.sensor(rng, r["m"], r["temp"], r["hum"])
        c.execute("INSERT OR REPLACE INTO readings VALUES(?,?,?,?,?,?,?,?)",
                  (pid, r["ts"], raw, r["m"], t, hu, r["rain"], r["irr"]))


def load(fid):
    with db() as c:
        f = c.execute("SELECT * FROM farms WHERE id=?", (fid,)).fetchone()
        if not f:
            return None, None, None
        plots = [dict(p) for p in c.execute("SELECT * FROM plots WHERE farm_id=? ORDER BY id", (fid,))]
        ids = ",".join(str(p["id"]) for p in plots)
        rd = pd.read_sql_query(f"SELECT * FROM readings WHERE plot_id IN ({ids})", c)
    return dict(f), plots, rd


def analysis(fid):
    f, plots, rd = load(fid)
    return None if f is None else twin.analyze(f, plots, rd)


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/farm")
def create_farm():
    j = request.get_json(force=True)
    try:
        size, water = float(j["size_ha"]), float(j["water_l_day"])
        plots = j["plots"]
        assert size > 0 and water >= 0 and 1 <= len(plots) <= 8
        for p in plots:
            assert p["crop"] in twin.CROPS and p["soil"] in twin.SOILS and p["stage"] in twin.STAGES
            assert 5 <= float(p["moisture"]) <= 60
    except Exception:
        return jsonify(error="Invalid input: check size, water, crop/soil/stage and moisture (5-60%)."), 400
    seed = int(np.random.randint(1, 10000))
    rng = np.random.default_rng(seed)
    with db() as c:
        fid = c.execute("INSERT INTO farms(name,size_ha,water_l_day,seed) VALUES(?,?,?,?)",
                        (j.get("name") or "My Farm", size, water, seed)).lastrowid
        for k, p in enumerate(plots):
            pid = c.execute("INSERT INTO plots(farm_id,name,crop,soil,stage) VALUES(?,?,?,?,?)",
                            (fid, p.get("name") or f"Plot {k + 1}", p["crop"], p["soil"], p["stage"])).lastrowid
            rows = twin.history(seed, float(p["moisture"]), twin.kc_of(p["crop"], p["stage"]), p["soil"])
            insert(c, pid, rows, rng)
    return jsonify(id=fid)


@app.get("/api/farms/latest")
def latest():
    with db() as c:
        r = c.execute("SELECT id FROM farms ORDER BY id DESC LIMIT 1").fetchone()
    return jsonify(id=r["id"] if r else None)


@app.get("/api/farm/<int:fid>")
def get_farm(fid):
    a = analysis(fid)
    return (jsonify(a), 200) if a else (jsonify(error="Farm not found"), 404)


@app.post("/api/farm/<int:fid>/advance")
def advance(fid):
    """Feedback loop: apply (simulated) recommended irrigation, move the twin 24 h ahead, re-analyse."""
    a = analysis(fid)
    if not a:
        return jsonify(error="Farm not found"), 404
    f, plots, rd = load(fid)
    rng = np.random.default_rng(int(a["now"]) + f["seed"])
    with db() as c:
        for p, rec in zip(plots, a["plots"]):
            last = rd[rd.plot_id == p["id"]].sort_values("ts").iloc[-1]
            irr = {}
            if rec.get("offset") is not None and rec.get("alloc_mm", 0) > 0:
                irr[rec["offset"]] = rec["alloc_mm"]
            rows = twin.run(f["seed"], float(last.true), twin.kc_of(p["crop"], p["stage"]),
                            p["soil"], int(last.ts), 24, irr)
            c.execute("UPDATE readings SET irrigation=? WHERE plot_id=? AND ts=?",
                      (irr.get(0, 0.0), p["id"], int(last.ts)))
            insert(c, p["id"], rows[1:], rng)
    return jsonify(analysis(fid))


if __name__ == "__main__":
    app.run(debug=True)
