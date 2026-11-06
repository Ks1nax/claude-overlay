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
        ("Ctrl+V в окне", "текст из буфера — в материалы"),
    ]),
    ("Кнопки вверху окна", [
        ("📎", "прикрепить файлы: PDF, Word, PowerPoint, текст, картинки (или перетащи файл в окно)"),
        ("📋", "текст из буфера обмена — в материалы"),
        ("⟲", "новая задача: очистить диалог"),
        ("⚙", "настройки: модели распознавания, звук, Claude, клавиши, вид, невидимость"),
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
