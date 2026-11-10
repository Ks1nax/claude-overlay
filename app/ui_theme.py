# -*- coding: utf-8 -*-
"""Оформление: цвета тем, шрифты, значки и общие элементы окон (кнопки, переключатели, ползунки, тонкая полоса
прокрутки, индикаторы). Всё на обычном Tk — без лишних библиотек."""

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .config import S

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Цвета тем. Внутри темы все значения разные (по ним при смене темы перекрашиваются окна), чистые #ffffff и
# #000000 не используются — ими рисуются надписи на акцентных кнопках.
_K = ("BG", "BG2", "BG3", "BG4", "FG", "MUTED", "FAINT", "ACCENT", "ACCENT2", "CODE_BG", "CODE_FG", "IC_FG", "ERR",
      "OK", "WARN", "INFO", "BORDER", "SEL", "PURPLE", "TEAL", "REC", "Q_BG")


def _theme(dark, *colors):
    t = dict(zip(_K, colors))
    t["DARK_TITLE"] = dark
    return t


THEMES = {
    "dark": _theme(1, "#17181c", "#1e2026", "#26282f", "#31343c", "#eceef2", "#9b9fa9", "#646872", "#e07a5a",
                   "#ec8e70", "#111216", "#cdd6e4", "#f0c27a", "#ff7070", "#4fcb8f", "#e8b85c", "#6cb2ff",
                   "#2c2e36", "#3a3e4a", "#b896ff", "#5cc3cf", "#ef6f7b", "#22242b"),
    "midnight": _theme(1, "#0e1320", "#141a2a", "#1b2337", "#243048", "#e6ebf6", "#8e9ab4", "#586581", "#7aa2f7",
                       "#93b4fa", "#0a0e18", "#c6d2ea", "#f2c97d", "#f7768e", "#73daca", "#e0af68", "#7dcfff",
                       "#1f2740", "#2d3a5c", "#bb9af7", "#2ac3de", "#ff7a93", "#172036"),
    "black": _theme(1, "#030303", "#0d0d0f", "#18191c", "#222428", "#f0f0f0", "#8d9098", "#55585f", "#e07a5b",
                    "#ec8e71", "#0a0a0c", "#cfd6e2", "#f0c27b", "#ff7171", "#50cc90", "#e9b95d", "#6db3ff",
                    "#1c1d21", "#33363e", "#b997ff", "#5dc4d0", "#f0707c", "#121315"),
    "warm": _theme(1, "#1c1814", "#241f1a", "#2d2620", "#3a3129", "#f1e9df", "#a89a8a", "#6e6357", "#e8a253",
                   "#f2b56d", "#15120e", "#e2d6c6", "#f4cf86", "#f2766b", "#8cc98a", "#e9be62", "#7fb8e6",
                   "#322a23", "#4a3d31", "#c9a0e8", "#6fc2b4", "#ee7a6e", "#29231d"),
    "light": _theme(0, "#fafaf8", "#f0efeb", "#fefefe", "#e4e3de", "#1c1d21", "#62666f", "#9b9ea6", "#c95f3d",
                    "#b3502f", "#f2f2ef", "#24292f", "#9a5a00", "#d03434", "#1c8a57", "#a56a00", "#1f6bd0",
                    "#dcdbd5", "#cfe0fd", "#7a4bcb", "#17899a", "#cd3a4b", "#f4efe9"),
    "paper": _theme(0, "#f6f0e4", "#ece4d4", "#fbf7ef", "#e0d6c2", "#2b2419", "#6f6453", "#a69a85", "#b4562e",
                    "#9c4724", "#efe7d6", "#2e2a22", "#8a5200", "#c0392b", "#2d7d46", "#9a6400", "#2b63b5",
                    "#d9cdb6", "#e3d3b1", "#74479e", "#1d7f85", "#c23a3a", "#efe5d2"),
}
THEME_NAMES = {"dark": "Графит (тёмная)", "midnight": "Полночь (тёмно-синяя)", "black": "Чёрная (для OLED)",
               "warm": "Тёплая (тёмная, какао)", "light": "Светлая", "paper": "Бумага (светлая, тёплая)"}

T = dict(THEMES.get(S.theme, THEMES["dark"]))   # словарь меняется на месте при смене темы (apply_theme)
UI_FONT = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
MONO_FONT = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")
ICON_FONT = None

