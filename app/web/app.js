// Claude Overlay — главное окно (движок Edge / WebView2).
// Программа (Python) присылает события пачками: ui.recv([[имя, данные], …]); окно зовёт программу через pywebview.api.
"use strict";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const api = (fn, ...a) => {
  try { if (window.pywebview && pywebview.api && pywebview.api[fn]) return pywebview.api[fn](...a); } catch (e) { console.error(e); }
  return Promise.resolve(null);
};
const ICON = { voice: "mic", f7: "graphic_eq", text: "keyboard", materials: "attach_file", quick: "bolt" };
const SRC_NAME = { voice: "голосом", f7: "звук компьютера", text: "текстом", materials: "материалы", quick: "уточнение" };
const STEP_COLOR = { hear: "var(--teal)", stt: "var(--warn)", think: "var(--info)", answer: "var(--accent2)" };
const STATE_COLOR = { idle: "var(--muted)", loading: "var(--faint)", await: "var(--purple)", followup: "var(--purple)",
                      download: "var(--warn)", error: "var(--err)", think: "var(--info)", answer: "var(--info)", stt: "var(--warn)" };

const st = {
  follow: true, cards: new Map(), lastId: null, hotkeys: {}, mathRender: true, mats: [], busy: false,
  protect: true, panel: null, level: 0, levelTarget: 0, recLevels: [], themes: {}, theme: "", ghost: false,
};

// ======================================================================= Markdown + формулы + код
if (window.marked) marked.setOptions({ gfm: true, breaks: true });

function texHtml(tex, display) {
  if (!st.mathRender || !window.katex) return `<span class="mfall">${esc(tex)}</span>`;
  try { return katex.renderToString(tex, { displayMode: display, throwOnError: true, strict: "ignore", output: "html" }); }
  catch (e) { return `<span class="mfall">${esc(tex)}</span>`; }
}

function codeHtml(c, i) {
  let body = esc(c.body);
  if (window.hljs && c.body.length < 20000) {
    try {
      const lang = (c.lang || "").toLowerCase();
      body = lang && hljs.getLanguage(lang) ? hljs.highlight(c.body, { language: lang, ignoreIllegals: true }).value
                                            : (c.body.length < 4000 ? hljs.highlightAuto(c.body).value : body);
    } catch (e) { /* без подсветки */ }
  }
  return `<div class="codeb"><div class="ch"><span>${esc(c.lang || "код")}</span>` +
         `<button class="cp" data-code="${i}"><span class="ic">content_copy</span>Копировать</button></div>` +
         `<pre><code>${body}</code></pre></div>`;
}

