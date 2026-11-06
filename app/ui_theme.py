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

THEMES = {
    "dark": {"BG": "#16181d", "BG2": "#1e2128", "BG3": "#262a33", "BG4": "#30353f", "FG": "#e8e8e8",
             "MUTED": "#8b919c", "FAINT": "#5c626d", "ACCENT": "#d97757", "ACCENT2": "#e8896a",
             "CODE_BG": "#0c0e11", "CODE_FG": "#c8d3e0", "IC_FG": "#e5c07b", "ERR": "#ff6b6b", "OK": "#4cc38a",
             "WARN": "#e5c07b", "INFO": "#61afef", "BORDER": "#2c3038", "SEL": "#3a3f4b", "PURPLE": "#b48cff",
             "TEAL": "#56b6c2", "REC": "#e06c75", "DARK_TITLE": 1},
    "black": {"BG": "#000000", "BG2": "#0e0f11", "BG3": "#1a1c20", "BG4": "#24272d", "FG": "#ececec",
              "MUTED": "#8a8f98", "FAINT": "#55595f", "ACCENT": "#d97757", "ACCENT2": "#e8896a",
              "CODE_BG": "#0b0c0e", "CODE_FG": "#c8d3e0", "IC_FG": "#e5c07b", "ERR": "#ff6b6b", "OK": "#4cc38a",
              "WARN": "#e5c07b", "INFO": "#61afef", "BORDER": "#202227", "SEL": "#33373f", "PURPLE": "#b48cff",
              "TEAL": "#56b6c2", "REC": "#e06c75", "DARK_TITLE": 1},
    "light": {"BG": "#f7f7f5", "BG2": "#ebebe7", "BG3": "#ffffff", "BG4": "#e1e1dc", "FG": "#1d1f23",
              "MUTED": "#666b74", "FAINT": "#9a9ea6", "ACCENT": "#c8603f", "ACCENT2": "#b5532f",
              "CODE_BG": "#efefec", "CODE_FG": "#24292f", "IC_FG": "#9a5b00", "ERR": "#d32f2f", "OK": "#1e8e5a",
              "WARN": "#a86b00", "INFO": "#1f6fd1", "BORDER": "#d6d6d0", "SEL": "#cfe0ff", "PURPLE": "#7c4dcc",
              "TEAL": "#1b8a99", "REC": "#d0394a", "DARK_TITLE": 0},
}
THEME_NAMES = {"dark": "Тёмная", "black": "Чёрная", "light": "Светлая"}

T = dict(THEMES.get(S.theme, THEMES["dark"]))   # тема меняется после перезапуска

UI_FONT = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
MONO_FONT = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")
ICON_FONT = None

# Значки Segoe Fluent Icons / Segoe MDL2 Assets; запасной вариант — обычные символы
GLYPHS = {
    "settings": ("", "⚙"), "attach": ("", "📎"), "paste": ("", "📋"), "new": ("", "⟲"),
    "hide": ("", "—"), "close": ("", "✕"), "help": ("", "?"), "compact": ("", "▭"),
    "expand": ("", "▢"), "copy": ("", "⧉"), "down": ("", "↓"), "shield": ("", "🛡"),
    "mic": ("", "🎙"), "check": ("", "✓"), "warn": ("", "⚠"), "play": ("", "▶"),
    "delete": ("", "🗑"), "download": ("", "⬇"), "folder": ("", "📁"), "eye": ("", "👁"),
}

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
        _round_rect(self, 1, 1, w - 1, h - 1, 7, fill=bg, outline=bg)
        x = (w - tw - icon_w) / 2
        if self.icon:
            itxt, ifont = glyph(self.icon)
            self.create_text(x, h / 2, text=itxt, font=(ifont[0], self.font[1]), fill=fg, anchor="w")
            x += icon_w
        self.create_text(x, h / 2, text=label, font=self.font, fill=fg, anchor="w")

    def _set_hover(self, v):
        self._hover = v and self.enabled
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
        _round_rect(self, 1, 1, self.W - 1, self.H - 1, self.H / 2, fill=track, outline=track)
        r = self.H / 2 - 4
        cx = self.W - self.H / 2 if on else self.H / 2
        knob = "#ffffff" if self.enabled else T["FAINT"]
        self.create_oval(cx - r, self.H / 2 - r, cx + r, self.H / 2 + r, fill=knob, outline=knob)

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
        self.create_line(10, y, self.w - 10, y, fill=T["BG4"], width=4, capstyle="round")
        self.create_line(10, y, x, y, fill=T["ACCENT"], width=4, capstyle="round")
        self.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#ffffff", outline=T["ACCENT"], width=2)

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


class Choice(ttk.Combobox):
    """Выпадающий список: options = [(значение, подпись)]."""

    def __init__(self, parent, options, value, command=None, width=28):
        self.options = list(options)
        labels = [lab for _, lab in self.options]
        super().__init__(parent, values=labels, state="readonly", width=width, font=F(0))
        self.command = command
        self.set_value(value)
        self.bind("<<ComboboxSelected>>", self._sel)

    def set_options(self, options, value=None):
        self.options = list(options)
        self.config(values=[lab for _, lab in self.options])
        if value is not None:
            self.set_value(value)

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

    def _sel(self, _e=None):
        self.selection_clear()
        if self.command:
            self.command(self.value())


def entry(parent, value="", width=30, show=None):
    e = tk.Entry(parent, bg=T["BG3"], fg=T["FG"], insertbackground=T["FG"], relief="flat", font=F(0),
                 width=width, highlightthickness=1, highlightbackground=T["BORDER"], highlightcolor=T["ACCENT"],
                 disabledbackground=T["BG2"], selectbackground=T["SEL"], selectforeground=T["FG"],
                 cursor=text_cursor())
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
        self.delete("all")
        _round_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=T["BG4"], outline=T["BG4"])
        if frac > 0.01:
            c = color or self.color or (T["OK"] if frac < 0.75 else T["WARN"] if frac < 0.92 else T["ERR"])
            _round_rect(self, 0, 0, max(self.h, self.w * frac), self.h, self.h / 2, fill=c, outline=c)


def label(parent, text, muted=False, size=0, bold=False, wrap=0, color=None, **kw):
    return tk.Label(parent, text=text, bg=bg_of(parent), fg=color or (T["MUTED"] if muted else T["FG"]),
                    font=F(size, "bold" if bold else "normal"), justify="left", anchor="w",
                    wraplength=wrap, **kw)


def card(parent, title=None, subtitle=None):
    """Блок настроек: рамка со скруглением не нужна — просто светлее фон и отступы."""
    outer = tk.Frame(parent, bg=T["BG2"], highlightthickness=1, highlightbackground=T["BORDER"])
    outer.pack(fill="x", padx=16, pady=(0, 12))
    inner = tk.Frame(outer, bg=T["BG2"])
    inner.pack(fill="x", padx=14, pady=12)
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
