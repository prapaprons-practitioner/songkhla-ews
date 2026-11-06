#!/usr/bin/env python3
"""เทียบพยากรณ์ล่วงหน้ากับสิ่งที่เกิดขึ้นจริง รายวัน สำหรับเหตุการณ์ในอดีต (เช่น น้ำท่วม พ.ย. 2568)

ฝั่งพยากรณ์ (Open-Meteo, 3 โมเดลเดียวกับระบบจริง ที่จุดกึ่งกลางอำเภอเดียวกับระบบจริง)
- ฝนรายวันที่พยากรณ์ไว้ล่วงหน้า 1 วัน และ 2 วัน (Previous Runs API: previous_day1 / previous_day2)
- ฝนรายวันจากรอบพยากรณ์ล่าสุด (Historical Forecast API ≈ ล่วงหน้า 0–6 ชม. มองโลกในแง่ดีกว่าการใช้งานจริง)
- CAPE สูงสุด 06:00–23:59 น. (ล่วงหน้า 1 วัน) → วันเสี่ยงฝนฟ้าคะนองรุนแรง
- ระดับเตือนจากกติกาฝนของระบบ (update.amphoe_rain) ณ 07:00 และ 19:00 น. ของแต่ละวัน
  ใช้เฉพาะพยากรณ์ที่ออกก่อนเวลานั้น: ชั่วโมงที่อยู่ข้างหน้า 0–24 ชม. ใช้ค่า previous_day1, 24–48 ชม. ใช้ previous_day2,
  48–72 ชม. ใช้ previous_day3 (ระมัดระวังกว่าของจริง เพราะใช้รอบพยากรณ์ที่เก่ากว่าที่จะมีในตอนนั้น)
ฝั่งเกิดจริง
- ฝนที่หน่วยงานหรือข่าวรายงาน (reports/rain_reported.csv) เพราะไม่มีฝนรายชั่วโมงย้อนหลังในข้อมูลเปิด
- ระดับน้ำสูงสุดรายวันเทียบตลิ่ง (สาขา archive)
- ระดับเตือนจากกติการะดับน้ำ (site/data/static/replay.json) และเหตุน้ำท่วมจริง (reports/flood_reports.csv)
ผลลัพธ์: site/data/static/event_forecast.json (หน้าเว็บแสดงในแท็บ "ช่องว่างข้อมูล")
"""
import argparse
import csv
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update as U  # noqa: E402
from common import ICT, http_get, load_json, norm_code, save_json, summary  # noqa: E402

PREV = "https://previous-runs-api.open-meteo.com/v1/forecast"
HIST = "https://historical-forecast-api.open-meteo.com/v1/forecast"
KEY_STATIONS = ["X.44", "X.90", "X.174", "X.173A", "SLA003"]


def om_get(url, params, tries=4):
    q = urllib.parse.urlencode(params, safe=",")
    last = None
    for i in range(tries):
        try:
            return http_get(f"{url}?{q}", timeout=120, retries=1)
        except Exception as e:  # noqa: BLE001 - rate limits come back as errors; wait and retry
            last = e
            time.sleep(15 * (i + 1))
    raise RuntimeError(str(last)[:200])


def fetch(amphoes, models, start, end, notes, getter=om_get):
    """{ac: {"times": [...], (var, model): [values]}} for every amphoe centroid."""
    out = {a["ac"]: {} for a in amphoes}
    lat = ",".join(str(a["lat"]) for a in amphoes)
    lon = ",".join(str(a["lon"]) for a in amphoes)
    jobs = [(PREV, v, m) for m in models for v in ("precipitation_previous_day1", "precipitation_previous_day2",
                                                    "precipitation_previous_day3", "cape_previous_day1")]
    jobs += [(HIST, "precipitation", m) for m in models] + [(HIST, "soil_moisture_3_to_9cm", None)]
    for url, var, m in jobs:
        p = {"latitude": lat, "longitude": lon, "hourly": var, "start_date": start, "end_date": end, "timezone": "Asia/Bangkok"}
        if m:
            p["models"] = m
        try:
            data = getter(url, p)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{var} {m or ''}: ดึงไม่สำเร็จ ({str(e)[:100]})")
            continue
        locs = data if isinstance(data, list) else [data]
        for a, loc in zip(amphoes, locs):
            h = (loc or {}).get("hourly") or {}
            vals = h.get(var) or next((v for k, v in h.items() if k.startswith(var)), None)
            if vals is None:
                notes.append(f"{var} {m or ''}: ไม่มีค่าในช่วงนี้")
                continue
            out[a["ac"]]["times"] = h.get("time", [])
            out[a["ac"]][(var, m)] = vals
        time.sleep(1.5)
    return out


def at(series, times):
    idx = {t: i for i, t in enumerate(times)}
    return lambda t: (series[idx[t]] if t in idx and idx[t] < len(series) else None)