// → {html, codes}
function renderMd(md) {
  const codes = [], inl = [], maths = [];
  let s = String(md || "").replace(/\r\n/g, "\n");
  // 1) блоки кода (в том числе ещё не закрытый — пока ответ печатается)
  s = s.replace(/```([^\n`]*)\n([\s\S]*?)(?:```|$)/g, (m, lang, body) => {
    codes.push({ lang: lang.trim(), body: body.replace(/\n$/, "") });
    return `\n\n@@C${codes.length - 1}@@\n\n`;
  });
  // 2) код в строке
  s = s.replace(/`([^`\n]+)`/g, (m, c) => { inl.push(c); return `@@I${inl.length - 1}@@`; });
  // 3) формулы
  const put = (tex, disp) => { maths.push({ tex: tex.trim(), disp }); return disp ? `\n\n@@D${maths.length - 1}@@\n\n` : `@@M${maths.length - 1}@@`; };
  s = s.replace(/\$\$([\s\S]+?)\$\$/g, (m, t) => put(t, true))
       .replace(/\\\[([\s\S]+?)\\\]/g, (m, t) => put(t, true))
       .replace(/\\\(([\s\S]+?)\\\)/g, (m, t) => put(t, false))
       .replace(/(^|[^\\$\w])\$(?!\s)([^\n$]+?)(?<![\s\\])\$(?![\w$])/g, (m, pre, t) => pre + put(t, false));
  let html = window.marked ? marked.parse(s) : `<p>${esc(s).replace(/\n/g, "<br>")}</p>`;
  html = html.replace(/<p>\s*@@D(\d+)@@\s*<\/p>/g, (m, i) => texHtml(maths[+i].tex, true))
             .replace(/@@D(\d+)@@/g, (m, i) => texHtml(maths[+i].tex, true))
             .replace(/@@M(\d+)@@/g, (m, i) => texHtml(maths[+i].tex, false))
             .replace(/@@I(\d+)@@/g, (m, i) => `<code>${esc(inl[+i])}</code>`)
             .replace(/<p>\s*@@C(\d+)@@\s*<\/p>/g, (m, i) => codeHtml(codes[+i], +i))
             .replace(/@@C(\d+)@@/g, (m, i) => codeHtml(codes[+i], +i));
  return { html, codes: codes.map(c => c.body) };
}

// ответы на F7: «Скажи:» — крупным блоком, «Если спросят подробнее» — мельче
function decorate(el) {
  for (const p of el.querySelectorAll(":scope > p")) {
    const f = p.firstElementChild, txt = p.textContent.trim();
    if (f && f.tagName === "STRONG" && /^скажи:?$/i.test(f.textContent.trim()) && p.firstChild === f) {
      f.remove();
      const d = document.createElement("div"); d.className = "say";
      d.innerHTML = "<small>Скажи</small>" + p.innerHTML.replace(/^\s*:?\s*/, "");
      p.replaceWith(d);
    } else if (/^(\*\*)?если спросят/i.test(txt)) p.classList.add("more");
  }
}

// ======================================================================= лента
const feed = $("feed");
const spacer = document.createElement("div"); spacer.id = "spacer"; feed.appendChild(spacer);

function addSys(text, kind) {
  const d = document.createElement("div");
  d.className = "sys " + (kind || "");
  const icon = kind === "err" ? "error" : kind === "hint" ? "lightbulb" : "info";
  d.innerHTML = `<span class="ic">${icon}</span><span>${esc(text)}</span>`;
  feed.insertBefore(d, spacer);
  fit();
  return d;
}

function nowHM() { const d = new Date(); return d.getHours() + ":" + String(d.getMinutes()).padStart(2, "0"); }

function begin(p) {
  closePanel();
  const c = document.createElement("div");
  c.className = "card";
  const src = p.src || "voice";
  c.innerHTML = `<div class="q"><span class="src ${src}"><span class="ic">${ICON[src] || "chat"}</span></span>` +
    `<div class="qt">${esc(p.question)}<div class="meta">${esc(SRC_NAME[src] || "")} · ${nowHM()}${p.meta ? " · " + esc(p.meta) : ""}</div></div>` +
    (p.thumb ? `<img class="thumb" src="${p.thumb}" alt="" data-shot="${p.id}">` : "") + `</div>` +
    `<div class="a"><div class="skel" style="width:85%"></div><div class="skel" style="width:62%"></div><div class="skel" style="width:74%"></div></div>`;
  feed.insertBefore(c, spacer);
  st.cards.set(p.id, { el: c, md: "", codes: [] });
  st.lastId = p.id;
  st.follow = true;
  fit();
  toLast();
}

function setAnswer(p) {
  const card = st.cards.get(p.id);
  if (!card) return;
  card.md = p.md || "";
  const a = card.el.querySelector(".a");
  const keep = st.follow ? null : feed.scrollTop;
  const r = renderMd(card.md);
  card.codes = r.codes;
  a.innerHTML = r.html + (p.final ? "" : '<span class="caret"></span>');
  if (!p.final) {   // курсор печати — в конец последнего абзаца
    const caret = a.querySelector(":scope > .caret"), last = a.lastElementChild && a.lastElementChild.previousElementSibling;
    if (caret && last && /^(P|LI|UL|OL)$/.test(last.tagName)) {
      const tgt = last.tagName === "P" ? last : last.querySelector("li:last-child") || last;
      tgt.appendChild(caret);
    }
  }
  decorate(a);
  fit();
  if (st.follow) toLast(); else feed.scrollTop = keep;
}

function finish(p) {
  const card = st.cards.get(p.id);
  if (!card) return;
  if (p.md !== undefined) setAnswer({ id: p.id, md: p.md, final: true });
  const a = card.el.querySelector(".a");
  a.querySelectorAll(".caret, .skel").forEach(x => x.remove());
  if (!card.md.trim() && !p.error && !p.note) a.innerHTML = '<p class="note">(пустой ответ)</p>';
  if (p.error) {
    a.insertAdjacentHTML("beforeend", `<div class="errl"><span class="ic">error</span><span>${esc(p.error)}</span></div>` +
      (p.hint ? `<p class="hint">${esc(p.hint)}</p>` : ""));
  }
  if (p.note) a.insertAdjacentHTML("beforeend", `<p class="note">${esc(p.note)}</p>`);
  const acts = document.createElement("div");
  acts.className = "acts";
  if (card.md.trim()) {
    acts.innerHTML = `<button class="chip" data-act="copy"><span class="ic">content_copy</span>Копировать</button>` +
      (p.quick ? ["Короче", "Подробнее", "Объясни проще", "Пример"].map(x => `<button class="chip pri" data-quick="${x}">${x}</button>`).join("") : "");
  }
  if (p.error && p.fix) acts.innerHTML += `<button class="chip pri" data-act="settings"><span class="ic">tune</span>Открыть настройки</button>`;
  if (acts.innerHTML) card.el.appendChild(acts);
  fit();
  if (st.follow) toLast();
}

feed.addEventListener("click", e => {
  const cp = e.target.closest(".cp");
  if (cp) {
    const card = [...st.cards.values()].find(c => c.el.contains(cp));
    if (card) api("copy", card.codes[+cp.dataset.code] || "", "код");
    return;
  }
  const ch = e.target.closest(".chip");
  if (ch) {
    const card = [...st.cards.values()].find(c => c.el.contains(ch));
    if (ch.dataset.act === "copy" && card) api("copy", card.md, "ответ");
    else if (ch.dataset.act === "settings") api("open_settings", "claude");
    else if (ch.dataset.quick) api("quick", ch.dataset.quick);
    return;
  }
  const th = e.target.closest(".thumb");
  if (th) { api("shot_full", +th.dataset.shot).then(url => { if (url) { $("zoomImg").src = url; $("zoom").classList.add("on"); } }); return; }
  const a = e.target.closest("a[href]");
  if (a) { e.preventDefault(); api("open_url", a.getAttribute("href")); }
});
$("zoom").onclick = () => $("zoom").classList.remove("on");
document.addEventListener("click", e => { const a = e.target.closest("a[href]"); if (a && !feed.contains(a)) { e.preventDefault(); api("open_url", a.getAttribute("href")); } }, true);

// новый вопрос встаёт в верх окна, ответ дописывается ниже; пустое место снизу — чтобы было куда подняться
function fit() {
  const last = st.lastId != null && st.cards.get(st.lastId);
  if (!last) { spacer.style.height = "0px"; updDown(); return; }
  const h = feed.clientHeight - last.el.offsetHeight - 24;
  spacer.style.height = Math.max(0, h) + "px";
  updDown();
}
function toLast() {
  const last = st.lastId != null && st.cards.get(st.lastId);
  if (last) feed.scrollTop = last.el.offsetTop - 12;
  updDown();
}
function updDown() {
  const last = st.lastId != null && st.cards.get(st.lastId);
  let need = false;
  if (last && !st.follow) {
    const r = last.el.getBoundingClientRect(), fr = feed.getBoundingClientRect();
    need = r.top > fr.bottom - 40 || r.bottom < fr.top + 10;
  }
  $("down").classList.toggle("on", need);
}
// сам листает — окно больше не прыгает к ответу
feed.addEventListener("wheel", () => { st.follow = false; setTimeout(updDown, 50); }, { passive: true });
feed.addEventListener("pointerdown", e => { if (e.offsetX > feed.clientWidth) st.follow = false; });
feed.addEventListener("keydown", e => { if (/Page|Arrow|Home|End/.test(e.key)) st.follow = false; });
feed.addEventListener("scroll", () => updDown(), { passive: true });
$("down").onclick = () => { st.follow = true; toLast(); };
new ResizeObserver(() => { fit(); if (st.follow) toLast(); }).observe(feed);

// ======================================================================= заголовок, кнопки
const menuEl = $("menu");
function openMenu(anchor, html, up) {
  if (menuEl.classList.contains("on") && menuEl._anchor === anchor) { closeMenu(); return; }
  menuEl.innerHTML = html;
  menuEl._anchor = anchor;
  menuEl.classList.add("on");
  const r = anchor.getBoundingClientRect(), W = innerWidth, H = innerHeight;
  const mw = menuEl.offsetWidth, mh = menuEl.offsetHeight;
  menuEl.style.left = Math.max(8, Math.min(W - mw - 8, r.right - mw > 8 && r.left > W / 2 ? r.right - mw : r.left)) + "px";
  menuEl.style.top = Math.max(8, Math.min(H - mh - 8, up ? r.top - mh - 6 : r.bottom + 6)) + "px";
}
function closeMenu() { menuEl.classList.remove("on"); menuEl._anchor = null; }
document.addEventListener("pointerdown", e => {
  if (!e.target.closest(".menu") && !e.target.closest("#bMat,#bGear,#model")) closeMenu();
  if (st.panel === "info" && !e.target.closest("#panelBody") && !e.target.closest("#bGear")) closePanel();
}, true);
menuEl.addEventListener("click", e => {
  const it = e.target.closest("[data-do]");
  if (!it) return;
  const [fn, arg] = it.dataset.do.split(":");
  if (!it.dataset.keep) closeMenu();
  ACTIONS[fn] && ACTIONS[fn](arg);
});
const ACTIONS = {
  files: () => api("pick_files"), paste: () => api("paste_material"), clearmats: () => api("clear_materials"),
  rmmat: id => api("remove_material", id), settings: tab => api("open_settings", tab || null), info: () => api("toggle_info"),
  help: () => api("open_help"), check: () => showCheck(), wizard: () => api("open_wizard"), history: () => showHistory(),
  font: d => api("font", +d), theme: n => api("set_theme", n), ghost: () => api("set_ghost", !st.ghost),
};

$("bMat").onclick = e => {
  const items = st.mats.map(m => `<div class="it" data-do="rmmat:${m.id}" title="Убрать"><span class="ic">${m.icon}</span><span class="t">${esc(m.title)}</span><span class="r">${esc(m.size)} ✕</span></div>`).join("");
  openMenu(e.currentTarget,
    `<div class="it" data-do="files"><span class="ic">upload_file</span>Прикрепить файлы…<span class="r">PDF, Word, слайды</span></div>` +
    `<div class="it" data-do="paste"><span class="ic">content_paste</span>Текст из буфера<span class="r">Ctrl+V</span></div>` +
    (items ? `<div class="sep"></div><div class="lbl">Материалы · щёлкни, чтобы убрать</div>${items}<div class="sep"></div>` +
             `<div class="it" data-do="clearmats"><span class="ic">delete_sweep</span>Убрать все</div>` :
             `<div class="sep"></div><div class="lbl">Можно и перетащить файл в окно</div>`));
};
$("bHist").onclick = () => showHistory();
$("bNew").onclick = () => api("reset");
$("bGear").onclick = e => {
  const sw = Object.entries(st.themes).map(([k, v]) => `<span data-do="theme:${k}" data-keep="1" title="${esc(v.name)}" class="${k === st.theme ? "on" : ""}" style="background:linear-gradient(135deg, ${v.bg} 50%, ${v.accent} 50%)"></span>`).join("");
  openMenu(e.currentTarget,
    `<div class="it" data-do="settings"><span class="ic">tune</span>Настройки…</div>` +
    `<div class="it" data-do="info"><span class="ic">info</span>Как пользоваться</div>` +
    `<div class="it" data-do="help"><span class="ic">menu_book</span>Вся справка</div>` +
    `<div class="it" data-do="check"><span class="ic">verified_user</span>Проверить невидимость</div>` +
    `<div class="it" data-do="wizard"><span class="ic">build</span>Проверить и починить</div>` +
    `<div class="sep"></div>` +
    `<div class="it" data-do="font:1" data-keep="1"><span class="ic">text_increase</span>Крупнее текст<span class="r">Ctrl +</span></div>` +
    `<div class="it" data-do="font:-1" data-keep="1"><span class="ic">text_decrease</span>Мельче текст<span class="r">Ctrl −</span></div>` +
    `<div class="it" data-do="ghost"><span class="ic">${st.ghost ? "check_box" : "check_box_outline_blank"}</span>Призрачный режим<span class="r">бледнеет без мышки</span></div>` +
    `<div class="sep"></div><div class="lbl">Тема</div><div class="sw">${sw}</div>`);
};
$("model").onclick = e => openMenu(e.currentTarget,
  `<div class="it dis"><span class="ic">smart_toy</span><span class="t">Отвечает: ${esc($("modelTxt").textContent)}</span></div>` +
  `<div class="it" data-do="settings:claude"><span class="ic">swap_horiz</span>Сменить ИИ или модель…</div>`);
$("bCompact").onclick = () => api("toggle_compact");
$("bHide").onclick = () => api("hide");
$("bClose").onclick = () => api("quit");
$("shield").onclick = () => showCheck();
$("bCrop").onclick = () => api("pick_region");
$("shotChip").onclick = () => api("clear_shot");

// перетаскивание окна за заголовок, двойной щелчок — компактно
$("head").addEventListener("pointerdown", e => {
  if (e.button !== 0 || e.target.closest("button, .nodrag")) return;
  api("start_move");
});
$("head").addEventListener("dblclick", e => { if (!e.target.closest("button")) api("toggle_compact"); });
document.querySelectorAll(".rz").forEach(z => z.addEventListener("pointerdown", e => { if (e.button === 0) { e.preventDefault(); api("start_resize", z.dataset.e); } }));

// всплывающие подсказки
let tipT;
document.addEventListener("pointerover", e => {
  const t = e.target.closest("[data-tip]");
  clearTimeout(tipT);
  const tip = $("tip");
  if (!t) { tip.classList.remove("on"); return; }
  tipT = setTimeout(() => {
    tip.textContent = t.dataset.tip;
    const r = t.getBoundingClientRect();
    tip.classList.add("on");
    const w = tip.offsetWidth;
    tip.style.left = Math.max(6, Math.min(innerWidth - w - 6, r.left + r.width / 2 - w / 2)) + "px";
    tip.style.top = (r.bottom + 6 + tip.offsetHeight > innerHeight ? r.top - tip.offsetHeight - 6 : r.bottom + 6) + "px";
  }, 450);
});
document.addEventListener("pointerdown", () => { clearTimeout(tipT); $("tip").classList.remove("on"); });

// ======================================================================= ввод
const inp = $("inp");
inp.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  else if (e.key === "Escape") { inp.value = ""; inp.blur(); }
});
$("send").onclick = submit;
function submit() { const v = inp.value.trim(); if (!v) return; inp.value = ""; api("submit", v); }
document.addEventListener("keydown", e => {
  const inField = e.target === inp || e.target.classList.contains("search");
  if (e.key === "Escape") {
    if ($("zoom").classList.contains("on")) $("zoom").classList.remove("on");
    else if ($("modal").classList.contains("on")) $("modal").classList.remove("on");
    else if (menuEl.classList.contains("on")) closeMenu();
    else if (st.panel) closePanel();
  }
  if (!e.ctrlKey || e.altKey) return;
  if (e.code === "Equal" || e.code === "NumpadAdd") { api("font", 1); e.preventDefault(); }
  else if (e.code === "Minus" || e.code === "NumpadSubtract") { api("font", -1); e.preventDefault(); }
  else if (e.code === "KeyV" && !inField) { api("paste_material"); e.preventDefault(); }   // по коду клавиши — и в русской раскладке
});
document.addEventListener("wheel", e => { if (e.ctrlKey) { api("font", e.deltaY < 0 ? 1 : -1); e.preventDefault(); } }, { passive: false });
// перетащенный текст (файлы ловит сама программа — ей нужны полные пути)
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => {
  e.preventDefault();
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) return;
  const t = e.dataTransfer && e.dataTransfer.getData("text");
  if (t && t.trim()) api("drop_text", t);
});
document.addEventListener("mouseenter", () => document.documentElement.classList.add("hover"));
document.addEventListener("mouseleave", () => document.documentElement.classList.remove("hover"));