# Значки Segoe Fluent Icons / Segoe MDL2 Assets; запасной вариант — обычные символы
GLYPHS = {
    "settings": ("", "⚙"), "attach": ("", "📎"), "paste": ("", "📋"), "new": ("", "⟲"),
    "hide": ("", "—"), "close": ("", "✕"), "help": ("", "?"), "info": ("", "ⓘ"), "compact": ("", "▭"),
    "expand": ("", "▢"), "copy": ("", "⧉"), "down": ("", "↓"), "shield": ("", "🛡"),
    "mic": ("", "🎙"), "check": ("", "✓"), "warn": ("", "⚠"), "play": ("", "▶"),
    "delete": ("", "🗑"), "download": ("", "⬇"), "folder": ("", "📁"), "history": ("", "🕘"), "crop": ("", "✂"), "send": ("", "➤"), "eye": ("", "👁"),
}

GLYPHS["chev"] = ("\ue70d", "▾")
GLYPHS.update(volume=("\ue767", "V"), chat=("\ue8f2", "C"), keyboard=("\ue765", "K"), palette=("\ue790", "P"))

STATE_KEYS = {"loading": "MUTED", "idle": "OK", "await": "PURPLE", "followup": "PURPLE", "stt": "WARN",
              "think": "INFO", "answer": "INFO", "error": "ERR", "listen": "TEAL", "rec": "REC",
              "download": "WARN"}


def state_color(state):
    return T[STATE_KEYS.get(state, "MUTED")]


def hand():
    """Курсор «рука» выдал бы невидимое окно на демонстрации — при включённой невидимости везде стрелка."""
    return "arrow" if (IS_WIN and S.protect) else "hand2"


def text_cursor():
    return "arrow" if (IS_WIN and S.protect) else "xterm"


def F(delta=0, weight="normal", size=None):
    return (UI_FONT, (size or S.font_size) + delta, weight)


def MONO(delta=-1):
    return (MONO_FONT, S.font_size + delta)


def init_fonts(root):
    """Вызывается один раз после создания Tk: выбирает шрифт значков и настраивает ttk."""
    global ICON_FONT, UI_FONT
    fams = set(tkfont.families(root))
    for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if f in fams:
            ICON_FONT = f
            break
    if IS_WIN and "Segoe UI Variable Text" in fams:
        UI_FONT = "Segoe UI Variable Text"
    setup_ttk(root)


def glyph(name):
    """→ (текст, шрифт) для значка."""
    g, fb = GLYPHS[name]
    if ICON_FONT:
        return g, (ICON_FONT, S.font_size)
    return fb, F(1)


