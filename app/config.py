# -*- coding: utf-8 -*-
"""Настройки программы.

Значения по умолчанию — в DEFAULTS ниже (раньше это были константы в начале overlay.py). Всё, что пользователь
поменял в окне настроек ⚙, хранится в workspace/settings.json и переживает перезапуск. В файл пишутся только
отличия от значений по умолчанию — так новые значения по умолчанию из обновлений подхватываются сами."""

import json
import os
import threading

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # предупреждения HuggingFace не нужны
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # обычная загрузка — её прогресс видно по размеру файла
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # без консоли полосы tqdm некуда выводить

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # папка claude_overlay
# рабочая папка; CLAUDE_OVERLAY_WORKDIR — только для тестов (чтобы не трогать настоящие настройки и материалы)
WORKDIR = os.environ.get("CLAUDE_OVERLAY_WORKDIR") or os.path.join(HERE, "workspace")
MATERIALS_DIR = os.path.join(WORKDIR, "materials")
SETTINGS_PATH = os.path.join(WORKDIR, "settings.json")
LOG_PATH = os.path.join(WORKDIR, "overlay.log")
ICON_PATH = os.path.join(HERE, "app", "icon.ico")
ICON_PNG = os.path.join(HERE, "app", "icon.png")
API_KEY_PATH = os.path.join(WORKDIR, "api_key.txt")
LAST_F7_WAV = os.path.join(WORKDIR, "last_f7.wav")
SETUP_STATE_PATH = os.path.join(WORKDIR, "setup_state.json")

DEFAULTS = {
    # --- Claude ---
    "backend": "subscription",        # "subscription" — Claude Code по подписке Pro/Max; "api" — ключ Anthropic;
                                      # "provider" — другой провайдер по ключу (OpenAI, Gemini, OpenRouter, Ollama…)
    "provider": "openrouter",         # какой провайдер (app/providers.py)
    "provider_base_url": "",          # свой адрес сервиса ("" — стандартный для провайдера)
    "provider_model": "",             # модель для «Клод, …» ("" — по умолчанию у провайдера)
    "provider_listen_model": "",      # модель для F7 ("" — та же)
    "provider_vision": "auto",        # видит ли модель картинки: auto / yes / no
    "claude_cmd": "",                 # путь к claude.exe; "" — найти самому
    "cli_model": "sonnet",            # модель для «Клод, …»: sonnet / opus / haiku
    "cli_effort": "medium",           # сколько думать: low / medium / high ("" — как в настройках Claude Code)
    "cli_image_mode": "inline",       # "inline" — картинка в сообщении; "file" — Claude открывает файл сам
    "api_model": "claude-sonnet-5-5",  # для режима API-ключа
    "max_tokens": 4096,
    "screen_question": True,          # прикладывать скриншот к «Клод, …»
    "student_style": True,            # решения как в тетради: Дано / Найти / Решение / Ответ
    "math_render": True,              # рисовать формулы картинками (дроби, корни, степени)
    "math_fontset": "cm",             # шрифт формул: cm / stix / dejavusans
    "prompt_system": "",              # свои инструкции для «Клод, …» ("" — стандартные)
    "prompt_listen": "",              # свои инструкции для F7 ("" — стандартные)
    "prompt_analyze": "",             # что делать с новыми материалами ("" — стандартное)
    "keep_last_images": 2,            # сколько последних скриншотов держать в истории (режим API)
    "max_history_messages": 30,

    # --- распознавание речи: команды с микрофона ---
    "whisper_model": "small",         # tiny / base / small / medium / large-v3-turbo / large-v3
    "whisper_device": "auto",         # "auto" — видеокарта NVIDIA, если прошла проверку; "cpu" — процессор
    "language": "ru",                 # язык команд: ru / uk / en / auto
    "mic_hint": "",                   # подсказки распознаванию команд: термины через запятую
    "wake_words": ["клод", "клодик", "кладик", "клодя", "клоди", "клоуд", "клауд", "клот", "глод",
                   "claude", "cloud", "clod"],
    "followup_seconds": 15,           # сколько секунд после ответа можно дополнять без «Клод» (0 — выключить)

    # --- микрофон ---
    "mic_device": "",                 # "" — микрофон по умолчанию; иначе часть названия устройства
    "mic_threshold_mult": 3.0,        # во сколько раз голос громче фона (меньше — чувствительнее)
    "mic_min_level": 0.010,           # минимальный порог громкости
    "end_silence": 0.9,               # пауза (с), после которой фраза закончена
    "max_utterance": 40,              # самая длинная фраза (с)

    # --- скриншот ---
    "monitor": "mouse",               # "mouse" — монитор под курсором, "primary", "all"
    "max_image_side": 1568,

    # --- вопрос со звука компьютера (F7) ---
    "listen_whisper_model": "auto",   # "auto": с видеокартой — large-v3, без неё — large-v3-turbo
    "listen_language": "auto",        # auto / ru / uk / en
    "listen_languages": ["ru", "uk", "en"],  # из каких языков выбирать при автоопределении
    "listen_hint": "",                # подсказки распознаванию: термины, фамилии — через запятую
    "listen_pre_seconds": 2.0,        # сколько секунд ДО первого нажатия F7 попадает в запись
    "listen_post_seconds": 1.0,       # сколько секунд ПОСЛЕ второго нажатия ещё пишется
    "listen_max_seconds": 120,        # забыл нажать «завершить» — запись закончится сама
    "listen_device": "",              # "" — все устройства вывода, берём самое громкое; иначе часть названия
    "listen_model": "sonnet",         # кто отвечает на F7: sonnet / haiku / opus
    "listen_effort": "low",           # low — отвечать сразу
    "listen_style": "short",          # "short" — «Скажи:» до 30 слов; "detailed" — подробнее
    "listen_screen": True,            # прикладывать скриншот к F7
    "listen_image_side": 1280,
    "listen_max_turns": 20,           # после стольких ответов сессия Claude начинается заново

    # --- материалы ---
    "materials_max_chars": 150_000,
    "materials_hotwords": 30,

    # --- клавиши ---
    "hotkey_talk": "<f8>",            # следующая фраза — команда без «Клод»
    "hotkey_toggle": "<f9>",          # спрятать / показать окно
    "hotkey_listen": "<f7>",          # вопрос со звука компьютера: начать / закончить
    "hotkey_region": "<ctrl>+<alt>+s",  # выделить мышкой кусок экрана для следующего вопроса
    "hotkey_type": "<ctrl>+<alt>+<space>",  # написать вопрос текстом (курсор в поле вопроса)
    "text_input": True,               # поле для вопроса текстом внизу окна
    "history_save": True,             # сохранять вопросы и ответы между запусками (workspace/history)

    # --- внешний вид ---
    "font_size": 11,
    "width": 560,
    "height": 0,                      # 0 — 60% высоты экрана
    "pos_x": None,                    # положение окна запоминается само
    "pos_y": None,
    "alpha": 1.0,                     # 1.0 — непрозрачное
    "theme": "dark",                  # dark / midnight / black / warm / light / paper
    "compact": False,                 # маленькая полоска со статусом, разворачивается при ответе

    # --- невидимость и система ---
    "protect": True,                  # не показывать окна на демонстрации экрана и скриншотах
    "tray": False,                    # значок в трее (его видно на демонстрации — поэтому выключен)
}

