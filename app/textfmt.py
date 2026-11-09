# -*- coding: utf-8 -*-
"""Текст: слово-обращение «Клод», мусор распознавания, простой Markdown и формулы (рисуются картинками
через matplotlib mathtext — LaTeX ставить не нужно)."""

import io
import re

from .config import S

# ---------------------------------------------------------------- «Клод, …»

_WAKE_CACHE = {}


def wake_re():
    words = tuple(w.strip().lower() for w in (S.wake_words or []) if w.strip()) or ("клод",)
    rx = _WAKE_CACHE.get(words)
    if rx is None:
        rx = re.compile(
            r"(?<!\w)(?:(?:эй|окей|ok|hey)[\s,]*)?(?:" + "|".join(map(re.escape, words)) + r")(?!\w)[\s,.:;!?\-—…]*",
            re.IGNORECASE)
        _WAKE_CACHE.clear()
        _WAKE_CACHE[words] = rx
    return rx


HALLUCINATIONS = ("продолжение следует", "субтитры", "спасибо за просмотр", "подписывайтесь",
                  "редактор субтитров", "корректор", "amara.org", "dimatorzok")


def is_junk(text: str) -> bool:
    low = text.lower().strip()
    if len(low) < 2:
        return True
    if len(low.split()) <= 8 and any(h in low for h in HALLUCINATIONS):
        return True
    return False


def split_wake(text: str):
    """Возвращает текст после слова «Клод», если оно есть среди первых трёх слов, иначе None."""
    m = wake_re().search(text)
    if not m:
        return None
    if len(text[: m.start()].split()) > 2:
        return None
    return text[m.end():]


def strip_tail_junk(text):
    """Убирает «галлюцинации» Whisper в конце (вроде «Продолжение следует…») — бывают на тишине."""
    t = text.strip()
    for _ in range(3):
        low = t.lower()
        hit = next((h for h in HALLUCINATIONS if h in low[-len(h) - 30:]), None)
        if not hit:
            break
        t = t[: low.rfind(hit)].rstrip(" ,-—")
    return t


def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


# ---------------------------------------------------------------- Markdown

MATH = "\x00math"   # маркер формулы в списке сегментов: (MATH, (tex, display))
CODE = "\x00code"   # маркер начала блока кода: (CODE, (номер блока, язык)) — для кнопки «Копировать»

INLINE_RE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`|\$[^$\n]+?\$|\\\(.+?\\\))")
DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)


def _inline_segments(line, out, extra=()):
    math = S.math_render
    for part in INLINE_RE.split(line):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            _inline_segments(part[2:-2], out, extra + ("b",))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append((part[1:-1], extra + ("ic",)))
        elif math and part.startswith("$") and part.endswith("$") and len(part) > 2 \
                and not part[1].isspace() and not part[-2].isspace():
            out.append((MATH, (part[1:-1], False)))
        elif math and part.startswith("\\(") and part.endswith("\\)"):
            out.append((MATH, (part[2:-2], False)))
        else:
            out.append((part, extra))


def _text_segments(text, out):
    pieces = DISPLAY_RE.split(text) if S.math_render else [text]
    # split с двумя группами даёт: текст, $$-группа, \[-группа, текст, ...
    for i in range(0, len(pieces), 3):
        piece = pieces[i]
        if i > 0 and piece.startswith("\n"):  # перевод строки после формулы уже вставлен
            piece = piece[1:]
        lines = piece.split("\n") if (piece or i == 0) else []
        for j, line in enumerate(lines):
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m:
                out.append((m.group(2).replace("**", ""), ("h",)))
            else:
                m = re.match(r"^(\s*)[-*+]\s+(.*)", line)
                if m:
                    line = m.group(1) + "• " + m.group(2)
                _inline_segments(line, out)
            if j < len(lines) - 1:
                out.append(("\n", ()))
        if i + 2 < len(pieces):
            tex = pieces[i + 1] if pieces[i + 1] is not None else pieces[i + 2]
            prev_display = bool(out) and out[-1][0] == MATH and out[-1][1][1]
            if out and out[-1][0] != "\n" and not prev_display:
                out.append(("\n", ()))
            out.append((MATH, (tex, True)))


def md_segments(src: str, code_marks=False):
    """Простой рендер Markdown (+ формулы) → список (текст, теги) или (MATH, (tex, display)).
    code_marks=True — перед каждым блоком кода ставится (CODE, (номер, язык)) для кнопки «Копировать»."""
    out = []
    buf = []
    in_code = False
    n_code = 0
    for line in src.split("\n"):
        if line.strip().startswith("```"):
            if not in_code:
                if buf:
                    _text_segments("\n".join(buf), out)
                    out.append(("\n", ()))
                    buf = []
                if code_marks:
                    out.append((CODE, (n_code, line.strip()[3:].strip())))
                n_code += 1
            in_code = not in_code
            continue
        if in_code:
            out.append((line + "\n", ("code",)))
        else:
            buf.append(line)
    if buf:
        _text_segments("\n".join(buf), out)
        out.append(("\n", ()))
    return out