def setup_ttk(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("TCombobox", fieldbackground=T["BG3"], background=T["BG3"], foreground=T["FG"],
                 arrowcolor=T["MUTED"], bordercolor=T["BORDER"], lightcolor=T["BG3"], darkcolor=T["BG3"],
                 selectbackground=T["BG3"], selectforeground=T["FG"], padding=4, insertcolor=T["FG"])
    st.map("TCombobox", fieldbackground=[("readonly", T["BG3"]), ("disabled", T["BG2"])],
           foreground=[("disabled", T["FAINT"])], background=[("active", T["BG4"])],
           bordercolor=[("focus", T["ACCENT"])], arrowcolor=[("active", T["FG"])])
    root.option_add("*TCombobox*Listbox.background", T["BG3"])
    root.option_add("*TCombobox*Listbox.foreground", T["FG"])
    root.option_add("*TCombobox*Listbox.selectBackground", T["ACCENT"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", F(0))
    root.option_add("*TCombobox*Listbox.borderWidth", 0)


def dark_title_bar(win, dark=None):
    """Тёмный заголовок у обычных окон Windows (настройки, мастер)."""
    if not IS_WIN:
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = int(win.wm_frame(), 16)
        val = ctypes.c_int(T["DARK_TITLE"] if dark is None else int(dark))
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новые и старые сборки)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def bg_of(widget):
    try:
        return widget.cget("bg")
    except tk.TclError:
        return T["BG"]


R = 8   # одно закругление для всего (как у окон Windows 11 и главного окна)


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


class Tooltip:
    """Подсказка при наведении (маленькое окно; его тоже прячет защита от захвата)."""

    def __init__(self, widget, text, delay=550):
        self.widget, self.text, self.delay = widget, text, delay
        self.win = None
        self.job = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, _e=None):
        self._cancel()
        if self.text:
            self.job = self.widget.after(self.delay, self._show)

    def _leave(self, _e=None):
        self._cancel()
        if self.win is not None:
            self.win.destroy()
            self.win = None

    def _cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        if self.win is not None:
            return
        w = self.win = tk.Toplevel(self.widget)
        w.withdraw()
        if IS_WIN:
            w.attributes("-toolwindow", True)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        tk.Label(w, text=self.text, bg=T["BG4"], fg=T["FG"], font=F(-2), padx=8, pady=4, justify="left",
                 wraplength=320).pack()
        w.update_idletasks()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - w.winfo_reqwidth() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        sw = self.widget.winfo_screenwidth()
        w.geometry(f"+{max(4, min(x, sw - w.winfo_reqwidth() - 4))}+{y}")
        w.deiconify()


class IconButton(tk.Label):
    """Значок в заголовке: подсвечивается при наведении."""

    def __init__(self, parent, name, command, tip="", fg=None, size_delta=0):
        text, font = glyph(name)
        font = (font[0], font[1] + size_delta) + tuple(font[2:])
        bg = bg_of(parent)
        super().__init__(parent, text=text, font=font, bg=bg, fg=fg or T["MUTED"], cursor=hand(),
                         padx=7, pady=4)
        self._bg, self._fg = bg, fg or T["MUTED"]
        self.command = command
        self.bind("<Enter>", lambda e: self.config(fg=T["FG"], bg=T["BG4"]))
        self.bind("<Leave>", lambda e: self.config(fg=self._fg, bg=self._bg))
        self.bind("<ButtonRelease-1>", self._click)
        if tip:
            Tooltip(self, tip)

    def set_glyph(self, name):
        self.config(text=glyph(name)[0])

    def retheme(self, cmap):
        self._bg, self._fg = remap(self._bg, cmap), remap(self._fg, cmap)
        self.config(bg=self._bg, fg=self._fg)

    def _click(self, e):
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height() and self.command:
            self.command()


class RoundIconButton(tk.Canvas):
    """Значок в скруглённом квадрате, как кнопки главного окна; danger — при наведении красная (крестик «закрыть»)."""

    def __init__(self, parent, name, command, tip="", size=30, danger=False):
        self.parent_bg = bg_of(parent)
        super().__init__(parent, width=size, height=size, bg=self.parent_bg, highlightthickness=0, bd=0,
                         cursor=hand())
        self.name, self.command, self.size, self.danger, self.hover = name, command, size, danger, False
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<ButtonRelease-1>", self._click)
        if tip:
            Tooltip(self, tip)
        self._draw()

    own_children = True

    def _set(self, hover):
        self.hover = hover
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self.size
        if self.hover:
            _round_rect(self, 0, 0, s - 1, s - 1, 8, fill=T["ERR"] if self.danger else T["BG4"], outline="")
        fg = (T["BG"] if self.danger else T["FG"]) if self.hover else T["MUTED"]
        text, font = glyph(self.name)
        self.create_text(s / 2, s / 2, text=text, font=(font[0], 10) + tuple(font[2:]), fill=fg)

    def retheme(self, cmap):
        self.parent_bg = remap(self.parent_bg, cmap)
        self.config(bg=self.parent_bg)
        self._draw()

    def _click(self, e):
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height() and self.command:
            self.command()


class Button(tk.Canvas):
    """Скруглённая кнопка. kind: primary / secondary / ghost / danger."""

    def __init__(self, parent, text, command=None, kind="secondary", small=False, width=None, icon=None):
        self.parent_bg = bg_of(parent)
        self.kind, self.small, self.command = kind, small, command
        self.font = F(-1 if small else 0, "bold" if kind == "primary" else "normal")
        self.icon = icon
        self.enabled = True
        self._text = text
        self._fixed_w = width
        super().__init__(parent, bg=self.parent_bg, highlightthickness=0, bd=0, cursor=hand())
        self._hover = False
        self._draw()
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _colors(self):
        k = self.kind
        if not self.enabled:
            return T["BG3"], T["FAINT"]
        if k == "primary":
            return (T["ACCENT2"] if self._hover else T["ACCENT"]), "#ffffff"
        if k == "danger":
            return (T["BG4"] if self._hover else T["BG3"]), T["ERR"]
        if k == "ghost":
            return (T["BG3"] if self._hover else self.parent_bg), T["ACCENT"]
        return (T["BG4"] if self._hover else T["BG3"]), T["FG"]

    def _draw(self):
        self.delete("all")
        f = tkfont.Font(font=self.font)
        label = self._text
        tw = f.measure(label)
        icon_w = 0
        if self.icon:
            itxt, ifont = glyph(self.icon)
            icon_w = tkfont.Font(font=(ifont[0], self.font[1])).measure(itxt) + 6
        padx, pady = (10, 4) if self.small else (14, 6)
        w = self._fixed_w or (tw + icon_w + 2 * padx)
        h = f.metrics("linespace") + 2 * pady
        self.config(width=w, height=h)
        bg, fg = self._colors()
        _round_rect(self, 1, 1, w - 1, h - 1, R, fill=bg, outline=bg)
        x = (w - tw - icon_w) / 2
        if self.icon:
            itxt, ifont = glyph(self.icon)
            self.create_text(x, h / 2, text=itxt, font=(ifont[0], self.font[1]), fill=fg, anchor="w")
            x += icon_w
        self.create_text(x, h / 2, text=label, font=self.font, fill=fg, anchor="w")

    def _set_hover(self, v):
        self._hover = v and self.enabled
        self._draw()

    def retheme(self, cmap):
        self.parent_bg = remap(self.parent_bg, cmap)
        self.config(bg=self.parent_bg)
        self._draw()

    def _click(self, e):
        if self.enabled and self.command and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def set_text(self, text):
        self._text = text
        self._draw()

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        self.config(cursor=hand() if flag else "arrow")
        self._draw()


class Toggle(tk.Canvas):
    """Переключатель вкл/выкл."""

    W, H = 40, 22

    def __init__(self, parent, value=False, command=None):
        super().__init__(parent, width=self.W, height=self.H, bg=bg_of(parent), highlightthickness=0, bd=0,
                         cursor=hand())
        self.value = bool(value)
        self.command = command
        self.enabled = True
        self._draw()
        self.bind("<ButtonRelease-1>", self._click)

    def _draw(self):
        self.delete("all")
        on = self.value
        track = (T["ACCENT"] if on else T["BG4"]) if self.enabled else T["BG3"]
        _round_rect(self, 1, 1, self.W - 1, self.H - 1, 7, fill=track, outline=track)
        r = self.H / 2 - 4
        cx = self.W - self.H / 2 if on else self.H / 2
        knob = "#ffffff" if self.enabled else T["FAINT"]
        _round_rect(self, cx - r, self.H / 2 - r, cx + r, self.H / 2 + r, 4, fill=knob, outline=knob)

    def _click(self, _e=None):
        if not self.enabled:
            return
        self.value = not self.value
        self._draw()
        if self.command:
            self.command(self.value)

    def set(self, v):
        self.value = bool(v)
        self._draw()

    def retheme(self, cmap):
        self.config(bg=remap(self.cget("bg"), cmap))
        self._draw()

    def get(self):
        return self.value

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        self._draw()


class Slider(tk.Canvas):
    """Ползунок. command(value) — после отпускания; on_move(value) — во время перетаскивания."""

    def __init__(self, parent, from_, to, value, step=None, width=220, command=None, on_move=None, fmt=None):
        self.H = 24
        super().__init__(parent, width=width, height=self.H, bg=bg_of(parent), highlightthickness=0, bd=0,
                         cursor=hand())
        self.from_, self.to, self.step = from_, to, step
        self.value = value
        self.command, self.on_move, self.fmt = command, on_move, fmt
        self.w = width
        self._draw()
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def _x(self, v):
        f = (v - self.from_) / (self.to - self.from_) if self.to != self.from_ else 0
        return 10 + max(0.0, min(1.0, f)) * (self.w - 20)

    def _draw(self):
        self.delete("all")
        y = self.H / 2
        x = self._x(self.value)
        _round_rect(self, 10, y - 2, self.w - 10, y + 2, 2, fill=T["BG4"], outline=T["BG4"])
        if x > 12:
            _round_rect(self, 10, y - 2, x, y + 2, 2, fill=T["ACCENT"], outline=T["ACCENT"])
        _round_rect(self, x - 8, y - 8, x + 8, y + 8, 5, fill="#ffffff", outline=T["ACCENT"], width=2)

    def _val(self, x):
        f = max(0.0, min(1.0, (x - 10) / max(1, self.w - 20)))
        v = self.from_ + f * (self.to - self.from_)
        if self.step:
            v = round(round(v / self.step) * self.step, 6)
        return v

    def _press(self, e):
        self._move(e)

    def _move(self, e):
        self.value = self._val(e.x)
        self._draw()
        if self.on_move:
            self.on_move(self.value)

    def _release(self, e):
        self.value = self._val(e.x)
        self._draw()
        if self.command:
            self.command(self.value)

    def set(self, v):
        self.value = v
        self._draw()

    def retheme(self, cmap):
        self.config(bg=remap(self.cget("bg"), cmap))
        self._draw()


class RoundFrame(tk.Canvas):
    """Рамка со скруглёнными углами: содержимое кладётся в self.body. stretch — тянуть по ширине родителя
    (блоки настроек), иначе — по содержимому (поле ввода)."""

    def __init__(self, parent, fill=None, outline=None, pad=(14, 12), radius=None, stretch=True):
        super().__init__(parent, bg=bg_of(parent), highlightthickness=0, bd=0, height=10, width=10)
        self.fill_c, self.outline_c = fill or T["BG2"], outline or T["BORDER"]
        self.px, self.py = pad
        self.radius = R if radius is None else radius
        self.stretch = stretch
        self.body = tk.Frame(self, bg=self.fill_c)
        self._win = self.create_window(self.px, self.py, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._fit, add="+")
        self.bind("<Configure>", self._fit, add="+")

    def _fit(self, _e=None):
        bw, bh = self.body.winfo_reqwidth(), self.body.winfo_reqheight()
        h = bh + 2 * self.py
        if self.stretch:
            w = self.winfo_width()
            if w > 2 * self.px:
                self.itemconfigure(self._win, width=w - 2 * self.px)
        else:
            w = bw + 2 * self.px
            if int(float(self.cget("width"))) != w:
                self.configure(width=w)
        if int(float(self.cget("height"))) != h:
            self.configure(height=h)
        self.delete("rbg")
        _round_rect(self, 1, 1, max(2, w - 2), max(2, h - 2), self.radius, fill=self.fill_c, outline=self.outline_c,
                    tags="rbg")
        self.tag_lower("rbg")

    def set_outline(self, color):
        self.outline_c = color
        self.itemconfigure("rbg", outline=color)

    def retheme(self, cmap):
        self.fill_c, self.outline_c = remap(self.fill_c, cmap), remap(self.outline_c, cmap)
        self.config(bg=remap(self.cget("bg"), cmap))
        self._fit()


class _ChoiceRow(tk.Canvas):
    """Строка выпадающего списка: подсветка при наведении — скруглённая."""

    H = 30

    def __init__(self, parent, text, selected, on_click):
        super().__init__(parent, height=self.H, bg=bg_of(parent), highlightthickness=0, bd=0, cursor=hand())
        self.text, self.selected, self.hover = text, selected, False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<ButtonRelease-1>", lambda e: on_click())

    def _set(self, v):
        self.hover = v
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if self.hover:
            _round_rect(self, 0, 1, w - 1, self.H - 1, R, fill=T["BG4"], outline="")
        self.create_text(12, self.H / 2, text=self.text, anchor="w", font=F(0, "bold" if self.selected else "normal"),
                         fill=T["ACCENT2"] if self.selected else T["FG"])


class Choice(tk.Canvas):
    """Выпадающий список: options = [(значение, подпись)]. Поле со скруглением, список — своё окошко со скруглёнными
    углами (как у главного окна), невидимое на демонстрации экрана."""

    H = 32

    def __init__(self, parent, options, value, command=None, width=28):
        self.parent_bg = bg_of(parent)
        f = tkfont.Font(font=F(0))
        self.W = max(120, min(560, f.measure("0") * width + 44))
        super().__init__(parent, width=self.W, height=self.H, bg=self.parent_bg, highlightthickness=0, bd=0,
                         cursor=hand())
        self.options = list(options)
        self.command = command
        self._label = ""
        self.hover = False
        self.popup = None
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self._toggle())
        self.bind("<Configure>", lambda e: self._draw())
        self.set_value(value)

    own_children = True

    def _set_hover(self, v):
        self.hover = v
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() if self.winfo_width() > 20 else self.W
        _round_rect(self, 1, 1, w - 1, self.H - 1, R, fill=T["BG3"],
                    outline=T["ACCENT"] if self.popup else (T["SEL"] if self.hover else T["BORDER"]))
        f = tkfont.Font(font=F(0))
        text, room = self._label, w - 44
        if f.measure(text) > room:
            while text and f.measure(text + "…") > room:
                text = text[:-1]
            text += "…"
        self.create_text(12, self.H / 2, text=text, anchor="w", font=F(0), fill=T["FG"])
        g, gf = glyph("chev")
        self.create_text(w - 17, self.H / 2, text=g, font=(gf[0], 9) if ICON_FONT else gf, fill=T["MUTED"])

    def retheme(self, cmap):
        self.parent_bg = remap(self.parent_bg, cmap)
        self.config(bg=self.parent_bg)
        self._draw()

    # --- как у ttk.Combobox: подпись выбранного
    def set(self, label):
        self._label = label
        self._draw()

    def get(self):
        return self._label

    def selection_clear(self):
        pass

    def set_options(self, options, value=None):
        self.options = list(options)
        if value is not None:
            self.set_value(value)

    # --- список
    def _toggle(self):
        if self.popup is not None:
            self._close()
        else:
            self._open()

    def _open(self):
        from . import winsys
        top = tk.Toplevel(self)
        top.withdraw()
        if IS_WIN:
            top.attributes("-toolwindow", True)    # ДО overrideredirect
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=T["BG3"])
        n = len(self.options)
        rows = min(n, 10)
        h = rows * _ChoiceRow.H + 12
        f = tkfont.Font(font=F(0, "bold"))
        width = max(self.winfo_width(), min(620, max([f.measure(lab) for _, lab in self.options] or [100]) + 48))
        if n > 10:
            sf = ScrollFrame(top, bg=T["BG3"])
            sf.pack(fill="both", expand=True, padx=(6, 2), pady=6)
            box = sf.body
        else:
            box = tk.Frame(top, bg=T["BG3"])
            box.pack(fill="both", expand=True, padx=6, pady=6)
        for v, lab in self.options:
            _ChoiceRow(box, lab, lab == self._label, lambda v=v: self._pick(v)).pack(fill="x")
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.H + 4
        if y + h > self.winfo_screenheight() - 40:
            y = self.winfo_rooty() - h - 4
        top.geometry(f"{int(width)}x{int(h)}+{x}+{y}")
        self.popup = top
        top.deiconify()
        try:
            winsys.style_frame(winsys.tk_hwnd(top), T["SEL"])
        except Exception:
            pass
        top.bind("<ButtonPress-1>", self._outside, add="+")
        top.bind("<Escape>", lambda e: self._close())
        try:
            top.grab_set()
            top.focus_force()
        except tk.TclError:
            pass
        self._draw()

    def _outside(self, e):
        top = self.popup
        if top is None:
            return
        inside = (top.winfo_rootx() <= e.x_root < top.winfo_rootx() + top.winfo_width()
                  and top.winfo_rooty() <= e.y_root < top.winfo_rooty() + top.winfo_height())
        if not inside:
            self._close()

    def _close(self):
        top, self.popup = self.popup, None
        if top is not None:
            try:
                top.grab_release()
                top.destroy()
            except tk.TclError:
                pass
        self._draw()

    def _pick(self, v):
        self._close()
        self.set_value(v)
        if self.command:
            self.command(v)

    def set_value(self, value):
        for v, lab in self.options:
            if v == value:
                self.set(lab)
                return
        if self.options:
            self.set(self.options[0][1])

    def value(self):
        lab = self.get()
        for v, l2 in self.options:
            if l2 == lab:
                return v
        return None

