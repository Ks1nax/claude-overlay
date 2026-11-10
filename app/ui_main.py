# -*- coding: utf-8 -*-
"""Главное окно оверлея: интерфейс — на движке Edge (app/web, app/webwin.py), логика — здесь.

Потоки: главный поток — цикл окна pywebview; поток «logic» — эта логика + служебные окна Tk (настройки, выделение
куска экрана; корень Tk скрыт). Все остальные потоки общаются с логикой только через очередь ui_q (_poll каждые 30 мс),
окно получает события через self.web.send(...)."""

import base64
import io
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

from . import winsys
from .audio import Listener, SystemAudio, prepare_audio, level_fraction, save_wav
from .claude import ClaudeSession, cli_ask, api_ask, explain_error, find_claude
from .config import S, WORKDIR, HERE, LAST_F7_WAV, SETUP_STATE_PATH, load_api_key
from .hotkeys import HotkeyManager, display as key_display, ACTIONS as HK_ACTIONS, current_binds
from .materials import Materials, extract_material, material_terms
from .prompts import system_prompt, listen_prompt, analyze_prompt, MATERIALS_INTRO, FILE_IMAGE_RULE
from .screen import grab_screen, encode_image
from . import stt
from . import providers
from . import history
from .textfmt import last_code_block, split_wake, is_junk
from .ui_theme import T, THEMES, THEME_NAMES, init_fonts, apply_theme

BRAND = "Claude Overlay"
CSS_KEYS = {"BG": "bg", "BG2": "bg2", "BG3": "bg3", "BG4": "bg4", "FG": "fg", "MUTED": "muted", "FAINT": "faint",
            "ACCENT": "accent", "ACCENT2": "accent2", "CODE_BG": "code-bg", "CODE_FG": "code-fg", "IC_FG": "ic",
            "ERR": "err", "OK": "ok", "WARN": "warn", "INFO": "info", "BORDER": "border", "SEL": "sel",
            "PURPLE": "purple", "TEAL": "teal", "REC": "rec", "Q_BG": "qbg"}
QUICK = {"Короче": "Скажи то же самое короче — одной-двумя фразами.",
         "Подробнее": "Объясни подробнее, по шагам.",
         "Объясни проще": "Объясни проще, как будто я только начал изучать тему.",
         "Пример": "Приведи понятный пример."}


def theme_vars(theme):
    out = {css: theme[k] for k, css in CSS_KEYS.items()}
    out["on-accent"] = "#1a0f0b" if theme.get("DARK_TITLE") else "#fffaf6"
    return out


def data_url(img, side, quality=82):
    from PIL import Image
    im = img.copy()
    im.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def mat_icon(title):
    t = title.lower()
    if t.endswith(".pdf"):
        return "picture_as_pdf"
    if t.endswith((".doc", ".docx", ".rtf")):
        return "description"
    if t.endswith((".ppt", ".pptx")):
        return "slideshow"
    if t.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
        return "image"
    return "notes"


