# -*- coding: utf-8 -*-
"""Главное окно на движке Edge (WebView2, через pywebview): окно без рамки поверх всех, прозрачное по краям.

Потоки:
  * главный поток Python — цикл окна pywebview (webview.start), он требует главный поток;
  * поток «logic» — вся логика программы (ui_main.App) и служебные окна Tk (настройки, выделение куска экрана);
  * поток отправки — события для окна уходят пачками через run_js (порядок сохраняется).
Окно → программа: pywebview.api.* (класс Bridge) — всё пересылается в поток логики через app.ui_q."""

import ctypes
import json
import os
import sys
import threading
import time

from . import winsys
from .config import S, WORKDIR

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INDEX = os.path.join(WEB_DIR, "index.html")
TITLE = "Claude Overlay"
HEAD_H = 46                     # высота заголовка в CSS-пикселях (компактный режим — только он)
MIN_W, MIN_H = 340, 220

IS_WIN = sys.platform == "win32"
user32 = ctypes.windll.user32 if IS_WIN else None


def available():
    """Можно ли открыть окно на новом движке (есть pywebview)."""
    import importlib.util
    return importlib.util.find_spec("webview") is not None


WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def webview2_installed():
    """Компонент Microsoft Edge WebView2 (в Windows 11 есть всегда, в Windows 10 — почти всегда)."""
    if not IS_WIN:
        return True
    import winreg
    key = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, key.replace("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\")),
                       (winreg.HKEY_LOCAL_MACHINE, key), (winreg.HKEY_CURRENT_USER, key)):
        try:
            with winreg.OpenKey(root, path) as k:
                v, _ = winreg.QueryValueEx(k, "pv")
                if v and v != "0.0.0.0":
                    return True
        except OSError:
            pass
    pf = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return os.path.isdir(os.path.join(pf, "Microsoft", "EdgeWebView", "Application"))


def missing():
    """→ текст «чего не хватает» для окна программы или пустая строка."""
    if not available():
        return ("Не хватает библиотеки для окна программы (pywebview). Запусти «Установить.bat» в папке программы "
                "ещё раз — он докачает недостающее.")
    if not webview2_installed():
        return ("Окну программы нужен компонент Microsoft Edge WebView2 (бесплатный, от Microsoft). Сейчас откроется "
                "страница загрузки: нажми «Download» в блоке «Evergreen Bootstrapper», установи и запусти оверлей снова.")
    return ""


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_pos():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _title(hwnd):
    """Заголовок без обмена сообщениями с окном (GetWindowText шлёт окну другого потока сообщение — могло зависнуть)."""
    buf = ctypes.create_unicode_buffer(256)
    user32.InternalGetWindowText(hwnd, buf, 256)
    return buf.value


def is_main_window(hwnd):
    """Это окно оверлея (WinForms-окно с нашим заголовком)?"""
    try:
        return _title(hwnd) == TITLE and _class_name(hwnd).startswith("WindowsForms")
    except Exception:
        return False


