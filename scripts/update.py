#!/usr/bin/env python3
"""ดึงข้อมูลน้ำแบบเรียลไทม์ แล้วคำนวณระดับเตือนภัยรายตำบล (ใช้ Python มาตรฐานเท่านั้น)

ระดับ: 0 ปกติ · 1 เฝ้าระวัง · 2 เตือนภัย · 3 วิกฤต
"""
import argparse
import os
import sys
from collections import Counter
from datetime import timedelta

from common import (ICT, TambonIndex, find_records, fnum, http_get, iso, load_json, norm_code,
                    norm_name, now_utc, parse_iso, parse_local, save_json, summary, th)

LEVELS = ["ปกติ", "เฝ้าระวัง", "เตือนภัย", "วิกฤต"]


class Ctx:
    def __init__(self, args):
        self.args = args
        self.cfg = load_json(args.config)
        self.now = now_utc()
        self.status = {}
        self.fixtures = args.fixtures

    def fetch(self, name, url, as_text=False, timeout=150):
        if self.fixtures:
            p = os.path.join(self.fixtures, name + (".txt" if as_text else ".json"))
            if not os.path.exists(p):
                raise RuntimeError(f"ไม่มีไฟล์ทดสอบ {p}")
            with open(p, encoding="utf-8") as f:
                txt = f.read()
            return txt if as_text else __import__("json").loads(txt)
        return http_get(url, timeout=timeout, as_text=as_text)

    def run(self, name, label, fn):
        try:
            res = fn()
            n = len(res) if hasattr(res, "__len__") else None
            self.status[name] = {"label": label, "ok": True, "n": n, "at": iso(now_utc())}
            return res
        except Exception as e:  # noqa: BLE001 - a failed source must never stop the others
            msg = str(e)[:300]
            self.status[name] = {"label": label, "ok": False, "error": msg, "at": iso(now_utc())}
            print(f"::warning::{label}: {msg}")
            return None


# ---------------------------------------------------------------- sources

def get_thresholds(ctx):
    """HII FEWS station thresholds (CSV; column names detected at run time)."""
    import csv
    import io
    txt = ctx.fetch("fews_hii_waterlevel", ctx.cfg["fews_base"] + "/metadata/hii_waterlevel.csv", as_text=True, timeout=60)
    rows = list(csv.reader(io.StringIO(txt)))
    if not rows:
        return {}
    head = [h.strip().lower() for h in rows[0]]

    def col(*keys):
        for i, h in enumerate(head):
            if any(k in h for k in keys):
                return i
        return None
    ic = col("code", "station", "id")
    cols = {k: col(k) for k in ("alarm", "warning", "critical")}
    out = {}
    for r in rows[1:]:
        if ic is None or ic >= len(r):
            continue
        rec = {k: fnum(r[i]) for k, i in cols.items() if i is not None and i < len(r)}
        if any(v is not None for v in rec.values()):
            out[norm_code(r[ic])] = rec
    return out


def get_levels(ctx, idx, fews_thr):
    data = ctx.fetch("tw_waterlevel", ctx.cfg["thaiwater_base"] + "/waterlevel_load")
    provs = {norm_name(p) for p in ctx.cfg["provinces"]}
    out = []
    for r in find_records(data, "station"):
        st = r.get("station") or {}
        geo = r.get("geocode") or {}
        lat, lon = fnum(st.get("tele_station_lat")), fnum(st.get("tele_station_long"))
        # the agency's own tambon first: river gauges often sit on a tambon boundary
        tam = idx.by_names(th(geo.get("province_name")), th(geo.get("amphoe_name")), th(geo.get("tumbon_name"))) or idx.locate(lon, lat)
        if not tam and norm_name(th(geo.get("province_name"))) not in provs:
            continue
        code = st.get("tele_station_oldcode") or ""
        banks = [fnum(st.get(k)) for k in ("min_bank", "left_bank", "right_bank")]
        bank = banks[0] if banks[0] is not None else min([b for b in banks[1:] if b is not None], default=None)
        level = fnum(r.get("waterlevel_msl"))
        bank_note = None
        if bank is not None and (bank == 0 or (level is not None and level - bank > 5)):
            bank, bank_note = None, "ระดับตลิ่งในข้อมูลต้นทางผิดปกติ จึงไม่นำมาใช้"
        warn, crit = fnum(st.get("warning_level_m")), fnum(st.get("critical_level_m"))
        thr = fews_thr.get(norm_code(code)) if code else None
        thr_src = None
        if thr:
            if warn is None and thr.get("warning") is not None:
                warn, thr_src = thr["warning"], "FEWS"
            if crit is None and thr.get("critical") is not None:
                crit, thr_src = thr["critical"], "FEWS"
        t = parse_local(r.get("waterlevel_datetime"))
        out.append({
            "k": f"tw:{st.get('id')}", "id": st.get("id"), "code": code,
            "name": th(st.get("tele_station_name")), "agency": th((r.get("agency") or {}).get("agency_name")),
            "lat": lat, "lon": lon,
            "tc": tam["tc"] if tam else None,
            "geo": " ".join(x for x in (th(geo.get("tumbon_name")), th(geo.get("amphoe_name")), th(geo.get("province_name"))) if x),
            "level": level, "bank": bank, "bank_note": bank_note, "warn": warn, "crit": crit, "thr_src": thr_src,
            "q": fnum(r.get("discharge")), "sit": r.get("situation_level"),
            "time": iso(t),
        })
    return out


def get_rain(ctx, idx):
    data = ctx.fetch("tw_rain24", ctx.cfg["thaiwater_base"] + "/rain_24h", timeout=240)
    provs = {norm_name(p) for p in ctx.cfg["provinces"]}
    out = []
    for r in find_records(data, "station"):
        st = r.get("station") or {}
        geo = r.get("geocode") or {}
        lat, lon = fnum(st.get("tele_station_lat")), fnum(st.get("tele_station_long"))
        tam = idx.by_names(th(geo.get("province_name")), th(geo.get("amphoe_name")), th(geo.get("tumbon_name"))) or idx.locate(lon, lat)
        if not tam and norm_name(th(geo.get("province_name"))) not in provs:
            continue
        out.append({
            "k": f"twr:{st.get('id')}", "name": th(st.get("tele_station_name")), "lat": lat, "lon": lon,
            "tc": tam["tc"] if tam else None, "ac": tam["ac"] if tam else None,
            "r24": fnum(r.get("rain_24h")), "r1": fnum(r.get("rain_1h")),
            "time": iso(parse_local(r.get("rainfall_datetime") or r.get("rain_datetime"))),
        })
    return out