// ======================================================================= панели
function openPanel(name, html, full) {
  closeMenu();
  st.panel = name;
  $("panelBody").innerHTML = html;
  $("panel").classList.toggle("full", !!full);
  $("panel").classList.add("on");
}
function closePanel() { st.panel = null; $("panel").classList.remove("on"); }
$("panel").addEventListener("pointerdown", e => { if (e.target === $("panel")) closePanel(); });
const panelHead = (icon, title) => `<div class="ph"><span class="ic">${icon}</span><b>${esc(title)}</b><button class="hb x" onclick="closePanel()"><span class="ic">close</span></button></div>`;

function showInfo(p) {
  if (st.panel === "info") { closePanel(); return; }
  openPanel("info", panelHead("info", "Как пользоваться") +
    `<div class="rows">${p.rows.map(([k, v]) => `<div class="k">${esc(k)}</div><div>${esc(v)}</div>`).join("")}</div>` +
    p.notes.map(n => `<div class="pnote">${esc(n)}</div>`).join("") +
    `<div class="hfoot"><button class="plink" onclick="api('open_help')">Вся справка →</button></div>`);
}
function showHelp(p) {
  openPanel("help", panelHead("menu_book", "Справка") +
    p.sections.map(([t, rows]) => `<div class="hsec">${esc(t)}</div><div class="rows">${rows.map(([k, v]) => `<div class="k">${esc(k)}</div><div>${esc(v)}</div>`).join("")}</div>`).join("") +
    `<div class="pnote">Подробности — в README.md в папке программы.</div>`, true);
}

