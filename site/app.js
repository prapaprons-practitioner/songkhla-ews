"use strict";
/* เตือนน้ำท่วมล่วงหน้า: หน้าแสดงผล (อ่านไฟล์ที่ GitHub Actions สร้าง) */

const LV = ["ปกติ", "เฝ้าระวัง", "เตือนภัย", "วิกฤต"];
const COL = ["#cfe3d4", "#f6d55c", "#f08c2e", "#d7263d"];
const COLX = "#bdbdbd";
const SRC_LABEL = { rain: "ฝน", station: "สถานีวัดน้ำ", flashflood: "น้ำป่า", chain: "น้ำจากต้นน้ำ",
  urban_rain: "ฝนหนักในเมือง", dam: "เขื่อน", hold: "คงระดับรอยืนยัน" };
const KNOWN_GAPS = [
  ["สถานะประตูระบายน้ำและสถานีสูบน้ำ", "ไม่มีข้อมูลเปิดแบบเรียลไทม์ จึงยังคำนวณความสามารถระบายน้ำจริงไม่ได้", "กรมชลประทาน / เทศบาล"],
  ["ความจุคลองจริง (หลังตะกอนทับถม)", "ใช้ระดับตลิ่งแทน ยังไม่รู้ว่าคลองรับน้ำได้กี่ ลบ.ม./วินาที", "กรมชลประทาน (ข้อมูลรูปตัดคลอง)"],
  ["เวลาเดินทางของน้ำระหว่างสถานี", "ใช้ค่าประมาณ ต้องวิเคราะห์จากข้อมูลย้อนหลัง (workflow เก็บข้อมูลย้อนหลัง)", "คำนวณได้เองจากคลังข้อมูล"],
  ["เกณฑ์ธงสีและจุดธงของหาดใหญ่", "ยังผูกกับระดับน้ำที่สถานีไม่ได้", "มูลนิธิ Hatyai City Climate / เทศบาลนครหาดใหญ่"],
  ["ถนนที่ปิดจริงพร้อมเวลา", "ระดับเตือนภัยของถนนอนุมานจากตำบล ยังไม่ได้ยืนยันกับเหตุการณ์จริง", "กรมทางหลวง (HDMS) / ทางหลวงชนบท"],
  ["ระดับน้ำทะเลสาบสงขลาและน้ำขึ้นน้ำลง", "ยังไม่ได้นำมาคำนวณการระบายลงทะเลสาบ", "กรมอุทกศาสตร์ / สสน. FEWS (ตารางน้ำขึ้นลง)"],
  ["แผนระบายน้ำเขื่อนบางลางรายวัน/รายชั่วโมง", "มีแค่แผนรายเดือนและปริมาณระบายจริงรายวัน จึงบอกล่วงหน้าไม่ได้ว่าจะเพิ่มการระบายเมื่อไร", "กฟผ. (เขื่อนบางลาง)"],
  ["ระดับน้ำคลองเรียน คลอง 30 เมตร และคลองเตย", "คลองที่ท่วมจริงคืน 20 ต.ค. 2569 ไม่มีสถานีวัดระดับน้ำในคลังข้อมูลน้ำแห่งชาติ ระบบรู้ได้จากฝนเท่านั้น", "เทศบาลนครหาดใหญ่ / เทศบาลเมืองคอหงส์ / กรมชลประทาน"],
  ["ระดับน้ำกรมชลประทานช่วงเที่ยงคืน", "สถานีกรมชลประทานในภาคใต้ไม่มีข้อมูลราว 23:00–01:00 น. เกือบทุกคืน อย่างน้อยตั้งแต่ปี 2566 ดูตารางความครบถ้วนด้านบน", "กรมชลประทาน (ระบบส่งข้อมูลโทรมาตร) / สสน. / สทนช."],
  ["ฝนรายชั่วโมงที่แม่นยำ", "ถ้า สสน. ไม่ส่งค่าฝน 1 ชม. ระบบประมาณจากการเพิ่มของฝนสะสม 24 ชม. ซึ่งอาจต่ำกว่าจริง", "สสน. / เทศบาลนครหาดใหญ่ (เครื่องวัดฝนในเมือง)"],
  ["ความลึกน้ำท่วมจริงบนพื้นที่", "ไม่มีเซนเซอร์บนถนนในภาคใต้ ระบบบอกได้แค่ความเสี่ยง ไม่ใช่ความลึก", "เทศบาล / ภาพดาวเทียม GISTDA (ต้องขอ API key)"],
];

const S = { latest: null, tam: null, amp: null, admin: null, roads: null, event: null, alerts: [], freports: null, replay: null, efc: null, efAc: null, tracker: null,
  props: {}, sel: { pc: null, ac: null, tc: null }, onlyRisk: false, q: "", rq: "", openRoad: null, layers: {} };

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? "–" : Number(v).toLocaleString("th-TH", { maximumFractionDigits: d, minimumFractionDigits: d }));
const lvOf = (tc) => { const t = S.latest?.tambons?.[tc]; return t && t.lv != null ? t.lv : null; };
const badge = (lv, big) => `<span class="badge ${big ? "big " : ""}${lv == null ? "lvx" : "lv" + lv}">${lv == null ? "ไม่มีข้อมูล" : LV[lv]}</span>`;
const ago = (isoStr) => {
  if (!isoStr) return "–";
  const m = (Date.now() - new Date(isoStr).getTime()) / 60000;
  if (m < 1) return "เมื่อสักครู่";
  if (m < 60) return `${Math.round(m)} นาทีที่แล้ว`;
  if (m < 48 * 60) return `${(m / 60).toFixed(m < 600 ? 1 : 0)} ชม.ที่แล้ว`;
  return `${Math.round(m / 1440)} วันที่แล้ว`;
};
const timeTH = (isoStr) => isoStr ? new Date(isoStr).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok" }) : "–";

async function getJSON(url, optional) {
  try {
    const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now());
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    if (optional) return null;
    throw new Error(`โหลด ${url} ไม่ได้`);
  }
}

/* ------------------------------------------------------------------ map */
let map, tamLayer, ampLayer, roadLayer, stLayer, rgLayer;

function initMap() {
  map = L.map("map", { preferCanvas: true, zoomSnap: 0.5 }).setView([7.2, 100.4], 8);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  map.createPane("roads").style.zIndex = 420;
  map.createPane("points").style.zIndex = 450;

  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const d = L.DomUtil.create("div", "legend");
    d.innerHTML = LV.map((n, i) => `<div><i style="background:${COL[i]}"></i>${n}</div>`).join("") +
      `<div><i style="background:${COLX}"></i>ไม่มีข้อมูล</div>`;
    return d;
  };
  legend.addTo(map);
}

function tamStyle(f) {
  const lv = lvOf(f.properties.tc);
  const sel = S.sel.tc === f.properties.tc;
  return {
    color: sel ? "#0b3b4a" : "#ffffff", weight: sel ? 3 : 0.6,
    fillColor: lv == null ? COLX : COL[lv], fillOpacity: lv == null ? 0.5 : lv ? 0.6 : 0.28,
  };
}

function buildLayers() {
  tamLayer = L.geoJSON(S.tam, {
    style: tamStyle,
    onEachFeature: (f, layer) => {
      layer.bindTooltip(() => {
        const p = f.properties;
        return `<b>ต.${esc(p.t)}</b> อ.${esc(p.a)}<br>${LV[lvOf(p.tc)] ?? "ไม่มีข้อมูล"}`;
      }, { sticky: true });
      layer.on("click", () => select({ pc: f.properties.pc, ac: f.properties.ac, tc: f.properties.tc }, true));
    },
  }).addTo(map);
  ampLayer = L.geoJSON(S.amp, { style: { color: "#33424d", weight: 1.3, fill: false, opacity: 0.7 }, interactive: false }).addTo(map);
  if (S.roads) {
    roadLayer = L.geoJSON(S.roads, {
      pane: "roads",
      style: roadStyle,
      onEachFeature: (f, layer) => layer.bindTooltip(() => `${esc(roadTitle(f.properties))}<br>ต.${esc(S.props[f.properties.tc]?.t)} · ${LV[lvOf(f.properties.tc)] ?? "–"}`, { sticky: true }),
    });
    if (map.getZoom() >= 9) roadLayer.addTo(map);
  }
  stLayer = L.layerGroup().addTo(map);
  rgLayer = L.layerGroup();
  const ctl = L.control({ position: "topright" });
  ctl.onAdd = () => {
    const d = L.DomUtil.create("div", "layers");
    d.innerHTML = `<label><input type="checkbox" data-l="st" checked> สถานีวัดระดับน้ำ</label>
      <label><input type="checkbox" data-l="rg"> สถานีวัดฝน</label>
      ${S.roads ? '<label><input type="checkbox" data-l="rd" checked> ถนนสายหลัก</label>' : ""}`;
    L.DomEvent.disableClickPropagation(d);
    d.addEventListener("change", (e) => {
      const l = { st: stLayer, rg: rgLayer, rd: roadLayer }[e.target.dataset.l];
      S.layers[e.target.dataset.l] = e.target.checked;
      if (!l) return;
      if (e.target.checked) l.addTo(map); else map.removeLayer(l);
    });
    return d;
  };
  ctl.addTo(map);
  map.on("zoomend", () => {
    if (!roadLayer || S.layers.rd === false) return;
    if (map.getZoom() >= 9) roadLayer.addTo(map); else map.removeLayer(roadLayer);
  });
}

function roadStyle(f) {
  const lv = lvOf(f.properties.tc);
  const major = ["motorway", "trunk"].includes(f.properties.hw);
  return { color: lv ? COL[lv] : "#5b6670", weight: (major ? 3.2 : 2) + (lv >= 2 ? 1.5 : 0), opacity: lv ? 0.95 : 0.55 };
}

function refreshMapStyles() {
  tamLayer?.setStyle(tamStyle);
  roadLayer?.setStyle(roadStyle);
  stLayer.clearLayers();
  rgLayer.clearLayers();
  for (const s of S.latest?.stations || []) {
    if (s.lat == null || s.lon == null) continue;
    const c = s.state == null ? COLX : COL[s.state];
    L.circleMarker([s.lat, s.lon], { pane: "points", radius: 6, color: "#1d232a", weight: 1.2, fillColor: c, fillOpacity: 1 })
      .bindTooltip(`<b>${esc(s.name)}</b> ${esc(s.code || "")}<br>${esc(s.why)}`)
      .on("click", () => s.tc && select({ pc: S.props[s.tc].pc, ac: S.props[s.tc].ac, tc: s.tc }, true))
      .addTo(stLayer);
  }
  for (const g of S.latest?.rain_gauges || []) {
    if (g.lat == null) continue;
    L.circleMarker([g.lat, g.lon], { pane: "points", radius: 3 + Math.min(6, (g.r24 || 0) / 30), color: "#1f5f99", weight: 1, fillColor: "#5aa0e0", fillOpacity: 0.8 })
      .bindTooltip(`${esc(g.name)}<br>ฝน 24 ชม. ${fmt(g.r24, 1)} มม.`).addTo(rgLayer);
  }
}

function fitTo(pred) {
  const fs = S.tam.features.filter((f) => pred(f.properties));
  if (!fs.length) return;
  map.fitBounds(L.geoJSON({ type: "FeatureCollection", features: fs }).getBounds(), { padding: [20, 20], maxZoom: 12 });
}

/* ------------------------------------------------------------------ selection */
function select(sel, fromMap) {
  S.sel = { pc: sel.pc || null, ac: sel.ac || null, tc: sel.tc || null };
  const h = S.sel.tc ? `t=${S.sel.tc}` : S.sel.ac ? `a=${S.sel.ac}` : S.sel.pc ? `p=${S.sel.pc}` : "";
  history.replaceState(null, "", h ? "#" + h : location.pathname);
  showTab("area");
  renderArea();
  tamLayer?.setStyle(tamStyle);
  if (!fromMap) {
    if (S.sel.tc) fitTo((p) => p.tc === S.sel.tc);
    else if (S.sel.ac) fitTo((p) => p.ac === S.sel.ac);
    else if (S.sel.pc) fitTo((p) => p.pc === S.sel.pc);
    else fitTo(() => true);
  }
  $("#tab-area").scrollTop = 0;
  if (window.innerWidth <= 820 && (fromMap || window.scrollY > $(".panel").offsetTop)) $(".panel").scrollIntoView({ behavior: fromMap ? "smooth" : "auto", block: "start" });
}

