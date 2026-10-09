#!/usr/bin/env python3
"""สร้างข้อมูลจำลอง (ไม่ใช่ข้อมูลจริง) เพื่อทดสอบระบบแบบไม่ต่ออินเทอร์เน็ต

สถานการณ์สมมติ: ฝนหนักในลุ่มคลองอู่ตะเภา ณ 2026-11-24 10:00 น.
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "tests", "fixtures")
PREV = os.path.join(ROOT, "tests", "prev", "data")
ICT = timezone(timedelta(hours=7))
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=ICT)
random.seed(7)

tam = json.load(open(os.path.join(ROOT, "site/data/static/tambons.geojson"), encoding="utf-8"))["features"]
admin = json.load(open(os.path.join(ROOT, "site/data/static/admin.json"), encoding="utf-8"))
P = {f["properties"]["tc"]: f["properties"] for f in tam}


def find(t, a):
    return next(p for p in P.values() if p["t"] == t and p["a"] == a)


def geo(p):
    return {"province_name": {"th": p["p"]}, "amphoe_name": {"th": p["a"]}, "tumbon_name": {"th": p["t"]}}


def ts(dt):
    return dt.astimezone(ICT).strftime("%Y-%m-%d %H:%M")


os.makedirs(FX, exist_ok=True)
os.makedirs(PREV, exist_ok=True)

# ---- water level stations
wl, hist = [], {}
sid = 9000
special = [  # (code, tambon, amphoe, level, bank, rise m/h)
    ("X.173A", "สะเดา", "สะเดา", 31.2, 31.0, 0.15),
    ("X.90", "คลองหอยโข่ง", "คลองหอยโข่ง", 18.4, 18.9, 0.20),
    ("X.44", "หาดใหญ่", "หาดใหญ่", 7.1, 8.0, 0.12),
]
for code, t, a, lv, bank, rise in special:
    p = find(t, a)
    sid += 1
    wl.append({"waterlevel_datetime": ts(NOW - timedelta(minutes=10)), "waterlevel_msl": str(lv), "situation_level": 4,
               "station": {"id": sid, "tele_station_name": {"th": f"คลองอู่ตะเภา {t}"}, "tele_station_oldcode": code,
                           "tele_station_lat": p["lat"], "tele_station_long": p["lon"], "min_bank": bank,
                           "warning_level_m": None, "critical_level_m": None},
               "geocode": geo(p), "agency": {"agency_name": {"th": "กรมชลประทาน"}}})
    hist[f"tw:{sid}"] = [[(NOW - timedelta(minutes=10) - timedelta(hours=h)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          round(lv - rise * h, 2)] for h in (3, 2.5, 2, 1.5, 1, 0.5)]
others = random.sample([p for p in P.values() if p["p"] in ("สงขลา", "พัทลุง", "สตูล", "ยะลา", "ปัตตานี", "นครศรีธรรมราช")], 45)
for i, p in enumerate(others):
    sid += 1
    bank = round(random.uniform(3, 25), 2)
    gap = random.choice([2.5, 1.8, 1.2, 0.9, 0.4, 3.0, 2.0, -0.2])
    age = 30 if i % 9 else 60 * 30  # some stale stations
    wl.append({"waterlevel_datetime": ts(NOW - timedelta(minutes=age)), "waterlevel_msl": str(round(bank - gap, 2)),
               "situation_level": 3, "station": {"id": sid, "tele_station_name": {"th": f"สถานีจำลอง {p['t']}"},
                                                  "tele_station_oldcode": f"SIM{i:02d}", "tele_station_lat": p["lat"],
                                                  "tele_station_long": p["lon"], "min_bank": None if i % 11 == 0 else bank,
                                                  "warning_level_m": None, "critical_level_m": None},
               "geocode": geo(p), "agency": {"agency_name": {"th": "สสน."}}})
# one station outside the area (must be filtered out)
wl.append({"waterlevel_datetime": ts(NOW), "waterlevel_msl": "1.0", "station": {"id": 1, "tele_station_name": {"th": "กรุงเทพฯ"},
           "tele_station_lat": 13.7, "tele_station_long": 100.5, "min_bank": 2}, "geocode": {"province_name": {"th": "กรุงเทพมหานคร"}}})
json.dump({"waterlevel_data": {"data": wl}}, open(os.path.join(FX, "tw_waterlevel.json"), "w"), ensure_ascii=False)
json.dump(hist, open(os.path.join(PREV, "history.json"), "w"))

# ---- rain gauges
rain = []
for i, p in enumerate(random.sample(list(P.values()), 80)):
    heavy = p["a"] in ("หาดใหญ่", "สะเดา", "คลองหอยโข่ง", "นาหม่อม", "บางกล่ำ")
    rain.append({"rain_24h": round(random.uniform(120, 260) if heavy else random.uniform(0, 60), 1), "rainfall_datetime": ts(NOW - timedelta(minutes=15)),
                 "station": {"id": 7000 + i, "tele_station_name": {"th": f"ฝนจำลอง {p['t']}"}, "tele_station_lat": p["lat"], "tele_station_long": p["lon"]},
                 "geocode": geo(p)})
json.dump({"data": rain}, open(os.path.join(FX, "tw_rain24.json"), "w"), ensure_ascii=False)

# ---- Open-Meteo (multi-location responses, 40 per batch)
models = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
start = NOW.replace(hour=0) - timedelta(days=1)
times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(24 * 5)]
am = admin["amphoes"]
for b in range(0, len(am), 40):
    rr, ss = [], []
    for a in am[b:b + 40]:
        dist = abs(a["lat"] - 6.9) + abs(a["lon"] - 100.45)
        peak = max(0.2, 9 - dist * 9)  # mm/h near Hat Yai, tapering away
        h = {"time": times}
        for k, m in enumerate(models):
            h[f"precipitation_{m}"] = [round(max(0, peak * (0.7 + 0.3 * k) * (1 if 6 <= (i % 24) <= 20 else 0.4) * random.uniform(0.5, 1.3)), 1) for i in range(len(times))]
        rr.append({"latitude": a["lat"], "longitude": a["lon"], "hourly": h})
        ss.append({"hourly": {"time": times, "soil_moisture_3_to_9cm": [0.43 if dist < 0.5 else 0.31] * len(times)}})
    json.dump(rr, open(os.path.join(FX, f"om_rain_{b // 40}.json"), "w"))
    json.dump(ss, open(os.path.join(FX, f"om_soil_{b // 40}.json"), "w"))

# ---- HII FEWS files
ffl = ["province\tamphoe\ttambon\tffpi\train_forecast_1d\tstation"]
for t, a in (("ทุ่งลาน", "คลองหอยโข่ง"), ("คลองหลา", "คลองหอยโข่ง"), ("เขาพระ", "รัตภูมิ")):
    try:
        p = find(t, a)
        ffl.append(f"{p['p']}\t{p['a']}\t{p['t']}\t7.4\t110\tSIM")
    except StopIteration:
        pass
open(os.path.join(FX, "fews_flashflood.txt"), "w", encoding="utf-8").write("\n".join(ffl))
open(os.path.join(FX, "fews_hii_waterlevel.txt"), "w").write("station_code,lowest,alarm,warning,critical\nSIM03,0,1,2,3\n")
print("สร้างข้อมูลจำลองแล้ว:", FX, file=sys.stderr)

# ---- 365-day history (waterlevel_graph) for the archive test: an event with travel time
import math  # noqa: E402
peaks = {"X.173A": datetime(2025, 11, 24, 12, tzinfo=ICT), "X.90": datetime(2025, 11, 24, 19, tzinfo=ICT),
         "X.44": datetime(2025, 11, 25, 1, tzinfo=ICT)}
t0 = datetime(2025, 10, 1, tzinfo=ICT)
for r in wl:
    st = r["station"]
    code = st.get("tele_station_oldcode")
    bank = st.get("min_bank") or 10
    pts = []
    for h in range(0, 24 * 70):
        t = t0 + timedelta(hours=h)
        base = bank - 2.5 + 0.2 * math.sin(h / 9.0)
        if code in peaks:
            dh = (t - peaks[code]).total_seconds() / 3600
            base += 3.2 * math.exp(-(dh / 14) ** 2) + 0.4 * math.exp(-((dh + 120) / 10) ** 2)
        pts.append({"datetime": t.strftime("%Y-%m-%d %H:%M"), "value": round(base, 2)})
    json.dump({"data": {"graph_data": pts, "min_bank": bank}}, open(os.path.join(FX, f"graph_{st['id']}.json"), "w"))