def code_blocks(src: str):
    """Все блоки кода ответа по порядку (незакрытый последний — тоже)."""
    blocks, cur = [], None
    for line in src.split("\n"):  # так же, как md_segments: блок открывает/закрывает строка с ```
        if line.strip().startswith("```"):
            if cur is None:
                cur = []
            else:
                blocks.append("\n".join(cur))
                cur = None
            continue
        if cur is not None:
            cur.append(line)
    if cur is not None:
        blocks.append("\n".join(cur))
    return [b.rstrip("\n") for b in blocks]


def last_code_block(src: str):
    blocks = code_blocks(src)
    return blocks[-1] if blocks else None


# ---------------------------------------------------------------- формулы

_TEX_SUBS = [
    (r"\\le(?![a-zA-Z])", r"\\leq"), (r"\\ge(?![a-zA-Z])", r"\\geq"),
    (r"\\lt(?![a-zA-Z])", "<"), (r"\\gt(?![a-zA-Z])", ">"),
    (r"\\(arcctg|arctg|ctg|tg|cosec|sh|ch|th)(?![a-zA-Z])", r"\\mathrm{\1}\\,"),
    (r"\\(displaystyle|textstyle|limits|nolimits)(?![a-zA-Z])", ""),
    (r"\\boxed\{", "{"), (r"\\dots(?![a-zA-Z])", r"\\ldots"),
    (r"\\degree(?![a-zA-Z])", r"^{\\circ}"), (r"\\tfrac(?![a-zA-Z])", r"\\frac"),
    (r"\\begin\{[a-zA-Z*]+\}(\{[^}]*\})?", ""), (r"\\end\{[a-zA-Z*]+\}", ""),
]


# команды, у которых Claude иногда опускает фигурные скобки: \frac52, \sqrt2 — LaTeX это понимает, matplotlib нет
_ARG_CMDS = {"frac": 2, "dfrac": 2, "tfrac": 2, "cfrac": 2, "binom": 2, "dbinom": 2, "tbinom": 2, "sqrt": 1}


def _group_end(t, i):
    """t[i] == "{" → индекс парной «}» (или len(t), если её нет)."""
    depth = 0
    j = i
    while j < len(t):
        if t[j] == "\\":
            j += 2
            continue
        if t[j] == "{":
            depth += 1
        elif t[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(t)


def fix_shorthand(t):
    """\\frac52 → \\frac{5}{2}, \\sqrt2 → \\sqrt{2}, \\frac\\pi2 → \\frac{\\pi}{2} (в том числе внутри других скобок)."""
    out, i, n = [], 0, len(t)
    while i < n:
        m = re.match(r"\\([a-zA-Z]+)", t[i:])
        if not m:
            out.append(t[i])
            i += 1
            continue
        name = m.group(1)
        out.append(m.group(0))
        i += len(m.group(0))
        if name not in _ARG_CMDS:
            continue
        if name == "sqrt" and i < n and t[i] == "[":   # \sqrt[3]{8}
            j = t.find("]", i)
            j = n - 1 if j < 0 else j
            out.append(t[i:j + 1])
            i = j + 1
        for _ in range(_ARG_CMDS[name]):
            while i < n and t[i] == " ":
                i += 1
            if i >= n:
                break
            if t[i] == "{":
                j = _group_end(t, i)
                out.append("{" + fix_shorthand(t[i + 1:j]) + "}")
                i = j + 1
            elif t[i] == "\\":
                a = re.match(r"\\([a-zA-Z]+|.)", t[i:]).group(0)
                out.append("{" + a + "}")
                i += len(a)
            else:
                out.append("{" + t[i] + "}")
                i += 1
    return "".join(out)


def tex_rows(tex, display):
    """Подгоняет LaTeX под то, что умеет matplotlib; многострочные формулы режет на строки."""
    t = fix_shorthand(tex.strip())
    for pat, rep in _TEX_SUBS:
        t = re.sub(pat, rep, t)
    rows = [r.replace("&", " ").strip() for r in re.split(r"\\\\", t)] if display else [t.replace("\\\\", " ")]
    rows = [r for r in rows if r]
    if display:
        rows = [re.sub(r"\\frac(?![a-zA-Z])", r"\\dfrac", r) for r in rows]
    return rows


def render_tex(tex, size, dpi, fg, bg, pad=0.02):
    """LaTeX-формула → картинка PIL (через встроенный в matplotlib движок, LaTeX ставить не нужно)."""
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from PIL import Image

    with matplotlib.rc_context({"mathtext.fontset": S.math_fontset or "cm"}):
        fig = Figure(figsize=(0.01, 0.01), dpi=dpi)
        FigureCanvasAgg(fig)
        fig.text(0, 0, f"${tex}$", fontsize=size, color=fg)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor=bg, bbox_inches="tight", pad_inches=pad)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def warm_up_math(fg="#e8e8e8", bg="#16181d"):
    try:
        render_tex(r"\frac{1}{2}", 12, 96, fg, bg)
    except Exception as e:
        print("[math] формулы будут текстом:", e)


