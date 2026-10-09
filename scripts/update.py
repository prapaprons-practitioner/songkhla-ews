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
        tam = idx.locate(lon, lat) or idx.by_names(th(geo.get("province_name")), th(geo.get("amphoe_name")), th(geo.get("tumbon_name")))
        if not tam and norm_name(th(geo.get("province_name"))) not in provs:
            continue
        code = st.get("tele_station_oldcode") or ""
        banks = [fnum(st.get(k)) for k in ("min_bank", "left_bank", "right_bank")]
        bank = banks[0] if banks[0] is not None else min([b for b in banks[1:] if b is not None], default=None)
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
            "level": fnum(r.get("waterlevel_msl")), "bank": bank, "warn": warn, "crit": crit, "thr_src": thr_src,
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
        tam = idx.locate(lon, lat)
        if not tam and norm_name(th(geo.get("province_name"))) not in provs:
            continue
        out.append({
            "k": f"twr:{st.get('id')}", "name": th(st.get("tele_station_name")), "lat": lat, "lon": lon,
            "tc": tam["tc"] if tam else None, "ac": tam["ac"] if tam else None,
            "r24": fnum(r.get("rain_24h")), "time": iso(parse_local(r.get("rainfall_datetime") or r.get("rain_datetime"))),
        })
    return out


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


def station_state(s, thr, max_age_h, now):
    t = parse_iso(s["time"])
    s["age_h"] = round((now - t).total_seconds() / 3600, 1) if t else None
    s["stale"] = s["age_h"] is None or s["age_h"] > max_age_h
    s["state"], s["why"], s["eta_h"] = None, "", None
    if s["stale"] or s["level"] is None:
        s["why"] = "ข้อมูลไม่เป็นปัจจุบัน" if s["level"] is not None else "ไม่มีค่าระดับน้ำ"
        return
    L, B, W, C = s["level"], s["bank"], s["warn"], s["crit"]
    st, why = 0, []
    if B is not None:
        gap = B - L
        s["gap"] = round(gap, 2)
        why.append(f"{'สูงกว่า' if gap < 0 else 'ต่ำกว่า'}ตลิ่ง {abs(gap):.2f} ม.")
        if gap <= 0:
            st = 3
        elif gap <= thr["near_bank_m"]:
            st = 2
    else:
        why.append("ไม่มีระดับตลิ่ง")
    if C is not None and L >= C:
        st = 3
    elif W is not None and L >= W:
        st = max(st, 2)
        why.append("ถึงระดับเตือนภัยของสถานี")
    if s.get("sit") == 4:
        st = max(st, 1)
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
    fresh = [g["r24"] for g in gauges if g["r24"] is not None]
    out["p24_obs"] = max(fresh) if fresh else None
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
    if lv == 1 and soil is not None and soil >= soil_wet:
        lv = 2
        why.append("ดินอิ่มน้ำ")
    why.insert(0, f"ฝนพยากรณ์ 24 ชม. {out['n24']:.0f} มม. (สูงสุดในบางโมเดล {out['n24_max']:.0f}) · ฝนสะสม 24 ชม.ที่ผ่านมา + 48 ชม.ข้างหน้า {out['acc']:.0f} มม.")
    out["lv"], out["why"] = lv, " · ".join(why)
    return out


def bump(t, lv, src, text):
    if lv is None:
        return
    t["reasons"].append({"src": src, "lv": lv, "text": text})
    if lv > (t["lv"] or 0):
        t["lv"] = lv


def compute(ctx, tam_geo, admin, stations, gauges, fc, ff):
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
                         "lag_h_to_next": cs.get("lag_h_to_next")})
        trig, msgs, etas = None, [], []
        for i, r in enumerate(rows[:-1]):
            if r["state"] and r["state"] >= 2:
                lags = [x["lag_h_to_next"] for x in rows[i:-1]]
                eta = sum(lags) if all(v is not None for v in lags) else None
                lv = 2 if r["state"] >= 3 else 1
                msgs.append(f"{r['label']} {'ล้นตลิ่งแล้ว' if r['state'] >= 3 else 'ใกล้ตลิ่ง'}"
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
        "stations_outside_tambons": sum(1 for s in st if not s["tc"]),
        "rain_gauges": len(gauges or []),
        "chain_missing": [r["label"] for c in chains for r in c["stations"] if not r["found"]],
        "sources_failed": [v["label"] for v in ctx.status.values() if not v["ok"]],
    }


def make_alerts(ctx, T, prev_latest, tam_props):
    min_lv = ctx.cfg["notify"]["min_level"]
    prev = (prev_latest or {}).get("tambons", {})
    if not prev:  # first run: record a baseline, do not alert on everything at once
        return []
    out = []
    for tc, t in T.items():
        before = (prev.get(tc) or {}).get("lv") or 0
        if (t["lv"] or 0) >= min_lv and (t["lv"] or 0) > before:
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

    fews_thr = ctx.run("fews_thr", "เกณฑ์ระดับน้ำสถานี (สสน. FEWS)", lambda: get_thresholds(ctx)) or {}
    stations = ctx.run("levels", "ระดับน้ำ (คลังข้อมูลน้ำ สสน.)", lambda: get_levels(ctx, idx, fews_thr))
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
    T, A, P, chains = compute(ctx, tam_geo, admin, stations, gauges, fc, ff)
    alerts = make_alerts(ctx, T, prev_latest, tam_props)
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
    }
    out = args.out
    save_json(os.path.join(out, "latest.json"), latest)
    save_json(os.path.join(out, "history.json"), hist)
    if fc:
        fc.pop("reused", None)
        save_json(os.path.join(out, "forecast.json"), fc)
    save_json(os.path.join(out, "alerts_log.json"), log)

    # run summary
    cnt = [0, 0, 0, 0, 0]
    for t in T.values():
        cnt[4 if t["lv"] is None else t["lv"]] += 1
    md = ["## ผลการดึงข้อมูล", "", "| แหล่ง | ผล | จำนวน | หมายเหตุ |", "|---|---|---|---|"]
    for v in ctx.status.values():
        md.append(f"| {v['label']} | {'✅' if v['ok'] else '❌'} | {v.get('n') or ''} | {v.get('note') or v.get('error', '')} |")
    g = latest["gaps"]
    md += ["", "## ภาพรวม", "",
           f"- ตำบลทั้งหมด {len(T)}: ปกติ {cnt[0]} · เฝ้าระวัง {cnt[1]} · เตือนภัย {cnt[2]} · วิกฤต {cnt[3]} · ไม่มีข้อมูล {cnt[4]}",
           f"- สถานีระดับน้ำในพื้นที่ {g['stations']} (ข้อมูลสด {g['stations_fresh']}) · ตำบลที่มีสถานี {g['tambons_with_station']}",
           f"- สถานีวัดฝน {g['rain_gauges']}",
           f"- สถานีในห่วงโซ่ที่หาไม่พบ: {', '.join(g['chain_missing']) or '-'}",
           f"- แจ้งเตือน: {sent}"]
    summary("\n".join(md))


if __name__ == "__main__":
    main()
