#!/usr/bin/env python3
"""วิเคราะห์เหตุการณ์น้ำท่วมจากข้อมูลย้อนหลังในคลัง (เช่น พ.ย. 2568)

คำนวณ: ระดับสูงสุดและเวลา, ช่วงเวลาที่น้ำเกินตลิ่ง, อัตราน้ำขึ้นสูงสุด
และเวลาเดินทางของน้ำระหว่างสถานีในห่วงโซ่ (เทียบเวลายอดน้ำ + ความสัมพันธ์ไขว้)
ผลลัพธ์: site/data/static/event_analysis.json (หน้าเว็บแสดงในแท็บ "ช่องว่างข้อมูล")
"""
import argparse
import csv
import os
from datetime import datetime, timedelta

from common import ICT, load_json, norm_code, save_json, summary


def load_series(path, start, end):
    """Hourly mean series {datetime_hour: value} inside [start, end]."""
    buckets = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["datetime"], "%Y-%m-%d %H:%M").replace(tzinfo=ICT)
                v = float(r["value"])
            except (ValueError, KeyError):
                continue
            if start <= t <= end:
                buckets.setdefault(t.replace(minute=0), []).append(v)
    return {k: sum(v) / len(v) for k, v in sorted(buckets.items())}


def stats(series, bank):
    if not series:
        return None
    tpk, vpk = max(series.items(), key=lambda kv: kv[1])
    ks = sorted(series)
    rise = 0.0
    for a, b in zip(ks, ks[1:]):
        dt = (b - a).total_seconds() / 3600
        if 0 < dt <= 3:
            rise = max(rise, (series[b] - series[a]) / dt)
    out = {"peak": round(vpk, 2), "peak_time": tpk.strftime("%Y-%m-%d %H:%M"), "max_rise_m_per_h": round(rise, 2),
           "n_hours": len(series)}
    if bank is not None:
        above = [k for k in ks if series[k] >= bank]
        out.update(bank=bank, peak_above_bank=round(vpk - bank, 2), hours_above_bank=len(above),
                   first_above_bank=above[0].strftime("%Y-%m-%d %H:%M") if above else None)
    return out


def xcorr_lag(a, b, max_lag=48):
    """Lag (h) of b behind a that best matches hour-to-hour changes."""
    def diffs(s):
        ks = sorted(s)
        return {k2: s[k2] - s[k1] for k1, k2 in zip(ks, ks[1:]) if (k2 - k1) == timedelta(hours=1)}
    da, db = diffs(a), diffs(b)
    best = (None, -2)
    for lag in range(0, max_lag + 1):
        pairs = [(da[k], db[k + timedelta(hours=lag)]) for k in da if k + timedelta(hours=lag) in db]
        if len(pairs) < 24:
            continue
        xs, ys = zip(*pairs)
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sx = sum((x - mx) ** 2 for x in xs) ** 0.5
        sy = sum((y - my) ** 2 for y in ys) ** 0.5
        if sx == 0 or sy == 0:
            continue
        r = sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy)
        if r > best[1]:
            best = (lag, r)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--archive", default="archive")
    ap.add_argument("--out", default="site/data/static/event_analysis.json")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    cfg = load_json(args.config)
    start = datetime.fromisoformat(args.start or cfg["archive"]["event_start"]).replace(tzinfo=ICT)
    end = datetime.fromisoformat(args.end or cfg["archive"]["event_end"]).replace(tzinfo=ICT) + timedelta(days=1)

    meta = {}
    with open(os.path.join(args.archive, "stations.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            meta[r["id"]] = r
    series, rows = {}, []
    for sid, m in meta.items():
        path = os.path.join(args.archive, "levels", f"{sid}.csv")
        if not os.path.exists(path):
            continue
        s = load_series(path, start, end)
        if not s:
            continue
        series[sid] = s
        bank = float(m["bank_msl"]) if m.get("bank_msl") else None
        st = stats(s, bank)
        rows.append({"id": sid, "code": m["code"], "name": m["name"], "tambon": m["tambon"], "amphoe": m["amphoe"],
                     "province": m["province"], **st})
    rows.sort(key=lambda r: -(r.get("peak_above_bank") if r.get("peak_above_bank") is not None else -99))

    chains = []
    for ch in cfg.get("chains", []):
        ids = []
        for cs in ch["stations"]:
            sid = next((k for k, m in meta.items() if norm_code(m["code"]) == norm_code(cs["match"])
                        or norm_code(cs["match"]) in norm_code(m["name"])), None)
            ids.append((cs["label"], sid))
        legs = []
        for (la, a), (lb, b) in zip(ids, ids[1:]):
            leg = {"from": la, "to": lb, "found": bool(a and b and a in series and b in series)}
            if leg["found"]:
                pa = max(series[a].items(), key=lambda kv: kv[1])[0]
                pb = max(series[b].items(), key=lambda kv: kv[1])[0]
                lag, r = xcorr_lag(series[a], series[b])
                leg.update(peak_lag_h=round((pb - pa).total_seconds() / 3600, 1), xcorr_lag_h=lag,
                           xcorr_r=round(r, 2) if lag is not None else None)
            legs.append(leg)
        chains.append({"name": ch["name"], "legs": legs})

    out = {"window": [start.strftime("%Y-%m-%d"), (end - timedelta(days=1)).strftime("%Y-%m-%d")],
           "generated_at": datetime.now(ICT).strftime("%Y-%m-%d %H:%M"), "stations": rows, "chains": chains}
    save_json(args.out, out, compact=False)

    md = [f"## วิเคราะห์เหตุการณ์ {out['window'][0]} ถึง {out['window'][1]}", "",
          "### เวลาเดินทางของน้ำในห่วงโซ่", "", "| ช่วง | ยอดน้ำห่างกัน (ชม.) | จากความสัมพันธ์ไขว้ (ชม., r) |", "|---|---|---|"]
    for c in chains:
        for g in c["legs"]:
            md.append(f"| {g['from']} → {g['to']} | {g.get('peak_lag_h', 'ไม่พบข้อมูล')} | "
                      f"{g.get('xcorr_lag_h', '-')} ({g.get('xcorr_r', '-')}) |")
    md += ["", "### สถานีที่น้ำเกินตลิ่งมากที่สุด", "", "| สถานี | อำเภอ | ยอดน้ำเหนือตลิ่ง (ม.) | เวลา | ชม.ที่เกินตลิ่ง | ขึ้นเร็วสุด (ม./ชม.) |", "|---|---|---|---|---|---|"]
    for r in rows[:25]:
        md.append(f"| {r['name']} {r['code']} | {r['amphoe']} | {r.get('peak_above_bank', '-')} | {r['peak_time']} | "
                  f"{r.get('hours_above_bank', '-')} | {r['max_rise_m_per_h']} |")
    summary("\n".join(md))


if __name__ == "__main__":
    main()
