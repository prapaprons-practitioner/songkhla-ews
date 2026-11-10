"""ตัวติดตามรายวันช่วงเฝ้าระวัง (เช่น 10–30 พ.ย. 2569): ฝนพยากรณ์ vs ฝนจริง และระดับน้ำสถานีหลัก
เทียบกับเส้นทางน้ำท่วม พ.ย. 2568 แล้วบอกว่าสถานการณ์กำลังไปทางไหน

  ก. ท่วมขัง/น้ำหลากเป็นจุดไม่กี่ชั่วโมง  : ฝนหนัก ≥ 30 มม./ชม. หรือการ์ดฝนหนักในเมืองขึ้นระดับ
  ข. น้ำหลากจากเขาคอหงส์เข้าเมือง          : X.174 ห่างตลิ่ง ≤ 1 ม. หรือฝน 24 ชม. ฝั่งคอหงส์/หาดใหญ่ ≥ 150 มม.
  ค. ท่วมลึกและนานแบบปี 2568              : สถานีต้นน้ำ/คลองหลัก (สะเดา X.173A X.90 X.44) ห่างตลิ่ง ≤ 1 ม.
เกณฑ์ตั้งจากการวิเคราะห์เหตุการณ์ พ.ย. 2568 เป็นค่าเบื้องต้น ใช้ดูทิศทาง ไม่ใช่ประกาศเตือนภัย

วันฝน = 07:00 น. ถึง 07:00 น. วันถัดไป (แบบกรมอุตุนิยมวิทยา)
- พยากรณ์ของวัน D ล็อกที่รอบแรกตั้งแต่ 07:00 น. ของวัน D
- ฝนจริงของวัน D = มากที่สุดระหว่าง (ก) ค่า "ฝน 24 ชม." ตอน 07:00 น. ของวัน D+1 และ (ข) ผลรวมฝนรายชั่วโมงในบันทึกฝน
"""
import csv
import glob
import math
import os
from datetime import datetime, timedelta

from common import ICT, iso, norm_code, parse_iso

RANK = {None: 0, "ก": 1, "ข": 2, "ค": 3}


def _km(a, b, c, d):
    return math.hypot((a - c) * 111.0, (b - d) * 111.0 * math.cos(math.radians((a + c) / 2)))


def _fc_window(fc_a, start, end):
    """Rain per model summed over [start, end) from the live Open-Meteo hourly series."""
    times = fc_a.get("times", [])
    out = {}
    for m, vals in (fc_a.get("models") or {}).items():
        tot, n = 0.0, 0
        for t, v in zip(times, vals or []):
            dt = datetime.fromisoformat(t).replace(tzinfo=ICT)
            if start <= dt < end and v is not None:
                tot += v
                n += 1
        if n >= 20:
            out[m] = round(tot, 1)
    if not out:
        return None
    vs = list(out.values())
    return {"mean": round(sum(vs) / len(vs), 1), "max": max(vs), "models": out}


def _hourly_rain(rain_log_dir, start, end):
    """{gauge key: (name, tc, mm)} summed from the hourly rain log (rainy hours only are logged)."""
    acc = {}
    for p in sorted(glob.glob(os.path.join(rain_log_dir, "*.csv"))):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                t = parse_iso(r.get("time"))
                if not t or not (start < t <= end):  # stamp = end of the rainy hour
                    continue
                try:
                    v = float(r.get("rain_1h") or r.get("est_1h") or 0)
                except ValueError:
                    continue
                k = r["k"]
                name, tc, tot = acc.get(k, (r.get("name"), r.get("tc"), 0.0))
                acc[k] = (name, tc, tot + v)
    return acc


