#!/usr/bin/env python3
"""ดึงถนนสายหลักจาก OpenStreetMap (Overpass API) แล้วตัดเป็นช่วงตามตำบล

รันครั้งเดียว (หรือปีละครั้ง) ผลลัพธ์: site/data/static/roads.geojson
แต่ละช่วงถนนมีรหัสตำบล (tc) เพื่อให้หน้าเว็บระบายสีตามระดับเตือนภัยของตำบลนั้น
"""
import argparse
import os
import sys
import urllib.parse

from common import TambonIndex, http_get, load_json, save_json, summary

HIGHWAYS = "motorway|trunk|primary|secondary"
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def dp(points, tol):
    """Douglas–Peucker simplification (degrees)."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [points[0], points[-1]]
    return dp(points[:idx + 1], tol)[:-1] + dp(points[idx:], tol)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", default="site/data/static")
    ap.add_argument("--input", default=None, help="ไฟล์ผล Overpass ที่ดาวน์โหลดไว้แล้ว (ใช้ทดสอบ)")
    ap.add_argument("--tol", type=float, default=0.0004)
    args = ap.parse_args()
    tam = load_json(os.path.join(args.static, "tambons.geojson"))
    idx = TambonIndex(tam)
    xs = [c[0] for f in tam["features"] for poly in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]) for c in poly[0]]
    ys = [c[1] for f in tam["features"] for poly in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]) for c in poly[0]]
    bbox = f"{min(ys):.3f},{min(xs):.3f},{max(ys):.3f},{max(xs):.3f}"
    if args.input:
        data = load_json(args.input)
    else:
        q = f'[out:json][timeout:300];way["highway"~"^({HIGHWAYS})$"]({bbox});out tags geom;'
        data, err = None, None
        for s in SERVERS:
            try:
                data = http_get(s, timeout=360, retries=2, data=urllib.parse.urlencode({"data": q}).encode())
                break
            except Exception as e:  # noqa: BLE001
                err = e
        if data is None:
            print(f"::error::ดึงข้อมูลถนนไม่สำเร็จ: {err}")
            sys.exit(1)
    feats, n_ways = [], 0
    for w in data.get("elements", []):
        if w.get("type") != "way" or not w.get("geometry"):
            continue
        n_ways += 1
        tags = w.get("tags", {})
        ref = tags.get("ref", "")
        name = tags.get("name:th") or tags.get("name") or ""
        pts = [(round(g["lon"], 5), round(g["lat"], 5)) for g in w["geometry"]]
        # split the way where the tambon changes
        cur, seg = None, []
        for x, y in pts:
            p = idx.locate(x, y)
            tc = p["tc"] if p else None
            if seg and tc != cur:
                seg.append((x, y))  # keep the line continuous across the boundary
                if cur and len(seg) >= 2:
                    feats.append((cur, ref, name, tags.get("highway"), seg))
                seg = [(x, y)]
            else:
                seg.append((x, y))
            cur = tc
        if cur and len(seg) >= 2:
            feats.append((cur, ref, name, tags.get("highway"), seg))
    out = {"type": "FeatureCollection", "source": "© OpenStreetMap contributors (ODbL), Overpass API", "features": []}
    for tc, ref, name, hw, seg in feats:
        coords = [[round(x, 4), round(y, 4)] for x, y in dp(seg, args.tol)]
        out["features"].append({"type": "Feature", "properties": {"tc": tc, "ref": ref, "name": name, "hw": hw},
                                "geometry": {"type": "LineString", "coordinates": coords}})
    save_json(os.path.join(args.static, "roads.geojson"), out)
    size = os.path.getsize(os.path.join(args.static, "roads.geojson")) / 1e6
    summary(f"## ถนนจาก OpenStreetMap\n\n- ถนน {n_ways} เส้น → {len(out['features'])} ช่วงตามตำบล · ขนาดไฟล์ {size:.1f} MB")


if __name__ == "__main__":
    main()