async function showCheck() {
  openPanel("check", panelHead("verified_user", "Так тебя видят на демонстрации экрана") + `<div class="pnote">Делаю снимок экрана…</div>`, true);
  const r = await api("capture_check");
  if (st.panel !== "check") return;
  if (!r) { $("panelBody").innerHTML = panelHead("verified_user", "Проверка невидимости") + `<div class="badmsg">Не удалось сделать снимок.</div>`; return; }
  const [L, T, R, B] = r.rect;
  $("panelBody").innerHTML = panelHead("verified_user", "Так тебя видят на демонстрации экрана") +
    `<div class="${r.ok ? "okmsg" : "badmsg"}">${esc(r.msg)}</div>` +
    `<div class="ccheck"><img src="${r.img}" alt=""><div class="frame" style="left:${L / r.w * 100}%;top:${T / r.h * 100}%;width:${(R - L) / r.w * 100}%;height:${(B - T) / r.h * 100}%"></div></div>` +
    `<div class="pnote">Защита не спасает от камеры телефона, некоторых программ удалённого доступа (AnyDesk, TeamViewer) и очень старых драйверов захвата.</div>`;
}

let histQ = "", histT;
async function showHistory(q) {
  histQ = q ?? histQ;
  const r = await api("history", histQ);
  const items = (r && r.items) || [];
  openPanel("history", panelHead("history", "История") +
    `<input class="search" id="hq" placeholder="Поиск по вопросам и ответам" value="${esc(histQ)}">` +
    (r && !r.saving ? `<div class="pnote" style="margin:0 0 8px;color:var(--warn)">Сохранение истории выключено (настройки → «Невидимость и система»).</div>` : "") +
    `<div class="hlist">${items.length ? items.map((it, i) => `<div class="hitem" data-i="${i}"><span class="src ${it.kind || "voice"}"><span class="ic">${ICON[it.kind] || "chat"}</span></span>` +
      `<div class="w"><div class="qq">${esc(it.q)}</div><div class="dd">${esc(it.when)}${it.error ? " · ошибка" : ""}</div></div></div>`).join("")
      : `<div class="pnote">${histQ ? "Ничего не нашлось." : "Пока пусто."}</div>`}</div>` +
    `<div class="hfoot"><span class="pnote" style="margin:0;align-self:center">записей: ${items.length}</span><span class="sp" style="flex:1"></span>` +
    `<button class="btn" id="hExp"><span class="ic">download</span>Сохранить в файл…</button><button class="btn danger" id="hClr"><span class="ic">delete</span>Очистить</button></div>`, true);
  const hq = $("hq");
  hq.focus(); hq.setSelectionRange(hq.value.length, hq.value.length);
  hq.oninput = () => { clearTimeout(histT); histT = setTimeout(() => showHistory(hq.value), 250); };
  $("panelBody").querySelectorAll(".hitem").forEach(el => el.onclick = () => showHistItem(items[+el.dataset.i]));
  $("hExp").onclick = () => api("export_history", histQ);
  $("hClr").onclick = () => confirmBox("Удалить всю историю вопросов и ответов? Это нельзя отменить.", async () => { await api("clear_history"); showHistory(""); });
}
function showHistItem(it) {
  const r = renderMd(it.a || "");
  openPanel("history", `<div class="ph"><button class="hb" id="hBack"><span class="ic">arrow_back</span></button><b>${esc(it.when)}</b>` +
    `<span class="pnote" style="margin:0">${esc(SRC_NAME[it.kind] || "")}${it.mode ? " · " + esc(it.mode) : ""}</span>` +
    `<button class="hb x" onclick="closePanel()"><span class="ic">close</span></button></div>` +
    `<div class="hdetail"><div class="qbox">${esc(it.q)}</div><div class="a">${r.html}</div>` +
    (it.error ? `<div class="a"><div class="errl"><span class="ic">error</span>${esc(it.error)}</div></div>` : "") + `</div>` +
    `<div class="hfoot"><button class="btn" id="hCopy"><span class="ic">content_copy</span>Скопировать ответ</button></div>`, true);
  decorate($("panelBody").querySelector(".hdetail .a"));
  $("hBack").onclick = () => showHistory();
  $("hCopy").onclick = () => api("copy", it.a || "", "ответ из истории");
  $("panelBody").querySelectorAll(".cp").forEach(b => b.onclick = () => api("copy", r.codes[+b.dataset.code] || "", "код"));
}

