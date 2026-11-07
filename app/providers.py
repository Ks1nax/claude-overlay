# -*- coding: utf-8 -*-
"""Другие провайдеры ИИ по API-ключу: OpenAI, Google Gemini, OpenRouter, DeepSeek, Groq, Mistral, xAI, а также
модели на своём компьютере (Ollama, LM Studio) и любой сервис, совместимый с OpenAI.

Все они понимают один формат — OpenAI Chat Completions (POST {адрес}/chat/completions, ответ потоком SSE), поэтому
клиент один и без лишних библиотек (urllib). Картинка (скриншот) передаётся как data:-URL, если модель видит
картинки. Ключи хранятся в workspace/api_keys.json и нигде не показываются."""

import json
import os
import socket
import ssl
import urllib.error
import urllib.request

from .config import S, WORKDIR

KEYS_PATH = os.path.join(WORKDIR, "api_keys.json")


class Provider:
    def __init__(self, pid, title, base_url, model, listen_model, key_url, vision, needs_key, env, note=""):
        self.id, self.title, self.base_url, self.model, self.listen_model = pid, title, base_url, model, listen_model
        self.key_url, self.vision, self.needs_key, self.env, self.note = key_url, vision, needs_key, env, note


# Модели по умолчанию — разумный старт; список моделей провайдера загружается кнопкой «Загрузить список».
PROVIDERS = [
    Provider("openai", "OpenAI (ChatGPT)", "https://api.openai.com/v1", "gpt-4.1-mini", "gpt-4.1-mini",
             "https://platform.openai.com/api-keys", True, True, "OPENAI_API_KEY"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
             "gemini-2.5-flash", "gemini-2.5-flash", "https://aistudio.google.com/apikey", True, True,
             "GEMINI_API_KEY", "есть бесплатный уровень"),
    Provider("openrouter", "OpenRouter (сотни моделей по одному ключу)", "https://openrouter.ai/api/v1",
             "openai/gpt-4.1-mini", "openai/gpt-4.1-mini", "https://openrouter.ai/keys", True, True,
             "OPENROUTER_API_KEY"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat", "deepseek-chat",
             "https://platform.deepseek.com/api_keys", False, True, "DEEPSEEK_API_KEY",
             "не видит картинки — скриншот не передаётся"),
    Provider("groq", "Groq (очень быстрые ответы)", "https://api.groq.com/openai/v1",
             "meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-scout-17b-16e-instruct",
             "https://console.groq.com/keys", True, True, "GROQ_API_KEY", "есть бесплатный уровень"),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", "mistral-small-latest",
             "https://console.mistral.ai/api-keys", True, True, "MISTRAL_API_KEY"),
    Provider("xai", "xAI (Grok)", "https://api.x.ai/v1", "grok-3-mini", "grok-3-mini",
             "https://console.x.ai", False, True, "XAI_API_KEY"),
    Provider("ollama", "Ollama — модель на этом компьютере (без интернета)", "http://localhost:11434/v1",
             "llama3.2-vision", "llama3.2-vision", "https://ollama.com/download", True, False, "",
             "ключ не нужен; модель скачай в Ollama заранее"),
    Provider("lmstudio", "LM Studio — модель на этом компьютере", "http://localhost:1234/v1", "", "",
             "https://lmstudio.ai", False, False, "", "ключ не нужен; включи сервер в LM Studio"),
    Provider("custom", "Другой сервис, совместимый с OpenAI", "", "", "", "", True, False, "",
             "впиши адрес сервиса"),
]
BY_ID = {p.id: p for p in PROVIDERS}


class ProviderError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- ключи (никогда не показываются)

def _read_keys():
    try:
        with open(KEYS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_key(pid):
    key = (_read_keys().get(pid) or "").strip()
    p = BY_ID.get(pid)
    if not key and p and p.env:
        key = os.environ.get(p.env, "").strip()
    return key


def save_key(pid, key):
    data = _read_keys()
    if key:
        data[pid] = key.strip()
    else:
        data.pop(pid, None)
    os.makedirs(os.path.dirname(KEYS_PATH), exist_ok=True)
    tmp = KEYS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, KEYS_PATH)


# ---------------------------------------------------------------- текущий выбор из настроек

def current():
    """→ словарь с тем, что выбрано в ⚙: id, title, base_url, model, listen_model, vision, key."""
    p = BY_ID.get(S.provider) or BY_ID["openai"]
    base = (S.provider_base_url or "").strip() or p.base_url
    model = (S.provider_model or "").strip() or p.model
    listen = (S.provider_listen_model or "").strip() or model
    vision = {"yes": True, "no": False}.get(S.provider_vision, p.vision)  # "auto" — как у провайдера
    return {"id": p.id, "title": p.title, "base_url": base.rstrip("/"), "model": model, "listen_model": listen,
            "vision": bool(vision), "key": load_key(p.id), "needs_key": p.needs_key}


def problem(cfg):
    """Что мешает работать (понятными словами) или ""."""
    if not cfg["base_url"]:
        return "Не задан адрес сервиса: ⚙ → «Подключение к ИИ» → «Адрес»."
    if cfg["needs_key"] and not cfg["key"]:
        return f"Нет ключа для «{cfg['title']}»: ⚙ → «Подключение к ИИ» → впиши ключ и нажми «Сохранить»."
    if not cfg["model"]:
        return "Не выбрана модель: ⚙ → «Подключение к ИИ» → «Загрузить список» и выбери модель."
    return ""


# ---------------------------------------------------------------- запросы