def get_dams(ctx):
    """HII large-dam table (daily). Field names are discovered at run time; keep numeric fields only."""
    data = ctx.fetch("tw_dam", ctx.cfg["thaiwater_base"].replace("/public", "/analyst") + "/dam", timeout=120)
    names = [d["name_match"] for d in ctx.cfg.get("dams", [])]
    out = {}

    def flat(o, pre=""):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from flat(v, f"{pre}{k}.")
        elif not isinstance(o, list):
            yield pre[:-1], o

    def walk(o):
        if isinstance(o, dict):
            text = " ".join(str(v) for _, v in flat(o) if isinstance(v, str))
            hit = next((n for n in names if n in text), None)
            if hit and any(isinstance(v, (int, float)) for _, v in flat(o)):
                rec = {k: v for k, v in flat(o) if isinstance(v, (int, float, str)) and len(str(v)) < 40}
                out.setdefault(hit, rec)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def dam_fields(rec):
    """Pick storage %, storage, inflow, release and date out of an unknown record."""
    pick = {}
    for k, v in (rec or {}).items():
        kl = k.lower()
        if isinstance(v, str) and "date" in kl and "date" not in pick:
            pick["date"] = v
        if not isinstance(v, (int, float)):
            continue
        if "percent" in kl and "storage" in kl and "uses" not in kl:
            pick.setdefault("storage_pct", v)
        elif "storage" in kl and "percent" not in kl and "uses" not in kl and "normal" not in kl and "max" not in kl and "min" not in kl:
            pick.setdefault("storage", v)
        elif "inflow" in kl and "percent" not in kl:
            pick.setdefault("inflow", v)
        elif "release" in kl and "percent" not in kl:
            pick.setdefault("release", v)
        elif "spill" in kl:
            pick.setdefault("spill", v)
    return pick


def rain_intensity(gauges, prev_rh, now, keep_h=6):
    """Keep a short rain history per gauge and estimate rain in the last 1 h and 3 h.
    Uses HII rain_1h when present; otherwise the rise of the rolling 24-h total (a lower bound)."""
    rh = {k: v for k, v in (prev_rh or {}).items()}
    for g in gauges or []:
        if not g["time"] or g["r24"] is None:
            continue
        pts = rh.setdefault(g["k"], [])
        if not pts or pts[-1][0] != g["time"]:
            pts.append([g["time"], g["r24"], g.get("r1")])
    cutoff = now - timedelta(hours=keep_h)
    for k in list(rh):
        rh[k] = [p for p in rh[k] if (parse_iso(p[0]) or now) >= cutoff]
        if not rh[k]:
            del rh[k]
    for g in gauges or []:
        pts = rh.get(g["k"], [])
        t = parse_iso(g["time"]) if g["time"] else None
        g["i1"] = g["i3"] = None
        if not t or g["r24"] is None:
            continue

        def r24_ago(h):
            cand = [(abs((parse_iso(p[0]) - (t - timedelta(hours=h))).total_seconds()), p[1]) for p in pts if p[1] is not None]
            cand = [c for c in cand if c[0] <= 40 * 60]
            return min(cand)[1] if cand else None
        d1, d3 = r24_ago(1), r24_ago(3)
        est1 = max(0.0, g["r24"] - d1) if d1 is not None else None
        est3 = max(0.0, g["r24"] - d3) if d3 is not None else None
        g["i1"] = g["r1"] if g.get("r1") is not None else est1
        g["i1_src"] = "สสน. 1 ชม." if g.get("r1") is not None else ("ประมาณจากฝนสะสม" if est1 is not None else None)
        vals = [v for v in (est3, g["i1"]) if v is not None]
        g["i3"] = round(max(vals), 1) if vals else None
        if g["i1"] is not None:
            g["i1"] = round(g["i1"], 1)
    return rh


def get_forecast(ctx, amphoes, prev_fc):
    """Open-Meteo hourly rain (3 models) + soil moisture at each amphoe centroid."""
    om = ctx.cfg["open_meteo"]
    if prev_fc and not ctx.fixtures:
        t = parse_iso(prev_fc.get("fetched_at"))
        if t and ctx.now - t < timedelta(minutes=om["min_interval_minutes"]) and set(prev_fc.get("amphoes", {})) == {a["ac"] for a in amphoes}:
            prev_fc["reused"] = True
            return prev_fc
    res = {}
    bs = om.get("batch_size", 40)
    for b in range(0, len(amphoes), bs):
        batch = amphoes[b:b + bs]
        lats = ",".join(str(a["lat"]) for a in batch)
        lons = ",".join(str(a["lon"]) for a in batch)
        base = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&timezone=Asia%2FBangkok&past_days=1&forecast_days=4"
        rain = ctx.fetch(f"om_rain_{b // bs}", base + "&hourly=precipitation&models=" + ",".join(om["models"]))
        rain = rain if isinstance(rain, list) else [rain]
        try:
            soil = ctx.fetch(f"om_soil_{b // bs}", base + "&hourly=soil_moisture_3_to_9cm")
            soil = soil if isinstance(soil, list) else [soil]
        except Exception as e:  # noqa: BLE001
            print(f"::warning::ความชื้นดิน: {e}")
            soil = [None] * len(batch)
        for a, r, s in zip(batch, rain, soil):
            h = r.get("hourly", {})
            res[a["ac"]] = {
                "times": h.get("time", []),
                "models": {m: h.get(f"precipitation_{m}") or ([] if len(om["models"]) > 1 else h.get("precipitation", [])) for m in om["models"]},
                "soil": (s or {}).get("hourly", {}).get("soil_moisture_3_to_9cm", []),
                "soil_times": (s or {}).get("hourly", {}).get("time", []),
            }
    return {"fetched_at": iso(ctx.now), "models": om["models"], "amphoes": res}