def day_sum(times, vals, d0):
    """Rain from 07:00 of day d0 to 07:00 the next day (the Thai Meteorological Department's rain day)."""
    if not vals:
        return None
    a, b = d0.replace(hour=7), d0.replace(hour=7) + timedelta(days=1)
    xs = [v for t, v in zip(times, vals) if v is not None and a <= datetime.fromisoformat(t).replace(tzinfo=ICT) < b]
    return round(sum(xs), 1) if len(xs) >= 20 else None


def rule_at(cfg, D, models, check):
    """Run the live rain rule as it would have run at `check`, using only forecasts issued earlier."""
    times = D.get("times", [])
    get = {(k, m): at(D.get((k, m)) or [], times) for k in ("precipitation_previous_day1", "precipitation_previous_day2",
                                                            "precipitation_previous_day3") for m in models}
    hours, mod = [], {m: [] for m in models}
    for i in range(-24, 72):
        t = check + timedelta(hours=i)
        key = t.strftime("%Y-%m-%dT%H:00")
        lead = 1 if i < 24 else 2 if i < 48 else 3
        hours.append(key)
        for m in models:
            mod[m].append(get[(f"precipitation_previous_day{lead}", m)](key))
    fc_a = {"times": hours, "models": {m: v for m, v in mod.items() if any(x is not None for x in v)},
            "soil_times": times, "soil": D.get(("soil_moisture_3_to_9cm", None)) or []}
    if not fc_a["models"]:
        return None
    thr = cfg["thresholds"]
    r = U.amphoe_rain(fc_a, [], check, thr["rain"], thr["soil_wet_m3m3"])
    return {"lv": r.get("lv"), "n24": r.get("n24"), "n24_max": r.get("n24_max"), "acc": r.get("acc"),
            "p24": r.get("p24_model"), "soil": r.get("soil"), "why": r.get("why")}


