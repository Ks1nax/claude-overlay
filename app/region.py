# -*- coding: utf-8 -*-
"""Выделить кусок экрана для следующего вопроса (как «Ножницы»): снимок монитора под курсором показывается
поверх экрана затемнённым, рамку тянешь мышкой, отпустил — кусок прикреплён. Esc или правая кнопка — отмена.
Окно выделения, как и все окна программы, не видно на демонстрации экрана."""

import tkinter as tk

from . import winsys
from .ui_theme import T, F, IS_WIN


def _monitor_under(x, y):
    import mss
    with (mss.MSS() if hasattr(mss, "MSS") else mss.mss()) as sct:
        mons = sct.monitors
        mon = mons[1] if len(mons) > 1 else mons[0]
        for m in mons[1:]:
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                mon = m
                break
        shot = sct.grab(mon)
    from PIL import Image
    return dict(mon), Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


class RegionPicker:
    def __init__(self, app, on_done):
        """on_done(картинка PIL или None)."""
        from PIL import ImageEnhance, ImageTk
        self.app, self.on_done = app, on_done
        r = app.root
        x, y = r.winfo_pointerx(), r.winfo_pointery()
        hidden = app._hide_for_capture()  # на старой Windows окно оверлея попало бы в снимок
        try:
            self.mon, self.shot = _monitor_under(x, y)
        finally:
            app._restore_after_capture(hidden)
        dim = ImageEnhance.Brightness(self.shot).enhance(0.45)
        self._dim = ImageTk.PhotoImage(dim)
        self._crop_img = None
        w = self.win = tk.Toplevel(r)
        w.withdraw()
        if IS_WIN:
            w.attributes("-toolwindow", True)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        m = self.mon
        w.geometry(f"{m['width']}x{m['height']}+{m['left']}+{m['top']}")
        c = self.c = tk.Canvas(w, width=m["width"], height=m["height"], highlightthickness=0, bd=0,
                               cursor="crosshair", bg="#101010")
        c.pack(fill="both", expand=True)
        c.create_image(0, 0, image=self._dim, anchor="nw")
        self.hint = c.create_text(m["width"] // 2, 40, fill="#f2f2f2", font=F(3, "bold"),
                                  text="Выдели мышкой кусок экрана для вопроса · Esc — отмена")
        self.start = None
        self.rect = self.crop_item = self.size_lbl = None
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<ButtonPress-3>", lambda e: self._finish(None))
        w.bind("<Escape>", lambda e: self._finish(None))
        w.update_idletasks()
        app.guard.protect_tk(w)
        w.deiconify()
        app.guard.protect_tk(w)
        winsys.force_foreground(winsys.tk_hwnd(w))
        w.focus_force()

    def _box(self, e):
        x0, y0 = self.start
        return min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y)

    def _press(self, e):
        self.start = (e.x, e.y)
        self.c.itemconfigure(self.hint, state="hidden")

    def _move(self, e):
        if not self.start:
            return
        from PIL import ImageTk
        L, Tp, R, B = self._box(e)
        if R - L < 2 or B - Tp < 2:
            return
        self._crop_img = ImageTk.PhotoImage(self.shot.crop((L, Tp, R, B)))  # выделенное — без затемнения
        for item in (self.crop_item, self.rect, self.size_lbl):
            if item:
                self.c.delete(item)
        self.crop_item = self.c.create_image(L, Tp, image=self._crop_img, anchor="nw")
        self.rect = self.c.create_rectangle(L, Tp, R, B, outline=T["ACCENT"], width=2)
        self.size_lbl = self.c.create_text(L, max(12, Tp - 12), anchor="w", fill="#f2f2f2", font=F(-1),
                                           text=f"{R - L} × {B - Tp}")

    def _release(self, e):
        if not self.start:
            return
        L, Tp, R, B = self._box(e)
        if R - L < 12 or B - Tp < 12:  # просто щелчок — пусть выделит заново
            self.start = None
            self.c.itemconfigure(self.hint, state="normal")
            return
        self._finish(self.shot.crop((L, Tp, R, B)))

    def _finish(self, img):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_done(img)
