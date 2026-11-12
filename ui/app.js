/* Epson Ink Pad Reset — UI logic.
   Talks to Python through window.pywebview.api (see app_web.py).
   Every API method resolves to an object with ok: true/false. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const icon = (name) => `<svg><use href="#i-${name}"/></svg>`;
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (typeof n === "number" ? n.toLocaleString("th-TH") : esc(n ?? "—"));

let api = null;
const S = {
  page: "home",
  conn: "usb",            // usb | wifi
  host: "",
  busy: false,
  heroState: "idle",
  printer: null,           // last successful check()
  settings: { ink_threshold: 20, recent_hosts: [] },
  info: {},
  models: null,
  modelFilter: "all",
  release: null,
};

const PAGES = {
  home: ["ภาพรวม", "สถานะเครื่องพิมพ์และซับหมึก"],
  stats: ["สถิติเครื่อง", "ตัวนับการใช้งานที่เก็บในเครื่องพิมพ์ (อ่านอย่างเดียว)"],
  care: ["บำรุงรักษา", "เช็กหัวพิมพ์ ล้างหัวพิมพ์ และเวลาปิดเครื่อง"],
  history: ["ประวัติและสำรอง", "สิ่งที่โปรแกรมเคยทำ และไฟล์สำรองสำหรับกู้คืน"],
  models: ["รุ่นที่รองรับ", "รุ่นที่อยู่ในฐานข้อมูลของโปรแกรม"],
  settings: ["ตั้งค่า", "การแจ้งเตือน อัปเดต และข้อมูลทางเทคนิค"],
};

const HERO = {
  idle: ["question", "", "พร้อมเริ่มใช้งาน", () => S.conn === "wifi"
    ? "ใส่ IP ของเครื่องพิมพ์ด้านบน (หรือกดค้นหา) แล้วกด “ตรวจสอบเครื่องพิมพ์”"
    : "เสียบสาย USB และเปิดเครื่องพิมพ์ แล้วกด “ตรวจสอบเครื่องพิมพ์”"],
  busy: ["", "busy", "กำลังทำงาน", "กรุณารอสักครู่..."],
  error: ["alert", "bad", "ติดต่อเครื่องพิมพ์ไม่ได้", () => S.conn === "wifi"
    ? "เช็กว่าเครื่องพิมพ์กับคอมอยู่ในวง Wi‑Fi เดียวกัน และ IP ถูกต้อง แล้วลองใหม่"
    : "เช็กว่าเสียบสาย USB และเปิดเครื่องแล้ว ปิดโปรแกรมอื่นที่ใช้เครื่องพิมพ์ (เช่น WIC Reset) แล้วลองใหม่"],
  ok: ["check", "ok", "เครื่องพิมพ์ปกติ", "ซับหมึกยังไม่เต็ม ใช้งานต่อได้เลย"],
  full: ["alert", "bad", "ซับหมึกเต็ม", "เครื่องพิมพ์หยุดทำงานเพราะตัวนับซับหมึกเต็ม กด “รีเซ็ตซับหมึก” เพื่อแก้"],
  unsupported: ["question", "warn", "ยังไม่รองรับรีเซ็ตถาวรรุ่นนี้", "อ่านข้อมูลเครื่องได้ แต่ไม่มีข้อมูลสำหรับรีเซ็ตถาวร ลอง “รีเซ็ตชั่วคราว” ได้"],
  done: ["check", "ok", "รีเซ็ตสำเร็จ", "ปิดเครื่องพิมพ์ด้วยปุ่ม Power รอไฟดับ เปิดใหม่ แล้วกด “ตรวจสอบอีกครั้ง”"],
  temp_done: ["check", "ok", "รีเซ็ตชั่วคราวสำเร็จ", "เครื่องพิมพ์จะพิมพ์ต่อได้อีกระยะหนึ่ง ตัวนับไม่ได้ถูกล้าง ควรล้าง/เปลี่ยนแผ่นซับเร็ว ๆ นี้"],
  failed: ["alert", "bad", "รีเซ็ตไม่สำเร็จ", "เครื่องพิมพ์ไม่รับคำสั่ง ลองปิด-เปิดเครื่องพิมพ์แล้วทำใหม่"],
  backup_failed: ["alert", "bad", "สำรองข้อมูลไม่สำเร็จ", "จึงยังไม่ได้รีเซ็ต เพื่อความปลอดภัย ลองกดตรวจสอบแล้วทำใหม่"],
};

const STEP_LABELS = ["เชื่อมต่อ", "ตรวจสอบ", "รีเซ็ต", "ปิด-เปิดเครื่อง"];
const STEP_FOR = { idle: [0, 0], error: [0, 0], ok: [2, 2], full: [2, 2], unsupported: [1, 1],
  done: [3, 3], temp_done: [3, 3], failed: [2, 2], backup_failed: [2, 2] };

const INK_VAR = { Black: "--ink-black", "Photo Black": "--ink-black", "Matte Black": "--ink-black",
  Cyan: "--ink-cyan", "Light Cyan": "--ink-cyan", Magenta: "--ink-magenta", "Light Magenta": "--ink-magenta",
  Yellow: "--ink-yellow" };
const inkColor = (name) => `var(${INK_VAR[name] || "--accent"})`;

const WASTE_TH = { main_waste: "ซับหมึกหลัก", borderless_waste: "ซับหมึกพิมพ์ไร้ขอบ",
  first_waste: "ซับหมึก 1", second_waste: "ซับหมึก 2", third_waste: "ซับหมึก 3" };

const KIND = {
  reset: ["shield", "รีเซ็ตซับหมึก"], temp_reset: ["bolt", "รีเซ็ตชั่วคราว"],
  restore: ["restore", "กู้คืนจากไฟล์สำรอง"], power_timer: ["clock", "ตั้งเวลาปิดเครื่อง"],
  nozzle_check: ["grid", "พิมพ์หน้าเช็กหัวพิมพ์"], clean: ["sparkle", "ล้างหัวพิมพ์"],
  power_clean: ["bolt", "ล้างหัวพิมพ์แบบเข้ม"],
};

/* ------------------------------------------------------------ helpers */
function toast(text, kind = "ok", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === "ok" ? "check" : kind === "bad" ? "warn" : "info")}<span>${esc(text)}</span>`;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; setTimeout(() => el.remove(), 320); }, ms);
}

function hostArg() { return S.conn === "wifi" ? (S.host || null) : null; }

function errorText(res) {
  const e = String(res?.error || "");
  if (e.startsWith("model-mismatch")) return `ไฟล์สำรองนี้เป็นของรุ่น ${e.split(":")[1]} ไม่ตรงกับเครื่องที่ต่ออยู่`;
  if (e.startsWith("serial-mismatch")) return `ไฟล์สำรองนี้เป็นของเครื่องซีเรียล ${e.split(":")[1]} ไม่ใช่เครื่องนี้`;
  return ({
    "no-queue": "ไม่พบเครื่องพิมพ์นี้ใน Windows ให้ติดตั้งไดรเวอร์ Epson หรือเลือกคิวพิมพ์เอง",
    "unsupported": "รุ่นนี้ยังไม่รองรับคำสั่งนี้",
    "backup-failed": "อ่านข้อมูลสำรองไม่ครบ จึงไม่ได้ทำต่อเพื่อความปลอดภัย",
    "empty-host": "กรุณาใส่ IP ของเครื่องพิมพ์", "bad-host": "IP หรือชื่อเครื่องไม่ถูกต้อง",
    "empty-backup": "ไฟล์สำรองว่างหรืออ่านไม่ได้", "no-identification": "เครื่องพิมพ์ไม่ตอบกลับ",
  })[e] || (res?.kind === "TimeoutError" ? "เครื่องพิมพ์ไม่ตอบกลับ (หมดเวลา)" : e || "เกิดข้อผิดพลาด");
}

async function call(method, ...args) {
  try {
    const res = await api[method](...args);
    return res || { ok: false, error: "no-response" };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

/* ------------------------------------------------------------ navigation */
function go(page) {
  S.page = page;
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${page}`));
  const [t, sub] = PAGES[page];
  $("#pageTitle").innerHTML = `${esc(t)}<small>${esc(sub)}</small>`;
  $("#content").scrollTop = 0;
  if (page === "stats") renderStats();
  if (page === "care") renderCare();
  if (page === "history") loadHistory();
  if (page === "models") loadModels();
  if (page === "settings") loadSettingsPage();
}

