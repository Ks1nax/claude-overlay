# -*- coding: utf-8 -*-
"""Установка и починка (мастер первого запуска и «Проверить и починить»): Claude Code, вход, конфликты настроек,
ярлыки и автозапуск. Файлы пользователя вне папки программы меняются только по его кнопке и всегда с резервной
копией. Ключи и токены нигде не показываются и не пишутся в журнал."""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from . import winsys
from .config import HERE, ICON_PATH, WORKDIR
from .winsys import IS_WIN, NO_WINDOW

APP_NAME = "Claude Overlay"
CONFLICT_KEYS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")


# ---------------------------------------------------------------- ярлыки и автозапуск

def venv_pythonw():
    pyw = os.path.join(HERE, ".venv", "Scripts", "pythonw.exe")
    if os.path.isfile(pyw):
        return pyw
    exe = sys.executable
    alt = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return alt if os.path.isfile(alt) else exe


def shortcut_path(place):
    return os.path.join(winsys.known_folder(place), APP_NAME + ".lnk")


def make_app_shortcuts(places=("Desktop", "Programs")):
    """Ярлыки «Claude Overlay»: запуск через pythonw — без чёрной консоли."""
    made = []
    for place in places:
        lnk = shortcut_path(place)
        winsys.make_shortcut(lnk, venv_pythonw(), '"' + os.path.join(HERE, "overlay.py") + '"', HERE,
                             ICON_PATH if os.path.isfile(ICON_PATH) else "",
                             "Голосовой помощник Claude поверх всех окон")
        made.append(lnk)
    return made


def shortcut_ok(place):
    """Ярлык есть и ведёт в эту папку (после переноса папки старый ярлык ведёт в никуда)."""
    lnk = shortcut_path(place)
    info = winsys.read_shortcut(lnk) if os.path.isfile(lnk) else None
    if not info:
        return False
    target, args = info
    return os.path.normcase(os.path.dirname(os.path.dirname(os.path.dirname(target)))) == os.path.normcase(HERE) \
        and "overlay.py" in args


def autostart_enabled():
    return os.path.isfile(shortcut_path("Startup"))


def set_autostart(flag):
    lnk = shortcut_path("Startup")
    if flag:
        make_app_shortcuts(("Startup",))
    elif os.path.isfile(lnk):
        os.remove(lnk)


def remove_shortcuts():
    removed = []
    for place in ("Desktop", "Programs", "Startup"):
        lnk = shortcut_path(place)
        if os.path.isfile(lnk):
            try:
                os.remove(lnk)
                removed.append(lnk)
            except OSError:
                pass
    return removed


# ---------------------------------------------------------------- Claude Code: поиск, сломанная копия, установка

