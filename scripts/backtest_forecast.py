#!/usr/bin/env python3
"""ทดสอบย้อนหลัง: แบบจำลองพยากรณ์อากาศบอกล่วงหน้าได้หรือไม่ว่าจะมีฝนหนักในเขตหาดใหญ่

คำถาม: ถ้าดูพยากรณ์ตอนเช้า จะรู้ไหมว่าบ่าย–ค่ำวันนั้นจะมีฝนหนัก (≥ 30 มม./ชม.) ในอำเภอหาดใหญ่
- ฝนจริง: บันทึกฝนรายชั่วโมงของระบบเอง (gh-pages data/rain_log) และถ้าดึงได้ ข้อมูลฝนย้อนหลังจาก สสน.
- พยากรณ์ 2 แบบจาก Open-Meteo
  1. "พยากรณ์ล่วงหน้า 1 วัน" (Previous Runs API, รอบที่ออกก่อนราว 24–48 ชม.)
  2. "พยากรณ์รอบล่าสุด" (Historical Forecast API, ชั่วโมงต้น ๆ ของแต่ละรอบ ≈ ล่วงหน้า 0–6 ชม.)
     แบบนี้มองโลกในแง่ดีกว่าการใช้งานจริง เพราะไม่ได้หักเวลาที่ต้องรอผลพยากรณ์ออก
  พร้อมค่า CAPE (พลังงานที่ทำให้เกิดฝนฟ้าคะนอง)
- นับรายวัน: วันที่มีฝนหนักจริง พยากรณ์ส่งสัญญาณไหม และวันที่ไม่มีฝน พยากรณ์ส่งสัญญาณผิดกี่วัน
ผลลัพธ์: GitHub job summary และ site/data/static/forecast_backtest.json
"""
import argparse
import csv
import glob
import os
import sys
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from common import ICT, TambonIndex, find_records, fnum, http_get, load_json, parse_iso, parse_local, save_json, summary  # noqa: E402

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
POINTS = [  # (name, lat, lon)
    ("หาดใหญ่ (กลางเมือง)", 7.006, 100.474),
    ("คอหงส์ (เชิงเขา)", 6.995, 100.505),
    ("พะตง (ควนเนียง)", 6.880, 100.430),
]
P_THR = [5, 10, 20]          # forecast max hourly rain, mm/h
CAPE_THR = [1000, 2000, 3000]  # J/kg
HEAVY = 30                    # observed heavy hour, mm/h
# events seen on CCTV / reported before our hourly log began (no gauge numbers in our log)
REPORTED = {"2026-10-14": "ฝนหนักบ่าย คลอง 30 เมตรขึ้นเร็ว (CCTV)", "2026-10-15": "ฝนหนักบ่าย หนักกว่าวันก่อน (CCTV)"}


def om(url, params):
    q = urllib.parse.urlencode(params, safe=",")
    return http_get(f"{url}?{q}", timeout=120)


def forecast_series(kind, start, end):
    """{(model, var): {local hour iso: max over points}}"""
    if kind == "dayahead":
        url, vars_ = "https://previous-runs-api.open-meteo.com/v1/forecast", ["precipitation_previous_day1", "cape_previous_day1"]
    else:
        url, vars_ = "https://historical-forecast-api.open-meteo.com/v1/forecast", ["precipitation", "cape"]
    out, notes = defaultdict(dict), []
    for var in vars_:
        for m in MODELS:
            try:
                data = om(url, {"latitude": ",".join(str(p[1]) for p in POINTS), "longitude": ",".join(str(p[2]) for p in POINTS),
                                "hourly": var, "models": m, "start_date": start, "end_date": end, "timezone": "Asia/Bangkok"})
            except Exception as e:  # noqa: BLE001
                notes.append(f"{kind} {m} {var}: {str(e)[:120]}")
                continue
            locs = data if isinstance(data, list) else [data]
            key = (m, "rain" if var.startswith("precip") else "cape")
            for loc in locs:
                h = loc.get("hourly") or {}
                vals = h.get(var) or next((v for k, v in h.items() if k.startswith(var)), None)
                for t, v in zip(h.get("time", []), vals or []):
                    if v is not None:
                        out[key][t] = max(out[key].get(t, 0), v)
    return out, notes


