#!/usr/bin/env python3
"""เก็บระดับน้ำย้อนหลัง (สูงสุด 365 วันที่ สสน. ให้บริการ) ของทุกสถานีในพื้นที่

ควรรันอย่างน้อยเดือนละครั้ง เพราะข้อมูลที่เก่ากว่า 365 วันจะหายไปจากต้นทาง
ผลลัพธ์: <archive>/levels/<station_id>.csv และ <archive>/stations.csv
"""
import argparse
import csv
import os
import sys
import time
from datetime import timedelta

from common import (TambonIndex, find_records, fnum, http_get, load_json, now_utc, parse_local, summary, ICT)

sys.path.insert(0, os.path.dirname(__file__))
import update  # noqa: E402  (reuse the station filter)


def read_csv(path):
    rows = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[r["datetime"]] = r
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--static", default="site/data/static")
    ap.add_argument("--archive", default="archive")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--fixtures", default=None)
    args = ap.parse_args()

    ns = argparse.Namespace(config=args.config, fixtures=args.fixtures)
    ctx = update.Ctx(ns)
    idx = TambonIndex(load_json(os.path.join(args.static, "tambons.geojson")))
    props = {it[5]["tc"]: it[5] for it in idx.items}
    stations = update.get_levels(ctx, idx, {})
    os.makedirs(os.path.join(args.archive, "levels"), exist_ok=True)

    end = now_utc().astimezone(ICT)
    start = end - timedelta(days=args.days)
    ok, fail, new_rows = 0, [], 0
    first, last = None, None
    for s in stations:
        sid = s["id"]
        if sid is None:
            continue
        url = (f"{ctx.cfg['thaiwater_base']}/waterlevel_graph?station_type=tele_waterlevel&station_id={sid}"
               f"&start_date={start:%Y-%m-%d}&end_date={end:%Y-%m-%d}%2023:59")
        try:
            data = ctx.fetch(f"graph_{sid}", url, timeout=120) if args.fixtures else http_get(url, timeout=120)
        except Exception as e:  # noqa: BLE001
            fail.append(f"{s['name']} ({e})"[:120])
            continue
        pts = find_records(data, "datetime") or find_records(data, "value")
        path = os.path.join(args.archive, "levels", f"{sid}.csv")
        rows = read_csv(path)
        before = len(rows)
        for p in pts:
            t = parse_local(p.get("datetime") or p.get("date"))
            v = fnum(p.get("value"))
            if t is None or v is None:
                continue
            key = t.strftime("%Y-%m-%d %H:%M")
            rows[key] = {"datetime": key, "value": v, "discharge": fnum(p.get("discharge")) or ""}
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["datetime", "value", "discharge"])
            w.writeheader()
            for k in sorted(rows):
                w.writerow(rows[k])
        new_rows += len(rows) - before
        if rows:
            ks = sorted(rows)
            first = min(first or ks[0], ks[0])
            last = max(last or ks[-1], ks[-1])
        ok += 1
        if not args.fixtures:
            time.sleep(1.0)  # be gentle with the public server

    with open(os.path.join(args.archive, "stations.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "code", "name", "agency", "lat", "lon", "tc", "tambon", "amphoe", "province", "bank_msl", "warning_msl", "critical_msl"])
        for s in stations:
            p = props.get(s["tc"]) or {}
            w.writerow([s["id"], s["code"], s["name"], s["agency"], s["lat"], s["lon"], s["tc"] or "", p.get("t", ""), p.get("a", ""),
                        p.get("p", ""), s["bank"] if s["bank"] is not None else "", s["warn"] if s["warn"] is not None else "",
                        s["crit"] if s["crit"] is not None else ""])
    summary("\n".join([
        "## เก็บข้อมูลระดับน้ำย้อนหลัง", "",
        f"- สถานีในพื้นที่ {len(stations)} · ดึงสำเร็จ {ok} · ไม่สำเร็จ {len(fail)}",
        f"- แถวข้อมูลใหม่ {new_rows:,} · ช่วงข้อมูลที่มีในคลัง {first} ถึง {last}",
    ] + [f"  - ❌ {x}" for x in fail[:30]]))
    if ok == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