def daily_levels(archive, start, end):
    meta = {}
    with open(os.path.join(archive, "stations.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            meta[r["id"]] = r
    out = {}
    for code in KEY_STATIONS:
        sid = next((k for k, m in meta.items() if norm_code(m["code"]) == norm_code(code)), None)
        p = os.path.join(archive, "levels", f"{sid}.csv") if sid else None
        if not p or not os.path.exists(p):
            continue
        bank = float(meta[sid]["bank_msl"]) if meta[sid].get("bank_msl") else None
        days = {}
        with open(p, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                d, _, rest = line.partition(",")
                if not (start <= d[:10] <= end):
                    continue
                try:
                    v = float(rest.split(",", 1)[0])
                except ValueError:
                    continue
                k = d[:10]
                if k not in days or v > days[k][0]:
                    days[k] = (v, d[11:16])
        out[code] = {"name": meta[sid]["name"].strip(), "amphoe": meta[sid]["amphoe"], "bank": bank,
                     "days": {k: {"max": round(v, 2), "time": t, "above_bank": round(v - bank, 2) if bank is not None else None}
                              for k, (v, t) in sorted(days.items())}}
    return out


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def main(getter=om_get):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--static", default="site/data/static")
    ap.add_argument("--archive", default="archive")
    ap.add_argument("--start", default="2025-11-15")
    ap.add_argument("--end", default="2025-11-30")
    ap.add_argument("--amphoes", default="TH9011,TH9010,TH9001", help="รหัสอำเภอ คั่นด้วยจุลภาค (ค่าแรกคืออำเภอหลัก)")
    ap.add_argument("--rain-reported", default="reports/rain_reported.csv")
    ap.add_argument("--flood-reports", default="reports/flood_reports.csv")
    ap.add_argument("--out", default="site/data/static/event_forecast.json")
    args = ap.parse_args()
    cfg = load_json(args.config)
    admin = load_json(os.path.join(args.static, "admin.json"))
    models = cfg["open_meteo"]["models"]
    acs = args.amphoes.split(",")
    amph = [a for a in admin["amphoes"] if a["ac"] in acs]
    amph.sort(key=lambda a: acs.index(a["ac"]))
    d0 = datetime.fromisoformat(args.start).replace(tzinfo=ICT)
    d1 = datetime.fromisoformat(args.end).replace(tzinfo=ICT)
    # fetch 3 days before (past 24 h of the rule) and 4 days after (72 h look-ahead + the last rain day)
    f0, f1 = (d0 - timedelta(days=3)).strftime("%Y-%m-%d"), (d1 + timedelta(days=4)).strftime("%Y-%m-%d")
    notes = []
    data = fetch(amph, models, f0, f1, notes, getter)
    replay = load_json(os.path.join(args.static, "replay.json"), {}) or {}
    levels = daily_levels(args.archive, args.start, args.end) if os.path.isdir(args.archive) else {}
    rain_rep, floods = read_csv(args.rain_reported), read_csv(args.flood_reports)
    storm_thr = cfg.get("storm_risk", {}).get("cape_threshold", 3000)

    def replay_daymax(tc, day):
        ch = ((replay.get("timeline_focus") or {}).get(tc) or {}).get("changes", [])
        a = datetime.fromisoformat(day).replace(tzinfo=ICT)
        b = a + timedelta(days=1)
        state, top = None, None
        for t, lv in ch:
            ts = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if ts <= a:
                state = lv
            elif ts < b:
                top = lv if top is None else max(top, lv or 0)
        cand = [x for x in (state, top) if x is not None]
        return max(cand) if cand else None

    city_tc = next((tc for tc, v in (replay.get("timeline_focus") or {}).items() if v["name"].startswith("ต.หาดใหญ่ ")), "TH901101")
    rows = {}
    for a in amph:
        D = data.get(a["ac"], {})
        times = D.get("times", [])
        out = []
        d = d0
        while d <= d1:
            key = d.strftime("%Y-%m-%d")
            row = {"date": key, "fc": {}}
            for m in models:
                row["fc"][m] = {"d1": day_sum(times, D.get(("precipitation_previous_day1", m)), d),
                                "d2": day_sum(times, D.get(("precipitation_previous_day2", m)), d),
                                "latest": day_sum(times, D.get(("precipitation", m)), d)}
            capes = []
            for m in models:
                cs = D.get(("cape_previous_day1", m)) or []
                capes += [v for t, v in zip(times, cs) if v is not None and t[:10] == key and 6 <= int(t[11:13]) <= 23]
            row["cape"] = round(max(capes)) if capes else None
            row["storm_flag"] = row["cape"] is not None and row["cape"] >= storm_thr
            row["rule_07"] = rule_at(cfg, D, models, d.replace(hour=7))
            row["rule_19"] = rule_at(cfg, D, models, d.replace(hour=19))
            row["rain_reported"] = [r for r in rain_rep if r.get("amphoe") == a["a"] and r.get("date") == key]
            out.append(row)
            d += timedelta(days=1)
        rows[a["ac"]] = {"name": a["a"], "lat": a["lat"], "lon": a["lon"], "days": out}
    main_a = amph[0]["a"] if amph else ""
    days = [r["date"] for r in rows.get(acs[0], {}).get("days", [])]
    actual = {k: {"levels": {c: v["days"].get(k) for c, v in levels.items()},
                  "level_rule_city": replay_daymax(city_tc, k),
                  "floods": [{"time": f.get("time"), "place": f.get("place"), "tambon": f.get("tambon"), "depth_cm": f.get("depth_cm"), "source": f.get("source")}
                             for f in floods if (f.get("time") or "")[:10] == k and f.get("amphoe") == main_a]}
              for k in days}
    res = {"generated_at": datetime.now(ICT).strftime("%Y-%m-%d %H:%M"), "window": [args.start, args.end], "models": models,
           "amphoes": rows, "main": acs[0], "actual": actual,
           "stations": {c: {"name": v["name"], "amphoe": v["amphoe"], "bank": v["bank"]} for c, v in levels.items()},
           "rain_reported_all": rain_rep, "storm_threshold": storm_thr,
           "thresholds": cfg["thresholds"]["rain"], "notes": notes[:40]}
    save_json(args.out, res)
    # summary
    md = [f"## พยากรณ์ล่วงหน้า vs เกิดจริง: อ.{main_a} {args.start} ถึง {args.end}", "",
          "| วันที่ | ฝนพยากรณ์ล่วงหน้า 1 วัน (มม./วัน) " + " / ".join(models) + " | ล่วงหน้า 2 วัน (เฉลี่ย) | CAPE | ระดับจากกติกาฝน 07:00 | ฝนจริงที่รายงาน | X.44 เทียบตลิ่ง |",
          "|---|---|---|---|---|---|---|"]
    for r in rows.get(acs[0], {}).get("days", []):
        f1_ = " / ".join("-" if r["fc"][m]["d1"] is None else f"{r['fc'][m]['d1']:.0f}" for m in models)
        d2 = [r["fc"][m]["d2"] for m in models if r["fc"][m]["d2"] is not None]
        rr = "; ".join(f"{x.get('place')} {x.get('mm')} มม." for x in r["rain_reported"]) or "-"
        x44 = (actual[r["date"]]["levels"].get("X.44") or {}).get("above_bank")
        lv = (r["rule_07"] or {}).get("lv")
        md.append(f"| {r['date']} | {f1_} | {sum(d2) / len(d2):.0f} |" if d2 else f"| {r['date']} | {f1_} | - |")
        md[-1] += f" {r['cape'] if r['cape'] is not None else '-'}{' ⚠' if r['storm_flag'] else ''} | {U.LEVELS[lv] if lv is not None else '-'} | {rr} | {x44 if x44 is not None else '-'} |"
    if notes:
        md += ["", "### หมายเหตุการดึงข้อมูล", ""] + [f"- {n}" for n in notes[:40]]
    summary("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