class _REntry(tk.Entry):
    """Поле ввода внутри скруглённой рамки: pack/grid/place двигают рамку целиком."""

    def pack(self, *a, **k):
        return self._box.pack(*a, **k)

    pack_configure = pack

    def pack_forget(self):
        return self._box.pack_forget()

    def grid(self, *a, **k):
        return self._box.grid(*a, **k)

    grid_configure = grid

    def place(self, *a, **k):
        return self._box.place(*a, **k)

    place_configure = place


def round_focus(box, widget):
    """Рамка подсвечивается, пока в поле курсор."""
    widget.bind("<FocusIn>", lambda e: box.set_outline(T["ACCENT"]), add="+")
    widget.bind("<FocusOut>", lambda e: box.set_outline(T["BORDER"]), add="+")


def entry(parent, value="", width=30, show=None):
    box = RoundFrame(parent, fill=T["BG3"], outline=T["BORDER"], pad=(9, 4), stretch=False)
    e = _REntry(box.body, bg=T["BG3"], fg=T["FG"], insertbackground=T["FG"], relief="flat", font=F(0), bd=0,
                width=width, highlightthickness=0, disabledbackground=T["BG3"], disabledforeground=T["FAINT"],
                selectbackground=T["SEL"], selectforeground=T["FG"], cursor=text_cursor())
    e._box = box
    tk.Pack.pack_configure(e, fill="x", ipady=3)
    round_focus(box, e)
    if show:
        e.config(show=show)
    if value:
        e.insert(0, value)
    return e