class Bridge:
    """Что окно может попросить у программы (pywebview.api.*). Всё, что трогает логику, — через очередь в поток логики."""

    def __init__(self, app):
        self._app = app

    def _post(self, fn, *a):
        self._app.ui_q.put(("call", lambda: fn(*a)))

    # --- служебное
    def ready(self):
        self._app.web.on_ready()

    def log(self, text):
        print("[окно]", str(text)[:2000])

    # --- вопросы и ответы
    def submit(self, text):
        self._post(self._app.submit_text, str(text))

    def quick(self, kind):
        self._post(self._app.quick, str(kind))

    def copy(self, text, what="текст"):
        self._post(self._app._copy_text, str(text or ""), str(what))

    def cancel(self):
        self._post(self._app.cancel)

    def reset(self):
        self._post(self._app.reset)

    def shot_full(self, sid):
        return self._app.shot_preview(int(sid))

    def open_url(self, url):
        url = str(url or "")
        if url.startswith(("http://", "https://")):
            import webbrowser
            webbrowser.open(url)

    # --- материалы
    def pick_files(self):
        import webview
        try:
            paths = self._app.web.win.create_file_dialog(
                webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("Документы и картинки (*.pdf;*.docx;*.pptx;*.txt;*.md;*.png;*.jpg;*.jpeg;*.webp)",
                            "Все файлы (*.*)"))
        except Exception as e:
            print("[📎] окно выбора файлов:", e)
            paths = None
        if paths:
            self._post(self._app.attach_files, [str(p) for p in paths])

    def paste_material(self):
        self._post(self._app.paste_material)

    def drop_text(self, text):
        self._post(self._app.attach_text, str(text), "Перетащенный текст")

    def remove_material(self, mid):
        self._post(self._app.remove_material, mid)

    def clear_materials(self):
        self._post(self._app.clear_materials)

    # --- окна и панели
    def open_settings(self, tab=None):
        self._post(self._app.open_settings, tab)

    def open_wizard(self):
        self._post(self._app.open_wizard)

    def toggle_info(self):
        self._post(self._app.toggle_info)

    def open_help(self):
        self._post(self._app.open_help)

    def history(self, query=""):
        from . import history
        recs = history.load(str(query or ""))[:400]
        items = [{"q": r.get("q", ""), "a": r.get("a", ""), "kind": r.get("kind", "voice"), "mode": r.get("mode", ""),
                  "error": r.get("error", ""), "when": r.get("t", "")[:16].replace("T", " ")} for r in recs]
        return {"items": items, "saving": bool(S.history_save)}

    def export_history(self, query=""):
        self._post(self._app.export_history, str(query or ""))

    def clear_history(self):
        from . import history
        history.clear()
        return True

    def capture_check(self):
        try:
            return self._app.capture_check_web()
        except Exception as e:
            print("[невидимость] проверка:", e)
            return None

    def pick_region(self):
        self._post(self._app.pick_region)

    def clear_shot(self):
        self._post(self._app.set_pending_shot, None)

    def toggle_compact(self):
        self._post(self._app.toggle_compact)

    def hide(self):
        self._post(self._app.hide)

    def quit(self):
        self._post(self._app._quit)

    def font(self, delta):
        S.update(font_size=max(8, min(24, int(S.font_size) + (1 if int(delta) > 0 else -1))))

    def set_theme(self, name):
        S.update(theme=str(name))

    def set_ghost(self, on):
        S.update(ghost=bool(on))

    # --- перетаскивание и размер (свой цикл по мышке: у окна без рамки нет краёв Windows)
    def start_move(self):
        self._app.web.track("move")

    def start_resize(self, edge):
        self._app.web.track(str(edge))