/* ------------------------------------------------------------ connection */
function setConn(mode, { silent = false } = {}) {
  S.conn = mode;
  $$("#connSeg button").forEach((b) => b.classList.toggle("on", b.dataset.conn === mode));
  $("#hostBox").classList.toggle("show", mode === "wifi");
  if (!silent) {
    S.printer = null;
    clearPrinter();
    setHero("idle");
    call("save_settings", { connection: mode });
  }
  if (mode === "wifi" && !silent) setTimeout(() => $("#hostInput").focus(), 50);
}

function renderRecent() {
  $("#recentHosts").innerHTML = (S.settings.recent_hosts || []).map((h) => `<option value="${esc(h)}">`).join("");
}

/* ------------------------------------------------------------ hero */
function setHero(state, sub) {
  S.heroState = state;
  const [ic, cls, title, text] = HERO[state];
  const orb = $("#heroOrb");
  orb.className = `orb ${cls}`;
  orb.innerHTML = ic ? icon(ic) : "";
  $("#heroTitle").textContent = title;
  $("#heroSub").textContent = sub ?? (typeof text === "function" ? text() : text);

  if (state !== "busy") {
    const [done, cur] = STEP_FOR[state] || [0, 0];
    renderSteps(done, cur);
  }
  renderHeroActions();
}

function renderSteps(done, cur) {
  $("#steps").innerHTML = STEP_LABELS.map((l, i) => {
    const cls = i < done ? "done" : i === cur ? "cur" : "";
    const mark = i < done ? icon("check").replace("<svg>", '<svg width="12" height="12">') : i + 1;
    return `${i ? '<span class="step-line"></span>' : ""}<span class="step ${cls}"><i>${mark}</i>${l}</span>`;
  }).join("");
}

function renderHeroActions() {
  const st = S.heroState, p = S.printer, busy = st === "busy";
  const btns = [];
  if (st === "full") {
    btns.push(`<button class="btn lg danger" data-act="reset">${icon("shield")}รีเซ็ตซับหมึก</button>`);
    btns.push(`<button class="btn lg" data-act="check">${icon("refresh")}ตรวจสอบอีกครั้ง</button>`);
  } else {
    const label = st === "idle" ? "ตรวจสอบเครื่องพิมพ์" : st === "error" ? "ลองอีกครั้ง" : busy ? "กรุณารอสักครู่..." : "ตรวจสอบอีกครั้ง";
    btns.push(`<button class="btn lg primary" data-act="check" ${busy ? "disabled" : ""}>${busy ? '<i class="spin"></i>' : icon("refresh")}${label}</button>`);
    if (p && p.supported && ["ok", "failed", "backup_failed"].includes(st))
      btns.push(`<button class="btn lg ghost" data-act="reset">${icon("shield")}รีเซ็ตซับหมึกอยู่ดี</button>`);
  }
  if (p && !busy && (["unsupported", "failed", "full"].includes(st)))
    btns.push(`<button class="btn lg ghost" data-act="temp">${icon("bolt")}รีเซ็ตชั่วคราว</button>`);
  $("#heroActions").innerHTML = btns.join("");
}

function setBusy(on, sub) {
  S.busy = on;
  if (on) {
    setHero("busy", sub);
    $$("#connSeg button, #scanBtn, #hostInput").forEach((b) => (b.disabled = true));
  } else {
    $$("#connSeg button, #scanBtn, #hostInput").forEach((b) => (b.disabled = false));
  }
}

/* ------------------------------------------------------------ check */
function clearPrinter() {
  ["#kvModel", "#kvStatus", "#kvSerial", "#kvConn", "#kvSupport"].forEach((s) => ($(s).textContent = "—"));
  $("#gauges").innerHTML = ["ซับหมึก 1", "ซับหมึก 2"].map((l) => gaugeHtml(l, null, "unknown")).join("");
  $("#padPill").className = "pill"; $("#padPill").textContent = "—";
  renderInks([]);
  $("#alerts").innerHTML = "";
  updateChip();
  $("#careDot").classList.add("hidden");
}

function updateChip() {
  const p = S.printer, chip = $("#deviceChip");
  if (!p) { chip.innerHTML = `<i class="dot"></i><span>ยังไม่ได้เชื่อมต่อ</span>`; return; }
  const cls = p.waste_full ? "bad" : p.low_inks.length ? "warn" : "ok";
  chip.innerHTML = `<i class="dot ${cls}"></i><span>${esc(p.model)} · ${esc(p.connection)}</span>`;
}