# ---------------------------------------------------------------- запасной вид формулы (если не нарисовалась)

_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "le": "≤", "leq": "≤", "leqslant": "≤",
    "ge": "≥", "geq": "≥", "geqslant": "≥", "ne": "≠", "neq": "≠", "approx": "≈", "equiv": "≡", "sim": "~",
    "infty": "∞", "to": "→", "rightarrow": "→", "Rightarrow": "⇒", "leftarrow": "←", "Leftrightarrow": "⇔",
    "iff": "⇔", "implies": "⇒", "in": "∈", "notin": "∉", "subset": "⊂", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "partial": "∂", "nabla": "∇", "int": "∫", "iint": "∬", "oint": "∮",
    "sum": "Σ", "prod": "Π", "perp": "⊥", "parallel": "∥", "angle": "∠", "circ": "°", "degree": "°",
    "ldots": "…", "dots": "…", "cdots": "⋯", "emptyset": "∅", "neg": "¬", "land": "∧", "lor": "∨",
    "quad": "  ", "qquad": "    ", "sin": "sin", "cos": "cos", "tan": "tan", "tg": "tg", "ctg": "ctg",
    "cot": "cot", "ln": "ln", "log": "log", "lim": "lim", "max": "max", "min": "min", "exp": "exp",
}
_SUP = str.maketrans("0123456789+-=()nix", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _arg(t, i):
    """Аргумент команды с позиции i: {…} или один знак/команда → (текст аргумента, следующая позиция)."""
    while i < len(t) and t[i] == " ":
        i += 1
    if i >= len(t):
        return "", i
    if t[i] == "{":
        j = _group_end(t, i)
        return t[i + 1:j], j + 1
    m = re.match(r"\\[a-zA-Z]+|.", t[i:])
    return m.group(0), i + len(m.group(0))


def _wrap(s):
    """Скобки вокруг составного числителя/знаменателя: (a+b)/(c), а простое — как есть."""
    return s if re.fullmatch(r"[\w.,′]+", s) else f"({s})"


def tex_to_text(tex):
    """LaTeX → читаемый текст для запасного вида: \\frac{5}{2} → 5/2, \\lambda → λ, x^2 → x², \\sqrt{x} → √x."""
    t = fix_shorthand(tex)
    out, i = [], 0
    while i < len(t):
        ch = t[i]
        if ch == "\\":
            m = re.match(r"\\([a-zA-Z]+|.)", t[i:])
            name = m.group(1)
            i += len(m.group(0))
            if name in ("frac", "dfrac", "tfrac", "cfrac"):
                a, i = _arg(t, i)
                b, i = _arg(t, i)
                out.append(f"{_wrap(tex_to_text(a))}/{_wrap(tex_to_text(b))}")
            elif name == "sqrt":
                deg = ""
                if i < len(t) and t[i] == "[":
                    j = t.find("]", i)
                    deg, i = t[i + 1:j].translate(_SUP), j + 1
                a, i = _arg(t, i)
                out.append(f"{deg}√{_wrap(tex_to_text(a))}")
            elif name in ("text", "mathrm", "mathbf", "mathit", "operatorname", "textbf", "mbox", "mathbb"):
                a, i = _arg(t, i)
                out.append(tex_to_text(a) if name != "mathbb" else {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ",
                                                                    "C": "ℂ"}.get(a, a))
            elif name in ("vec", "overrightarrow", "overline", "bar", "hat", "widehat", "tilde"):
                a, i = _arg(t, i)
                mark = {"vec": "\u20d7", "overrightarrow": "\u20d7", "overline": "\u0305", "bar": "\u0305"}.get(name, "")
                out.append(tex_to_text(a) + mark)
            elif name in ("left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "limits", "nolimits"):
                continue
            elif name in (",", ";", ":", " ", "!"):
                out.append(" " if name != "!" else "")
            elif name in ("{", "}", "%", "$", "#", "&", "_"):
                out.append(name)
            elif name == "\\":
                out.append("; ")
            else:
                out.append(_SYMBOLS.get(name, name))
        elif ch in "^_":
            a, i = _arg(t, i + 1)
            s = tex_to_text(a)
            table = _SUP if ch == "^" else _SUB
            conv = s.translate(table)
            if all(c in "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣ₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎" for c in conv):
                out.append(conv)
            else:
                out.append(("^" if ch == "^" else "_") + _wrap(s))
        elif ch in "{}":
            i += 1
        elif ch == "&":
            out.append(" ")
            i += 1
        else:
            out.append(ch)
            i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()