def get_flashflood(ctx, tambons):
    """HII FEWS flash-flood list: only tambons at risk are listed. Match by names in the line."""
    txt = ctx.fetch("fews_flashflood", ctx.cfg["fews_base"] + "/flashflood/flashflood_report.txt", as_text=True, timeout=60)
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    delim = "\t" if any("\t" in ln for ln in lines[:5]) else ("," if any("," in ln for ln in lines[:5]) else None)
    head, ffpi_i = None, None
    for ln in lines[:10]:
        if "ffpi" in ln.lower():
            head = [c.strip().lower() for c in (ln.split(delim) if delim else ln.split())]
            ffpi_i = next((i for i, c in enumerate(head) if "ffpi" in c), None)
            break
    out = {}
    for ln in lines:
        cells = [c.strip() for c in (ln.split(delim) if delim else ln.split())]
        have = Counter(norm_name(c) for c in cells)
        for t in tambons:
            p = t["properties"]
            need = Counter([norm_name(p["t"]), norm_name(p["a"]), norm_name(p["p"])])
            if all(have[k] >= v for k, v in need.items()):  # a tambon named like its amphoe needs both cells
                ffpi = fnum(cells[ffpi_i]) if ffpi_i is not None and ffpi_i < len(cells) else None
                out[p["tc"]] = {"ffpi": ffpi, "raw": ln.strip()[:240]}
    return out


# ---------------------------------------------------------------- calculations

def merge_history(prev_hist, stations, keep_h, now):
    hist = {k: v for k, v in (prev_hist or {}).items()}
    for s in stations:
        if s["level"] is None or not s["time"]:
            continue
        pts = hist.setdefault(s["k"], [])
        if not pts or pts[-1][0] != s["time"]:
            pts.append([s["time"], s["level"]])
    cutoff = now - timedelta(hours=keep_h)
    for k in list(hist):
        hist[k] = sorted([p for p in hist[k] if (parse_iso(p[0]) or now) >= cutoff], key=lambda p: p[0])
        if not hist[k]:
            del hist[k]
    return hist