async function onCheck() {
  if (S.busy) return;
  if (S.conn === "wifi") {
    S.host = $("#hostInput").value.trim();
    if (!S.host) { toast("กรุณาใส่ IP ของเครื่องพิมพ์ หรือกดค้นหา", "bad"); $("#hostInput").focus(); return; }
  }
  setBusy(true, "กำลังอ่านข้อมูลจากเครื่องพิมพ์...");
  renderSteps(1, 1);
  const res = await call("check", hostArg());
  setBusy(false);
  if (!res.ok) {
    S.printer = null; clearPrinter();
    setHero("error", res.error === "bad-host" ? "IP หรือชื่อเครื่องไม่ถูกต้อง" : undefined);
    return;
  }
  S.printer = res;
  if (S.conn === "wifi") {
    S.settings.recent_hosts = [S.host, ...(S.settings.recent_hosts || []).filter((h) => h !== S.host)].slice(0, 6);
    renderRecent();
  }
  renderPrinter(res);
  if (!res.supported) setHero("unsupported", `อ่านข้อมูล ${res.model || "เครื่องนี้"} ได้ แต่ยังไม่มีข้อมูลสำหรับรีเซ็ตถาวร ลอง “รีเซ็ตชั่วคราว” ได้`);
  else if (res.waste_full) setHero("full");
  else setHero("ok");
  if (res.low_inks.length) toast(`หมึก${res.low_inks.map((i) => i.th).join(", ")} ใกล้หมด`, "info");
}

function gaugeHtml(label, percent, state) {
  const pct = percent == null ? null : Math.max(0, percent);
  const cls = state === "full" || (pct != null && pct >= 100) ? "bad" : state === "near" || (pct != null && pct >= 85) ? "warn" : "";
  const val = pct == null ? (state === "full" ? "เต็ม" : state === "near" ? "ใกล้เต็ม" : state === "ok" ? "ปกติ" : "—") : `${pct.toFixed(pct < 10 ? 1 : 0)}%`;
  const width = pct == null ? (state === "full" ? 100 : state === "near" ? 88 : state === "ok" ? 30 : 0) : Math.min(100, pct);
  return `<div class="gauge"><div class="lbl"><span>${esc(label)}</span></div>
    <div class="val num">${val}</div><div class="meter ${cls}"><span style="width:${width}%"></span></div></div>`;
}

function renderPrinter(p) {
  $("#kvModel").textContent = p.model || "ไม่ทราบ";
  $("#kvStatus").textContent = p.status_text || "—";
  $("#kvSerial").textContent = p.serial || "—";
  $("#kvConn").textContent = p.connection;
  $("#kvSupport").innerHTML = p.supported ? '<span class="pill ok">รองรับ</span>' : '<span class="pill warn">ชั่วคราวเท่านั้น</span>';

  const waste = p.waste || [];
  if (waste.length) {
    $("#gauges").innerHTML = waste.slice(0, 2).map((w, i) => gaugeHtml(WASTE_TH[w.key] || w.key, w.percent, p.pads[i])).join("");
  } else {
    $("#gauges").innerHTML = p.pads.map((s, i) => gaugeHtml(`ซับหมึก ${i + 1}`, null, s)).join("");
  }
  const padPill = $("#padPill");
  if (p.waste_full) { padPill.className = "pill bad"; padPill.textContent = "เต็ม"; }
  else if (p.pads.includes("near")) { padPill.className = "pill warn"; padPill.textContent = "ใกล้เต็ม"; }
  else if (p.pads.includes("ok")) { padPill.className = "pill ok"; padPill.textContent = "ปกติ"; }
  else { padPill.className = "pill"; padPill.textContent = "—"; }

  renderInks(p.inks, p.ink_threshold);
  renderAlerts(p);
  updateChip();
  $("#careDot").classList.toggle("hidden", !p.low_inks.length);
}

function renderInks(inks, threshold = S.settings.ink_threshold) {
  const pill = $("#inkPill");
  if (!inks || !inks.length) {
    const names = ["Black", "Cyan", "Magenta", "Yellow"];
    $("#inks").innerHTML = names.map((n) => `<div class="ink"><span class="pct num muted">—</span>
      <div class="tube" style="--c:${inkColor(n)}"><span style="height:0"></span></div>
      <span class="name">${{ Black: "ดำ", Cyan: "ฟ้า", Magenta: "ชมพู", Yellow: "เหลือง" }[n]}</span></div>`).join("");
    pill.className = "pill"; pill.textContent = "—";
    return;
  }
  $("#inks").innerHTML = inks.map((i) => {
    const low = i.level <= threshold;
    return `<div class="ink ${low ? "low" : ""}" title="${esc(i.name)}"><span class="pct num">${i.level}%</span>
      <div class="tube" style="--c:${inkColor(i.name)}"><span style="height:${Math.max(3, Math.min(100, i.level))}%"></span></div>
      <span class="name">${esc(i.th)}</span></div>`;
  }).join("");
  const low = inks.filter((i) => i.level <= threshold).length;
  pill.className = low ? "pill bad" : "pill ok";
  pill.textContent = low ? `ใกล้หมด ${low} สี` : "เพียงพอ";
}

function renderAlerts(p) {
  const out = [];
  if (p.low_inks.length) {
    const list = p.low_inks.map((i) => `${i.th} ${i.level}%`).join(" · ");
    out.push(`<div class="alert bad">${icon("drop")}<div><b>หมึกใกล้หมด</b>${esc(list)} — เติมหมึกก่อนพิมพ์งานใหญ่ (เตือนที่ ≤ ${p.ink_threshold}% ตั้งค่าได้ในหน้า “ตั้งค่า”)</div></div>`);
  }
  if (p.advice && p.advice.count > 0) {
    out.push(`<div class="alert ${p.advice.level === "warn" ? "warn" : "info"}">${icon(p.advice.level === "warn" ? "warn" : "info")}<div><b>แผ่นซับหมึก</b>${esc(p.advice.text)}</div></div>`);
  }
  if (p.error_code && !p.waste_full) {
    out.push(`<div class="alert warn">${icon("warn")}<div><b>เครื่องพิมพ์แจ้งข้อผิดพลาด</b>${esc(p.error_code)}</div></div>`);
  }
  $("#alerts").innerHTML = out.join("");
}

