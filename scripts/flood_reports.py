"""บันทึกเหตุน้ำท่วมจริง: อ่าน ระบุตำบล และให้คะแนนการเตือนเทียบกับเหตุที่เกิดจริง (Python มาตรฐานเท่านั้น)

แหล่งรายงาน
- ไฟล์ reports/flood_reports.csv ใน repo (แก้ผ่านหน้าเว็บ GitHub ได้) ถือว่าตรวจแล้วทุกแถว
- (ไม่บังคับ) Google Form ที่เผยแพร่คำตอบเป็น CSV: นับเฉพาะแถวที่ใส่ "ใช่" ในคอลัมน์ "ตรวจแล้ว"

คะแนน (ต่อรายงานหนึ่งเหตุ)
- เตือนทัน: ตำบลนั้นขึ้นถึงระดับเตือนภัยภายใน 24 ชม. ก่อนเวลาที่น้ำท่วม
- เฝ้าระวังเท่านั้น: ขึ้นถึงแค่ระดับเฝ้าระวัง
- พลาด: ไม่มีการเตือนเลย
- เวลานำ = เวลาน้ำท่วม − เวลาที่ระบบขึ้นระดับครั้งแรกในช่วงนั้น
"""
import csv
import io
from datetime import datetime, timedelta

from common import ICT, iso, norm_name, parse_iso

HEADER_KEYS = [  # (key, words that identify the column) — checked in this order
    ("submitted", ["ประทับเวลา", "timestamp", "submitted"]),
    ("verified", ["ตรวจแล้ว", "verified", "ตรวจสอบแล้ว"]),
    ("time_quality", ["ชนิดเวลา", "แม่นยำ", "time_quality", "ความแน่นอนของเวลา"]),
    ("depth_cm", ["ความลึก", "depth"]),
    ("tambon", ["ตำบล", "tambon"]),
    ("amphoe", ["อำเภอ", "amphoe"]),
    ("province", ["จังหวัด", "province"]),
    ("place", ["สถานที่", "จุดที่", "place"]),
    ("latlon", ["พิกัด", "latlon", "lat,lon"]),
    ("source", ["แหล่ง", "source", "ลิงก์", "link"]),
    ("note", ["หมายเหตุ", "รายละเอียด", "note"]),
    ("time", ["วันเวลา", "เวลา", "time", "date"]),
]
YES = {"ใช่", "yes", "y", "true", "1", "✓", "ตรวจแล้ว", "x"}
QUALITY = {"onset": "onset", "เริ่มท่วม": "onset", "เวลาที่เริ่มท่วม": "onset",
           "observed": "observed", "พบ": "observed", "รายงาน": "observed", "เวลาที่พบหรือรายงาน": "observed",
           "day": "day", "ทราบแค่วัน": "day", "ไม่ทราบเวลา": "day"}
QUALITY_TH = {"onset": "เวลาที่เริ่มท่วม", "observed": "เวลาที่พบ/รายงาน (ท่วมก่อนหน้านั้นได้)", "day": "ทราบแค่วัน"}


def _map_header(head):
    keys = {}
    for i, h in enumerate(head):
        hl = (h or "").strip().lower()
        for key, words in HEADER_KEYS:
            if key not in keys.values() and any(w.lower() in hl for w in words):
                keys[i] = key
                break
    return keys


def parse_time(s):
    """2025-11-22 01:55 · 22/11/2025 1:55:00 · 22/11/2568 01:55 · 2025-11-22 → (datetime ICT, has_time)."""
    s = (s or "").strip().replace("T", " ").replace("น.", "").strip()
    if not s:
        return None, False
    for fmt, has_t in (("%Y-%m-%d %H:%M:%S", True), ("%Y-%m-%d %H:%M", True), ("%d/%m/%Y %H:%M:%S", True),
                       ("%d/%m/%Y %H:%M", True), ("%d/%m/%Y %H.%M", True), ("%Y-%m-%d", False), ("%d/%m/%Y", False)):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if dt.year > 2400:  # Buddhist year
            dt = dt.replace(year=dt.year - 543)
        return dt.replace(tzinfo=ICT), has_t
    return None, False


def read_csv_text(txt, origin):
    rows = list(csv.reader(io.StringIO(txt.lstrip("﻿"))))
    if not rows:
        return []
    cols = _map_header(rows[0])
    has_verify = "verified" in cols.values()
    out = []
    for n, r in enumerate(rows[1:], start=2):
        rec = {k: (r[i].strip() if i < len(r) else "") for i, k in cols.items()}
        if not any(rec.values()):
            continue
        rec["origin"], rec["row"] = origin, n
        if origin == "form":
            rec["status"] = "verified" if has_verify and rec.get("verified", "").strip().lower() in YES else "pending"
        else:
            rec["status"] = "verified"
        out.append(rec)
    return out