class WebWindow:
    def __init__(self, app):
        import webview
        self.app = app
        self.webview = webview
        self.ready = False
        self._q = []
        self._keys = {}
        self._cv = threading.Condition()
        self._hwnd = None
        self._tracking = False
        self.visible = True
        x, y, w, h = app.initial_rect()
        self.win = webview.create_window(
            TITLE, url=INDEX, js_api=Bridge(app), width=w, height=h, x=x, y=y, frameless=True, on_top=True,
            transparent=True, easy_drag=False, min_size=(200, 40), background_color="#17181c", text_select=True,
            shadow=False, focus=True)
        self.win.events.before_show += self._before_show
        self.win.events.loaded += self._on_loaded
        self.win.events.closed += lambda: app.ui_q.put(("call", app._quit))
        threading.Thread(target=self._sender, daemon=True, name="web-send").start()

    # ---------------------------------------------------------------- запуск
    def start(self):
        """Цикл окна — в главном потоке, до закрытия окна."""
        storage = os.path.join(WORKDIR, "webview")
        os.makedirs(storage, exist_ok=True)
        self.webview.start(gui="edgechromium", private_mode=True, storage_path=storage, debug=False)

    def _before_show(self):
        """В потоке окна, до первого показа: без кнопки на панели задач и в Alt+Tab, невидимо для захвата экрана."""
        try:
            h = self.hwnd
            if h:
                winsys.ensure_tool_window(h)
                g = getattr(self.app, "guard", None)
                if g is not None:
                    g.apply(h)
        except Exception as e:
            print("[окно] подготовка окна:", e)

    def _on_loaded(self):
        """Страница загрузилась: файлы, перетащенные в окно, — с полными путями (их даёт только pywebview)."""
        try:
            from webview.dom import DOMEventHandler

            def on_drop(e):
                files = (e.get("dataTransfer") or {}).get("files") or []
                paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
                if paths:
                    self.app.ui_q.put(("call", lambda: self.app.attach_files(paths)))
            self.win.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception as e:
            print("[📎] перетаскивание файлов недоступно:", e)

    def on_ready(self):
        first = not self.ready
        self.app.ui_q.put(("call", self.app.web_ready))
        if first:
            print("[окно] новый интерфейс готов")

    def mark_ready(self):
        with self._cv:
            self.ready = True
            self._cv.notify()

    # ---------------------------------------------------------------- события в окно
    def send(self, name, payload=None, key=None):
        """key — заменить ещё не отправленное событие с тем же ключом (строка состояния, печать ответа)."""
        with self._cv:
            if key is not None and key in self._keys and self._keys[key] < len(self._q):
                self._q[self._keys[key]] = [name, payload]
            else:
                if key is not None:
                    self._keys[key] = len(self._q)
                self._q.append([name, payload])
            self._cv.notify()

    def _sender(self):
        while True:
            with self._cv:
                while not (self.ready and self._q):
                    self._cv.wait()
                batch, self._q, self._keys = self._q, [], {}
            js = "window.ui&&ui.recv(" + json.dumps(batch, ensure_ascii=False) + ")"
            try:
                self.win.run_js(js)
            except Exception as e:
                print("[окно] не удалось передать в окно:", e)
            time.sleep(0.012)

    # ---------------------------------------------------------------- окно Windows
    @property
    def hwnd(self):
        h = self._hwnd
        if h and user32.IsWindow(h) and is_main_window(h):
            return h
        for h in winsys.process_windows(os.getpid(), visible_only=False):
            if is_main_window(h):
                self._hwnd = h
                return h
        return None

    def scale(self):
        h = self.hwnd
        try:
            return (user32.GetDpiForWindow(h) if h else 96) / 96.0 or 1.0
        except Exception:
            return 1.0

    def rect(self):
        h = self.hwnd
        return winsys.window_rect(h) if h else None

    def set_rect(self, x, y, w, h):
        hw = self.hwnd
        if hw:
            # SWP_NOZORDER | SWP_NOACTIVATE
            user32.SetWindowPos(hw, None, int(x), int(y), int(w), int(h), 0x0004 | 0x0010)

    def show(self):
        self.visible = True
        try:
            self.win.show()
        except Exception as e:
            print("[окно] show:", e)
        h = self.hwnd
        if h:
            user32.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_TOPMOST, NOSIZE|NOMOVE|NOACTIVATE

    def hide(self):
        self.visible = False
        try:
            self.win.hide()
        except Exception as e:
            print("[окно] hide:", e)

    def unminimize(self):
        """Win+D / «свернуть все» сворачивают и наше окно — разворачиваем обратно."""
        h = self.hwnd
        if h and self.visible and user32.IsIconic(h):
            user32.ShowWindow(h, 9)  # SW_RESTORE
            user32.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

    def focus(self):
        h = self.hwnd
        if h:
            winsys.force_foreground(h)
        self.send("focus", {})

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass

    # ---------------------------------------------------------------- перетаскивание / размер
    def track(self, kind):
        if self._tracking or not self.hwnd:
            return
        self._tracking = True
        threading.Thread(target=self._track, args=(kind,), daemon=True, name="web-drag").start()

    def _track(self, kind):
        try:
            h = self.hwnd
            x0, y0, x1, y1 = winsys.window_rect(h)
            cx0, cy0 = cursor_pos()
            sc = self.scale()
            mw, mh = int(MIN_W * sc), int(MIN_H * sc)
            moved = False
            while user32.GetAsyncKeyState(0x01) & 0x8000:  # левая кнопка ещё нажата
                cx, cy = cursor_pos()
                dx, dy = cx - cx0, cy - cy0
                if dx or dy:
                    moved = True
                if kind == "move":
                    user32.SetWindowPos(h, None, x0 + dx, y0 + dy, 0, 0, 0x0001 | 0x0004 | 0x0010)
                else:
                    L, T, R, B = x0, y0, x1, y1
                    if "l" in kind:
                        L = min(x0 + dx, x1 - mw)
                    if "r" in kind:
                        R = max(x1 + dx, x0 + mw)
                    if "b" in kind:
                        B = max(y1 + dy, y0 + mh)
                    user32.SetWindowPos(h, None, L, T, R - L, B - T, 0x0004 | 0x0010)
                time.sleep(0.008)
            if moved:
                self.app.ui_q.put(("call", self.app._save_geometry))
        except Exception as e:
            print("[окно] перетаскивание:", e)
        finally:
            self._tracking = False