/* ------------------------------------------------------------ modals */
function modal(html, { wide = false } = {}) {
  const m = $("#modal");
  m.className = `modal${wide ? " wide" : ""}`;
  m.innerHTML = html;
  $("#scrim").classList.add("show");
  return new Promise((resolve) => {
    S._modalResolve = resolve;
    m.onclick = (e) => {
      const b = e.target.closest("[data-m]");
      if (b && !b.disabled) closeModal(b.dataset.m);
    };
  });
}
function closeModal(value) {
  $("#scrim").classList.remove("show");
  const r = S._modalResolve; S._modalResolve = null;
  if (r) r(value);
}
$("#scrim").addEventListener("mousedown", (e) => { if (e.target.id === "scrim" && !S.modalLocked) closeModal(null); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#scrim").classList.contains("show") && !S.modalLocked) closeModal(null); });

function confirmBox({ title, sub = "", points = [], agree, ok = "ยืนยัน", danger = false, orb = "warn", extra = "" }) {
  const html = `
    <div class="m-head"><div class="orb ${orb}">${icon(orb === "bad" ? "alert" : orb === "ok" ? "check" : "warn")}</div>
      <div><h3>${esc(title)}</h3>${sub ? `<div class="m-sub">${esc(sub)}</div>` : ""}</div></div>
    ${points.length ? `<ul class="points">${points.map(([ic, t]) => `<li>${icon(ic)}<span>${esc(t)}</span></li>`).join("")}</ul>` : ""}
    ${extra}
    ${agree ? `<label class="check"><input type="checkbox" id="mAgree">${esc(agree)}</label>` : ""}
    <div class="m-foot"><button class="btn ghost" data-m="cancel">ยกเลิก</button>
      <button class="btn ${danger ? "danger" : "primary"}" data-m="ok" id="mOk" ${agree ? "disabled" : ""}>${esc(ok)}</button></div>`;
  const p = modal(html);
  if (agree) $("#mAgree").addEventListener("change", (e) => ($("#mOk").disabled = !e.target.checked));
  return p.then((v) => v === "ok");
}

/* ------------------------------------------------------------ reset */
async function onReset() {
  const p = S.printer;
  if (!p || !p.supported || S.busy) return;
  const extra = p.advice && p.advice.count > 0
    ? `<div class="alert ${p.advice.level === "warn" ? "warn" : "info"}" style="margin-top:14px">${icon("info")}<div>${esc(p.advice.text)}</div></div>` : "";
  const yes = await confirmBox({
    title: `รีเซ็ตซับหมึก ${p.model}?`, sub: `ผ่าน ${p.connection}`, danger: true, orb: "warn",
    points: [["save", "โปรแกรมจะสำรองข้อมูลเครื่องพิมพ์ไว้ก่อนอัตโนมัติ"],
      ["plug", "ห้ามปิดเครื่องพิมพ์หรือถอดสายระหว่างรีเซ็ต"],
      ["drop", "แผ่นซับหมึกจริงยังเต็ม ควรล้าง/เปลี่ยน หรือต่อถังหมึกทิ้ง"],
      ["shield", "การรีเซ็ตเองอาจทำให้เสียสิทธิ์ประกันจาก Epson"]],
    extra, agree: "ฉันเข้าใจและต้องการรีเซ็ต", ok: "รีเซ็ตเลย" });
  if (!yes) return;
  setBusy(true, "กำลังสำรองข้อมูลและรีเซ็ต... ห้ามปิดเครื่องพิมพ์");
  renderSteps(2, 2);
  const res = await call("reset", p.model, p.serial, hostArg());
  setBusy(false);
  if (res.ok) {
    p.pads = p.pads.map(() => "unknown"); p.waste_full = false;
    p.waste = (p.waste || []).map((w) => ({ ...w, percent: 0 }));
    await refreshAdvice();
    renderPrinter(p);
    $("#kvStatus").textContent = "รอปิด-เปิดเครื่อง";
    setHero("done");
    toast("รีเซ็ตสำเร็จ ไฟล์สำรองอยู่ในหน้า “ประวัติและสำรอง”");
  } else if (String(res.error).includes("backup-failed")) setHero("backup_failed");
  else setHero("failed");
}

async function onTempReset() {
  const p = S.printer;
  if (!p || S.busy) return;
  const yes = await confirmBox({
    title: "รีเซ็ตชั่วคราว?", sub: `${p.model} · ${p.connection}`, orb: "warn",
    points: [["bolt", "ปลดล็อกให้เครื่องพิมพ์ต่อได้อีกระยะหนึ่ง ใช้กับรุ่นใหม่ที่ล็อก EEPROM"],
      ["info", "ไม่ได้ล้างตัวนับ เครื่องจะหยุดอีกครั้งในภายหลัง ทำซ้ำได้"],
      ["drop", "แผ่นซับหมึกจริงยังเต็ม ควรล้าง/เปลี่ยนโดยเร็ว"]],
    ok: "รีเซ็ตชั่วคราว" });
  if (!yes) return;
  setBusy(true, "กำลังส่งคำสั่งรีเซ็ตชั่วคราว...");
  const res = await call("temp_reset", p.model, p.serial, hostArg());
  setBusy(false);
  if (res.ok) { await refreshAdvice(); renderAlerts(p); setHero("temp_done"); toast("รีเซ็ตชั่วคราวสำเร็จ ปิด-เปิดเครื่องพิมพ์หนึ่งครั้ง"); }
  else setHero("failed", "เครื่องพิมพ์ไม่รับคำสั่งรีเซ็ตชั่วคราว รุ่นนี้หรือเฟิร์มแวร์นี้อาจไม่รองรับ");
}

/* ------------------------------------------------------------ stats */
function needPrinter(target, what) {
  target.innerHTML = `<div class="glass card empty"><div>
    <div class="e-icon" style="margin:0 auto 14px">${icon("printer")}</div>
    <h3>ยังไม่ได้ตรวจสอบเครื่องพิมพ์</h3><p>${esc(what)}</p>
    <button class="btn primary" data-act="check-go">${icon("refresh")}ตรวจสอบเครื่องพิมพ์</button></div></div>`;
}

function renderStats() {
  const body = $("#statsBody"), p = S.printer;
  if (!p) return needPrinter(body, "กดตรวจสอบเครื่องพิมพ์ก่อน แล้วโปรแกรมจะอ่านจำนวนหน้าที่พิมพ์ จำนวนครั้งล้างหัว และการเติมหมึก");
  if (!p.stats.length) {
    body.innerHTML = `<div class="glass card empty"><div><div class="e-icon" style="margin:0 auto 14px">${icon("chart")}</div>
      <h3>ไม่มีสถิติสำหรับ ${esc(p.model)}</h3><p>${p.supported ? "ฐานข้อมูลไม่มีตำแหน่งตัวนับของรุ่นนี้" : "รุ่นนี้ยังไม่อยู่ในฐานข้อมูล จึงอ่านตัวนับไม่ได้"}</p></div></div>`;
    return;
  }
  const groups = [["usage", "การใช้งาน"], ["clean", "การล้างหัวพิมพ์"], ["ink", "การเติม/เปลี่ยนหมึก"], ["info", "ข้อมูลเครื่อง"]];
  const tile = (r) => `<div class="glass tile"><div class="t-lbl">${r.color ? `<span class="swatch" style="background:${inkColor(r.color)}"></span>` : ""}${esc(r.label)}</div>
    <div class="t-val num">${r.value == null ? "—" : fmt(r.value)}${r.unit && r.value != null ? `<small>${esc(r.unit)}</small>` : ""}</div></div>`;
  const waste = (p.waste || []).map((w) => ({ label: WASTE_TH[w.key] || w.key, value: `${w.percent.toFixed(1)}`, unit: "%" }));
  let html = "";
  for (const [g, title] of groups) {
    const rows = p.stats.filter((r) => r.group === g);
    if (g === "info") rows.push(...waste);
    if (!rows.length) continue;
    html += `<div class="section-title">${title}</div><div class="tiles">${rows.map(tile).join("")}</div>`;
  }
  body.innerHTML = `<div class="alert info" style="margin-bottom:4px">${icon("info")}<div>ค่าจาก ${esc(p.model)} (${esc(p.serial || "ไม่ทราบซีเรียล")}) ณ เวลาที่ตรวจสอบล่าสุด กดตรวจสอบอีกครั้งเพื่ออัปเดต</div></div>${html}`;
}

/* ------------------------------------------------------------ care */
async function renderCare() {
  const p = S.printer;
  if (!p) { needPrinter($("#careNeed"), "ต้องรู้รุ่นเครื่องพิมพ์ก่อนส่งคำสั่งบำรุงรักษา"); $("#careBody").classList.add("hidden"); return; }
  $("#careNeed").innerHTML = "";
  $("#careBody").classList.remove("hidden");
  // queue / route
  if (S.conn === "wifi") {
    $("#queueBody").innerHTML = `<div class="row-item" style="padding:6px 0"><span class="r-icon">${icon("wifi")}</span><div class="r-main"><div class="r-title">Wi‑Fi ${esc(S.host)}</div><div class="r-sub">ส่งงานแบบ LPR ไปที่เครื่องพิมพ์โดยตรง</div></div><span></span></div>`;
  } else {
    const q = await call("queues");
    const list = (q.queues || []);
    const auto = list.find((n) => n.toLowerCase().replace(/\s/g, "").includes((p.model || "").toLowerCase())) || "";
    S.queue = S.queue && list.includes(S.queue) ? S.queue : auto;
    $("#queueBody").innerHTML = list.length
      ? `<label class="muted small">คิวพิมพ์ของ Windows</label>
         <select class="input" id="queueSel" style="width:100%;margin-top:6px">${list.map((n) => `<option ${n === S.queue ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`
      : `<div class="alert warn">${icon("warn")}<div>${S.info.platform === "win32" ? "ไม่พบเครื่องพิมพ์ใน Windows ติดตั้งไดรเวอร์ Epson ก่อน" : "ใช้ได้บน Windows เท่านั้น"}${S.info.mock ? " (โหมดทดสอบ: จำลองการส่ง)" : ""}</div></div>`;
    const sel = $("#queueSel");
    if (sel) { if (!S.queue) S.queue = sel.value; sel.onchange = () => (S.queue = sel.value); }
  }
  loadTimer();
}

async function onMaint(action) {
  const p = S.printer;
  if (!p || S.busy) return;
  const meta = { nozzle_check: ["พิมพ์หน้าเช็กหัวพิมพ์?", "ใส่กระดาษ A4 ในเครื่องพิมพ์ก่อน", "พิมพ์เลย"],
    clean: ["ล้างหัวพิมพ์?", "ใช้เวลาประมาณ 1–2 นาที ห้ามปิดเครื่องระหว่างล้าง", "เริ่มล้าง"],
    power_clean: ["ล้างหัวพิมพ์แบบเข้ม?", "ใช้หมึกมากและเพิ่มหมึกเสียในแผ่นซับ ใช้เมื่อจำเป็นเท่านั้น", "ล้างแบบเข้ม"] }[action];
  const points = action === "nozzle_check" ? [] : [["drop", "หมึกที่ใช้ล้างจะไหลลงแผ่นซับหมึก ทำให้ตัวนับเพิ่มขึ้น"]];
  const yes = await confirmBox({ title: meta[0], sub: meta[1], points, ok: meta[2], orb: action === "power_clean" ? "warn" : "busy",
    danger: action === "power_clean" });
  if (!yes) return;
  const btn = $(`[data-maint="${action}"]`);
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<i class="spin"></i>กำลังส่ง...';
  const res = await call("maintenance", action, p.model, p.serial, hostArg(), S.conn === "usb" ? (S.queue || null) : null);
  btn.disabled = false; btn.innerHTML = old;
  if (res.ok) toast(action === "nozzle_check" ? "ส่งหน้าเช็กหัวพิมพ์แล้ว" : "ส่งคำสั่งล้างหัวพิมพ์แล้ว รอเครื่องทำงานจนเสร็จ");
  else toast(errorText(res), "bad", 6000);
}

const TIMER_TH = (m) => (m >= 60 ? `${m / 60} ชม.` : `${m} นาที`);
async function loadTimer() {
  const p = S.printer, box = $("#timerBody");
  if (!p.supported) { box.innerHTML = `<span class="muted small">รุ่นนี้ยังไม่รองรับการตั้งเวลา</span>`; return; }
  box.innerHTML = `<span class="muted small"><i class="spin" style="vertical-align:-3px;margin-right:6px"></i>กำลังอ่านค่า...</span>`;
  const r = await call("power_timer", p.model, hostArg());
  if (!r.ok) { box.innerHTML = `<span class="muted small">อ่านค่าไม่ได้: ${esc(errorText(r))}</span>`; return; }
  if (!r.supported) { box.innerHTML = `<span class="muted small">ฐานข้อมูลยังไม่มีตำแหน่งเวลาปิดเครื่องของ ${esc(p.model)}</span>`; return; }
  S.timerSel = r.minutes;
  const draw = () => {
    box.innerHTML = `<div class="chips">${r.choices.map((m) => `<button class="chip-btn ${m === S.timerSel ? "on" : ""}" data-min="${m}">${TIMER_TH(m)}${m === r.minutes ? '<span class="cur">ปัจจุบัน</span>' : ""}</button>`).join("")}</div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:14px"><span class="small muted">ตอนนี้: <b class="num">${r.minutes == null ? "—" : TIMER_TH(r.minutes)}</b>${r.choices.includes(r.minutes) || r.minutes == null ? "" : " (ค่าที่ไม่อยู่ในตัวเลือก)"}</span><span style="flex:1"></span>
      <button class="btn sm primary" id="timerSave" ${S.timerSel === r.minutes || S.timerSel == null ? "disabled" : ""}>บันทึก</button></div>`;
    $$("[data-min]", box).forEach((b) => (b.onclick = () => { S.timerSel = +b.dataset.min; draw(); }));
    $("#timerSave").onclick = async () => {
      const yes = await confirmBox({ title: `ตั้งเวลาปิดเครื่องเป็น ${TIMER_TH(S.timerSel)}?`, sub: p.model, orb: "busy",
        points: [["save", "สำรองข้อมูลเครื่องพิมพ์ก่อนเขียนค่าใหม่"], ["plug", "ห้ามปิดเครื่องหรือถอดสายระหว่างบันทึก"]], ok: "บันทึก" });
      if (!yes) return;
      $("#timerSave").disabled = true; $("#timerSave").innerHTML = '<i class="spin"></i>';
      const w = await call("set_power_timer", p.model, p.serial, S.timerSel, hostArg());
      if (w.ok) { toast(`ตั้งเวลาปิดเครื่องเป็น ${TIMER_TH(S.timerSel)} แล้ว`); r.minutes = S.timerSel; }
      else toast(errorText(w) || "บันทึกไม่สำเร็จ", "bad");
      draw();
    };
  };
  draw();
}

/* ------------------------------------------------------------ history & backups */
function when(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  return d.toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" });
}

async function refreshAdvice() {
  const p = S.printer;
  if (!p) return;
  const r = await call("advice", p.serial, p.model);
  if (r.ok) { delete r.ok; p.advice = r; }
}

async function loadHistory() {
  await refreshAdvice();
  const p = S.printer;
  const adv = p && p.advice;
  $("#adviceCard").innerHTML = p
    ? `<div class="card-h" style="margin:0"><span class="icon-tile">${icon("pad")}</span><div><h3 style="color:var(--text)">${esc(p.model)} · ${esc(p.serial || "ไม่ทราบซีเรียล")}</h3>
        <div class="small muted">${adv && adv.count ? `รีเซ็ตแล้ว ${adv.count} ครั้ง · ล่าสุด ${when(adv.last)}` : "ยังไม่เคยรีเซ็ตด้วยโปรแกรมนี้"}</div></div>
        <span class="spacer"></span><span class="pill ${adv && adv.level === "warn" ? "warn" : adv && adv.count ? "info" : "ok"}">${adv && adv.level === "warn" ? "ควรเปลี่ยนแผ่นซับ" : adv && adv.count ? "ควรล้างแผ่นซับ" : "ปกติ"}</span></div>
       ${adv && adv.count ? `<p class="small" style="margin:12px 0 0;color:var(--text-2)">${esc(adv.text)}</p>` : ""}`
    : `<div class="card-h" style="margin:0"><span class="icon-tile">${icon("pad")}</span><div><h3 style="color:var(--text)">คำแนะนำแผ่นซับหมึก</h3><div class="small muted">ตรวจสอบเครื่องพิมพ์ก่อน แล้วโปรแกรมจะบอกว่าเครื่องนี้ถูกรีเซ็ตมากี่ครั้งและควรเปลี่ยนแผ่นซับหรือยัง</div></div></div>`;

  const [h, b] = await Promise.all([call("history"), call("backups")]);
  const items = h.items || [];
  $("#histList").innerHTML = items.length ? items.slice(0, 80).map((e) => {
    const [ic, label] = KIND[e.kind] || ["info", e.kind];
    let sub = `${esc(e.model)} · ${esc(e.connection || "")}`;
    if (e.kind === "power_timer" && e.detail) sub += ` · ${TIMER_TH(e.detail.minutes)}`;
    if (e.kind === "restore" && e.detail) sub += ` · เขียน ${e.detail.written} ค่า`;
    return `<div class="row-item"><span class="r-icon ${e.ok ? "ok" : "bad"}">${icon(ic)}</span>
      <div class="r-main"><div class="r-title">${esc(label)}</div><div class="r-sub">${sub}</div></div>
      <div class="r-side"><span class="small muted">${when(e.time)}</span><span class="pill ${e.ok ? "ok" : "bad"}">${e.ok ? "สำเร็จ" : "ไม่สำเร็จ"}</span></div></div>`;
  }).join("") : `<div class="muted small" style="padding:18px 4px">ยังไม่มีประวัติ</div>`;

  const bks = b.items || [];
  $("#bkList").innerHTML = bks.length ? bks.slice(0, 60).map((x, i) => {
    const mine = p && p.model === x.model;
    return `<div class="row-item"><span class="r-icon">${icon("save")}</span>
      <div class="r-main"><div class="r-title">${esc(x.model || "ไม่ทราบรุ่น")} <span class="muted small">· ${esc(x.serial)}</span></div><div class="r-sub">${when(x.when)}</div></div>
      <div class="r-side"><button class="btn sm ${mine ? "" : "ghost"}" data-restore="${i}" ${p && p.supported && mine ? "" : "disabled"} title="${p ? (mine ? "กู้คืนไฟล์นี้" : "ไฟล์นี้ไม่ใช่ของรุ่นที่ต่ออยู่") : "ตรวจสอบเครื่องพิมพ์ก่อน"}">${icon("restore")}กู้คืน</button></div></div>`;
  }).join("") : `<div class="muted small" style="padding:18px 4px">ยังไม่มีไฟล์สำรอง โปรแกรมจะสร้างให้อัตโนมัติก่อนรีเซ็ตทุกครั้ง</div>`;
  $$("[data-restore]").forEach((btn) => (btn.onclick = () => onRestore(bks[+btn.dataset.restore])));
}

async function onRestore(bk) {
  const p = S.printer;
  if (!p || S.busy) return;
  toast("กำลังเทียบไฟล์สำรองกับเครื่องพิมพ์...", "info", 2200);
  const plan = await call("restore_plan", bk.path, p.model, p.serial, hostArg());
  if (!plan.ok) { toast(errorText(plan), "bad", 6000); return; }
  if (!plan.diff.length) {
    await modal(`<div class="m-head"><div class="orb ok">${icon("check")}</div><div><h3>ไม่มีอะไรต้องกู้คืน</h3><div class="m-sub">ค่าในเครื่องตรงกับไฟล์สำรองทุกตำแหน่งแล้ว</div></div></div>
      <div class="m-foot"><button class="btn primary" data-m="ok">ตกลง</button></div>`);
    return;
  }
  const rows = plan.diff.slice(0, 120).map((d) => `<tr><td>0x${d.addr.toString(16).toUpperCase().padStart(2, "0")}</td><td>${d.now}</td><td>${d.backup}</td></tr>`).join("");
  const yes = await confirmBox({
    title: `กู้คืน ${plan.diff.length} ค่า?`, sub: `จากไฟล์ ${bk.name}`, orb: "warn", danger: true,
    points: [["save", "สำรองค่าปัจจุบันไว้อีกไฟล์ก่อน จึงย้อนกลับได้"],
      ["restore", "จะเขียนเฉพาะตำแหน่งที่ต่างจากไฟล์สำรอง"],
      ["plug", "ห้ามปิดเครื่องพิมพ์หรือถอดสายระหว่างกู้คืน"]],
    extra: `<div class="scroll-box"><table class="table"><thead><tr><th>ตำแหน่ง</th><th>ตอนนี้</th><th>ในไฟล์สำรอง</th></tr></thead><tbody>${rows}</tbody></table></div>`,
    agree: "ฉันเข้าใจและต้องการเขียนค่าเดิมกลับ", ok: "กู้คืนเลย" });
  if (!yes) return;
  go("home");
  setBusy(true, "กำลังกู้คืนข้อมูลเครื่องพิมพ์... ห้ามปิดเครื่อง");
  const res = await call("restore", bk.path, p.model, p.serial, hostArg());
  setBusy(false);
  if (res.ok) { setHero("done", `กู้คืนแล้ว ${res.written} ค่า ปิด-เปิดเครื่องพิมพ์ แล้วกด “ตรวจสอบอีกครั้ง”`); toast("กู้คืนสำเร็จ"); }
  else setHero("failed", res.failed ? `เขียนไม่สำเร็จ ${res.failed.length} ตำแหน่ง (สำเร็จ ${res.written}) ไฟล์ก่อนกู้คืนถูกเก็บไว้แล้ว` : errorText(res));
}

/* ------------------------------------------------------------ models */
async function loadModels() {
  if (!S.models) {
    $("#modelGrid").innerHTML = `<span class="muted small"><i class="spin" style="vertical-align:-3px;margin-right:6px"></i>กำลังโหลด...</span>`;
    const r = await call("models");
    S.models = r.items || [];
  }
  drawModels();
}

function drawModels() {
  const q = $("#modelSearch").value.trim().toLowerCase().replace(/\s+/g, "");
  const f = S.modelFilter, mine = S.printer && S.printer.model;
  const list = S.models.filter((m) => {
    if (f === "timer" && !m.timer) return false;
    if (f === "stats" && !m.stats) return false;
    if (!q) return true;
    return [m.name, ...m.aliases].some((n) => n.toLowerCase().replace(/\s+/g, "").includes(q));
  });
  if (mine) list.sort((a, b) => (b.name === mine || b.aliases.includes(mine)) - (a.name === mine || a.aliases.includes(mine)));
  $("#modelCount").textContent = q || f !== "all" ? `${list.length} / ${S.models.length} รุ่น` : `${S.models.length} รุ่น`;
  $("#modelGrid").innerHTML = list.length ? list.map((m) => {
    const isMine = mine && (m.name === mine || m.aliases.includes(mine));
    return `<div class="model ${isMine ? "mine" : ""}"><div class="m-name">${esc(m.name)}${isMine ? ' <span class="pill info" style="height:20px;font-size:11px">เครื่องคุณ</span>' : ""}</div>
      ${m.aliases.length ? `<div class="m-alias" title="${esc(m.aliases.join(", "))}">${esc(m.aliases.join(", "))}</div>` : ""}
      <div class="m-tags"><span class="tag ${m.reset ? "on" : ""}">รีเซ็ต</span><span class="tag ${m.stats ? "on" : ""}">สถิติ</span><span class="tag ${m.timer ? "on" : ""}">ตั้งเวลาปิด</span></div></div>`;
  }).join("") : `<div class="glass card empty" style="grid-column:1/-1"><div><div class="e-icon" style="margin:0 auto 14px">${icon("search")}</div><h3>ไม่พบรุ่นนี้</h3><p>รุ่นที่ไม่อยู่ในรายการอาจยังใช้ “รีเซ็ตชั่วคราว” ได้</p></div></div>`;
}

/* ------------------------------------------------------------ settings */
async function loadSettingsPage() {
  const r = $("#inkRange");
  r.value = S.settings.ink_threshold;
  paintRange();
  $("#setVer").textContent = `v${S.info.version || "—"}${S.info.mock ? " (โหมดทดสอบ)" : ""}`;
  $("#bkDir").textContent = S.info.backup_dir || "—";
  loadLog();
}
function paintRange() {
  const r = $("#inkRange");
  const p = ((r.value - r.min) / (r.max - r.min)) * 100;
  r.style.setProperty("--p", `${p}%`);
  $("#inkRangeVal").textContent = `${r.value}%`;
}
async function loadLog() {
  const r = await call("tech_log");
  $("#techLog").textContent = (r.lines || []).join("\n") || "ยังไม่มีบันทึก";
}

/* ------------------------------------------------------------ network scan */
async function onScan() {
  const html = `<div class="m-head"><div class="orb busy">${icon("wifi")}</div><div><h3>ค้นหาเครื่องพิมพ์ในวงแลน</h3>
    <div class="m-sub" id="scanSub">กำลังค้นหา... ใช้เวลาไม่เกิน 1 นาที</div></div></div>
    <div class="meter" style="margin:4px 0 12px"><span id="scanBar" style="width:2%"></span></div>
    <div class="list" id="scanList"></div>
    <div class="m-foot"><button class="btn ghost" data-m="cancel">ปิด</button></div>`;
  const done = modal(html, { wide: true });
  await call("scan_start");
  let stopped = false;
  done.then(() => (stopped = true));
  while (!stopped) {
    const s = await call("scan_status");
    const bar = $("#scanBar");
    if (bar) bar.style.width = `${Math.max(2, (s.progress || 0) * 100)}%`;
    if (s.state === "done" || s.state === "error") { if (!stopped) drawScan(s); break; }
    await new Promise((r) => setTimeout(r, 400));
  }
  const pick = await done;
  if (pick && pick.startsWith("ip:")) {
    S.host = pick.slice(3); $("#hostInput").value = S.host;
    onCheck();
  }
}

function drawScan(s) {
  const orb = $("#modal .orb");
  if (orb) orb.className = `orb ${s.results && s.results.length ? "ok" : "warn"}`;
  const sub = $("#scanSub");
  const bar = $("#scanBar");
  if (bar) bar.style.width = "100%";
  if (s.state === "error") { sub.textContent = "ค้นหาไม่สำเร็จ ใส่ IP เองแทนได้"; return; }
  const list = s.results || [];
  sub.textContent = list.length ? `พบ ${list.length} เครื่อง เลือกเครื่องที่ต้องการ` : "ไม่พบเครื่องพิมพ์ เช็กว่าเปิดเครื่องและต่อ Wi‑Fi วงเดียวกัน";
  $("#scanList").innerHTML = list.map((p) => `<div class="row-item"><span class="r-icon ${p.epson ? "" : "warn"}">${icon("printer")}</span>
    <div class="r-main"><div class="r-title">${esc(p.name)}</div><div class="r-sub num">${esc(p.ip)}${p.epson ? (p.supported ? " · รองรับรีเซ็ต" : " · รีเซ็ตชั่วคราวเท่านั้น") : " · ไม่ใช่ Epson"}</div></div>
    <div class="r-side"><button class="btn sm ${p.epson ? "primary" : "ghost"}" data-m="ip:${esc(p.ip)}">เลือก</button></div></div>`).join("");
}

/* ------------------------------------------------------------ updates */
async function checkUpdate(silent) {
  if (!silent) { $("#setUpd").textContent = "กำลังตรวจ..."; $("#footUpd").textContent = "กำลังตรวจ..."; }
  const r = await call("update_check");
  $("#footUpd").textContent = "ตรวจหาอัปเดต";
  if (!r.ok) { $("#setUpd").textContent = "ตรวจไม่ได้ (เช็กอินเทอร์เน็ต)"; if (!silent) toast("ตรวจหาอัปเดตไม่ได้ เช็กอินเทอร์เน็ต", "bad"); return; }
  if (!r.available) { $("#setUpd").textContent = "เป็นเวอร์ชันล่าสุดแล้ว"; if (!silent) toast(`v${r.current} เป็นเวอร์ชันล่าสุดแล้ว`); return; }
  S.release = r;
  $("#setUpd").textContent = `มี v${r.version}`;
  $("#updDot").classList.remove("hidden");
  $("#updText").textContent = `มีเวอร์ชันใหม่ v${r.version} (ตอนนี้ v${r.current})`;
  $("#updGo").textContent = "อัปเดตเลย"; $("#updGo").disabled = false;
  $("#updLater").classList.remove("hidden"); $("#updMeter").classList.add("hidden");
  $("#updBanner").classList.add("show");
}

async function startUpdate() {
  if (!S.release || S.busy) return;
  const r = await call("update_start");
  if (r.state === "browser") return;
  $("#updGo").disabled = true; $("#updGo").textContent = "กำลังโหลด...";
  $("#updLater").classList.add("hidden"); $("#updMeter").classList.remove("hidden");
  $("#updText").textContent = `กำลังดาวน์โหลด v${S.release.version}...`;
  for (;;) {
    const s = await call("update_status");
    $("#updMeter span").style.width = `${(s.progress || 0) * 100}%`;
    if (s.state === "installing") { $("#updText").textContent = "กำลังติดตั้ง โปรแกรมจะปิดแล้วเปิดใหม่เองในไม่กี่วินาที"; return; }
    if (s.state === "manual") { $("#updText").textContent = `โหลดไว้ที่ ${s.path} — โฟลเดอร์โปรแกรมเขียนไม่ได้ ปิดโปรแกรมแล้วใช้ไฟล์นี้แทน`; $("#updMeter").classList.add("hidden"); return; }
    if (s.state === "error") {
      $("#updText").textContent = s.error === "checksum" ? "ไฟล์ที่โหลดมาไม่ตรงกับต้นฉบับ จึงไม่ได้ติดตั้ง" : "ดาวน์โหลดไม่สำเร็จ ลองใหม่อีกครั้ง";
      $("#updGo").disabled = false; $("#updGo").textContent = "ลองอีกครั้ง"; $("#updLater").classList.remove("hidden"); $("#updMeter").classList.add("hidden");
      return;
    }
    await new Promise((res) => setTimeout(res, 250));
  }
}

/* ------------------------------------------------------------ wiring */
function wire() {
  $("#nav").addEventListener("click", (e) => { const b = e.target.closest(".nav-btn"); if (b) go(b.dataset.page); });
  $("#connSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && !S.busy && b.dataset.conn !== S.conn) setConn(b.dataset.conn); });
  $("#hostInput").addEventListener("keydown", (e) => { if (e.key === "Enter") onCheck(); });
  $("#hostInput").addEventListener("change", (e) => { S.host = e.target.value.trim(); });
  $("#scanBtn").addEventListener("click", onScan);
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-act]");
    if (a && !a.disabled) {
      const act = a.dataset.act;
      if (act === "check") onCheck();
      if (act === "reset") onReset();
      if (act === "temp") onTempReset();
      if (act === "check-go") { go("home"); onCheck(); }
    }
    const m = e.target.closest("[data-maint]");
    if (m && !m.disabled) onMaint(m.dataset.maint);
  });
  $("#histReload").addEventListener("click", loadHistory);
  $("#openFolder").addEventListener("click", () => call("open_backups"));
  $("#modelSearch").addEventListener("input", () => S.models && drawModels());
  $("#modelFilter").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S.modelFilter = b.dataset.f;
    $$("#modelFilter button").forEach((x) => x.classList.toggle("on", x === b));
    S.models && drawModels();
  });
  let saveT;
  $("#inkRange").addEventListener("input", () => {
    paintRange();
    S.settings.ink_threshold = +$("#inkRange").value;
    clearTimeout(saveT);
    saveT = setTimeout(() => call("save_settings", { ink_threshold: S.settings.ink_threshold }), 300);
    if (S.printer) {
      S.printer.ink_threshold = S.settings.ink_threshold;
      S.printer.low_inks = S.printer.inks.filter((i) => i.level <= S.settings.ink_threshold);
      renderPrinter(S.printer);
    }
  });
  $("#logReload").addEventListener("click", loadLog);
  $("#setUpdBtn").addEventListener("click", () => checkUpdate(false));
  $("#footUpd").addEventListener("click", () => checkUpdate(false));
  $("#updGo").addEventListener("click", startUpdate);
  $("#updLater").addEventListener("click", () => $("#updBanner").classList.remove("show"));
}

async function boot(theApi) {
  api = theApi;
  wire();
  clearPrinter();
  const info = await call("info");
  S.info = info;
  S.settings = info.settings || S.settings;
  $("#verLabel").textContent = `v${info.version || "—"}`;
  renderRecent();
  if (S.settings.connection === "wifi") {
    S.host = S.settings.host || "";
    $("#hostInput").value = S.host;
    setConn("wifi", { silent: true });
  }
  setHero("idle");
  if (!info.has_db) setHero("error", "ไม่พบไฟล์ข้อมูลรุ่นเครื่องพิมพ์ (printers.pickle)");
  if (info.mock) toast("โหมดทดสอบ: ใช้เครื่องพิมพ์จำลอง L4260", "info", 5000);
  setTimeout(() => checkUpdate(true), 1500);
}

/* pywebview injects window.pywebview.api and fires "pywebviewready".
   Opened in a normal browser (no pywebview), demo.js provides a fake API. */
(function start() {
  let started = false;
  const go2 = (a) => { if (!started) { started = true; boot(a); } };
  if (window.pywebview && window.pywebview.api) go2(window.pywebview.api);
  window.addEventListener("pywebviewready", () => go2(window.pywebview.api));
  setTimeout(() => { if (!started && window.DemoApi) go2(new window.DemoApi()); }, 900);
})();