function selFromHash() {
  const m = location.hash.match(/^#([tap])=(\w+)/);
  if (!m) return { pc: null, ac: null, tc: null };
  if (m[1] === "t" && S.props[m[2]]) { const p = S.props[m[2]]; return { pc: p.pc, ac: p.ac, tc: p.tc }; }
  if (m[1] === "a") { const a = S.admin.amphoes.find((x) => x.ac === m[2]); return a ? { pc: a.pc, ac: a.ac } : {}; }
  if (m[1] === "p") return { pc: m[2] };
  return {};
}

/* ------------------------------------------------------------------ rendering helpers */
const LVN = [...LV, "ไม่มีข้อมูล"];
function countsBar(n) {
  const tot = n.reduce((a, b) => a + b, 0) || 1;
  return `<div class="counts" title="${n.map((v, i) => `${LVN[i]} ${v}`).join(" · ")}">${n.map((v, i) => v ? `<span class="c${i}" style="width:${(100 * v) / tot}%"></span>` : "").join("")}</div>`;
}
function countsText(n) {
  return n.map((v, i) => (i && v ? `${LVN[i]} ${v}` : "")).filter(Boolean).join(" · ") || "ทุกตำบลปกติ";
}
function tamCounts(pred) {
  const n = [0, 0, 0, 0, 0];
  for (const tc in S.props) if (pred(S.props[tc])) { const v = lvOf(tc); n[v == null ? 4 : v]++; }
  return n;
}
function crumbs() {
  const parts = [`<a data-go="">ทั้งหมด</a>`];
  if (S.sel.pc) parts.push(`<a data-go="p">${esc(S.admin.provinces.find((p) => p.pc === S.sel.pc)?.p)}</a>`);
  if (S.sel.ac) parts.push(`<a data-go="a">อ.${esc(S.admin.amphoes.find((a) => a.ac === S.sel.ac)?.a)}</a>`);
  if (S.sel.tc) parts.push(`<span>ต.${esc(S.props[S.sel.tc].t)}</span>`);
  return `<div class="crumbs">${parts.join(" › ")}</div>`;
}
function spark(h) {
  if (!h || !h.length) return "";
  const W = 360, H = 64, max = Math.max(5, ...h.filter((v) => v != null));
  const bw = W / h.length, top = 13, bot = 12, ph = H - top - bot;
  const bars = h.map((v, i) => v ? `<rect x="${(i * bw).toFixed(1)}" y="${(H - bot - (ph * v) / max).toFixed(1)}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${((ph * v) / max).toFixed(1)}"></rect>` : "").join("");
  const lab = [0, 24, 48, 71].map((i) => `<text x="${Math.min(W - 26, i * bw)}" y="${H - 1}">${i ? "+" + (i === 71 ? 72 : i) + " ชม." : "ตอนนี้"}</text>`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="ฝนพยากรณ์รายชั่วโมง 72 ชม."><text x="0" y="9">ฝนพยากรณ์รายชั่วโมง · สูงสุด ${fmt(max, 1)} มม./ชม.</text>${bars}${lab}</svg>`;
}
function stationRow(s) {
  const lvl = s.state == null ? null : s.state;
  return `<div class="reason">${badge(lvl)}<div><b>${esc(s.name)}</b> <span class="note">${esc(s.code || "")} · ${esc(s.agency || "")}</span><br>
    ระดับน้ำ ${fmt(s.level, 2)} ม.รทก. · ตลิ่ง ${fmt(s.bank, 2)}${s.warn != null ? ` · ระดับเตือน ${fmt(s.warn, 2)}` : ""}<br>
    <span class="note">${esc(s.why || "")} · วัดเมื่อ ${ago(s.time)}</span></div></div>`;
}

/* ------------------------------------------------------------------ benchmark: compare with a past event */
const BM = () => S.event?.benchmark;
const bmTime = (i) => {
  const t = new Date(new Date(BM().start).getTime() + i * 3600e3);
  return t.toLocaleString("th-TH", { day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" }) + " น.";
};
const hrs = (h) => (h >= 48 ? `${fmt(h / 24, h >= 240 ? 0 : 1)} วัน (${fmt(h)} ชม.)` : `${fmt(h)} ชม.`);

/* Where does the level now sit on the past event's rising limb? */
function analog(s) {
  const b = BM()?.stations?.[String(s.id)];
  if (!b || s.level == null || s.bank == null || s.state == null) return null;
  const rel = s.level - s.bank;
  const pk = b.peak_i, relPk = b.rel[pk];
  // each station's own pre-event level (median of the first two days of the window)
  const pre = b.rel.slice(0, 48).filter((v) => v != null).sort((x, y) => x - y);
  const base = pre.length ? pre[Math.floor(pre.length / 2)] : null;
  const frac = base != null && relPk > base ? (rel - base) / (relPk - base) : null;
  // compare only once the water has made a real part of that event's rise, and is near the bank
  // stations whose level barely moved in that event (lake / tidal gauges) are not comparable
  const active = rel >= -BM().activate_below_bank_m && frac != null && frac >= 0.3;
  const r = { b, rel, pk, relPk, base, frac, active };
  if (rel > relPk) { r.above = true; return r; }
  const i = b.rel.findIndex((v, j) => j <= pk && v != null && v >= rel);
  // a match in the first two days of the window is the pre-event baseline, not the flood
  if (i < 48) { r.beforeStart = true; return r; }
  r.i = i;
  r.hToPeak = pk - i;
  if (rel < 0) {
    const ib = b.rel.findIndex((v, j) => j >= i && j <= pk && v != null && v >= 0);
    r.hToBank = ib >= 0 ? ib - i : null;
  }
  return r;
}

function analogShort(s) {
  const r = analog(s);
  if (!r || !r.active) return "";
  if (r.above) return `สูงกว่ายอดน้ำ ${BM().label}`;
  if (r.i == null) return "";
  return `เทียบ ${BM().label}: ≈ ${bmTime(r.i)} · อีก ${hrs(r.hToPeak)} ถึงยอดน้ำ`;
}

function benchCard(s) {
  const r = analog(s);
  if (!r) return "";
  const lab = BM().label;
  const relTxt = (v) => `${v < 0 ? "ต่ำกว่า" : "สูงกว่า"}ตลิ่ง ${fmt(Math.abs(v), 2)} ม.`;
  let msg;
  if (r.above) {
    msg = `<div class="warnnote"><b>ระดับน้ำตอนนี้สูงกว่ายอดน้ำ ${lab}</b> (ตอนนี้${relTxt(r.rel)} · ยอดน้ำ ${lab} ${relTxt(r.relPk)})</div>`;
  } else if (r.frac == null) {
    msg = `<p class="note">ใน ${lab} ระดับน้ำที่สถานีนี้ไม่ได้ขึ้นชัดเจน (อาจเป็นสถานีที่ขึ้นลงตามน้ำทะเล ทะเลสาบ หรือการปล่อยน้ำจากเขื่อน) จึงไม่เทียบเวลา</p>`;
  } else if (!r.active || r.i == null) {
    msg = `<p class="note">ตอนนี้${relTxt(r.rel)}${r.frac != null ? ` (คิดเป็น ${fmt(Math.max(0, r.frac) * 100)}% ของระดับที่น้ำขึ้นใน ${lab})` : ""} ยังไม่ถึงช่วงน้ำขึ้นจริงของเหตุการณ์ ${lab} จึงยังไม่เทียบเวลา · ${lab} ที่สถานีนี้ยอดน้ำ${relTxt(r.relPk)} เมื่อ ${bmTime(r.pk)}</p>`;
  } else {
    msg = `<div class="bm-msg"><b>ระดับนี้เท่ากับ ${bmTime(r.i)}</b> ในเหตุการณ์ ${lab}<br>
      ตอนนั้น${r.hToBank != null ? `อีก <b>${hrs(r.hToBank)}</b> น้ำถึงตลิ่ง และ` : ""}อีก <b>${hrs(r.hToPeak)}</b> ถึงยอดน้ำ (${relTxt(r.relPk)})</div>
      ${s.slope != null && s.slope < -0.005 ? `<p class="note">ตอนนี้ระดับน้ำกำลังลด ซึ่งต่างจากปี 2568 ที่ช่วงนี้น้ำยังขึ้นต่อ</p>` : ""}
      <p class="note">เส้นทาง ${lab} เป็นสถานการณ์หนึ่งที่เคยเกิด ไม่ใช่การพยากรณ์ น้ำจะขึ้นต่อหรือไม่ขึ้นกับฝนที่จะตกต่อ</p>`;
  }
  if (r.b.gap_near_peak) msg += `<p class="note">⚠️ ${lab} สถานีนี้หยุดส่งข้อมูลช่วงใกล้ยอดน้ำ ยอดน้ำจริงอาจสูงกว่าที่แสดง</p>`;
  return `<div class="card bm"><h3>เทียบกับน้ำท่วม ${lab}: ${esc(s.name)} ${esc(s.code || "")}</h3>${msg}${benchChart(s, r)}</div>`;
}

function benchChart(s, r) {
  const b = r.b, n = b.rel.length;
  const x0 = Math.max(0, r.pk - 120), x1 = Math.min(n - 1, r.pk + 48);
  const W = 360, H = 150, L = 34, R = 8, T = 10, B = 22;
  // current series, aligned so "now" sits at the matching moment of the past event
  const cur = [];
  const pts = S.hist?.[s.k] || [];
  if (r.i != null && r.active) {
    const now = new Date(s.time).getTime();
    for (const [t, v] of pts) {
      const x = r.i - (now - new Date(t).getTime()) / 3600e3;
      if (x >= x0 && x <= x1 && v != null) cur.push([x, v - s.bank]);
    }
    cur.push([r.i, r.rel]);
  }
  const ys = b.rel.slice(x0, x1 + 1).filter((v) => v != null).concat(cur.map((p) => p[1]), [r.rel, 0]);
  const y0 = Math.min(...ys) - 0.3, y1 = Math.max(...ys) + 0.4;
  const X = (i) => L + ((i - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v) => T + ((y1 - v) / (y1 - y0)) * (H - T - B);
  let past = "", seg = [];
  const flush = () => { if (seg.length > 1) past += `<polyline class="bm-past" points="${seg.join(" ")}"/>`; seg = []; };
  for (let i = x0; i <= x1; i++) { const v = b.rel[i]; if (v == null) flush(); else seg.push(`${X(i).toFixed(1)},${Y(v).toFixed(1)}`); }
  flush();
  const ticks = [];
  for (let d = -5; d <= 2; d++) {
    const i = r.pk + d * 24;
    if (i >= x0 && i <= x1) ticks.push(`<line class="bm-grid" x1="${X(i)}" x2="${X(i)}" y1="${T}" y2="${H - B}"/><text class="bm-ax" x="${X(i)}" y="${H - 8}" text-anchor="middle">${d ? (d > 0 ? "+" : "−") + Math.abs(d) + " วัน" : "ยอดน้ำ"}</text>`);
  }
  const yt = [];
  for (let v = Math.ceil(y0); v <= Math.floor(y1); v++) yt.push(`<text class="bm-ax" x="${L - 4}" y="${Y(v) + 3}" text-anchor="end">${v > 0 ? "+" : ""}${v}</text>`);
  const nowEl = cur.length > 1
    ? `<polyline class="bm-now" points="${cur.map(([x, v]) => `${X(x).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")}"/>`
    : "";
  const nowDot = r.i != null && r.active
    ? `<circle class="bm-dot" cx="${X(r.i)}" cy="${Y(r.rel)}" r="4"/><text class="bm-lbl" x="${X(r.i) - 6}" y="${Y(r.rel) - 8}" text-anchor="end">ตอนนี้</text>`
    : `<line class="bm-nowline" x1="${L}" x2="${W - R}" y1="${Y(r.rel)}" y2="${Y(r.rel)}"/><text class="bm-lbl" x="${W - R}" y="${Y(r.rel) - 4}" text-anchor="end">ระดับตอนนี้</text>`;
  return `<svg class="bm-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="กราฟระดับน้ำเทียบตลิ่ง ปัจจุบันเทียบ ${BM().label}">
    ${ticks.join("")}${yt.join("")}
    <line class="bm-bank" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/><text class="bm-ax" x="${L + 2}" y="${Y(0) - 3}">ตลิ่ง</text>
    ${past}<circle class="bm-pk" cx="${X(r.pk)}" cy="${Y(r.relPk)}" r="3"/>
    ${nowEl}${nowDot}
  </svg>
  <div class="bm-legend"><span><i class="lp"></i>${esc(BM().label)}</span><span><i class="ln"></i>ตอนนี้${r.i != null && r.active ? " (7 วันล่าสุด วางตรงจุดที่ระดับเท่ากัน)" : ""}</span><span class="note">แกนตั้ง: เมตร เทียบตลิ่ง</span></div>`;
}

async function ensureHist() {
  if (S.hist || S.histLoading) return;
  S.histLoading = true;
  S.hist = (await getJSON("data/history.json", true)) || {};
  S.histLoading = false;
  if (S.sel.tc) renderArea();
}

/* ------------------------------------------------------------------ tab: area */
function renderArea() {
  const el = $("#tab-area");
  const L0 = S.latest;
  let html = crumbs() + `<input class="search" id="q" placeholder="ค้นหาตำบลหรืออำเภอ เช่น คอหงส์, หาดใหญ่" value="${esc(S.q)}">`;
  if (S.q.trim()) {
    const q = S.q.trim();
    const hits = Object.values(S.props).filter((p) => p.t.includes(q) || p.a.includes(q) || (p.te || "").toLowerCase().includes(q.toLowerCase())).slice(0, 40);
    html += `<ul class="list">${hits.map((p) => `<li data-tc="${p.tc}"><span class="dot" style="background:${lvOf(p.tc) == null ? COLX : COL[lvOf(p.tc)]}"></span>
      <div><div class="nm">ต.${esc(p.t)}</div><div class="meta">อ.${esc(p.a)} จ.${esc(p.p)}</div></div>${badge(lvOf(p.tc))}</li>`).join("") || '<li class="note">ไม่พบ</li>'}</ul>`;
    el.innerHTML = html;
    bindArea(el);
    return;
  }
  if (S.sel.tc) html += tambonDetail(S.sel.tc);
  else if (S.sel.ac) {
    const a = S.admin.amphoes.find((x) => x.ac === S.sel.ac);
    const n = tamCounts((p) => p.ac === a.ac);
    html += hero(`อ.${a.a}`, `จ.${a.p}`, L0?.amphoes?.[a.ac]?.lv, n);
    html += stormCard((x) => x.ac === a.ac);
    if (S.tracker && ["TH9011", "TH9012", "TH9010"].includes(a.ac)) html += trackerCard();
    html += rainCard(a.ac);
    html += childList(Object.values(S.props).filter((p) => p.ac === a.ac).map((p) => ({ key: p.tc, attr: "tc", name: "ต." + p.t, lv: lvOf(p.tc), meta: (L0?.tambons?.[p.tc]?.reasons?.[0]?.text || "ไม่พบปัจจัยเสี่ยง").slice(0, 90) })));
  } else if (S.sel.pc) {
    const p = S.admin.provinces.find((x) => x.pc === S.sel.pc);
    const n = tamCounts((x) => x.pc === p.pc);
    html += hero(`จ.${p.p}`, `${n.reduce((a, b) => a + b)} ตำบล`, L0?.provinces?.[p.pc]?.lv, n);
    html += stormCard((x) => x.pc === p.pc);
    html += childList(S.admin.amphoes.filter((a) => a.pc === p.pc).map((a) => {
      const c = tamCounts((x) => x.ac === a.ac);
      return { key: a.ac, attr: "ac", name: "อ." + a.a, lv: L0?.amphoes?.[a.ac]?.lv, meta: countsText(c), n: c };
    }));
  } else {
    const n = tamCounts(() => true);
    html += stormCard(() => true).replace('<div class="card storm">', '<div class="card storm" id="storm-top">');
    html += trackerCard();
    html += hero(L0?.area_name || "ทุกจังหวัด", `${Object.keys(S.props).length} ตำบล · ${S.admin.amphoes.length} อำเภอ`, Math.max(...Object.values(L0?.provinces || {}).map((p) => p.lv ?? 0), 0), n);
    if (safeUrl(S.freports?.form_url)) html += `<a class="reportbtn" href="${esc(S.freports.form_url)}" target="_blank" rel="noopener">แจ้งเหตุน้ำท่วมที่เห็นจริง</a><p class="note">ช่วยให้ตรวจได้ว่าระบบเตือนทันหรือไม่ · ไม่ต้องใส่ชื่อหรือเบอร์โทร</p>`;
    html += childList(S.admin.provinces.map((p) => {
      const c = tamCounts((x) => x.pc === p.pc);
      return { key: p.pc, attr: "pc", name: "จ." + p.p, lv: L0?.provinces?.[p.pc]?.lv, meta: countsText(c), n: c };
    }), true);
    const top = Object.entries(L0?.tambons || {}).filter(([, t]) => t.lv >= 2).sort((a, b) => b[1].lv - a[1].lv).slice(0, 25);
    if (top.length) {
      html += `<div class="card"><h3>ตำบลที่ต้องจับตา (เตือนภัยขึ้นไป)</h3><ul class="list">${top.map(([tc, t]) => `<li data-tc="${tc}"><span class="dot" style="background:${COL[t.lv]}"></span>
        <div><div class="nm">ต.${esc(S.props[tc].t)} <span class="meta">อ.${esc(S.props[tc].a)} จ.${esc(S.props[tc].p)}</span></div><div class="meta">${esc((t.reasons[0]?.text || "").slice(0, 100))}</div></div>${badge(t.lv)}</li>`).join("")}</ul></div>`;
    }
  }
  el.innerHTML = html;
  bindArea(el);
}

