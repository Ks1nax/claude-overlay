# -*- coding: utf-8 -*-
"""Windows: невидимость окон на демонстрации экрана, окно без кнопки на панели задач, один запущенный экземпляр,
ярлыки, автозапуск и журнал workspace/overlay.log.

Невидимость — SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE): окно видно на мониторе, но его нет ни в одном
захвате экрана (GDI/BitBlt, DXGI — OBS/Discord/Zoom/Teams, Windows.Graphics.Capture — браузеры, Ножницы).
Проверено опытом на этом компьютере: без защиты окно было в 100% кадров всех трёх способов, с защитой — в 0%."""

import ctypes
import os
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform == "win32"

WDA_NONE = 0x00
WDA_MONITOR = 0x01                 # старые Windows: в записи вместо окна чёрный прямоугольник
WDA_EXCLUDEFROMCAPTURE = 0x11      # Windows 10 2004 (сборка 19041) и новее: окна в записи нет совсем

NO_WINDOW = {"creationflags": 0x08000000} if IS_WIN else {}  # дочерние программы — без чёрного окна консоли

if IS_WIN:
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)

    user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
    user32.SetWindowDisplayAffinity.restype = wt.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wt.BOOL
    user32.GetAncestor.argtypes = [wt.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wt.HWND
    user32.GetParent.argtypes = [wt.HWND]
    user32.GetParent.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindow.restype = wt.BOOL
    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_uint]
    user32.SetWindowPos.restype = wt.BOOL
    user32.GetClassNameW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC, wt.DWORD, wt.DWORD, wt.DWORD]
    user32.SetWinEventHook.restype = wt.HANDLE
    user32.UnhookWinEvent.argtypes = [wt.HANDLE]
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateEventW.restype = wt.HANDLE
    kernel32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    kernel32.OpenEventW.restype = wt.HANDLE
    kernel32.SetEvent.argtypes = [wt.HANDLE]
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.WaitForSingleObject.restype = wt.DWORD
    kernel32.CloseHandle.argtypes = [wt.HANDLE]

GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000


def windows_build():
    if not IS_WIN:
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def exclude_supported():
    """Полная невидимость есть с Windows 10 версии 2004 (сборка 19041)."""
    return windows_build() >= 19041


def get_affinity(hwnd):
    if not IS_WIN or not hwnd:
        return None
    d = wt.DWORD(0)
    if not user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(d)):
        return None
    return d.value


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def tk_hwnd(widget):
    """Настоящее верхнее окно Windows для окна Tk (обёртка, которую Tk создаёт вокруг содержимого).
    Важно: Tk пересоздаёт обёртку при смене overrideredirect/-toolwindow — поэтому берём заново каждый раз."""
    if not IS_WIN:
        return 0
    try:
        h = int(widget.wm_frame(), 16)
        if h and user32.IsWindow(h):
            return h
    except Exception:
        pass
    try:
        inner = widget.winfo_id()
        return user32.GetAncestor(inner, GA_ROOT) or user32.GetParent(inner) or inner
    except Exception:
        return 0


def window_rect(hwnd):
    rc = wt.RECT()
    if IS_WIN and hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return rc.left, rc.top, rc.right, rc.bottom
    return None


def process_windows(pid=None, visible_only=True):
    """Все верхние окна этого процесса."""
    if not IS_WIN:
        return []
    pid = pid or os.getpid()
    out = []

    def cb(h, _l):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and (not visible_only or user32.IsWindowVisible(h)):
            out.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def ensure_tool_window(hwnd):
    """Окно-инструмент: без кнопки на панели задач и без пункта в Alt+Tab."""
    if not IS_WIN or not hwnd:
        return
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    want = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if want != ex:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, want)
        # SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)