class ThinScroll(tk.Canvas):
    """Тонкая полоса прокрутки; прячется, когда всё помещается."""

    def __init__(self, parent, target, width=8):
        super().__init__(parent, width=width, bg=bg_of(parent), highlightthickness=0, bd=0)
        self.target = target
        self.first, self.last = 0.0, 1.0
        self.wd = width
        self._drag = None
        self._hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))

    def _set_hover(self, v):
        self._hover = v
        self._draw()

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def retheme(self, cmap):
        self.config(bg=remap(self.cget("bg"), cmap))
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.first <= 0.0 and self.last >= 1.0:
            return
        h = self.winfo_height()
        y0 = self.first * h
        y1 = max(y0 + 24, self.last * h)
        col = T["MUTED"] if (self._hover or self._drag) else T["BG4"]
        _round_rect(self, 2, y0 + 2, self.wd - 2, y1 - 2, (self.wd - 4) / 2, fill=col, outline=col)

    def _press(self, e):
        h = max(1, self.winfo_height())
        f = e.y / h
        if self.first <= f <= self.last:
            self._drag = (e.y, self.first)
        else:
            self.target.yview_moveto(max(0.0, f - (self.last - self.first) / 2))
            self._drag = (e.y, max(0.0, f - (self.last - self.first) / 2))

    def _motion(self, e):
        if not self._drag:
            return
        y0, f0 = self._drag
        h = max(1, self.winfo_height())
        self.target.yview_moveto(max(0.0, f0 + (e.y - y0) / h))