def resolve(reports, idx, admin):
    """Attach tc (tambon) or ac (amphoe-level) and the parsed time to every report."""
    amph = {}
    for a in admin.get("amphoes", []):
        amph.setdefault(norm_name(a["a"]), []).append(a)
    for r in reports:
        t, has_t = parse_time(r.get("time"))
        q = QUALITY.get((r.get("time_quality") or "").strip().lower()) or QUALITY.get((r.get("time_quality") or "").strip())
        if not has_t:
            q = "day"
        r["t"], r["q"] = t, q or "observed"
        r["problems"] = []
        if t is None:
            r["problems"].append("อ่านวันเวลาไม่ได้")
        prov, amp, tam = r.get("province", ""), r.get("amphoe", ""), r.get("tambon", "")
        hit = idx.by_names(prov, amp, tam) if tam else None
        if not hit and r.get("latlon"):
            try:
                lat, lon = (float(x) for x in r["latlon"].replace(" ", "").split(",")[:2])
                hit = idx.locate(lon, lat)
            except ValueError:
                pass
        if hit:
            r["tc"], r["ac"] = hit["tc"], hit["ac"]
        else:
            cand = [a for a in amph.get(norm_name(amp), []) if not prov or norm_name(a.get("p", "")) == norm_name(prov)]
            if cand:
                r["ac"] = cand[0]["ac"]
                if tam:
                    r["problems"].append(f"ไม่พบตำบล \"{tam}\" จึงใช้ทั้งอำเภอ")
            else:
                r["problems"].append("ระบุตำบล/อำเภอไม่ได้")
        try:
            r["depth_cm"] = float(r["depth_cm"]) if r.get("depth_cm") else None
        except ValueError:
            r["depth_cm"] = None
    return reports


# ------------------------------------------------------------ level history

def update_level_log(prev, T, prev_alerts, now, keep_days=400):
    """Tambon level changes only: {"since": iso, "tambons": {tc: [[iso, lv], ...]}, "seed_rises": {...}}.
    The first run seeds 'rises' from the alert log (warning or higher only, no drops known)."""
    log = prev or {}
    if not log.get("tambons"):
        log = {"since": iso(now), "tambons": {}, "seed_rises": {}}
        for a in prev_alerts or []:
            log["seed_rises"].setdefault(a["tc"], []).append([a["time"], a["to"]])
        if prev_alerts:
            log["seed_since"] = min(a["time"] for a in prev_alerts)
    tam = log["tambons"]
    for tc, t in T.items():
        lv = t.get("lv")
        pts = tam.setdefault(tc, [])
        if not pts or pts[-1][1] != lv:
            pts.append([iso(now), lv])
    cut = iso(now - timedelta(days=keep_days))
    for tc in list(tam):
        old = [p for p in tam[tc] if p[0] < cut]
        tam[tc] = ([[cut, old[-1][1]]] if old else []) + [p for p in tam[tc] if p[0] >= cut]
    for tc in list(log.get("seed_rises", {})):
        log["seed_rises"][tc] = [p for p in log["seed_rises"][tc] if p[0] >= cut]
        if not log["seed_rises"][tc]:
            del log["seed_rises"][tc]
    return log


def _first_at_least(log, tcs, t0, t1):
    """Earliest time in [t0, t1] each level (1, 2, 3) was reached in any of tcs, and the max level."""
    first, top, covered = {}, None, False
    since = parse_iso(log.get("since"))
    seed_since = parse_iso(log.get("seed_since"))
    for tc in tcs:
        pts = [(parse_iso(a), b) for a, b in log.get("tambons", {}).get(tc, [])]
        state = None
        for t, lv in pts:
            if t <= t0:
                state = lv
        if pts and pts[0][0] <= t1:
            covered = True
        events = ([(t0, state)] if state is not None else []) + [(t, lv) for t, lv in pts if t0 < t <= t1]
        for t, lv in (([parse_iso(a), b] for a, b in log.get("seed_rises", {}).get(tc, []))):
            if t0 <= t <= t1:
                events.append((t, lv))
        for t, lv in events:
            if lv is None:
                continue
            top = lv if top is None else max(top, lv)
            for k in (1, 2, 3):
                if lv >= k and (k not in first or t < first[k]):
                    first[k] = t
    # full level history covers the moment of the flood; before that only the alert log (warning or higher)
    if since and since <= t1:
        return first, top, True, "levels" if since <= t0 else "partial"
    if seed_since and seed_since <= t0:
        return first, top, True, "alerts"
    return first, top, covered, "levels"