const thDate = (d) => d ? new Date(d + "T12:00:00+07:00").toLocaleDateString("th-TH", { day: "numeric", month: "short", timeZone: "Asia/Bangkok" }) : "";
function stormCard(filter) {
  const sr = S.latest?.storm_risk;
  if (!sr) return "";
  const am = (S.admin?.amphoes || []).filter(filter).map((a) => ({ ...a, r: sr.amphoes?.[a.ac] })).filter((a) => a.r);
  const flagged = am.filter((a) => a.r.flag).sort((a, b) => b.r.cape - a.r.cape);
  if (!flagged.length && am.length > 1) return "";
  const one = am.length === 1 ? am[0] : null;
  const head = `<h3>วันเสี่ยงฝนฟ้าคะนองรุนแรง ${thDate(sr.date)} <span class="tag-exp">ทดลอง</span></h3>`;
  const body = one
    ? `<div class="kv"><span class="k">CAPE สูงสุดช่วง ${sr.window[0]}:00–${sr.window[1]}:59 น.</span><span class="v">${fmt(one.r.cape)} J/kg <span class="note">${esc(one.r.time)} น.</span>${one.r.flag ? ' <span class="tag-storm">เสี่ยง</span>' : ""}</span></div>`
    : `<ul class="list">${flagged.map((a) => `<li data-ac="${a.ac}"><span class="dot" style="background:var(--storm, #7b5cd6)"></span><div><div class="nm">อ.${esc(a.a)} <span class="meta">จ.${esc(a.p)}</span></div><div class="meta">CAPE ${fmt(a.r.cape)} J/kg ช่วง ${esc(a.r.time)} น.</div></div></li>`).join("")}</ul>`;
  return `<div class="card storm">${head}${body}
    <p class="note">บรรยากาศพร้อมเกิดฝนฟ้าคะนองรุนแรง (CAPE ≥ ${fmt(sr.threshold)} J/kg) บอกได้แค่ว่าเป็น "วันเสี่ยง" ไม่ได้บอกเวลาหรือจุดที่ฝนจะตก ใช้เป็นสัญญาณให้ยกของที่ยกง่ายขึ้นที่สูงไว้ก่อน · ทดสอบย้อนหลังที่หาดใหญ่ 14 ต.ค.–2 พ.ย. 2569 จับวันฝนหนักได้ 3 ใน 5 วัน และเตือนผิด 2 วันจาก 16 วัน · ยังไม่ส่งแจ้งเตือนและไม่ยกระดับตำบล</p></div>`;
}

/* daily watch for the rainy period: forecast vs rain that fell, key stations vs the 2025 path, and where it is heading */
const SCN = {
  "ก": ["ก. ท่วมขัง/น้ำหลากเป็นจุด", "ฝนหนักเป็นช่วงๆ ถนนต่ำและชุมชนริมคลองย่อยท่วมเร็วแล้วลดในไม่กี่ชั่วโมง", "#f6d55c", "#3a2f00"],
  "ข": ["ข. น้ำหลากจากเขาคอหงส์เข้าเมือง", "แบบระลอกแรกของปี 2568: น้ำจากเขาทางตะวันออกเข้าเมืองตามถนนสาย 1–3 ภายในไม่กี่ชั่วโมง", "#f08c2e", "#fff"],
  "ค": ["ค. ท่วมลึกและนานแบบปี 2568", "คลองอู่ตะเภาล้นจากน้ำต้นน้ำ ท่วมสูงหลายเมตรและนานหลายวัน", "#d7263d", "#fff"],
};
function trackerCard() {
  const T = S.tracker;
  if (!T || !T.days || !T.window) return "";
  if (Date.now() > new Date(T.window[1] + "T23:59:00+07:00").getTime() + 3 * 864e5) return "";  // the watch period is over
  const A = T.areas || {}, areas = Object.keys(A);
  const now = T.now || {};
  const sc = now.scenario;
  const chip = (s, small) => s ? `<span class="scn${small ? " sm" : ""}" style="background:${SCN[s][2]};color:${SCN[s][3]}">${small ? esc(s) : esc(SCN[s][0])}</span>` : `<span class="scn${small ? " sm" : ""}" style="background:var(--lv0);color:#123">${small ? "–" : "ยังไม่เข้าสถานการณ์ใด"}</span>`;
  const mm = (f) => (f ? `${fmt(f.mean)}<span class="note"> (${fmt(f.max)})</span>` : "–");
  const rel = (v) => (v == null ? "–" : `<span class="${v > -1 ? "up" : ""}">${v >= 0 ? "ล้น +" : ""}${fmt(v, 2)}</span>`);
  // 2025 reference from the event benchmark: daily max relative to bank on chosen days, and the peak
  const ref = (id, day) => {
    const b = BM()?.stations?.[String(id)];
    if (!b) return null;
    const i0 = Math.round((new Date(`2025-11-${day}T00:00:00+07:00`) - new Date(BM().start)) / 3.6e6);
    const v = b.rel.slice(i0, i0 + 24).filter((x) => x != null);
    return v.length ? Math.max(...v) : null;
  };
  const peak = (id) => { const b = BM()?.stations?.[String(id)]; return b ? [b.rel[b.peak_i], bmTime(b.peak_i)] : [null, ""]; };
  // one block per station: a scale from far below the bank to above it, with last year's path and where the water is now
  const scale = (vals, nowV) => {
    const W = 300, H = 26, lo = -7.5, hi = 3.5, x = (v) => 6 + ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (W - 12);
    const mk = vals.filter((v) => v[0] != null).map(([v, lab, col]) => `<circle cx="${x(v).toFixed(1)}" cy="13" r="4" fill="${col}"><title>${esc(lab)} ${fmt(v, 2)} ม.</title></circle>`).join("");
    return `<svg class="trk-scale" viewBox="0 0 ${W} ${H}" role="img" aria-label="ระดับน้ำเทียบตลิ่ง">
      <rect x="${x(-1).toFixed(1)}" y="6" width="${(x(0) - x(-1)).toFixed(1)}" height="14" fill="#f08c2e" opacity=".25"/>
      <rect x="${x(0).toFixed(1)}" y="6" width="${(x(hi) - x(0)).toFixed(1)}" height="14" fill="#d7263d" opacity=".15"/>
      <line x1="6" y1="13" x2="${W - 6}" y2="13" stroke="var(--ink-3)" stroke-width="1"/>
      <line x1="${x(0).toFixed(1)}" y1="3" x2="${x(0).toFixed(1)}" y2="23" stroke="var(--ink-2)" stroke-width="1.5"/>
      ${mk}${nowV != null ? `<circle cx="${x(nowV).toFixed(1)}" cy="13" r="6" fill="#0d6c78" stroke="#fff" stroke-width="2"><title>ตอนนี้ ${fmt(nowV, 2)} ม.</title></circle>` : ""}</svg>`;
  };
  const stRows = Object.entries(T.stations || {}).map(([code, st]) => {
    const n = now.levels?.[code];
    const s = (S.latest?.stations || []).find((x) => x.k === st.k);
    const an = s ? analogShort(s) : "";
    const [pk, pkT] = peak(st.id);
    const r19 = ref(st.id, 19), r21 = ref(st.id, 21);
    return `<div class="trk-st"><div><b>${esc(code)}</b> ${esc(st.name)} <span class="note">${esc(st.role || "")}</span></div>
      <div>ตอนนี้ <b>${n ? rel(n.rel) : "–"}</b> ม.${n?.slope != null && Math.abs(n.slope) > 0.005 ? ` <span class="note">${n.slope > 0 ? "กำลังขึ้น" : "กำลังลด"} ${fmt(Math.abs(n.slope), 2)} ม./ชม.</span>` : ""}
      <span class="note"> · ปี 68: 19 พ.ย. ${rel(r19)} → 21 พ.ย. ${rel(r21)} → ยอด ${rel(pk)} (${esc(pkT)})</span></div>
      ${scale([[r19, "19 พ.ย. 68", "#bbb"], [r21, "21 พ.ย. 68", "#888"], [pk, "ยอดน้ำ 68", "#444"]], n ? n.rel : null)}
      ${an ? `<div class="note">${esc(an)}</div>` : ""}</div>`;
  }).join("");
  const nx = (T.next || []).map((d) => `<tr><td>${thDate(d.date)}</td>${areas.map((a) => `<td class="n">${mm(d.fc?.[a])}</td>`).join("")}</tr>`).join("");
  const today = new Date(S.latest?.generated_at || Date.now()).toLocaleDateString("sv-SE", { timeZone: "Asia/Bangkok" });
  const codes = Object.keys(T.stations || {});
  const dayRows = Object.keys(T.days).sort().reverse().map((d) => {
    const r = T.days[d];
    const partial = !r.obs_final && r.obs_until ? `<br><span class="note">ถึง ${new Date(r.obs_until).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" })} น.</span>` : "";
    const ratio = (a) => { const f = r.fc?.[a]?.mean, o = r.obs?.[a]?.max; return r.obs_final && f > 0 && o > f * 2 ? ` <span class="up">×${fmt(o / f, 1)}</span>` : ""; };
    return `<tr${d === today ? ' class="today"' : ""}><td>${thDate(d)}${partial}</td>
      ${areas.map((a) => `<td class="n">${mm(r.fc?.[a])}</td>`).join("")}
      ${areas.map((a, i) => `<td class="n${i === 0 ? " sep" : ""}">${r.obs?.[a] ? `${fmt(r.obs[a].max)}${ratio(a)}` : "–"}</td>`).join("")}
      ${codes.map((c, i) => `<td class="n${i === 0 ? " sep" : ""}">${rel(r.levels?.[c]?.max_rel)}</td>`).join("")}
      <td class="sep">${chip(r.scenario, true)}</td></tr>`;
  }).join("");
  const th = T.thresholds || {};
  return `<div class="card tracker" id="tracker"><h3>ติดตามรายวัน: ${esc(T.label || "")}</h3>
    <div class="scn-now">${chip(sc)}<span class="note">ตอนนี้ · ${timeTH(now.at)}</span></div>
    ${sc ? `<p class="note">${esc(SCN[sc][1])}</p>` : ""}
    ${now.signals?.length ? `<ul class="sig">${now.signals.map((x) => `<li>${chip(x.s, true)} ${esc(x.text)}</li>`).join("")}</ul>` : '<p class="note">ยังไม่มีฝนหนัก ≥ ' + fmt(th.heavy_mm_h) + ' มม./ชม. ฝน 24 ชม. ยังไม่ถึง ' + fmt(th.rain24_b) + ' มม. และสถานีหลักยังห่างตลิ่งเกิน ' + fmt(th.near_bank_m) + ' ม.</p>'}
    <p><b>สถานีหลักเทียบเส้นทางปี 2568</b> <span class="note">(ระดับน้ำเทียบตลิ่ง ม. · ติดลบ = ต่ำกว่าตลิ่ง)</span></p>
    ${stRows}
    <p class="note trk-legend"><span class="dotc" style="background:#0d6c78"></span>ตอนนี้ <span class="dotc" style="background:#bbb"></span>19 พ.ย. 68 <span class="dotc" style="background:#888"></span>21 พ.ย. 68 <span class="dotc" style="background:#444"></span>ยอดน้ำ 68 · เส้นตั้ง = ตลิ่ง · แถบส้ม = ห่างตลิ่งไม่เกิน 1 ม. · ระดับในเมืองท่วมก่อน X.44 ล้นตลิ่งได้ (ปี 68 ราว 10 ชม.)</p>
    <p><b>ฝนพยากรณ์ 3 วันข้างหน้า</b> <span class="note">(มม./วัน 07:00–07:00 น. · เฉลี่ย 3 โมเดล และค่าสูงสุดในวงเล็บ)</span></p>
    <table class="t trk"><tr><th>วัน</th>${areas.map((a) => `<th>${esc(A[a])}</th>`).join("")}</tr>${nx}</table>
    <p class="note">ปี 2568 ฝนจริงมากกว่าพยากรณ์ล่วงหน้า 1 วัน 4–7 เท่า ตัวเลขพยากรณ์จึงใช้ดูแนวโน้ม ไม่ใช่ปริมาณที่จะตกจริง</p>
    <p><b>บันทึกรายวัน</b> <span class="note">เลื่อนตารางไปทางขวาได้ →</span></p>
    <table class="t trk wide"><tr><th rowspan="2">วัน</th><th colspan="${areas.length}">ฝนพยากรณ์ (มม.)</th><th colspan="${areas.length}" class="sep">ฝนจริงสูงสุด (มม.)</th><th colspan="${codes.length}" class="sep">ระดับน้ำสูงสุดเทียบตลิ่ง (ม.)</th><th rowspan="2" class="sep">สถานการณ์</th></tr>
    <tr>${areas.map((a) => `<th>${esc(A[a])}</th>`).join("")}${areas.map((a, i) => `<th${i === 0 ? ' class="sep"' : ""}>${esc(A[a])}</th>`).join("")}${codes.map((c, i) => `<th${i === 0 ? ' class="sep"' : ""}>${esc(c)}</th>`).join("")}</tr>${dayRows}</table>
    <p class="note">สถานการณ์ ก. ฝน ≥ ${fmt(th.heavy_mm_h)} มม./ชม. หรือฝนหนักในเมือง · ข. X.174 ห่างตลิ่ง ≤ ${fmt(th.near_bank_m)} ม. หรือฝน 24 ชม. ≥ ${fmt(th.rain24_b)} มม. · ค. สะเดา/X.173A/X.44 ห่างตลิ่ง ≤ ${fmt(th.near_bank_m)} ม. · เกณฑ์ตั้งจากการวิเคราะห์ พ.ย. 2568 เป็นค่าเบื้องต้น ใช้ดูทิศทาง ไม่ใช่ประกาศเตือนภัย ให้ติดตามประกาศจังหวัดและ ปภ. 1784
    · พยากรณ์ของแต่ละวันล็อกตอน 07:00 น. ของวันนั้น · ฝนจริง = สถานีที่ฝนมากที่สุดในพื้นที่ ช่วง 07:00–07:00 น. ไม่นับสถานีที่ยังไม่มีสถานีข้างเคียงยืนยัน · ×N = ฝนจริงมากกว่าพยากรณ์ N เท่า · ฝั่งเขาคอหงส์ใช้พยากรณ์ที่จุดกึ่งกลาง อ.นาหม่อม และสถานีวัดฝนในรัศมี 6 กม. จากเขาคอหงส์</p></div>`;
}

