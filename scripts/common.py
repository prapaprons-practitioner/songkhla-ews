"""Shared helpers (Python standard library only)."""
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ICT = timezone(timedelta(hours=7))
UA = "songkhla-ews/1.0 (community flood early-warning pilot; GitHub Actions)"


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_local(s):
    """Parse ThaiWater / Open-Meteo local time strings (no TZ) as ICT."""
    if not s:
        return None
    s = str(s).strip().replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt).replace(tzinfo=ICT)
        except ValueError:
            continue
    return None


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def http_get(url, timeout=120, retries=3, data=None, headers=None, as_text=False):
    last = None
    for attempt in range(retries):
        try:
            h = {"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "application/json, text/plain, */*"}
            if "thaiwater" in url:
                h["Referer"] = "https://www.thaiwater.net/"
            h.update(headers or {})
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            text = raw.decode("utf-8-sig", errors="replace")
            return text if as_text else json.loads(text)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url[:90]} → {last}")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, obj, compact=True):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)


def fnum(v):
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def th(v):
    if isinstance(v, dict):
        return v.get("th") or v.get("en") or ""
    return v or ""


def norm_name(s):
    s = (s or "").strip()
    for p in ("ตำบล", "อำเภอ", "จังหวัด", "ต.", "อ.", "จ."):
        if s.startswith(p):
            s = s[len(p):]
    return re.sub(r"[\s\.]", "", s)


def norm_code(s):
    """'X.173A' / 'X173A' / 'x.173a' → 'X173A'."""
    return re.sub(r"[^0-9A-Za-z]", "", s or "").upper()


def find_records(obj, key="station"):
    """Return the first list of dicts that carry `key` anywhere in a JSON tree."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and key in obj[0]:
            return obj
        for x in obj:
            r = find_records(x, key)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = find_records(v, key)
            if r:
                return r
    return []


# ---------- point in polygon with a bbox index ----------

def _ring_contains(ring, x, y):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _poly_contains(poly, x, y):
    if not _ring_contains(poly[0], x, y):
        return False
    return not any(_ring_contains(h, x, y) for h in poly[1:])


class TambonIndex:
    def __init__(self, geojson):
        self.items = []
        for f in geojson["features"]:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            xs = [p[0] for poly in polys for p in poly[0]]
            ys = [p[1] for poly in polys for p in poly[0]]
            self.items.append((min(xs), min(ys), max(xs), max(ys), polys, f["properties"]))

    def locate(self, lon, lat):
        if lon is None or lat is None:
            return None
        for x0, y0, x1, y1, polys, props in self.items:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and any(_poly_contains(p, lon, lat) for p in polys):
                return props
        return None

    def by_names(self, prov, amphoe, tambon):
        p, a, t = norm_name(prov), norm_name(amphoe), norm_name(tambon)
        for *_, props in self.items:
            if norm_name(props["p"]) == p and norm_name(props["a"]) == a and norm_name(props["t"]) == t:
                return props
        return None


def summary(md):
    """Append markdown to the GitHub Actions run summary (if running there)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    else:
        print(md)
