# -*- coding: utf-8 -*-
"""Мастер первого запуска (он же «Проверить и починить»): шаги с галочками, каждый можно повторить.
1 Claude Code · 2 конфликты настроек · 3 видеокарта · 4 модели распознавания · 5 микрофон и звук компьютера ·
6 клавиши · 7 ярлыки. Запускается из «Установить.bat» (python overlay.py --wizard) или из настроек."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

from . import stt, winsys
from .config import S, HERE, SETUP_STATE_PATH, ICON_PATH
from .hotkeys import HotkeyManager, ACTION_TITLES, display as key_display, problems as key_problems, parse_spec
from .ui_theme import (T, F, MONO, Button, Choice, Meter, ScrollFrame, ThinScroll, label, init_fonts, dark_title_bar,
                       hand, text_cursor)

STEPS = [
    ("claude", "Claude Code и вход"),
    ("conflicts", "Конфликты настроек"),
    ("gpu", "Видеокарта"),
    ("models", "Модели распознавания"),
    ("audio", "Микрофон и звук"),
    ("keys", "Клавиши"),
    ("shortcuts", "Ярлыки"),
]


def load_state():
    try:
        with open(SETUP_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(SETUP_STATE_PATH), exist_ok=True)
    with open(SETUP_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


class Wizard:
    def __init__(self, inst=None):
        self.inst = inst
        self.q = queue.Queue()
        self.state = load_state()
        self.marks = {k: self.state.get("done", {}).get(k) and "done" or "todo" for k, _ in STEPS}
        self.cur = None
        self.busy = set()
        self.cleanups = []

        r = self.root = tk.Tk()
        r.withdraw()
        r.title("Claude Overlay — установка и проверка")
        init_fonts(r)
        r.configure(bg=T["BG"])
        try:
            r.iconbitmap(ICON_PATH)
        except tk.TclError:
            pass
        r.geometry("1000x700")
        r.minsize(860, 600)
        r.protocol("WM_DELETE_WINDOW", self.close)
        self.guard = winsys.CaptureGuard(enabled=S.protect)
        self.guard.install()

        side = tk.Frame(r, bg=T["BG2"], width=260)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        head = tk.Frame(side, bg=T["BG2"])
        head.pack(fill="x", padx=18, pady=(20, 14))
        try:
            from PIL import Image, ImageTk
            from .config import ICON_PNG
            self._logo = ImageTk.PhotoImage(Image.open(ICON_PNG).resize((40, 40)))
            tk.Label(head, image=self._logo, bg=T["BG2"]).pack(side="left", padx=(0, 10))
        except Exception:
            pass
        box = tk.Frame(head, bg=T["BG2"])
        box.pack(side="left")
        label(box, "Claude Overlay", size=3, bold=True).pack(anchor="w")
        label(box, "установка и проверка", muted=True, size=-1).pack(anchor="w")
        self.step_items = {}
        for i, (key, title) in enumerate(STEPS, 1):
            it = tk.Frame(side, bg=T["BG2"], cursor=hand())
            it.pack(fill="x", padx=8, pady=1)
            mark = tk.Label(it, text="", bg=T["BG2"], font=F(1), width=2)
            mark.pack(side="left", padx=(8, 4), pady=7)
            txt = tk.Label(it, text=f"{i}. {title}", bg=T["BG2"], fg=T["MUTED"], font=F(0), anchor="w")
            txt.pack(side="left", fill="x", expand=True)
            for w in (it, mark, txt):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.step_items[key] = (it, mark, txt)
        it = tk.Frame(side, bg=T["BG2"], cursor=hand())
        it.pack(fill="x", padx=8, pady=(10, 1))
        txt = tk.Label(it, text="   ✦  Готово — запустить", bg=T["BG2"], fg=T["MUTED"], font=F(0), anchor="w")
        txt.pack(fill="x", pady=7)
        for w in (it, txt):
            w.bind("<Button-1>", lambda e: self.show("finish"))
        self.step_items["finish"] = (it, None, txt)
        label(side, "Каждый шаг можно открыть снова и повторить. Окно можно закрыть в любой момент — "
                    "сделанное сохранится.", muted=True, size=-2, wrap=220).pack(side="bottom", anchor="w",
                                                                                padx=18, pady=16)

        self.main = tk.Frame(r, bg=T["BG"])
        self.main.pack(side="left", fill="both", expand=True)
        self.page = None
        self.footer = tk.Frame(self.main, bg=T["BG"])
        self.footer.pack(side="bottom", fill="x", padx=20, pady=14)
        self.btn_next = Button(self.footer, "Далее", self.next, kind="primary")
        self.btn_next.pack(side="right")
        self.btn_back = Button(self.footer, "Назад", self.back)
        self.btn_back.pack(side="right", padx=8)

        self._paint_marks()
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry(f"+{(sw - 1000) // 2}+{max(0, (sh - 700) // 3)}")
        self.guard.protect_tk(r, tool=False)
        dark_title_bar(r)
        r.deiconify()
        self.guard.protect_tk(r, tool=False)
        first = next((k for k, _ in STEPS if self.marks[k] != "done"), "claude")
        self.show(first)
        self._tick()
        if self.inst is not None:
            self.inst.on_wake(lambda: self.later(lambda: (r.deiconify(), r.lift(), r.focus_force())))
        self._close_running_overlay()

    # ------------------------------------------------------------ каркас
    def later(self, fn):
        self.q.put(fn)

    def _tick(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.root.after(60, self._tick)

    def _close_running_overlay(self):
        """Работающий оверлей держит микрофон и клавиши — на время мастера просим его закрыться."""
        probe = winsys.SingleInstance("ClaudeOverlay")
        if probe.already and probe.signal("Quit"):
            self.overlay_was_running = True
            print("[мастер] попросил работающий оверлей закрыться на время настройки")
        else:
            self.overlay_was_running = False
        probe.release()

    def close(self):
        """Закрыли крестиком: если мастер открыт из оверлея (или закрыл работающий) — вернуть оверлей."""
        if not getattr(self, "launched", False) and (getattr(self, "overlay_was_running", False)
                                                     or "--from-overlay" in sys.argv):
            self.launch_overlay(close=False)
        for fn in self.cleanups:
            try:
                fn()
            except Exception:
                pass
        self.root.destroy()
        os._exit(0)

    def mark(self, key, status):
        """status: todo / done / warn / busy."""
        self.marks[key] = status
        done = self.state.setdefault("done", {})
        if status == "done":
            done[key] = time.strftime("%Y-%m-%d %H:%M")
        else:
            done.pop(key, None)
        save_state(self.state)
        self._paint_marks()

    def _paint_marks(self):
        sym = {"done": ("✓", T["OK"]), "warn": ("!", T["WARN"]), "busy": ("…", T["INFO"]), "todo": ("○", T["FAINT"])}
        for key, (it, mark, txt) in self.step_items.items():
            cur = key == self.cur
            bg = T["BG3"] if cur else T["BG2"]
            it.config(bg=bg)
            txt.config(bg=bg, fg=T["FG"] if cur else T["MUTED"])
            if mark is not None:
                s, c = sym[self.marks.get(key, "todo")]
                mark.config(text=s, fg=c, bg=bg)

    def show(self, key):
        for fn in self.cleanups:
            try:
                fn()
            except Exception:
                pass
        self.cleanups = []
        if self.page is not None:
            self.page.destroy()
        self.cur = key
        self._paint_marks()
        self.page = ScrollFrame(self.main, bg=T["BG"])
        self.page.pack(fill="both", expand=True)
        keys = [k for k, _ in STEPS] + ["finish"]
        i = keys.index(key)
        self.btn_back.set_enabled(i > 0)
        self.btn_next.set_text("Далее" if key != "finish" else "Запустить Claude Overlay")
        getattr(self, "_step_" + key)(self.page.body)

    def next(self):
        keys = [k for k, _ in STEPS] + ["finish"]
        i = keys.index(self.cur)
        if self.cur == "finish":
            self.launch_overlay()
        else:
            self.show(keys[i + 1])

    def back(self):
        keys = [k for k, _ in STEPS] + ["finish"]
        i = keys.index(self.cur)
        if i > 0:
            self.show(keys[i - 1])

    def header(self, p, num, title, text):
        label(p, f"Шаг {num} из {len(STEPS)}" if num else "", muted=True, size=-1).pack(anchor="w", padx=24,
                                                                                         pady=(20, 0))
        label(p, title, size=6, bold=True).pack(anchor="w", padx=24, pady=(0, 4))
        label(p, text, muted=True, wrap=660).pack(anchor="w", padx=24, pady=(0, 14))

    def panel(self, p):
        f = tk.Frame(p, bg=T["BG2"], highlightthickness=1, highlightbackground=T["BORDER"])
        f.pack(fill="x", padx=24, pady=(0, 12))
        inner = tk.Frame(f, bg=T["BG2"])
        inner.pack(fill="x", padx=16, pady=14)
        return inner

    def status_line(self, parent, ok, text):
        color = {True: T["OK"], False: T["ERR"], None: T["WARN"], "info": T["MUTED"]}[ok]
        sym = {True: "✓", False: "✕", None: "!", "info": "•"}[ok]
        r = tk.Frame(parent, bg=parent.cget("bg"))
        r.pack(fill="x", pady=2)
        tk.Label(r, text=sym, bg=parent.cget("bg"), fg=color, font=F(1, "bold"), width=2).pack(side="left",
                                                                                             anchor="n")
        tk.Label(r, text=text, bg=parent.cget("bg"), fg=T["FG"] if ok is not False else T["ERR"], font=F(0),
                 justify="left", anchor="w", wraplength=600).pack(side="left", fill="x")
        return r

    def log_box(self, parent, height=7):
        fr = tk.Frame(parent, bg=T["CODE_BG"])  # появляется, когда есть что показать
        t = tk.Text(fr, height=height, wrap="word", bg=T["CODE_BG"], fg=T["CODE_FG"], bd=0, highlightthickness=0,
                    font=MONO(-2), padx=8, pady=6, cursor=text_cursor())
        sb = ThinScroll(fr, t)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="x", expand=True)
        t.config(state="disabled")

        def add(line):
            def ui():
                try:
                    if not fr.winfo_ismapped():
                        fr.pack(fill="x", pady=(8, 0))
                    t.config(state="normal")
                    t.insert("end", line.rstrip() + "\n")
                    t.see("end")
                    t.config(state="disabled")
                except tk.TclError:
                    pass
            self.later(ui)
        return add

    def run_bg(self, name, fn):
        """Фоновая работа шага (одна на шаг): fn() в отдельном потоке."""
        if name in self.busy:
            return False
        self.busy.add(name)

        def work():
            try:
                fn()
            except Exception as e:
                import traceback
                print(f"[мастер] ошибка шага {name}:\n" + traceback.format_exc())
                self.later(lambda: self.mark(name, "warn"))
                self.later(lambda e=e: self._error_popup(name, e))
            finally:
                self.busy.discard(name)

        threading.Thread(target=work, daemon=True, name=f"wizard-{name}").start()
        return True

    def _error_popup(self, name, e):
        from tkinter import messagebox
        messagebox.showerror("Ошибка", f"Шаг не получился: {e}\nПодробности — в workspace\\overlay.log.",
                             parent=self.root)

    def refresh(self):
        self.show(self.cur)

    # ------------------------------------------------------------ шаг 1: Claude Code
    def _step_claude(self, p):
        from .claude import find_claude, claude_version
        from .setup_tools import npm_claude_files
        self.header(p, 1, "Claude Code и вход",
                    "Через Claude Code оверлей отвечает по твоей подписке Pro или Max — API-ключ не нужен. "
                    "Здесь проверим, что он установлен, не мешает старая копия и выполнен вход.")
        pan = self.panel(p)
        npm = npm_claude_files()
        cli = find_claude()
        if npm:
            self.status_line(pan, None, "Нашлась старая копия Claude Code, установленная через npm:\n"
                                        + "\n".join(npm) + "\nОна может перекрывать новую — тогда Claude Code не "
                                        "запускается («claude.exe не является действительным приложением»). "
                                        "Лучше её убрать (файлы переименуются в резервные копии).")
            Button(pan, "Убрать старую копию", lambda: self._remove_npm(log), kind="primary").pack(anchor="w",
                                                                                                    pady=6)
        if cli:
            self.status_line(pan, True, f"Claude Code установлен: {cli}")
            ver = label(pan, "версия: проверяю…", muted=True, size=-1)
            ver.pack(anchor="w", padx=28)
            self.run_bg("claude-ver", lambda: self.later(lambda: ver.config(text="версия: " + claude_version(cli))))
        else:
            self.status_line(pan, False, "Claude Code не найден.")
            label(pan, "Нажми «Установить» — поставлю официальный Claude Code от Anthropic через winget "
                       "(или установщиком с claude.ai). Устанавливая, ты принимаешь условия использования "
                       "Claude Code. Нужен интернет, 1–3 минуты.", muted=True, size=-1, wrap=620).pack(anchor="w",
                                                                                                pady=(4, 6))
            self.inst_prog = Meter(pan, width=420, height=8, color=T["ACCENT"])
            self.inst_prog.pack(anchor="w", pady=(0, 4))
            self.inst_state = label(pan, "", muted=True, size=-1)
            self.inst_state.pack(anchor="w")
            Button(pan, "Установить Claude Code", lambda: self._install_claude(log), kind="primary").pack(
                anchor="w", pady=6)
        log = self.log_box(pan, 5)

        pan2 = self.panel(p)
        label(pan2, "Вход в аккаунт", size=1, bold=True).pack(anchor="w")
        label(pan2, "1) «Открыть окно входа» — откроется чёрное окно с Claude Code. Введи там /login и войди "
                    "аккаунтом claude.ai (Pro или Max). 2) Вернись сюда и нажми «Проверить вход».",
              muted=True, wrap=620).pack(anchor="w", pady=(2, 8))
        b = tk.Frame(pan2, bg=T["BG2"])
        b.pack(anchor="w")
        Button(b, "Открыть окно входа", lambda: self._open_login(), kind="secondary").pack(side="left")
        Button(b, "Проверить вход", lambda: self._check_login(res), kind="primary").pack(side="left", padx=8)
        res = tk.Frame(pan2, bg=T["BG2"])
        res.pack(fill="x", pady=(8, 0))
        if self.marks["claude"] == "done":
            self.status_line(res, True, "Вход проверен раньше — всё работало. Можно проверить ещё раз.")

    def _remove_npm(self, log):
        from .setup_tools import remove_npm_claude

        def work():
            ok = remove_npm_claude(log)
            log("Готово." if ok else "Убрал не всё — подробности выше.")
            self.later(self.refresh)
        self.run_bg("npm", work)

    def _install_claude(self, log):
        from .setup_tools import install_claude
        self.mark("claude", "busy")

        def prog(frac, text):
            self.later(lambda: (self.inst_prog.set(frac), self.inst_state.config(text=text)))

        def beat(sec):
            self.later(lambda: self.inst_state.config(text=f"идёт установка… {sec} с (программа установки "
                                                           "может долго молчать — это нормально)"))

        def work():
            ok = install_claude(log, prog, beat)
            log("Claude Code установлен ✓" if ok else "Не получилось установить. Попробуй ещё раз или поставь вручную "
                                                      "командой в PowerShell: winget install Anthropic.ClaudeCode")
            self.later(lambda: self.mark("claude", "todo" if ok else "warn"))
            self.later(self.refresh)
        self.run_bg("claude-install", work)

    def _open_login(self):
        from .claude import find_claude
        from .setup_tools import open_login_console
        cli = find_claude()
        if not cli:
            from tkinter import messagebox
            messagebox.showwarning("Claude Code", "Сначала установи Claude Code (кнопка выше).", parent=self.root)
            return
        open_login_console(cli)

    def _check_login(self, res):
        from .claude import find_claude, check_login, explain_error
        for w in res.winfo_children():
            w.destroy()
        cli = find_claude()
        if not cli:
            self.status_line(res, False, "Claude Code не найден — сначала установи его.")
            return
        wait = self.status_line(res, "info", "Отправляю пробный вопрос Claude («ответь одним словом: ок»)…")
        self.mark("claude", "busy")

        def work():
            ok, msg = check_login(cli)

            def ui():
                wait.destroy()
                if ok:
                    self.status_line(res, True, f"Всё работает: Claude ответил «{msg[:40]}». Подписка подключена.")
                    self.mark("claude", "done")
                else:
                    self.status_line(res, False, f"Не работает: {msg[:300]}")
                    hint = explain_error(msg)
                    if hint:
                        self.status_line(res, None, hint)
                    self.mark("claude", "warn")
            self.later(ui)
        self.run_bg("login", work)

    # ------------------------------------------------------------ шаг 2: конфликты
    def _step_conflicts(self, p):
        from .setup_tools import find_conflicts, claude_settings_path
        self.header(p, 2, "Конфликты настроек",
                    "Иногда в настройках Claude Code или в переменных среды Windows остаются чужой адрес сервера "
                    "или ключ (например, от других программ). Тогда Claude Code идёт не в твою подписку, а мимо неё "
                    "— и выдаёт ошибку «401 User not found». Значения ключей здесь не показываются.")
        pan = self.panel(p)
        items = find_conflicts()
        if not items:
            self.status_line(pan, True, "Конфликтов нет: ни в " + claude_settings_path() +
                             ", ни в переменных среды нет чужих адресов и ключей.")
            self.mark("conflicts", "done")
            return
        for it in items:
            self.status_line(pan, None, it["text"])
        fixable = [it for it in items if it["where"] in ("settings", "user")]
        if fixable:
            label(pan, "«Убрать» — удалю эти строки и переменные. Перед этим сохраню резервную копию "
                       "(settings.json.bak-… и env_backup_….json в папке .claude).", muted=True, size=-1,
                  wrap=620).pack(anchor="w", pady=(8, 4))
            Button(pan, "Убрать (с резервной копией)", lambda: self._fix_conflicts(fixable, log),
                   kind="primary").pack(anchor="w", pady=4)
        log = self.log_box(pan, 5)
        self.mark("conflicts", "warn")

    def _fix_conflicts(self, items, log):
        from .setup_tools import fix_conflicts

        def work():
            fix_conflicts(items, log)
            self.later(lambda: self.root.after(1200, self.refresh))
        self.run_bg("conflicts", work)

    # ------------------------------------------------------------ шаг 3: видеокарта
    def _step_gpu(self, p):
        self.header(p, 3, "Видеокарта",
                    "С видеокартой NVIDIA распознавание речи в разы быстрее и можно брать самую точную модель. "
                    "Без неё всё тоже работает — на процессоре, просто медленнее.")
        pan = self.panel(p)
        hw = stt.hardware_info(refresh=True)
        if hw["gpu"]:
            self.status_line(pan, "info", f"Нашёл видеокарту: {hw['gpu']} ({hw['vram_mb'] / 1024:.0f} ГБ памяти)."
                             .replace(".0 ГБ", " ГБ"))
        else:
            self.status_line(pan, "info", "Видеокарты NVIDIA нет — распознавание будет на процессоре "
                                          f"({hw['cores']} потоков). Этот шаг можно пропустить.")
            self.mark("gpu", "done")
            return
        st = tk.Frame(pan, bg=T["BG2"])
        st.pack(fill="x")
        if os.path.isfile(stt.GPU_OK):
            self.status_line(st, True, "Готово: распознавание работает на видеокарте.")
            self.mark("gpu", "done")
        elif os.path.isfile(stt.GPU_FAIL):
            self.status_line(st, None, "Раньше видеокарта не заработала — распознавание на процессоре. "
                                       "Если обновил драйвер NVIDIA — нажми «Проверить заново».")
        else:
            self.status_line(st, "info", "Нужно один раз докачать библиотеки CUDA (0,7–1,2 ГБ) и проверить работу.")
        self.gpu_prog = Meter(pan, width=420, height=8, color=T["ACCENT"])
        self.gpu_prog.pack(anchor="w", pady=(8, 2))
        self.gpu_state = label(pan, "", muted=True, size=-1)
        self.gpu_state.pack(anchor="w")
        b = tk.Frame(pan, bg=T["BG2"])
        b.pack(anchor="w", pady=6)
        Button(b, "Настроить видеокарту", lambda: self._setup_gpu(log, False), kind="primary").pack(side="left")
        Button(b, "Проверить заново", lambda: self._setup_gpu(log, True)).pack(side="left", padx=8)
        log = self.log_box(pan, 8)

    def _setup_gpu(self, log, force):
        self.mark("gpu", "busy")
        import re as _re

        def report(line):
            m = _re.search(r"Progress (\d+) of (\d+)", line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                self.later(lambda: (self.gpu_prog.set(done / total if total else 0),
                                    self.gpu_state.config(text=f"качаю: {stt.fmt_size(done)} из {stt.fmt_size(total)}")))
                return
            if line.startswith("[видеокарта]"):
                self.later(lambda: self.gpu_state.config(text=line.replace("[видеокарта] ", "")))
            log(line)

        def work():
            res = stt.setup_gpu(report, force=force)
            self.later(lambda: self.mark("gpu", "done" if res in ("ok", "cpu") else "warn"))
            self.later(lambda: self.root.after(800, self.refresh))
        self.run_bg("gpu", work)

    # ------------------------------------------------------------ шаг 4: модели
    def _step_models(self, p):
        self.header(p, 4, "Модели распознавания",
                    "Модели распознают речь прямо на компьютере. Для команд «Клод, …» хватит небольшой, для вопросов "
                    "со звука компьютера (F7) лучше точная. Отмечены рекомендованные для этого компьютера. "
                    "Скачивание можно прервать — продолжится с того же места.")
        hw = stt.hardware_info()
        rec = stt.recommend(hw)
        pan = self.panel(p)
        self.status_line(pan, "info", f"Совет: для команд — {rec['mic']}, для F7 — {rec['listen']} ({rec['why']}).")
        mic_opts = [(n, f"{n} · {stt.model_meta(n)['accuracy']}") for n in stt.MODEL_NAMES]
        cur_listen = S.listen_whisper_model if S.listen_whisper_model != "auto" else rec["listen"]
        r = tk.Frame(pan, bg=T["BG2"])
        r.pack(fill="x", pady=(8, 2))
        label(r, "Для команд с микрофона:", width=26).pack(side="left")
        self.wz_mic = Choice(r, mic_opts, S.whisper_model, lambda v: self._models_status(), width=34)
        self.wz_mic.pack(side="left")
        r = tk.Frame(pan, bg=T["BG2"])
        r.pack(fill="x", pady=2)
        label(r, "Для звука компьютера (F7):", width=26).pack(side="left")
        self.wz_listen = Choice(r, mic_opts, cur_listen, lambda v: self._models_status(), width=34)
        self.wz_listen.pack(side="left")
        self.dl_rows = tk.Frame(pan, bg=T["BG2"])
        self.dl_rows.pack(fill="x", pady=(10, 0))
        b = tk.Frame(pan, bg=T["BG2"])
        b.pack(anchor="w", pady=8)
        Button(b, "Скачать и выбрать", self._download_models, kind="primary", icon="download").pack(side="left")
        label(b, "  Все модели и подробности — потом в ⚙ → Распознавание речи.", muted=True, size=-1).pack(
            side="left")
        threading.Thread(target=lambda: (stt.remote_sizes(), self.later(self._models_status)), daemon=True).start()
        self._models_status()

    def _models_status(self):
        if not hasattr(self, "dl_rows"):
            return
        try:
            for w in self.dl_rows.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        names = list(dict.fromkeys([self.wz_mic.value(), self.wz_listen.value()]))
        self.dl_widgets = {}
        all_ok = True
        for n in names:
            r = tk.Frame(self.dl_rows, bg=T["BG3"])
            r.pack(fill="x", pady=2)
            cached = stt.model_cached(n)
            all_ok &= cached
            tk.Label(r, text=n, bg=T["BG3"], fg=T["FG"], font=F(0, "bold"), width=16, anchor="w").pack(side="left",
                                                                                                     padx=10, pady=6)
            st = tk.Label(r, text=("✓ скачана · " + stt.fmt_size(stt.model_disk_size(n))) if cached else
                          f"не скачана · {stt.fmt_size(stt.model_size_bytes(n))}", bg=T["BG3"],
                          fg=T["OK"] if cached else T["MUTED"], font=F(-1), anchor="w")
            st.pack(side="left")
            m = Meter(r, width=200, height=6, color=T["ACCENT"])
            if not cached:
                m.pack(side="right", padx=10)
            self.dl_widgets[n] = (st, m)
        if all_ok and S.whisper_model == self.wz_mic.value():
            self.mark("models", "done")

    def _download_models(self):
        mic, listen = self.wz_mic.value(), self.wz_listen.value()
        rec = stt.recommend()
        S.update(whisper_model=mic,
                 listen_whisper_model="auto" if listen == rec["listen"] else listen)
        self._models_status()
        self.mark("models", "busy")
        names = list(dict.fromkeys([mic, listen]))

        def work():
            ok = True
            for n in names:
                if stt.model_cached(n):
                    continue
                st, m = self.dl_widgets.get(n, (None, None))

                def report(pr, st=st, m=m):
                    self.later(lambda: (m.set(pr.get("pct", 0) / 100),
                                        st.config(text="⬇ " + (pr.get("text") or "готово"), fg=T["WARN"])))
                try:
                    stt.download_with_progress(n, report)
                except Exception as e:
                    ok = False
                    self.later(lambda e=e, st=st: st.config(text=f"не скачалась: {stt.short_err(e)} — нажми ещё раз, "
                                                                 "продолжит с того же места", fg=T["ERR"]))
            self.later(lambda: self.mark("models", "done" if ok else "warn"))
            self.later(self._models_status)
        self.run_bg("models", work)

    # ------------------------------------------------------------ шаг 5: микрофон и звук компьютера
    def _step_audio(self, p):
        from .audio import list_input_devices, level_fraction, SystemAudio, Listener
        self.header(p, 5, "Микрофон и звук компьютера",
                    "Проверим, что оверлей слышит тебя (команды «Клод, …») и звук компьютера (вопросы с лекции или "
                    "созвона по F7).")
        pan = self.panel(p)
        label(pan, "Микрофон", size=1, bold=True).pack(anchor="w")
        names = list_input_devices()
        r = tk.Frame(pan, bg=T["BG2"])
        r.pack(fill="x", pady=4)
        Choice(r, [("", "Как в Windows (по умолчанию)")] + [(n, n) for n in names], S.mic_device,
               lambda v: (S.update(mic_device=v), self.refresh()), width=46).pack(side="left")
        mic_meter = Meter(pan, width=420, height=10)
        mic_meter.pack(anchor="w", pady=4)
        self.mic_result = tk.Frame(pan, bg=T["BG2"])
        self.mic_result.pack(fill="x")
        self.status_line(self.mic_result, "info", "Скажи вслух: «Клод, привет» — распознаю и покажу, что услышал.")

        ui_q = queue.Queue()
        lst = Listener(queue.Queue(), ui_q)
        lst.tap = lambda audio: self._mic_test(audio)
        lst.start()
        self.cleanups.append(lst.stop)

        pan2 = self.panel(p)
        label(pan2, "Звук компьютера", size=1, bold=True).pack(anchor="w")
        label(pan2, "Включи любое видео или музыку — полоска устройства, в которое идёт звук, задвигается.",
              muted=True, wrap=620).pack(anchor="w", pady=(2, 6))
        dev_box = tk.Frame(pan2, bg=T["BG2"])
        dev_box.pack(fill="x")
        self.sys_result = label(pan2, "", size=0)
        self.sys_result.pack(anchor="w", pady=(6, 0))
        sa = SystemAudio(ui_q)
        sa.start()
        self.cleanups.append(sa.close)
        meters = {}
        heard = {"mic": False, "sys": False}

        def tick():
            if self.cur != "audio":
                return
            try:
                while True:
                    m = ui_q.get_nowait()
                    if m[0] == "mic_error":
                        self.status_line(self.mic_result, False, m[1])
            except queue.Empty:
                pass
            try:
                mic_meter.set(level_fraction(lst.level))
                levels = sa.device_levels()
                for i, (n, lv) in enumerate(levels):
                    if n not in meters:
                        row_ = tk.Frame(dev_box, bg=T["BG2"])
                        row_.pack(fill="x", pady=1)
                        tk.Label(row_, text=n[:50], bg=T["BG2"], fg=T["FG"], font=F(-2), width=46,
                                 anchor="w").pack(side="left")
                        mm = Meter(row_, width=200, height=8)
                        mm.pack(side="left")
                        meters[n] = mm
                    meters[n].set(level_fraction(lv))
                    if lv > 0.01 and not heard["sys"]:
                        heard["sys"] = True
                        self.sys_result.config(text=f"✓ Звук компьютера слышен: {n}", fg=T["OK"])
                        if self.marks.get("audio") != "done" and heard["mic"]:
                            self.mark("audio", "done")
                if sa.state == "error":
                    self.sys_result.config(text="✕ " + sa.error, fg=T["ERR"])
            except tk.TclError:
                return
            self.root.after(100, tick)

        self._audio_heard = heard
        tick()

    def _mic_test(self, audio):
        """Фраза с микрофона (из потока звука) → распознаём маленькой моделью в фоне."""
        if "mictest" in self.busy:
            return

        def work():
            from .textfmt import split_wake
            self.later(lambda: self._mic_line("info", "Распознаю…"))
            name = S.whisper_model if stt.model_cached(S.whisper_model) else next(
                (n for n in ("small", "base", "tiny", "medium") if stt.model_cached(n)), None)
            if not name:
                self.later(lambda: self._mic_line(None, "Нет скачанной модели распознавания — сначала шаг 4."))
                return
            if not hasattr(self, "_test_model") or self._test_model[0] != name:
                self._test_model = (name, stt.load_whisper(name, stt.whisper_device())[0])
            segs, _ = self._test_model[1].transcribe(audio, language=None if S.language == "auto" else S.language,
                                                     beam_size=5, vad_filter=True,
                                                     initial_prompt=stt.WAKE_PROMPT)
            text = " ".join(s.text.strip() for s in segs).strip()
            woke = split_wake(text) is not None if text else False

            def ui():
                if not text:
                    self._mic_line(None, "Ничего не разобрал — скажи ещё раз чуть громче.")
                elif woke:
                    self._mic_line(True, f"Услышал: «{text}» — слово «Клод» узнаю ✓")
                    self._audio_heard["mic"] = True
                    if self._audio_heard["sys"]:
                        self.mark("audio", "done")
                else:
                    self._mic_line(None, f"Услышал: «{text}» — но «Клод» не узнал. Попробуй ещё раз; если не выходит "
                                         "— добавь, как он слышит «Клод», в ⚙ → Звук → «Слова-обращения».")
            self.later(ui)
        self.run_bg("mictest", work)

    def _mic_line(self, ok, text):
        try:
            for w in self.mic_result.winfo_children():
                w.destroy()
            self.status_line(self.mic_result, ok, text)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ шаг 6: клавиши
    def _step_keys(self, p):
        self.header(p, 6, "Клавиши",
                    "Клавиши работают в любой программе. Пока оверлей запущен, они не доходят до других программ "
                    "(например, F7 не включит «режим каретки» в браузере). Можно назначить свои: нажми «Назначить» "
                    "и потом нужную клавишу (можно с Ctrl/Alt/Shift).")
        pan = self.panel(p)
        if not hasattr(self, "hk"):
            self.hk = HotkeyManager(lambda ev: None)
            self.hk.start({})
        self.key_lbls = {}
        for action, skey in (("listen", "hotkey_listen"), ("talk", "hotkey_talk"), ("toggle", "hotkey_toggle")):
            r = tk.Frame(pan, bg=T["BG2"])
            r.pack(fill="x", pady=4)
            label(r, ACTION_TITLES[action], width=44).pack(side="left")
            lbl = tk.Label(r, text=key_display(S.get(skey)), bg=T["BG3"], fg=T["FG"], font=F(1, "bold"), width=12,
                           pady=4)
            lbl.pack(side="left", padx=6)
            Button(r, "Назначить…", lambda a=action, k=skey: self._capture(k), small=True).pack(side="left")
            self.key_lbls[skey] = lbl
        self.key_warn = label(pan, "", size=-1, wrap=620)
        self.key_warn.pack(anchor="w", pady=(8, 0))
        self._key_warn()
        self.mark("keys", "done")

    def _capture(self, skey):
        lbl = self.key_lbls[skey]
        lbl.config(text="нажми…", fg=T["WARN"])

        def got(spec):
            def ui():
                if spec:
                    trial = {"listen": S.hotkey_listen, "talk": S.hotkey_talk, "toggle": S.hotkey_toggle}
                    trial[{"hotkey_listen": "listen", "hotkey_talk": "talk", "hotkey_toggle": "toggle"}[skey]] = spec
                    bad = [w for w in key_problems(trial) if "нельзя" in w or "дважды" in w]
                    if parse_spec(spec) and not bad:
                        S.update(**{skey: spec})
                    else:
                        self.key_warn.config(text="Не назначено: " + " ".join(bad), fg=T["ERR"])
                        lbl.config(text=key_display(S.get(skey)), fg=T["FG"])
                        return
                lbl.config(text=key_display(S.get(skey)), fg=T["FG"])
                self._key_warn()
            self.later(ui)
        self.hk.capture_next(got)

    def _key_warn(self):
        warn = key_problems({"listen": S.hotkey_listen, "talk": S.hotkey_talk, "toggle": S.hotkey_toggle})
        self.key_warn.config(text="\n".join("⚠ " + w for w in warn) if warn else "✓ Конфликтов нет.",
                             fg=T["WARN"] if warn else T["OK"])

    # ------------------------------------------------------------ шаг 7: ярлыки
    def _step_shortcuts(self, p):
        from .setup_tools import shortcut_ok, autostart_enabled
        self.header(p, 7, "Ярлыки",
                    "Ярлык «Claude Overlay» запускает оверлей без чёрного окна консоли. Запуск вместе с Windows — "
                    "по желанию (по умолчанию выключен).")
        pan = self.panel(p)
        self.sc_vars = {}
        for place, title, default in (("Desktop", "На рабочем столе", True), ("Programs", "В меню «Пуск»", True),
                                      ("Startup", "Запускать вместе с Windows", autostart_enabled())):
            exists = shortcut_ok(place) if place != "Startup" else autostart_enabled()
            v = tk.BooleanVar(value=exists or (default and place != "Startup"))
            tk.Checkbutton(pan, text=title + ("  (уже есть)" if exists else ""), variable=v, bg=T["BG2"], fg=T["FG"],
                           selectcolor=T["BG3"], activebackground=T["BG2"], activeforeground=T["FG"], font=F(0),
                           cursor=hand()).pack(anchor="w", pady=2)
            self.sc_vars[place] = v
        res = tk.Frame(pan, bg=T["BG2"])
        Button(pan, "Создать ярлыки", lambda: self._make_shortcuts(res), kind="primary").pack(anchor="w", pady=8)
        res.pack(fill="x")
        if shortcut_ok("Desktop") or shortcut_ok("Programs"):
            self.mark("shortcuts", "done")

    def _make_shortcuts(self, res):
        from .setup_tools import make_app_shortcuts, shortcut_path
        for w in res.winfo_children():
            w.destroy()
        want = [p for p in ("Desktop", "Programs") if self.sc_vars[p].get()]
        try:
            made = make_app_shortcuts(want)
            for p in ("Desktop", "Programs"):
                if not self.sc_vars[p].get() and os.path.isfile(shortcut_path(p)):
                    os.remove(shortcut_path(p))
            from .setup_tools import set_autostart
            set_autostart(self.sc_vars["Startup"].get())
            for m in made:
                self.status_line(res, True, f"Ярлык: {m}")
            if self.sc_vars["Startup"].get():
                self.status_line(res, True, "Оверлей будет запускаться вместе с Windows.")
            self.mark("shortcuts", "done")
        except Exception as e:
            self.status_line(res, False, f"Не получилось создать ярлык: {e}")
            self.mark("shortcuts", "warn")

    # ------------------------------------------------------------ финиш
    def _step_finish(self, p):
        self.header(p, 0, "Готово", "Можно запускать. Этот мастер всегда можно открыть снова: ⚙ → «Невидимость и "
                                    "система» → «Проверить и починить».")
        pan = self.panel(p)
        for key, title in STEPS:
            m = self.marks.get(key)
            self.status_line(pan, True if m == "done" else None,
                             title + ("" if m == "done" else " — не завершено (можно вернуться к шагу)"))
        pan2 = self.panel(p)
        label(pan2, "Как пользоваться", size=1, bold=True).pack(anchor="w")
        label(pan2, f"• Скажи «Клод, …» и вопрос — сделаю скриншот и отвечу.\n"
                    f"• {key_display(S.hotkey_listen)} — в начале вопроса со звука компьютера (лекция, созвон), "
                    f"{key_display(S.hotkey_listen)} ещё раз — в конце.\n"
                    "• 📎 / 📋 — прикрепить материалы (лекции, конспекты, вопросы).\n"
                    "• Окно не видно на демонстрации экрана — внизу окна надпись «🛡 Скрыт от демонстрации».",
              wrap=620).pack(anchor="w", pady=(4, 0))

    def launch_overlay(self, close=True):
        from .setup_tools import venv_pythonw
        self.launched = True
        for fn in self.cleanups:
            try:
                fn()
            except Exception:
                pass
        if self.inst is not None:
            self.inst.release()
        subprocess.Popen([venv_pythonw(), os.path.join(HERE, "overlay.py")], cwd=HERE, **winsys.NO_WINDOW)
        print("[мастер] запустил оверлей")
        if close:
            self.root.after(300, self.close)

    def run(self):
        self.root.mainloop()


def run_wizard(inst=None):
    Wizard(inst).run()