def npm_claude_files():
    """Старая копия Claude Code из npm (%APPDATA%\\npm\\claude*): она перекрывала новую и ломала запуск
    («claude.exe не является действительным приложением»)."""
    if not IS_WIN:
        return []
    npm = os.path.join(os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming")), "npm")
    out = []
    for name in ("claude", "claude.cmd", "claude.ps1"):
        p = os.path.join(npm, name)
        if os.path.isfile(p):
            out.append(p)
    pkg = os.path.join(npm, "node_modules", "@anthropic-ai", "claude-code")
    if os.path.isdir(pkg):
        out.append(pkg)
    return out


def remove_npm_claude(report=print):
    """Убирает копию из npm: сначала штатно (npm uninstall), остатки — переименовывает в *.bak (не удаляет)."""
    npm = shutil.which("npm")
    if npm:
        report("Убираю старую копию: npm uninstall -g @anthropic-ai/claude-code …")
        try:
            r = subprocess.run([npm, "uninstall", "-g", "@anthropic-ai/claude-code"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300, **NO_WINDOW)
            report((r.stdout or r.stderr or "").strip()[-300:] or "готово")
        except Exception as e:
            report(f"npm не сработал: {e}")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for p in npm_claude_files():
        try:
            os.replace(p, p + f".bak-{stamp}")
            report(f"Переименовал в резервную копию: {p}.bak-{stamp}")
        except OSError as e:
            report(f"Не получилось убрать {p}: {e}")
    return not npm_claude_files()


def winget_path():
    w = shutil.which("winget")
    if w:
        return w
    p = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "winget.exe")
    return p if os.path.isfile(p) else None


_PROGRESS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(KB|MB|GB)\s*/\s*(\d+(?:[.,]\d+)?)\s*(KB|MB|GB)", re.I)
_PCT_RE = re.compile(r"(\d{1,3})\s*%")


def _stream(cmd, report, progress=None, timeout=1800, heartbeat=None):
    """Запускает команду без окна; построчно (и по \\r) отдаёт вывод. progress(доля 0…1) — если в выводе есть проценты.
    heartbeat(секунд прошло) — раз в секунду, если программа молчит дольше 2 с (установщик Claude Code минутами ничего не пишет)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **NO_WINDOW)
    t0 = time.time()
    last_out = [time.time()]
    stop = threading.Event()

    timed_out = []

    def beat():
        while not stop.wait(1.0):
            if time.time() - t0 > timeout:  # установщик завис и молчит — останавливаем его отсюда
                timed_out.append(True)
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            if heartbeat and time.time() - last_out[0] > 2.0:
                heartbeat(int(time.time() - t0))

    threading.Thread(target=beat, daemon=True).start()
    buf = b""
    try:
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch in (b"\r", b"\n"):
                line = buf.decode("utf-8", "replace").strip()
                buf = b""
                if not line:
                    continue
                last_out[0] = time.time()
                m = _PROGRESS_RE.search(line)
                if m and progress:
                    mult = {"kb": 1 / 1024, "mb": 1, "gb": 1024}
                    done = float(m.group(1).replace(",", ".")) * mult[m.group(2).lower()]
                    total = float(m.group(3).replace(",", ".")) * mult[m.group(4).lower()]
                    progress(done / total if total else 0, f"{done:.0f} из {total:.0f} МБ")
                    continue
                m = _PCT_RE.search(line)
                if m and progress and len(line) < 80 and not re.search(r"[a-zа-я]{4}", line, re.I):
                    progress(int(m.group(1)) / 100, f"{m.group(1)}%")
                    continue
                if re.fullmatch(r"[\s\-\\|/█▒▓░]+", line):  # спиннер и полоски
                    continue
                report(line)
            else:
                buf += ch
    finally:
        stop.set()
    if timed_out:
        report(f"Установка шла дольше {timeout // 60} мин — остановил. Попробуй ещё раз.")
    return proc.wait()


def install_claude(report, progress=None, heartbeat=None):
    """winget install Anthropic.ClaudeCode (виден прогресс); не вышло — официальный установщик с claude.ai."""
    wg = winget_path()
    if wg:
        report("Устанавливаю Claude Code через winget (официальный пакет Anthropic)…")
        code = _stream([wg, "install", "-e", "--id", "Anthropic.ClaudeCode", "--accept-package-agreements",
                        "--accept-source-agreements", "--disable-interactivity"], report, progress,
                       heartbeat=heartbeat)
        from .claude import find_claude
        if find_claude():
            return True
        report(f"winget закончил с кодом {code}, но Claude Code не нашёлся — пробую официальный установщик.")
    report("Устанавливаю Claude Code официальным установщиком с claude.ai (несколько минут без вывода — это нормально)…")
    _stream(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             "irm https://claude.ai/install.ps1 | iex"], report, progress, heartbeat=heartbeat)
    from .claude import find_claude
    return bool(find_claude())


def open_login_console(cli):
    """Отдельное окно с Claude Code для входа (/login). Оно видно — его можно закрыть после входа."""
    lines = ["chcp 65001 >nul", "cls",
             "echo ===============================================================",
             "echo   Вход в Claude Code",
             "echo   1. Ниже откроется Claude Code. Введи  /login  и нажми Enter.",
             "echo   2. Выбери вход аккаунтом claude.ai (подписка Pro или Max).",
             "echo   3. Войди в браузере, вернись сюда. Когда увидишь приглашение — окно можно закрыть.",
             "echo ===============================================================",
             "echo.", f'"{cli}"']
    script = os.path.join(WORKDIR, "login_claude.cmd")
    os.makedirs(os.path.dirname(script), exist_ok=True)
    with open(script, "w", encoding="utf-8") as f:
        f.write("@echo off\r\n" + "\r\n".join(lines) + "\r\n")
    from .claude import clean_env
    subprocess.Popen(["cmd", "/k", script], creationflags=0x00000010, env=clean_env(),  # CREATE_NEW_CONSOLE
                     cwd=os.path.expanduser("~"))


# ---------------------------------------------------------------- конфликты настроек

def claude_settings_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "settings.json")


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def find_conflicts(settings_path=None, registry=True):
    """Что мешает входу по подписке. Возвращает список {"where", "name", "kind", "text"} — без значений ключей."""
    out = []
    path = settings_path or claude_settings_path()
    data = _read_json(path) if os.path.isfile(path) else None
    if isinstance(data, dict):
        env = data.get("env") if isinstance(data.get("env"), dict) else {}
        for k in CONFLICT_KEYS:
            if k in env:
                out.append({"where": "settings", "name": k, "kind": _kind(k), "path": path,
                            "text": _explain(k, env.get(k), "в настройках Claude Code (settings.json)")})
        if data.get("apiKeyHelper"):
            out.append({"where": "settings", "name": "apiKeyHelper", "kind": "key", "path": path,
                        "text": "В настройках Claude Code задана программа, выдающая API-ключ (apiKeyHelper): "
                                "Claude Code платит по ключу, а не по подписке."})
    # Переменные среды Windows (пользователя и общие). Переменные только этого процесса не считаем:
    # оверлей и так не передаёт их Claude Code (clean_env), а в settings.json он читает их сам.
    for scope in (("user", "machine") if (IS_WIN and registry) else ()):
        for k in CONFLICT_KEYS:
            v = _reg_env(scope, k)
            if v is not None:
                out.append({"where": scope, "name": k, "kind": _kind(k),
                            "text": _explain(k, v, "в переменных среды Windows" +
                                             (" (для всех пользователей — нужны права администратора)"
                                              if scope == "machine" else ""))})
    return out


def _kind(k):
    return "url" if k == "ANTHROPIC_BASE_URL" else "model" if k == "ANTHROPIC_MODEL" else "key"


def _explain(k, value, where):
    if k == "ANTHROPIC_BASE_URL":
        host = re.sub(r"^\w+://", "", str(value or "")).split("/")[0]
        if "api.anthropic.com" in (value or ""):
            return f"Адрес сервера Claude задан {where} ({host}) — это официальный адрес, но с ним Claude Code " \
                   "может требовать ключ вместо подписки."
        return f"Claude Code отправляет запросы на чужой сервер ({host or 'неизвестный'}) — {where}. " \
               "Из-за этого вход по подписке не работает (ошибка «401 User not found»)."
    if k == "ANTHROPIC_MODEL":
        return f"Модель Claude Code жёстко задана {where} — оверлей сам выбирает модель, эта строка может мешать."
    return f"Ключ {k} задан {where} (значение скрыто) — с ним Claude Code платит по ключу, а не по подписке."


def _reg_env(scope, name):
    try:
        import winreg
        if scope == "user":
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        else:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
        with key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def backup_file(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak-{stamp}"
    shutil.copy2(path, bak)
    return bak


def fix_conflicts(items, report=print):
    """Убирает найденное: settings.json — с резервной копией; переменные пользователя — с резервной копией
    в %USERPROFILE%\\.claude\\env_backup_*.json; общие для всех — только объясняем (нужен администратор)."""
    ok = True
    by_path = {}
    for it in items:
        if it["where"] == "settings":
            by_path.setdefault(it["path"], []).append(it["name"])
    for path, names in by_path.items():
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        bak = backup_file(path)
        report(f"Резервная копия настроек Claude Code: {bak}")
        env = data.get("env") if isinstance(data.get("env"), dict) else {}
        for n in names:
            if n == "apiKeyHelper":
                data.pop("apiKeyHelper", None)
            else:
                env.pop(n, None)
            report(f"Убрал из settings.json: {n}")
        if "env" in data and not env:
            data.pop("env")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    user = [it["name"] for it in items if it["where"] == "user"]
    if user:
        backup = {n: _reg_env("user", n) for n in user}
        bdir = os.path.dirname(claude_settings_path())
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, f"env_backup_{time.strftime('%Y%m%d-%H%M%S')}.json")
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=1)
        report(f"Резервная копия переменных среды: {bpath}")
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
                for n in user:
                    winreg.DeleteValue(key, n)
                    os.environ.pop(n, None)
                    report(f"Убрал переменную среды: {n}")
            _broadcast_env_change()
        except OSError as e:
            ok = False
            report(f"Не получилось убрать переменные: {e}")
    machine = [it["name"] for it in items if it["where"] == "machine"]
    if machine:
        ok = False
        report("Переменные " + ", ".join(machine) + " заданы для всех пользователей компьютера — их может убрать "
               "только администратор: Пуск → «Изменение системных переменных среды» → «Переменные среды» → "
               "нижний список → выделить → «Удалить». Оверлей и так их не передаёт Claude Code.")
    return ok


def _broadcast_env_change():
    try:
        import ctypes
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000, ctypes.byref(res))
    except Exception:
        pass
