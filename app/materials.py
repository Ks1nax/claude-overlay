# -*- coding: utf-8 -*-
"""Материалы пользователя (📎 / 📋 / перетаскивание): лекции, конспекты, вопросы. Хранится только извлечённый текст —
в workspace/materials, переживает перезапуск. Термины из материалов подсказываются распознаванию речи."""

import json
import os
import re
import shutil
import time
from collections import Counter

from .config import S, MATERIALS_DIR
from .textfmt import plural

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".tex", ".log", ".ini",
            ".py", ".js", ".ts", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".kt", ".swift", ".php",
            ".rb", ".sql", ".sh", ".bat", ".ps1", ".yaml", ".yml", ".srt", ".vtt"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
OLD_OFFICE = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".pdf", ".xlsx": ".pdf", ".odt": ".docx", ".rtf": ".docx"}


def _decode_text(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace")


def _looks_textual(path):
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return b"\x00" not in head or head[:2] in (b"\xff\xfe", b"\xfe\xff")


def _docx_text(path):
    import zipfile
    import xml.etree.ElementTree as ET
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(W + "p"):
        parts = []
        for node in p.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _pptx_text(path):
    import zipfile
    import xml.etree.ElementTree as ET
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    out = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        for i, n in enumerate(sorted(names, key=lambda n: int(re.findall(r"\d+", n)[-1])), 1):
            root = ET.fromstring(z.read(n))
            paras = ["".join(t.text or "" for t in p.iter(A + "t")).strip() for p in root.iter(A + "p")]
            out.append(f"[Слайд {i}]\n" + "\n".join(x for x in paras if x))
    return "\n\n".join(out)


def _pdf_text(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        pages.append(f"[Стр. {i}]\n{t}")
    return "\n\n".join(pages), len(reader.pages)


def extract_material(path, cli):
    """Файл → (текст, короткое описание). Word/PowerPoint/PDF/текст — на месте; картинки и сканы — через Claude."""
    from .claude import claude_read_file
    ext = os.path.splitext(path)[1].lower()
    if ext in OLD_OFFICE:
        raise ValueError(f"формат {ext} не читается — сохрани файл как {OLD_OFFICE[ext]} или PDF")
    if ext == ".docx":
        return _docx_text(path), "Word"
    if ext == ".pptx":
        text = _pptx_text(path)
        n = text.count("[Слайд ")
        return text, f"PowerPoint, {n} {plural(n, 'слайд', 'слайда', 'слайдов')}"
    if ext == ".pdf":
        text, pages = _pdf_text(path)
        if len(re.sub(r"\s+|\[Стр\. \d+\]", "", text)) >= 40 * max(1, pages):
            return text, f"PDF, {pages} стр."
        if not cli:
            raise ValueError("PDF без текстового слоя (скан) — такой может прочитать только Claude Code")
        return claude_read_file(cli, path), f"PDF-скан, {pages} стр., прочитал Claude"
    if ext in TEXT_EXT or (ext not in IMAGE_EXT and _looks_textual(path)):
        with open(path, "rb") as f:
            return _decode_text(f.read()), "текст"
    if cli:
        return claude_read_file(cli, path), ("картинка, прочитал Claude" if ext in IMAGE_EXT else "прочитал Claude")
    raise ValueError("этот формат не поддерживается")


_STOP_WORDS = set("""
который которая которое которые которого которой котором которых также только можно нужно будет между после через когда
дополнено спросить спросят скажи подробнее точно пример примеры примером вопрос вопросы вопросов ответ ответы ответа
термин термины конспект главное контекст ловушки ключевые слова
чтобы этого этот такой такие более всего всех даже очень потому поэтому однако например является являются являться
этом этих тогда здесь там если пока если-то ещё уже может могут должен должны сколько каждый каждая другой другие
первый второй третий свой своих своей своего снова почему какой какая какие какое где куда откуда зачем чего чему
which there their these those where while about would could should other after before because between through using
also have has been being than then them they this that with from into your what when will
""".split())


def _keyword_section(text):
    """Термины из раздела «Ключевые слова» (так их выписывает «Промпт для конспекта»)."""
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^\s*#+\s*", line):
            inside = bool(re.match(r"^\s*#+\s*ключевые слова\b", line, re.I))
            continue
        if inside:
            out += [t.strip(" .;:-—*«»\"'") for t in re.split(r"[,;]", line)]
    return [t for t in out if 2 <= len(t) <= 40]


def material_terms(text, limit=30):
    """Термины из материалов — подсказка распознаванию речи: сначала раздел «Ключевые слова», если он есть,
    потом повторяющиеся длинные слова, аббревиатуры и фамилии."""
    curated = _keyword_section(text)
    words = re.findall(r"[A-Za-zА-Яа-яЁёЇїІіЄєҐґ][A-Za-zА-Яа-яЁёЇїІіЄєҐґ'’\-]{2,}", text)
    counts, forms = Counter(), {}
    for w in words:
        w = w.strip("-'’")
        key = w.lower()
        if len(key) < 4 or key in _STOP_WORDS:
            continue
        is_abbr = w.isupper() and 2 <= len(w) <= 8
        if not is_abbr and len(key) < 7 and not w[0].isupper():
            continue  # короткие обычные слова Whisper и так знает
        counts[key] += 2 if is_abbr else 1
        forms.setdefault(key, Counter())[w] += 1
    terms = [forms[k].most_common(1)[0][0] for k, c in counts.most_common() if c >= 2]
    seen, out = set(), []
    for t in curated + terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit]


class Materials:
    """Материалы пользователя: хранятся в workspace/materials (только извлечённый текст) и переживают перезапуск."""

    def __init__(self):
        self.items = []
        self.load()

    @property
    def index_path(self):
        return os.path.join(MATERIALS_DIR, "index.json")

    def load(self):
        try:
            with open(self.index_path, encoding="utf-8") as f:
                items = json.load(f).get("items", [])
            self.items = [it for it in items if os.path.isfile(os.path.join(MATERIALS_DIR, it["txt"]))]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.items = []

    def save(self):
        os.makedirs(MATERIALS_DIR, exist_ok=True)
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.index_path)

    def add(self, title, text, kind):
        os.makedirs(MATERIALS_DIR, exist_ok=True)
        mid = f"{int(time.time() * 1000)}_{len(self.items)}"
        with open(os.path.join(MATERIALS_DIR, mid + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)
        self.items.append({"id": mid, "title": title, "kind": kind, "chars": len(text), "txt": mid + ".txt"})
        self.save()

    def text(self, mid):
        it = next((x for x in self.items if x["id"] == mid), None)
        if not it:
            return ""
        try:
            with open(os.path.join(MATERIALS_DIR, it["txt"]), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def remove(self, mid):
        it = next((x for x in self.items if x["id"] == mid), None)
        if not it:
            return False
        self.items.remove(it)
        try:
            os.remove(os.path.join(MATERIALS_DIR, it["txt"]))
        except OSError:
            pass
        self.save()
        return True

    def clear(self):
        self.items = []
        shutil.rmtree(MATERIALS_DIR, ignore_errors=True)

    def full_text(self):
        """→ (текст для Claude, обрезано ли)."""
        limit = S.materials_max_chars
        parts, total, cut = [], 0, False
        for it in self.items:
            try:
                with open(os.path.join(MATERIALS_DIR, it["txt"]), encoding="utf-8") as f:
                    body = f.read()
            except OSError:
                continue
            block = f"=== {it['title']} ({it['kind']}) ===\n{body.strip()}\n"
            if total + len(block) > limit:
                block = block[: max(0, limit - total)] + "\n[…дальше обрезано…]\n"
                cut = True
            parts.append(block)
            total += len(block)
            if cut:
                break
        return "\n".join(parts), cut

    def summary(self):
        if not self.items:
            return ""
        names = ", ".join(it["title"] for it in self.items[:4]) + (f" и ещё {len(self.items) - 4}" if len(self.items) > 4 else "")
        chars = sum(it["chars"] for it in self.items)
        return f"{names} · ~{chars // 1000 if chars >= 1000 else chars}{' тыс.' if chars >= 1000 else ''} знаков"