def slope_m_per_h(points, window_h):
    if len(points) < 3:
        return None
    t_end = parse_iso(points[-1][0])
    pts = [(parse_iso(t), v) for t, v in points if v is not None and parse_iso(t) and (t_end - parse_iso(t)) <= timedelta(hours=window_h)]
    if len(pts) < 3 or (pts[-1][0] - pts[0][0]) < timedelta(minutes=50):
        return None
    xs = [(t - pts[0][0]).total_seconds() / 3600 for t, _ in pts]
    ys = [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def norm_levels(n, bank=None, near=0.5):
    """Thresholds for gauges whose level is not well judged by distance to bank: normal water near the
    bank (lake / low bank) or a daily swing (tide, dam releases). Compare with the gauge's own normal
    high (p99 of a year without the flood) and the 2025 flood peak. Where the bank is meaningfully
    above the normal high, overtopping it is still critical and nearing it still a warning."""
    p99, pk = n["p99"], n.get("event_peak")
    span = (pk - p99) if pk is not None and pk - p99 >= 0.3 else 0.9
    warn, crit = p99 + span / 3, p99 + 2 * span / 3
    if bank is not None and bank > p99 + 0.1:
        crit = min(crit, bank)
        warn = min(warn, max(p99 + 0.05, bank - near))
    return p99, round(warn, 2), round(crit, 2)


def station_state_norm(s, thr):
    n = s["norm"]
    watch, warn, crit = norm_levels(n, s["bank"], thr["near_bank_m"])
    L, sl = s["level"], s.get("slope")
    st = 3 if L >= crit else 2 if L >= warn else 1 if L > watch else 0
    if s["bank"] is not None:
        s["gap"] = round(s["bank"] - L, 2)
    why = [f"สถานีนี้ระดับน้ำปกติอยู่ใกล้ตลิ่งหรือขึ้นลงทุกวัน (น้ำทะเล ทะเลสาบ หรือการปล่อยน้ำจากเขื่อน) จึงเทียบกับระดับของตัวเอง: "
           f"ตอนนี้ {L:.2f} ม.รทก. · สูงปกติ {watch:.2f} · เตือนภัย {warn:.2f} · วิกฤต {crit:.2f}"]
    if sl is not None:
        if sl > 0.005:
            why.append(f"กำลังขึ้น {sl:.2f} ม./ชม.")
        elif sl < -0.005:
            why.append(f"กำลังลด {abs(sl):.2f} ม./ชม.")
        # tides rise every few hours: only project when the water is already above its normal high
        if sl > 0.005 and watch < L < warn:
            eta = (warn - L) / sl
            s["eta_h"] = round(eta, 1)
            if eta <= thr["eta_warning_h"]:
                st = max(st, 2)
            if eta <= thr["eta_watch_h"]:
                st = max(st, 1)
                why.append(f"ถ้าขึ้นต่อในอัตรานี้ จะถึงระดับเตือนภัยใน ~{eta:.0f} ชม.")
    s["state"], s["why"] = st, " · ".join(why)


def station_state(s, thr, max_age_h, now):
    t = parse_iso(s["time"])
    s["age_h"] = round((now - t).total_seconds() / 3600, 1) if t else None
    s["stale"] = s["age_h"] is None or s["age_h"] > max_age_h
    s["state"], s["why"], s["eta_h"] = None, "", None
    if s["stale"] or s["level"] is None:
        s["why"] = "ข้อมูลไม่เป็นปัจจุบัน" if s["level"] is not None else "ไม่มีค่าระดับน้ำ"
        # a gauge that goes silent while the water is high must not turn "grey"
        # (Nov 2025: X.90 stopped reporting for ~23 h right at the peak)
        if s.get("norm") and s["level"] is not None and s["age_h"] is not None and s["age_h"] <= 24:
            if s["level"] >= norm_levels(s["norm"], s["bank"], thr["near_bank_m"])[1]:
                s["state"] = 2
                s["why"] = f"หยุดส่งข้อมูลขณะน้ำสูง: ค่าล่าสุด {s['level']:.2f} ม.รทก. เมื่อ {s['age_h']:.0f} ชม.ก่อน"
        elif (s["level"] is not None and s["bank"] is not None and s["age_h"] is not None
                and s["age_h"] <= 24 and s["bank"] - s["level"] <= thr["near_bank_m"]):
            gap = s["bank"] - s["level"]
            s["state"] = 2
            s["why"] = (f"หยุดส่งข้อมูลขณะน้ำสูง: ค่าล่าสุด{'สูงกว่า' if gap < 0 else 'ต่ำกว่า'}ตลิ่ง {abs(gap):.2f} ม. "
                        f"เมื่อ {s['age_h']:.0f} ชม.ก่อน ให้ถือว่ายังเสี่ยงจนกว่าจะยืนยันได้")
        return
    if s.get("norm"):
        return station_state_norm(s, thr)
    L, B, W, C = s["level"], s["bank"], s["warn"], s["crit"]
    st, why = 0, []
    if B is not None:
        gap = B - L
        s["gap"] = round(gap, 2)
        why.append(f"{'สูงกว่า' if gap < 0 else 'ต่ำกว่า'}ตลิ่ง {abs(gap):.2f} ม.")
        if gap <= 0:
            st = 3
        elif gap <= thr["near_bank_m"]:
            rising = s.get("slope") is not None and s["slope"] > 0.005
            st = 2 if rising else 1
            if not rising:
                why.append("ใกล้ตลิ่ง แต่ยังไม่พบว่ากำลังขึ้น")
    else:
        why.append(s.get("bank_note") or "ไม่มีระดับตลิ่ง")
    if C is not None and L >= C:
        st = 3
    elif W is not None and L >= W:
        st = max(st, 2)
        why.append("ถึงระดับเตือนภัยของสถานี")
    if s.get("sit") == 4 and thr.get("use_hii_class", True):
        st = max(st, 1)
        why.append("สสน. จัดเป็น \"น้ำมาก\" (70–100% ของตลิ่ง)")
    sl = s.get("slope")
    if sl is not None:
        if sl > 0.005:
            why.append(f"กำลังขึ้น {sl:.2f} ม./ชม.")
        elif sl < -0.005:
            why.append(f"กำลังลด {abs(sl):.2f} ม./ชม.")
        if sl >= thr["rise_watch_m_per_h"]:
            st = max(st, 1)
        if B is not None and L < B and sl > 0.005:
            eta = (B - L) / sl
            s["eta_h"] = round(eta, 1)
            if eta <= thr["eta_warning_h"]:
                st = max(st, 2)
            elif eta <= thr["eta_watch_h"]:
                st = max(st, 1)
            if eta <= thr["eta_watch_h"]:
                why.append(f"ถ้าขึ้นต่อในอัตรานี้ จะถึงตลิ่งใน ~{eta:.0f} ชม.")
    s["state"], s["why"] = st, " · ".join(why)


def window_sum(times, vals, start, end):
    tot, n = 0.0, 0
    for t, v in zip(times, vals or []):
        dt = parse_local(t)
        if dt and start <= dt < end and v is not None:
            tot += v
            n += 1
    return round(tot, 1) if n else None


def amphoe_rain(fc_a, gauges, now, rthr, soil_wet):
    hour = now.astimezone(ICT).replace(minute=0, second=0, microsecond=0)
    times = fc_a.get("times", [])
    per = {}
    for m, vals in fc_a.get("models", {}).items():
        n24 = window_sum(times, vals, hour, hour + timedelta(hours=24))
        if n24 is None:
            continue
        per[m] = {"n24": n24, "n48": window_sum(times, vals, hour, hour + timedelta(hours=48)),
                  "n72": window_sum(times, vals, hour, hour + timedelta(hours=72)),
                  "p24": window_sum(times, vals, hour - timedelta(hours=24), hour)}
    out = {"models": per}
    if per:
        mean = lambda k: round(sum(v[k] or 0 for v in per.values()) / len(per), 1)  # noqa: E731
        out.update(n24=mean("n24"), n48=mean("n48"), n72=mean("n72"), n24_max=max(v["n24"] for v in per.values()),
                   p24_model=mean("p24"))
        series = []
        for i in range(72):
            t0 = hour + timedelta(hours=i)
            vals = [window_sum(times, v, t0, t0 + timedelta(hours=1)) for v in fc_a["models"].values()]
            vals = [x for x in vals if x is not None]
            series.append(round(sum(vals) / len(vals), 1) if vals else None)
        out["h72"] = series
    fresh = sorted((g["r24"] for g in gauges if g["r24"] is not None), reverse=True)
    # 3rd-highest gauge: one very local downpour should not lift the whole district
    out["p24_obs"] = fresh[min(2, len(fresh) - 1)] if fresh else None
    out["p24_obs_max"] = fresh[0] if fresh else None
    out["n_gauges"] = len(fresh)
    soil = None
    st, sv = fc_a.get("soil_times", []), fc_a.get("soil", [])
    for t, v in zip(st, sv):
        dt = parse_local(t)
        if dt and dt >= hour and v is not None:
            soil = v
            break
    out["soil"] = soil
    if "n24" not in out:
        out["lv"], out["why"] = None, "ไม่มีฝนพยากรณ์"
        return out
    past = out["p24_obs"] if out["p24_obs"] is not None else out["p24_model"]
    out["acc"] = round((past or 0) + out["n48"], 1)
    lv, why = 0, []
    for k, lvl in (("next24_critical", 3), ("next24_warning", 2), ("next24_watch", 1)):
        if out["n24"] >= rthr[k]:
            lv = max(lv, lvl)
            break
    for k, lvl in (("acc_critical", 3), ("acc_warning", 2), ("acc_watch", 1)):
        if out["acc"] >= rthr[k]:
            lv = max(lv, lvl)
            break
    if out["n24_max"] >= rthr["next24_warning"]:
        lv = max(lv, 1)
    if lv == 1 and soil is not None and soil >= soil_wet and out["n24"] >= rthr["next24_watch"]:
        lv = 2
        why.append("ดินอิ่มน้ำ")
    obs = ""
    if out["p24_obs"] is not None:
        obs = (f" (ฝนที่ผ่านมาใช้ค่าสถานีอันดับ 3 จาก {len(fresh)} สถานี = {out['p24_obs']:.0f} มม. สูงสุด {out['p24_obs_max']:.0f})"
               if len(fresh) >= 3 else f" (ฝนที่ผ่านมาจากสถานีวัดฝน {out['p24_obs']:.0f} มม.)")
    why.insert(0, f"ฝนพยากรณ์ 24 ชม. {out['n24']:.0f} มม. (สูงสุดในบางโมเดล {out['n24_max']:.0f}) · ฝนสะสม 24 ชม.ที่ผ่านมา + 48 ชม.ข้างหน้า {out['acc']:.0f} มม.{obs}")
    out["lv"], out["why"] = lv, " · ".join(why)
    return out


def bump(t, lv, src, text):
    if lv is None:
        return
    t["reasons"].append({"src": src, "lv": lv, "text": text})
    if lv > (t["lv"] or 0):
        t["lv"] = lv


def compute(ctx, tam_geo, admin, stations, gauges, fc, ff, prev_tambons=None, dams=None):
    cfg = ctx.cfg
    thr = cfg["thresholds"]
    T = {}
    for f in tam_geo["features"]:
        p = f["properties"]
        T[p["tc"]] = {"lv": 0, "reasons": [], "st": [], "rg": [], "ac": p["ac"], "pc": p["pc"]}
    # rain per amphoe
    A = {}
    for a in admin["amphoes"]:
        g = [x for x in (gauges or []) if x["ac"] == a["ac"] and x["r24"] is not None
             and x["time"] and (ctx.now - parse_iso(x["time"])) <= timedelta(hours=cfg["max_age_hours"])]
        fa = (fc or {}).get("amphoes", {}).get(a["ac"], {})
        A[a["ac"]] = {"rain": amphoe_rain(fa, g, ctx.now, thr["rain"], thr["soil_wet_m3m3"])}
    for tc, t in T.items():
        r = A[t["ac"]]["rain"]
        if r.get("lv"):
            bump(t, r["lv"], "rain", r["why"])
        t["has_fc"] = r.get("lv") is not None
    # stations
    for s in stations or []:
        if s["tc"] in T:
            T[s["tc"]]["st"].append(s["k"])
            if s["state"]:
                bump(T[s["tc"]], s["state"], "station", f"สถานี {s['name']}{' (' + s['code'] + ')' if s['code'] else ''}: {s['why']}")
    for g in gauges or []:
        if g["tc"] in T:
            T[g["tc"]]["rg"].append(g["k"])
    # HII flash-flood list
    for tc, v in (ff or {}).items():
        if tc in T:
            bump(T[tc], thr["flashflood_level"], "flashflood", "สสน. ระบุเป็นพื้นที่เสี่ยงน้ำท่วมฉับพลัน/น้ำป่า" + (f" (FFPI {v['ffpi']})" if v.get("ffpi") is not None else ""))
    # upstream → downstream chains
    by_code = {}
    for s in stations or []:
        for key in {norm_code(s["code"]), norm_code(s["name"].split(" ")[0])}:
            if key:
                by_code.setdefault(key, s)
    chains = []
    for ch in cfg.get("chains", []):
        rows = []
        for i, cs in enumerate(ch["stations"]):
            s = by_code.get(norm_code(cs["match"]))
            if not s:  # fall back to "code appears in the station name"
                s = next((x for x in stations or [] if norm_code(cs["match"]) in norm_code(x["name"]) or norm_code(cs["match"]) == norm_code(x["code"])), None)
            rows.append({"label": cs["label"], "match": cs["match"], "found": bool(s), "k": s["k"] if s else None,
                         "state": s["state"] if s else None, "level": s["level"] if s else None, "bank": s["bank"] if s else None,
                         "eta_h": s["eta_h"] if s else None, "stale": s["stale"] if s else None,
                         "gap": s.get("gap") if s else None,
                         "lag_h_to_next": cs.get("lag_h_to_next")})
        trig, msgs, etas = None, [], []
        for i, r in enumerate(rows[:-1]):
            if r["state"] and r["state"] >= 2:
                lags = [x["lag_h_to_next"] for x in rows[i:-1]]
                eta = sum(lags) if all(v is not None for v in lags) else None
                far_above = r["gap"] is not None and r["gap"] <= -ch.get("critical_above_bank_m", 99)
                lv = 3 if far_above else 2 if r["state"] >= 3 else 1
                what = (f"สูงกว่าตลิ่ง {-r['gap']:.1f} ม." if far_above else "ล้นตลิ่งแล้ว" if r["state"] >= 3
                        else "หยุดส่งข้อมูลขณะน้ำสูง" if r["stale"] else "ใกล้ตลิ่ง")
                msgs.append(f"{r['label']} {what}"
                            + (f" (น้ำอาจถึงปลายทางในราว {eta:.0f} ชม.)" if eta is not None else " (ยังไม่ทราบเวลาเดินทางของน้ำ)"))
                if eta is not None:
                    etas.append(eta)
                trig = {"lv": max(lv, trig["lv"] if trig else 0)}
        if trig:
            trig["eta_h"] = min(etas) if etas else None
            trig["msg"] = "ต้นน้ำ: " + " · ".join(msgs)
        if trig:
            for tc, t in T.items():
                p = next((f["properties"] for f in tam_geo["features"] if f["properties"]["tc"] == tc), None)
                if p and p["a"] == ch["downstream_amphoe"] and p["t"] in ch["downstream_tambons"]:
                    bump(t, trig["lv"], "chain", f"{ch['name']}: {trig['msg']}")
        chains.append({"name": ch["name"], "stations": rows, "trigger": trig})
    # heavy rain inside towns: drains and small canals fill long before the main river moves
    ur = cfg.get("urban_rain", {})
    urban = []
    props = {f["properties"]["tc"]: f["properties"] for f in tam_geo["features"]}
    for z in ur.get("zones", []):
        ztc = [tc for tc, p in props.items() if p["a"] == z["amphoe"] and p["t"] in z["tambons"]]
        g = [x for x in gauges or [] if x["tc"] in ztc and x.get("time")
             and (ctx.now - parse_iso(x["time"])) <= timedelta(minutes=ur.get("max_age_minutes", 90))]
        g1 = max((x for x in g if x.get("i1") is not None), key=lambda x: x["i1"], default=None)
        g3 = max((x for x in g if x.get("i3") is not None), key=lambda x: x["i3"], default=None)
        i1, i3 = (g1 or {}).get("i1") or 0, (g3 or {}).get("i3") or 0
        lv = 2 if (i1 >= ur["warning_1h"] or i3 >= ur["warning_3h"]) else 1 if (i1 >= ur["watch_1h"] or i3 >= ur["watch_3h"]) else 0
        row = {"name": z["name"], "lv": lv, "i1": i1, "i3": i3, "n_gauges": len(g),
               "g1": (g1 or {}).get("name"), "g3": (g3 or {}).get("name"), "src": (g1 or {}).get("i1_src")}
        urban.append(row)
        if lv:
            for tc in ztc:
                by1 = i1 >= ur["watch_1h"]
                what = (f"{row['g1']} วัดได้ {i1:.0f} มม. ใน 1 ชม." if by1 else f"{row['g3']} วัดได้ {i3:.0f} มม. ใน 3 ชม.")
                est = " (ค่าประมาณจากฝนสะสม อาจต่ำกว่าจริง)" if row["src"] != "สสน. 1 ชม." else ""
                bump(T[tc], lv, "urban_rain", f"ฝนหนักใน{z['name']}: {what}{est} · คู/คลองระบายในเมืองอาจล้นแม้คลองสายหลักยังต่ำ")
    ctx.urban = urban
    # dam tailwater above its normal high → downstream districts on watch
    for d in dams or []:
        tw = d.get("tailwater_state")
        if tw and tw >= 1:
            for tc, p in props.items():
                if p["a"] in d.get("downstream_amphoes", []):
                    bump(T[tc], 1, "dam", f"ระดับน้ำท้าย{d['name']}สูงกว่าปกติ อาจเพิ่มการระบายน้ำ")
    # hysteresis: a level may rise at once but drops only after two lower runs in a row
    for tc, t in T.items():
        pv = (prev_tambons or {}).get(tc) or {}
        plv = pv.get("lv")
        if t["lv"] is not None and plv is not None and t["lv"] < plv and not pv.get("pending_drop"):
            t["reasons"].append({"src": "hold", "lv": plv, "text": f"คงระดับ{LEVELS[plv]}ไว้อีก 1 รอบเพื่อยืนยันว่าสถานการณ์ลดลงจริง (ค่าล่าสุดอยู่ระดับ{LEVELS[t['lv']]})"})
            t["lv"], t["pending_drop"] = plv, True
    # no forecast and no fresh station → "no data" rather than a false "normal"
    fresh_tc = {s["tc"] for s in stations or [] if s.get("state") is not None}
    for tc, t in T.items():
        if not t["has_fc"] and tc not in fresh_tc and not t["reasons"]:
            t["lv"] = None
    # roll-ups
    def counts(lvs):
        c = [0, 0, 0, 0]
        for v in lvs:
            c[v or 0] += 1
        return c
    for ac, a in A.items():
        lvs = [t["lv"] for t in T.values() if t["ac"] == ac]
        a["lv"], a["n"] = max((v for v in lvs if v is not None), default=None), counts(lvs)
    P = {}
    for p in admin["provinces"]:
        lvs = [t["lv"] for t in T.values() if t["pc"] == p["pc"]]
        P[p["pc"]] = {"lv": max((v for v in lvs if v is not None), default=None), "n": counts(lvs)}
    for t in T.values():
        t["reasons"].sort(key=lambda r: -r["lv"])
        del t["ac"], t["pc"]
    return T, A, P, chains


def gaps(ctx, T, stations, gauges, chains):
    st = stations or []
    fresh = [s for s in st if not s["stale"]]
    return {
        "tambons": len(T),
        "tambons_with_station": sum(1 for t in T.values() if t["st"]),
        "tambons_with_fresh_station": len({s["tc"] for s in fresh if s["tc"]}),
        "tambons_with_gauge": sum(1 for t in T.values() if t["rg"]),
        "tambons_forecast_only": sum(1 for t in T.values() if not t["st"] and t["has_fc"]),
        "stations": len(st), "stations_fresh": len(fresh),
        "stations_stale": [{"k": s["k"], "name": s["name"], "age_h": s["age_h"]} for s in st if s["stale"]][:80],
        "stations_no_bank": [{"k": s["k"], "name": s["name"]} for s in st if s["bank"] is None][:80],
        "stations_norm_mode": [{"k": s["k"], "name": s["name"], "code": s["code"],
                                "near_frac": s["norm"].get("near_bank_frac")} for s in st if s.get("norm")],
        "stations_outside_tambons": sum(1 for s in st if not s["tc"]),
        "rain_gauges": len(gauges or []),
        "chain_missing": [r["label"] for c in chains for r in c["stations"] if not r["found"]],
        "sources_failed": [v["label"] for v in ctx.status.values() if not v["ok"]],
    }


def make_alerts(ctx, T, prev_latest, tam_props, prev_log=None):
    min_lv = ctx.cfg["notify"]["min_level"]
    prev = (prev_latest or {}).get("tambons", {})
    if not prev:  # first run: record a baseline, do not alert on everything at once
        return []
    out = []
    for tc, t in T.items():
        before = (prev.get(tc) or {}).get("lv") or 0
        if (t["lv"] or 0) >= min_lv and (t["lv"] or 0) > before:
            recent = [a for a in (prev_log or []) if a["tc"] == tc and a["to"] >= t["lv"]
                      and ctx.now - (parse_iso(a["time"]) or ctx.now) < timedelta(hours=6)]
            if recent:  # already told people about this tambon at this level recently
                continue
            p = tam_props[tc]
            out.append({"time": iso(ctx.now), "tc": tc, "name": f"ต.{p['t']} อ.{p['a']} จ.{p['p']}", "from": before, "to": t["lv"],
                        "why": t["reasons"][0]["text"] if t["reasons"] else ""})
    return out


def notify(alerts, ctx):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not alerts or not topic or ctx.fixtures:
        return "ไม่ได้ส่ง" if alerts else "ไม่มีการแจ้งเตือนใหม่"
    import json
    import urllib.request
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    top = max(a["to"] for a in alerts)
    lines = [f"[{LEVELS[a['to']]}] {a['name']}" for a in sorted(alerts, key=lambda a: -a["to"])[:15]]
    if len(alerts) > 15:
        lines.append(f"…และอีก {len(alerts) - 15} ตำบล")
    body = {"topic": topic, "title": f"เตือนน้ำท่วม: {len(alerts)} ตำบลระดับ{LEVELS[top]}ขึ้นไป",
            "message": "\n".join(lines), "priority": 5 if top >= 3 else 4, "tags": ["warning"]}
    if os.environ.get("PAGES_URL"):
        body["click"] = os.environ["PAGES_URL"]
    try:
        req = urllib.request.Request(server, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return f"ส่งแล้ว {len(alerts)} ตำบล"
    except Exception as e:  # noqa: BLE001
        print(f"::warning::ส่งแจ้งเตือนไม่สำเร็จ: {e}")
        return "ส่งไม่สำเร็จ"


def dam_status(cfg, stations, dam_raw, ev, now):
    by = {norm_code(s["code"]): s for s in stations if s.get("code")}
    out = []
    for d in cfg.get("dams", []):
        res, tw = by.get(norm_code(d["reservoir"])), by.get(norm_code(d["tailwater"]))
        month = now.astimezone(ICT).strftime("%Y-%m")
        plan = (d.get("monthly_plan_mcm") or {}).get(month)
        days = 31 if month[-2:] in ("01", "03", "05", "07", "08", "10", "12") else 30 if month[-2:] != "02" else 28
        past = (ev.get("dams") or {}).get(d["reservoir"], {})
        row = {"name": d["name"], "downstream_amphoes": d.get("downstream_amphoes", []),
               "capacity_mcm": d.get("capacity_mcm"), "ref_points": d.get("ref_points", []),
               "plan_month": month, "plan_mcm": plan, "plan_per_day": round(plan / days, 2) if plan else None,
               "plan_source": d.get("plan_source"),
               "reservoir": {"code": d["reservoir"], "level": res and res["level"], "time": res and res["time"],
                             "slope": res and res.get("slope")} if res else None,
               "tailwater": {"code": d["tailwater"], "level": tw and tw["level"], "time": tw and tw["time"],
                             "state": tw and tw.get("state"), "why": tw and tw.get("why")} if tw else None,
               "tailwater_state": tw and tw.get("state"), "past": past,
               "hii": dam_fields(dam_raw.get(d["name_match"])), "hii_raw_keys": sorted((dam_raw.get(d["name_match"]) or {}).keys())[:40]}
        out.append(row)
    return out


def write_rain_log(prev_dir, out_dir, gauges, now):
    """Append rainy readings to a monthly CSV (kept 3 months on the site; the monthly archive job keeps them for good)."""
    import csv
    import glob
    import shutil
    src, dst = os.path.join(prev_dir, "rain_log"), os.path.join(out_dir, "rain_log")
    os.makedirs(dst, exist_ok=True)
    month = now.astimezone(ICT).strftime("%Y-%m")
    keep = sorted(os.path.basename(p) for p in glob.glob(os.path.join(src, "*.csv")))[-3:]
    for f in keep:
        if f != month + ".csv":
            shutil.copy(os.path.join(src, f), os.path.join(dst, f))
    path = os.path.join(dst, month + ".csv")
    seen, rows = set(), []
    if os.path.exists(os.path.join(src, month + ".csv")):
        with open(os.path.join(src, month + ".csv"), encoding="utf-8") as f:
            for r in csv.reader(f):
                rows.append(r)
                seen.add((r[0], r[1]))
    if not rows:
        rows.append(["time", "k", "name", "tc", "rain_24h", "rain_1h", "est_1h"])
    for g in gauges:
        if not g.get("time") or (g.get("r1") or 0) <= 0 and (g.get("i1") or 0) <= 0:
            continue
        key = (g["time"], g["k"])
        if key in seen:
            continue
        seen.add(key)
        rows.append([g["time"], g["k"], g["name"], g["tc"] or "", g["r24"], "" if g.get("r1") is None else g["r1"],
                     "" if g.get("i1") is None else g["i1"]])
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--static", default="site/data/static")
    ap.add_argument("--prev", default="prev/data")
    ap.add_argument("--out", default="out/data")
    ap.add_argument("--fixtures", default=None, help="โฟลเดอร์ไฟล์ทดสอบ (ไม่ต่ออินเทอร์เน็ต)")
    ap.add_argument("--now", default=None, help="กำหนดเวลาปัจจุบัน (ใช้ทดสอบ) เช่น 2026-11-24T10:00:00+07:00")
    args = ap.parse_args()
    ctx = Ctx(args)
    if args.now:
        ctx.now = parse_iso(args.now)
    cfg = ctx.cfg
    tam_geo = load_json(os.path.join(args.static, "tambons.geojson"))
    admin = load_json(os.path.join(args.static, "admin.json"))
    idx = TambonIndex(tam_geo)
    tam_props = {f["properties"]["tc"]: f["properties"] for f in tam_geo["features"]}
    prev_latest = load_json(os.path.join(args.prev, "latest.json"), {})
    prev_hist = load_json(os.path.join(args.prev, "history.json"), {})
    prev_fc = load_json(os.path.join(args.prev, "forecast.json"), None)
    prev_alerts = load_json(os.path.join(args.prev, "alerts_log.json"), [])
    prev_rh = load_json(os.path.join(args.prev, "rain_history.json"), {})
    ctx.urban = []

    fews_thr = ctx.run("fews_thr", "เกณฑ์ระดับน้ำสถานี (สสน. FEWS)", lambda: get_thresholds(ctx)) or {}
    stations = ctx.run("levels", "ระดับน้ำ (คลังข้อมูลน้ำ สสน.)", lambda: get_levels(ctx, idx, fews_thr))
    norms = (load_json(os.path.join(args.static, "event_analysis.json"), {}) or {}).get("norms", {})
    st_cfg = cfg["thresholds"]["station"]
    force_norm = {norm_code(c) for c in st_cfg.get("force_norm_stations", [])}
    force_bank = {norm_code(c) for c in st_cfg.get("force_bank_stations", [])}
    for s_ in stations or []:
        n = norms.get(str(s_["id"]))
        code = norm_code(s_["code"])
        use = n and (code in force_norm or (n.get("mode") == "norm" and code not in force_bank))
        s_["norm"] = n if use else None
    gauges = ctx.run("rain", "ฝน 24 ชม. (คลังข้อมูลน้ำ สสน.)", lambda: get_rain(ctx, idx))
    for g in gauges or []:
        if g["tc"]:
            g["ac"] = tam_props[g["tc"]]["ac"]
    fc = ctx.run("forecast", "ฝนพยากรณ์ 3 โมเดล + ความชื้นดิน (Open-Meteo)", lambda: get_forecast(ctx, admin["amphoes"], prev_fc))
    fc_age = ctx.now - (parse_iso((prev_fc or {}).get("fetched_at")) or ctx.now - timedelta(days=99))
    if fc is None and prev_fc and fc_age <= timedelta(hours=12):
        fc = prev_fc
        ctx.status["forecast"]["note"] = "ใช้ข้อมูลพยากรณ์รอบก่อน"
    if fc and ctx.status["forecast"]["ok"]:
        ctx.status["forecast"]["n"] = len(fc.get("amphoes", {}))
    if fc and fc.get("reused"):
        ctx.status["forecast"]["note"] = "ใช้รอบก่อน (ยังไม่ถึงรอบดึงใหม่)"
    ff = ctx.run("flashflood", "พื้นที่เสี่ยงน้ำท่วมฉับพลัน (สสน. FEWS)", lambda: get_flashflood(ctx, tam_geo["features"]))
    dam_raw = ctx.run("dams", "ข้อมูลเขื่อนรายวัน (สสน.)", lambda: get_dams(ctx)) if cfg.get("dams") else None
    rh = rain_intensity(gauges or [], prev_rh, ctx.now)
    if gauges is not None:
        n1 = sum(1 for g in gauges if g.get("r1") is not None)
        ctx.status["rain"]["note"] = f"มีค่าฝน 1 ชม. จาก สสน. {n1} สถานี" if n1 else "ไม่มีค่าฝน 1 ชม. จาก สสน. ใช้ค่าประมาณจากฝนสะสม"

    if stations is None and prev_latest.get("stations"):
        stations = prev_latest["stations"]
        ctx.status["levels"]["note"] = "ใช้ข้อมูลรอบก่อน"
    hist = merge_history(prev_hist, stations or [], cfg["history_hours"], ctx.now)
    for s in stations or []:
        s["slope"] = slope_m_per_h(hist.get(s["k"], []), cfg["thresholds"]["station"]["trend_window_h"])
        if s["slope"] is not None:
            s["slope"] = round(s["slope"], 3)
        station_state(s, cfg["thresholds"]["station"], cfg["max_age_hours"], ctx.now)

    if all(not v["ok"] for v in ctx.status.values()):
        summary("## ❌ ดึงข้อมูลไม่สำเร็จทุกแหล่ง\n\nไม่เขียนทับข้อมูลรอบก่อน หน้าเว็บจะแสดงข้อมูลเดิมพร้อมเวลาที่อัปเดตล่าสุด\n\n" +
                "\n".join(f"- {v['label']}: {v.get('error', '')}" for v in ctx.status.values()))
        sys.exit(2)
    dams = dam_status(cfg, stations or [], dam_raw or {}, load_json(os.path.join(args.static, "event_analysis.json"), {}) or {}, ctx.now)
    T, A, P, chains = compute(ctx, tam_geo, admin, stations, gauges, fc, ff, prev_latest.get("tambons"), dams)
    alerts = make_alerts(ctx, T, prev_latest, tam_props, prev_alerts)
    sent = notify(alerts, ctx)
    log = (prev_alerts + alerts)[-2000:]

    latest = {
        "generated_at": iso(ctx.now), "area_name": cfg["area_name"], "levels": LEVELS,
        "sources": ctx.status, "thresholds": cfg["thresholds"],
        "tambons": T, "amphoes": A, "provinces": P, "chains": chains,
        "stations": stations or [], "rain_gauges": gauges or [],
        "flashflood": ff or {}, "gaps": gaps(ctx, T, stations, gauges, chains),
        "alerts_now": alerts, "notify": sent,
        "forecast_at": (fc or {}).get("fetched_at"),
        "urban_rain": ctx.urban, "urban_rain_cfg": cfg.get("urban_rain", {}), "dams": dams,
    }
    out = args.out
    save_json(os.path.join(out, "latest.json"), latest)
    save_json(os.path.join(out, "history.json"), hist)
    if fc:
        fc.pop("reused", None)
        save_json(os.path.join(out, "forecast.json"), fc)
    save_json(os.path.join(out, "alerts_log.json"), log)
    save_json(os.path.join(out, "rain_history.json"), rh)
    write_rain_log(args.prev, out, gauges or [], ctx.now)

    # run summary
    cnt = [0, 0, 0, 0, 0]
    for t in T.values():
        cnt[4 if t["lv"] is None else t["lv"]] += 1
    md = ["## ผลการดึงข้อมูล", "", "| แหล่ง | ผล | จำนวน | หมายเหตุ |", "|---|---|---|---|"]
    for v in ctx.status.values():
        md.append(f"| {v['label']} | {'✅' if v['ok'] else '❌'} | {'' if v.get('n') is None else v['n']} | {v.get('note') or v.get('error', '')} |")
    g = latest["gaps"]
    md += ["", "## ภาพรวม", "",
           f"- ตำบลทั้งหมด {len(T)}: ปกติ {cnt[0]} · เฝ้าระวัง {cnt[1]} · เตือนภัย {cnt[2]} · วิกฤต {cnt[3]} · ไม่มีข้อมูล {cnt[4]}",
           f"- สถานีระดับน้ำในพื้นที่ {g['stations']} (ข้อมูลสด {g['stations_fresh']}) · ตำบลที่มีสถานี {g['tambons_with_station']}",
           f"- สถานีวัดฝน {g['rain_gauges']}",
           f"- สถานีในห่วงโซ่ที่หาไม่พบ: {', '.join(g['chain_missing']) or '-'}",
           "- ฝนหนักในเมือง: " + (" · ".join(f"{u['name']} {u['i1']:.0f} มม./1 ชม. ({LEVELS[u['lv']]})" for u in ctx.urban) or "-"),
           f"- แจ้งเตือน: {sent}"]
    summary("\n".join(md))


if __name__ == "__main__":
    main()
