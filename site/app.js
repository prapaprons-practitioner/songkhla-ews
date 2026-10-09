"use strict";
/* เตือนน้ำท่วมล่วงหน้า: หน้าแสดงผล (อ่านไฟล์ที่ GitHub Actions สร้าง) */

const LV = ["ปกติ", "เฝ้าระวัง", "เตือนภัย", "วิกฤต"];
const COL = ["#cfe3d4", "#f6d55c", "#f08c2e", "#d7263d"];
const COLX = "#bdbdbd";
const SRC_LABEL = { rain: "ฝน", station: "สถานีวัดน้ำ", flashflood: "น้ำป่า", chain: "น้ำจากต้นน้ำ" };
const KNOWN_GAPS = [
  ["สถานะประตูระบายน้ำและสถานีสูบน้ำ", "ไม่มีข้อมูลเปิดแบบเรียลไทม์ จึงยังคำนวณความสามารถระบายน้ำจริงไม่ได้", "กรมชลประทาน / เทศบาล"],
  ["ความจุคลองจริง (หลังตะกอนทับถม)", "ใช้ระดับตลิ่งแทน ยังไม่รู้ว่าคลองรับน้ำได้กี่ ลบ.ม./วินาที", "กรมชลประทาน (ข้อมูลรูปตัดคลอง)"],
  ["เวลาเดินทางของน้ำระหว่างสถานี", "ใช้ค่าประมาณ ต้องวิเคราะห์จากข้อมูลย้อนหลัง (workflow เก็บข้อมูลย้อนหลัง)", "คำนวณได้เองจากคลังข้อมูล"],
  ["เกณฑ์ธงสีและจุดธงของหาดใหญ่", "ยังผูกกับระดับน้ำที่สถานีไม่ได้", "มูลนิธิ Hatyai City Climate / เทศบาลนครหาดใหญ่"],
  ["ถนนที่ปิดจริงพร้อมเวลา", "ระดับเตือนภัยของถนนอนุมานจากตำบล ยังไม่ได้ยืนยันกับเหตุการณ์จริง", "กรมทางหลวง (HDMS) / ทางหลวงชนบท"],
  ["ระดับน้ำทะเลสาบสงขลาและน้ำขึ้นน้ำลง", "ยังไม่ได้นำมาคำนวณการระบายลงทะเลสาบ", "กรมอุทกศาสตร์ / สสน. FEWS (ตารางน้ำขึ้นลง)"],
  ["ความลึกน้ำท่วมจริงบนพื้นที่", "ไม่มีเซนเซอร์บนถนนในภาคใต้ ระบบบอกได้แค่ความเสี่ยง ไม่ใช่ความลึก", "เทศบาล / ภาพดาวเทียม GISTDA (ต้องขอ API key)"],
];