class App:
    def __init__(self, inst=None, web=None):
        self.inst = inst
        self.ui_q = queue.Queue()
        self.audio_q = queue.Queue()

        self.history = []
        self.rid = 0
        self.ans_no = 0
        self.busy = False
        self.cancel_ev = None
        self.cur_question = ""
        self.cur_answer = ""
        self.last_answer = ""
        self.dirty = False
        self.last_render = 0.0
        self.followup_until = 0.0
        self.forced_until = 0.0
        self.ready = False
        self.fatal = False
        self.visible = True
        self.compact = bool(S.compact)
        self.expanded_for_answer = False
        self.mic_on = False
        self.stt_on = False
        self.state = ("loading", "Запуск…")
        self.math_cache = {}                    # (для совместимости с окном настроек)
        self.error_hint = ""
        self.pending_shot = None
        self.shots = {}                         # номер ответа → скриншот (для увеличения по щелчку)
        self.next_source = "voice"
        self.next_icon = None
        self._status_last = None
        self._rec_shown = False
        self._quitting = False

        # вопросы со звука компьютера (F7)
        self.models = stt.Models()
        self.listen_pause = threading.Event()  # пока пишем/распознаём вопрос — фразы с микрофона не распознаём
        self.sysaudio = None
        self.listen_tr = None
        self.listen_session = None
        self.rec = None                         # идёт запись: {"id", "t0", "press"}
        self.listen_jobs = {}                   # id → задание, которое дослушиваем или распознаём
        self.listen_seq = 0
        self.listen_model_state = ("loading", "")
        self.mic_model_info = ""
        self.download_info = ""
        self.via_listen = False
        self.cur_is_listen = False
        self._sys_announced = False
        self._sys_err_shown = False
        self.last_f7_audio = None

        self.client = None
        self.cli = None
        self.provider = None
        self.session_id = None
        self.session_gen = 0
        self.proc = None
        self.shot_no = 0
        self.materials = Materials()
        self.api_system = ""
        self.attach_busy = 0
        self.settings_win = None
        self.help_win = None
        self.history_win = None
        self.tray = None
        self.listener = None
        self.transcriber = None
        self.root = None
        self.guard = None
        self._logic_ready = threading.Event()

        if web is None:
            from .webwin import WebWindow
            web = WebWindow(self)
        self.web = web

    # ------------------------------------------------------------ запуск
    def run(self):
        """Логика — в своём потоке, окно — в главном (так требует движок окна)."""
        threading.Thread(target=self._logic_main, daemon=True, name="logic").start()
        self._logic_ready.wait(30)
        try:
            self.web.start()
        finally:
            self._quit()

    def _logic_main(self):
        try:
            self._setup()
        except Exception:
            import traceback
            print("[ошибка] запуск:\n" + traceback.format_exc())
            self._logic_ready.set()
            raise
        self._logic_ready.set()
        self.root.mainloop()

    def _setup(self):
        """Всё, что раньше было в __init__: служебный корень Tk, невидимость, звук, распознавание, клавиши."""
        r = self.root = tk.Tk()
        r.withdraw()          # корень Tk не показывается: он нужен только для окон настроек и выделения куска экрана
        r.title(BRAND + " · служебное")
        init_fonts(r)
        r.report_callback_exception = self._tk_error
        # Невидимость на демонстрации экрана: хук защищает каждое новое окно программы в момент создания —
        # и главное окно (его создаёт поток окна уже после этого), и окна настроек, и окна выбора файлов
        from .webwin import is_main_window
        self.guard = winsys.CaptureGuard(enabled=S.protect)
        self.guard.tool_check = is_main_window
        self.guard.install()

        backend_ok, problem = self._init_backend()
        self._write_prompts()
        print("[запуск] режим:", self._mode_name() if backend_ok else "не настроен")
        if not backend_ok:
            self._write([(problem + "\n", ("err",))])
        if S.load_error:
            self._write([("⚠ " + S.load_error + "\n", ("err",))])
        if self.materials.items:
            print("[материалы] с прошлого раза:", self.materials.summary())

        self.transcriber = stt.Transcriber(self.audio_q, self.ui_q, self.models, self.listen_pause)
        self.transcriber.start()
        self.listener = Listener(self.audio_q, self.ui_q)
        self.listener.start()
        self.listen_tr = stt.ListenTranscriber(self.ui_q, self.models)
        self.listen_tr.hotwords = self._hotwords()
        self.listen_tr.start()
        self.sysaudio = SystemAudio(self.ui_q)
        self.sysaudio.start()
        self.hk = HotkeyManager(lambda ev: self.ui_q.put((ev,)), esc_active=lambda: self.rec is not None)
        self.hk.start(self._hotkey_actions())
        if S.tray:
            self._start_tray()
        S.on_change(lambda changed: self.ui_q.put(("settings_changed", changed)))
        r.after(30, self._poll)
        r.after(1500, self._refresh_shield)

    def web_ready(self):
        """Страница окна загрузилась (или перезагрузилась): всё состояние — заново."""
        w = self.web
        w.send("init", self._init_payload(), key="init")
        self._place_window()
        if self.compact:
            self._apply_compact()
        self._update_mat_bar()
        self._status_last = None
        self._refresh_status()
        self._shield_last = None
        self._refresh_shield(again=False)
        if self.pending_shot is not None:
            self.set_pending_shot(self.pending_shot)
        w.mark_ready()

    def _init_payload(self):
        return {"brand": BRAND, "theme": self._theme_payload(), "fs": self._fs()["fs"], "hotkeys": self._hotkey_labels(),
                "mode": self._mode_payload(), "protect": bool(S.protect), "math": bool(S.math_render),
                "alpha": float(S.alpha), "ghost": bool(S.ghost), "ghost_fade": float(S.ghost_fade), "glass": False, "text_input": bool(S.text_input),
                "compact": self.compact and not self.expanded_for_answer,
                "themes": {k: {"name": THEME_NAMES.get(k, k), "bg": v["BG"], "accent": v["ACCENT"]} for k, v in THEMES.items()}}

    @staticmethod
    def _fs():
        return {"fs": round(float(S.font_size) * 4 / 3)}

    @staticmethod
    def _theme_payload():
        return {"name": S.theme, "vars": theme_vars(T)}

    @staticmethod
    def _hotkey_labels():
        return {"listen": key_display(S.hotkey_listen), "talk": key_display(S.hotkey_talk),
                "toggle": key_display(S.hotkey_toggle), "region": key_display(S.hotkey_region),
                "type": key_display(S.hotkey_type)}

    def _mode_payload(self):
        ok = bool(self.cli or self.client or self.provider)
        return {"name": self._short_mode() if ok else "не настроено", "ok": ok}

    def _short_mode(self):
        if self.provider:
            return f"{self.provider['title'].split(' (')[0].split(' —')[0]} · {self.provider['model']}"
        if self.cli:
            return f"Claude · {str(S.cli_model).capitalize()}"
        return "Claude · " + str(S.api_model).replace("claude-", "").replace("-", " ").capitalize()

    def _tk_error(self, exc, val, tb):
        import traceback
        print("[ошибка окна]\n" + "".join(traceback.format_exception(exc, val, tb)))
        try:
            self._write([(f"Внутренняя ошибка: {val}. Подробности — в журнале (⚙ → «Невидимость и система» → "
                          "«Открыть журнал»).\n", ("err",))])
        except Exception:
            pass

    # ------------------------------------------------------------ окно: положение, размер, компактный режим
    def initial_rect(self):
        """Положение для создания окна (в логических пикселях: движок окна сам умножит на масштаб экрана)."""
        try:
            sc = ctypes_dpi() / 96.0
        except Exception:
            sc = 1.0
        x, y, w, h = self._wanted_rect()
        if self.compact:
            h = int(HEAD_PX() * sc)
        return int(x / sc), int(y / sc), int(w / sc), int(h / sc)

    def _wanted_rect(self):
        sw, sh = screen_size()
        w = int(S.width or 560)
        h = int(S.height or sh * 0.6)
        x = S.pos_x if S.pos_x is not None else sw - w - 24
        y = S.pos_y if S.pos_y is not None else 40
        # положение могло остаться от второго монитора, которого больше нет — проверяем, что окно видно
        vx, vy, vw, vh = virtual_screen()
        if not (vx - w + 80 <= x <= vx + vw - 80 and vy <= y <= vy + vh - 60):
            x, y = sw - w - 24, 40
        return int(x), int(y), w, h

    def _place_window(self):
        x, y, w, h = self._wanted_rect()
        self._full_h = h
        if self.compact and not self.expanded_for_answer:
            h = self._head_h()
        self.web.set_rect(x, y, w, h)

    def _head_h(self):
        return int(round(HEAD_PX() * self.web.scale())) + 2

    def window_height(self):
        rc = self.web.rect()
        return (rc[3] - rc[1]) if rc else int(S.height or 600)

    def _save_geometry(self):
        """Положение и размер запоминаются между запусками."""
        rc = self.web.rect()
        if not rc:
            return
        x, y, r, b = rc
        vals = {"pos_x": x, "pos_y": y, "width": r - x}
        if not self.compact or self.expanded_for_answer:
            vals["height"] = b - y
            self._full_h = b - y
        S.update(**vals)

    def _geometry_matches(self):
        rc = self.web.rect()
        if not rc or S.pos_x is None or S.pos_y is None:
            return False
        x, y, r, b = rc
        same = (x, y, r - x) == (S.pos_x, S.pos_y, int(S.width))
        if not self.compact or self.expanded_for_answer:
            same = same and (not S.height or b - y == int(S.height))
        return same

    def toggle_compact(self):
        if self.compact:
            self.expanded_for_answer = not self.expanded_for_answer   # развернуть на время / свернуть обратно
            self._apply_compact()
            return
        S.update(compact=True)

    def _apply_compact(self):
        """Компактный режим: только заголовок со статусом; при ответе окно разворачивается само."""
        small = self.compact and not self.expanded_for_answer
        rc = self.web.rect()
        if rc:
            x, y, r, b = rc
            if small:
                if b - y > self._head_h() + 20:
                    self._full_h = b - y
                self.web.set_rect(x, y, r - x, self._head_h())
            else:
                self.web.set_rect(x, y, r - x, max(220, int(getattr(self, "_full_h", 0) or S.height or 600)))
        self.web.send("compact", {"on": small}, key="compact")
        self._update_mat_bar()

    def _expand_for_answer(self):
        if self.compact and not self.expanded_for_answer:
            self.expanded_for_answer = True
            self._apply_compact()

    # ------------------------------------------------------------ вывод в окно
    def _write(self, segments, at_end=True):
        """Служебные строки в ленту: [(текст, (тег,…)), …] — теги err/errhint/meta определяют вид."""
        for text, tags in segments:
            text = (text or "").strip()
            if not text:
                continue
            kind = "err" if "err" in tags else "hint" if "errhint" in tags else ""
            self.web.send("sys", {"text": text, "kind": kind})

    def heard(self, text, kind="", sticky=False):
        self.web.send("heard", {"text": text, "kind": kind, "sticky": sticky}, key="heard")

    def toast(self, text, icon="check"):
        self.web.send("toast", {"text": text, "icon": icon})

    def _init_backend(self):
        self.client = self.cli = self.provider = None
        if S.backend == "provider":
            cfg = providers.current()
            bad = providers.problem(cfg)
            if bad:
                return False, bad
            self.provider = cfg
            return True, ""
        if S.backend == "api":
            key = load_api_key()
            if not key:
                return False, ("Нет API-ключа Anthropic. Впиши его: ⚙ → «Подключение к ИИ», или переключись "
                               "на подписку (Claude Code).")
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
            except Exception as e:
                return False, f"Не удалось подключиться через API-ключ: {e}"
            return True, ""
        self.cli = find_claude()
        if not self.cli:
            return False, ("Не найден Claude Code — через него оверлей работает по твоей подписке. "
                           "Открой мастер: ⚙ → «Проверить и починить» — он установит Claude Code и поможет войти.")
        os.makedirs(os.path.join(WORKDIR, "shots"), exist_ok=True)
        return True, ""

    def _mode_name(self):
        if self.provider:
            return f"{self.provider['title'].split(' (')[0].split(' —')[0]} · {self.provider['model']}"
        return "подписка (Claude Code)" if self.cli else "API-ключ Anthropic"

    def _write_prompts(self):
        """Инструкции для Claude (обычный режим и F7) — вместе с материалами пользователя, если они есть."""
        mats, _ = self.materials.full_text()
        extra = MATERIALS_INTRO.format(text=mats) if mats else ""
        main = system_prompt()
        self.api_system = main + extra  # для режима API
        self.api_listen_system = listen_prompt() + extra  # F7 в режиме API — тоже «Скажи:»
        if S.cli_image_mode == "file":
            main += FILE_IMAGE_RULE
        os.makedirs(WORKDIR, exist_ok=True)
        with open(os.path.join(WORKDIR, "system_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(main + extra)
        with open(os.path.join(WORKDIR, "listen_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(listen_prompt() + extra)

    def _render_answer(self, final=False):
        self.web.send("answer", {"id": self.ans_no, "md": self.cur_answer, "final": final}, key=f"ans{self.ans_no}")
        self.dirty = False
        self.last_render = time.time()

    def _copy_text(self, text, what):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()   # чтобы буфер сразу видели другие программы
        except tk.TclError as e:
            print("[буфер] не удалось скопировать:", e)
            return
        self.toast(f"Скопировано: {what}", "content_copy")

    def _begin_exchange(self, question, img=None, region=False, src="voice", listen=False):
        self.ans_no += 1
        meta = ("кусок экрана" if region else "со скриншотом") if img is not None else ("" if listen else "без скриншота")
        thumb = None
        if img is not None:
            try:
                thumb = data_url(img, 240, 75)
                self.shots[self.ans_no] = img
                for k in sorted(self.shots)[:-20]:
                    self.shots.pop(k, None)
            except Exception as e:
                print("[окно] миниатюра:", e)
        self.web.send("begin", {"id": self.ans_no, "question": question, "src": src, "meta": meta, "thumb": thumb})
        self.cur_question, self.cur_answer = question, ""

    def shot_preview(self, sid):
        img = self.shots.get(sid)
        return data_url(img, 1600, 88) if img is not None else None

    # ------------------------------------------------------------ строка состояния
    def set_state(self, state, msg):
        self.state = (state, msg)
        self._refresh_status()

    def _refresh_status(self):
        state, msg = self.state
        step = None
        stages = {j.get("stage") for j in self.listen_jobs.values()}
        if self.rec:
            step, msg = "hear", "Запись вопроса со звука компьютера"
        elif "tail" in stages:
            step, msg = "hear", "Дослушиваю секунду…"
        elif "stt" in stages:
            step, msg = "stt", "Распознаю вопрос…" + (" (точная модель ещё загружается)"
                                                      if self.listen_model_state[0] != "ready" else "")
        elif self.busy:
            step = "answer" if state == "answer" else "think"
        elif self.mic_on:
            step, msg = "hear", "Слышу…"
        elif self.stt_on:
            step, msg = "stt", "Распознаю команду…"
        payload = {"step": step, "text": msg, "state": state}
        if payload != self._status_last:
            self._status_last = payload
            self.web.send("status", payload, key="status")

    def _refresh_rec(self):
        stages = {j.get("stage") for j in self.listen_jobs.values()}
        if self.rec:
            el = int(time.time() - self.rec["press"])
            lvl = level_fraction(self.sysaudio.level(0.15)) if self.sysaudio else 0.0
            self.web.send("rec", {"on": True, "time": f"{el // 60}:{el % 60:02d}", "level": lvl}, key="rec")
            self._rec_shown = True
        elif "tail" in stages:
            lvl = level_fraction(self.sysaudio.level(0.15)) if self.sysaudio else 0.0
            self.web.send("rec", {"on": True, "tail": True, "time": "", "level": lvl}, key="rec")
            self._rec_shown = True
        elif self._rec_shown:
            self._rec_shown = False
            self.web.send("rec", {"on": False}, key="rec")

    def _idle(self):
        if not self.ready or self.fatal:
            return
        now = time.time()
        if now < self.forced_until:
            self.set_state("await", f"Слушаю вопрос… ({int(self.forced_until - now) + 1} с)")
        elif now < self.followup_until:
            self.set_state("followup", f"Можно дополнить без «Клод» ({int(self.followup_until - now) + 1} с)")
        elif self.download_info:
            self.set_state("download", f"Качаю модель распознавания: {self.download_info}")
        elif self.error_hint:
            self.set_state("error", self.error_hint)
        else:
            self.set_state("idle", f"Жду «Клод, …» или {key_display(S.hotkey_listen)}")

    # ------------------------------------------------------------ главный цикл
    def _poll(self):
        try:
            while True:
                self._handle(self.ui_q.get_nowait())
        except queue.Empty:
            pass
        except Exception as e:
            import traceback
            print("[ошибка] обработка события:\n" + traceback.format_exc())
            self._write([(f"Внутренняя ошибка: {e}\n", ("err",))])
        if self.dirty and time.time() - self.last_render > 0.06:
            self._render_answer()
        if self.rec and time.time() - self.rec["press"] > S.listen_max_seconds:
            self.listen_finish()
        if not self.busy and self.ready:
            self._idle()
        else:
            self._refresh_status()
        now = time.time()
        if now - getattr(self, "_rec_tick", 0) > 0.06:
            self._rec_tick = now
            self._refresh_rec()
        if now - getattr(self, "_slow_tick", 0) > 0.25:
            self._slow_tick = now
            self.web.unminimize()
        self.root.after(30, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "status":
            self.set_state(msg[1], msg[2])
        elif kind == "ready":
            self.ready = True
            self.fatal = False
            self._idle()
        elif kind == "fatal":
            self.fatal = True
            self.set_state("error", "Ошибка — подробности в окне")
            self._write([(msg[1] + "\n", ("err",))])
        elif kind == "mic_error":
            self.error_hint = "Микрофон не работает — ⚙ → Звук"
            self._write([("Микрофон: " + msg[1] + " Вопросы со звука компьютера работают и без микрофона.\n", ("err",))])
        elif kind == "mic":
            self.mic_on = msg[1]
            self.web.send("mic", {"on": bool(msg[1])}, key="mic")
            self._refresh_status()
        elif kind == "stt":
            self.stt_on = msg[1]
            self._refresh_status()
        elif kind == "heard":
            self.on_heard(msg[1])
        elif kind == "delta":
            if msg[1] == self.rid and self.busy:
                if not self.cur_answer:
                    self.set_state("answer", "Отвечаю…")
                self.cur_answer += msg[2]
                self.dirty = True
        elif kind == "done":
            if msg[1] == self.rid and self.busy:
                self._finish(error=None)
        elif kind == "error":
            if msg[1] == self.rid and self.busy:
                self._finish(error=msg[2])
        elif kind == "interrupted":
            if msg[1] == self.rid and self.busy:
                self._finish(note="Прервано: поменялись материалы или настройки — спроси ещё раз.")
        elif kind == "session":
            if msg[1] == self.session_gen:
                self.session_id = msg[2]
        elif kind in ("ptt", "talk"):
            self.forced_until = time.time() + 10
            self._idle()
        elif kind == "listen":
            self.listen_key()
        elif kind == "region":
            self.pick_region()
        elif kind == "type":
            self.focus_entry(force=True)
        elif kind == "listen_cancel":
            self.listen_cancel()
        elif kind == "listen_text":
            self.on_listen_text(*msg[1:])
        elif kind == "listen_model":
            self.on_listen_model(msg[1], msg[2])
        elif kind == "mic_model":
            self.on_mic_model(msg[1], msg[2])
        elif kind == "sys_audio":
            self.on_sys_audio()
        elif kind == "mat_status":
            self.heard(msg[1], sticky=True)
        elif kind == "mat_add":
            self.materials.add(msg[1], msg[2], msg[3])
            self._write([(f"Материал добавлен: {msg[1]} ({msg[3]}, {len(msg[2]):,} знаков)\n".replace(",", " "), ("meta",))])
        elif kind == "mat_err":
            self._write([(f"{msg[1]}: {msg[2]}\n", ("err",))])
        elif kind == "mat_done":
            self.attach_busy = max(0, self.attach_busy - 1)
            self.heard("")
            if msg[1]:
                self._apply_materials(analyze=True)
        elif kind == "toggle":
            self.toggle()
        elif kind == "show":
            self.show()
        elif kind == "settings_changed":
            self._on_settings(msg[1])
        elif kind == "tray":
            {"toggle": self.toggle, "settings": self.open_settings, "wizard": self.open_wizard,
             "quit": self._quit}.get(msg[1], lambda: None)()
        elif kind == "call":   # выполнить функцию в потоке логики (окно, настройки, проверки)
            msg[1]()
        elif kind == "quit":   # мастер попросил закрыться на время настройки
            self._quit()

    # ------------------------------------------------------------ голосовые команды
    def on_heard(self, text):
        text = (text or "").strip()
        if not text or is_junk(text):
            return
        now = time.time()
        body = split_wake(text)
        if body is None:
            if now < self.forced_until or now < self.followup_until:
                body = text
            else:
                self.heard("Не мне: " + text, "notme")
                print(f"[микрофон] фраза без «Клод» ({len(text.split())} слов) — не мне")  # чужую речь не пишем
                return
        print(f"[микрофон] команда: {text}")
        self.heard("Услышал: " + text)
        self.forced_until = 0.0
        self.followup_until = 0.0
        self.command(body.strip(" ,.:;!?-—…"))

    def command(self, body):
        low = body.lower().strip(" ,.:;!?-—…")
        words = low.split()

        if not low:  # просто «Клод» — ждём вопрос следующей фразой
            self.forced_until = time.time() + 8
            self._idle()
            return

        if "из буфера" in low and any(w in low for w in ("возьми", "добавь", "запомни", "прикрепи", "вставь", "текст")):
            self.paste_material()
            return
        if any(p in low for p in ("убери материалы", "удали материалы", "забудь материалы", "очисти материалы")):
            self.clear_materials()
            return

        if words[0] in ("стоп", "хватит", "отмена", "отбой", "замолчи", "остановись", "стой"):
            self.cancel(note="Остановлено.")
            return

        if low in ("скрой", "скройся", "спрячь", "спрячься", "скрой окно", "убери окно", "свернись"):
            self.hide()
            return
        if low in ("покажи", "покажись", "появись", "покажи окно", "вернись", "покажи ответ"):
            self.show()
            return

        if len(words) <= 3 and any(w in words for w in ("вниз", "ниже", "листай")):
            self.web.send("scroll", {"dir": "down"})
            return
        if len(words) <= 3 and any(w in words for w in ("вверх", "выше", "наверх")):
            self.web.send("scroll", {"dir": "up"})
            return

        if words[0] in ("скопируй", "копируй", "скопировать") and len(words) <= 4:
            self.copy(code_only=any(w.startswith("код") for w in words))
            return

        for phrase in ("новая задача", "новый вопрос", "новый диалог", "начни сначала", "начнём сначала",
                       "начнем сначала", "сбрось", "сброс", "забудь всё", "забудь все", "забудь"):
            if low.startswith(phrase):
                self.reset()
                rest = body[len(phrase):].strip(" ,.:;!?-—…")
                if rest:
                    self.ask(rest)
                return

        for phrase in ("без экрана", "без скриншота", "без скрина"):
            if low.startswith(phrase):
                rest = body[len(phrase):].strip(" ,.:;!?-—…")
                if rest:
                    self.ask(rest, screen=False)
                return

        self.ask(body, screen=S.screen_question)

    def quick(self, kind):
        """Кнопки под ответом: «Короче», «Подробнее», «Объясни проще», «Пример» — уточнение в том же диалоге."""
        prompt = QUICK.get(kind)
        if not prompt:
            return
        self.next_source, self.next_icon = "text", "quick"
        self.ask(kind, screen=False, prompt=prompt)

    # ------------------------------------------------------------ вопрос
    def ask(self, question, screen=True, prompt=None, listen=False, icon="🎧"):
        if self.busy:
            self.cancel(note="Прервано новым вопросом.")
        if not self.client and not self.cli and not self.provider:
            self._write([("Не настроено подключение к ИИ (см. сообщение выше). Открой мастер: "
                          "⚙ → «Проверить и починить».\n", ("err",))])
            return
        use_session = bool(listen and self.cli)
        self.show()
        self._expand_for_answer()
        self.error_hint = ""

        img = None
        hidden = False
        region = self.pending_shot
        used_region = False
        if screen and region is not None:  # заранее выделенный кусок экрана — вместо всего монитора
            self.set_pending_shot(None)
            img = region.copy()
            side = S.listen_image_side if listen else S.max_image_side
            from PIL import Image
            img.thumbnail((side, side), Image.LANCZOS)
            screen = False
            used_region = True
        if screen:
            self.set_state("think", "Делаю скриншот…")
            xy = cursor_xy()
            hidden = self._hide_for_capture()
            try:
                img = grab_screen(xy, S.listen_image_side if listen else S.max_image_side)
            except Exception as e:
                self._write([(f"Не удалось сделать скриншот: {e}\n", ("err",))])
            finally:
                self._restore_after_capture(hidden)

        content = []
        text = prompt or question
        if img is not None and self.cli and S.cli_image_mode == "file" and not use_session:
            path = self._save_shot(img)
            text = f"Скриншот экрана: {path}\n\nВопрос: {text}"
        elif img is not None:
            b64, media = encode_image(img)
            content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}})
        content.append({"type": "text", "text": text})

        source, src_icon = self.next_source, self.next_icon
        self.next_source, self.next_icon = "voice", None
        self.cur_source = "f7" if listen and icon == "🎧" else "materials" if icon == "📎" else source
        self._begin_exchange(question, img, used_region, src=src_icon or self.cur_source, listen=listen)
        self.ask_t0 = time.time()
        print(f"[вопрос] {self.cur_source}, "
              + ("без скриншота" if img is None else "выделенный кусок экрана" if used_region else
                 ("скриншот — окно не пряталось (оно и так невидимо)" if not hidden else
                  "скриншот — окно на миг пряталось (невидимость недоступна)")))
        self.set_state("think", "Думаю…")
        self.busy = True
        self.rid += 1
        self.cancel_ev = threading.Event()
        self.via_listen = use_session
        self.cur_is_listen = listen
        if use_session:
            self._ensure_listen_session()
            self.listen_session.send(self.rid, content)
        elif self.cli:
            args = (self.ui_q, self.cli, self.rid, content, self.session_id, self.session_gen, self.cancel_ev,
                    lambda p: setattr(self, "proc", p))
            threading.Thread(target=cli_ask, args=args, daemon=True).start()
        elif self.provider:
            self.history.append({"role": "user", "content": content})
            system = self.api_listen_system if listen else self.api_system
            model = self.provider["listen_model"] if listen else self.provider["model"]
            threading.Thread(target=providers.provider_ask, args=(self.ui_q, self.provider, self.rid, model, system,
                                                                  self._messages(), self.cancel_ev),
                             daemon=True).start()
        else:
            self.history.append({"role": "user", "content": content})
            system = self.api_listen_system if listen else self.api_system
            threading.Thread(target=api_ask, args=(self.ui_q, self.client, self.rid, system,
                                                   self._messages(), self.cancel_ev), daemon=True).start()

    def _save_shot(self, img):
        self.shot_no += 1
        shots = os.path.join(WORKDIR, "shots")
        os.makedirs(shots, exist_ok=True)
        path = os.path.join(shots, f"shot_{int(time.time())}_{self.shot_no}.png")
        img.save(path, "PNG")
        try:  # держим только последние 30 скриншотов
            files = sorted(os.listdir(shots))
            for name in files[:-30]:
                os.remove(os.path.join(shots, name))
        except OSError:
            pass
        return path

    def _hide_for_capture(self):
        if not self.web.visible:
            return False
        if self.guard is not None and self.guard.fully_hidden():
            return False  # окна и так нет в захвате экрана — прятать не нужно, ничего не мигает
        self.web.hide()
        time.sleep(0.2)
        return True

    def _restore_after_capture(self, hidden):
        if hidden:
            self.web.show()

    def _messages(self):
        hist = self.history[-S.max_history_messages:]
        while hist and hist[0]["role"] != "user":
            hist = hist[1:]
        out, seen_images = [], 0
        for msg in reversed(hist):
            if msg["role"] == "user" and isinstance(msg["content"], list):
                blocks = []
                for blk in msg["content"]:
                    if blk["type"] == "image":
                        seen_images += 1
                        if seen_images > S.keep_last_images:
                            blocks.append({"type": "text", "text": "[здесь был более ранний скриншот]"})
                            continue
                    blocks.append(blk)
                out.append({"role": "user", "content": blocks})
            else:
                out.append(msg)
        return list(reversed(out))

    def _finish(self, error=None, note=None):
        """Закрывает текущий обмен и поддерживает историю в порядке user/assistant."""
        self.busy = False
        if self.cancel_ev:
            self.cancel_ev.set()
        if self.via_listen and note and self.listen_session:
            self.listen_session.restart()  # прерванный ответ — перезапуск постоянной сессии
        self.via_listen = False
        was_listen, self.cur_is_listen = self.cur_is_listen, False
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None
        self.rid += 1  # поздние куски старого ответа игнорируются
        answer = self.cur_answer.strip()
        print(f"[ответ] {len(answer)} знаков за {time.time() - getattr(self, 'ask_t0', time.time()):.1f} с"
              + (f", ошибка: {str(error)[:200]}" if error else "") + (f", {note}" if note else ""))
        if answer:
            self.last_answer = self.cur_answer
        if S.history_save and (answer or error) and self.cur_question:
            try:
                history.add(self.cur_question, answer + (("\n" + note) if note else ""),
                            kind=getattr(self, "cur_source", "voice"), mode=self._mode_name(), error=str(error or ""))
            except OSError as e:
                print("[история] не удалось сохранить:", e)
        if not self.cli:  # в режиме подписки историю хранит сам Claude Code
            if answer:
                self.history.append({"role": "assistant", "content": answer + ("\n" + note if note else "")})
            elif self.history and self.history[-1]["role"] == "user":
                self.history.pop()
        hint = ""
        if error:
            hint = (providers.explain(str(error)) if self.provider else "") or explain_error(error)
            print("[claude] ошибка:", error)
            self.error_hint = "Ошибка — что делать, написано в окне"
        self.dirty = False
        self.web.send("finish", {"id": self.ans_no, "md": self.cur_answer, "error": str(error) if error else "",
                                 "hint": hint or "", "note": note or "", "quick": bool(answer and not error),
                                 "fix": bool(error)})
        # после ответа на вопрос с компьютера «дополнить без Клод» не включаем: микрофон может слышать колонки
        if not error and not note and S.followup_seconds and not was_listen:
            self.followup_until = time.time() + S.followup_seconds
        self._idle()

    # ------------------------------------------------------------ вопросы со звука компьютера (F7)
    def listen_key(self):
        if self.rec:
            self.listen_finish()
        else:
            self.listen_start()

    def listen_start(self):
        sa = self.sysaudio
        if sa is None:
            return
        if sa.state == "error":
            self._write([("Звук компьютера: " + sa.error + "\n", ("err",))])
            sa.refresh_if_stale()
            return
        sa.refresh_if_stale()  # переключили наушники/колонки — откроем устройства заново
        now = time.time()
        self.listen_seq += 1
        self.rec = {"id": self.listen_seq, "t0": now - S.listen_pre_seconds, "press": now}
        self.listen_pause.set()
        if self.cli:
            self._ensure_listen_session()  # Claude прогревается, пока идёт запись
        self.show()
        self._expand_for_answer()
        self._refresh_status()
        self._refresh_rec()

    def listen_finish(self):
        job, self.rec = self.rec, None
        if not job:
            return
        job["t1"] = time.time() + S.listen_post_seconds
        job["stage"] = "tail"
        self.listen_jobs[job["id"]] = job
        self.root.after(int(S.listen_post_seconds * 1000) + 60, lambda: self._listen_cut(job["id"]))
        self._refresh_status()

    def listen_cancel(self):
        if not self.rec:
            return
        self.rec = None
        self._listen_update_pause()
        self.toast("Запись вопроса отменена", "close")
        self._idle()
        self._refresh_status()

    def _listen_cut(self, job_id):
        job = self.listen_jobs.get(job_id)
        if not job:
            return
        audio, rate, dev = self.sysaudio.segment(job["t0"], job["t1"]) if self.sysaudio else (None, 0, "")
        if audio is None or len(audio) < rate * 0.3:
            self.listen_jobs.pop(job_id, None)
            self._listen_update_pause()
            self._write([("За эти секунды компьютер не играл звук — распознавать нечего. Если звук был, "
                          "проверь устройство вывода: ⚙ → Звук.\n", ("err",))])
            self._idle()
            self._refresh_status()
            return
        job["stage"], job["dur"], job["dev"] = "stt", len(audio) / rate, dev
        prepared = prepare_audio(audio, rate)
        self.last_f7_audio = prepared
        threading.Thread(target=self._save_last_f7, args=(prepared,), daemon=True).start()
        self.listen_tr.q.put((job_id, prepared))
        self._refresh_status()

    @staticmethod
    def _save_last_f7(audio):
        try:
            save_wav(LAST_F7_WAV, audio)
        except Exception as e:
            print("[F7] не удалось сохранить запись для сравнения моделей:", e)

    def on_listen_text(self, job_id, text, lang, secs, err=None):
        job = self.listen_jobs.pop(job_id, None)
        self._listen_update_pause()
        if job is None:
            return
        if err:
            self._write([(f"Звук компьютера: {err}\n", ("err",))])
            self._idle()
            return
        text = (text or "").strip()
        print(f"[F7] {job['dur']:.1f} с звука («{job['dev']}»), язык {lang or '?'}, распознано за {secs:.1f} с: {text}")
        if not text or is_junk(text):
            self._write([("В записи не нашлось речи.\n", ("meta",))])
            self._idle()
            return
        prompt = (f"Фрагмент звука с компьютера ({job['dur']:.0f} с" + (f", язык: {lang}" if lang else "")
                  + "). Автоматическая расшифровка:\n«" + text + "»")
        self.ask(text, screen=S.listen_screen, prompt=prompt, listen=True)

    def _listen_update_pause(self):
        if self.rec or self.listen_jobs:
            self.listen_pause.set()
        else:
            self.listen_pause.clear()

    def on_mic_model(self, state, info):
        if state == "progress":
            self.download_info = info.get("text", "") if isinstance(info, dict) else str(info)
            if not self.ready:
                self.set_state("download", f"Скачиваю модель распознавания команд: {self.download_info}")
            return
        if state == "loading":
            print(f"[whisper] команды: загружаю {info}")
        elif state == "ready":
            self.download_info = ""
            self.mic_model_info = info
            if self.ready and getattr(self, "_mic_model_switch_shown", False):
                self._write([(f"Команды: теперь распознаёт {info}.\n", ("meta",))])
            self._mic_model_switch_shown = True
        elif state == "error":
            self.download_info = ""
            self._write([(f"Модель для команд не загрузилась ({info}) — осталась прежняя.\n", ("err",))])

    def on_listen_model(self, state, info):
        if state == "progress":
            self.download_info = info.get("text", "") if isinstance(info, dict) else str(info)
            if not self.busy:
                self._idle()
            return
        if state == "download":
            now = self.listen_model_state[1] if self.listen_model_state[0] == "ready" else ""
            size = stt.fmt_size(stt.model_size_bytes(info))
            self._write([(f"В фоне качаю модель распознавания {info} (~{size}, один раз)"
                          + (f". {key_display(S.hotkey_listen)} пока работает на {now.split(' ·')[0]}" if now else "")
                          + ".\n", ("meta",))])
            return
        if state == "upgraded":
            self.download_info = ""
            self.listen_model_state = ("ready", info)
            self._write([(f"{key_display(S.hotkey_listen)}: теперь распознаёт {info}.\n", ("meta",))])
            return
        if state == "upgrade_fail":
            self.download_info = ""
            self._write([(f"Модель не загрузилась ({info}) — {key_display(S.hotkey_listen)} работает на прежней.\n",
                          ("meta",))])
            return
        self.listen_model_state = (state, info)
        if state == "ready":
            print(f"[whisper] звук компьютера готов: {info}")
        elif state == "fallback":
            self._write([(f"Точная модель не загрузилась ({info}) — будет модель микрофона.\n", ("err",))])
        elif state == "error":
            self._write([(f"Вопросы со звука компьютера не будут работать: {info}\n", ("err",))])

    def on_sys_audio(self):
        sa = self.sysaudio
        if sa is None:
            return
        if sa.state == "ok" and not self._sys_announced:
            self._sys_announced = True
            main = f" (основное: {sa.default_name.replace(' [Loopback]', '')})" if sa.default_name else ""
            print(f"[звук] слушаю устройств: {len(sa.devices)}{main}")
        elif sa.state == "error" and not self._sys_err_shown:
            self._sys_err_shown = True
            self._write([("Звук компьютера: " + sa.error + "\n", ("err",))])

    def _ensure_listen_session(self):
        if self.listen_session is None:
            self.listen_session = ClaudeSession(self.ui_q, self.cli, os.path.join(WORKDIR, "listen_prompt.txt"),
                                                S.listen_model, S.listen_effort, S.listen_max_turns)
        if not self.listen_session.alive():
            self.listen_session.start()

    # ------------------------------------------------------------ материалы (📎)
    def pick_files(self):
        """Окно выбора файлов (стандартное окно Windows; хук невидимости прячет его от захвата в момент создания)."""
        from .webwin import Bridge
        threading.Thread(target=Bridge(self).pick_files, daemon=True).start()

    def paste_material(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        lines = [x.strip().strip('"') for x in text.strip().splitlines() if x.strip()]
        if lines and all(os.path.isfile(x) for x in lines):  # в буфере пути к файлам
            self.attach_files(lines)
        elif text.strip():
            self.attach_text(text, "Текст из буфера")
        else:
            self.toast("В буфере обмена нет текста — скопируй текст (Ctrl+C) и попробуй ещё раз", "content_paste")

    def attach_files(self, paths):
        self.show()
        self._expand_for_answer()
        self.attach_busy += 1
        cli = self.cli or find_claude()  # сканы и картинки читает Claude Code — даже если отвечает другой ИИ

        def work():
            added = 0
            for path in paths:
                name = os.path.basename(path)
                self.ui_q.put(("mat_status", f"Читаю «{name}»…"))
                try:
                    text, kind = extract_material(path, cli)
                    if not text.strip():
                        raise ValueError("в файле не нашлось текста")
                    self.ui_q.put(("mat_add", name, text, kind))
                    added += 1
                except Exception as e:
                    self.ui_q.put(("mat_err", name, str(e)))
            self.ui_q.put(("mat_done", added))

        threading.Thread(target=work, daemon=True).start()

    def attach_text(self, text, title):
        self.show()
        self._expand_for_answer()
        self.materials.add(title, text.strip(), "текст")
        self._write([(f"Материал добавлен: {title} ({len(text.strip()):,} знаков)\n".replace(",", " "), ("meta",))])
        self._apply_materials(analyze=True)

    def clear_materials(self):
        if not self.materials.items:
            return
        self.materials.clear()
        self._apply_materials(analyze=False)
        self.toast("Материалы убраны", "delete_sweep")

    def remove_material(self, mid):
        it = next((x for x in self.materials.items if x["id"] == mid), None)
        if it and self.materials.remove(mid):
            self._apply_materials(analyze=False)
            self.toast(f"Убрано: {it['title']}", "delete")

    def _hotwords(self):
        terms = []
        if S.materials_hotwords and self.materials.items:
            terms = material_terms(self.materials.full_text()[0], S.materials_hotwords)
        hint = [t.strip() for t in (S.listen_hint or "").split(",") if t.strip()]
        out = ", ".join(dict.fromkeys(hint + terms))
        return out or None

    def _update_mat_bar(self):
        items = [{"id": it["id"], "title": it["title"], "icon": mat_icon(it["title"]),
                  "size": f"{it['chars']:,} знаков".replace(",", " ")} for it in self.materials.items]
        cut = self.materials.full_text()[1] if items else False
        self.web.send("mats", {"items": items, "cut": bool(cut)}, key="mats")

    def _apply_materials(self, analyze):
        """Материалы поменялись: новые инструкции, новый диалог, новые подсказки для распознавания."""
        self._write_prompts()
        self.session_id = None
        self.session_gen += 1
        self.history.clear()
        if self.busy and self.via_listen:  # шёл разбор прошлых материалов — новый важнее
            self._finish(note="Прервано: добавились новые материалы.")
        if self.listen_session:
            self.listen_session.stop()  # перезапустится с новыми материалами при следующем вопросе
        if self.listen_tr:
            self.listen_tr.hotwords = self._hotwords()
        self._update_mat_bar()
        if analyze and self.materials.items and (self.cli or self.client or self.provider) and not self.busy:
            titles = ", ".join(it["title"] for it in self.materials.items[-3:])
            self.ask("Материалы: " + titles, screen=False, prompt=analyze_prompt(), listen=True, icon="📎")

    def cancel(self, note="Остановлено."):
        if self.busy:
            self._finish(note=note)

    def reset(self):
        self.cancel(note="Остановлено.")
        if self.listen_session:
            self.listen_session.stop()  # и вопросы с компьютера начинаем с чистого листа
        self.history.clear()
        self.session_id = None
        self.session_gen += 1
        self.followup_until = 0.0
        self.error_hint = ""
        self.web.send("clear", {})
        self.toast("Новая задача — контекст очищен", "add_comment")

    def copy(self, code_only=False):
        src = self.cur_answer or self.last_answer
        if not src:
            return
        text = (last_code_block(src) if code_only else None) or src
        self._copy_text(text, "код" if code_only and last_code_block(src) else "ответ")

    def hide(self):
        if self.visible:
            self.web.hide()
            self.visible = False

    def show(self):
        if not self.visible:
            self.web.show()
            self.visible = True

    def toggle(self):
        self.hide() if self.visible else self.show()

    def _hotkey_actions(self):
        return current_binds(S)

    def _start_tray(self):
        from .tray import Tray
        if self.tray is None:
            self.tray = Tray(lambda ev: self.ui_q.put(("tray", ev)))
        if not self.tray.start():
            self._write([(f"Значок в трее не запустился: {self.tray.error}\n", ("err",))])

    # ------------------------------------------------------------ невидимость на демонстрации экрана
    def _refresh_shield(self, again=True):
        if self.guard is not None:
            level, text = self.guard.status()
            if (level, text) != getattr(self, "_shield_last", None):
                self._shield_last = (level, text)
                self.web.send("shield", {"level": level, "text": text.replace("🛡 ", "").replace("⚠ ", "")}, key="shield")
                print("[невидимость]", text, "| окна:", [(hex(h), a) for h, a in self.guard.window_states()])
        if again:
            self.root.after(3000, self._refresh_shield)

    def capture_check(self):
        """Снимок экрана тем же способом, что у программ демонстрации. → (картинка, прямоугольник окна, ок, текст)."""
        hwnd = self.web.hwnd
        shot, rect = winsys.grab_monitor_of(hwnd)
        seen = winsys.region_looks_like(shot, rect, [T["BG"], T["BG2"]]) if self.visible else 0.0
        level, status = self.guard.status()
        # решает защита окна (Windows сама сообщает, что окно исключено из захвата); сравнение цветов —
        # только для журнала: на тёмном фоне за окном оно давало ложную тревогу
        ok = level == "ok"
        print(f"[невидимость] проверка: {status}; доля цветов окна в снимке {seen:.2f}")
        if ok:
            msg = ("Окна оверлея на снимке нет. Так тебя видят в Zoom, Teams, Discord, Google Meet, OBS и на "
                   "скриншотах. Оранжевая рамка — где окно стоит на самом деле (на демонстрации её нет).")
        else:
            msg = status.replace("⚠ ", "") + " Оранжевая рамка — где стоит окно."
        return shot, rect, ok, msg

    def capture_check_web(self):
        shot, rect, ok, msg = self.capture_check()
        return {"img": data_url(shot, 1100, 80), "rect": [int(v) for v in rect], "w": shot.width, "h": shot.height,
                "ok": ok, "msg": msg}

    def show_capture_check(self, parent=None):
        if parent is not None:   # из окна настроек — отдельным окном
            from .ui_dialogs import show_capture_check
            show_capture_check(self, parent)
            return
        self.show()
        self._expand_for_answer()
        self.web.send("check", {})

    # ------------------------------------------------------------ настройки, справка, история, мастер
    def open_settings(self, tab=None):
        from .ui_settings import SettingsWindow
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.focus(tab)
            return
        self.settings_win = SettingsWindow(self, tab)

    def focus_entry(self, force=False):
        """Курсор — в поле вопроса. force: по горячей клавише из другой программы (окно становится активным)."""
        if not S.text_input:
            S.update(text_input=True)
        self.show()
        self._expand_for_answer()
        self.web.focus()

    def submit_text(self, text):
        text = (text or "").strip()
        if not text:
            return
        self.heard("Написал: " + text)
        print(f"[текст] вопрос ({len(text.split())} слов)")
        self.forced_until = self.followup_until = 0.0
        self.next_source = "text"
        body = split_wake(text)  # «Клод, …» в тексте тоже можно — лишнее слово уберём
        self.command((body if body is not None else text).strip(" ,.:;!?-—…") or text)
        self.next_source = "voice"

    def pick_region(self):
        """Выделить мышкой кусок экрана — он приложится к следующему вопросу (голосом, текстом или F7)."""
        if getattr(self, "_picker", None) is not None:
            return
        from .region import RegionPicker

        def done(img):
            self._picker = None
            if img is None:
                return
            self.set_pending_shot(img)
            self.show()
            self._expand_for_answer()
            if S.text_input:
                self.focus_entry(force=True)

        try:
            self._picker = RegionPicker(self, done)
        except Exception as e:
            self._picker = None
            self._write([(f"Не удалось выделить кусок экрана: {e}\n", ("err",))])

    def set_pending_shot(self, img):
        self.pending_shot = img
        if img is None:
            self.web.send("shot", None, key="shot")
            self.heard("")
        else:
            self.web.send("shot", {"w": img.width, "h": img.height}, key="shot")
            self.heard("Кусок экрана выбран — задай вопрос голосом, текстом или "
                       f"{key_display(S.hotkey_listen)}", sticky=True)
            print(f"[кусок экрана] {img.width}×{img.height}")

    def open_history(self):
        self.show()
        self._expand_for_answer()
        self.web.send("history", {})

    def export_history(self, query=""):
        """Сохранить историю в файл .md (окно «Сохранить как» — от главного окна)."""
        recs = history.load(query)
        if not recs:
            self.toast("Сохранять нечего — история пуста", "info")
            return

        def work():
            import webview
            try:
                kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
                path = self.web.win.create_file_dialog(kind, save_filename="История Claude Overlay.md",
                                                       file_types=("Текст с разметкой (*.md)", "Текст (*.txt)"))
            except Exception as e:
                print("[история] окно сохранения:", e)
                return
            if isinstance(path, (list, tuple)):
                path = path[0] if path else None
            if path:
                history.export_markdown(recs, path)
                self.ui_q.put(("call", lambda: self.toast(f"Сохранено записей: {len(recs)}", "download_done")))
        threading.Thread(target=work, daemon=True).start()

    def toggle_info(self):
        """Короткая подсказка — панель под заголовком; повторное нажатие (или щелчок в окне) прячет."""
        k, t8, t9 = key_display(S.hotkey_listen), key_display(S.hotkey_talk), key_display(S.hotkey_toggle)
        rows = [("«Клод, …»", "вопрос по экрану: сделаю скриншот под курсором и отвечу"),
                ("«Клод, дополни…»", f"тот же диалог; {S.followup_seconds} с после ответа можно без «Клод»"
                 if S.followup_seconds else "тот же диалог продолжается"),
                ("«Клод, новая задача»", "очистить диалог · «стоп» · «скопируй код» · «скрой»"),
                (k, "вопрос со звука компьютера (лекция, созвон): нажми в начале и в конце · Esc — отмена"),
                (t8, "следующая фраза — команда без «Клод»"),
                (t9, "спрятать / показать окно"),
                (key_display(S.hotkey_region), "выделить кусок экрана — приложится к следующему вопросу"),
                (key_display(S.hotkey_type), "написать вопрос текстом (поле внизу окна)"),
                ("Скрепка вверху", "материалы: файлы, текст из буфера (Ctrl+V) или перетащи файл в окно")]
        notes = [f"Отвечает: {self._mode_name()}" if (self.cli or self.client or self.provider) else ""]
        if not os.path.isfile(SETUP_STATE_PATH):
            notes.append("Совет: один раз проверь всё мастером — ⚙ → «Проверить и починить».")
        self.show()
        self._expand_for_answer()
        self.web.send("info", {"rows": rows, "notes": [n for n in notes if n]})

    def open_help(self):
        from .ui_dialogs import HELP
        keys = {"listen": key_display(S.hotkey_listen), "talk": key_display(S.hotkey_talk),
                "toggle": key_display(S.hotkey_toggle), "followup": S.followup_seconds,
                "region": key_display(S.hotkey_region), "type": key_display(S.hotkey_type),
                "pre": f"{S.listen_pre_seconds:g}"}
        sections = [[title, [[k.format(**keys), d.format(**keys)] for k, d in items]] for title, items in HELP]
        self.show()
        self._expand_for_answer()
        self.web.send("help", {"sections": sections})

    def open_wizard(self):
        """«Проверить и починить» = мастер первого запуска. Оверлей закрывается, мастер потом запустит его снова."""
        self.restart(["--wizard", "--from-overlay"])

    def restart(self, args=()):
        if self.inst is not None:
            self.inst.release()
        pyw = sys.executable
        if pyw.lower().endswith("python.exe") and os.path.isfile(pyw[:-10] + "pythonw.exe"):
            pyw = pyw[:-10] + "pythonw.exe"
        subprocess.Popen([pyw, os.path.join(HERE, "overlay.py"), *args], cwd=HERE, **winsys.NO_WINDOW)
        self._quit()

    def _on_settings(self, changed):
        """Настройки поменялись в окне ⚙ — применяем сразу, без перезапуска."""
        if changed <= {"pos_x", "pos_y", "width", "height"} and self._geometry_matches():
            return  # это мы сами запомнили положение после перетаскивания
        w = self.web
        if changed & {"prompt_system", "prompt_listen", "student_style", "math_render", "listen_style",
                      "cli_image_mode", "materials_max_chars"}:
            self._write_prompts()
            if self.listen_session:
                self.listen_session.stop()
        if changed & {"listen_model", "listen_effort", "listen_max_turns"} and self.listen_session:
            self.listen_session.stop()
            self.listen_session = None
        if changed & {"backend", "claude_cmd", "cli_model", "api_model", "provider", "provider_base_url", "provider_model",
                      "provider_listen_model", "provider_vision", "api_key_saved"}:
            ok, problem = self._init_backend()
            self.session_id = None
            self.session_gen += 1
            if self.listen_session:
                self.listen_session.stop()
                self.listen_session = None
            w.send("mode", self._mode_payload(), key="mode")
            self._write([(("Подключение к ИИ: " + self._mode_name() + "\n")
                          if ok else (problem + "\n"), ("meta",) if ok else ("err",))])
        if changed & {k for _, k in HK_ACTIONS}:
            self.hk.set_binds(self._hotkey_actions())
            w.send("hotkeys", self._hotkey_labels(), key="hotkeys")
        prefs = {}
        if "alpha" in changed:
            prefs["alpha"] = float(S.alpha)
        if "ghost" in changed:
            prefs["ghost"] = bool(S.ghost)
        if "ghost_fade" in changed:
            prefs["ghost_fade"] = float(S.ghost_fade)
        if "math_render" in changed:
            prefs["math"] = bool(S.math_render)
        if "protect" in changed:
            self.guard.set_enabled(S.protect)
            self._shield_last = None
            self._refresh_shield(again=False)
            prefs["protect"] = bool(S.protect)
        if prefs:
            w.send("prefs", prefs)
        if "tray" in changed:
            if S.tray:
                self._start_tray()
            elif self.tray:
                self.tray.stop()
        if "font_size" in changed:
            w.send("font", self._fs(), key="font")
        if "text_input" in changed:
            w.send("textinput", {"on": bool(S.text_input)}, key="textinput")
        if "compact" in changed:
            self.compact = bool(S.compact)
            self.expanded_for_answer = False
            self._apply_compact()
        if changed & {"width", "height", "pos_x", "pos_y"} and not self._geometry_matches():
            self._place_window()
        if "whisper_model" in changed and self.transcriber:
            self.transcriber.request_model(S.whisper_model)
        if "listen_whisper_model" in changed and self.listen_tr:
            self.listen_tr.request_model(stt.listen_model_name(stt.whisper_device()))
        if "mic_device" in changed:
            self.restart_mic()
        if changed & {"listen_pre_seconds", "listen_max_seconds", "listen_post_seconds"} and self.sysaudio:
            self.sysaudio.update_keep()
        if "listen_device" in changed and self.sysaudio and not self.rec:  # во время записи не трогаем
            self._sys_announced = self._sys_err_shown = False
            self.sysaudio.start()
        if changed & {"listen_hint", "materials_hotwords"} and self.listen_tr:
            self.listen_tr.hotwords = self._hotwords()
        if "theme" in changed:
            self.retheme()

    def retheme(self):
        """Новая тема — сразу и в главном окне, и в окнах настроек."""
        apply_theme(S.theme, self.root)
        self.web.send("theme", self._theme_payload(), key="theme")
        print("[тема]", S.theme)

    def restart_mic(self):
        if self.listener:
            self.listener.stop()
        self.error_hint = ""
        self.listener = Listener(self.audio_q, self.ui_q)
        self.listener.start()

    def _quit(self):
        if self._quitting:
            return
        self._quitting = True
        try:
            print("[выход] закрываю оверлей")
            if self.listen_session:
                self.listen_session.stop()
            if self.tray:
                self.tray.stop()
            try:
                self._save_geometry()
            except Exception:
                pass
            self.web.destroy()
        finally:
            os._exit(0)


# ---------------------------------------------------------------- экран
def HEAD_PX():
    from .webwin import HEAD_H
    return HEAD_H


def ctypes_dpi():
    import ctypes
    try:
        return ctypes.windll.user32.GetDpiForSystem()
    except Exception:
        return 96


def screen_size():
    import ctypes
    gm = ctypes.windll.user32.GetSystemMetrics
    return gm(0), gm(1)


def virtual_screen():
    import ctypes
    gm = ctypes.windll.user32.GetSystemMetrics
    return gm(76), gm(77), gm(78), gm(79)


def cursor_xy():
    from .webwin import cursor_pos
    try:
        return cursor_pos()
    except Exception:
        return 0, 0