function stormScoreCard() {
  const sr = S.latest?.storm_risk;
  if (!sr) return "";
  const sc = (x) => `จับได้ ${x.hit} · พลาด ${x.miss} · เตือนผิด ${x.false_alarm} · วันเงียบถูก ${x.quiet} <span class="note">(${x.days} อำเภอ-วัน)</span>`;
  const names = Object.fromEntries((S.admin?.amphoes || []).map((a) => [a.ac, a.a]));
  const days = Object.keys(sr.recent || {}).sort().reverse();
  const rows = days.flatMap((d) => Object.entries(sr.recent[d]).map(([ac, e]) => ({ d, ac, e }))).filter((r) => r.e.issued);
  const verdict = (e, d) => {
    const today = new Date(S.latest?.generated_at || Date.now()).toLocaleDateString("sv-SE", { timeZone: "Asia/Bangkok" });
    if (d >= today) return '<span class="note">ยังไม่จบวัน</span>';
    const hv = (e.obs_max || 0) >= sr.heavy_mm_h;
    return e.flag && hv ? '<span class="dn">จับได้</span>' : hv ? '<span class="up">พลาด</span>' : e.flag ? '<span class="up">เตือนผิด</span>' : '<span class="note">เงียบถูก</span>';
  };
  return `<div class="card"><h3>ผลของ "วันเสี่ยงฝนฟ้าคะนองรุนแรง" (ทดลอง)</h3>
    <div class="kv"><span class="k">${(sr.focus || []).map((a) => "อ." + (names[a] || a)).join(" / ")}</span><span class="v">${sc(sr.score_focus)}</span>
    <span class="k">ทุกอำเภอ (31 วันล่าสุด)</span><span class="v">${sc(sr.score_all)}</span></div>
    ${rows.length ? `<table class="t"><tr><th>วันที่</th><th>อำเภอ</th><th>CAPE ตอนเช้า</th><th>ฝนจริงสูงสุด</th><th>ผล</th></tr>${rows.map(({ d, ac, e }) => `<tr><td>${thDate(d)}</td><td>${esc(names[ac] || ac)}</td><td class="n">${fmt(e.cape)}${e.flag ? " ⚠" : ""}</td><td class="n">${e.obs_max != null ? fmt(e.obs_max, 1) + " มม./ชม." : "–"}${e.obs_time ? ` <span class="note">${esc(e.obs_time)}</span>` : ""}</td><td>${verdict(e, d)}</td></tr>`).join("")}</table>` : '<p class="note">เริ่มบันทึกตั้งแต่เช้าพรุ่งนี้ ระบบตัดสินว่าเป็นวันเสี่ยงหรือไม่จากรอบอัปเดตแรกหลัง 06:00 น. (ไม่เกิน 10:00 น.) แล้วล็อกไว้ เพื่อตรวจกับฝนที่ตกจริงทั้งวันอย่างยุติธรรม</p>'}
    <p class="note">ฝนหนัก = มีสถานีในอำเภอวัดได้ ≥ ${sr.heavy_mm_h} มม./ชม. · จะตัดสินว่าควรเปิดส่งแจ้งเตือนหรือไม่หลังสะสมผลช่วงมรสุมพฤศจิกายน</p></div>`;
}

function hero(title, sub, lv, n) {
  return `<div class="hero"><div style="flex:1"><h2>${esc(title)}</h2><div class="sub">${esc(sub)}</div>
    <div style="margin-top:6px">${countsBar(n)}</div><div class="sub" style="margin-top:4px">${esc(countsText(n))}</div></div>${badge(lv, true)}</div>`;
}

function childList(items, noFilter) {
  const its = items.filter((x) => noFilter || !S.onlyRisk || (x.lv || 0) > 0)
    .sort((a, b) => (b.lv ?? -1) - (a.lv ?? -1) || a.name.localeCompare(b.name, "th"));
  return `${noFilter ? "" : `<div class="row-tools"><label><input type="checkbox" id="onlyRisk" ${S.onlyRisk ? "checked" : ""}> แสดงเฉพาะที่มีความเสี่ยง</label></div>`}
    <ul class="list">${its.map((x) => `<li data-${x.attr}="${x.key}"><span class="dot" style="background:${x.lv == null ? COLX : COL[x.lv]}"></span>
    <div><div class="nm">${esc(x.name)}</div><div class="meta">${esc(x.meta || "")}</div>${x.n ? `<div style="margin-top:4px">${countsBar(x.n)}</div>` : ""}</div>${badge(x.lv)}</li>`).join("") || '<li class="note">ไม่มีพื้นที่ที่มีความเสี่ยง</li>'}</ul>`;
}

function rainCard(ac) {
  const r = S.latest?.amphoes?.[ac]?.rain;
  if (!r) return "";
  if (r.n24 == null) return `<div class="card"><h3>ฝน (ระดับอำเภอ)</h3><div class="note">ไม่มีข้อมูลฝนพยากรณ์ในรอบนี้</div></div>`;
  const models = Object.entries(r.models || {}).map(([m, v]) => `<tr><td>${esc(m.replace("_seamless", "").replace("_ifs025", ""))}</td><td class="n">${fmt(v.n24)}</td><td class="n">${fmt(v.n48)}</td><td class="n">${fmt(v.n72)}</td></tr>`).join("");
  return `<div class="card"><h3>ฝน (ระดับอำเภอ) ${r.lv ? badge(r.lv) : ""}</h3>
    <div class="kv">
      <span class="k">ฝนพยากรณ์ 24 ชม.ข้างหน้า (เฉลี่ย ${Object.keys(r.models).length} โมเดล)</span><span class="v">${fmt(r.n24)} มม.</span>
      <span class="k">48 / 72 ชม.ข้างหน้า</span><span class="v">${fmt(r.n48)} / ${fmt(r.n72)} มม.</span>
      <span class="k">โมเดลที่คาดฝนมากที่สุด (24 ชม.)</span><span class="v">${fmt(r.n24_max)} มม.</span>
      <span class="k">ฝนที่ตกแล้ว 24 ชม. ${r.p24_obs != null ? (r.n_gauges >= 3 ? `(สถานีอันดับ 3 จาก ${r.n_gauges} สถานี · สูงสุด ${fmt(r.p24_obs_max ?? r.p24_obs)} มม.)` : `(จาก ${r.n_gauges} สถานี)`) : "(ประมาณจากโมเดล)"}</span><span class="v">${fmt(r.p24_obs ?? r.p24_model)} มม.</span>
      <span class="k">ฝนสะสม (ที่ตกแล้ว + 48 ชม.ข้างหน้า)</span><span class="v">${fmt(r.acc)} มม.</span>
      <span class="k">ความชื้นดิน 3–9 ซม.</span><span class="v">${r.soil != null ? fmt(r.soil, 2) + " ม³/ม³" : "–"}</span>
    </div>
    ${spark(r.h72)}
    <table class="t"><tr><th>โมเดล</th><th>24 ชม.</th><th>48 ชม.</th><th>72 ชม.</th></tr>${models}</table>
    <div class="note">ฝนพยากรณ์ที่จุดกึ่งกลางอำเภอ ทุกตำบลในอำเภอใช้ค่าเดียวกัน · ฝนที่ตกแล้วใช้สถานีอันดับ 3 เพื่อไม่ให้ฝนหนักเฉพาะจุดเดียวยกทั้งอำเภอ (ฝนหนักเฉพาะจุดในเมืองดูที่การ์ดฝนหนักในเมือง)</div></div>`;
}

const zoneOf = (tc) => { const p = S.props[tc]; const z = (S.latest?.urban_rain_cfg?.zones || []).find((z) => p && z.amphoe === p.a && z.tambons.includes(p.t)); return z; };
function urbanCard(name) {
  const u = (S.latest?.urban_rain || []).find((x) => x.name === name);
  const c = S.latest?.urban_rain_cfg || {};
  if (!u) return "";
  const est = u.src && u.src !== "สสน. 1 ชม.";
  return `<div class="card"><h3>ฝนหนักใน${esc(u.name)} ${badge(u.lv)}</h3><div class="kv">
    <span class="k">ฝน 1 ชม. ล่าสุด (สถานีที่มากที่สุด)</span><span class="v">${fmt(u.i1, 1)} มม.${u.g1 ? ` <span class="note">${esc(u.g1)}</span>` : ""}</span>
    <span class="k">ฝน 3 ชม. ล่าสุด</span><span class="v">${fmt(u.i3, 1)} มม.${u.g3 ? ` <span class="note">${esc(u.g3)}</span>` : ""}</span>
    <span class="k">สถานีวัดฝนในเขตที่ข้อมูลสด</span><span class="v">${fmt(u.n_gauges)}</span>
    <span class="k">เกณฑ์ เฝ้าระวัง / เตือนภัย</span><span class="v">1 ชม. ≥${c.watch_1h}/${c.warning_1h} · 3 ชม. ≥${c.watch_3h}/${c.warning_3h} มม.</span></div>
    ${u.data_time ? `<div class="note">เวลาที่สถานีบันทึก: ${timeTH(u.data_time)} (สิ้นสุดชั่วโมงที่วัดฝน)</div>` : ""}
    ${(u.cameras || []).length ? `<p class="note"><b>ดูสภาพคลองจริง:</b> ${u.cameras.map((c) => `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a> <span class="note">(${esc(c.credit || "")})</span>`).join(" · ")}</p>` : ""}
    <div class="note">${est ? "ค่าประมาณจากการเพิ่มของฝนสะสม 24 ชม. ระหว่างรอบ อาจต่ำกว่าจริง · " : ""}ฝนหนักระยะสั้นทำให้คู คลองระบาย และถนนในเมืองท่วมได้ก่อนคลองสายหลัก (20 ต.ค. 2569 ฝนหนักฝั่งคอหงส์ คลอง 30 เมตรเกือบล้น · 28 ต.ค. ฝนหนักพอกันแต่ตกกลางเมือง คลองยังอยู่ระดับปกติ)</div></div>`;
}