function confirmBox(text, yes) {
  $("modalTxt").textContent = text;
  $("modal").classList.add("on");
  $("modalYes").onclick = () => { $("modal").classList.remove("on"); yes(); };
  $("modalNo").onclick = () => $("modal").classList.remove("on");
}

let toastT;
function toast(icon, text) {
  const t = $("toast");
  t.innerHTML = `<span class="ic">${icon || "check"}</span><span>${esc(text)}</span>`;
  t.classList.add("on");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("on"), 2200);
}

// ======================================================================= живой значок и запись F7
function animate(t) {
  st.level += (st.levelTarget - st.level) * .2;
  const bars = document.querySelectorAll("#logo i");
  bars.forEach((b, i) => {
    const base = [.35, .6, .85, .6, .35][i];
    const wob = st.level > .03 ? Math.abs(Math.sin(t / 90 + i * 1.3)) * st.level : 0;
    b.style.height = (4 + 10 * base + 6 * wob) + "px";
  });
  if ($("rec").classList.contains("on")) drawWave();
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);
function drawWave() {
  const cv = $("wave"), g = cv.getContext("2d"), n = 60;
  const w = cv.width / n, col = getComputedStyle(document.documentElement).getPropertyValue($("rec").classList.contains("tail") ? "--teal" : "--rec");
  g.clearRect(0, 0, cv.width, cv.height);
  g.fillStyle = col;
  const lv = st.recLevels;
  for (let i = 0; i < n; i++) {
    const v = lv[lv.length - n + i] ?? 0;
    const h = Math.max(4, v * cv.height * .95);
    g.globalAlpha = .35 + .65 * (i / n);
    g.beginPath(); g.roundRect(i * w + 2, (cv.height - h) / 2, w - 5, h, 3); g.fill();
  }
  g.globalAlpha = 1;
}