LANG_NAMES = {"auto": "определять самому", "ru": "русский", "uk": "украинский", "en": "английский"}


class Settings:
    """S.имя — текущее значение; S.update(имя=значение) — поменять и сохранить."""

    def __init__(self, path=SETTINGS_PATH):
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_values", dict(DEFAULTS))
        object.__setattr__(self, "_lock", threading.RLock())
        object.__setattr__(self, "_listeners", [])
        object.__setattr__(self, "load_error", "")
        # Только для разработки: окна видны на скриншотах (чтобы проверять внешний вид). В файл не сохраняется.
        object.__setattr__(self, "_overrides",
                           {"protect": False} if os.environ.get("CLAUDE_OVERLAY_DEBUG_VISIBLE") == "1" else {})
        self.load()

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self.update(**{name: value})

    def get(self, name, default=None):
        return self._values.get(name, default)

    def as_dict(self):
        with self._lock:
            return dict(self._values)

    def load(self):
        data = {}
        if os.path.isfile(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("не словарь")
            except (OSError, ValueError) as e:
                object.__setattr__(self, "load_error", f"файл настроек повреждён ({e}) — взяты значения по умолчанию")
                try:
                    os.replace(self._path, self._path + ".bad")
                except OSError:
                    pass
                data = {}
        with self._lock:
            vals = dict(DEFAULTS)
            for k, v in data.items():
                if k in DEFAULTS:
                    ok, v = normalize(k, v)
                    if ok:
                        vals[k] = v
            object.__setattr__(self, "_values", vals)

    def save(self):
        with self._lock:
            diff = {k: v for k, v in self._values.items() if DEFAULTS.get(k, object()) != v}
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(diff, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)

    def update(self, save=True, **kw):
        """Меняет значения → множество изменившихся имён. Слушатели узнают об изменениях."""
        changed = set()
        with self._lock:
            for k, v in kw.items():
                if k not in DEFAULTS:
                    raise KeyError(f"нет такой настройки: {k}")
                ok, v = normalize(k, v)
                if not ok:
                    print(f"[настройки] неподходящее значение для {k} — оставляю прежнее")
                    continue
                if self._values.get(k) != v:
                    self._values[k] = v
                    changed.add(k)
        if changed:
            if save:
                try:
                    self.save()
                except OSError as e:
                    print("[настройки] не удалось сохранить:", e)
            for cb in list(self._listeners):
                try:
                    cb(changed)
                except Exception as e:
                    print("[настройки] ошибка обработчика:", e)
        return changed

    def reset(self, *names):
        return self.update(**{n: DEFAULTS[n] for n in names})

    def on_change(self, callback):
        self._listeners.append(callback)


# Разумные пределы: значение из испорченного (или вручную поправленного) файла не должно ронять программу
RANGES = {
    "font_size": (8, 24), "width": (300, 4000), "height": (0, 4000), "alpha": (0.3, 1.0),
    "followup_seconds": (0, 120), "listen_pre_seconds": (0, 10), "listen_post_seconds": (0, 5),
    "listen_max_seconds": (10, 600), "max_image_side": (320, 4096), "listen_image_side": (320, 4096),
    "mic_threshold_mult": (1.0, 10.0), "mic_min_level": (0.0005, 0.2), "end_silence": (0.2, 5.0),
    "max_utterance": (5, 120), "materials_max_chars": (1000, 2_000_000), "materials_hotwords": (0, 200),
    "max_tokens": (256, 64000), "keep_last_images": (0, 20), "max_history_messages": (2, 200),
    "listen_max_turns": (1, 200), "pos_x": (-20000, 20000), "pos_y": (-20000, 20000),
}
CHOICES = {
    "backend": ("subscription", "api", "provider"), "provider_vision": ("auto", "yes", "no"), "theme": ("dark", "midnight", "black", "warm", "light", "paper"), "monitor": ("mouse", "primary", "all"),
    "cli_image_mode": ("inline", "file"), "whisper_device": ("auto", "cpu", "cuda"),
    "listen_style": ("short", "detailed"), "language": ("auto", "ru", "uk", "en"),
    "listen_language": ("auto", "ru", "uk", "en"), "math_fontset": ("cm", "stix", "dejavusans", "dejavuserif"),
    "cli_effort": ("", "low", "medium", "high", "xhigh", "max"),
    "listen_effort": ("", "low", "medium", "high", "xhigh", "max"),
}
NULLABLE = {"pos_x", "pos_y"}


def normalize(key, value):
    """→ (подходит ли, приведённое значение). Целые — целыми, числа — в пределах, списки — из строк."""
    default = DEFAULTS[key]
    if value is None:
        return (key in NULLABLE), value
    if isinstance(default, bool) or (key in ("tray", "protect", "compact")):
        return isinstance(value, bool), value
    if isinstance(default, (int, float)) or key in NULLABLE:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            return False, value
        lo, hi = RANGES.get(key, (float("-inf"), float("inf")))
        value = min(max(value, lo), hi)
        if isinstance(default, int) or key in NULLABLE:
            value = int(round(value))
        return True, value
    if isinstance(default, list):
        ok = isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value) and value
        return bool(ok), value
    if isinstance(default, str):
        if not isinstance(value, str):
            return False, value
        if key in CHOICES and value not in CHOICES[key]:
            return False, value
        return True, value
    return isinstance(value, type(default)), value


S = Settings()


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def load_api_key():
    """Ключ API: файл workspace/api_key.txt, старый api_key.txt рядом с программой или ANTHROPIC_API_KEY."""
    for path in (API_KEY_PATH, os.path.join(HERE, "api_key.txt")):
        key = read_text(path)
        if key:
            return key
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def save_api_key(key):
    if key:
        write_text(API_KEY_PATH, key.strip())
    else:
        try:
            os.remove(API_KEY_PATH)
        except OSError:
            pass


def mask_secret(s):
    """Ключи и токены никогда не показываем — даже частично."""
    return "•••••••• (скрыто)" if (s or "").strip() else ""