class ScrollFrame(tk.Frame):
    """Прокручиваемая колонка (страницы настроек): self.body — куда класть содержимое."""

    def __init__(self, parent, bg=None):
        bg = bg or bg_of(parent)
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ThinScroll(self, self.canvas)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        if not ScrollFrame._wheel_bound:  # одно колесо на всё приложение: крутим ту колонку, что под курсором
            ScrollFrame._wheel_bound = True
            self.bind_all("<MouseWheel>", ScrollFrame._on_wheel_all, add="+")

    _wheel_bound = False

    @staticmethod
    def _on_wheel_all(e):
        try:
            w = e.widget.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, AttributeError, KeyError):
            return
        while w is not None and not isinstance(w, ScrollFrame):
            if isinstance(w, (tk.Text, ttk.Combobox, tk.Listbox)):
                return  # у этих своя прокрутка
            w = w.master
        if w is not None:
            w._on_wheel(e)

    def _on_wheel(self, e):
        if self.bar.first <= 0.0 and self.bar.last >= 1.0:
            return
        self.canvas.yview_scroll(int(-e.delta / 120) * 3, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)


class Meter(tk.Canvas):
    """Индикатор громкости / прогресса."""

    def __init__(self, parent, width=220, height=10, color=None):
        super().__init__(parent, width=width, height=height, bg=bg_of(parent), highlightthickness=0, bd=0)
        self.w, self.h = width, height
        self.color = color
        self.set(0)

    def set(self, frac, color=None):
        frac = max(0.0, min(1.0, frac))
        self._frac = frac
        self.delete("all")
        _round_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=T["BG4"], outline=T["BG4"])
        if frac > 0.01:
            c = color or self.color or (T["OK"] if frac < 0.75 else T["WARN"] if frac < 0.92 else T["ERR"])
            _round_rect(self, 0, 0, max(self.h, self.w * frac), self.h, self.h / 2, fill=c, outline=c)

    def retheme(self, cmap):
        self.color = remap(self.color, cmap) if self.color else None
        self.config(bg=remap(self.cget("bg"), cmap))
        self.set(getattr(self, "_frac", 0))