def _request(url, key, body=None, timeout=60):
    headers = {"Content-Type": "application/json", "User-Agent": "ClaudeOverlay"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if "openrouter.ai" in url:
        headers["X-Title"] = "Claude Overlay"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
            j = json.loads(raw)
            err = j.get("error") if isinstance(j, dict) else None
            msg = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or raw
            if isinstance(j, list) and j and isinstance(j[0], dict):   # Gemini иногда отвечает списком
                msg = (j[0].get("error") or {}).get("message") or raw
        except Exception:
            msg = getattr(e, "reason", "") or str(e)
        raise ProviderError(f"HTTP {e.code}: {str(msg)[:400]}", e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ProviderError(f"нет связи с {url.split('/')[2] if '//' in url else url}: {reason}") from None


def to_openai(system, messages, vision):
    """Сообщения в формате Claude (блоки text/image) → формат OpenAI. Без «зрения» картинки выкидываются."""
    out = [{"role": "system", "content": system}] if system else []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        parts, dropped = [], False
        for b in c:
            if b.get("type") == "text":
                parts.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "image":
                if vision:
                    src = b["source"]
                    parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
                else:
                    dropped = True
        if dropped:
            parts.append({"type": "text", "text": "[скриншот экрана не передан: эта модель не видит картинки]"})
        if all(p["type"] == "text" for p in parts):  # некоторые сервисы принимают только строку
            out.append({"role": m["role"], "content": "\n\n".join(p["text"] for p in parts)})
        else:
            out.append({"role": m["role"], "content": parts})
    return out


def stream_chat(cfg, model, system, messages, on_text, cancel=None, max_tokens=None, timeout=120):
    """Ответ потоком: on_text(кусок) на каждый кусок. Исключение ProviderError — с понятным текстом."""
    body = {"model": model, "messages": to_openai(system, messages, cfg["vision"]), "stream": True,
            "max_tokens": int(max_tokens or S.max_tokens)}
    resp = _request(cfg["base_url"] + "/chat/completions", cfg["key"], body, timeout=timeout)
    got = False
    with resp:
        for raw in resp:
            if cancel is not None and cancel.is_set():
                return got
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue   # пустые строки и служебные комментарии (": processing")
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("error"):
                err = ev["error"]
                raise ProviderError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
            for ch in (ev.get("choices") or []):
                piece = (ch.get("delta") or {}).get("content")
                if isinstance(piece, list):   # редкий формат: список частей
                    piece = "".join(x.get("text", "") for x in piece if isinstance(x, dict))
                if piece:
                    got = True
                    on_text(piece)
    return got


def provider_ask(ui_q, cfg, rid, model, system, messages, cancel):
    """Запрос в поток окна: ("delta", rid, текст) … ("done", rid) или ("error", rid, текст)."""
    try:
        got = stream_chat(cfg, model, system, messages, lambda t: ui_q.put(("delta", rid, t)), cancel)
        if cancel.is_set():
            return
        if not got:
            ui_q.put(("error", rid, f"{cfg['title']}: пустой ответ (модель {model})"))
        else:
            ui_q.put(("done", rid))
    except ProviderError as e:
        if not cancel.is_set():
            ui_q.put(("error", rid, f"{cfg['title']}: {e}"))
    except Exception as e:
        if not cancel.is_set():
            ui_q.put(("error", rid, f"{cfg['title']}: {e}"))


def list_models(cfg, timeout=20):
    """Модели провайдера (GET /models) → отсортированный список названий."""
    with _request(cfg["base_url"] + "/models", cfg["key"], timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for it in items or []:
        mid = it.get("id") if isinstance(it, dict) else str(it)
        if mid:
            ids.append(mid.replace("models/", "", 1) if mid.startswith("models/") else mid)
    return sorted(set(ids), key=str.lower)


def check(cfg, model=None, timeout=60):
    """Пробный вопрос → (успех, ответ или ошибка)."""
    parts = []
    try:
        stream_chat(cfg, model or cfg["model"], "", [{"role": "user", "content": "ответь одним словом: ок"}],
                    parts.append, max_tokens=20, timeout=timeout)
    except ProviderError as e:
        return False, str(e)
    text = "".join(parts).strip()
    return (True, text) if text else (False, "пустой ответ")


def explain(text):
    """Ошибка провайдера → что делать (или "")."""
    low = (text or "").lower()
    if "http 401" in low or "http 403" in low or "invalid api key" in low or "incorrect api key" in low \
            or "unauthorized" in low or "api key not valid" in low:
        return "Ключ не подходит: проверь, что скопирован целиком и от того же сервиса (⚙ → «Подключение к ИИ»)."
    if "http 404" in low or "model not found" in low or "does not exist" in low or "not found" in low:
        return "Такой модели у сервиса нет: ⚙ → «Подключение к ИИ» → «Загрузить список» и выбери из списка."
    if "http 429" in low or "rate limit" in low or "quota" in low or "insufficient" in low:
        return "Лимит или деньги на счёте закончились. Подожди или пополни баланс у провайдера."
    if "http 402" in low or "payment" in low or "credits" in low:
        return "На счёте у провайдера нет денег — пополни баланс."
    if "image" in low and ("support" in low or "vision" in low):
        return ("Эта модель не принимает картинки: выключи «Модель видит картинки» в ⚙ → «Подключение к ИИ» "
                "или выбери другую модель.")
    if "нет связи" in low:
        if "localhost" in low or "127.0.0.1" in low:
            return "Программа с моделью на этом компьютере не запущена — открой Ollama / LM Studio."
        return "Нет связи с сервисом. Проверь интернет (и VPN, если сервис без него недоступен)."
    return ""