const S = { latest: null, tam: null, amp: null, admin: null, roads: null, event: null, alerts: [],
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
    const c = s.stale || s.state == null ? COLX : COL[s.state];
    L.circleMarker([s.lat, s.lon], { pane: "points", radius: 6, color: "#1d232a", weight: 1.2, fillColor: c, fillOpacity: 1 })
      .bindTooltip(`<b>${esc(s.name)}</b> ${esc(s.code || "")}<br>${s.stale ? "ข้อมูลไม่เป็นปัจจุบัน" : esc(s.why)}`)
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
  const lvl = s.stale || s.state == null ? null : s.state;
  return `<div class="reason">${badge(lvl)}<div><b>${esc(s.name)}</b> <span class="note">${esc(s.code || "")} · ${esc(s.agency || "")}</span><br>
    ระดับน้ำ ${fmt(s.level, 2)} ม.รทก. · ตลิ่ง ${fmt(s.bank, 2)}${s.warn != null ? ` · ระดับเตือน ${fmt(s.warn, 2)}` : ""}<br>
    <span class="note">${esc(s.why || "")} · วัดเมื่อ ${ago(s.time)}</span></div></div>`;
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
    html += rainCard(a.ac);
    html += childList(Object.values(S.props).filter((p) => p.ac === a.ac).map((p) => ({ key: p.tc, attr: "tc", name: "ต." + p.t, lv: lvOf(p.tc), meta: (L0?.tambons?.[p.tc]?.reasons?.[0]?.text || "ไม่พบปัจจัยเสี่ยง").slice(0, 90) })));
  } else if (S.sel.pc) {
    const p = S.admin.provinces.find((x) => x.pc === S.sel.pc);
    const n = tamCounts((x) => x.pc === p.pc);
    html += hero(`จ.${p.p}`, `${n.reduce((a, b) => a + b)} ตำบล`, L0?.provinces?.[p.pc]?.lv, n);
    html += childList(S.admin.amphoes.filter((a) => a.pc === p.pc).map((a) => {
      const c = tamCounts((x) => x.ac === a.ac);
      return { key: a.ac, attr: "ac", name: "อ." + a.a, lv: L0?.amphoes?.[a.ac]?.lv, meta: countsText(c), n: c };
    }));
  } else {
    const n = tamCounts(() => true);
    html += hero(L0?.area_name || "ทุกจังหวัด", `${Object.keys(S.props).length} ตำบล · ${S.admin.amphoes.length} อำเภอ`, Math.max(...Object.values(L0?.provinces || {}).map((p) => p.lv ?? 0), 0), n);
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
      <span class="k">ฝนที่ตกแล้ว 24 ชม. ${r.p24_obs != null ? `(สถานีวัดสูงสุด จาก ${r.n_gauges} สถานี)` : "(ประมาณจากโมเดล)"}</span><span class="v">${fmt(r.p24_obs ?? r.p24_model)} มม.</span>
      <span class="k">ฝนสะสม (ที่ตกแล้ว + 48 ชม.ข้างหน้า)</span><span class="v">${fmt(r.acc)} มม.</span>
      <span class="k">ความชื้นดิน 3–9 ซม.</span><span class="v">${r.soil != null ? fmt(r.soil, 2) + " ม³/ม³" : "–"}</span>
    </div>
    ${spark(r.h72)}
    <table class="t"><tr><th>โมเดล</th><th>24 ชม.</th><th>48 ชม.</th><th>72 ชม.</th></tr>${models}</table>
    <div class="note">ฝนพยากรณ์ที่จุดกึ่งกลางอำเภอ ทุกตำบลในอำเภอใช้ค่าเดียวกัน</div></div>`;
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
  h += rainCard(p.ac);
  if (rgs.length) h += `<div class="card"><h3>สถานีวัดฝนในตำบล</h3><div class="kv">${rgs.map((g) => `<span class="k">${esc(g.name)}</span><span class="v">${fmt(g.r24, 1)} มม. <span class="note">${ago(g.time)}</span></span>`).join("")}</div></div>`;
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
  let h = "";
  for (const c of L0?.chains || []) {
    h += `<div class="card"><h3>${esc(c.name)} ${c.trigger ? badge(c.trigger.lv) : ""}</h3><div class="chain">`;
    c.stations.forEach((s, i) => {
      h += `<div class="node">${badge(s.found && !s.stale ? s.state : null)}<div><b>${esc(s.label)}</b><br><span class="note">${s.found
        ? (s.stale ? "ข้อมูลไม่เป็นปัจจุบัน" : `ระดับ ${fmt(s.level, 2)} · ตลิ่ง ${fmt(s.bank, 2)} ม.รทก.${s.eta_h != null ? ` · ถึงตลิ่งใน ~${fmt(s.eta_h)} ชม.` : ""}`)
        : "ไม่พบสถานีนี้ในข้อมูล สสน."}</span></div></div>`;
      if (i < c.stations.length - 1) h += `<div class="lag">น้ำเดินทาง ${s.lag_h_to_next != null ? "~" + s.lag_h_to_next + " ชม." : "ยังไม่ทราบเวลา"}</div>`;
    });
    h += `</div>${c.trigger ? `<div class="warnnote">${esc(c.trigger.msg)}</div>` : ""}</div>`;
  }
  const sts = [...(L0?.stations || [])].sort((a, b) => ((b.stale ? -1 : b.state ?? -1) - (a.stale ? -1 : a.state ?? -1)) || ((a.gap ?? 99) - (b.gap ?? 99)));
  h += `<div class="card"><h3>สถานีวัดระดับน้ำในพื้นที่ (${sts.length})</h3><table class="t"><tr><th>สถานี</th><th>เทียบตลิ่ง</th><th>แนวโน้ม</th><th></th></tr>
    ${sts.map((s) => `<tr class="click" data-tc="${s.tc || ""}"><td>${esc(s.name)}<br><span class="note">${esc(s.code || "")} ${s.tc ? "ต." + esc(S.props[s.tc].t) : ""} · ${ago(s.time)}</span></td>
    <td class="n">${s.gap != null ? (s.gap < 0 ? "+" : "−") + fmt(Math.abs(s.gap), 2) + " ม." : "–"}</td>
    <td class="n">${s.slope != null ? (s.slope > 0 ? "▲ " : s.slope < 0 ? "▼ " : "") + fmt(Math.abs(s.slope), 2) : "–"}</td>
    <td>${badge(s.stale ? null : s.state)}</td></tr>`).join("")}</table>
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
    ${g.stations_no_bank?.length ? `<p class="note"><b>สถานีที่ไม่มีระดับตลิ่ง</b> (คำนวณระยะถึงตลิ่งไม่ได้): ${g.stations_no_bank.map((s) => esc(s.name)).join(", ")}</p>` : ""}</div>`;
  const th = L0.thresholds;
  if (th) h += `<div class="card"><h3>เกณฑ์ที่ใช้คำนวณ (ค่าเริ่มต้น ยังไม่ปรับเทียบ)</h3><table class="t">
    <tr><th>ปัจจัย</th><th>เฝ้าระวัง</th><th>เตือนภัย</th><th>วิกฤต</th></tr>
    <tr><td>ฝนพยากรณ์ 24 ชม. (มม.)</td><td class="n">≥${th.rain.next24_watch}</td><td class="n">≥${th.rain.next24_warning}</td><td class="n">≥${th.rain.next24_critical}</td></tr>
    <tr><td>ฝนสะสม: ตกแล้ว 24 ชม. + 48 ชม.ข้างหน้า (มม.)</td><td class="n">≥${th.rain.acc_watch}</td><td class="n">≥${th.rain.acc_warning}</td><td class="n">≥${th.rain.acc_critical}</td></tr>
    <tr><td>ระดับน้ำที่สถานี</td><td>ขึ้นเร็ว ≥${th.station.rise_watch_m_per_h} ม./ชม. หรือถึงตลิ่งใน ≤${th.station.eta_watch_h} ชม.</td><td>ต่ำกว่าตลิ่ง ≤${th.station.near_bank_m} ม. หรือถึงตลิ่งใน ≤${th.station.eta_warning_h} ชม.</td><td>ถึงหรือเกินตลิ่ง</td></tr>
    </table><p class="note">ดินอิ่มน้ำ (≥${th.soil_wet_m3m3} ม³/ม³) ยกระดับฝนจากเฝ้าระวังเป็นเตือนภัย · พื้นที่ที่ สสน. ระบุเสี่ยงน้ำป่าอยู่ระดับ${LV[th.flashflood_level]}ขึ้นไป · แก้เกณฑ์ได้ใน config.json</p></div>`;
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
  h += `<div class="card"><h3>ข้อมูลที่ระบบยังไม่มี</h3><table class="t"><tr><th>ข้อมูล</th><th>ผลต่อระบบ</th><th>ใครมี</th></tr>
    ${KNOWN_GAPS.map(([a, b, c]) => `<tr><td>${esc(a)}</td><td>${esc(b)}</td><td>${esc(c)}</td></tr>`).join("")}</table></div>`;
  const log = [...(S.alerts || [])].reverse().slice(0, 40);
  h += `<div class="card"><h3>ประวัติการแจ้งเตือน (ใช้ตรวจย้อนหลังว่าเตือนถูกหรือไม่)</h3>${log.length
    ? `<table class="t">${log.map((a) => `<tr class="click" data-tc="${a.tc}"><td>${timeTH(a.time)}</td><td>${esc(a.name)}</td><td>${badge(a.to)}</td></tr>`).join("")}</table>`
    : '<div class="note">ยังไม่มีการแจ้งเตือน</div>'}</div>`;
  el.innerHTML = h;
  el.querySelectorAll("tr[data-tc]").forEach((tr) => tr.addEventListener("click", () => { const p = S.props[tr.dataset.tc]; if (p) select({ pc: p.pc, ac: p.ac, tc: p.tc }); }));
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
  u.textContent = `ข้อมูล ณ ${timeTH(t)} (${ago(t)})`;
  u.classList.toggle("stale", mins > 90);
  if (mins > 90) u.textContent += " · ระบบอาจหยุดอัปเดต";
  if (S.latest.area_name) $("#areaName").textContent = S.latest.area_name;
}

function renderAll() {
  renderHeader();
  refreshMapStyles();
  const cur = document.querySelector(".tabs button.on")?.dataset.tab || "area";
  renderArea();
  if (cur !== "area") showTab(cur);
}

async function refresh() {
  const [latest, alerts] = await Promise.all([getJSON("data/latest.json", true), getJSON("data/alerts_log.json", true)]);
  if (latest) S.latest = latest;
  if (alerts) S.alerts = alerts;
  renderAll();
}

async function boot() {
  initMap();
  try {
    const [tam, amp, admin, roads, ev] = await Promise.all([
      getJSON("data/static/tambons.geojson"), getJSON("data/static/amphoes.geojson"), getJSON("data/static/admin.json"),
      getJSON("data/static/roads.geojson", true), getJSON("data/static/event_analysis.json", true)]);
    Object.assign(S, { tam, amp, admin, roads, event: ev });
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