# ---------------------------------------------------------------- смена темы на лету

_COLOR_OPTS = ("bg", "fg", "activebackground", "activeforeground", "highlightbackground", "highlightcolor",
               "selectbackground", "selectforeground", "insertbackground", "selectcolor", "disabledbackground",
               "disabledforeground", "troughcolor", "readonlybackground")
_TAG_OPTS = ("foreground", "background", "selectbackground", "selectforeground", "lmargincolor", "rmargincolor")


def remap(color, cmap):
    if not isinstance(color, str):
        return color
    return cmap.get(color.lower(), color)


def _recolor(w, cmap):
    if hasattr(w, "retheme"):
        try:
            w.retheme(cmap)
        except tk.TclError:
            pass
        if getattr(w, "own_children", False):  # сам перекрасил всё внутри
            return
    else:
        for opt in _COLOR_OPTS:
            try:
                v = str(w.cget(opt))
            except (tk.TclError, ValueError):
                continue
            nv = remap(v, cmap)
            if nv != v:
                try:
                    w.configure(**{opt: nv})
                except tk.TclError:
                    pass
        if isinstance(w, tk.Text):
            for tag in w.tag_names():
                for opt in _TAG_OPTS:
                    try:
                        v = str(w.tag_cget(tag, opt))
                    except tk.TclError:
                        continue
                    nv = remap(v, cmap)
                    if v and nv != v:
                        w.tag_configure(tag, **{opt: nv})
        elif isinstance(w, tk.Canvas):
            for item in w.find_all():
                for opt in ("fill", "outline"):
                    try:
                        v = str(w.itemcget(item, opt))
                    except tk.TclError:
                        continue
                    nv = remap(v, cmap)
                    if v and nv != v:
                        w.itemconfigure(item, **{opt: nv})
    for child in w.winfo_children():
        _recolor(child, cmap)