function damCard(d) {
  if (!d) return "";
  const r = d.reservoir || {}, tw = d.tailwater || {}, hii = d.hii || {}, past = d.past || {};
  const ref = (d.ref_points || [])[0];
  const pr = past.reservoir, pt = past.tailwater;
  const relVsPlan = hii.release != null && d.plan_per_day ? hii.release / d.plan_per_day : null;
  return `<div class="card dam"><h3>${esc(d.name)} ${d.tailwater_state != null ? badge(d.tailwater_state) : '<span class="note">ท้ายเขื่อนข้อมูลไม่สด</span>'}</h3><div class="kv">
    <span class="k">ระดับอ่าง ${esc(r.code || "")}</span><span class="v">${fmt(r.level, 2)} ม.รทก.${r.slope != null ? ` ${r.slope > 0 ? "▲" : r.slope < 0 ? "▼" : ""} ${fmt(Math.abs(r.slope), 2)} ม./ชม.` : ""} <span class="note">${ago(r.time)}</span></span>
    ${hii.storage != null ? `<span class="k">น้ำในอ่าง${hii.date ? " " + esc(String(hii.date).slice(5, 10).split("-").reverse().join("/")) : ""}</span><span class="v">${fmt(hii.storage)} ล้าน ลบ.ม.${hii.storage_pct != null ? ` (${fmt(hii.storage_pct, 1)}%)` : ""}</span>` : ""}
    ${hii.inflow != null ? `<span class="k">ไหลเข้า / ระบาย</span><span class="v">${fmt(hii.inflow, 2)} / ${fmt(hii.release, 2)} ล้าน ลบ.ม./วัน${hii.spill ? ` · ล้นทางระบาย ${fmt(hii.spill, 2)}` : ""}</span>` : ""}
    ${d.plan_mcm ? `<span class="k">แผนระบายเดือนนี้ (กฟผ.)</span><span class="v">${fmt(d.plan_mcm)} ล้าน ลบ.ม. (เฉลี่ย ${fmt(d.plan_per_day, 2)}/วัน)${relVsPlan != null ? ` · จริง ${fmt(relVsPlan * 100)}% ของแผน` : ""}</span>` : ""}
    <span class="k">ท้ายเขื่อน ${esc(tw.code || "")}</span><span class="v">${fmt(tw.level, 2)} ม.รทก. <span class="note">${ago(tw.time)}</span></span>
    ${pr ? `<span class="k">อ่าง พ.ย. 68</span><span class="v">${fmt(pr.start, 2)} → สูงสุด ${fmt(pr.max, 2)} ม. (${esc(pr.max_time)})</span>` : ""}
    ${pt ? `<span class="k">ท้ายเขื่อน พ.ย. 68</span><span class="v">สูงสุด ${fmt(pt.max, 2)} ม. (${esc(pt.max_time)})</span>` : ""}
    </div>
    ${tw.why ? `<div class="note">ท้ายเขื่อน: ${esc(tw.why)}</div>` : ""}
    ${ref && r.level != null ? `<div class="note">จุดเทียบ: ${esc(ref.note)} ระดับอ่าง ${fmt(ref.level_m, 1)} ม. ≈ ${fmt(ref.storage_mcm)} ล้าน ลบ.ม. — ตอนนี้${Math.abs(r.level - ref.level_m) < 0.5 ? "ใกล้เคียงกัน" : r.level > ref.level_m ? `สูงกว่า ${fmt(r.level - ref.level_m, 1)} ม.` : `ต่ำกว่า ${fmt(ref.level_m - r.level, 1)} ม.`} · ความจุปกติ ${fmt(d.capacity_mcm)} ล้าน ลบ.ม.</div>` : ""}
    <div class="note">เขื่อนบางลางอยู่ลุ่มน้ำปัตตานี ไม่ไหลมาหาดใหญ่ · มีผลกับอำเภอท้ายน้ำ: ${esc((d.downstream_amphoes || []).join(", "))} · แผน: ${esc(d.plan_source || "")}</div></div>`;
}

function tambonDetail(tc) {
  const p = S.props[tc];
  const t = S.latest?.tambons?.[tc];
  const sts = (S.latest?.stations || []).filter((s) => s.tc === tc);
  const rgs = (S.latest?.rain_gauges || []).filter((g) => g.tc === tc);
  let h = `<div class="hero"><div style="flex:1"><h2>ต.${esc(p.t)}</h2><div class="sub">อ.${esc(p.a)} จ.${esc(p.p)} · ${fmt(p.km2)} ตร.กม.</div></div>${badge(t ? t.lv : null, true)}</div>`;
  h += `<div class="card"><h3>ทำไมถึงอยู่ระดับนี้</h3>${t?.reasons?.length
    ? t.reasons.map((r) => `<div class="reason">${badge(r.lv)}<div><span class="note">${SRC_LABEL[r.src] || r.src}</span><br>${esc(r.text)}</div></div>`).join("")
    : '<div class="note">ไม่พบปัจจัยเสี่ยงจากข้อมูลที่มีอยู่</div>'}</div>`;
  if (!sts.length) h += `<div class="warnnote">ตำบลนี้ไม่มีสถานีวัดระดับน้ำ ระดับเตือนภัยมาจากฝนพยากรณ์ระดับอำเภอ น้ำป่า และน้ำจากต้นน้ำเท่านั้น</div>`;
  if (sts.length) h += `<div class="card"><h3>สถานีวัดระดับน้ำในตำบล</h3>${sts.map(stationRow).join("")}</div>`;
  if (BM()) {
    const bc = sts.map(benchCard).filter(Boolean);
    if (bc.length) { h += bc.join(""); ensureHist(); }
  }
  const z = zoneOf(tc);
  if (z) h += urbanCard(z.name);
  h += rainCard(p.ac);
  if (rgs.length) h += `<div class="card"><h3>สถานีวัดฝนในตำบล</h3><div class="kv">${rgs.map((g) => `<span class="k">${esc(g.name)}${g.suspect ? ' <span class="tag-sus">ยังไม่ยืนยัน</span>' : ""}</span><span class="v">${fmt(g.r24, 1)} มม./24 ชม.${g.i1 ? ` · ${fmt(g.i1, 1)} มม./1 ชม.` : ""} <span class="note">${ago(g.time)}</span>${g.suspect ? `<br><span class="note">${esc(g.suspect_why)}</span>` : ""}</span>`).join("")}</div></div>`;
  for (const d of S.latest?.dams || []) if ((d.downstream_amphoes || []).includes(p.a)) h += damCard(d);
  const ff = S.latest?.flashflood?.[tc];
  if (ff) h += `<div class="card"><h3>รายงานน้ำท่วมฉับพลันของ สสน.</h3><div class="note">${esc(ff.raw)}</div></div>`;
  const rd = roadGroups().filter((g) => g.tcs.has(tc));
  h += `<div class="card"><h3>ถนนสายหลักที่ผ่านตำบลนี้</h3>${S.roads
    ? (rd.length ? `<ul class="list">${rd.map((g) => `<li data-road="${esc(g.key)}"><span class="dot" style="background:${lvOf(tc) ? COL[lvOf(tc)] : "#5b6670"}"></span><div><div class="nm">${esc(g.title)}</div><div class="meta">ผ่าน ${g.tcs.size} ตำบล · ระดับสูงสุดตลอดสาย ${LV[g.lv] ?? "–"}</div></div>${badge(lvOf(tc))}</li>`).join("")}</ul>` : '<div class="note">ไม่มีถนนสายหลักในข้อมูล</div>')
    : '<div class="note">ยังไม่ได้สร้างชั้นข้อมูลถนน (รัน workflow "สร้างชั้นข้อมูลถนน")</div>'}</div>`;
  return h;
}

function bindArea(el) {
  const q = $("#q", el);
  q.addEventListener("input", () => { S.q = q.value; const pos = q.selectionStart; renderArea(); const n = $("#q"); n.focus(); n.setSelectionRange(pos, pos); });
  el.querySelectorAll("[data-go]").forEach((a) => a.addEventListener("click", () => {
    S.q = "";
    const g = a.dataset.go;
    select(g === "" ? {} : g === "p" ? { pc: S.sel.pc } : { pc: S.sel.pc, ac: S.sel.ac });
  }));
  el.querySelectorAll("li[data-pc]").forEach((li) => li.addEventListener("click", () => select({ pc: li.dataset.pc })));
  el.querySelectorAll("li[data-ac]").forEach((li) => li.addEventListener("click", () => { const a = S.admin.amphoes.find((x) => x.ac === li.dataset.ac); select({ pc: a.pc, ac: a.ac }); }));
  el.querySelectorAll("li[data-tc]").forEach((li) => li.addEventListener("click", () => { S.q = ""; const p = S.props[li.dataset.tc]; select({ pc: p.pc, ac: p.ac, tc: p.tc }); }));
  el.querySelectorAll("li[data-road]").forEach((li) => li.addEventListener("click", () => { S.openRoad = li.dataset.road; S.rq = ""; showTab("roads"); focusRoad(li.dataset.road); }));
  const o = $("#onlyRisk", el);
  if (o) o.addEventListener("change", () => { S.onlyRisk = o.checked; renderArea(); });
}

/* ------------------------------------------------------------------ tab: roads */
function roadTitle(p) {
  const ref = (p.ref || "").split(";")[0].trim();
  const num = /^\d+$/.test(ref) ? `ทางหลวงหมายเลข ${ref}` : ref;
  return [num, p.name].filter(Boolean).join(" · ") || "ถนนไม่มีชื่อ";
}
let _roadCache = null;
function roadGroups() {
  if (!S.roads) return [];
  if (!_roadCache) {
    const m = new Map();
    for (const f of S.roads.features) {
      const p = f.properties;
      const key = (p.ref || "").split(";")[0].trim() || p.name || "";
      if (!key) continue;
      if (!m.has(key)) m.set(key, { key, title: roadTitle(p), tcs: new Set(), feats: [], hw: p.hw });
      const g = m.get(key);
      g.tcs.add(p.tc);
      g.feats.push(f);
      if (!g.title.includes("·") && p.name && p.ref) g.title = roadTitle(p);
    }
    _roadCache = [...m.values()];
  }
  for (const g of _roadCache) g.lv = Math.max(0, ...[...g.tcs].map((tc) => lvOf(tc) ?? 0));
  return _roadCache;
}
function renderRoads() {
  const el = $("#tab-roads");
  if (!S.roads) {
    el.innerHTML = `<div class="warnnote">ยังไม่มีชั้นข้อมูลถนน ให้รัน workflow <b>สร้างชั้นข้อมูลถนน</b> ในแท็บ Actions ของ GitHub หนึ่งครั้ง (ดูคู่มือ README)</div>`;
    return;
  }
  const q = S.rq.trim();
  let gs = roadGroups().filter((g) => !q || g.title.includes(q) || g.key.includes(q));
  gs.sort((a, b) => b.lv - a.lv || (parseInt(a.key) || 1e9) - (parseInt(b.key) || 1e9));
  const total = gs.length;
  gs = gs.slice(0, q ? 200 : 80);
  el.innerHTML = `<input class="search" id="rq" placeholder="ค้นหาเลขทางหลวงหรือชื่อถนน เช่น 4, 43, เพชรเกษม" value="${esc(S.rq)}">
    <p class="note">ระดับของถนนอนุมานจากระดับเตือนภัยของตำบลที่ถนนผ่าน ยังไม่ใช่สถานะถนนปิดจริง</p>
    <ul class="list">${gs.map((g) => `<li data-road="${esc(g.key)}"><span class="dot" style="background:${g.lv ? COL[g.lv] : "#5b6670"}"></span>
      <div><div class="nm">${esc(g.title)}</div><div class="meta">ผ่าน ${g.tcs.size} ตำบล${g.lv ? " · ช่วงที่เสี่ยง " + [...g.tcs].filter((tc) => lvOf(tc) >= 1).length + " ตำบล" : ""}</div>
      ${S.openRoad === g.key ? roadDetail(g) : ""}</div>${badge(g.lv)}</li>`).join("")}</ul>
    ${total > gs.length ? `<p class="note">แสดง ${gs.length} จาก ${total} สาย พิมพ์ค้นหาเพื่อดูสายอื่น</p>` : ""}`;
  const inp = $("#rq", el);
  inp.addEventListener("input", () => { S.rq = inp.value; const pos = inp.selectionStart; renderRoads(); const n = $("#rq"); n.focus(); n.setSelectionRange(pos, pos); });
  el.querySelectorAll("li[data-road]").forEach((li) => li.addEventListener("click", (e) => {
    if (e.target.closest("[data-tc]")) return;
    S.openRoad = S.openRoad === li.dataset.road ? null : li.dataset.road;
    renderRoads();
    if (S.openRoad) focusRoad(S.openRoad);
  }));
  el.querySelectorAll("[data-tc]").forEach((x) => x.addEventListener("click", () => { const p = S.props[x.dataset.tc]; select({ pc: p.pc, ac: p.ac, tc: p.tc }); }));
}
function roadDetail(g) {
  const tcs = [...g.tcs].filter((tc) => S.props[tc]).sort((a, b) => (lvOf(b) ?? 0) - (lvOf(a) ?? 0));
  return `<table class="t" style="margin-top:6px">${tcs.map((tc) => `<tr class="click" data-tc="${tc}"><td>ต.${esc(S.props[tc].t)}</td><td>อ.${esc(S.props[tc].a)}</td><td>${badge(lvOf(tc))}</td></tr>`).join("")}</table>`;
}
function focusRoad(key) {
  const g = roadGroups().find((x) => x.key === key);
  if (!g) return;
  if (roadLayer && !map.hasLayer(roadLayer) && S.layers.rd !== false) roadLayer.addTo(map);
  map.fitBounds(L.geoJSON({ type: "FeatureCollection", features: g.feats }).getBounds(), { padding: [30, 30], maxZoom: 13 });
  renderRoads();
}

/* ------------------------------------------------------------------ tab: stations */
function renderStations() {
  const el = $("#tab-stations");
  const L0 = S.latest;
  const ur = L0?.urban_rain || [];
  let h = ur.filter((u) => u.lv).map((u) => urbanCard(u.name)).join("");
  const calm = ur.filter((u) => !u.lv);
  if (calm.length) h += `<div class="card"><h3>ฝนหนักในเมือง</h3><div class="kv">${calm.map((u) => `<span class="k">${esc(u.name)}</span><span class="v">${fmt(u.i1, 1)} มม./1 ชม. · ${fmt(u.i3, 1)} มม./3 ชม. ${badge(u.lv)}</span>`).join("")}</div></div>`;
  h += (L0?.dams || []).map(damCard).join("");
  for (const c of L0?.chains || []) {
    h += `<div class="card"><h3>${esc(c.name)} ${c.trigger ? badge(c.trigger.lv) : ""}</h3><div class="chain">`;
    c.stations.forEach((s, i) => {
      h += `<div class="node">${badge(s.found ? s.state : null)}<div><b>${esc(s.label)}</b><br><span class="note">${s.found
        ? (s.stale ? (s.state ? "หยุดส่งข้อมูลขณะน้ำสูง" : "ข้อมูลไม่เป็นปัจจุบัน") : `ระดับ ${fmt(s.level, 2)} · ตลิ่ง ${fmt(s.bank, 2)} ม.รทก.${s.eta_h != null ? ` · ถึงตลิ่งใน ~${fmt(s.eta_h)} ชม.` : ""}`)
        : "ไม่พบสถานีนี้ในข้อมูล สสน."}</span>${(() => { const st = (L0.stations || []).find((x) => x.k === s.k); const a = st && analogShort(st); return a ? `<br><span class="bm-short">${esc(a)}</span>` : ""; })()}</div></div>`;
      if (i < c.stations.length - 1) h += `<div class="lag">น้ำเดินทาง ${s.lag_h_to_next != null ? "~" + s.lag_h_to_next + " ชม." : "ยังไม่ทราบเวลา"}</div>`;
    });
    h += `</div>${c.trigger ? `<div class="warnnote">${esc(c.trigger.msg)}</div>` : ""}</div>`;
  }
  const sts = [...(L0?.stations || [])].sort((a, b) => ((b.state ?? -1) - (a.state ?? -1)) || ((a.gap ?? 99) - (b.gap ?? 99)));
  h += `<div class="card"><h3>สถานีวัดระดับน้ำในพื้นที่ (${sts.length})</h3><table class="t"><tr><th>สถานี</th><th>เทียบตลิ่ง</th><th>แนวโน้ม</th><th></th></tr>
    ${sts.map((s) => `<tr class="click" data-tc="${s.tc || ""}"><td>${esc(s.name)}<br><span class="note">${esc(s.code || "")} ${s.tc ? "ต." + esc(S.props[s.tc].t) : ""} · ${ago(s.time)}</span>${analogShort(s) ? `<br><span class="bm-short">${esc(analogShort(s))}</span>` : ""}</td>
    <td class="n">${s.gap != null ? (s.gap < 0 ? "+" : "−") + fmt(Math.abs(s.gap), 2) + " ม." : "–"}${s.norm ? '<br><span class="note">ใช้ระดับปกติ</span>' : ""}</td>
    <td class="n">${s.slope != null ? (s.slope > 0 ? "▲ " : s.slope < 0 ? "▼ " : "") + fmt(Math.abs(s.slope), 2) : "–"}</td>
    <td>${badge(s.state)}</td></tr>`).join("")}</table>
    <p class="note">เทียบตลิ่ง: − ต่ำกว่าตลิ่ง, + สูงกว่าตลิ่ง · แนวโน้ม ม./ชม. คำนวณจาก 3 ชม.ล่าสุด (ระบบต้องเก็บข้อมูลอย่างน้อย 3 รอบก่อน)</p></div>`;
  el.innerHTML = h;
  el.querySelectorAll("tr[data-tc]").forEach((tr) => tr.addEventListener("click", () => { const p = S.props[tr.dataset.tc]; if (p) select({ pc: p.pc, ac: p.ac, tc: p.tc }); }));
}

