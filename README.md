# AgriTwin AI 🌱
Software-only smart-agriculture digital twin: virtual farm -> simulated IoT data -> cleaning -> ML moisture
prediction -> what-if irrigation scenarios -> water-budget-aware recommendations -> dashboard + feedback loop.

    pip install -r requirements.txt
    python app.py        # open http://127.0.0.1:5000  -> "Load example" -> "Create virtual farm"

Files: app.py (Flask+SQLite), twin.py (twin engine, ML, scenarios), templates/index.html, static/app.js.
Note: sensors, weather and irrigation effects are simulated; crop thresholds are illustrative, not validated agronomy.
No real irrigation equipment is controlled. Leaflet map is an optional extension (not included).
