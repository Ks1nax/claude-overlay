#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Overlay — голосовой помощник поверх всех окон (Windows).

  * постоянно слушает микрофон (локально, через faster-whisper — звук никуда не уходит);
  * «Клод, …» — скриншот экрана + вопрос уходят Claude (Claude Code по подписке или API-ключ);
  * F7 — вопрос со звука компьютера (лекция, созвон, видео): нажать в начале и в конце вопроса;
  * окно не видно на демонстрации экрана и скриншотах (у тебя на мониторе — видно).

Запуск:
  ярлык «Claude Overlay» (pythonw overlay.py)  — обычный запуск, без чёрной консоли
  start.bat                                    — то же с консолью (для отладки)
  python overlay.py --wizard                   — мастер первого запуска («Проверить и починить»)
  python overlay.py --settings                 — открыть сразу и настройки
  python overlay.py --setup-gpu                — подготовить видеокарту NVIDIA (в консоли)
  python overlay.py --make-shortcuts           — ярлыки на рабочем столе и в «Пуске»

Программа — в папке app/ (настройки по умолчанию — app/config.py), журнал — workspace/overlay.log.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _dpi_aware():
    if sys.platform == "win32":
        try:  # чтобы координаты курсора, окна и скриншота совпадали при масштабировании экрана
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def main():
    if "--gpu-test" in sys.argv:   # отдельный процесс проверки видеокарты (может упасть — оверлей не пострадает)
        from app.stt import gpu_selftest
        sys.exit(gpu_selftest())

    from app import winsys
    from app.config import LOG_PATH
    winsys.setup_log(LOG_PATH)  # без консоли (pythonw) всё, что раньше было в чёрном окне, — в workspace/overlay.log

    if "--setup-gpu" in sys.argv:
        from app.stt import setup_gpu
        setup_gpu()
        return
    if "--make-shortcuts" in sys.argv:
        from app.setup_tools import make_app_shortcuts
        for p in make_app_shortcuts():
            print("[ярлык]", p)
        return

    _dpi_aware()
    if "--wizard" in sys.argv:
        inst = winsys.SingleInstance("ClaudeOverlay.Wizard")
        if inst.already:  # мастер уже открыт — показываем его
            inst.wake_other()
            return
        from app.ui_wizard import run_wizard
        run_wizard(inst)
        return

    inst = winsys.SingleInstance("ClaudeOverlay")
    if inst.already:  # вторая копия дралась бы за микрофон и клавиши — будим первую и выходим
        print("[запуск] оверлей уже запущен — показываю его окно" if inst.wake_other() else
              "[запуск] оверлей уже запущен, но не отвечает — вторую копию не запускаю")
        return
    from app import webwin
    problem = webwin.missing()
    if problem:   # без движка окна программа не откроется — объясняем, что сделать
        print("[запуск]", problem)
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Claude Overlay", problem, parent=r)
        r.destroy()
        if webwin.available():
            import webbrowser
            webbrowser.open(webwin.WEBVIEW2_URL)
        return
    from app.ui_main import App
    app = App(inst)
    inst.on_wake(lambda: app.ui_q.put(("show",)))
    inst.on_signal("Quit", lambda: app.ui_q.put(("quit",)))
    if "--settings" in sys.argv:
        app.ui_q.put(("call", app.open_settings))
    app.run()


if __name__ == "__main__":
    main()