/* ------------------------------------------------------------------ tab: gaps */
function renderGaps() {
  const el = $("#tab-gaps");
  const L0 = S.latest || {};
  const g = L0.gaps || {};
  const pct = (a, b) => (b ? ` (${Math.round((100 * a) / b)}%)` : "");
  let h = `<div class="card"><h3>แหล่งข้อมูลรอบล่าสุด</h3><div class="src">${Object.values(L0.sources || {}).map((s) => `<span class="${s.ok ? "ok" : "bad"}">${s.ok ? "✓" : "✗"}</span>
    <span>${esc(s.label)}${s.n != null ? ` · ${s.n} รายการ` : ""}${s.note ? ` · ${esc(s.note)}` : ""}${s.error ? `<br><span class="note">${esc(s.error)}</span>` : ""}</span>`).join("")}</div></div>`;
  h += `<div class="card"><h3>ความครอบคลุมของข้อมูล</h3><div class="kv">
    <span class="k">ตำบลทั้งหมด</span><span class="v">${fmt(g.tambons)}</span>
    <span class="k">มีสถานีวัดระดับน้ำ</span><span class="v">${fmt(g.tambons_with_station)}${pct(g.tambons_with_station, g.tambons)}</span>
    <span class="k">มีสถานีวัดระดับน้ำที่ข้อมูลสด</span><span class="v">${fmt(g.tambons_with_fresh_station)}${pct(g.tambons_with_fresh_station, g.tambons)}</span>
    <span class="k">มีสถานีวัดฝน</span><span class="v">${fmt(g.tambons_with_gauge)}${pct(g.tambons_with_gauge, g.tambons)}</span>
    <span class="k">ใช้ได้แค่ฝนพยากรณ์</span><span class="v">${fmt(g.tambons_forecast_only)}${pct(g.tambons_forecast_only, g.tambons)}</span>
    <span class="k">สถานีวัดระดับน้ำ (สด / ทั้งหมด)</span><span class="v">${fmt(g.stations_fresh)} / ${fmt(g.stations)}</span>
    <span class="k">สถานีวัดฝน</span><span class="v">${fmt(g.rain_gauges)}</span></div>
    ${g.chain_missing?.length ? `<div class="warnnote">สถานีในห่วงโซ่ที่หาไม่พบ: ${esc(g.chain_missing.join(", "))} — ตรวจรหัสใน config.json</div>` : ""}
    ${g.stations_stale?.length ? `<p class="note"><b>สถานีที่ข้อมูลไม่สด:</b> ${g.stations_stale.map((s) => `${esc(s.name)} (${fmt(s.age_h)} ชม.)`).join(", ")}</p>` : ""}
    ${g.stations_norm_mode?.length ? `<p class="note"><b>สถานีที่ระดับน้ำปกติอยู่ใกล้ตลิ่งหรือขึ้นลงทุกวัน</b> (น้ำทะเล ทะเลสาบ หรือการปล่อยน้ำจากเขื่อน) ระบบเทียบกับระดับสูงปกติของสถานีเองแทนระยะถึงตลิ่ง: ${g.stations_norm_mode.map((s) => `${esc(s.name)} ${esc(s.code)}`).join(", ")}</p>` : ""}
    ${g.stations_no_bank?.length ? `<p class="note"><b>สถานีที่ไม่มีระดับตลิ่ง</b> (คำนวณระยะถึงตลิ่งไม่ได้): ${g.stations_no_bank.map((s) => esc(s.name)).join(", ")}</p>` : ""}</div>`;
  const th = L0.thresholds;
  if (th) h += `<div class="card"><h3>เกณฑ์ที่ใช้คำนวณ (ค่าเริ่มต้น ยังไม่ปรับเทียบ)</h3><table class="t">
    <tr><th>ปัจจัย</th><th>เฝ้าระวัง</th><th>เตือนภัย</th><th>วิกฤต</th></tr>
    <tr><td>ฝนพยากรณ์ 24 ชม. (มม.)</td><td class="n">≥${th.rain.next24_watch}</td><td class="n">≥${th.rain.next24_warning}</td><td class="n">≥${th.rain.next24_critical}</td></tr>
    <tr><td>ฝนสะสม: ตกแล้ว 24 ชม. + 48 ชม.ข้างหน้า (มม.)</td><td class="n">≥${th.rain.acc_watch}</td><td class="n">≥${th.rain.acc_warning}</td><td class="n">≥${th.rain.acc_critical}</td></tr>
    ${L0.urban_rain_cfg?.watch_1h ? `<tr><td>ฝนหนักในเขตเมือง (สถานีใดสถานีหนึ่งในเขต, มม.)</td><td class="n">1 ชม. ≥${L0.urban_rain_cfg.watch_1h} หรือ 3 ชม. ≥${L0.urban_rain_cfg.watch_3h}</td><td class="n">1 ชม. ≥${L0.urban_rain_cfg.warning_1h} หรือ 3 ชม. ≥${L0.urban_rain_cfg.warning_3h}</td><td>–</td></tr>` : ""}
    <tr><td>ระดับน้ำที่สถานี</td><td>ขึ้นเร็ว ≥${th.station.rise_watch_m_per_h} ม./ชม. หรือถึงตลิ่งใน ≤${th.station.eta_watch_h} ชม.</td><td>ต่ำกว่าตลิ่ง ≤${th.station.near_bank_m} ม. หรือถึงตลิ่งใน ≤${th.station.eta_warning_h} ชม.</td><td>ถึงหรือเกินตลิ่ง</td></tr>
    </table><p class="note">ดินอิ่มน้ำ (≥${th.soil_wet_m3m3} ม³/ม³) ยกระดับฝนจากเฝ้าระวังเป็นเตือนภัย เฉพาะเมื่อฝนพยากรณ์ 24 ชม. ≥${th.rain.soil_bump_min_next24 ?? 60} มม. หรือฝนสะสม ≥${th.rain.soil_bump_min_acc ?? 150} มม. · ฝนที่ตกแล้วใช้สถานีวัดฝนอันดับ 3 ของอำเภอ · ระดับขึ้นได้ทันที แต่ลดลงได้เมื่อค่าต่ำกว่าเดิม 2 รอบติดกัน · ไม่แจ้งเตือนซ้ำตำบลเดิมที่ระดับเดิมภายใน 6 ชม. · พื้นที่ที่ สสน. ระบุเสี่ยงน้ำป่าอยู่ระดับ${LV[th.flashflood_level]}ขึ้นไป · แก้เกณฑ์ได้ใน config.json</p></div>`;
  h += eventForecastCard();
  h += replayCard();
  if (S.event) {
    const ev = S.event;
    h += `<div class="card"><h3>ผลวิเคราะห์เหตุการณ์ ${esc(ev.window[0])} ถึง ${esc(ev.window[1])}</h3>
      ${ev.chains.map((c) => `<p><b>${esc(c.name)}</b></p><table class="t"><tr><th>ช่วง</th><th>ยอดน้ำห่างกัน</th><th>ความสัมพันธ์ไขว้</th></tr>${c.legs.map((l) => `<tr><td>${esc(l.from)} → ${esc(l.to)}</td><td class="n">${l.found ? fmt(l.peak_lag_h, 1) + " ชม." : "ไม่มีข้อมูล"}</td><td class="n">${l.xcorr_lag_h != null ? l.xcorr_lag_h + " ชม. (r=" + fmt(l.xcorr_r, 2) + ")" : "–"}</td></tr>`).join("")}</table>`).join("")}
      <p><b>สถานีที่น้ำเกินตลิ่งมากที่สุด</b></p><table class="t"><tr><th>สถานี</th><th>เกินตลิ่ง</th><th>ชม.</th><th>ขึ้นเร็วสุด</th></tr>
      ${ev.stations.slice(0, 15).map((s) => `<tr><td>${esc(s.name)} ${esc(s.code)}<br><span class="note">อ.${esc(s.amphoe)} · ยอด ${esc(s.peak_time)}</span></td><td class="n">${fmt(s.peak_above_bank, 2)} ม.</td><td class="n">${fmt(s.hours_above_bank)}</td><td class="n">${fmt(s.max_rise_m_per_h, 2)}</td></tr>`).join("")}</table>
      <p class="note">นำเวลาเดินทางของน้ำไปใส่ lag_h_to_next ใน config.json เพื่อให้ระบบบอกเวลาที่น้ำจะมาถึงได้</p></div>`;
  } else {
    h += `<div class="card"><h3>ผลวิเคราะห์เหตุการณ์ในอดีต</h3><div class="note">ยังไม่มี ให้รัน workflow "เก็บข้อมูลย้อนหลังและวิเคราะห์เหตุการณ์" (ควรทำก่อนกลาง พ.ย. 2569 เพื่อเก็บข้อมูลน้ำท่วมปี 2568 ไว้)</div></div>`;
  }
  h += qualityCard(L0.quality);
  if (L0.rain_suspect?.length) h += `<div class="card"><h3>สถานีวัดฝนที่ยังไม่มีสถานีข้างเคียงยืนยัน</h3>${L0.rain_suspect.map((g) => `<p class="note"><b>${esc(g.name)}</b>${g.tc && S.props[g.tc] ? ` ต.${esc(S.props[g.tc].t)}` : ""}: ${esc(g.why)}</p>`).join("")}<p class="note">ฝนหนักที่สถานีเดียวขณะที่สถานีรอบข้างแทบไม่มีฝน อาจเป็นฝนเฉพาะจุดจริงหรือเครื่องวัดผิดพลาด ระบบยังไม่นำมาคิดฝนระดับอำเภอ และให้ยกระดับฝนหนักในเมืองได้ไม่เกินเฝ้าระวัง (จึงไม่ส่งแจ้งเตือน) จนกว่าสถานีข้างเคียงจะวัดได้ด้วย</p></div>`;
  h += `<div class="card"><h3>ข้อมูลที่ระบบยังไม่มี</h3><table class="t"><tr><th>ข้อมูล</th><th>ผลต่อระบบ</th><th>ใครมี</th></tr>
    ${KNOWN_GAPS.map(([a, b, c]) => `<tr><td>${esc(a)}</td><td>${esc(b)}</td><td>${esc(c)}</td></tr>`).join("")}</table></div>`;
  const log = [...(S.alerts || [])].reverse().slice(0, 40);
  h += floodReportCard();
  h += stormScoreCard();
  const lagRows = [...(S.alerts || [])].filter((a) => a.lag_min != null).reverse();
  const seen = new Set(), lag = lagRows.filter((a) => { const k = a.time; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 12);
  h += `<div class="card"><h3>ความเร็วของการเตือนฝนหนักในเมือง</h3>${lag.length
    ? `<table class="t"><tr><th>เวลาที่ระบบเตือน</th><th>เวลาที่สถานีบันทึกฝน</th><th>ช้ากว่าข้อมูล</th></tr>${lag.map((a) => `<tr><td>${timeTH(a.time)}</td><td>${timeTH(a.data_time)}</td><td class="n">${fmt(a.lag_min)} นาที</td></tr>`).join("")}</table>
       <p class="note">นับจากเวลาที่สถานีบันทึกฝน (สิ้นสุดชั่วโมงที่วัด) ถึงเวลาที่ระบบเตือน ยิ่งน้อยยิ่งดี น้ำในคลองกลางเมืองเริ่มขึ้นได้ภายในไม่กี่นาทีหลังฝนหนัก จึงควรต่ำกว่า 30 นาที</p>`
    : '<div class="note">ยังไม่มีการเตือนฝนหนักในเมืองหลังเริ่มบันทึกตัวชี้วัดนี้</div>'}</div>`;
  h += `<div class="card"><h3>ประวัติการแจ้งเตือน (ใช้ตรวจย้อนหลังว่าเตือนถูกหรือไม่)</h3>${log.length
    ? `<table class="t">${log.map((a) => `<tr class="click" data-tc="${a.tc}"><td>${timeTH(a.time)}</td><td>${esc(a.name)}</td><td>${badge(a.to)}</td></tr>`).join("")}</table>`
    : '<div class="note">ยังไม่มีการแจ้งเตือน</div>'}</div>`;
  el.innerHTML = h;
  el.querySelectorAll("tr[data-tc]").forEach((tr) => tr.addEventListener("click", () => { const p = S.props[tr.dataset.tc]; if (p) select({ pc: p.pc, ac: p.ac, tc: p.tc }); }));
  el.querySelectorAll("button[data-efac]").forEach((b) => b.addEventListener("click", () => {
    S.efAc = b.dataset.efac;
    const y = el.scrollTop;
    renderGaps();
    el.scrollTop = y;
  }));
}

const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u.trim()) ? u.trim() : null);
const FR_RESULT = { warned: ['<span class="dn">เตือนทัน</span>', "ขึ้นถึงเตือนภัยภายใน 24 ชม. ก่อนน้ำท่วม"],
  watch_only: ['<span class="mid">เฝ้าระวังเท่านั้น</span>', "ขึ้นแค่เฝ้าระวัง ไม่ถึงเตือนภัย"], missed: ['<span class="up">พลาด</span>', "ไม่มีการเตือนใน 24 ชม. ก่อนน้ำท่วม"],
  no_data: ['<span class="note">ยังไม่มีประวัติระดับ</span>', ""], pending: ['<span class="note">รอตรวจ</span>', ""], unscored: ['<span class="note">ระบุเวลา/ที่ไม่ได้</span>', ""] };