def apply_theme(name, root):
    """Сменить тему сразу во всех открытых окнах программы: старые цвета → новые по ключам палитры."""
    new = THEMES.get(name)
    if not new or new == T:
        return False
    cmap = {T[k].lower(): new[k] for k in T if k != "DARK_TITLE" and isinstance(T[k], str)}
    T.clear()
    T.update(new)
    setup_ttk(root)
    _recolor(root, cmap)
    for top in [root] + [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]:
        try:
            if top is not root and not top.overrideredirect():
                dark_title_bar(top)
        except tk.TclError:
            pass
    return True


def label(parent, text, muted=False, size=0, bold=False, wrap=0, color=None, **kw):
    return tk.Label(parent, text=text, bg=bg_of(parent), fg=color or (T["MUTED"] if muted else T["FG"]),
                    font=F(size, "bold" if bold else "normal"), justify="left", anchor="w",
                    wraplength=wrap, **kw)


def card(parent, title=None, subtitle=None):
    """Блок настроек: светлее фон, тонкая рамка, скруглённые углы (как карточки главного окна)."""
    rf = RoundFrame(parent, fill=T["BG2"], outline=T["BORDER"], pad=(15, 13))
    rf.pack(fill="x", padx=16, pady=(0, 12))
    inner = rf.body
    if title:
        label(inner, title, size=1, bold=True).pack(anchor="w")
    if subtitle:
        label(inner, subtitle, muted=True, size=-1, wrap=640).pack(anchor="w", pady=(2, 6))
    return inner


def row(parent, title, hint=None):
    """Строка «подпись слева — элемент справа». → правая часть (Frame)."""
    r = tk.Frame(parent, bg=bg_of(parent))
    r.pack(fill="x", pady=5)
    left = tk.Frame(r, bg=bg_of(parent))
    left.pack(side="left", fill="x", expand=True)
    label(left, title).pack(anchor="w")
    if hint:
        label(left, hint, muted=True, size=-2, wrap=380).pack(anchor="w")
    right = tk.Frame(r, bg=bg_of(parent))
    right.pack(side="right")
    return right