def observed(rain_log_dir, idx, amphoe, extra):
    """{date: (max mm/h, time, gauge)} for the amphoe, from our hourly log (+ optional extra rows)."""
    props = {it[5]["tc"]: it[5] for it in idx.items}
    day = {}
    rows = []
    for f in sorted(glob.glob(os.path.join(rain_log_dir, "*.csv"))):
        with open(f, encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    rows += extra
    covered = set()
    for r in rows:
        t = parse_iso(r["time"]) if "T" in r["time"] else parse_local(r["time"])
        if not t:
            continue
        t = t.astimezone(ICT)
        covered.add(t.strftime("%Y-%m-%d"))
        if (props.get(r.get("tc")) or {}).get("a") != amphoe:
            continue
        v = fnum(r.get("rain_1h")) or fnum(r.get("est_1h")) or 0
        d = t.strftime("%Y-%m-%d")
        if v > day.get(d, (0,))[0]:
            day[d] = (v, t.strftime("%H:%M"), r.get("name"))
    return day, covered


def probe_rain_history(base, gauge_ids, start, end):
    """Look for a ThaiWater endpoint that returns past hourly rain for a gauge; report what answered."""
    tried, rows = [], []
    cands = ["rain_graph?station_type=tele_station&station_id={i}&start_date={s}&end_date={e}",
             "rain_graph?station_id={i}&start_date={s}&end_date={e}",
             "rainfall_graph?station_id={i}&start_date={s}&end_date={e}"]
    for c in cands:
        url = base + "/" + c.format(i=gauge_ids[0], s=start, e=end)
        try:
            data = http_get(url, timeout=60, retries=1)
            recs = find_records(data, "datetime") or find_records(data, "date")
            tried.append(f"`{c.split('?')[0]}`: ตอบกลับ {len(recs)} แถว")
            if recs:
                for i in gauge_ids:
                    try:
                        d = http_get(base + "/" + c.format(i=i, s=start, e=end), timeout=60, retries=1)
                    except Exception:  # noqa: BLE001
                        continue
                    for p in find_records(d, "datetime") or find_records(d, "date"):
                        v = fnum(p.get("value") or p.get("rainfall") or p.get("rain"))
                        rows.append({"time": p.get("datetime") or p.get("date"), "k": f"twr:{i}", "tc": None, "rain_1h": v, "_id": i})
                return tried, rows
        except Exception as e:  # noqa: BLE001
            tried.append(f"`{c.split('?')[0]}`: {str(e)[:80]}")
    return tried, rows


def probe_subhourly(base):
    """Does the rain feed carry anything finer than 1 hour?"""
    notes = []
    try:
        data = http_get(base + "/rain_24h", timeout=180)
        recs = find_records(data, "station")
        keys = sorted({k for r in recs[:50] for k in r.keys()})
        notes.append("ฟิลด์ใน rain_24h: " + ", ".join(f"`{k}`" for k in keys))
    except Exception as e:  # noqa: BLE001
        notes.append(f"rain_24h: {e}")
    for ep in ("rain_15m", "rain_10m", "rain_5m", "rain_today"):
        try:
            d = http_get(f"{base}/{ep}", timeout=60, retries=1)
            notes.append(f"`{ep}`: ตอบกลับ {len(find_records(d, 'station'))} สถานี")
        except Exception as e:  # noqa: BLE001
            notes.append(f"`{ep}`: {str(e)[:60]}")
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--static", default="site/data/static")
    ap.add_argument("--rain-log", default="pages/data/rain_log")
    ap.add_argument("--latest", default="pages/data/latest.json")
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default="site/data/static/forecast_backtest.json")
    args = ap.parse_args()
    cfg = load_json(args.config)
    end = args.end or (datetime.now(ICT) - timedelta(days=1)).strftime("%Y-%m-%d")
    idx = TambonIndex(load_json(os.path.join(args.static, "tambons.geojson")))
    props = {it[5]["tc"]: it[5] for it in idx.items}

    # observed rain: our log, plus ThaiWater history for the Hat Yai gauges if an endpoint answers
    latest = load_json(args.latest, {}) or {}
    hy = [g for g in latest.get("rain_gauges", []) if (props.get(g.get("tc")) or {}).get("a") == "หาดใหญ่"]
    ids = [g["k"].split(":")[1] for g in hy][:25]
    probe, extra = probe_rain_history(cfg["thaiwater_base"], ids, args.start, end) if ids else (["ไม่พบรายชื่อสถานีวัดฝน"], [])
    tc_of = {g["k"].split(":")[1]: g["tc"] for g in hy}
    for r in extra:
        r["tc"] = tc_of.get(r.pop("_id"))
    obs, covered = observed(args.rain_log, idx, "หาดใหญ่", extra)
    sub = probe_subhourly(cfg["thaiwater_base"])

    fc = {}
    notes = []
    for kind in ("dayahead", "latest"):
        fc[kind], n = forecast_series(kind, args.start, end)
        notes += n

    days = []
    d = datetime.strptime(args.start, "%Y-%m-%d")
    while d.strftime("%Y-%m-%d") <= end:
        key = d.strftime("%Y-%m-%d")
        o = obs.get(key)
        if key in covered or key in REPORTED:
            row = {"date": key, "obs_max": o[0] if o else 0, "obs_time": o[1] if o else None, "obs_gauge": o[2] if o else None,
                   "heavy": bool(o and o[0] >= HEAVY) or key in REPORTED, "reported": REPORTED.get(key)}
            for kind in fc:
                for var in ("rain", "cape"):
                    vals = []
                    for m in MODELS:
                        s = fc[kind].get((m, var), {})
                        # afternoon–evening window, when Hat Yai cloudbursts happen
                        hrs = [(t, v) for t, v in s.items() if t[:10] == key and (11 if var == "rain" else 6) <= int(t[11:13]) <= 23]
                        if hrs:
                            t, v = max(hrs, key=lambda x: x[1])
                            vals.append((v, t[11:16], m))
                    if vals:
                        v, t, m = max(vals)
                        row[f"{kind}_{var}"] = round(v, 1)
                        row[f"{kind}_{var}_time"] = t
                        row[f"{kind}_{var}_model"] = m
            days.append(row)
        d += timedelta(days=1)

    def score(kind, var, thr):
        k = f"{kind}_{var}"
        rows = [r for r in days if k in r]
        hit = sum(1 for r in rows if r["heavy"] and r[k] >= thr)
        miss = sum(1 for r in rows if r["heavy"] and r[k] < thr)
        fa = sum(1 for r in rows if not r["heavy"] and r[k] >= thr)
        cn = sum(1 for r in rows if not r["heavy"] and r[k] < thr)
        return {"kind": kind, "var": var, "thr": thr, "days": len(rows), "hit": hit, "miss": miss, "false_alarm": fa, "quiet": cn,
                "pod": round(hit / (hit + miss), 2) if hit + miss else None, "far": round(fa / (hit + fa), 2) if hit + fa else None}
    scores = [score(k, "rain", t) for k in fc for t in P_THR] + [score(k, "cape", t) for k in fc for t in CAPE_THR]
    # combined: model rain ≥5 and CAPE ≥2000 on the same day
    for kind in fc:
        rows = [r for r in days if f"{kind}_rain" in r and f"{kind}_cape" in r]
        sig = lambda r: r[f"{kind}_rain"] >= 5 and r[f"{kind}_cape"] >= 2000  # noqa: E731
        hit = sum(1 for r in rows if r["heavy"] and sig(r)); miss = sum(1 for r in rows if r["heavy"] and not sig(r))
        fa = sum(1 for r in rows if not r["heavy"] and sig(r)); cn = len(rows) - hit - miss - fa
        scores.append({"kind": kind, "var": "rain≥5 & cape≥2000", "thr": None, "days": len(rows), "hit": hit, "miss": miss, "false_alarm": fa,
                       "quiet": cn, "pod": round(hit / (hit + miss), 2) if hit + miss else None, "far": round(fa / (hit + fa), 2) if hit + fa else None})

    out = {"generated_at": datetime.now(ICT).strftime("%Y-%m-%d %H:%M"), "start": args.start, "end": end, "heavy_mm_h": HEAVY,
           "points": POINTS, "models": MODELS, "days": days, "scores": scores, "notes": notes, "probe_history": probe, "probe_subhourly": sub}
    save_json(args.out, out)

    kname = {"dayahead": "ล่วงหน้า 1 วัน", "latest": "รอบล่าสุด (≈0–6 ชม.)"}
    md = [f"## ทดสอบพยากรณ์ฝนหนักล่วงหน้า อ.หาดใหญ่ {args.start} ถึง {end}", "",
          f"ฝนหนัก = มีสถานีใดในอำเภอหาดใหญ่วัดได้ ≥ {HEAVY} มม./ชม. · ใช้ได้ {len(days)} วันที่มีข้อมูลฝนจริง "
          f"(วันฝนหนัก {sum(1 for r in days if r['heavy'])} วัน)", "",
          "### ผลรายวันที่มีฝนหนัก หรือพยากรณ์ส่งสัญญาณแรง", "",
          "| วันที่ | ฝนจริงสูงสุด (มม./ชม.) | พยากรณ์ล่วงหน้า 1 วัน (มม./ชม.) | CAPE ล่วงหน้า 1 วัน | พยากรณ์รอบล่าสุด (มม./ชม.) | CAPE รอบล่าสุด |",
          "|---|---|---|---|---|---|"]
    for r in days:
        show = r["heavy"] or any(r.get(f"{k}_rain", 0) >= 10 for k in fc)
        if show:
            obs_txt = r["reported"] + " (ไม่มีตัวเลขในบันทึก)" if r["reported"] and not r["obs_max"] else f"{r['obs_max']:.0f} {r['obs_time'] or ''} {r['obs_gauge'] or ''}"
            md.append(f"| {r['date']}{' ⚠️' if r['heavy'] else ''} | {obs_txt} | "
                      f"{r.get('dayahead_rain', '-')} {r.get('dayahead_rain_time', '')} | {r.get('dayahead_cape', '-')} | "
                      f"{r.get('latest_rain', '-')} {r.get('latest_rain_time', '')} | {r.get('latest_cape', '-')} |")
    md += ["", "### คะแนนรายสัญญาณ", "", "| พยากรณ์ | สัญญาณ | จับได้ | พลาด | เตือนผิด | วันเงียบถูก | POD | FAR |", "|---|---|---|---|---|---|---|---|"]
    for s in scores:
        md.append(f"| {kname[s['kind']]} | {s['var']}{' ≥ ' + str(s['thr']) if s['thr'] else ''} | {s['hit']} | {s['miss']} | {s['false_alarm']} | {s['quiet']} | {s['pod']} | {s['far']} |")
    md += ["", "POD = สัดส่วนวันฝนหนักที่จับได้ · FAR = สัดส่วนสัญญาณที่เตือนผิด", "",
           "### แหล่งข้อมูลฝนย้อนหลังจาก สสน.", ""] + [f"- {x}" for x in probe] + \
          ["", "### ข้อมูลฝนถี่กว่ารายชั่วโมง", ""] + [f"- {x}" for x in sub]
    if notes:
        md += ["", "### เรียกข้อมูลไม่สำเร็จ", ""] + [f"- {x}" for x in notes]
    summary("\n".join(md))


if __name__ == "__main__":
    main()
