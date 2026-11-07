# -*- coding: utf-8 -*-
"""История вопросов и ответов между запусками: workspace/history/ГГГГ-ММ-ДД.jsonl (одна строка — один обмен).
Хранится только текст (без скриншотов), только на этом компьютере. Выключается в ⚙ → «Невидимость и система»."""

import glob
import json
import os
import shutil
import time

from .config import WORKDIR

HIST_DIR = os.path.join(WORKDIR, "history")
KIND_ICONS = {"voice": "🎙", "text": "⌨", "f7": "🎧", "materials": "📎"}
KIND_NAMES = {"voice": "голосом", "text": "текстом", "f7": "звук компьютера", "materials": "материалы"}


def add(question, answer, kind="voice", mode="", error=""):
    os.makedirs(HIST_DIR, exist_ok=True)
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "q": question, "a": answer, "kind": kind, "mode": mode}
    if error:
        rec["error"] = error
    path = os.path.join(HIST_DIR, time.strftime("%Y-%m-%d") + ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load(query="", limit=2000):
    """Записи, новые первыми; query — поиск по вопросу и ответу (без учёта регистра)."""
    out = []
    q = (query or "").strip().lower()
    for path in sorted(glob.glob(os.path.join(HIST_DIR, "*.jsonl")), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or "q" not in rec:
                continue
            if q and q not in (rec.get("q", "") + "\n" + rec.get("a", "")).lower():
                continue
            out.append(rec)
            if len(out) >= limit:
                return out
    return out


def export_markdown(records, path):
    """Сохранить записи в файл .md (читается Блокнотом, Word, Obsidian)."""
    lines = ["# История Claude Overlay", ""]
    for r in sorted(records, key=lambda r: r.get("t", "")):
        kind = KIND_NAMES.get(r.get("kind"), "")
        lines += [f"## {r.get('t', '')} · {kind}", "", f"**Вопрос:** {r.get('q', '')}", "", r.get("a", ""), ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def clear():
    shutil.rmtree(HIST_DIR, ignore_errors=True)


def count():
    n = 0
    for path in glob.glob(os.path.join(HIST_DIR, "*.jsonl")):
        try:
            with open(path, encoding="utf-8") as f:
                n += sum(1 for line in f if line.strip())
        except OSError:
            pass
    return n
