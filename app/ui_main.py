# -*- coding: utf-8 -*-
"""Главное окно оверлея (Tkinter): окно без рамки поверх всех, невидимое на демонстрации экрана.
Все потоки общаются с окном только через очередь ui_q (_poll каждые 30 мс)."""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

from . import winsys
from .audio import Listener, SystemAudio, prepare_audio, level_bars, save_wav
from .claude import ClaudeSession, cli_ask, api_ask, explain_error, find_claude
from .config import S, WORKDIR, HERE, LAST_F7_WAV, SETUP_STATE_PATH, load_api_key
from .hotkeys import HotkeyManager, display as key_display
from .materials import Materials, extract_material, material_terms
from .prompts import system_prompt, listen_prompt, analyze_prompt, MATERIALS_INTRO, FILE_IMAGE_RULE
from .screen import grab_screen, encode_image
from . import stt
from . import providers
from .textfmt import (MATH, CODE, md_segments, code_blocks, last_code_block, tex_rows, render_tex, warm_up_math,
                      split_wake, is_junk)
from .ui_theme import (T, F, MONO, IS_WIN, IS_MAC, IconButton, ThinScroll, Tooltip, hand, text_cursor, init_fonts,
                       state_color, apply_theme)

HEADER_H = 38


class App:
    def __init__(self, inst=None):
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
        self.math_cache = {}
        self.follow = True                      # держать текущий вопрос вверху окна (пока сам не листал)
        self.error_hint = ""

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
        self.download_info = ""                 # «1,2 из 3,1 ГБ (40%)» — пока в фоне качается модель
        self.via_listen = False                 # текущий ответ идёт через постоянную сессию
        self.cur_is_listen = False
        self._sys_announced = False
        self._sys_err_shown = False
        self.last_f7_audio = None

        self.client = None
        self.cli = None
        self.session_id = None
        self.session_gen = 0
        self.proc = None
        self.shot_no = 0
        self.materials = Materials()
        self.api_system = ""
        self.attach_busy = 0
        self.settings_win = None
        self.help_win = None
        self.tray = None
        self.listener = None
        self.transcriber = None
        backend_ok, problem = self._init_backend()
        self._write_prompts()

        self._build_ui()
        self._welcome(backend_ok, problem)
        if S.load_error:
            self._write([("⚠ " + S.load_error + "\n", ("err",))])

        if self.materials.items:
            self._update_mat_bar()
            print("[материалы] с прошлого раза:", self.materials.summary())
        if S.math_render:
            threading.Thread(target=warm_up_math, args=(T["FG"], T["BG"]), daemon=True).start()
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

        self.root.after(30, self._poll)

    # ------------------------------------------------------------ UI build
    def _build_ui(self):
        r = self.root = tk.Tk()
        r.withdraw()  # показываем только после того, как окно спрятано от захвата экрана
        r.title("Claude Overlay")
        init_fonts(r)
        r.configure(bg=T["BORDER"])
        if IS_WIN:
            # окно-инструмент: нет кнопки на панели задач и в Alt+Tab. Ставить ДО overrideredirect и прозрачности:
            # иначе Tk при смене прозрачности сбрасывает этот признак и окно вылезает на панель задач
            r.attributes("-toolwindow", True)
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        try:
            r.attributes("-alpha", float(S.alpha))
        except tk.TclError:
            pass
        r.report_callback_exception = self._tk_error
        self._place_window()

        outer = self.outer = tk.Frame(r, bg=T["BG"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        head = self._head = tk.Frame(outer, bg=T["BG2"], height=HEADER_H)
        head.pack(fill="x")
        head.pack_propagate(False)
        self.dot = tk.Canvas(head, width=12, height=12, bg=T["BG2"], highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(12, 6))
        self._dot_item = self.dot.create_oval(1, 1, 11, 11, fill=T["MUTED"], outline="")
        self.icons = {}
        for name, glyph_name, cmd, tip in (
                ("close", "close", self._quit, "Выход"),
                ("hide", "hide", self.hide, f"Спрятать ({key_display(S.hotkey_toggle)})"),
                ("compact", "compact", self.toggle_compact, "Компактно: только строка состояния"),
                ("help", "info", self.toggle_info, "Подсказки: что можно сказать и нажать"),
                ("settings", "settings", self.open_settings, "Настройки"),
                ("new", "new", self.reset, "Новая задача (очистить диалог)"),
                ("paste", "paste", self.paste_material, "Материалы: текст из буфера (Ctrl+V)"),
                ("attach", "attach", self.pick_files, "Материалы: прикрепить файлы")):
            b = IconButton(head, glyph_name, cmd, tip)
            b.pack(side="right", padx=(0, 2) if name != "close" else (0, 6))
            self.icons[name] = b
        self.status_lbl = tk.Label(head, text="", bg=T["BG2"], fg=T["FG"], font=F(-1), anchor="w", width=1)
        self.status_lbl.pack(side="left", fill="x", expand=True)
        self.status_tip = Tooltip(self.status_lbl, "")
        for w in (head, self.status_lbl, self.dot):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Double-Button-1>", lambda e: self.toggle_compact())

        self.mat_bar = tk.Frame(outer, bg=T["BG3"])
        self.mat_lbl = tk.Label(self.mat_bar, text="", bg=T["BG3"], fg=T["PURPLE"], font=F(-2),
                                anchor="w", justify="left")
        self.mat_lbl.pack(side="left", fill="x", expand=True, padx=(12, 4), pady=4)
        mat_x = tk.Label(self.mat_bar, text="✕ убрать", bg=T["BG3"], fg=T["MUTED"], font=F(-2), cursor=hand())
        mat_x.pack(side="right", padx=8)
        mat_x.bind("<Button-1>", lambda e: self.clear_materials())
        self.mat_bar.bind("<Configure>", lambda e: self.mat_lbl.config(wraplength=max(100, e.width - 110)))

        self.heard_lbl = tk.Label(outer, text="", bg=T["BG"], fg=T["MUTED"], font=F(-2), anchor="w", justify="left")
        self.heard_lbl.pack(fill="x", padx=14, pady=(6, 0))
        self.heard_lbl.bind("<Configure>", lambda e: self.heard_lbl.config(wraplength=max(100, e.width - 4)))

        body = self.body = tk.Frame(outer, bg=T["BG"])
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", bg=T["BG"], fg=T["FG"], bd=0, highlightthickness=0,
                            padx=14, pady=8, font=F(0), insertbackground=T["FG"], cursor=text_cursor(), height=1,
                            selectbackground=T["SEL"], selectforeground=T["FG"], spacing1=2, spacing2=2, spacing3=3)
        self.scroll = ThinScroll(body, self.text)
        self.text.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y", padx=(0, 2), pady=4)
        self.text.pack(side="left", fill="both", expand=True)
        self._config_tags()
        self.text.config(state="disabled")
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.text.bind(ev, self._user_scrolled, add="+")
        self.scroll.bind("<ButtonPress-1>", self._user_scrolled, add="+")  # тянет полосу — тоже «читает выше»
        self.text.bind("<ButtonPress-1>", lambda e: self.text.focus_set(), add="+")
        self.down_btn = IconButton(body, "down", self.scroll_to_last, "К последнему ответу", fg=T["FG"])
        self.down_btn.config(bg=T["BG4"])
        self.down_btn._bg = T["BG4"]
        self._down_shown = False

        foot = self.foot = tk.Frame(outer, bg=T["BG2"])
        foot.pack(fill="x", side="bottom", before=body)  # нижняя строка всегда видна, ответ занимает остальное
        grip = tk.Label(foot, text="◢", bg=T["BG2"], fg=T["FAINT"], font=F(-2))
        grip.pack(side="right", anchor="se", padx=(2, 3))
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_move)
        grip.bind("<ButtonRelease-1>", self._drag_end)
        self.shield_lbl = tk.Label(foot, text="", bg=T["BG2"], fg=T["MUTED"], font=F(-2), anchor="w",
                                   cursor=hand())
        self.shield_lbl.pack(side="left", padx=(12, 6), pady=5)
        self.shield_lbl.bind("<Button-1>", lambda e: self.show_capture_check())
        Tooltip(self.shield_lbl, "Проверить: показать снимок экрана таким, каким его видят на демонстрации")

        r.protocol("WM_DELETE_WINDOW", self._quit)
        # щелчок где угодно в окне (кроме самой кнопки «i») прячет подсказку
        r.bind("<ButtonPress-1>", lambda e: self.toggle_info() if getattr(self, "info_win", None) is not None
               and e.widget is not self.icons["help"] else None, add="+")
        # Ctrl+V в окне — текст из буфера в материалы (по коду клавиши: работает и в русской раскладке)
        r.bind("<Control-KeyPress>", self._on_ctrl_key)
        self._setup_drop()

        # Невидимость на демонстрации экрана: хук защищает каждое новое окно программы в момент создания
        # (в том числе стандартное окно выбора файлов 📎 и сообщения), основное окно — ещё до показа.
        self.guard = winsys.CaptureGuard(enabled=S.protect)
        self.guard.install()
        r.update_idletasks()
        self.guard.protect_tk(r)
        if self.compact:
            self._apply_compact()
        r.deiconify()
        self.guard.protect_tk(r)
        self._window_frame()
        self._refresh_shield()

    def _config_tags(self):
        t = self.text
        t.configure(font=F(0))
        # вопрос — на подложке во всю ширину окна (фон перевода строки тянется до правого края)
        t.tag_configure("user", foreground=T["ACCENT"], background=T["Q_BG"], font=F(0, "bold"), spacing1=6,
                        spacing3=6, lmargin1=10, lmargin2=10, rmargin=10)
        t.tag_configure("liveq", foreground=T["TEAL"], background=T["Q_BG"], font=F(0, "bold"), spacing1=6,
                        spacing3=6, lmargin1=10, lmargin2=10, rmargin=10)
        t.tag_configure("qpad", background=T["Q_BG"], font=F(-6))
        t.tag_configure("meta", foreground=T["MUTED"], font=F(-2))
        t.tag_configure("b", font=F(0, "bold"))
        t.tag_configure("h", font=F(1, "bold"), spacing1=6)
        t.tag_configure("ic", font=MONO(-1), background=T["CODE_BG"], foreground=T["IC_FG"])
        t.tag_configure("code", font=MONO(-1), background=T["CODE_BG"], foreground=T["CODE_FG"],
                        lmargin1=10, lmargin2=10, rmargin=6)
        t.tag_configure("codehdr", font=F(-3), background=T["CODE_BG"], foreground=T["MUTED"], justify="right",
                        lmargin1=10, lmargin2=10, rmargin=6, spacing1=4)
        t.tag_configure("link", foreground=T["MUTED"], font=F(-3))
        t.tag_configure("anslink", foreground=T["FAINT"], font=F(-3), justify="right", spacing1=2)
        t.tag_configure("dm", justify="center", spacing1=4, spacing3=4)
        t.tag_configure("err", foreground=T["ERR"])
        t.tag_configure("errhint", foreground=T["WARN"], font=F(-1))
        t.tag_configure("sep", background=T["BORDER"], font=(F()[0], 1), spacing1=0, spacing2=0, spacing3=0)
        t.tag_configure("gap", font=(F()[0], 4), spacing1=0, spacing2=0, spacing3=0)
        t.tag_configure("helph", font=F(0, "bold"), foreground=T["ACCENT"], spacing1=6)

    def _update_hint(self):
        if getattr(self, "info_win", None) is not None:  # клавиши поменялись — подсказка перерисуется
            self.toggle_info()

    def _place_window(self):
        r = self.root
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w = int(S.width or 560)
        h = int(S.height or sh * 0.6)
        x = S.pos_x if S.pos_x is not None else sw - w - 24
        y = S.pos_y if S.pos_y is not None else 40
        # положение могло остаться от второго монитора, которого больше нет — проверяем, что окно видно
        vx, vy, vw, vh = self._virtual_screen()
        if not (vx - w + 80 <= x <= vx + vw - 80 and vy <= y <= vy + vh - 60):
            x, y = sw - w - 24, 40
        self._full_h = h
        r.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

    def _virtual_screen(self):
        if IS_WIN:
            try:
                import ctypes
                gm = ctypes.windll.user32.GetSystemMetrics
                return gm(76), gm(77), gm(78), gm(79)
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _tk_error(self, exc, val, tb):
        import traceback
        print("[ошибка окна]\n" + "".join(traceback.format_exception(exc, val, tb)))
        try:
            self._write([(f"\nВнутренняя ошибка: {val}. Подробности — в журнале (⚙ → «Невидимость и система» → «Открыть журнал»).\n",
                          ("err",))])
        except Exception:
            pass

    # ------------------------------------------------------------ окно: перетаскивание, размер, компактный режим
    def _user_scrolled(self, _e=None):
        self.follow = False

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()
        self._dragged = False

    def _drag_move(self, e):
        self._dragged = True
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _drag_end(self, _e=None):
        self._save_geometry()

    def _resize_start(self, e):
        self._rs = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height())

    def _resize_move(self, e):
        x0, y0, w0, h0 = self._rs
        w, h = max(340, w0 + e.x_root - x0), max(220, h0 + e.y_root - y0)
        self.root.geometry(f"{w}x{h}")
        self._full_h = h

    def _save_geometry(self):
        """Положение и размер запоминаются между запусками."""
        r = self.root
        vals = {"pos_x": r.winfo_x(), "pos_y": r.winfo_y(), "width": r.winfo_width()}
        if not self.compact or self.expanded_for_answer:
            vals["height"] = r.winfo_height()
            self._full_h = r.winfo_height()
        S.update(**vals)

    def _geometry_matches(self):
        """Совпадает ли окно с сохранёнными настройками (тогда ничего двигать не надо)."""
        r = self.root
        if S.pos_x is None or S.pos_y is None:
            return False
        same = (r.winfo_x(), r.winfo_y(), r.winfo_width()) == (S.pos_x, S.pos_y, int(S.width))
        if not self.compact or self.expanded_for_answer:
            same = same and (not S.height or r.winfo_height() == int(S.height))
        return same

    def toggle_compact(self):
        if self.compact and not self.expanded_for_answer:
            self.expanded_for_answer = True   # развернуть на время
            self._apply_compact()
            return
        if self.compact and self.expanded_for_answer:
            self.expanded_for_answer = False
            self._apply_compact()
            return
        S.update(compact=True)

    def _apply_compact(self):
        """Компактный режим: только заголовок со статусом; при ответе окно разворачивается само."""
        small = self.compact and not self.expanded_for_answer
        r = self.root
        width = r.winfo_width() if r.winfo_width() > 100 else int(S.width or 560)  # до показа ширина ещё 1
        if small:
            for w in (self.mat_bar, self.heard_lbl, self.body, self.foot):
                w.pack_forget()
            r.geometry(f"{width}x{HEADER_H + 2}")
            self.icons["compact"].set_glyph("expand")
        else:
            self.foot.pack(fill="x", side="bottom")
            self.heard_lbl.pack(fill="x", padx=14, pady=(6, 0))
            self.body.pack(fill="both", expand=True)
            self._update_mat_bar()
            r.geometry(f"{width}x{max(220, int(self._full_h))}")
            self.icons["compact"].set_glyph("compact")

    def _expand_for_answer(self):
        if self.compact and not self.expanded_for_answer:
            self.expanded_for_answer = True
            self._apply_compact()

    # ------------------------------------------------------------ text helpers
    def _write(self, segments, at_end=True):
        at_bottom = self.text.bbox("end-1c") is not None  # низ окна был виден — значит, никто не читает выше
        self.text.config(state="normal")
        for s, tags in segments:
            self.text.insert("end", s, tags)
        self.text.config(state="disabled")
        if at_end and at_bottom:
            self.text.see("end")

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
                           "Открой мастер: ⚙ → «Невидимость и система» → «Проверить и починить» — он установит Claude Code "
                           "и поможет войти.")
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

    def _welcome(self, backend_ok, problem):
        """Окно при запуске пустое — подсказки по кнопке «i» в заголовке. Здесь только то, что мешает работать."""
        print("[запуск] режим:", self._mode_name() if backend_ok else "не настроен")
        if not backend_ok:
            self._write([(problem + "\n", ("err",))])
    def _render_answer(self, final=False):
        # Пока пользователь не листал сам — держим вопрос в самом верху окна: ответ дописывается ниже
        # и ничего не прыгает. Если листал — оставляем окно ровно там, где он читает.
        keep = None
        if not self.follow:
            top = self.text.index("@0,0")
            if self.text.compare(top, ">=", "ans_start"):
                n = self.text.count("ans_start", top, "chars")
                keep = (n[0] if isinstance(n, tuple) else n) or 0
        self.text.config(state="normal")
        self.text.delete("ans_start", "end-1c")
        blocks = code_blocks(self.cur_answer)
        for s, tags in md_segments(self.cur_answer, code_marks=True):
            if s == MATH:
                self._insert_math(*tags)
            elif s == CODE:
                n = tags[0]
                tag = f"cp{self.ans_no}_{n}"
                self.text.insert("end", "\n" if self.text.get("end-2c") != "\n" else "")
                self.text.insert("end", "⧉ Копировать" + (f" · {tags[1]}" if tags[1] else ""), ("codehdr", tag))
                self.text.insert("end", "\n", ("codehdr",))
                if n < len(blocks):
                    self._bind_link(tag, lambda b=blocks[n]: self._copy_text(b, "код"))
            else:
                self.text.insert("end", s, tags)
        self.text.config(state="disabled")
        if self.follow:
            self.text.yview("q_start")
        elif keep is not None:
            self.text.yview(f"ans_start + {keep} chars")
        self.dirty = False
        self.last_render = time.time()

    def _bind_link(self, tag, func):
        """Ссылка «Копировать». Привязка делается один раз на тег (перерисовка идёт ~16 раз в секунду —
        иначе копились бы тысячи команд Tcl), а что копировать — берётся из словаря."""
        links = self.__dict__.setdefault("_links", {})
        first = tag not in links
        links[tag] = func
        if not first:
            return
        t = self.text
        t.tag_bind(tag, "<Button-1>", lambda e: links[tag]())
        t.tag_bind(tag, "<Enter>", lambda e: t.tag_configure(tag, foreground=T["FG"], underline=True))
        t.tag_bind(tag, "<Leave>", lambda e: t.tag_configure(tag, foreground="", underline=False))

    def _copy_text(self, text, what):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.heard_lbl.config(text=f"Скопировано: {what} ({len(text)} знаков)")

    def _math_image(self, tex, display):
        """Картинка формулы (с кэшем) или None, если нарисовать не удалось."""
        key = (tex, display, S.font_size)
        if key in self.math_cache:
            return self.math_cache[key]
        imgs = None
        try:
            from PIL import Image, ImageTk
            dpi = self.root.winfo_fpixels("1i")
            size = S.font_size + (5 if display else 2)
            rows = [render_tex(r, size, dpi, T["FG"], T["BG"], pad=0.03 if display else 0.005)
                    for r in tex_rows(tex, display)]
            max_w = max(self.text.winfo_width() - 40, 200)
            imgs = []
            for im in rows:
                if im.width > max_w:  # длинная формула — уменьшаем под ширину окна
                    im = im.resize((max_w, max(1, int(im.height * max_w / im.width))), Image.LANCZOS)
                imgs.append(ImageTk.PhotoImage(im))
        except Exception as e:
            print("[math] не удалось нарисовать:", tex, "→", str(e).splitlines()[-1] if str(e) else e)
            imgs = None
        self.math_cache[key] = imgs
        return imgs

    def _insert_math(self, tex, display):
        imgs = self._math_image(tex, display)
        if not imgs:
            self.text.insert("end", tex if not display else tex.strip() + "\n", ("ic",))
            return
        for i, img in enumerate(imgs):
            start = self.text.index("end-1c")
            name = self.text.image_create("end", image=img, align="center", padx=1)
            self.__dict__.setdefault("math_names", {})[name] = (tex, display, i)  # для перерисовки при смене темы
            if display:
                self.text.insert("end", "\n")
                self.text.tag_add("dm", start, "end-1c")

    def _begin_exchange(self, question, with_screen, live=False, icon="🎧"):
        self.ans_no += 1
        self.text.config(state="normal")
        if self.text.compare("end-1c", ">", "1.0"):
            self.text.insert("end", "\n" if self.text.get("end-2c") != "\n" else "")
            self.text.insert("end", "\n", ("gap",))
            self.text.insert("end", " \n", ("sep",))  # тонкая линия во всю ширину между вопросами
            self.text.insert("end", "\n", ("gap",))
        self.text.mark_set("q_start", "end-1c")
        self.text.mark_gravity("q_start", "left")
        if live:
            self.text.insert("end", icon + " " + question + "\n", ("liveq",))
        else:
            self.text.insert("end", "› " + question + "\n", ("user",))
        if not with_screen and not live:
            self.text.insert("end", "(без скриншота)\n", ("meta",))
        self.text.insert("end", "\n", ("gap",))  # немного воздуха между вопросом и ответом
        self.text.mark_set("ans_start", "end-1c")
        self.text.mark_gravity("ans_start", "left")
        self.text.config(state="disabled")
        self.follow = True
        self.text.yview("q_start")
        self.cur_question, self.cur_answer = question, ""

    def scroll_to_last(self):
        """Кнопка «вниз»: к последнему вопросу (он встаёт вверх окна), дальше окно снова держит его."""
        self.follow = True
        try:
            self.text.yview("q_start")
        except tk.TclError:
            self.text.see("end")
        if self.text.bbox("end-1c") is None:
            self.text.see("end")

    def _update_down_btn(self):
        need = self.text.bbox("end-1c") is None and not self.follow
        if need != self._down_shown:
            self._down_shown = need
            if need:
                self.down_btn.place(relx=1.0, rely=1.0, x=-22, y=-10, anchor="se")
            else:
                self.down_btn.place_forget()

    # ------------------------------------------------------------ status
    def set_state(self, state, msg):
        self.state = (state, msg)
        self._refresh_status()

    def _refresh_status(self):
        state, msg = self.state
        listen = self._listen_status()
        if listen:
            color, msg = listen
        elif self.mic_on:
            color, msg = T["ACCENT"], "🎙 Слышу…" if not self.busy else msg + "  · 🎙"
        elif self.stt_on and not self.busy:
            color, msg = state_color("stt"), "Распознаю команду…"
        else:
            color = state_color(state)
        if (color, msg) != getattr(self, "_status_last", None):
            self._status_last = (color, msg)
            self.dot.itemconfigure(self._dot_item, fill=color)
            self.status_lbl.config(text=msg)
            self.status_tip.text = msg if len(msg) > 40 else ""
        if self.rec:  # мигающая точка во время записи
            self.dot.itemconfigure(self._dot_item, fill=color if int(time.time() * 2) % 2 else T["BG4"])

    def _idle(self):
        if not self.ready or self.fatal:
            return
        now = time.time()
        if now < self.forced_until:
            self.set_state("await", f"Слушаю вопрос… ({int(self.forced_until - now) + 1} с)")
        elif now < self.followup_until:
            self.set_state("followup", f"Можно дополнить без «Клод» ({int(self.followup_until - now) + 1} с)")
        elif self.download_info:
            self.set_state("download", f"⬇ Качаю модель распознавания: {self.download_info}")
        elif self.error_hint:
            self.set_state("error", self.error_hint)
        else:
            self.set_state("idle", f"Жду «Клод, …» или {key_display(S.hotkey_listen)}")

    # ------------------------------------------------------------ main loop
    def _poll(self):
        try:
            while True:
                self._handle(self.ui_q.get_nowait())
        except queue.Empty:
            pass
        except Exception as e:
            import traceback
            print("[ошибка] обработка события:\n" + traceback.format_exc())
            self._write([(f"\nВнутренняя ошибка: {e}\n", ("err",))])
        if self.dirty and time.time() - self.last_render > 0.06:
            self._render_answer()
        if self.rec and time.time() - self.rec["press"] > S.listen_max_seconds:
            self.listen_finish()
        if not self.busy and self.ready:
            self._idle()
        elif self.rec or self.listen_jobs:
            self._refresh_status()
        now = time.time()
        if now - getattr(self, "_slow_tick", 0) > 0.25:
            self._slow_tick = now
            self._update_down_btn()
            self._unminimize()
        self.root.after(30, self._poll)

    def _unminimize(self):
        """Win+D / «свернуть все» сворачивают и наше окно — оно превращается в серую полоску в углу экрана.
        Сразу разворачиваем обратно (спрятать окно можно клавишей или «Клод, скрой»)."""
        try:
            if self.visible and self.root.state() == "iconic":
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.guard.protect_tk(self.root)
        except tk.TclError:
            pass

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
            self._write([("\n" + msg[1] + "\n", ("err",))])
        elif kind == "mic_error":
            self.error_hint = "Микрофон не работает — ⚙ → Звук"
            self._write([("\n🎙 " + msg[1] + " Вопросы со звука компьютера работают и без микрофона.\n", ("err",))])
        elif kind == "mic":
            self.mic_on = msg[1]
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
                self._finish(note="[прервано: поменялись материалы или настройки — спроси ещё раз]")
        elif kind == "session":
            if msg[1] == self.session_gen:
                self.session_id = msg[2]
        elif kind in ("ptt", "talk"):
            self.forced_until = time.time() + 10
            self._idle()
        elif kind == "listen":
            self.listen_key()
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
            self._write([(msg[1] + "\n", ("meta",))])
        elif kind == "mat_add":
            self.materials.add(msg[1], msg[2], msg[3])
            self._write([(f"📎 Добавлено: {msg[1]} ({msg[3]}, {len(msg[2]):,} знаков)\n".replace(",", " "), ("meta",))])
        elif kind == "mat_err":
            self._write([(f"📎 {msg[1]}: {msg[2]}\n", ("err",))])
        elif kind == "mat_done":
            self.attach_busy = max(0, self.attach_busy - 1)
            if msg[1]:
                self._apply_materials(analyze=True)
        elif kind == "toggle":
            self.toggle()
        elif kind == "show":
            self.show()
            self.root.lift()
        elif kind == "settings_changed":
            self._on_settings(msg[1])
        elif kind == "tray":
            {"toggle": self.toggle, "settings": self.open_settings, "wizard": self.open_wizard,
             "quit": self._quit}.get(msg[1], lambda: None)()
        elif kind == "call":   # выполнить функцию в потоке окна (для окна настроек и проверок)
            msg[1]()
        elif kind == "quit":   # мастер попросил закрыться на время настройки
            self._quit()

    # ------------------------------------------------------------ voice commands
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
                self.heard_lbl.config(text="(не мне) " + text)
                print(f"[микрофон] фраза без «Клод» ({len(text.split())} слов) — не мне")  # чужую речь не пишем
                return
        print(f"[микрофон] команда: {text}")
        self.heard_lbl.config(text="Услышал: " + text)
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
            self.cancel(note="[остановлено]")
            return

        if low in ("скрой", "скройся", "спрячь", "спрячься", "скрой окно", "убери окно", "свернись"):
            self.hide()
            return
        if low in ("покажи", "покажись", "появись", "покажи окно", "вернись", "покажи ответ"):
            self.show()
            return

        if len(words) <= 3 and any(w in words for w in ("вниз", "ниже", "листай")):
            self.follow = False
            self.text.yview_scroll(8, "units")
            return
        if len(words) <= 3 and any(w in words for w in ("вверх", "выше", "наверх")):
            self.follow = False
            self.text.yview_scroll(-8, "units")
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

    # ------------------------------------------------------------ actions
    def ask(self, question, screen=True, prompt=None, listen=False, icon="🎧"):
        if self.busy:
            self.cancel(note="[прервано новым вопросом]")
        if not self.client and not self.cli and not self.provider:
            self._write([("\nНе настроено подключение к Claude (см. сообщение выше). Открой мастер: "
                          "⚙ → «Невидимость и система» → «Проверить и починить».\n", ("err",))])
            return
        use_session = bool(listen and self.cli)
        self.show()
        self._expand_for_answer()
        self.error_hint = ""

        img = None
        hidden = False
        if screen:
            self.set_state("think", "Делаю скриншот…")
            xy = (self.root.winfo_pointerx(), self.root.winfo_pointery())
            hidden = self._hide_for_capture()
            try:
                img = grab_screen(xy, S.listen_image_side if listen else S.max_image_side)
            except Exception as e:
                self._write([(f"\nНе удалось сделать скриншот: {e}\n", ("err",))])
            finally:
                self._restore_after_capture(hidden)

        content = []
        text = prompt or question
        if img is not None and self.cli and S.cli_image_mode == "file" and not use_session:
            path = self._save_shot(img)
            text = f"Скриншот экрана: {path}\n\nВопрос (распознан голосом): {text}"
        elif img is not None:
            b64, media = encode_image(img)
            content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}})
        content.append({"type": "text", "text": text})

        self._begin_exchange(question, img is not None, live=listen, icon=icon)
        self.ask_t0 = time.time()
        print(f"[вопрос] {'звук компьютера' if listen else 'голос'}, "
              + ("без скриншота" if img is None else
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
        if not self.visible:
            return False
        if self.guard.fully_hidden():
            return False  # окна и так нет в захвате экрана — прятать не нужно, ничего не мигает
        if IS_WIN or IS_MAC:
            self.root.attributes("-alpha", 0.0)
        else:
            self.root.withdraw()
        self.root.update()
        time.sleep(0.15)
        return True

    def _restore_after_capture(self, hidden):
        if not hidden:
            return
        if IS_WIN or IS_MAC:
            self.root.attributes("-alpha", float(S.alpha))
        else:
            self.root.deiconify()
            self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.guard.protect_tk(self.root)

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
        if not self.cli:  # в режиме подписки историю хранит сам Claude Code
            if answer:
                self.history.append({"role": "assistant", "content": answer + ("\n" + note if note else "")})
            elif self.history and self.history[-1]["role"] == "user":
                self.history.pop()
        self._render_answer(final=True)
        if answer and not error:
            tag = f"cpa{self.ans_no}"
            self._write([("⧉ Копировать ответ\n", ("anslink", tag))], at_end=False)
            self._bind_link(tag, lambda a=answer: self._copy_text(a, "ответ"))
        if error:
            hint = (providers.explain(str(error)) if self.provider else "") or explain_error(error)
            print("[claude] ошибка:", error)
            self._write([(f"\nОшибка: {error}\n", ("err",))] + ([("→ " + hint + "\n", ("errhint",))] if hint else []))
            self.error_hint = "Ошибка — что делать, написано в окне"
        elif note:
            self._write([(note + "\n", ("meta",))])
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
            self._write([("\n🎧 " + sa.error + "\n", ("err",))])
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
        self._refresh_status()

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
        self._write([("🎧 Запись вопроса отменена.\n", ("meta",))])
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
            self._write([("\n🎧 За эти секунды компьютер не играл звук — распознавать нечего. Если звук был, "
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
            self._write([(f"\n🎧 {err}\n", ("err",))])
            self._idle()
            return
        text = (text or "").strip()
        print(f"[F7] {job['dur']:.1f} с звука («{job['dev']}»), язык {lang or '?'}, распознано за {secs:.1f} с: {text}")
        if not text or is_junk(text):
            self._write([("\n🎧 В записи не нашлось речи.\n", ("meta",))])
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

    def _listen_status(self):
        """Строка состояния для F7 (или None, если ничего не пишем и не распознаём)."""
        k = key_display(S.hotkey_listen)
        if self.rec:
            el = int(time.time() - self.rec["press"])
            lvl = level_bars(self.sysaudio.level()) if self.sysaudio else ""
            return T["REC"], f"🔴 Запись вопроса {el // 60}:{el % 60:02d}  {lvl}  · {k} — готово · Esc — отмена"
        stages = {j.get("stage") for j in self.listen_jobs.values()}
        if "tail" in stages:
            return T["TEAL"], "⏳ Дослушиваю секунду…"
        if "stt" in stages:
            msg = "📝 Распознаю вопрос…"
            if self.listen_model_state[0] != "ready":
                msg += " (точная модель ещё загружается)"
            return T["TEAL"], msg
        return None

    def on_mic_model(self, state, info):
        if state == "progress":
            self.download_info = info.get("text", "") if isinstance(info, dict) else str(info)
            if not self.ready:
                self.set_state("download", f"⬇ Скачиваю модель распознавания команд: {self.download_info}")
            return
        if state == "loading":
            print(f"[whisper] команды: загружаю {info}")
        elif state == "ready":
            self.download_info = ""
            self.mic_model_info = info
            if self.ready and getattr(self, "_mic_model_switch_shown", False):
                self._write([(f"🎙 Команды: теперь распознаёт {info}.\n", ("meta",))])
            self._mic_model_switch_shown = True
        elif state == "error":
            self.download_info = ""
            self._write([(f"🎙 Модель для команд не загрузилась ({info}) — осталась прежняя.\n", ("err",))])

    def on_listen_model(self, state, info):
        if state == "progress":
            self.download_info = info.get("text", "") if isinstance(info, dict) else str(info)
            if not self.busy:
                self._idle()
            return
        if state == "download":
            now = self.listen_model_state[1] if self.listen_model_state[0] == "ready" else ""
            size = stt.fmt_size(stt.model_size_bytes(info))
            self._write([(f"🎧 В фоне качаю модель распознавания {info} (~{size}, один раз)"
                          + (f". {key_display(S.hotkey_listen)} пока работает на {now.split(' ·')[0]}" if now else "")
                          + ".\n", ("meta",))])
            return
        if state == "upgraded":
            self.download_info = ""
            self.listen_model_state = ("ready", info)
            self._write([(f"🎧 {key_display(S.hotkey_listen)}: теперь распознаёт {info}.\n", ("meta",))])
            return
        if state == "upgrade_fail":
            self.download_info = ""
            self._write([(f"🎧 Модель не загрузилась ({info}) — {key_display(S.hotkey_listen)} работает на прежней.\n",
                          ("meta",))])
            return
        self.listen_model_state = (state, info)
        if state == "ready":
            print(f"[whisper] звук компьютера готов: {info}")
        elif state == "fallback":
            self._write([(f"🎧 Точная модель не загрузилась ({info}) — будет модель микрофона.\n", ("err",))])
        elif state == "error":
            self._write([(f"\n🎧 Вопросы со звука компьютера не будут работать: {info}\n", ("err",))])

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
            self._write([("\n🎧 " + sa.error + "\n", ("err",))])

    def _ensure_listen_session(self):
        if self.listen_session is None:
            self.listen_session = ClaudeSession(self.ui_q, self.cli, os.path.join(WORKDIR, "listen_prompt.txt"),
                                                S.listen_model, S.listen_effort, S.listen_max_turns)
        if not self.listen_session.alive():
            self.listen_session.start()

    # ------------------------------------------------------------ материалы (📎)
    def pick_files(self):
        from tkinter import filedialog
        # окно выбора файлов — стандартное окно Windows; хук невидимости прячет его от захвата в момент создания
        paths = filedialog.askopenfilenames(
            parent=self.root, title="Материалы для Claude: лекции, конспекты, вопросы",
            filetypes=[("Документы и картинки", "*.pdf *.docx *.pptx *.txt *.md *.png *.jpg *.jpeg *.webp"),
                       ("Все файлы", "*.*")])
        if paths:
            self.attach_files(list(paths))

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
            self._write([("📋 В буфере обмена нет текста. Скопируй текст (Ctrl+C) и нажми 📋 ещё раз.\n", ("meta",))])

    def _on_ctrl_key(self, e):
        if e.keycode == 86 or (e.keysym or "").lower() == "v":  # V — и в русской раскладке
            self.paste_material()
            return "break"
        if e.keycode == 67 or (e.keysym or "").lower() == "c":  # Ctrl+C — скопировать выделенное
            try:
                sel = self.text.get("sel.first", "sel.last")
            except tk.TclError:
                sel = ""
            if sel:
                self._copy_text(sel, "выделенный текст")
            return "break"

    def _setup_drop(self):
        """Перетаскивание файлов и текста в окно (если доступна библиотека tkinterdnd2)."""
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES, DND_TEXT
            TkinterDnD._require(self.root)
            for w in (self.text, self._head, self.status_lbl, self.heard_lbl, self.mat_lbl):
                w.drop_target_register(DND_FILES, DND_TEXT)
                w.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_ok = True
        except Exception as e:
            self.drop_ok = False
            print("[📎] перетаскивание файлов недоступно:", e)

    def _on_drop(self, event):
        data = event.data or ""
        try:
            items = list(self.root.tk.splitlist(data))
        except Exception:
            items = [data]
        files = [x for x in items if os.path.isfile(x)]
        if files:
            self.attach_files(files)
        elif data.strip():
            self.attach_text(data, "Перетащенный текст")
        return "copy"

    def attach_files(self, paths):
        self.show()
        self._expand_for_answer()
        self.attach_busy += 1
        cli = self.cli or find_claude()  # сканы и картинки читает Claude Code — даже если отвечает другой ИИ

        def work():
            added = 0
            for path in paths:
                name = os.path.basename(path)
                self.ui_q.put(("mat_status", f"📎 Читаю «{name}»…"))
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
        self._write([(f"📎 Добавлено: {title} ({len(text.strip()):,} знаков)\n".replace(",", " "), ("meta",))])
        self._apply_materials(analyze=True)

    def clear_materials(self):
        if not self.materials.items:
            return
        self.materials.clear()
        self._apply_materials(analyze=False)
        self._write([("📎 Материалы убраны.\n", ("meta",))])

    def remove_material(self, mid):
        it = next((x for x in self.materials.items if x["id"] == mid), None)
        if it and self.materials.remove(mid):
            self._apply_materials(analyze=False)
            self._write([(f"📎 Убрано: {it['title']}\n", ("meta",))])

    def _hotwords(self):
        terms = []
        if S.materials_hotwords and self.materials.items:
            terms = material_terms(self.materials.full_text()[0], S.materials_hotwords)
        hint = [t.strip() for t in (S.listen_hint or "").split(",") if t.strip()]
        out = ", ".join(dict.fromkeys(hint + terms))
        return out or None

    def _update_mat_bar(self):
        small = self.compact and not self.expanded_for_answer
        if self.materials.items and not small:
            _, cut = self.materials.full_text()
            self.mat_lbl.config(text="📎 Материалы: " + self.materials.summary()
                                + (" (слишком много — часть обрезана)" if cut else ""))
            self.mat_bar.pack(fill="x", after=self._head)
        else:
            self.mat_bar.pack_forget()

    def _apply_materials(self, analyze):
        """Материалы поменялись: новые инструкции, новый диалог, новые подсказки для распознавания."""
        self._write_prompts()
        self.session_id = None
        self.session_gen += 1
        self.history.clear()
        if self.busy and self.via_listen:  # шёл разбор прошлых материалов — новый важнее
            self._finish(note="[прервано: добавились новые материалы]")
        if self.listen_session:
            self.listen_session.stop()  # перезапустится с новыми материалами при следующем вопросе
        if self.listen_tr:
            self.listen_tr.hotwords = self._hotwords()
        self._update_mat_bar()
        if analyze and self.materials.items and (self.cli or self.client or self.provider) and not self.busy:
            titles = ", ".join(it["title"] for it in self.materials.items[-3:])
            self.ask("Материалы: " + titles, screen=False, prompt=analyze_prompt(), listen=True, icon="📎")

    def cancel(self, note="[остановлено]"):
        if self.busy:
            self._finish(note=note)

    def reset(self):
        self.cancel(note="[остановлено]")
        if self.listen_session:
            self.listen_session.stop()  # и вопросы с компьютера начинаем с чистого листа
        self.history.clear()
        self.session_id = None
        self.session_gen += 1
        self.followup_until = 0.0
        self.error_hint = ""
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self._write([("Новая задача — контекст очищен.\n", ("meta",))])

    def copy(self, code_only=False):
        src = self.cur_answer or self.last_answer
        if not src:
            return
        text = (last_code_block(src) if code_only else None) or src
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._write([("Скопировано " + ("код" if code_only and last_code_block(src) else "ответ")
                      + " в буфер обмена.\n", ("meta",))])

    def hide(self):
        if self.visible:
            self.root.withdraw()
            self.visible = False

    def show(self):
        if not self.visible:
            self.guard.protect_tk(self.root)
            self.root.deiconify()
            if not (IS_WIN or IS_MAC):
                self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.guard.protect_tk(self.root)
            self.visible = True

    def toggle(self):
        self.hide() if self.visible else self.show()

    def _hotkey_actions(self):
        return {"talk": S.hotkey_talk, "toggle": S.hotkey_toggle, "listen": S.hotkey_listen}

    def _start_tray(self):
        from .tray import Tray
        if self.tray is None:
            self.tray = Tray(lambda ev: self.ui_q.put(("tray", ev)))
        if not self.tray.start():
            self._write([(f"Значок в трее не запустился: {self.tray.error}\n", ("err",))])

    # ------------------------------------------------------------ невидимость на демонстрации экрана
    def _refresh_shield(self):
        level, text = self.guard.status(self.root)
        if (level, text) != getattr(self, "_shield_last", None):
            self._shield_last = (level, text)
            color = {"ok": T["OK"], "partial": T["WARN"]}.get(level, T["ERR"])
            short = {"ok": "🛡 Скрыт от демонстрации экрана", "partial": "⚠ Скрыт не полностью (старая Windows)",
                     "off": "⚠ Не скрыт: невидимость выключена"}.get(level, "⚠ Не скрыт")
            self.shield_lbl.config(text=short, fg=color)
            print("[невидимость]", text, "| окна:", [(hex(h), a) for h, a in self.guard.window_states()])
        self.root.after(3000, self._refresh_shield)

    def capture_check(self):
        """Снимок экрана тем же способом, что у программ демонстрации. → (картинка, прямоугольник окна, ок, текст)."""
        hwnd = winsys.tk_hwnd(self.root)
        shot, rect = winsys.grab_monitor_of(hwnd)
        seen = winsys.region_looks_like(shot, rect, [T["BG"], T["BG2"]]) if self.visible else 0.0
        level, status = self.guard.status(self.root)
        # решает защита окна (Windows сама сообщает, что окно исключено из захвата); сравнение цветов —
        # только для журнала: на тёмном фоне за окном оно давало ложную тревогу
        ok = level == "ok"
        print(f"[невидимость] проверка: {status}; доля цветов окна в снимке {seen:.2f}")
        if ok:
            msg = ("✓ Окна оверлея на снимке нет. Так тебя видят в Zoom, Teams, Discord, Google Meet, OBS и на "
                   "скриншотах. Оранжевая рамка — где окно стоит на самом деле (на демонстрации её нет).")
        else:
            msg = "⚠ " + (status if level != "ok" else "Окно оверлея видно на снимке!") + \
                  " Оранжевая рамка — где стоит окно."
        return shot, rect, ok, msg

    def show_capture_check(self, parent=None):
        from .ui_dialogs import show_capture_check
        show_capture_check(self, parent)

    # ------------------------------------------------------------ настройки, справка, мастер
    def open_settings(self, tab=None):
        from .ui_settings import SettingsWindow
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.focus(tab)
            return
        self.settings_win = SettingsWindow(self, tab)

    def toggle_info(self):
        """Кнопка «i»: короткая подсказка выпадает под заголовком; повторное нажатие (или щелчок в окне) прячет."""
        win = getattr(self, "info_win", None)
        if win is not None:
            self.info_win = None
            try:
                win.destroy()
            except tk.TclError:
                pass
            return
        k, t8, t9 = key_display(S.hotkey_listen), key_display(S.hotkey_talk), key_display(S.hotkey_toggle)
        rows = [("«Клод, …»", "вопрос по экрану: сделаю скриншот под курсором и отвечу"),
                ("«Клод, дополни…»", f"тот же диалог; {S.followup_seconds} с после ответа можно без «Клод»"
                 if S.followup_seconds else "тот же диалог продолжается"),
                ("«Клод, новая задача»", "очистить диалог · «стоп» · «скопируй код» · «скрой»"),
                (k, "вопрос со звука компьютера (лекция, созвон): нажми в начале и в конце · Esc — отмена"),
                (t8, "следующая фраза — команда без «Клод»"),
                (t9, "спрятать / показать окно"),
                ("📎  📋", "материалы: файлы, текст из буфера или перетащи файл в окно")]
        w = self.info_win = tk.Toplevel(self.root)
        w.withdraw()
        if IS_WIN:
            w.attributes("-toolwindow", True)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=T["BORDER"])
        box = tk.Frame(w, bg=T["BG3"])
        box.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(box, text="Как пользоваться", bg=T["BG3"], fg=T["FG"], font=F(1, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(12, 6))
        width = max(300, self.root.winfo_width() - 24)
        for key, what in rows:
            r = tk.Frame(box, bg=T["BG3"])
            r.pack(fill="x", padx=14, pady=2)
            tk.Label(r, text=key, bg=T["BG3"], fg=T["ACCENT"], font=F(-1, "bold"), anchor="nw", width=17,
                     justify="left").pack(side="left", anchor="n")
            tk.Label(r, text=what, bg=T["BG3"], fg=T["FG"], font=F(-1), anchor="w", justify="left",
                     wraplength=width - 190).pack(side="left", fill="x", expand=True)
        notes = [f"Отвечает: {self._mode_name()}" if (self.cli or self.client or self.provider) else ""]
        if not os.path.isfile(SETUP_STATE_PATH):
            notes.append("Совет: один раз проверь всё мастером — ⚙ → «Невидимость и система» → «Проверить и починить».")
        for n in filter(None, notes):
            tk.Label(box, text=n, bg=T["BG3"], fg=T["MUTED"], font=F(-2), anchor="w", justify="left",
                     wraplength=width - 30).pack(fill="x", padx=14, pady=(6, 0))
        foot = tk.Frame(box, bg=T["BG3"])
        foot.pack(fill="x", padx=14, pady=(10, 12))
        more = tk.Label(foot, text="Вся справка →", bg=T["BG3"], fg=T["INFO"], font=F(-1), cursor=hand())
        more.pack(side="left")
        more.bind("<Button-1>", lambda e: (self.toggle_info(), self.open_help()))
        close = tk.Label(foot, text="Понятно", bg=T["BG3"], fg=T["MUTED"], font=F(-1), cursor=hand())
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.toggle_info())
        w.bind("<Escape>", lambda e: self.toggle_info())
        w.update_idletasks()
        x = self.root.winfo_x() + 12
        y = self.root.winfo_y() + HEADER_H + 4
        w.geometry(f"{width}x{w.winfo_reqheight()}+{x}+{y}")
        self.guard.protect_tk(w)
        w.deiconify()
        self.guard.protect_tk(w)
        winsys.style_frame(winsys.tk_hwnd(w), T["BORDER"])

    def open_help(self):
        from .ui_dialogs import show_help
        show_help(self)

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
        """Настройки поменялись в окне ⚙ — применяем сразу, без перезапуска (кроме темы)."""
        if changed <= {"pos_x", "pos_y", "width", "height"} and self._geometry_matches():
            return  # это мы сами запомнили положение после перетаскивания
        if changed & {"prompt_system", "prompt_listen", "student_style", "math_render", "listen_style",
                      "cli_image_mode", "materials_max_chars"}:
            self._write_prompts()
            if self.listen_session:
                self.listen_session.stop()
        if changed & {"listen_model", "listen_effort", "listen_max_turns"} and self.listen_session:
            self.listen_session.stop()
            self.listen_session = None
        if changed & {"backend", "claude_cmd", "provider", "provider_base_url", "provider_model",
                      "provider_listen_model", "provider_vision", "api_key_saved"}:
            ok, problem = self._init_backend()
            self.session_id = None
            self.session_gen += 1
            if self.listen_session:
                self.listen_session.stop()
                self.listen_session = None
            self._write([(("Подключение к ИИ: " + self._mode_name() + "\n")
                          if ok else ("\n" + problem + "\n"), ("meta",) if ok else ("err",))])
        if changed & {"hotkey_talk", "hotkey_toggle", "hotkey_listen"}:
            self.hk.set_binds(self._hotkey_actions())
            self._update_hint()
        if "alpha" in changed:
            try:
                self.root.attributes("-alpha", float(S.alpha))
            except tk.TclError:
                pass
            self.guard.protect_tk(self.root)
        if "protect" in changed:
            self.guard.set_enabled(S.protect)
            self._shield_last = None
        if "tray" in changed:
            if S.tray:
                self._start_tray()
            elif self.tray:
                self.tray.stop()
        if "font_size" in changed:
            self._config_tags()
            for w in (self.status_lbl,):
                w.config(font=F(-1))
            for w in (self.heard_lbl, self.mat_lbl, self.shield_lbl):
                w.config(font=F(-2))
            self.math_cache.clear()
        if "compact" in changed:
            self.compact = bool(S.compact)
            self.expanded_for_answer = False
            self._apply_compact()
        if changed & {"width", "height", "pos_x", "pos_y"} and not self._geometry_matches():
            self._place_window()
            if self.compact and not self.expanded_for_answer:
                self._apply_compact()
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
        """Новая тема — сразу во всех окнах, без перезапуска (формулы перерисовываются новыми цветами)."""
        if not apply_theme(S.theme, self.root):
            return
        self._status_last = self._shield_last = None
        self._refresh_status()
        self.math_cache.clear()
        names = getattr(self, "math_names", {})
        for _key, name, index in self.text.dump("1.0", "end", image=True):
            info = names.get(name)
            imgs = self._math_image(info[0], info[1]) if info else None
            if imgs and info[2] < len(imgs):
                self.text.image_configure(index, image=imgs[info[2]])
        self._window_frame()
        print("[тема]", S.theme)

    def _window_frame(self):
        """Windows 11: скруглённые углы и тонкая рамка цвета темы (на старых Windows просто ничего не меняется)."""
        winsys.style_frame(winsys.tk_hwnd(self.root), T["BORDER"])

    def restart_mic(self):
        if self.listener:
            self.listener.stop()
        self.error_hint = ""
        self.listener = Listener(self.audio_q, self.ui_q)
        self.listener.start()

    def _quit(self):
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
            self.root.destroy()
        finally:
            os._exit(0)

    def run(self):
        self.root.mainloop()
