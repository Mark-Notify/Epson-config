/* Glass UI template — page switching, modal, toast.
   Replace the demo handlers at the bottom with your own logic. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (id) => `<svg><use href="#i-${id}"/></svg>`;

/* page id -> [title, subtitle] */
const PAGES = {
  home: ["ภาพรวม", "คำอธิบายหน้า"],
  stats: ["สถิติ", "ตัวเลขสรุป"],
  list: ["รายการ", "ประวัติการทำงาน"],
  settings: ["ตั้งค่า", "ปรับการทำงานของโปรแกรม"],
};

function go(page) {
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${page}`));
  const [t, sub] = PAGES[page];
  $("#pageTitle").innerHTML = `${esc(t)}<small>${esc(sub)}</small>`;
  $("#content").scrollTop = 0;
}

function toast(text, kind = "ok", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === "ok" ? "check" : kind === "bad" ? "warn" : "info")}<span>${esc(text)}</span>`;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; setTimeout(() => el.remove(), 320); }, ms);
}

/* modal(html) resolves with the data-m value of the button pressed */
let modalResolve = null;
function modal(html, { wide = false } = {}) {
  const m = $("#modal");
  m.className = `modal${wide ? " wide" : ""}`;
  m.innerHTML = html;
  $("#scrim").classList.add("show");
  return new Promise((resolve) => {
    modalResolve = resolve;
    m.onclick = (e) => { const b = e.target.closest("[data-m]"); if (b && !b.disabled) closeModal(b.dataset.m); };
  });
}
function closeModal(value) {
  $("#scrim").classList.remove("show");
  if (modalResolve) { modalResolve(value); modalResolve = null; }
}

function confirmBox(title, sub, okText = "ตกลง", kind = "warn") {
  return modal(`<div class="m-head"><div class="orb ${kind}">${icon(kind === "bad" ? "alert" : kind === "ok" ? "check" : "warn")}</div>
    <div><h3>${esc(title)}</h3><div class="m-sub">${esc(sub)}</div></div></div>
    <div class="m-foot"><button class="btn ghost" data-m="cancel">ยกเลิก</button>
    <button class="btn ${kind === "bad" ? "danger" : "primary"}" data-m="ok">${esc(okText)}</button></div>`);
}

/* ------------------------------------------------------------ wiring */
$("#nav").addEventListener("click", (e) => { const b = e.target.closest(".nav-btn"); if (b) go(b.dataset.page); });
$("#scrim").addEventListener("click", (e) => { if (e.target.id === "scrim") closeModal("cancel"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal("cancel"); });
$$("#modeSeg button").forEach((b) => b.addEventListener("click", () => {
  $$("#modeSeg button").forEach((x) => x.classList.toggle("on", x === b));
}));

/* demo */
$("#demoToast").addEventListener("click", () => toast("บันทึกแล้ว"));
$("#demoModal").addEventListener("click", async () => {
  const r = await confirmBox("ยืนยันการทำงาน", "ข้อความอธิบายสิ่งที่จะเกิดขึ้น", "ทำเลย");
  if (r === "ok") toast("เสร็จแล้ว");
});
$("#range").addEventListener("input", (e) => { $("#rangeVal").textContent = `${e.target.value}%`; });