function frWhere(r) {
  const p = r.tc ? S.props[r.tc] : null;
  const a = !p && r.ac ? (S.admin?.amphoes || []).find((x) => x.ac === r.ac) : null;
  return p ? `ต.${esc(p.t)} อ.${esc(p.a)}` : a ? `อ.${esc(a.a)} <span class="note">(ทั้งอำเภอ)</span>` : esc([r.tambon, r.amphoe, r.province].filter(Boolean).join(" "));
}
function frLead(r) {
  if (r.q === "day") return '<span class="note">ทราบแค่วัน</span>';
  const h = (v, atleast) => (atleast ? `${fmt(v)}+ ชม.` : `${r.q === "observed" ? "ไม่เกิน " : ""}${fmt(v, 1)} ชม.`);
  const w = r.lead_warn_h != null ? h(r.lead_warn_h, r.lead_warn_h_atleast) : "";
  const wa = r.lead_watch_h != null && (r.lead_warn_h == null || r.lead_watch_h > r.lead_warn_h) ? `<span class="note">เฝ้าระวัง ${h(r.lead_watch_h, r.lead_watch_h_atleast)}</span>` : "";
  return [w, wa].filter(Boolean).join("<br>") || "–";
}
function frRows(rows) {
  return `<table class="t"><tr><th>เวลาน้ำท่วม</th><th>ที่</th><th>ผล</th><th>เตือนก่อน</th></tr>${rows.map((r) => {
    const src = safeUrl(r.source);
    const tm = r.time ? (r.q === "day" ? thDate(new Date(r.time).toLocaleDateString("sv-SE", { timeZone: "Asia/Bangkok" })) : timeTH(r.time)) : "–";
    return `<tr><td>${tm}${r.q === "observed" ? '<br><span class="note">เวลาที่พบ/รายงาน</span>' : ""}</td>
      <td>${frWhere(r)}<br><span class="note">${esc(r.place || "")}${r.depth_cm != null ? ` · ลึก ~${fmt(r.depth_cm)} ซม.` : ""}${src ? ` · <a href="${esc(src)}" target="_blank" rel="noopener">ที่มา</a>` : r.source ? ` · ${esc(r.source)}` : ""}${r.problems?.length ? ` · ${esc(r.problems.join(", "))}` : ""}</span></td>
      <td>${(FR_RESULT[r.result] || ["", ""])[0]}${r.basis === "alerts" ? '<br><span class="note">ตรวจได้เฉพาะระดับเตือนภัย</span>' : ""}</td><td class="n">${frLead(r)}</td></tr>`;
  }).join("")}</table>`;
}
const frScore = (sc) => `เตือนทัน <b>${sc.warned}</b> · เฝ้าระวังเท่านั้น <b>${sc.watch_only}</b> · พลาด <b>${sc.missed}</b> <span class="note">จาก ${sc.n} เหตุ${sc.lead_warn_median_h != null ? ` · เตือนก่อนน้ำท่วม (มัธยฐาน) ${fmt(sc.lead_warn_median_h, 1)} ชม.` : ""}</span>`;

function floodReportCard() {
  const fr = S.freports;
  const form = safeUrl(fr?.form_url);
  const how = `<p class="note">แจ้งเพิ่มได้${form ? `ทาง<a href="${esc(form)}" target="_blank" rel="noopener">แบบฟอร์ม</a> (ผู้ดูแลตรวจก่อนนับคะแนน) หรือ` : ""}โดยเพิ่มแถวในไฟล์ reports/flood_reports.csv ของ repo: วันเวลา · ชนิดเวลา (onset = เวลาที่เริ่มท่วม, observed = เวลาที่พบ/รายงาน, day = ทราบแค่วัน) · จังหวัด อำเภอ ตำบล · สถานที่ · ความลึก (ซม.) · ที่มา</p>`;
  if (!fr) return `<div class="card"><h3>เหตุน้ำท่วมจริงเทียบกับการเตือน</h3><p class="note">ระบบจะเริ่มให้คะแนนในรอบอัปเดตถัดไป</p>${how}</div>`;
  const live = fr.rows.filter((r) => r.result !== "no_data");
  const ep = fr.episodes || {};
  const names = Object.fromEntries((S.admin?.amphoes || []).map((a) => [a.ac, a.a]));
  const foc = (S.latest?.storm_risk?.focus || ["TH9011", "TH9001"]).map((a) => "อ." + (names[a] || a)).join("/");
  return `<div class="card"><h3>เหตุน้ำท่วมจริงเทียบกับการเตือน</h3>
    <p><b>เหตุที่ตรวจแล้ว:</b> ${fr.score.n ? frScore(fr.score) : '<span class="note">ยังไม่มีบันทึกเหตุน้ำท่วมหลังเริ่มระบบ</span>'}</p>
    <p><b>ระบบขึ้นระดับเตือนภัย:</b> ${fmt(ep.all?.n)} ครั้ง (${foc} ${fmt(ep.focus?.n)}) · มีรายงานน้ำท่วมยืนยันในอำเภอเดียวกัน ${fmt(ep.all?.confirmed)} ครั้ง <span class="note">ตั้งแต่ ${timeTH(ep.start)}</span></p>
    ${fr.counts?.pending ? `<p><b>รอตรวจ:</b> ${fr.counts.pending} รายงานจากแบบฟอร์ม</p>` : ""}
    ${live.length ? frRows(live.slice(0, 30)) : ""}
    <p class="note">เตือนทัน = ตำบลนั้น (หรืออำเภอนั้น ถ้าไม่ระบุตำบล) ขึ้นถึงเตือนภัยภายใน 24 ชม. ก่อนเวลาน้ำท่วม · "เตือนก่อน" นับจากครั้งแรกที่ขึ้นระดับในช่วงนั้นถึงเวลาน้ำท่วม ถ้าเป็นเวลาที่พบ/รายงาน น้ำอาจท่วมก่อนหน้านั้น จึงเป็นค่าสูงสุดที่เป็นไปได้ · การเตือนที่ยังไม่มีรายงานยืนยัน ไม่ได้แปลว่าเตือนผิด อาจแค่ยังไม่มีคนแจ้ง</p>${how}</div>`;
}