def update(cfg, prev, fc, gauges, stations, hist, urban, rain_log_dir, now, tam_props):
    c = cfg.get("tracker") or {}
    if not c.get("enabled"):
        return None
    d0 = datetime.fromisoformat(c["start"]).replace(tzinfo=ICT)
    d1 = datetime.fromisoformat(c["end"]).replace(tzinfo=ICT)
    nl = now.astimezone(ICT)
    if nl < d0 - timedelta(days=1) or nl > d1 + timedelta(days=3):
        return prev
    T = prev or {}
    T.update({"window": [c["start"], c["end"]], "label": c.get("label", ""), "generated_at": iso(now),
              "areas": {k: v["name"] for k, v in c["areas"].items()}, "thresholds": c["thresholds"]})
    days = T.setdefault("days", {})
    thr = c["thresholds"]

    def in_area(g, area):
        a = c["areas"][area]
        if a.get("amphoe") and g.get("ac") == a["amphoe"]:
            return True
        if a.get("center") and g.get("lat") is not None and g.get("lon") is not None:
            return _km(g["lat"], g["lon"], a["center"][0], a["center"][1]) <= a.get("radius_km", 8)
        return False

    meta = {g["k"]: g for g in gauges or []}
    by_code = {norm_code(s.get("code")): s for s in stations or [] if s.get("code")}
    T["stations"] = {}
    for code in c["stations"]:
        s = by_code.get(norm_code(code))
        if s:
            T["stations"][code] = {"name": (s.get("name") or "").strip(), "k": s["k"], "id": s.get("id"), "bank": s.get("bank"),
                                   "tc": s.get("tc"), "role": c["station_roles"].get(code, "")}

    d = d0
    while d <= min(d1, nl):
        key = d.strftime("%Y-%m-%d")
        rec = days.setdefault(key, {})
        a, b = d.replace(hour=7), d.replace(hour=7) + timedelta(days=1)
        # forecast: locked at the first run from 07:00 of that day (earlier runs may still show it as provisional)
        if fc and not rec.get("fc_locked"):
            f = {area: _fc_window((fc.get("amphoes") or {}).get(ar["forecast_amphoe"], {}), a, b) for area, ar in c["areas"].items()}
            if any(f.values()):
                rec["fc"] = f
                rec["fc_issued"] = iso(now)
                rec["fc_locked"] = nl >= a
        # observed rain over the rain day, updated until the day is over plus 3 h
        if nl >= a and not rec.get("obs_final"):
            # gauges flagged as unconfirmed (one gauge pouring while its neighbours stay dry) are left out of the day's rain
            sus = set(rec.get("suspect", [])) | ({g["k"] for g in gauges or [] if g.get("suspect")} if nl < b + timedelta(hours=3) else set())
            rec["suspect"] = sorted(sus)
            hourly = {k: v for k, v in _hourly_rain(rain_log_dir, a, min(b, now)).items() if k not in sus}
            snap = {}
            if b <= now <= b + timedelta(hours=3):  # the 24-h totals read around 07:00 next day cover the whole rain day
                snap = {g["k"]: g.get("r24") for g in gauges or [] if g.get("r24") is not None}
            obs = {}
            for area in c["areas"]:
                vals = []
                for k, (name, tc, mm) in hourly.items():
                    g = meta.get(k) or {"k": k, "name": name, "tc": tc, "ac": (tam_props.get(tc) or {}).get("ac")}
                    if in_area(g, area):
                        vals.append((max(mm, snap.get(k) or 0), g.get("name") or name))
                for k, v in snap.items():
                    g = meta.get(k)
                    if g and in_area(g, area) and k not in hourly and k not in sus:
                        vals.append((v, g.get("name")))
                vals.sort(key=lambda x: -x[0])
                obs[area] = {"max": round(vals[0][0], 1), "max_gauge": vals[0][1], "third": round(vals[min(2, len(vals) - 1)][0], 1),
                             "n_rainy": len([v for v in vals if v[0] >= 1])} if vals else {"max": 0, "n_rainy": 0}
            rec["obs"] = obs
            rec["obs_until"] = iso(min(b, now))
            if now >= b + timedelta(hours=3):
                rec["obs_final"] = True
        # station levels over the calendar day, relative to the bank
        lv = rec.setdefault("levels", {})
        for code, st in T["stations"].items():
            if st.get("bank") is None:
                continue
            pts = [(parse_iso(t), v) for t, v in (hist or {}).get(st["k"], []) if v is not None]
            pts = [(t, v) for t, v in pts if t and d <= t.astimezone(ICT) < d + timedelta(days=1)]
            if pts:
                t, v = max(pts, key=lambda p: p[1])
                old = lv.get(code)
                rel = round(v - st["bank"], 2)
                if not old or rel >= old["max_rel"]:
                    lv[code] = {"max_rel": rel, "max_time": iso(t)}
        d += timedelta(days=1)

    # what the models say for the next rain days (not locked; changes every run)
    T["next"] = []
    base = nl.replace(hour=7, minute=0, second=0, microsecond=0) - (timedelta(days=1) if nl.hour < 7 else timedelta(0))
    for i in range(3):
        a = base + timedelta(days=i)
        T["next"].append({"date": a.strftime("%Y-%m-%d"), "fc": {area: _fc_window((fc or {}).get("amphoes", {}).get(ar["forecast_amphoe"], {}), a, a + timedelta(days=1))
                                                                  for area, ar in c["areas"].items()}})
    # where things stand right now
    sig = []
    st_now = {}
    for code, st in T["stations"].items():
        s = by_code.get(norm_code(code))
        if s and s.get("level") is not None and st.get("bank") is not None and not s.get("stale"):
            rel = round(s["level"] - st["bank"], 2)
            st_now[code] = {"rel": rel, "time": s.get("time"), "slope": s.get("slope")}
            if rel >= -thr["near_bank_m"]:
                sc = "ค" if code in c["scenario_c_stations"] else "ข" if code in c["scenario_b_stations"] else None
                if sc:
                    sig.append({"s": sc, "text": f"{code} {st['name']} ห่างตลิ่ง {abs(rel):.2f} ม." if rel < 0 else f"{code} {st['name']} ล้นตลิ่ง {rel:.2f} ม."})
    for area, ar in c["areas"].items():
        g24 = [g for g in gauges or [] if in_area(g, area) and g.get("r24") is not None and not g.get("suspect")]
        if g24:
            top = max(g24, key=lambda g: g["r24"])
            if top["r24"] >= thr["rain24_b"]:
                sig.append({"s": "ข", "text": f"ฝน 24 ชม. {ar['name']} {top['r24']:.0f} มม. ({top['name']})"})
        g1 = [g for g in gauges or [] if in_area(g, area) and (g.get("i1") or 0) >= thr["heavy_mm_h"] and not g.get("suspect")]
        for g in sorted(g1, key=lambda g: -g["i1"])[:2]:
            sig.append({"s": "ก", "text": f"ฝนหนัก {g['i1']:.0f} มม./ชม. ที่ {g['name']} ({ar['name']})"})
    for u in urban or []:
        if (u.get("lv") or 0) >= 1:
            sig.append({"s": "ก", "text": f"ฝนหนักใน{u['name']} ({'เตือนภัย' if u['lv'] >= 2 else 'เฝ้าระวัง'})"})
    scen = max((x["s"] for x in sig), key=lambda s: RANK[s], default=None)
    T["now"] = {"scenario": scen, "signals": sorted(sig, key=lambda x: -RANK[x["s"]]), "levels": st_now, "at": iso(now)}
    key = nl.strftime("%Y-%m-%d")
    if key in days:
        rec = days[key]
        if RANK[scen] > RANK[rec.get("scenario")]:
            rec["scenario"] = scen
            rec["scenario_at"] = iso(now)
            rec["signals"] = [x["text"] for x in sig if x["s"] == scen][:4]
    return T