def style_frame(hwnd, border_hex=None, rounded=True):
    """Windows 11: скруглённые углы (DWMWA_WINDOW_CORNER_PREFERENCE) и цвет тонкой рамки (DWMWA_BORDER_COLOR)."""
    if not IS_WIN or not hwnd:
        return
    try:
        dwm = ctypes.windll.dwmapi
        pref = ctypes.c_int(2 if rounded else 1)          # DWMWCP_ROUND / DWMWCP_DONOTROUND
        dwm.DwmSetWindowAttribute(wt.HWND(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        if border_hex:
            h = border_hex.lstrip("#")
            colorref = ctypes.c_uint(int(h[4:6], 16) << 16 | int(h[2:4], 16) << 8 | int(h[0:2], 16))
            dwm.DwmSetWindowAttribute(wt.HWND(hwnd), 34, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:
        pass


def force_foreground(hwnd):
    """Сделать окно активным (чтобы печатать в нём) по горячей клавише из другой программы."""
    if not IS_WIN or not hwnd:
        return False
    try:
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        # «подключаемся» к вводу активного окна — тогда Windows разрешает передать фокус нам (без лишних нажатий)
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        my_tid = kernel32.GetCurrentThreadId()
        attached = bool(fg_tid and fg_tid != my_tid and user32.AttachThreadInput(my_tid, fg_tid, True))
        try:
            ok = bool(user32.SetForegroundWindow(hwnd))
            user32.BringWindowToTop(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(my_tid, fg_tid, False)
        return ok
    except Exception:
        return False


def is_tool_window(hwnd):
    if not IS_WIN or not hwnd:
        return False
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    return bool(ex & WS_EX_TOOLWINDOW) and not ex & WS_EX_APPWINDOW


class CaptureGuard:
    """Прячет ВСЕ окна программы от захвата экрана.
    1) Хук событий окон: любое новое окно программы (стандартный выбор файлов, сообщение, меню, подсказка)
       защищается в момент создания — ещё до того, как появится на экране. Проверено: стандартное окно
       выбора файлов без хука попадало в 26 из 44 кадров записи, с хуком — ни в один.
    2) Раз в полсекунды — проход по всем окнам программы (Tk пересоздаёт окно при смене некоторых свойств).
    3) protect_tk(окно) — явная защита конкретного окна Tk (после показа, смены overrideredirect и т. п.)."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.mode = WDA_EXCLUDEFROMCAPTURE if exclude_supported() else WDA_MONITOR
        self.pid = os.getpid()
        self._hook = None
        self._proc = None
        self._started = False
        self.errors = 0
        # функция(hwnd) → True: окно должно быть «инструментом» (без панели задач и Alt+Tab). Проверяется только
        # проходом раз в 0,5 с: в хуке нельзя — окно другого потока, обмен сообщениями с ним мог зависнуть
        self.tool_check = None

    @property
    def want(self):
        return self.mode if self.enabled else WDA_NONE

    def install(self):
        """Вызывать из потока с циклом сообщений (поток Tk): события хука приходят в этот цикл. Ловит окна всех
        потоков программы — и окна Tk, и главное окно на движке Edge."""
        if not IS_WIN or self._started:
            return
        self._started = True
        try:
            self._proc = WINEVENTPROC(self._on_event)
            self._hook = user32.SetWinEventHook(EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW, None, self._proc,
                                                self.pid, 0, WINEVENT_OUTOFCONTEXT)
            if not self._hook:
                print("[невидимость] хук событий окон не установился — работает только периодическая проверка")
        except Exception as e:
            print("[невидимость] хук событий окон недоступен:", e)
        threading.Thread(target=self._sweeper, daemon=True, name="capture-guard").start()

    def _on_event(self, hook, event, hwnd, id_obj, id_child, thread, t):
        if id_obj != 0 or not hwnd or event == 0x8001:  # только сами окна (OBJID_WINDOW), не удаление
            return
        try:
            if user32.GetAncestor(hwnd, GA_ROOT) == hwnd:
                self.apply(hwnd)   # стиль окна здесь не трогаем: окно может принадлежать другому потоку (зависание)
        except Exception:
            pass

    def _tool(self, hwnd):
        if self.tool_check is not None and self.tool_check(hwnd):
            ensure_tool_window(hwnd)

    def _sweeper(self):
        while True:
            time.sleep(0.5)
            try:
                for h in process_windows(self.pid):
                    self.apply(h)
                    self._tool(h)
            except Exception as e:
                self.errors += 1
                if self.errors < 5:
                    print("[невидимость] ошибка проверки окон:", e)

    def apply(self, hwnd):
        """Ставит окну нужную защиту. → итоговое значение (0x11 — невидимо, 0x01 — чёрный прямоугольник)."""
        if not IS_WIN or not hwnd:
            return None
        want = self.want
        cur = get_affinity(hwnd)
        if cur == want:
            return cur
        if not user32.SetWindowDisplayAffinity(hwnd, want) and want == WDA_EXCLUDEFROMCAPTURE:
            user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)  # хотя бы чёрный прямоугольник
        return get_affinity(hwnd)

    def protect_tk(self, widget, tool=True):
        """Защитить окно Tk (и сделать окном-инструментом). Безопасно вызывать сколько угодно раз."""
        h = tk_hwnd(widget)
        if tool:
            ensure_tool_window(h)
        return self.apply(h)

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        for h in process_windows(self.pid, visible_only=False):
            self.apply(h)

    def window_states(self):
        return [(h, get_affinity(h)) for h in process_windows(self.pid)]

    def fully_hidden(self, widget=None):
        """True — окна точно нет в захвате (можно делать свой скриншот, не пряча окно)."""
        if not IS_WIN or not self.enabled or self.mode != WDA_EXCLUDEFROMCAPTURE:
            return False
        if widget is not None:
            return get_affinity(tk_hwnd(widget)) == WDA_EXCLUDEFROMCAPTURE
        states = self.window_states()
        return bool(states) and all(a == WDA_EXCLUDEFROMCAPTURE for _, a in states)

    def status(self, widget=None):
        """→ (уровень, текст для окна): уровень "ok" / "partial" / "off" / "fail"."""
        if not IS_WIN:
            return "fail", "⚠ Не скрыт: невидимость на демонстрации есть только в Windows"
        if not self.enabled:
            return "off", "⚠ Не скрыт: невидимость выключена в настройках"
        states = self.window_states()   # только видимые окна: у спрятанного/свёрнутого окна Windows может не ответить
        if widget is not None:
            h = tk_hwnd(widget)
            if h and user32.IsWindowVisible(h) and not user32.IsIconic(h) and h not in [s[0] for s in states]:
                states = [(h, get_affinity(h))] + states
        if not states:  # окон на экране нет — значит, и показывать нечего; защита включена для будущих окон
            return ("ok", "🛡 Скрыт от демонстрации экрана") if self.mode == WDA_EXCLUDEFROMCAPTURE else \
                ("partial", "⚠ Скрыт не полностью: эта Windows старая — на демонстрации вместо окна будет "
                            "чёрный прямоугольник. Полная невидимость — с Windows 10 версии 2004.")
        if all(a == WDA_EXCLUDEFROMCAPTURE for _, a in states):
            return "ok", "🛡 Скрыт от демонстрации экрана"
        if states and all(a in (WDA_MONITOR, WDA_EXCLUDEFROMCAPTURE) for _, a in states):
            return "partial", ("⚠ Скрыт не полностью: эта Windows старая — на демонстрации вместо окна будет "
                               "чёрный прямоугольник. Полная невидимость — с Windows 10 версии 2004.")
        return "fail", "⚠ Не скрыт: Windows не дала включить защиту окна"


def grab_monitor_of(hwnd):
    """Снимок монитора, где окно, тем же способом, что у программ демонстрации и скриншотов (BitBlt рабочего
    стола; DXGI и Windows.Graphics.Capture Windows обрабатывает так же). → (картинка PIL, прямоугольник окна
    в координатах картинки)."""
    import mss
    from PIL import Image

    rc = window_rect(hwnd) or (0, 0, 0, 0)
    cx, cy = (rc[0] + rc[2]) // 2, (rc[1] + rc[3]) // 2
    with mss.MSS() if hasattr(mss, "MSS") else mss.mss() as sct:
        mons = sct.monitors
        mon = mons[1] if len(mons) > 1 else mons[0]
        for m in mons[1:]:
            if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
                mon = m
                break
        shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    rel = (rc[0] - mon["left"], rc[1] - mon["top"], rc[2] - mon["left"], rc[3] - mon["top"])
    return img, rel


def region_looks_like(img, rect, colors, tol=6):
    """Какая доля пикселей в прямоугольнике совпадает с цветами окна (если окно попало в снимок — почти все)."""
    import numpy as np

    L, T, R, B = [int(v) for v in rect]
    L, T = max(0, L), max(0, T)
    R, B = min(img.width, R), min(img.height, B)
    if R - L < 4 or B - T < 4:
        return 0.0
    a = np.asarray(img.crop((L, T, R, B)), dtype=np.int16)
    hit = np.zeros(a.shape[:2], bool)
    for c in colors:
        c = c.lstrip("#")
        rgb = np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)
        hit |= (np.abs(a - rgb) <= tol).all(axis=2)
    return float(hit.mean())


# ---------------------------------------------------------------- один экземпляр программы

class SingleInstance:
    """Не даёт запустить вторую копию (две копии дрались бы за микрофон и клавиши).
    Вторая копия будит первую — та показывает окно."""

    def __init__(self, name):
        self.name = name
        self.handle = None
        self.already = False
        if not IS_WIN:
            return
        self.handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
        self.already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        self._events = {}
        if not self.already:
            # «звонки» создаём сразу: окно появляется только через 1–3 с, а вторую копию (двойной щелчок по
            # ярлыку) надо поймать и в это время — сигнал дождётся, пока окно будет готово
            for what in ("Show", "Quit"):
                self._events[what] = kernel32.CreateEventW(None, False, False, f"Local\\{name}.{what}")

    def release(self):
        """Перед перезапуском: новая копия не должна посчитать, что старая ещё работает."""
        if IS_WIN and self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def wake_other(self, wait=6.0):
        """Разбудить работающую копию; если она ещё запускается — подождать до wait секунд."""
        t_end = time.time() + wait
        while True:
            if self.signal("Show"):
                return True
            if time.time() > t_end:
                return False
            time.sleep(0.25)

    def signal(self, what):
        """Послать работающей копии сигнал ("Show" — показать окно, "Quit" — закрыться)."""
        if not IS_WIN:
            return False
        ev = kernel32.OpenEventW(0x0002, False, f"Local\\{self.name}.{what}")  # EVENT_MODIFY_STATE
        if not ev:
            return False
        kernel32.SetEvent(ev)
        kernel32.CloseHandle(ev)
        return True

    def on_wake(self, callback):
        """callback() вызывается (из отдельного потока), когда кто-то запустил вторую копию."""
        self.on_signal("Show", callback)

    def on_signal(self, what, callback):
        if not IS_WIN:
            return
        ev = self._events.get(what) or kernel32.CreateEventW(None, False, False, f"Local\\{self.name}.{what}")
        if not ev:
            return

        def wait():
            while True:
                if kernel32.WaitForSingleObject(ev, 0xFFFFFFFF) == 0:
                    try:
                        callback()
                    except Exception:
                        pass

        threading.Thread(target=wait, daemon=True, name="single-instance").start()


# ---------------------------------------------------------------- папки Windows, ярлыки, автозапуск

_FOLDERS = {
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Programs": "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",
    "Startup": "{B97D20BB-F46A-4C97-BA10-5E3608430854}",
}


def known_folder(name):
    """Настоящая папка «Рабочий стол» / «Пуск → Программы» / «Автозагрузка» (с учётом OneDrive и т. п.)."""
    if not IS_WIN:
        return os.path.expanduser("~")

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]

    guid = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(_FOLDERS[name]), ctypes.byref(guid))
    path = ctypes.c_wchar_p()
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wt.DWORD, wt.HANDLE,
                                             ctypes.POINTER(ctypes.c_wchar_p)]
    if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) != 0:
        fallback = {"Desktop": r"~\Desktop", "Programs": r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs",
                    "Startup": r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"}[name]
        return os.path.expanduser(fallback)
    value = path.value
    ole32.CoTaskMemFree(path)
    return value


def run_powershell(script, timeout=60):
    """Скрипт PowerShell без окна консоли. Текст передаётся закодированным — русские пути не ломаются."""
    import base64
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", enc], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, **NO_WINDOW)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def make_shortcut(lnk, target, args="", workdir="", icon="", desc=""):
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ws = New-Object -ComObject WScript.Shell; "
              f"$s = $ws.CreateShortcut({_ps_quote(lnk)}); $s.TargetPath = {_ps_quote(target)}; "
              f"$s.Arguments = {_ps_quote(args)}; $s.WorkingDirectory = {_ps_quote(workdir)}; "
              + (f"$s.IconLocation = {_ps_quote(icon)}; " if icon else "")
              + f"$s.Description = {_ps_quote(desc)}; $s.Save(); 'ok'")
    code, out = run_powershell(script)
    if code != 0 or not os.path.isfile(lnk):
        raise RuntimeError(out.strip()[-300:] or f"код {code}")
    return lnk


def read_shortcut(lnk):
    """→ (цель, аргументы) или None."""
    if not os.path.isfile(lnk):
        return None
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ws = New-Object -ComObject WScript.Shell; "
              f"$s = $ws.CreateShortcut({_ps_quote(lnk)}); $s.TargetPath; $s.Arguments")
    code, out = run_powershell(script)
    lines = out.splitlines()
    return (lines[0].strip() if lines else "", lines[1].strip() if len(lines) > 1 else "") if code == 0 else None


# ---------------------------------------------------------------- журнал

class _Tee:
    """Поток вывода: всё, что программа печатает, — в журнал (со временем) и в консоль, если она есть."""

    def __init__(self, f, console, lock):
        self.f, self.console, self.lock = f, console, lock
        self.at_line_start = True
        self.encoding = "utf-8"
        self.errors = "replace"

    def write(self, s):
        if not s:
            return 0
        with self.lock:
            try:
                out = []
                for part in s.splitlines(keepends=True):
                    if self.at_line_start:
                        out.append(time.strftime("%H:%M:%S "))
                    out.append(part)
                    self.at_line_start = part.endswith("\n")
                self.f.write("".join(out))
                self.f.flush()
            except Exception:
                pass
            if self.console is not None:
                try:
                    self.console.write(s)
                    self.console.flush()
                except Exception:
                    pass
        return len(s)

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        return self.f.fileno()

    def writable(self):
        return True


LOG_FILE = None


def setup_log(path, max_bytes=2_000_000):
    """Журнал в файл. Без консоли (pythonw) всё равно пишется: и сообщения программы, и ошибки библиотек."""
    global LOG_FILE
    import faulthandler
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
    except OSError:
        pass
    f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    LOG_FILE = f
    lock = threading.Lock()
    no_console = sys.__stdout__ is None or sys.__stderr__ is None
    sys.stdout = _Tee(f, sys.__stdout__, lock)
    sys.stderr = _Tee(f, sys.__stderr__, lock)
    if no_console and IS_WIN:
        try:  # сообщения библиотек на C (видеокарта, звук) — тоже в журнал
            os.dup2(f.fileno(), 2)
        except OSError:
            pass
    try:
        faulthandler.enable(file=f, all_threads=True)
    except Exception:
        pass

    def hook(exc_type, exc, tb):
        import traceback
        print("[ошибка] необработанная ошибка:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    print("=" * 20, "запуск", time.strftime("%Y-%m-%d"), "| Python", sys.version.split()[0],
          "| Windows сборка", windows_build(), "| консоль:", "нет" if no_console else "есть")
    return f


def open_path(path):
    """Открыть файл или папку обычной программой Windows (журнал — в Блокноте)."""
    if IS_WIN:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])
