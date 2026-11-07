# -*- coding: utf-8 -*-
"""Окно настроек ⚙. Всё, что раньше правилось константами в коде, правится здесь; сохраняется в
workspace/settings.json и применяется сразу (тема — после перезапуска)."""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

from . import stt, winsys
from .audio import list_input_devices, level_fraction, load_wav
from .claude import find_claude, claude_version, check_login, explain_error
from .config import S, DEFAULTS, LOG_PATH, HERE, LAST_F7_WAV, load_api_key, save_api_key, mask_secret
from .hotkeys import ACTION_TITLES, display as key_display, problems as key_problems, parse_spec
from .prompts import default_system_prompt, default_listen_prompt, ANALYZE_PROMPT
from .setup_tools import autostart_enabled, set_autostart
from .ui_dialogs import make_dialog, show_dialog, show_text
from .ui_theme import (T, F, MONO, Button, Toggle, Slider, Choice, Meter, ScrollFrame, label, card, row,
                       entry, text_cursor, THEME_NAMES, glyph, hand)

TABS = [
    ("stt", "Распознавание речи", "mic"),
    ("sound", "Звук", "play"),
    ("claude", "Подключение к ИИ", "help"),
    ("keys", "Клавиши", "settings"),
    ("look", "Внешний вид", "eye"),
    ("materials", "Материалы", "attach"),
    ("system", "Невидимость и система", "shield"),
]

LANG_OPTS = [("auto", "Определять самому (рус / укр / англ)"), ("ru", "Русский"), ("uk", "Украинский"),
             ("en", "Английский")]
CLAUDE_MODELS = [("sonnet", "Sonnet — умный и быстрый (по умолчанию)"), ("opus", "Opus — самый умный, медленнее"),
                 ("haiku", "Haiku — самый быстрый, проще")]
API_MODELS = [("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-opus-5-5", "Opus 5.5"), ("claude-haiku-5-5", "Haiku 5.5")]
EFFORTS = [("low", "Мало — отвечать сразу"), ("medium", "Средне"), ("high", "Много — дольше, но тщательнее"),
           ("", "Как в настройках Claude Code")]


class NavItem(tk.Frame):
    """Пункт списка вкладок: значок + название."""

    def __init__(self, parent, title, icon, on_click, is_current):
        super().__init__(parent, bg=T["BG2"], cursor=hand())
        g, gf = glyph(icon)
        self.icon = tk.Label(self, text=g, font=gf, bg=T["BG2"], fg=T["MUTED"], width=2)
        self.icon.pack(side="left", padx=(10, 6), pady=8)
        self.text = tk.Label(self, text=title, font=F(0), bg=T["BG2"], fg=T["MUTED"], anchor="w")
        self.text.pack(side="left", fill="x", expand=True)
        self.is_current = is_current
        for w in (self, self.icon, self.text):
            w.bind("<Button-1>", lambda e: on_click())
            w.bind("<Enter>", lambda e: self._paint(hover=True))
            w.bind("<Leave>", lambda e: self._paint())

    def _paint(self, hover=False):
        cur = self.is_current()
        bg = T["BG3"] if cur else (T["BG4"] if hover else T["BG2"])
        fg = T["FG"] if cur or hover else T["MUTED"]
        tk.Frame.configure(self, bg=bg)
        for w in (self.icon, self.text):
            w.config(bg=bg)
        self.icon.config(fg=T["ACCENT"] if cur else fg)
        self.text.config(fg=fg)

    own_children = True

    def repaint(self):
        self._paint()

    def retheme(self, cmap):
        self._paint()