// ======================================================================= события из программы
function setStatus(p) {
  const s = $("steps");
  s.classList.toggle("active", !!p.step);
  const order = ["hear", "stt", "think", "answer"], k = order.indexOf(p.step);
  s.querySelectorAll(".st").forEach((e, i) => {
    e.classList.toggle("on", i === k); e.classList.toggle("done", k > i);
    e.style.color = i === k ? STEP_COLOR[p.step] : "";
  });
  const t = $("statusTxt");
  t.textContent = p.text || "";
  t.style.color = STATE_COLOR[p.state] || "var(--muted)";
  const island = $("islandTxt");
  island.textContent = p.text || "";
  island.style.color = p.step ? STEP_COLOR[p.step] : (STATE_COLOR[p.state] || "var(--muted)");
  st.busy = !!p.step;
  document.documentElement.classList.toggle("busy", st.busy);
  st.levelTarget = p.step === "hear" ? 1 : p.step ? .35 : 0;
}

let heardT;
const H = {
  init(p) {
    st.themes = p.themes || {};
    H.theme(p.theme); H.font(p); H.hotkeys(p.hotkeys); H.mode(p.mode);
    H.prefs(p);
    H.textinput({ on: p.text_input });
    H.compact({ on: p.compact });
    $("title").textContent = p.brand || "Claude Overlay";
    st.inited = true;
  },
  prefs(p) {
    if ("protect" in p) { st.protect = !!p.protect; document.documentElement.classList.toggle("protect", st.protect); }
    if ("math" in p) st.mathRender = !!p.math;
    if ("alpha" in p) document.documentElement.style.setProperty("--alpha", p.alpha);
    if ("ghost" in p) { st.ghost = !!p.ghost; document.documentElement.classList.toggle("ghost", st.ghost); }
    if ("ghost_fade" in p) {
      document.documentElement.style.setProperty("--ghost", Math.max(.05, 1 - p.ghost_fade));
      if (st.inited) {       // двигают ползунок в настройках — показываем, как будет выглядеть
        document.documentElement.classList.add("ghostpreview");
        clearTimeout(st.ghostT);
        st.ghostT = setTimeout(() => document.documentElement.classList.remove("ghostpreview"), 1500);
      }
    }
    if ("glass" in p) document.documentElement.classList.toggle("glass", !!p.glass);
  },
  theme(p) {
    for (const [k, v] of Object.entries(p.vars || {})) document.documentElement.style.setProperty("--" + k, v);
    st.theme = p.name || st.theme;
    document.querySelectorAll(".sw span").forEach(s => s.classList.toggle("on", s.dataset.do === "theme:" + st.theme));
  },
  font(p) { document.documentElement.style.setProperty("--fs", p.fs + "px"); fit(); },
  hotkeys(p) {
    st.hotkeys = p || {};
    const k = st.hotkeys;
    $("foot").innerHTML = [[k.listen, "звук лекции"], [k.talk, "без «Клод»"], [k.toggle, "спрятать"], [k.region, "кусок экрана"]]
      .filter(x => x[0]).map(([key, t]) => `<span class="k"><span class="kbd">${esc(key)}</span>${t}</span>`).join("");
    inp.placeholder = `Спроси текстом… или скажи «Клод, …»`;
    $("bCrop").dataset.tip = `Выделить кусок экрана (${k.region || ""})`;
    $("bHide").dataset.tip = `Спрятать (${k.toggle || ""})`;
  },
  mode(p) { $("modelTxt").textContent = p.name || "не настроено"; $("model").classList.toggle("bad", !p.ok); },
  status: setStatus,
  heard(p) {
    const h = $("heard");
    h.textContent = p.text || "";
    h.className = p.text ? "on" + (p.kind === "notme" ? " notme" : "") : "";
    clearTimeout(heardT);
    if (p.text && !p.sticky) heardT = setTimeout(() => h.classList.remove("on"), 7000);
    setTimeout(fit, 300);
  },
  begin, answer: setAnswer, finish,
  sys(p) { addSys(p.text, p.kind); if (st.follow && st.lastId == null) feed.scrollTop = feed.scrollHeight; },
  clear() {
    st.cards.clear(); st.lastId = null; st.follow = true;
    feed.querySelectorAll(".card, .sys").forEach(x => x.remove());
    fit();
  },
  rec(p) {
    const r = $("rec");
    r.classList.toggle("on", !!p.on);
    r.classList.toggle("tail", !!p.tail);
    if (!p.on) { st.recLevels = []; return; }
    $("recT").textContent = p.time || "";
    $("recHint").innerHTML = p.tail ? "дослушиваю секунду…" : `<span class="kbd">${esc(st.hotkeys.listen || "F7")}</span> готово · <span class="kbd">Esc</span> отмена`;
    st.recLevels.push(Math.max(0, Math.min(1, p.level || 0)));
    if (st.recLevels.length > 200) st.recLevels.splice(0, st.recLevels.length - 200);
  },
  mic(p) { if (!st.busy) st.levelTarget = p.on ? .8 : 0; },
  mats(p) {
    st.mats = p.items || [];
    const n = st.mats.length;
    $("matCount").textContent = n;
    $("matCount").classList.toggle("on", n > 0);
    $("bMat").classList.toggle("on", n > 0);
    const box = $("mats");
    box.classList.toggle("on", n > 0 && !p.hide_bar);
    box.innerHTML = st.mats.map(m => `<span class="chip" title="${esc(m.title)} · ${esc(m.size)}"><span class="ic">${m.icon}</span><span class="t">${esc(m.title)}</span>` +
      `<span class="ic x" data-rm="${m.id}">close</span></span>`).join("") + (p.cut ? `<span class="chip" style="color:var(--warn)">часть обрезана — слишком много</span>` : "");
    box.querySelectorAll("[data-rm]").forEach(x => x.onclick = () => api("remove_material", x.dataset.rm));
    fit();
  },
  shot(p) {
    const c = $("shotChip");
    c.classList.toggle("on", !!p);
    c.innerHTML = p ? `<span class="ic">screenshot_region</span>${p.w}×${p.h}<span class="ic">close</span>` : "";
  },
  shield(p) {
    const s = $("shield");
    s.className = "nodrag " + p.level;
    $("shieldTxt").textContent = { ok: "Невидим", partial: "Видна рамка", off: "Видно на демонстрации", fail: "Видно на демонстрации" }[p.level] || "?";
    s.dataset.tip = p.text + " — щёлкни, чтобы проверить";
  },
  compact(p) {
    document.documentElement.classList.toggle("island", !!p.on);
    $("icCompact").textContent = p.on ? "open_in_full" : "close_fullscreen";
    if (!p.on) setTimeout(() => { fit(); if (st.follow) toLast(); }, 60);
  },
  textinput(p) { $("ask").classList.toggle("off", !p.on); },
  focus() { closePanel(); inp.focus(); },
  scroll(p) {
    if (p.dir === "last") { st.follow = true; toLast(); return; }
    st.follow = false;
    feed.scrollBy({ top: (p.dir === "up" ? -1 : 1) * feed.clientHeight * .6, behavior: "smooth" });
  },
  toast(p) { toast(p.icon, p.text); },
  info: showInfo, help: showHelp,
  history() { showHistory(""); },
  check() { showCheck(); },
  close_panels() { closePanel(); closeMenu(); },
};

window.ui = {
  recv(batch) {
    for (const [name, p] of batch) {
      try { H[name] && H[name](p || {}); }
      catch (e) { console.error(name, e); api("log", `${name}: ${e && e.stack || e}`); }
    }
  },
};
window.addEventListener("error", e => { if (!/ResizeObserver/.test(e.message)) api("log", String(e.message) + " @" + e.lineno); });
window.addEventListener("pywebviewready", () => api("ready"));
if (window.pywebview && window.pywebview.api && window.pywebview.api.ready) api("ready");
