# -*- coding: utf-8 -*-
"""Значок в трее (по умолчанию выключен: панель задач видна на демонстрации экрана). Включается в ⚙ → «Невидимость и система».
Меню трея — окно нашей программы, его тоже прячет защита от захвата экрана."""

import threading

from .config import ICON_PNG


class Tray:
    def __init__(self, on_event):
        self.on_event = on_event      # on_event("toggle" / "settings" / "wizard" / "quit") — из потока трея
        self.icon = None
        self.error = ""

    @property
    def running(self):
        return self.icon is not None

    def start(self):
        if self.icon is not None:
            return True
        try:
            import pystray
            from PIL import Image
        except Exception as e:
            self.error = f"нет библиотеки pystray ({e}) — запусти «Установить.bat», он её поставит"
            print("[трей]", self.error)
            return False
        try:
            image = Image.open(ICON_PNG)
        except Exception:
            image = Image.new("RGB", (64, 64), (217, 119, 87))
        ev = self.on_event
        menu = pystray.Menu(
            pystray.MenuItem("Показать / спрятать", lambda *_: ev("toggle"), default=True),
            pystray.MenuItem("Настройки", lambda *_: ev("settings")),
            pystray.MenuItem("Проверить и починить (мастер)", lambda *_: ev("wizard")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda *_: ev("quit")),
        )
        try:
            self.icon = pystray.Icon("ClaudeOverlay", image, "Claude Overlay", menu)
            threading.Thread(target=self.icon.run, daemon=True, name="tray").start()
            return True
        except Exception as e:
            self.icon = None
            self.error = str(e)
            print("[трей] не запустился:", e)
            return False

    def stop(self):
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
