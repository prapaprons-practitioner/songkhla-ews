#!/usr/bin/env python3
"""รันกติกาเตือนภัยปัจจุบันซ้ำกับข้อมูลระดับน้ำย้อนหลังในสาขา archive (เช่น น้ำท่วม พ.ย. 2568)

ใช้โค้ดคำนวณชุดเดียวกับระบบจริง (update.py) ทีละ 30 นาที แล้วเทียบกับบันทึกเหตุน้ำท่วมจริง
ข้อจำกัด: ไม่มีฝนรายชั่วโมงย้อนหลังในข้อมูลเปิด จึงทดสอบได้เฉพาะกติกาจากระดับน้ำ (สถานี ห่วงโซ่ต้นน้ำ-ปลายน้ำ การคงระดับ)
ผลลัพธ์: site/data/static/replay.json (หน้าเว็บแสดงในแท็บ "ช่องว่างข้อมูล")
"""
import argparse
import bisect
import csv
import os
import sys
import types
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flood_reports as FR  # noqa: E402
import update as U  # noqa: E402
from common import ICT, TambonIndex, iso, load_json, norm_code, save_json, summary  # noqa: E402


def load_station_series(archive):
    meta, series = {}, {}
    with open(os.path.join(archive, "stations.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            meta[r["id"]] = r
    for sid in meta:
        p = os.path.join(archive, "levels", f"{sid}.csv")
        if not os.path.exists(p):
            continue
        pts = []
        with open(p, encoding="utf-8") as f:
            next(f, None)
            for line in f:  # "2025-11-20 00:10,0.88,..." — sliced by hand: strptime is far too slow for a year of 10-min data
                d, _, rest = line.partition(",")
                v = rest.split(",", 1)[0]
                try:
                    pts.append((datetime(int(d[0:4]), int(d[5:7]), int(d[8:10]), int(d[11:13]), int(d[14:16]), tzinfo=ICT), float(v)))
                except (ValueError, IndexError):
                    continue
        pts.sort()
        if pts:
            series[sid] = pts
    return meta, series


def f_or_none(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--static", default="site/data/static")
    ap.add_argument("--archive", default="archive")
    ap.add_argument("--reports", default="reports/flood_reports.csv")
    ap.add_argument("--start", default="2025-11-10")
    ap.add_argument("--end", default="2025-12-05")
    ap.add_argument("--year-from", default=None, help="นับจำนวนครั้งที่เตือนทั้งปีตั้งแต่วันนี้ (ไม่ใส่ = ทั้งคลัง)")
    ap.add_argument("--until", default=None, help="หยุดรันที่วันนี้ (ไม่ใส่ = จนสุดคลัง)")
    ap.add_argument("--step-min", type=int, default=30)
    ap.add_argument("--out", default="site/data/static/replay.json")
    args = ap.parse_args()

    cfg = load_json(args.config)
    tam_geo = load_json(os.path.join(args.static, "tambons.geojson"))
    admin = load_json(os.path.join(args.static, "admin.json"))
    norms = (load_json(os.path.join(args.static, "event_analysis.json"), {}) or {}).get("norms", {})
    idx = TambonIndex(tam_geo)
    tam_props = {f["properties"]["tc"]: f["properties"] for f in tam_geo["features"]}
    meta, series = load_station_series(args.archive)
    times = {sid: [p[0] for p in pts] for sid, pts in series.items()}
    st_cfg = cfg["thresholds"]["station"]
    force_norm = {norm_code(c) for c in st_cfg.get("force_norm_stations", [])}
    force_bank = {norm_code(c) for c in st_cfg.get("force_bank_stations", [])}
    win_h = st_cfg["trend_window_h"]

    ev0 = datetime.fromisoformat(args.start).replace(tzinfo=ICT)
    ev1 = datetime.fromisoformat(args.end).replace(tzinfo=ICT) + timedelta(days=1)
    first_t = min(p[0][0] for p in series.values())
    last_t = max(p[-1][0] for p in series.values())
    y0 = datetime.fromisoformat(args.year_from).replace(tzinfo=ICT) if args.year_from else first_t.replace(hour=0, minute=0) + timedelta(days=1)
    y1 = min(last_t, datetime.fromisoformat(args.until).replace(tzinfo=ICT)) if args.until else last_t
    step = timedelta(minutes=args.step_min)

    ctx = types.SimpleNamespace(cfg=cfg, now=None, status={}, urban=[], fixtures="replay")
    prevT, alerts, log = {}, [], {"since": iso(y0), "tambons": {}}
    key_codes = {norm_code(c) for c in ["X.44", "X.90", "X.173A", "X.174", "X.240", "ONE037", "SLA003"]}
    key_first = {}
    now = y0
    n_steps = 0
    while now <= y1:
        stations = []
        for sid, pts in series.items():
            i = bisect.bisect_right(times[sid], now) - 1
            if i < 0:
                continue
            m = meta[sid]
            t_last, v = pts[i]
            j = bisect.bisect_left(times[sid], now - timedelta(hours=win_h))
            hist = [[iso(t), x] for t, x in pts[j:i + 1]]
            bank = f_or_none(m.get("bank_msl"))
            bank_note = None
            if bank is not None and (bank == 0 or v - bank > 5):
                bank, bank_note = None, "ระดับตลิ่งในข้อมูลต้นทางผิดปกติ จึงไม่นำมาใช้"
            s = {"k": f"tw:{sid}", "id": sid, "code": m["code"], "name": m["name"].strip(), "agency": m["agency"].strip(),
                 "tc": m.get("tc") or None, "level": v, "bank": bank, "bank_note": bank_note,
                 "warn": f_or_none(m.get("warning_msl")), "crit": f_or_none(m.get("critical_msl")), "thr_src": None,
                 "q": None, "sit": None, "time": iso(t_last)}
            n = norms.get(str(sid))
            code = norm_code(m["code"])
            s["norm"] = n if n and (code in force_norm or (n.get("mode") == "norm" and code not in force_bank)) else None
            s["slope"] = U.slope_m_per_h(hist, win_h)
            U.station_state(s, st_cfg, cfg["max_age_hours"], now)
            stations.append(s)
            if code in key_codes and ev0 <= now < ev1 and s["state"]:
                kf = key_first.setdefault(m["code"], {"name": s["name"], "tc": s["tc"], "bank": bank})
                for k in (1, 2, 3):
                    if s["state"] >= k and str(k) not in kf:
                        kf[str(k)] = iso(now)
                        kf[f"why{k}"] = s["why"]
        ctx.now = now
        T, A, P, chains = U.compute(ctx, tam_geo, admin, stations, [], None, None, prevT, None)
        if prevT:
            for a in U.make_alerts(ctx, T, {"tambons": prevT}, tam_props, alerts):
                alerts.append(a)
        for tc, t in T.items():
            pts = log["tambons"].setdefault(tc, [])
            if not pts or pts[-1][1] != t["lv"]:
                pts.append([iso(now), t["lv"]])
        prevT = {tc: {"lv": t["lv"], "pending_drop": t.get("pending_drop")} for tc, t in T.items()}
        now += step
        n_steps += 1

    # ---- scoring against real flood reports in the event window
    rep_txt = open(args.reports, encoding="utf-8").read() if os.path.exists(args.reports) else ""
    rep = FR.build(cfg, rep_txt, "", idx, admin, tam_props, log, ev1, start=ev0, end=ev1)
    focus = cfg.get("flood_reports", {}).get("focus_amphoes", ["TH9011", "TH9001"])

    def label(tc):
        p = tam_props.get(tc, {})
        return f"ต.{p.get('t')} อ.{p.get('a')} จ.{p.get('p')}"

    # level changes of focus tambons during the event
    timeline = {}
    for tc, pts in log["tambons"].items():
        if tam_props.get(tc, {}).get("ac") not in focus:
            continue
        ch = [[a, lv] for a, lv in pts if ev0 - timedelta(days=1) <= datetime.fromisoformat(a.replace("Z", "+00:00")) < ev1]
        if any((lv or 0) >= 1 for _, lv in ch):
            timeline[tc] = {"name": label(tc), "changes": ch}
    ev_alerts = [a for a in alerts if ev0 <= datetime.fromisoformat(a["time"].replace("Z", "+00:00")) < ev1]
    # the whole archive: how often would the water-level rules have raised a warning?
    by_month = Counter()
    by_month_focus = Counter()
    for a in alerts:
        mth = datetime.fromisoformat(a["time"].replace("Z", "+00:00")).astimezone(ICT).strftime("%Y-%m")
        by_month[mth] += 1
        if tam_props.get(a["tc"], {}).get("ac") in focus:
            by_month_focus[mth] += 1
    out = {
        "generated_at": datetime.now(ICT).strftime("%Y-%m-%d %H:%M"),
        "window": [args.start, args.end], "archive": [iso(y0), iso(y1)], "step_min": args.step_min, "steps": n_steps,
        "rules": "ระดับน้ำที่สถานี · ห่วงโซ่ต้นน้ำ-ปลายน้ำ · การคงระดับ 2 รอบ · ไม่แจ้งซ้ำใน 6 ชม. (ไม่มีกติกาฝน)",
        "stations": len(series), "key_stations": key_first,
        "alerts_event": [{k: a.get(k) for k in ("time", "tc", "name", "from", "to", "why")} for a in ev_alerts][:400],
        "alerts_event_n": len(ev_alerts),
        "alerts_event_focus_n": sum(1 for a in ev_alerts if tam_props.get(a["tc"], {}).get("ac") in focus),
        "timeline_focus": timeline,
        "reports": rep, "alerts_by_month": dict(sorted(by_month.items())), "alerts_by_month_focus": dict(sorted(by_month_focus.items())),
        "focus": focus,
    }
    save_json(args.out, out)
    sc = rep["score"]
    md = [f"## รันกติกาปัจจุบันซ้ำกับระดับน้ำ {args.start} ถึง {args.end}", "",
          f"สถานี {len(series)} แห่ง · ทุก {args.step_min} นาที · {n_steps} รอบ (ทั้งคลัง {iso(y0)[:10]} ถึง {iso(y1)[:10]})", "",
          f"- เหตุน้ำท่วมที่มีบันทึก {sc['n']} เหตุ: เตือนทัน {sc['warned']} · เฝ้าระวังเท่านั้น {sc['watch_only']} · พลาด {sc['missed']}"
          + (f" · เวลานำ (มัธยฐาน) {sc['lead_warn_median_h']} ชม." if sc.get('lead_warn_median_h') is not None else ""),
          f"- การเตือนระดับเตือนภัยขึ้นไปในช่วงเหตุการณ์: {len(ev_alerts)} ครั้ง (หาดใหญ่/เมืองสงขลา {out['alerts_event_focus_n']})", "",
          "| เวลา | สถานที่ | ผล | เวลานำ |", "|---|---|---|---|"]
    for r in rep["rows"]:
        md.append(f"| {r.get('time')} | {r.get('place') or ''} | {r['result']} | {r.get('lead_warn_h', r.get('lead_watch_h', ''))} |")
    md += ["", "### สถานีหลัก: ครั้งแรกที่ถึงแต่ละระดับ", "", "| สถานี | เฝ้าระวัง | เตือนภัย | วิกฤต |", "|---|---|---|---|"]
    for c, v in key_first.items():
        md.append(f"| {c} {v['name']} | {v.get('1', '-')} | {v.get('2', '-')} | {v.get('3', '-')} |")
    md += ["", "### จำนวนการเตือน (ระดับเตือนภัยขึ้นไป) รายเดือนทั้งคลัง", "", "| เดือน | ทุกตำบล | หาดใหญ่/เมืองสงขลา |", "|---|---|---|"]
    for mth, n in sorted(by_month.items()):
        md.append(f"| {mth} | {n} | {by_month_focus.get(mth, 0)} |")
    summary("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
