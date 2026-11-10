# -*- coding: utf-8 -*-
"""Небольшие окна: проверка невидимости, справка, просмотр текста. Все защищены от захвата экрана."""

import tkinter as tk

from .config import S
from .hotkeys import display as key_display
from . import winsys
from .ui_theme import T, F, MONO, IS_WIN, Button, RoundIconButton, ThinScroll, label, text_cursor

HEAD_H = 44


def make_dialog(app, title, tool=True, size=None, parent=None):
    """Окно без рамки Windows, как главное: свой заголовок (перетаскивание, крестик), скруглённые углы,
    размер — за правый нижний уголок. Нет кнопки на панели задач и в Alt+Tab, невидимо на демонстрации."""
    top = tk.Toplevel(parent or app.root)
    top.withdraw()
    top.title(title)
    top.configure(bg=T["BG"])
    if IS_WIN:
        top.attributes("-toolwindow", True)    # ДО overrideredirect (иначе Tk сбросит признак окна-инструмента)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    if size:
        top.geometry(size)
    head = tk.Frame(top, bg=T["BG2"], height=HEAD_H)
    head.pack(fill="x", side="top")
    head.pack_propagate(False)
    name = tk.Label(head, text=title, bg=T["BG2"], fg=T["MUTED"], font=F(-1), anchor="w")
    name.pack(side="left", padx=(16, 8), fill="x", expand=True)
    RoundIconButton(head, "close", lambda: _close(top), "Закрыть (Esc)", danger=True).pack(side="right", padx=8)
    tk.Frame(top, bg=T["BORDER"], height=1).pack(fill="x", side="top")
    for w in (head, name):
        w.bind("<ButtonPress-1>", lambda e: _grab(top, e, "move"))
        w.bind("<B1-Motion>", lambda e: _drag(top, e))
    grip = tk.Label(top, text="◢", bg=T["BG"], fg=T["FAINT"], font=F(-3))
    grip.place(relx=1.0, rely=1.0, x=-3, y=-1, anchor="se")
    grip.bind("<ButtonPress-1>", lambda e: _grab(top, e, "size"))
    grip.bind("<B1-Motion>", lambda e: _drag(top, e))
    top._grip = grip
    # окно без рамки само клавиатуру не получает — забираем её при щелчке (поля ввода в настройках)
    top.bind("<ButtonPress-1>", lambda e: _activate(top), add="+")
    top.update_idletasks()
    app.guard.protect_tk(top, tool=True)
    return top


def _close(top):
    """Крестик — как закрытие окна Windows: обработчик WM_DELETE_WINDOW, если он задан, иначе просто закрыть."""
    try:
        cmd = top.protocol("WM_DELETE_WINDOW")
        if cmd:
            top.tk.call(cmd)
        else:
            top.destroy()
    except tk.TclError:
        pass


def _activate(top):
    try:
        if IS_WIN and top.winfo_exists():
            winsys.force_foreground(winsys.tk_hwnd(top))
    except tk.TclError:
        pass


def _grab(top, e, kind):
    top._drag = (kind, e.x_root, e.y_root, top.winfo_x(), top.winfo_y(), top.winfo_width(), top.winfo_height())


def _drag(top, e):
    kind, x0, y0, wx, wy, ww, wh = getattr(top, "_drag", ("move", e.x_root, e.y_root, 0, 0, 0, 0))
    dx, dy = e.x_root - x0, e.y_root - y0
    if kind == "move":
        top.geometry(f"+{wx + dx}+{wy + dy}")
    else:
        mw, mh = top.minsize()
        top.geometry(f"{max(mw or 300, ww + dx)}x{max(mh or 200, wh + dy)}")


def show_dialog(app, top, center=True):
    top.update_idletasks()
    if center:
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        w, h = top.winfo_width() if top.winfo_width() > 50 else top.winfo_reqwidth(), \
            top.winfo_height() if top.winfo_height() > 50 else top.winfo_reqheight()
        top.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
    app.guard.protect_tk(top, tool=True)
    top.deiconify()
    app.guard.protect_tk(top, tool=True)
    winsys.style_frame(winsys.tk_hwnd(top), T["BORDER"])     # скруглённые углы Windows 11 и тонкая рамка
    top.lift()
    if getattr(top, "_grip", None) is not None:
        top._grip.lift()
    top.focus_force()
    _activate(top)


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
        ("{region} или рамка слева в поле вопроса", "выделить мышкой кусок экрана — он приложится к следующему вопросу вместо всего экрана"),
        ("{type}", "написать вопрос текстом: курсор встанет в поле внизу окна; Enter — отправить"),
        ("Ctrl+V в окне", "текст из буфера — в материалы"),
        ("Ctrl + колёсико, Ctrl+плюс/минус", "крупнее / мельче текст"),
    ]),
    ("Кнопки вверху окна", [
        ("Модель (рядом с названием)", "кто отвечает; щёлкни — сменить ИИ или модель"),
        ("Скрепка", "материалы: прикрепить файлы (PDF, Word, PowerPoint, текст, картинки), текст из буфера, "
                    "убрать; файл можно и просто перетащить в окно"),
        ("Часы", "история: все прошлые вопросы и ответы, поиск, сохранить в файл"),
        ("Облачко с плюсом", "новая задача: очистить диалог"),
        ("Шестерёнка", "настройки, подсказки, справка, проверка невидимости, размер текста, тема, призрачный режим"),
        ("Стрелки внутрь", "компактный режим: только полоска со статусом, при ответе окно разворачивается"),
        ("Минус", "спрятать окно"),
        ("Двойной щелчок по заголовку", "тоже компактный режим; за заголовок окно перетаскивается, за края — "
                                        "меняется размер"),
    ]),
    ("Под ответом", [
        ("Копировать", "весь ответ в буфер обмена (у каждого блока кода — своя кнопка)"),
        ("Короче · Подробнее · Объясни проще · Пример", "уточнить ответ одной кнопкой — в том же диалоге"),
        ("Миниатюра справа от вопроса", "что увидел Claude; щёлкни — крупно"),
    ]),
    ("Невидимость", [
        ("Щит «Невидим» вверху", "окна оверлея не видно на демонстрации экрана и скриншотах; щёлкни — покажу "
                                 "снимок, каким его видит собеседник"),
        ("Призрачный режим", "окно бледнеет, когда мышка не над ним (шестерёнка → «Призрачный режим»)"),
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