def score(reports, log, tam_props, now, cfg):
    before = timedelta(hours=cfg.get("window_before_h", 24))
    by_amp = {}
    for tc, p in tam_props.items():
        by_amp.setdefault(p["ac"], []).append(tc)
    rows = []
    for r in reports:
        row = {k: r.get(k) for k in ("origin", "row", "status", "place", "province", "amphoe", "tambon", "depth_cm", "source", "note", "q", "tc", "ac")}
        row["time"] = iso(r["t"]) if r.get("t") else None
        row["problems"] = r.get("problems", [])
        if r.get("t") is None or (not r.get("tc") and not r.get("ac")):
            row["result"] = "unscored"
            rows.append(row)
            continue
        if r["q"] == "day":  # flooded some time that day: any warning from 24 h before the day to its end counts
            d0 = r["t"].replace(hour=0, minute=0, second=0)
            t0, t_ref = d0 - before, d0 + timedelta(hours=23, minutes=59)
        else:
            t0, t_ref = r["t"] - before, r["t"]
        tcs = [r["tc"]] if r.get("tc") else by_amp.get(r["ac"], [])
        first, top, covered, basis = _first_at_least(log, tcs, t0, t_ref)
        row["basis"] = basis
        row["scope"] = "tambon" if r.get("tc") else "amphoe"
        row["max_lv"] = top
        if not covered:
            row["result"] = "no_data"
        elif 2 in first:
            row["result"], row["first_warn"] = "warned", iso(first[2])
        elif 1 in first:
            row["result"], row["first_watch"] = "watch_only", iso(first[1])
        else:
            row["result"] = "missed"
        if 1 in first:
            row["first_watch"] = iso(first[1])
        if r["q"] != "day":
            for k, name in ((2, "lead_warn_h"), (1, "lead_watch_h")):
                if k in first:
                    row[name] = round((r["t"] - first[k]).total_seconds() / 3600, 1)
                    if first[k] <= t0:  # already at that level when the window opened: lead is at least the window
                        row[name + "_atleast"] = True
        if r.get("status") == "pending":
            row["result_if_verified"], row["result"] = row["result"], "pending"
        rows.append(row)
    ok = [x for x in rows if x["status"] == "verified" and x["result"] in ("warned", "watch_only", "missed")]
    sc = {k: sum(1 for x in ok if x["result"] == k) for k in ("warned", "watch_only", "missed")}
    sc["n"] = len(ok)
    leads = sorted(x["lead_warn_h"] for x in ok if x.get("lead_warn_h") is not None)
    sc["lead_warn_median_h"] = leads[len(leads) // 2] if leads else None
    return rows, sc


def warning_episodes(log, reports, tam_props, start, end, confirm_h=36, focus=()):
    """Rises to warning (or higher) and whether a verified report in the same amphoe backs them up."""
    ok = [r for r in reports if r.get("status") == "verified" and r.get("t") and r.get("ac")]
    eps = []
    for tc, pts in log.get("tambons", {}).items():
        prev = None
        for i, (a, lv) in enumerate(pts):
            t = parse_iso(a)
            if i == 0 and a <= (log.get("since") or ""):  # first record: the level before it is unknown
                prev = lv
                continue
            if (lv or 0) >= 2 and (prev or 0) < 2 and start <= t <= end:
                p = tam_props.get(tc, {})
                conf = any(r["ac"] == p.get("ac") and t - timedelta(hours=6) <= r["t"] <= t + timedelta(hours=confirm_h) for r in ok)
                eps.append({"tc": tc, "ac": p.get("ac"), "time": a, "lv": lv, "confirmed": conf})
            prev = lv
    def summ(sel):
        return {"n": len(sel), "confirmed": sum(1 for e in sel if e["confirmed"])}
    foc = [e for e in eps if e["ac"] in focus]
    return {"start": iso(start), "end": iso(end), "all": summ(eps), "focus": summ(foc),
            "focus_list": sorted(foc, key=lambda e: e["time"])[-200:]}


def build(cfg_all, repo_csv_text, form_csv_text, idx, admin, tam_props, log, now, start=None, end=None):
    cfg = cfg_all.get("flood_reports", {})
    reps = read_csv_text(repo_csv_text or "", "repo") + read_csv_text(form_csv_text or "", "form")
    reps = resolve(reps, idx, admin)
    if start or end:
        reps = [r for r in reps if r.get("t") and (not start or r["t"] >= start) and (not end or r["t"] <= end)]
    rows, sc = score(reps, log, tam_props, now, cfg)
    ls = parse_iso(log.get("since")) or now
    since = max(start, ls) if start else ls  # rises are only known from the full level history
    ep = warning_episodes(log, reps, tam_props, since, end or now, cfg.get("confirm_window_h", 36), cfg.get("focus_amphoes", []))
    return {"generated_at": iso(now), "rows": sorted(rows, key=lambda x: x.get("time") or "", reverse=True), "score": sc,
            "episodes": ep, "form_url": cfg.get("form_url") or None,
            "counts": {"repo": sum(1 for r in reps if r["origin"] == "repo"), "form": sum(1 for r in reps if r["origin"] == "form"),
                       "pending": sum(1 for r in reps if r["status"] == "pending")},
            "log_since": log.get("since"), "quality_labels": QUALITY_TH}
