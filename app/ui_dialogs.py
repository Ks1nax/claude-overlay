# -*- coding: utf-8 -*-
"""Небольшие окна: проверка невидимости, справка, просмотр текста. Все защищены от захвата экрана."""

import tkinter as tk

from .config import S
from .hotkeys import display as key_display
from .ui_theme import T, F, MONO, IS_WIN, Button, ThinScroll, label, dark_title_bar, text_cursor


def make_dialog(app, title, tool=True, size=None, parent=None):
    """Обычное окно Windows с тёмным заголовком. tool=True — без кнопки на панели задач."""
    top = tk.Toplevel(parent or app.root)
    top.withdraw()
    top.title(title)
    top.configure(bg=T["BG"])
    if IS_WIN and tool:
        top.attributes("-toolwindow", True)
    top.attributes("-topmost", True)
    try:
        from .config import ICON_PATH
        top.iconbitmap(ICON_PATH)
    except Exception:
        pass
    if size:
        top.geometry(size)
    top.update_idletasks()
    app.guard.protect_tk(top, tool=tool)
    return top


def show_dialog(app, top, center=True):
    top.update_idletasks()
    if center:
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        w, h = top.winfo_width() if top.winfo_width() > 50 else top.winfo_reqwidth(), \
            top.winfo_height() if top.winfo_height() > 50 else top.winfo_reqheight()
        top.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
    dark_title_bar(top)
    app.guard.protect_tk(top, tool=False)
    top.deiconify()
    app.guard.protect_tk(top, tool=False)
    top.lift()
    top.focus_force()


def show_capture_check(app, parent=None):
    """«Проверить невидимость»: снимок экрана тем же способом, что у программ демонстрации (снимается ДО открытия
    этого окна), — что видит собеседник. Оранжевая рамка — где на самом деле стоит окно оверлея."""
    from PIL import ImageDraw, ImageTk, Image
    try:
        shot, rect, ok, msg = app.capture_check()
    except Exception as e:
        app._write([(f"\nНе удалось сделать снимок для проверки: {e}\n", ("err",))])
        return
    img = shot.copy()
    scale = min(900 / img.width, 520 / img.height, 1.0)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    L, Tp, R, B = [int(v * scale) for v in rect]
    for i in range(3):
        d.rectangle((L - i, Tp - i, R + i, B + i), outline=T["ACCENT"])
    top = make_dialog(app, "Проверка невидимости", parent=parent)
    top.configure(bg=T["BG2"])
    label(top, "Так тебя видят на демонстрации экрана", size=2, bold=True).pack(anchor="w", padx=16, pady=(14, 2))
    label(top, msg, color=T["OK"] if ok else T["ERR"], wrap=img.width).pack(anchor="w", padx=16, pady=(0, 10))
    photo = ImageTk.PhotoImage(img)
    pic = tk.Label(top, image=photo, bg=T["BG2"], bd=0)
    pic.image = photo
    pic.pack(padx=16)
    label(top, "Защита не спасает от камеры телефона, некоторых программ удалённого доступа (AnyDesk, TeamViewer) и "
               "очень старых драйверов захвата.", muted=True, size=-2, wrap=img.width).pack(anchor="w", padx=16,
                                                                                           pady=(8, 0))
    Button(top, "Закрыть", top.destroy, kind="primary").pack(pady=12)
    top.bind("<Escape>", lambda e: top.destroy())
    show_dialog(app, top)


def show_text(app, title, text, parent=None):
    top = make_dialog(app, title, size="760x560", parent=parent)
    frame = tk.Frame(top, bg=T["BG"])
    frame.pack(fill="both", expand=True)
    t = tk.Text(frame, wrap="word", bg=T["BG"], fg=T["FG"], bd=0, highlightthickness=0, padx=14, pady=10,
                font=MONO(0), cursor=text_cursor(), selectbackground=T["SEL"], selectforeground=T["FG"])
    sb = ThinScroll(frame, t)
    t.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    t.insert("1.0", text)
    t.config(state="disabled")
    top.bind("<Escape>", lambda e: top.destroy())
    show_dialog(app, top)
    return top