class SettingsWindow:
    def __init__(self, app, tab=None):
        self.app = app
        self.q = queue.Queue()
        self.top = make_dialog(app, "Настройки — Claude Overlay", size="980x700")
        self.top.minsize(820, 520)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", lambda e: self.close())
        self.pages = {}
        self.nav = {}
        self.cur = None
        self.meters = []          # (Meter, функция → громкость 0…1)
        self.model_rows = {}
        self.downloading = set()
        self.sizes = {}
        self.hw = None
        self._closed = False

        nav = tk.Frame(self.top, bg=T["BG2"], width=230)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        label(nav, "Настройки", size=4, bold=True).pack(anchor="w", padx=18, pady=(18, 12))
        for key, title, icon in TABS:
            item = NavItem(nav, title, icon, lambda k=key: self.show(k), lambda k=key: self.cur == k)
            item.pack(fill="x", padx=8, pady=1)
            self.nav[key] = item
        label(nav, "Изменения сохраняются сразу.", muted=True, size=-2, wrap=200).pack(side="bottom", anchor="w",
                                                                                     padx=18, pady=14)
        self.content = tk.Frame(self.top, bg=T["BG"])
        self.content.pack(side="left", fill="both", expand=True)

        threading.Thread(target=self._load_info, daemon=True).start()
        self.show(tab or "stt")
        show_dialog(app, self.top)
        self._tick()

    # ------------------------------------------------------------ каркас
    def alive(self):
        return not self._closed

    def focus(self, tab=None):
        if tab:
            self.show(tab)
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()

    def close(self):
        self._closed = True
        if self.app.hk.capture is not None:
            self.app.hk.capture = None
        self.top.destroy()

    def show(self, key):
        if self.cur == key:
            return
        if self.cur in self.pages:
            self.pages[self.cur].pack_forget()
        self.cur = key
        for item in self.nav.values():
            item.repaint()
        if key not in self.pages:
            sf = ScrollFrame(self.content, bg=T["BG"])
            self.pages[key] = sf
            getattr(self, "_page_" + key)(sf.body)
        self.pages[key].pack(fill="both", expand=True)

    def _title(self, parent, text, sub=None):
        label(parent, text, size=5, bold=True).pack(anchor="w", padx=16, pady=(18, 2))
        if sub:
            label(parent, sub, muted=True, size=-1, wrap=680).pack(anchor="w", padx=16, pady=(0, 12))

    def _tick(self):
        if self._closed:
            return
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        for m, f in list(self.meters):
            try:
                if m.winfo_ismapped():
                    m.set(f())
            except tk.TclError:
                self.meters.remove((m, f))
            except Exception:
                pass
        self.top.after(80, self._tick)

    def later(self, fn):
        """Из другого потока: выполнить fn в потоке окна."""
        self.q.put(fn)

    def _load_info(self):
        self.hw = stt.hardware_info()
        self.later(self._refresh_hw)
        self.sizes = stt.remote_sizes()
        self.later(self._refresh_models)

    # ------------------------------------------------------------ 1. распознавание речи
    def _page_stt(self, p):
        self._title(p, "Распознавание речи",
                    "Речь распознаётся на твоём компьютере — звук никуда не уходит. Для команд «Клод, …» и для "
                    "вопросов со звука компьютера (F7) можно выбрать разные модели.")
        c = card(p, "Команды с микрофона («Клод, …»)")
        self.mic_model = Choice(row(c, "Модель"), self._model_opts(False), S.whisper_model,
                                lambda v: S.update(whisper_model=v))
        self.mic_model.pack()
        Choice(row(c, "Язык"), LANG_OPTS, S.language, lambda v: S.update(language=v)).pack()
        self._text_setting(row(c, "Подсказки распознаванию", "Термины, имена — через запятую"), "mic_hint")

        c = card(p, f"Звук компьютера ({key_display(S.hotkey_listen)})")
        self.listen_model = Choice(row(c, "Модель", "«Авто»: с видеокартой — large-v3, без неё — large-v3-turbo"),
                                   self._model_opts(True), S.listen_whisper_model,
                                   lambda v: S.update(listen_whisper_model=v))
        self.listen_model.pack()
        Choice(row(c, "Язык"), LANG_OPTS, S.listen_language, lambda v: S.update(listen_language=v)).pack()
        self._text_setting(row(c, "Подсказки распознаванию",
                               "Термины предмета, фамилии — через запятую. Термины из материалов добавляются сами."),
                           "listen_hint")

        c = card(p, "Где распознавать")
        Choice(row(c, "Видеокарта или процессор", "Меняется после перезапуска оверлея"),
               [("auto", "Видеокарта NVIDIA, если готова (рекомендуется)"), ("cpu", "Всегда процессор")],
               S.whisper_device, lambda v: S.update(whisper_device=v), width=40).pack()
        self._text_setting(row(c, "Языки для «определять самому»", "Коды через запятую: ru, uk, en, de, pl…"),
                           "listen_languages", is_list=True, width=20)

        c = card(p, "Модели", "Скачанные модели лежат в общей папке моделей HuggingFace на этом компьютере.")
        self.hw_lbl = label(c, "Смотрю, что за компьютер…", muted=True, wrap=680)
        self.hw_lbl.pack(anchor="w", pady=(0, 8))
        self.models_box = tk.Frame(c, bg=T["BG2"])
        self.models_box.pack(fill="x")
        self._build_model_rows()

        c = card(p, "Сравнить модели",
                 f"Распознать последнюю запись {key_display(S.hotkey_listen)} несколькими моделями и показать тексты "
                 "рядом — так видно, какая лучше разбирает твою лекцию.")
        self.cmp_info = label(c, "", muted=True, size=-1)
        self.cmp_info.pack(anchor="w")
        self.cmp_checks = tk.Frame(c, bg=T["BG2"])
        self.cmp_checks.pack(fill="x", pady=6)
        self.cmp_vars = {}
        self.cmp_btn = Button(c, "Сравнить", self._compare, kind="primary")
        self.cmp_btn.pack(anchor="w", pady=(4, 0))
        self.cmp_out = tk.Frame(c, bg=T["BG2"])
        self.cmp_out.pack(fill="x", pady=(8, 0))
        self._refresh_compare_box()

    def _model_opts(self, listen):
        opts = [("auto", "Авто (рекомендуемая для этого компьютера)")] if listen else []
        for m in stt.MODELS:
            meta = stt.model_meta(m[0])
            opts.append((m[0], f"{m[0]} — {meta['accuracy']}, {meta['speed']}"))
        return opts

    def _build_model_rows(self):
        box = self.models_box
        for w in box.winfo_children():
            w.destroy()
        self.model_rows = {}
        rec = stt.recommend(self.hw) if self.hw else {}
        head = tk.Frame(box, bg=T["BG2"])
        head.pack(fill="x")
        for text, w in (("Модель", 17), ("Размер", 8), ("Точность / скорость", 34), ("", 30)):
            tk.Label(head, text=text, bg=T["BG2"], fg=T["FAINT"], font=F(-2), anchor="w", width=w).pack(side="left")
        for name in stt.MODEL_NAMES:
            meta = stt.model_meta(name)
            r = tk.Frame(box, bg=T["BG3"], highlightthickness=0)
            r.pack(fill="x", pady=2)
            left = tk.Frame(r, bg=T["BG3"])
            left.pack(side="left", fill="x", expand=True, padx=10, pady=6)
            top = tk.Frame(left, bg=T["BG3"])
            top.pack(fill="x")
            tk.Label(top, text=name, bg=T["BG3"], fg=T["FG"], font=F(0, "bold"), anchor="w").pack(side="left")
            tags = []
            if rec.get("listen") == name:
                tags.append(f"рекомендуем для {key_display(S.hotkey_listen)}")
            if rec.get("mic") == name:
                tags.append("рекомендуем для команд")
            for tg in tags:
                tk.Label(top, text=tg, bg=T["ACCENT"], fg="#ffffff", font=F(-3, "bold"), padx=6).pack(side="left",
                                                                                                    padx=(8, 0))
            used = []
            if S.whisper_model == name:
                used.append("команды")
            if (S.listen_whisper_model == name) or (S.listen_whisper_model == "auto" and
                                                    stt.listen_model_name(stt.whisper_device()) == name):
                used.append(key_display(S.hotkey_listen))
            if used:
                tk.Label(top, text="выбрана: " + ", ".join(used), bg=T["BG3"], fg=T["OK"], font=F(-2)).pack(
                    side="left", padx=(8, 0))
            info = f"{meta['accuracy']} · {meta['speed']} · {meta['when']}"
            tk.Label(left, text=info, bg=T["BG3"], fg=T["MUTED"], font=F(-2), anchor="w", justify="left",
                     wraplength=430).pack(fill="x")
            status = tk.Label(left, text="", bg=T["BG3"], fg=T["MUTED"], font=F(-2), anchor="w")
            status.pack(fill="x")
            prog = Meter(left, width=300, height=6, color=T["ACCENT"])
            right = tk.Frame(r, bg=T["BG3"])
            right.pack(side="right", padx=8, pady=6)
            b_dl = Button(right, "Скачать", lambda n=name: self._download(n), small=True, icon="download")
            b_del = Button(right, "Удалить", lambda n=name: self._delete(n), small=True, kind="danger")
            b_mic = Button(right, "Для команд", lambda n=name: self._choose(n, False), small=True)
            b_f7 = Button(right, f"Для {key_display(S.hotkey_listen)}", lambda n=name: self._choose(n, True),
                          small=True)
            self.model_rows[name] = {"status": status, "prog": prog, "dl": b_dl, "del": b_del, "mic": b_mic,
                                     "f7": b_f7, "right": right}
        self._refresh_models()

    def _refresh_hw(self):
        hw = self.hw or {}
        if not hasattr(self, "hw_lbl"):
            return
        dev = stt.whisper_device()
        if hw.get("gpu"):
            g = f"Видеокарта: {hw['gpu']}, {hw['vram_mb'] / 1024:.0f} ГБ".replace(".", ",")
            g += " — распознавание на ней ✓" if dev == "cuda" else \
                " — пока не подготовлена (мастер → шаг «Видеокарта»), распознавание на процессоре"
        else:
            g = "Видеокарты NVIDIA нет — распознавание на процессоре"
        rec = stt.recommend(hw)
        self.hw_lbl.config(text=f"{g}. Процессор: {hw.get('cores', '?')} потоков, память: "
                                f"{hw.get('ram_gb', 0):g} ГБ.\nСовет: для команд — {rec['mic']}, для "
                                f"{key_display(S.hotkey_listen)} — {rec['listen']} ({rec['why']}).".replace(".0 ГБ", " ГБ"))
        self._build_model_rows()

    def _refresh_models(self):
        in_use = self._in_use()
        for name, w in self.model_rows.items():
            cached = stt.model_cached(name)
            size = stt.model_size_bytes(name, self.sizes) if self.sizes else stt.model_meta(name)["approx_mb"] * 2 ** 20
            if name in self.downloading:
                continue
            for b in ("dl", "del", "mic", "f7"):
                w[b].pack_forget()
            if cached:
                disk = stt.model_disk_size(name)
                w["status"].config(text=f"✓ скачана · {stt.fmt_size(disk)}" + (" · сейчас работает" if name in in_use
                                                                                 else ""), fg=T["OK"])
                if name not in in_use:
                    w["del"].pack(side="right", padx=2)
            else:
                w["status"].config(text=f"не скачана · {stt.fmt_size(size)}", fg=T["MUTED"])
                w["dl"].pack(side="right", padx=2)
            w["f7"].pack(side="right", padx=2)
            w["mic"].pack(side="right", padx=2)

    def _in_use(self):
        a = self.app
        names = {a.models.mic_name}
        if a.listen_tr:
            names |= {a.listen_tr.model_name, a.listen_tr.switching}
        return {n for n in names if n}

    def _download(self, name):
        if name in self.downloading:
            return
        self.downloading.add(name)
        w = self.model_rows[name]
        w["dl"].pack_forget()
        w["prog"].pack(anchor="w", pady=(3, 0))
        w["status"].config(text="начинаю скачивание…", fg=T["WARN"])

        def report(p):
            def ui():
                if name in self.model_rows:
                    self.model_rows[name]["prog"].set(p.get("pct", 0) / 100)
                    if p.get("text"):
                        self.model_rows[name]["status"].config(text="⬇ " + p["text"], fg=T["WARN"])
            self.later(ui)

        def work():
            err = None
            try:
                stt.download_with_progress(name, report)
            except Exception as e:
                err = stt.short_err(e)

            def done():
                self.downloading.discard(name)
                if name in self.model_rows:
                    self.model_rows[name]["prog"].pack_forget()
                self._refresh_models()
                if err:
                    self.model_rows[name]["status"].config(text=f"не скачалась: {err}. Проверь интернет и место "
                                                                f"на диске, потом «Скачать» ещё раз — продолжит с того "
                                                                f"же места.", fg=T["ERR"])
                self._refresh_compare_box()
            self.later(done)

        threading.Thread(target=work, daemon=True, name=f"download-{name}").start()

    def _delete(self, name):
        if not messagebox.askyesno("Удалить модель", f"Удалить скачанную модель {name}? Её можно будет скачать снова.",
                                   parent=self.top):
            return
        try:
            stt.delete_model(name, self._in_use())
        except Exception as e:
            messagebox.showerror("Не получилось", f"Модель не удалилась: {e}", parent=self.top)
        self._refresh_models()
        self._refresh_compare_box()

    def _choose(self, name, listen):
        if listen:
            S.update(listen_whisper_model=name)
            self.listen_model.set_value(name)
        else:
            S.update(whisper_model=name)
            self.mic_model.set_value(name)
        self.top.after(300, self._build_model_rows)

    # --- сравнение моделей
    def _refresh_compare_box(self):
        if not hasattr(self, "cmp_checks"):
            return
        audio_ok = self.app.last_f7_audio is not None or os.path.isfile(LAST_F7_WAV)
        when = ""
        if os.path.isfile(LAST_F7_WAV):
            when = time.strftime("%d.%m %H:%M", time.localtime(os.path.getmtime(LAST_F7_WAV)))
        self.cmp_info.config(text=(f"Последняя запись: {when}." if audio_ok else
                                   f"Записей пока нет — задай вопрос клавишей {key_display(S.hotkey_listen)}, "
                                   "потом возвращайся сюда.") + " Отметь скачанные модели:")
        for w in self.cmp_checks.winfo_children():
            w.destroy()
        for name in stt.MODEL_NAMES:
            if not stt.model_cached(name):
                continue
            var = self.cmp_vars.get(name) or tk.BooleanVar(value=name in self._in_use())
            self.cmp_vars[name] = var
            tk.Checkbutton(self.cmp_checks, text=name, variable=var, bg=T["BG2"], fg=T["FG"], selectcolor=T["BG3"],
                           activebackground=T["BG2"], activeforeground=T["FG"], font=F(-1),
                           cursor=hand()).pack(side="left", padx=(0, 10))
        self.cmp_btn.set_enabled(audio_ok)

    def _compare(self):
        names = [n for n, v in self.cmp_vars.items() if v.get() and stt.model_cached(n)]
        if not names:
            return
        audio = self.app.last_f7_audio
        if audio is None:
            try:
                audio = load_wav(LAST_F7_WAV)
            except Exception as e:
                messagebox.showerror("Нет записи", f"Не удалось открыть последнюю запись: {e}", parent=self.top)
                return
        for w in self.cmp_out.winfo_children():
            w.destroy()
        self.cmp_btn.set_enabled(False)
        cols = {}
        for i, name in enumerate(names):
            col = tk.Frame(self.cmp_out, bg=T["BG3"])
            col.grid(row=0, column=i, sticky="nsew", padx=3)
            self.cmp_out.grid_columnconfigure(i, weight=1, uniform="cmp")
            tk.Label(col, text=name, bg=T["BG3"], fg=T["FG"], font=F(0, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
            st = tk.Label(col, text="жду очереди…", bg=T["BG3"], fg=T["MUTED"], font=F(-2))
            st.pack(anchor="w", padx=8)
            tx = tk.Label(col, text="", bg=T["BG3"], fg=T["FG"], font=F(-1), justify="left", anchor="nw",
                          wraplength=max(160, 640 // len(names)))
            tx.pack(fill="both", expand=True, padx=8, pady=(4, 8))
            cols[name] = (st, tx)

        def report(name, text, secs, err, total):
            def ui():
                st, tx = cols[name]
                if err:
                    st.config(text="ошибка", fg=T["ERR"])
                    tx.config(text=err)
                else:
                    st.config(text=f"распознано за {secs:.1f} с (с загрузкой {total:.0f} с)".replace(".", ","),
                              fg=T["OK"])
                    tx.config(text=text or "(пусто)")
            self.later(ui)

        def work():
            for n in names:
                self.later(lambda n=n: cols[n][0].config(text="распознаю…", fg=T["WARN"]))
                self.app.listen_tr.compare(audio, [n], report)
            self.later(lambda: self.cmp_btn.set_enabled(True))

        threading.Thread(target=work, daemon=True, name="compare").start()

    # ------------------------------------------------------------ 2. звук
    def _page_sound(self, p):
        self._title(p, "Звук", "Микрофон — для команд «Клод, …». Звук компьютера — для вопросов клавишей "
                               f"{key_display(S.hotkey_listen)} (лекция, созвон, видео).")
        c = card(p, "Микрофон")
        names = list_input_devices()
        opts = [("", "Как в Windows (по умолчанию)")] + [(n, n) for n in names]
        if S.mic_device and S.mic_device not in names:
            opts.append((S.mic_device, S.mic_device + " (сейчас не найден)"))
        Choice(row(c, "Устройство"), opts, S.mic_device, lambda v: S.update(mic_device=v), width=40).pack()
        m = Meter(row(c, "Громкость сейчас", "Скажи что-нибудь — полоска должна двигаться"), width=260)
        m.pack()
        self.meters.append((m, lambda: level_fraction(self.app.listener.level if self.app.listener else 0)))
        sens = row(c, "Чувствительность", "Вправо — слышит тише и дальше, но чаще срабатывает от шума")
        val = tk.Label(sens, text="", bg=T["BG2"], fg=T["MUTED"], font=F(-1), width=6)
        s = Slider(sens, 1.5, 6.0, 7.5 - S.mic_threshold_mult, step=0.1, width=220,
                   command=lambda v: S.update(mic_threshold_mult=round(7.5 - v, 1)),
                   on_move=lambda v: val.config(text=f"{v:.1f}"))
        s.pack(side="left")
        val.pack(side="left")
        val.config(text=f"{7.5 - S.mic_threshold_mult:.1f}")
        self._slider(c, "Пауза в конце фразы", "end_silence", 0.4, 2.0, 0.1, "{:.1f} с",
                     "Сколько тишины считать концом фразы")
        self._slider(c, "Самый тихий голос", "mic_min_level", 0.002, 0.05, 0.001, "{:.3f}",
                     "Звук тише этого — никогда не речь (меньше — чувствительнее)")
        self._slider(c, "Самая длинная фраза", "max_utterance", 10, 90, 5, "{:.0f} с", as_int=True)
        self._text_setting(row(c, "Слова-обращения", "Как распознавание слышит «Клод» — через запятую"),
                           "wake_words", is_list=True, width=40)
        self._slider(c, "Дополнять без «Клод»", "followup_seconds", 0, 60, 1, "{:.0f} с",
                     "Сколько секунд после ответа можно говорить без «Клод» (0 — всегда нужно «Клод»)", as_int=True)

        c = card(p, f"Звук компьютера ({key_display(S.hotkey_listen)})")
        sa = self.app.sysaudio
        names = sa.all_names if sa else []
        opts = [("", "Все устройства — брать самое громкое")] + [(n, n) for n in names]
        if S.listen_device and S.listen_device not in names:
            opts.append((S.listen_device, S.listen_device))
        Choice(row(c, "Откуда брать звук"), opts, S.listen_device, lambda v: S.update(listen_device=v),
               width=40).pack()
        lv = tk.Frame(c, bg=T["BG2"])
        lv.pack(fill="x", pady=(6, 4))
        label(lv, "Громкость по устройствам (включи любое видео — полоска нужного устройства задвигается):",
              muted=True, size=-2).pack(anchor="w")
        self.dev_meter_box = tk.Frame(lv, bg=T["BG2"])
        self.dev_meter_box.pack(fill="x")
        self._dev_meter_names = None
        self._refresh_dev_meters()
        self._slider(c, "Секунд до нажатия", "listen_pre_seconds", 0, 6, 0.5, "{:.1f} с",
                     "Сколько звука ДО первого нажатия попадает в запись")
        self._slider(c, "Секунд после нажатия", "listen_post_seconds", 0, 3, 0.5, "{:.1f} с",
                     "Сколько ещё пишется после второго нажатия")
        self._slider(c, "Самая длинная запись", "listen_max_seconds", 30, 300, 10, "{:.0f} с",
                     "Если забыл нажать второй раз — запись закончится сама", as_int=True)

    def _refresh_dev_meters(self):
        if self._closed or not hasattr(self, "dev_meter_box"):
            return
        sa = self.app.sysaudio
        levels = sa.device_levels() if sa else []
        names = [n for n, _ in levels]
        if names != self._dev_meter_names:
            self._dev_meter_names = names
            for w in self.dev_meter_box.winfo_children():
                w.destroy()
            for i, n in enumerate(names):
                r = tk.Frame(self.dev_meter_box, bg=T["BG2"])
                r.pack(fill="x", pady=1)
                tk.Label(r, text=n[:48], bg=T["BG2"], fg=T["FG"], font=F(-2), width=44, anchor="w").pack(side="left")
                m = Meter(r, width=200, height=8)
                m.pack(side="left", padx=6)
                self.meters.append((m, lambda i=i: level_fraction(
                    (self.app.sysaudio.device_levels()[i][1]) if self.app.sysaudio and
                    i < len(self.app.sysaudio.device_levels()) else 0)))
            if not names:
                label(self.dev_meter_box, "устройства ещё открываются…" if sa and sa.state == "starting" else
                      (sa.error if sa else "звук компьютера недоступен"), muted=True, size=-2).pack(anchor="w")
        self.top.after(2000, self._refresh_dev_meters)

    # ------------------------------------------------------------ 3. Claude
    def _page_claude(self, p):
        self._title(p, "Подключение к ИИ", "Кто отвечает на вопросы: Claude по подписке, Claude по ключу или другой "
                                            "провайдер (ChatGPT, Gemini, OpenRouter, DeepSeek, модель на своём компьютере…).")
        c = card(p, "Подключение")
        Choice(row(c, "Способ"), [("subscription", "Claude по подписке Pro/Max (Claude Code, без ключа)"),
                                  ("api", "Claude по API-ключу Anthropic"),
                                  ("provider", "Другой провайдер по ключу (ChatGPT, Gemini…)")], S.backend,
               lambda v: (S.update(backend=v), self._build_conn()), width=52).pack()
        self.conn_box = tk.Frame(c, bg=T["BG2"])
        self.conn_box.pack(fill="x")
        self._build_conn()
        c = card(p, "Claude: модели и «сколько думать»", "Для подписки и ключа Anthropic.")
        Choice(row(c, "«Клод, …» — модель"), CLAUDE_MODELS, S.cli_model, lambda v: S.update(cli_model=v),
               width=40).pack()
        Choice(row(c, "«Клод, …» — сколько думать"), EFFORTS, S.cli_effort, lambda v: S.update(cli_effort=v),
               width=40).pack()
        Choice(row(c, f"{key_display(S.hotkey_listen)} — модель"), CLAUDE_MODELS, S.listen_model,
               lambda v: S.update(listen_model=v), width=40).pack()
        Choice(row(c, f"{key_display(S.hotkey_listen)} — сколько думать", "«Мало» — первые слова через ~1 с"),
               EFFORTS, S.listen_effort, lambda v: S.update(listen_effort=v), width=40).pack()

        c = card(p, "Ответы")
        Choice(row(c, f"Ответ на {key_display(S.hotkey_listen)}"),
               [("short", "«Скажи:» коротко — 1–2 фразы до 30 слов"),
                ("detailed", "Подробнее — до 60 слов и 3–5 пунктов")], S.listen_style,
               lambda v: S.update(listen_style=v), width=40).pack()
        self._toggle(c, "Решения «как в тетради»", "student_style", "Дано / Найти / Решение / Ответ")
        self._toggle(c, "Формулы картинками", "math_render", "Дроби, корни, степени — как в учебнике")
        self._toggle(c, "Скриншот к «Клод, …»", "screen_question", "Без него — «Клод, без экрана, …» не нужно")
        self._toggle(c, f"Скриншот к {key_display(S.hotkey_listen)}", "listen_screen",
                     "Видно слайд, задание или код на экране")

        c = card(p, "Скриншот")
        Choice(row(c, "Какой монитор снимать"), [("mouse", "Тот, где курсор"), ("primary", "Основной"),
                                                 ("all", "Все сразу")], S.monitor,
               lambda v: S.update(monitor=v)).pack()
        self._slider(c, "Размер картинки для «Клод, …»", "max_image_side", 800, 2560, 32, "{:.0f} пикс.",
                     "Больше — Claude лучше видит мелкий текст, но ответ чуть медленнее", as_int=True)
        self._slider(c, f"Размер картинки для {key_display(S.hotkey_listen)}", "listen_image_side", 640, 2048, 32,
                     "{:.0f} пикс.", as_int=True)

        c = card(p, "Тонкая настройка (для продвинутых)")
        self._text_setting(row(c, "Путь к Claude Code", "Пусто — найти самому (claude.exe)"), "claude_cmd",
                           width=36)
        Choice(row(c, "Как передавать скриншот", "«Файлом» — если твоя версия Claude Code не принимает картинку"),
               [("inline", "Картинкой в сообщении"), ("file", "Файлом (Claude откроет сам)")], S.cli_image_mode,
               lambda v: S.update(cli_image_mode=v)).pack()
        self._slider(c, "Длина ответа (режим API)", "max_tokens", 512, 16000, 512, "{:.0f} токенов", as_int=True)
        self._slider(c, "Скриншотов в истории (режим API)", "keep_last_images", 0, 6, 1, "{:.0f}", as_int=True)
        self._slider(c, "Сообщений в истории (режим API)", "max_history_messages", 6, 100, 2, "{:.0f}", as_int=True)
        self._slider(c, f"Ответов {key_display(S.hotkey_listen)} до новой сессии", "listen_max_turns", 5, 60, 1,
                     "{:.0f}", "Потом Claude начинает с чистого листа (чтобы не разрасталось)", as_int=True)

        c = card(p, "Инструкции для Claude (для продвинутых)",
                 "Здесь можно переписать, как Claude отвечает. «Вернуть как было» — стандартный текст.")
        for key, title, default in (("prompt_system", "Для «Клод, …»", default_system_prompt),
                                    ("prompt_listen", f"Для {key_display(S.hotkey_listen)}", default_listen_prompt),
                                    ("prompt_analyze", "Когда добавлены материалы", lambda: ANALYZE_PROMPT)):
            self._prompt_editor(c, key, title, default)

    # --- подключение: содержимое зависит от способа
    def _build_conn(self):
        box = self.conn_box
        for w in box.winfo_children():
            w.destroy()
        self.conn_lbl = label(box, "", muted=True, size=-1, wrap=640)
        self.conn_lbl.pack(anchor="w", pady=(4, 4))
        if S.backend == "subscription":
            cli = find_claude()
            self.conn_lbl.config(text=(f"Claude Code найден: {cli}" if cli else
                                       "Claude Code не найден — открой мастер (вкладка «Невидимость и система» → "
                                       "«Проверить и починить»)."))
            return
        if S.backend == "api":
            self.conn_lbl.config(text="Ответы через API-ключ Anthropic — оплачивается каждый запрос.")
            keyrow = row(box, "Ключ Anthropic", "Хранится в workspace\\api_key.txt, нигде не показывается")
            ent = entry(keyrow, "", width=30, show="•")
            ent.pack(side="left")
            state = label(box, "", muted=True, size=-2)

            def save():
                save_api_key(ent.get().strip())
                ent.delete(0, "end")
                state.config(text="Ключ сохранён " + mask_secret(load_api_key()) if load_api_key() else "Ключ не задан")
                self.app.ui_q.put(("settings_changed", {"api_key_saved"}))

            Button(keyrow, "Сохранить", save, small=True).pack(side="left", padx=4)
            state.pack(anchor="w")
            state.config(text="Ключ сохранён " + mask_secret(load_api_key()) if load_api_key() else "Ключ не задан")
            Choice(row(box, "Модель"), API_MODELS, S.api_model, lambda v: S.update(api_model=v)).pack()
            return
        self._build_provider(box)

    def _build_provider(self, box):
        from . import providers as pv
        cfg = pv.current()
        p = pv.BY_ID[cfg["id"]]
        self.conn_lbl.config(text="Оплата — у выбранного провайдера, по его ценам. Скриншот уходит туда же, куда вопрос.")

        def set_provider(v):
            S.update(provider=v, provider_model="", provider_listen_model="", provider_base_url="",
                     provider_vision="auto")
            self._build_conn()

        Choice(row(box, "Провайдер"), [(x.id, x.title) for x in pv.PROVIDERS], p.id, set_provider,
               width=52).pack()
        info = []
        if p.note:
            info.append(p.note)
        if p.key_url:
            info.append("где взять: " + p.key_url)
        if info:
            lnk = label(box, " · ".join(info), color=T["INFO"], size=-2, wrap=640, cursor=hand())
            lnk.pack(anchor="w", pady=(0, 4))
            if p.key_url:
                lnk.bind("<Button-1>", lambda e: __import__("webbrowser").open(p.key_url))
        r = row(box, "Адрес сервиса", "Обычно менять не нужно" if p.id != "custom" else
                "Например http://localhost:8000/v1 — адрес, где есть /chat/completions")
        url = entry(r, S.provider_base_url or p.base_url, width=36)
        url.pack()

        def save_url(_e=None):
            v = url.get().strip()
            S.update(provider_base_url="" if v == p.base_url else v)

        url.bind("<Return>", save_url)
        url.bind("<FocusOut>", save_url)
        keyrow = row(box, "Ключ" + ("" if p.needs_key else " (не обязателен)"),
                     "Хранится в workspace\\api_keys.json, нигде не показывается")
        kent = entry(keyrow, "", width=30, show="•")
        kent.pack(side="left")
        kstate = label(box, "", muted=True, size=-2)

        def show_key_state():
            k = pv.load_key(p.id)
            kstate.config(text=("Ключ сохранён " + mask_secret(k)) if k else
                          ("Ключ не задан" + ("" if p.needs_key else " — для этого провайдера он и не нужен")))

        def save_key():
            pv.save_key(p.id, kent.get().strip())
            kent.delete(0, "end")
            show_key_state()
            self.app.ui_q.put(("settings_changed", {"api_key_saved"}))

        Button(keyrow, "Сохранить", save_key, small=True).pack(side="left", padx=4)
        kstate.pack(anchor="w")
        show_key_state()

        models = [m for m in (cfg["model"], p.model) if m]
        mrow = row(box, "Модель для «Клод, …»")
        mbox = self._model_combo(mrow, S.provider_model or p.model, models, "provider_model", p.model)
        frow = row(box, f"Модель для {key_display(S.hotkey_listen)}", "Пусто — та же; для F7 лучше быстрая")
        fbox = self._model_combo(frow, S.provider_listen_model, models, "provider_listen_model", "")
        Choice(row(box, "Модель видит картинки", "Если нет — скриншот не передаётся, отвечает по тексту"),
               [("auto", "Как обычно у провайдера (" + ("да" if p.vision else "нет") + ")"), ("yes", "Да"),
                ("no", "Нет")], S.provider_vision, lambda v: S.update(provider_vision=v), width=30).pack()
        res = label(box, "", size=-1, wrap=640)
        btns = tk.Frame(box, bg=T["BG2"])
        btns.pack(anchor="w", pady=(6, 0))

        def load_list():
            res.config(text="Загружаю список моделей…", fg=T["MUTED"])

            def work():
                try:
                    ids = pv.list_models(pv.current())
                    msg, ok = f"Моделей: {len(ids)}. Выбери в списке «Модель».", True
                except Exception as e:
                    ids, msg, ok = [], f"Не получилось: {e}. " + pv.explain(str(e)), False

                def ui():
                    if ids:
                        mbox.config(values=ids)
                        fbox.config(values=[""] + ids)
                    res.config(text=msg, fg=T["OK"] if ok else T["ERR"])
                self.later(ui)
            threading.Thread(target=work, daemon=True).start()

        def check():
            res.config(text="Отправляю пробный вопрос…", fg=T["MUTED"])

            def work():
                cfg2 = pv.current()
                bad = pv.problem(cfg2)
                ok, msg = (False, bad) if bad else pv.check(cfg2)
                text = (f"✓ Работает: «{msg[:40]}» (модель {cfg2['model']})" if ok else
                        f"✕ {msg[:300]}" + ("\n→ " + pv.explain(msg) if pv.explain(msg) else ""))
                self.later(lambda: res.config(text=text, fg=T["OK"] if ok else T["ERR"]))
            threading.Thread(target=work, daemon=True).start()

        Button(btns, "Загрузить список моделей", load_list, small=True).pack(side="left")
        Button(btns, "Проверить", check, small=True, kind="primary").pack(side="left", padx=6)
        res.pack(anchor="w", pady=(6, 0))

    def _model_combo(self, parent, value, values, key, default):
        """Поле модели: можно выбрать из загруженного списка или вписать своё название."""
        from tkinter import ttk
        cb = ttk.Combobox(parent, values=values, width=34, font=F(0))
        cb.set(value)
        cb.pack()

        def commit(_e=None):
            v = cb.get().strip()
            S.update(**{key: "" if v == default else v})

        cb.bind("<<ComboboxSelected>>", commit)
        cb.bind("<Return>", commit)
        cb.bind("<FocusOut>", commit)
        return cb
    def _prompt_editor(self, parent, key, title, default):
        box = tk.Frame(parent, bg=T["BG2"])
        box.pack(fill="x", pady=(8, 0))
        top = tk.Frame(box, bg=T["BG2"])
        top.pack(fill="x")
        label(top, title, bold=True).pack(side="left")
        state = label(top, "", muted=True, size=-2)
        state.pack(side="left", padx=8)
        t = tk.Text(box, height=8, wrap="word", bg=T["BG3"], fg=T["FG"], insertbackground=T["FG"], relief="flat",
                    font=MONO(-1), padx=8, pady=6, highlightthickness=1, highlightbackground=T["BORDER"],
                    highlightcolor=T["ACCENT"], cursor=text_cursor(), undo=True)
        t.pack(fill="x", pady=4)

        def load():
            t.delete("1.0", "end")
            t.insert("1.0", (S.get(key) or "").strip() or default())
            state.config(text="свои инструкции" if (S.get(key) or "").strip() else "стандартные")

        def save():
            txt = t.get("1.0", "end").strip()
            S.update(**{key: "" if txt == default().strip() else txt})
            load()

        def reset():
            S.update(**{key: ""})
            load()

        btns = tk.Frame(box, bg=T["BG2"])
        btns.pack(anchor="w")
        Button(btns, "Сохранить", save, small=True, kind="primary").pack(side="left")
        Button(btns, "Вернуть как было", reset, small=True).pack(side="left", padx=6)
        load()

    # ------------------------------------------------------------ 4. клавиши
    def _page_keys(self, p):
        self._title(p, "Клавиши", "Нажми «Назначить», потом нужную клавишу (можно с Ctrl/Alt/Shift). Esc — отмена. "
                                  "Пока оверлей запущен, эти клавиши не доходят до других программ.")
        c = card(p)
        self.key_lbls = {}
        for action, skey in (("listen", "hotkey_listen"), ("talk", "hotkey_talk"), ("toggle", "hotkey_toggle")):
            r = row(c, ACTION_TITLES[action])
            lbl = tk.Label(r, text=key_display(S.get(skey)), bg=T["BG3"], fg=T["FG"], font=F(1, "bold"), width=12,
                           pady=4)
            lbl.pack(side="left", padx=6)
            Button(r, "Назначить…", lambda a=action, k=skey: self._capture_key(a, k), small=True).pack(side="left")
            Button(r, "Как было", lambda k=skey: self._set_key(k, DEFAULTS[k]), small=True).pack(side="left", padx=4)
            self.key_lbls[skey] = lbl
        self.key_warn = label(c, "", color=T["WARN"], size=-1, wrap=640)
        self.key_warn.pack(anchor="w", pady=(8, 0))
        label(c, "Esc во время записи вопроса — отмена записи (только пока идёт запись).", muted=True,
              size=-2).pack(anchor="w", pady=(6, 0))
        self._refresh_key_warn()

    def _capture_key(self, action, skey):
        lbl = self.key_lbls[skey]
        lbl.config(text="нажми клавишу…", fg=T["WARN"])

        def got(spec):  # из потока хука клавиатуры
            self.later(lambda: self._set_key(skey, spec) if spec else
                       lbl.config(text=key_display(S.get(skey)), fg=T["FG"]))

        self.app.hk.capture_next(got)

    def _set_key(self, skey, spec):
        trial = {"listen": S.hotkey_listen, "talk": S.hotkey_talk, "toggle": S.hotkey_toggle}
        action = {"hotkey_listen": "listen", "hotkey_talk": "talk", "hotkey_toggle": "toggle"}[skey]
        trial[action] = spec
        p = parse_spec(spec)
        bad = [w for w in key_problems(trial) if "нельзя" in w or "дважды" in w]
        if not p or bad:
            self.key_warn.config(text="Не назначено: " + (" ".join(bad) or "такую клавишу нельзя."), fg=T["ERR"])
            self.key_lbls[skey].config(text=key_display(S.get(skey)), fg=T["FG"])
            return
        S.update(**{skey: spec})
        self.key_lbls[skey].config(text=key_display(spec), fg=T["FG"])
        self._refresh_key_warn()

    def _refresh_key_warn(self):
        warn = key_problems({"listen": S.hotkey_listen, "talk": S.hotkey_talk, "toggle": S.hotkey_toggle})
        self.key_warn.config(text="\n".join("⚠ " + w for w in warn) if warn else "✓ Конфликтов нет.",
                             fg=T["WARN"] if warn else T["OK"])

    # ------------------------------------------------------------ 5. внешний вид
    def _page_look(self, p):
        self._title(p, "Внешний вид")
        c = card(p, "Окно")
        self._slider(c, "Размер шрифта", "font_size", 9, 18, 1, "{:.0f}", as_int=True)
        self._slider(c, "Прозрачность", "alpha", 0.5, 1.0, 0.05, "{:.0%}", "100% — непрозрачное")
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        self._slider(c, "Ширина", "width", 340, min(1600, sw), 10, "{:.0f} пикс.", as_int=True)
        self._slider(c, "Высота", "height", 220, min(1600, sh), 10, "{:.0f} пикс.", "Положение и размер окна "
                     "запоминаются сами, когда двигаешь его мышкой", as_int=True,
                     value=S.height or self.app.root.winfo_height())
        self._toggle(c, "Компактный режим", "compact",
                     "Окно — маленькая полоска со статусом; при ответе разворачивается само")
        Choice(row(c, "Шрифт формул"), [("cm", "Как в учебнике (Computer Modern)"), ("stix", "STIX (как в Word)"),
                                        ("dejavusans", "Без засечек")], S.math_fontset,
               lambda v: (S.update(math_fontset=v), self.app.math_cache.clear())).pack()
        r = row(c, "Положение окна", "Если окно потерялось за краем экрана")
        Button(r, "Вернуть в правый верхний угол", lambda: S.update(pos_x=None, pos_y=None), small=True).pack()
        c = card(p, "Тема")
        r = row(c, "Цвета", "Тема меняется после перезапуска оверлея")
        Choice(r, list(THEME_NAMES.items()), S.theme, lambda v: S.update(theme=v), width=16).pack(side="left")
        Button(r, "Перезапустить", lambda: self.app.restart(["--settings"]), small=True).pack(side="left", padx=6)

    # ------------------------------------------------------------ 6. материалы
    def _page_materials(self, p):
        self._title(p, "Материалы", "Лекции, конспекты, вопросы — Claude отвечает по ним. Хранится только "
                                    "извлечённый текст, материалы переживают перезапуск.")
        c = card(p)
        btns = tk.Frame(c, bg=T["BG2"])
        btns.pack(anchor="w", pady=(0, 8))
        Button(btns, "Прикрепить файлы", lambda: (self.app.pick_files(), self.top.after(1500, self._refresh_mats)),
               kind="primary", icon="attach").pack(side="left")
        Button(btns, "Текст из буфера", lambda: (self.app.paste_material(), self._refresh_mats()),
               icon="paste").pack(side="left", padx=6)
        Button(btns, "Убрать все", lambda: self._clear_mats(), kind="danger").pack(side="left")
        self.mat_box = tk.Frame(c, bg=T["BG2"])
        self.mat_box.pack(fill="x")
        self._slider(c, "Сколько текста давать Claude", "materials_max_chars", 20_000, 400_000, 10_000,
                     "{:,.0f} знаков", "Больше — ответы медленнее и быстрее тратится лимит", as_int=True)
        self._slider(c, "Терминов в подсказку распознаванию", "materials_hotwords", 0, 60, 5, "{:.0f}",
                     as_int=True)
        self._refresh_mats()

    def _refresh_mats(self):
        if self._closed or not hasattr(self, "mat_box"):
            return
        for w in self.mat_box.winfo_children():
            w.destroy()
        items = self.app.materials.items
        if not items:
            label(self.mat_box, "Материалов нет.", muted=True).pack(anchor="w", pady=4)
        for it in items:
            r = tk.Frame(self.mat_box, bg=T["BG3"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text=it["title"], bg=T["BG3"], fg=T["FG"], font=F(0, "bold"), anchor="w").pack(
                side="left", padx=10, pady=6)
            tk.Label(r, text=f"{it['kind']} · {it['chars']:,} знаков".replace(",", " "), bg=T["BG3"], fg=T["MUTED"],
                     font=F(-2)).pack(side="left")
            Button(r, "Убрать", lambda m=it["id"]: (self.app.remove_material(m), self._refresh_mats()), small=True,
                   kind="danger").pack(side="right", padx=6)
            Button(r, "Посмотреть текст", lambda m=it: show_text(self.app, m["title"], self.app.materials.text(m["id"]),
                                                                 parent=self.top), small=True).pack(side="right")
        self.top.after(3000, self._refresh_mats)

    def _clear_mats(self):
        if self.app.materials.items and messagebox.askyesno("Убрать материалы", "Убрать все материалы?",
                                                            parent=self.top):
            self.app.clear_materials()
            self._refresh_mats()

    # ------------------------------------------------------------ 7. невидимость и система
    def _page_system(self, p):
        self._title(p, "Невидимость и система")
        c = card(p, "Невидимость на демонстрации экрана",
                 "Окна оверлея не видны в Zoom, Teams, Discord, Google Meet, OBS и на скриншотах — у тебя на "
                 "мониторе они видны как обычно. Не спасает от камеры телефона, некоторых программ удалённого "
                 "доступа (AnyDesk, TeamViewer) и очень старых драйверов захвата.")
        self._toggle(c, "Прятать окна от захвата экрана", "protect")
        self.shield_state = label(c, "", size=-1, wrap=640)
        self.shield_state.pack(anchor="w", pady=4)
        Button(c, "Проверить невидимость", lambda: self.app.show_capture_check(self.top), kind="primary",
               icon="eye").pack(anchor="w", pady=(4, 0))
        self._refresh_shield_state()

        c = card(p, "Система")
        self._toggle(c, "Значок в трее", "tray", "Его видно на демонстрации экрана (панель задач видна всем) — "
                                                 "поэтому по умолчанию выключен")
        r = row(c, "Запускать вместе с Windows", "Ярлык в папке «Автозагрузка»")
        t = Toggle(r, autostart_enabled(), lambda v: self._autostart(v, t))
        t.pack()
        r = tk.Frame(c, bg=T["BG2"])
        r.pack(anchor="w", pady=(8, 0))
        Button(r, "Открыть журнал", lambda: winsys.open_path(LOG_PATH), small=True).pack(side="left")
        Button(r, "Папка программы", lambda: winsys.open_path(HERE), small=True).pack(side="left", padx=6)
        Button(r, "Проверить и починить (мастер)", self.app.open_wizard, small=True).pack(side="left")

        c = card(p, "Диагностика")
        bar = tk.Frame(c, bg=T["BG2"])
        bar.pack(anchor="w", pady=(0, 6))
        Button(bar, "Обновить", self._diag, small=True).pack(side="left")
        self.login_btn = Button(bar, "Проверить вход в Claude", self._check_login, small=True)
        self.login_btn.pack(side="left", padx=6)
        Button(bar, "Скопировать", lambda: self.app._copy_text(self.diag_text, "диагностика"), small=True).pack(
            side="left")
        self.diag_lbl = tk.Label(c, text="Собираю сведения…", bg=T["BG3"], fg=T["FG"], font=MONO(-1),
                                 justify="left", anchor="nw", padx=10, pady=8, wraplength=660)
        self.diag_lbl.pack(fill="x")
        self.diag_text = ""
        self._diag()

    def _refresh_shield_state(self):
        if self._closed or not hasattr(self, "shield_state"):
            return
        level, text = self.app.guard.status(self.app.root)
        self.shield_state.config(text=text, fg={"ok": T["OK"], "partial": T["WARN"]}.get(level, T["ERR"]))
        self.top.after(2000, self._refresh_shield_state)

    def _autostart(self, v, toggle):
        try:
            set_autostart(v)
        except Exception as e:
            toggle.set(not v)
            messagebox.showerror("Автозапуск", f"Не получилось: {e}", parent=self.top)

    def _diag(self):
        app = self.app

        def work():
            lines = []
            cli = find_claude()
            lines.append(f"Claude Code: {cli or 'не найден'}")
            if cli:
                lines.append(f"  версия: {claude_version(cli)}")
            lines.append(f"Способ: {'подписка' if S.backend == 'subscription' else 'API-ключ'}")
            hw = stt.hardware_info(refresh=True)
            lines.append(f"Видеокарта: {hw['gpu'] or 'NVIDIA нет'}" + (f", {hw['vram_mb']} МБ" if hw["gpu"] else ""))
            ct2 = stt.ctranslate2_version()
            lines.append(f"Распознавание на: {'видеокарте' if stt.whisper_device() == 'cuda' else 'процессоре'}"
                         f" (ctranslate2 {ct2}, проверка видеокарты: "
                         f"{'пройдена' if os.path.isfile(stt.GPU_OK) else 'не пройдена' if os.path.isfile(stt.GPU_FAIL) else 'не делалась'})")
            lines.append(f"Процессор: {hw['cores']} потоков, память {hw['ram_gb']} ГБ")
            lines.append(f"Модель команд: {app.models.mic_name or '—'} ({app.transcriber.where if app.transcriber else ''})")
            if app.listen_tr:
                lines.append(f"Модель {key_display(S.hotkey_listen)}: {app.listen_tr.model_name or '—'} ({app.listen_tr.where})")
            cached = [n for n in stt.MODEL_NAMES if stt.model_cached(n)]
            lines.append("Скачанные модели: " + (", ".join(f"{n} ({stt.fmt_size(stt.model_disk_size(n))})"
                                                          for n in cached) or "нет"))
            lines.append(f"Микрофон: {app.listener.device_name if app.listener else '—'}")
            sa = app.sysaudio
            if sa:
                lines.append(f"Звук компьютера: {sa.state}" + (f" — {sa.error}" if sa.error else "") +
                             f", устройств: {len(sa.devices)}")
            level, text = app.guard.status(app.root)
            lines.append(f"Невидимость: {text} (Windows сборка {winsys.windows_build()})")
            lines.append(f"Клавиши: {key_display(S.hotkey_listen)} / {key_display(S.hotkey_talk)} / "
                         f"{key_display(S.hotkey_toggle)} (режим: {app.hk.mode or 'нет'})")
            txt = "\n".join(lines)

            def ui():
                self.diag_text = txt
                self.diag_lbl.config(text=txt)
            self.later(ui)

        threading.Thread(target=work, daemon=True, name="diag").start()

    def _check_login(self):
        cli = find_claude()
        if not cli:
            messagebox.showwarning("Claude Code", "Claude Code не найден — открой мастер.", parent=self.top)
            return
        self.login_btn.set_enabled(False)
        self.login_btn.set_text("Проверяю…")

        def work():
            ok, msg = check_login(cli)

            def ui():
                self.login_btn.set_enabled(True)
                self.login_btn.set_text("Проверить вход в Claude")
                if ok:
                    messagebox.showinfo("Claude Code", f"Вход в порядке, Claude ответил: «{msg[:60]}»", parent=self.top)
                else:
                    hint = explain_error(msg)
                    messagebox.showerror("Claude Code", f"Не работает: {msg[:400]}" + (f"\n\n{hint}" if hint else ""),
                                         parent=self.top)
            self.later(ui)

        threading.Thread(target=work, daemon=True, name="login-check").start()

    # ------------------------------------------------------------ общие элементы
    def _toggle(self, parent, title, key, hint=None):
        r = row(parent, title, hint)
        t = Toggle(r, S.get(key), lambda v: S.update(**{key: bool(v)}))
        t.pack()
        return t

    def _slider(self, parent, title, key, lo, hi, step, fmt, hint=None, as_int=False, value=None):
        r = row(parent, title, hint)
        val = tk.Label(r, text="", bg=T["BG2"], fg=T["MUTED"], font=F(-1), width=14, anchor="w")
        cur = value if value is not None else S.get(key)

        def show(v):
            val.config(text=fmt.format(int(round(v)) if as_int else v).replace(",", " "))

        def commit(v):
            S.update(**{key: int(round(v)) if as_int else round(v, 3)})

        s = Slider(r, lo, hi, cur, step=step, width=240, command=commit, on_move=show)
        s.pack(side="left")
        val.pack(side="left", padx=(6, 0))
        show(cur)
        return s

    def _text_setting(self, parent, key, is_list=False, width=30):
        cur = S.get(key)
        e = entry(parent, ", ".join(cur) if is_list else (cur or ""), width=width)
        e.pack()

        def commit(_e=None):
            v = e.get().strip()
            if is_list:
                words = [w.strip().lower() for w in v.split(",") if w.strip()]
                if not words:
                    words = list(DEFAULTS[key])
                    e.delete(0, "end")
                    e.insert(0, ", ".join(words))
                S.update(**{key: words})
            else:
                S.update(**{key: v})

        e.bind("<Return>", commit)
        e.bind("<FocusOut>", commit)
        return e