/* forecast issued ahead vs what really happened, day by day, for a past event */
function eventForecastCard() {
  const E = S.efc;
  if (!E) return `<div class="card"><h3>พยากรณ์ล่วงหน้า vs เกิดจริง (น้ำท่วม พ.ย. 2568)</h3><p class="note">ยังไม่มีผล ให้กด Run workflow "เทียบพยากรณ์กับเหตุการณ์จริง" ในแท็บ Actions ของ GitHub หนึ่งครั้ง (ใช้เวลาราว 2–5 นาที)</p></div>`;
  const acs = Object.keys(E.amphoes || {});
  const ac = acs.includes(S.efAc) ? S.efAc : E.main;
  const A = E.amphoes[ac];
  if (!A) return "";
  const mean = (xs) => { const v = xs.filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const fcv = (r, k) => mean(E.models.map((m) => r.fc[m]?.[k]));
  const fcmax = (r, k) => { const v = E.models.map((m) => r.fc[m]?.[k]).filter((x) => x != null); return v.length ? Math.max(...v) : null; };
  const lvB = (x) => (x && x.lv != null ? badge(x.lv) : '<span class="note">–</span>');
  const isMain = ac === E.main;
  const above = (v) => (v == null ? "–" : `<span class="${v > 0 ? "up" : ""}">${v > 0 ? "+" : ""}${fmt(v, 2)}</span>`);
  const codes = Object.keys(E.stations || {});
  // headline: first warning from the rain rule, the first recorded flood, and how far the forecast fell short on the record day
  const firstWarn = A.days.flatMap((r) => [["07:00", r.rule_07], ["19:00", r.rule_19]].map(([h, x]) => ({ t: `${r.date}T${h}:00+07:00`, x }))).find((o) => (o.x?.lv ?? 0) >= 2);
  const floodT = isMain ? Object.values(E.actual || {}).flatMap((a) => a.floods || []).map((f) => f.time).filter((t) => t && t.length > 10).sort()[0] : null;
  const rec = (E.rain_reported_all || []).filter((r) => r.amphoe === A.name && /^1 วัน/.test(r.period || "")).sort((a, b) => b.mm - a.mm)[0];
  const recRow = rec && A.days.find((r) => r.date === rec.date);
  const recFc = recRow ? fcv(recRow, "d1") : null;
  const lead = firstWarn && floodT ? (new Date(floodT.replace(" ", "T") + ":00+07:00") - new Date(firstWarn.t)) / 3.6e6 : null;
  const head = [];
  if (firstWarn) head.push(`กติกาฝนของระบบขึ้น<b>เตือนภัย</b>ครั้งแรก ${timeTH(firstWarn.t)}${lead == null ? "" : lead > 0 ? ` ก่อนเหตุน้ำท่วมแรกที่บันทึกในตัวเมืองราว <b>${fmt(lead / 24, 1)} วัน</b> (${fmt(lead)} ชม.)` : ` <b>หลัง</b>เหตุน้ำท่วมแรกที่บันทึกในตัวเมือง ${fmt(-lead)} ชม. (เตือนไม่ทัน)`}`);
  const firstWatch = A.days.flatMap((r) => [["07:00", r.rule_07], ["19:00", r.rule_19]].map(([h, x]) => ({ t: `${r.date}T${h}:00+07:00`, x }))).find((o) => (o.x?.lv ?? 0) >= 1);
  if (firstWatch && firstWatch !== firstWarn) {
    const lw = floodT ? (new Date(floodT.replace(" ", "T") + ":00+07:00") - new Date(firstWatch.t)) / 3.6e6 : null;
    head.push(`ระดับเฝ้าระวังครั้งแรก ${timeTH(firstWatch.t)}${lw != null && lw > 0 ? ` ก่อนเหตุน้ำท่วมแรกราว ${fmt(lw)} ชม.` : ""}`);
  }
  else head.push("กติกาฝนของระบบไม่ขึ้นถึงเตือนภัยในช่วงนี้");
  if (rec && recFc != null) head.push(`วันที่ฝนมากที่สุด (${thDate(rec.date)}) ${esc(rec.place)} วัดได้ <b>${fmt(+rec.mm, 1)} มม.</b> ขณะที่พยากรณ์ล่วงหน้า 1 วันเฉลี่ย ${E.models.length} โมเดลบอก <b>${fmt(recFc)} มม.</b>${recFc > 0 ? ` (ต่ำกว่าจริงราว ${fmt(rec.mm / recFc, 1)} เท่า)` : ""}`);
  const tabs = acs.length > 1 ? `<div class="segs">${acs.map((k) => `<button data-efac="${k}" class="${k === ac ? "on" : ""}">อ.${esc(E.amphoes[k].name)}</button>`).join("")}</div>` : "";
  const rows = A.days.map((r) => {
    const act = E.actual?.[r.date] || {};
    const rr = (r.rain_reported || []).map((x) => `${fmt(+x.mm, 1)} <span class="note">${esc(x.place)} · ${esc(x.period)}</span>`).join("<br>") || '<span class="note">–</span>';
    const fl = (act.floods || []).length;
    return `<tr><td>${thDate(r.date)}</td>
      <td class="n">${fcv(r, "d1") != null ? fmt(fcv(r, "d1")) : "–"}<br><span class="note">สูงสุด ${fmt(fcmax(r, "d1"))}</span></td>
      <td class="n">${fcv(r, "d2") != null ? fmt(fcv(r, "d2")) : "–"}</td>
      <td class="n">${fcv(r, "latest") != null ? fmt(fcv(r, "latest")) : "–"}</td>
      <td class="n">${r.cape != null ? fmt(r.cape) : "–"}${r.storm_flag ? " ⚠" : ""}</td>
      <td>${lvB(r.rule_07)}<br>${lvB(r.rule_19)}</td>
      <td class="sep">${rr}</td>
      ${isMain ? codes.map((c) => `<td class="n">${above(act.levels?.[c]?.above_bank)}</td>`).join("") + `<td>${act.level_rule_city != null ? badge(act.level_rule_city) : '<span class="note">–</span>'}</td><td>${fl ? `${fl} เหตุ` : '<span class="note">–</span>'}</td>` : ""}</tr>`;
  }).join("");
  return `<div class="card" id="efc"><h3>พยากรณ์ล่วงหน้า vs เกิดจริง ${thDate(E.window[0])}–${thDate(E.window[1])} ${new Date(E.window[0]).getFullYear() + 543}</h3>${tabs}
    ${head.map((x) => `<p>${x}</p>`).join("")}
    <p class="note">เลื่อนตารางไปทางขวาเพื่อดูฝั่งเกิดจริง →</p>
    <table class="t efc"><tr><th rowspan="2">วันที่</th><th colspan="5">ฝั่งพยากรณ์ (อ.${esc(A.name)})</th><th colspan="${isMain ? codes.length + 3 : 1}" class="sep">ฝั่งเกิดจริง</th></tr>
    <tr><th>ฝน 1 วันล่วงหน้า<br><span class="note">มม./วัน</span></th><th>2 วันล่วงหน้า</th><th>รอบล่าสุด</th><th>CAPE</th><th>กติกาฝน<br><span class="note">07:00 / 19:00</span></th><th class="sep">ฝนที่รายงาน (มม.)</th>
    ${isMain ? codes.map((c) => `<th>${esc(c)}<br><span class="note">เทียบตลิ่ง ม.</span></th>`).join("") + '<th>กติการะดับน้ำ<br><span class="note">ตัวเมือง</span></th><th>น้ำท่วมที่บันทึก</th>' : ""}</tr>${rows}</table>
    <p class="note">ฝนพยากรณ์ = ฝนรวม 07:00 น. ถึง 07:00 น. วันถัดไป (วันฝนแบบกรมอุตุนิยมวิทยา) ที่จุดกึ่งกลางอำเภอ เฉลี่ย ${E.models.length} โมเดล (${esc(E.models.join(", "))}) · "รอบล่าสุด" ใช้รอบพยากรณ์ที่ใกล้เวลาจริงที่สุด จึงดีกว่าที่ใช้ได้จริง · CAPE ⚠ = ถึงเกณฑ์วันเสี่ยงฝนฟ้าคะนอง (≥ ${fmt(E.storm_threshold)} J/kg) · กติกาฝน = รันเกณฑ์ฝนของระบบซ้ำตอน 07:00 และ 19:00 น. โดยใช้เฉพาะพยากรณ์ที่ออกก่อนเวลานั้น ไม่มีฝนจากสถานีวัด (ไม่มีข้อมูลย้อนหลัง) · ระดับน้ำ = ค่าสูงสุดของวันเทียบตลิ่ง (+ = ล้นตลิ่ง)</p>
    <p class="note">ข้อจำกัด: ฝนจริงมีแค่ตัวเลขรายวันบางจุดจากกรมอุตุนิยมวิทยา กรมชลประทาน และข่าว ฝนที่จุดเดียวเทียบตรงๆ กับพยากรณ์ที่เป็นค่าเฉลี่ยพื้นที่กว้างราว 10–25 กม. ไม่ได้ · เพิ่มตัวเลขฝนได้ใน reports/rain_reported.csv แล้วกด Run workflow "เทียบพยากรณ์กับเหตุการณ์จริง" · รันเมื่อ ${esc(E.generated_at)}${E.notes?.length ? ` · ดึงบางส่วนไม่สำเร็จ ${E.notes.length} รายการ` : ""}</p></div>`;
}

function replayCard() {
  const R = S.replay;
  if (!R) return "";
  const fr = R.reports || {};
  const lvTh = { 1: "เฝ้าระวัง", 2: "เตือนภัย", 3: "วิกฤต" };
  const ks = Object.entries(R.key_stations || {}).sort((a, b) => (a[1]["2"] || "z").localeCompare(b[1]["2"] || "z"));
  const months = Object.entries(R.alerts_by_month || {});
  return `<div class="card"><h3>ทดสอบกติกาปัจจุบันกับน้ำท่วม ${esc(R.window[0])} ถึง ${esc(R.window[1])}</h3>
    <p class="note">รันโค้ดคำนวณชุดเดียวกับระบบจริงซ้ำทุก ${R.step_min} นาที ด้วยระดับน้ำย้อนหลัง ${R.stations} สถานี · ใช้ได้เฉพาะ${esc(R.rules)} · รันเมื่อ ${esc(R.generated_at)}</p>
    <p><b>เหตุน้ำท่วมที่มีบันทึก:</b> ${fr.score ? frScore(fr.score) : "–"}</p>
    <p><b>การเตือนระดับเตือนภัยขึ้นไปช่วงนี้:</b> ${fmt(R.alerts_event_n)} ครั้งทุกตำบล · หาดใหญ่/เมืองสงขลา ${fmt(R.alerts_event_focus_n)} ครั้ง</p>
    ${fr.rows?.length ? frRows(fr.rows) : ""}
    ${ks.length ? `<p><b>สถานีหลัก: ครั้งแรกที่ถึงแต่ละระดับ</b></p><table class="t"><tr><th>สถานี</th>${[1, 2, 3].map((k) => `<th>${lvTh[k]}</th>`).join("")}</tr>${ks.map(([c, v]) => `<tr><td>${esc(c)} ${esc(v.name)}${v.tc && S.props[v.tc] ? `<br><span class="note">ต.${esc(S.props[v.tc].t)}</span>` : ""}</td>${[1, 2, 3].map((k) => `<td>${v[k] ? timeTH(v[k]) : "–"}</td>`).join("")}</tr>`).join("")}</table>` : ""}
    ${months.length > 1 ? `<p><b>จำนวนครั้งที่กติการะดับน้ำจะเตือน (เตือนภัยขึ้นไป) รายเดือน</b></p><table class="t"><tr><th>เดือน</th><th>ทุกตำบล</th><th>หาดใหญ่/เมืองสงขลา</th></tr>${months.map(([m, n]) => `<tr><td>${esc(m)}</td><td class="n">${fmt(n)}</td><td class="n">${fmt(R.alerts_by_month_focus?.[m] || 0)}</td></tr>`).join("")}</table>` : ""}
    <p class="note">ข้อจำกัด: ไม่มีฝนรายชั่วโมงย้อนหลังในข้อมูลเปิด จึงยังทดสอบกติกาฝนและฝนหนักในเมืองไม่ได้ · ข้อมูลย้อนหลังคือค่าที่หน่วยงานส่งครบแล้ว ตอนเกิดเหตุจริงบางสถานี (โดยเฉพาะกรมชลประทานช่วงกลางคืน) ส่งช้ากว่านี้ ผลจริงจึงอาจช้ากว่าที่เห็น · เพิ่มเหตุน้ำท่วมใน reports/flood_reports.csv แล้วกด Run workflow "ทดสอบกติกาเตือนภัยกับเหตุการณ์ในอดีต" เพื่อคำนวณใหม่</p></div>`;
}

function qualityCard(q) {
  if (!q) return `<div class="card"><h3>ความครบถ้วนของข้อมูลรายหน่วยงาน</h3><div class="note">ระบบจะเริ่มตรวจวันละครั้งหลัง 06:00 น. โดยอ่านกราฟของเมื่อวานจากต้นทางทุกสถานี ผลแรกจะขึ้นภายในวันนี้หรือพรุ่งนี้</div></div>`;
  const short = (n) => ({ "สถาบันสารสนเทศทรัพยากรน้ำ (องค์การมหาชน)": "สสน.", "การไฟฟ้าฝ่ายผลิตแห่งประเทศไทย": "กฟผ.", "มูลนิธิอาสาเพื่อนพึ่ง (ภาฯ) ยามยาก สภากาชาดไทย": "มูลนิธิอาสาเพื่อนพึ่ง (ภาฯ) สภากาชาดไทย" }[n] || n);
  const row = (a) => `<tr><td>${esc(short(a.agency))}<br><span class="note">${a.stations} สถานี</span></td><td class="n">${fmt(a.complete_pct, 1)}%</td><td class="n">${fmt(a.midnight_pct)}%</td><td class="n">${fmt(a.dead_station_days)}</td></tr>`;
  const tbl = (rows) => `<table class="t"><tr><th>หน่วยงาน</th><th>มีข้อมูล</th><th>ขาดช่วงเที่ยงคืน</th><th>ดับทั้งวัน</th></tr>${rows.map(row).join("")}</table>`;
  const worst = (q.d7 || []).flatMap((a) => a.worst.map((w) => ({ ...w, agency: a.agency }))).sort((a, b) => b.missing_h - a.missing_h).slice(0, 10);
  return `<div class="card"><h3>ความครบถ้วนของข้อมูลรายหน่วยงาน</h3>
    <p class="note">ตรวจจากกราฟต้นทางบน thaiwater.net วันละครั้ง นับชั่วโมงที่มีค่าระดับน้ำ ไม่ขึ้นกับจังหวะดึงข้อมูลของระบบเรา · มีข้อมูล ${q.n_days} วัน (${esc(q.first_day)} ถึง ${esc(q.last_day)})</p>
    <p><b>7 วันล่าสุด</b></p>${tbl(q.d7 || [])}
    ${q.n_days > 7 ? `<p><b>30 วันล่าสุด</b></p>${tbl(q.d30 || [])}` : ""}
    ${worst.length ? `<p><b>สถานีที่ขาดมากที่สุด (7 วัน)</b></p><table class="t">${worst.map((w) => `<tr><td>${esc(w.name)} ${esc(w.code || "")}<br><span class="note">${esc(short(w.agency))}</span></td><td class="n">${fmt(w.missing_h)} ชม.</td></tr>`).join("")}</table>` : ""}
    <p class="note">มีข้อมูล = ร้อยละของชั่วโมงที่มีค่า · ขาดช่วงเที่ยงคืน = ร้อยละของสถานี-วันที่ไม่มีค่าเวลา 23:00 หรือ 00:00 น. · ดับทั้งวัน = จำนวนสถานี-วันที่ไม่มีค่าเลย</p>
    <p class="note">ใช้เป็นหลักฐานประกอบข้อเสนอถึงหน่วยงานได้ พ.ร.บ.ทรัพยากรน้ำ 2561 มาตรา 23 (9) ให้ สทนช. กำกับให้หน่วยงานส่งข้อมูลที่เป็นปัจจุบัน ทั้งในภาวะปกติและภาวะวิกฤติ</p></div>`;
}

/* ------------------------------------------------------------------ tabs + boot */
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tabbody").forEach((d) => d.classList.toggle("hidden", d.id !== "tab-" + name));
  if (name === "roads") renderRoads();
  if (name === "stations") renderStations();
  if (name === "gaps") renderGaps();
}

function renderHeader() {
  const u = $("#updated");
  const t = S.latest?.generated_at;
  if (!t) { u.textContent = "ยังไม่มีข้อมูล"; return; }
  const mins = (Date.now() - new Date(t).getTime()) / 60000;
  u.textContent = `ระบบอัปเดตล่าสุด ${timeTH(t)} (${ago(t)})`;
  u.classList.toggle("stale", mins > 90);
  if (mins > 90) u.textContent += " · ระบบอาจหยุดอัปเดต";
  if (S.latest.area_name) $("#areaName").textContent = S.latest.area_name;
}

/* how recent each kind of data is: shown on every tab, turns amber when a source is late or failing */
function renderFresh() {
  const el = $("#fresh");
  const F = S.latest?.freshness;
  if (!el || !F) { if (el) el.hidden = true; return; }
  const when = (t) => (t ? new Date(t).toLocaleString("th-TH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" }) + " น." : "ไม่มีข้อมูล");
  const items = Object.entries(F).map(([k, f]) => {
    const age = f.data_time ? (Date.now() - new Date(f.data_time).getTime()) / 3.6e6 : null;
    return { k, f, age, bad: !f.ok || age == null || age > f.stale_h };
  }).sort((a, b) => b.bad - a.bad);
  const anyBad = items.some((i) => i.bad);
  const chip = (i) => {
    const why = [];
    if (i.bad && i.age != null) why.push(ago(i.f.data_time));
    if (!i.f.ok) why.push(`ดึงไม่สำเร็จตั้งแต่ ${when(i.f.error_since)}`);
    const extra = i.k === "levels" && i.f.n ? ` · สด ${i.f.n_fresh}/${i.f.n} สถานี` : i.k === "rain" && i.f.ok ? ` · ${i.f.n} สถานี` : "";
    return `<span class="fr${i.bad ? " bad" : ""}"><b>${esc(i.f.label)}</b> ถึง ${when(i.f.data_time)}${why.length ? ` (${why.join(" · ")})` : ""}<span class="note">${extra}</span></span>`;
  };
  el.className = "freshbar" + (anyBad ? " warn" : "");
  el.innerHTML = `<span class="frhead">${anyBad ? "⚠ ข้อมูลบางส่วนไม่เป็นปัจจุบัน ระดับเตือนภัยอาจไม่ตรงกับสถานการณ์จริง:" : "ข้อมูลอัปเดตถึง"}</span>${items.map(chip).join("")}`;
  el.hidden = false;
}

function renderAll() {
  renderHeader();
  renderFresh();
  refreshMapStyles();
  const cur = document.querySelector(".tabs button.on")?.dataset.tab || "area";
  renderArea();
  if (cur !== "area") showTab(cur);
}

async function refresh() {
  const [latest, alerts, fr] = await Promise.all([getJSON("data/latest.json", true), getJSON("data/alerts_log.json", true), getJSON("data/flood_reports.json", true)]);
  S.tracker = await getJSON("data/tracker.json", true);
  if (latest) S.latest = latest;
  if (alerts) S.alerts = alerts;
  if (fr) S.freports = fr;
  renderAll();
}

async function boot() {
  initMap();
  try {
    const [tam, amp, admin, roads, ev, replay] = await Promise.all([
      getJSON("data/static/tambons.geojson"), getJSON("data/static/amphoes.geojson"), getJSON("data/static/admin.json"),
      getJSON("data/static/roads.geojson", true), getJSON("data/static/event_analysis.json", true), getJSON("data/static/replay.json", true)]);
    Object.assign(S, { tam, amp, admin, roads, event: ev, replay });
    S.efc = await getJSON("data/static/event_forecast.json", true);
    for (const f of tam.features) S.props[f.properties.tc] = f.properties;
  } catch (e) {
    $("#tab-area").innerHTML = `<div class="warnnote">${esc(e.message)}</div>`;
    return;
  }
  buildLayers();
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  await refresh();
  if (!S.latest) $("#tab-area").insertAdjacentHTML("afterbegin", `<div class="warnnote">ยังไม่มีไฟล์ข้อมูล (data/latest.json) ให้รัน workflow "อัปเดตข้อมูลน้ำ" ก่อน</div>`);
  select(selFromHash());
  setInterval(refresh, 5 * 60 * 1000);
  window.addEventListener("hashchange", () => select(selFromHash()));
}
boot();