HELP = [
    ("Голосом (микрофон)", [
        ("«Клод, реши задачу на экране»", "скриншот экрана под курсором + ответ"),
        ("«Клод, добавь, что без циклов»", "дополнение к той же задаче — диалог продолжается"),
        ("сразу после ответа", "{followup} с можно дополнять без слова «Клод»"),
        ("«Клод» … пауза … вопрос", "тоже работает"),
        ("«Клод, следующее задание»", "новый скриншот, прошлые условия помнит"),
        ("«Клод, новая задача, …»", "очистить диалог и начать заново"),
        ("«Клод, без экрана, …»", "вопрос без скриншота"),
        ("«Клод, стоп»", "прервать ответ"),
        ("«Клод, вниз» / «вверх»", "прокрутка"),
        ("«Клод, скопируй код» / «скопируй»", "в буфер обмена"),
        ("«Клод, скрой» / «покажи»", "спрятать / показать окно"),
        ("«Клод, возьми текст из буфера»", "добавить текст из буфера в материалы"),
        ("«Клод, убери материалы»", "убрать все материалы"),
    ]),
    ("Клавиши", [
        ("{listen}", "вопрос со звука компьютера: нажать в начале вопроса и ещё раз в конце "
                     "(в запись попадают и {pre} с до нажатия)"),
        ("Esc во время записи", "отменить запись"),
        ("{talk}", "следующая фраза — команда без «Клод»"),
        ("{toggle}", "спрятать / показать окно"),
        ("{region} или ✂ внизу окна", "выделить мышкой кусок экрана — он приложится к следующему вопросу вместо всего экрана"),
        ("{type}", "написать вопрос текстом: курсор встанет в поле внизу окна; Enter — отправить"),
        ("Ctrl+V в окне", "текст из буфера — в материалы"),
    ]),
    ("Кнопки вверху окна", [
        ("📎", "прикрепить файлы: PDF, Word, PowerPoint, текст, картинки (или перетащи файл в окно)"),
        ("📋", "текст из буфера обмена — в материалы"),
        ("⟲", "новая задача: очистить диалог"),
        ("🕘", "история: все прошлые вопросы и ответы, поиск, сохранить в файл"),
        ("⚙", "настройки: модели распознавания, звук, подключение к ИИ, клавиши, вид, невидимость"),
        ("ⓘ", "короткие подсказки — эта справка открывается оттуда"),
        ("▭", "компактный режим: только строка состояния, при ответе окно разворачивается"),
        ("—", "спрятать окно"),
    ]),
    ("Невидимость", [
        ("🛡 внизу окна", "окна оверлея не видно на демонстрации экрана и скриншотах; щёлкни — покажу снимок, "
                         "каким его видит собеседник"),
    ]),
]


def show_help(app):
    if app.help_win is not None:
        try:
            app.help_win.lift()
            app.help_win.focus_force()
            return
        except tk.TclError:
            app.help_win = None
    top = make_dialog(app, "Справка — Claude Overlay", size="720x640")
    app.help_win = top
    top.bind("<Destroy>", lambda e: setattr(app, "help_win", None) if e.widget is top else None)
    frame = tk.Frame(top, bg=T["BG"])
    frame.pack(fill="both", expand=True)
    t = tk.Text(frame, wrap="word", bg=T["BG"], fg=T["FG"], bd=0, highlightthickness=0, padx=18, pady=12,
                font=F(0), cursor=text_cursor(), spacing1=2, spacing3=2)
    sb = ThinScroll(frame, t)
    t.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    t.tag_configure("h", font=F(2, "bold"), foreground=T["ACCENT"], spacing1=12, spacing3=4)
    t.tag_configure("k", font=F(0, "bold"), lmargin1=6)
    t.tag_configure("d", foreground=T["MUTED"], lmargin1=30, lmargin2=30, spacing3=6)
    keys = {"listen": key_display(S.hotkey_listen), "talk": key_display(S.hotkey_talk),
            "toggle": key_display(S.hotkey_toggle), "followup": S.followup_seconds,
            "region": key_display(S.hotkey_region), "type": key_display(S.hotkey_type),
            "pre": f"{S.listen_pre_seconds:g}"}
    for title, items in HELP:
        t.insert("end", title + "\n", ("h",))
        for k, d in items:
            t.insert("end", k.format(**keys) + "\n", ("k",))
            t.insert("end", d.format(**keys) + "\n", ("d",))
    t.insert("end", "\nПодробности — в README.md в папке программы.\n", ("d",))
    t.config(state="disabled")
    top.bind("<Escape>", lambda e: top.destroy())
    show_dialog(app, top)


def show_history(app):
    """История вопросов и ответов между запусками: поиск, просмотр, копирование, выгрузка в файл."""
    from tkinter import filedialog, messagebox
    from . import history
    from .config import S
    from .textfmt import md_segments, MATH, CODE, tex_to_text
    if getattr(app, "history_win", None) is not None:
        try:
            app.history_win.deiconify()
            app.history_win.lift()
            return
        except tk.TclError:
            pass
    top = make_dialog(app, "История — Claude Overlay", size="1000x640")
    app.history_win = top
    top.bind("<Destroy>", lambda e: setattr(app, "history_win", None) if e.widget is top else None)
    bar = tk.Frame(top, bg=T["BG2"])
    bar.pack(fill="x")
    label(bar, "История", size=3, bold=True).pack(side="left", padx=(16, 12), pady=10)
    q = tk.Entry(bar, bg=T["BG3"], fg=T["FG"], insertbackground=T["FG"], relief="flat", font=F(0), width=34,
                 highlightthickness=1, highlightbackground=T["BORDER"], highlightcolor=T["ACCENT"])
    q.pack(side="left", ipady=4)
    label(bar, "  поиск по вопросам и ответам", muted=True, size=-1).pack(side="left")
    count = label(bar, "", muted=True, size=-1)
    count.pack(side="right", padx=16)
    if not S.history_save:
        label(top, "Сохранение истории выключено (⚙ → «Невидимость и система»). Здесь — то, что было раньше.",
              color=T["WARN"], size=-1).pack(fill="x", padx=16, pady=(6, 0))
    body = tk.Frame(top, bg=T["BG"])
    body.pack(fill="both", expand=True)
    left = tk.Frame(body, bg=T["BG2"], width=330)
    left.pack(side="left", fill="y")
    left.pack_propagate(False)
    lb = tk.Listbox(left, bg=T["BG2"], fg=T["FG"], selectbackground=T["ACCENT"], selectforeground="#ffffff",
                    relief="flat", bd=0, highlightthickness=0, font=F(-1), activestyle="none")
    sb = ThinScroll(left, lb)
    lb.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    lb.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
    right = tk.Frame(body, bg=T["BG"])
    right.pack(side="left", fill="both", expand=True)
    t = tk.Text(right, wrap="word", bg=T["BG"], fg=T["FG"], bd=0, highlightthickness=0, padx=18, pady=12,
                font=F(0), cursor=text_cursor(), spacing1=2, spacing2=2, spacing3=3, height=1,
                selectbackground=T["SEL"], selectforeground=T["FG"])
    tsb = ThinScroll(right, t)
    t.configure(yscrollcommand=tsb.set)
    tsb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    t.tag_configure("meta", foreground=T["MUTED"], font=F(-2))
    t.tag_configure("q", foreground=T["ACCENT"], background=T["Q_BG"], font=F(0, "bold"), spacing1=6, spacing3=6,
                    lmargin1=8, lmargin2=8)
    t.tag_configure("b", font=F(0, "bold"))
    t.tag_configure("h", font=F(1, "bold"))
    t.tag_configure("ic", font=MONO(-1), background=T["CODE_BG"], foreground=T["IC_FG"])
    t.tag_configure("code", font=MONO(-1), background=T["CODE_BG"], foreground=T["CODE_FG"], lmargin1=10,
                    lmargin2=10)
    t.tag_configure("err", foreground=T["ERR"])
    t.tag_configure("mf", font=(F()[0], S.font_size + 1, "italic"))
    foot = tk.Frame(top, bg=T["BG2"])
    foot.pack(fill="x")
    state = {"items": [], "cur": None}

    def show(rec):
        state["cur"] = rec
        t.config(state="normal")
        t.delete("1.0", "end")
        from .history import KIND_NAMES
        t.insert("end", f"{rec.get('t', '')} · {KIND_NAMES.get(rec.get('kind'), '')} · {rec.get('mode', '')}\n",
                 ("meta",))
        t.insert("end", rec.get("q", "") + "\n", ("q",))
        t.insert("end", "\n")
        for s, tags in md_segments(rec.get("a", "")):
            if s == MATH:
                t.insert("end", tex_to_text(tags[0]) + ("\n" if tags[1] else ""), ("mf",))
            elif s != CODE:
                t.insert("end", s, tags)
        if rec.get("error"):
            t.insert("end", "\nОшибка: " + rec["error"] + "\n", ("err",))
        t.config(state="disabled")

    def refresh(_e=None):
        recs = history.load(q.get())
        state["items"] = recs
        lb.delete(0, "end")
        for r in recs:
            icon = history.KIND_ICONS.get(r.get("kind"), "•")
            when = r.get("t", "")[5:16].replace("-", ".")
            lb.insert("end", f" {when}  {icon} {r.get('q', '')[:60]}")
        count.config(text=f"записей: {len(recs)}")
        if recs:
            lb.selection_set(0)
            show(recs[0])
        else:
            t.config(state="normal")
            t.delete("1.0", "end")
            t.insert("end", "Пока пусто." if not q.get() else "Ничего не нашлось.", ("meta",))
            t.config(state="disabled")

    def on_select(_e=None):
        sel = lb.curselection()
        if sel and sel[0] < len(state["items"]):
            show(state["items"][sel[0]])

    def copy_answer():
        if state["cur"]:
            app._copy_text(state["cur"].get("a", ""), "ответ из истории")

    def export():
        recs = state["items"]
        if not recs:
            return
        path = filedialog.asksaveasfilename(parent=top, title="Сохранить историю", defaultextension=".md",
                                            initialfile="История Claude Overlay.md",
                                            filetypes=[("Текст с разметкой", "*.md"), ("Текст", "*.txt")])
        if path:
            history.export_markdown(recs, path)
            messagebox.showinfo("История", f"Сохранено записей: {len(recs)}\n{path}", parent=top)

    def clear_all():
        if messagebox.askyesno("История", "Удалить всю историю вопросов и ответов? Это нельзя отменить.",
                               parent=top):
            history.clear()
            refresh()

    lb.bind("<<ListboxSelect>>", on_select)
    q.bind("<KeyRelease>", refresh)
    Button(foot, "Скопировать ответ", copy_answer, small=True, icon="copy").pack(side="left", padx=(16, 6), pady=10)
    Button(foot, "Сохранить в файл…", export, small=True).pack(side="left")
    Button(foot, "Очистить всё", clear_all, small=True, kind="danger").pack(side="right", padx=16)
    top.bind("<Escape>", lambda e: top.destroy())
    refresh()
    show_dialog(app, top)
