# -*- coding: utf-8 -*-
"""Тесты Claude Overlay. Запуск из папки программы:

    .venv\\Scripts\\python.exe tests\\test_overlay.py            — логика, без окон и устройств
    .venv\\Scripts\\python.exe tests\\test_overlay.py --ui       — плюс окна Tk (прозрачные: на экране их не видно)
    .venv\\Scripts\\python.exe tests\\test_overlay.py --whisper  — плюс настоящее распознавание «Клод, …» (нужна модель small)

Рабочая папка — временная (CLAUDE_OVERLAY_WORKDIR): настоящие настройки и материалы не трогаются.
Микрофон, звук компьютера, перехват клавиш и Claude в тестах окон заменены заглушками."""

import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import traceback
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="overlay_test_")
os.environ["CLAUDE_OVERLAY_WORKDIR"] = os.path.join(TMP, "workspace")
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from app.config import S, Settings, DEFAULTS, WORKDIR  # noqa: E402
from app import stt as _stt  # noqa: E402

REAL_TRANSCRIBER = _stt.Transcriber   # тесты окон подменяют его заглушкой

assert WORKDIR.startswith(TMP), "тесты должны работать во временной папке"
UI = "--ui" in sys.argv
WHISPER = "--whisper" in sys.argv
RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


# ---------------------------------------------------------------- настройки

@test
def test_settings_roundtrip():
    p = os.path.join(TMP, "s1.json")
    s = Settings(p)
    assert s.width == DEFAULTS["width"] and not os.path.exists(p)
    assert s.update(width=700, font_size=13) == {"width", "font_size"}
    data = json.load(open(p, encoding="utf-8"))
    assert data == {"width": 700, "font_size": 13}, data      # в файле только отличия
    s2 = Settings(p)
    assert s2.width == 700 and s2.font_size == 13 and s2.alpha == DEFAULTS["alpha"]
    s2.reset("width")
    assert Settings(p).width == DEFAULTS["width"]


@test
def test_settings_corrupt_and_types():
    p = os.path.join(TMP, "s2.json")
    open(p, "w").write("{ испорчено")
    s = Settings(p)
    assert s.load_error and os.path.exists(p + ".bad") and s.width == DEFAULTS["width"]
    json.dump({"width": "широко", "tray": 1, "font_size": 14, "unknown": 5}, open(p, "w"))
    s = Settings(p)
    assert s.width == DEFAULTS["width"] and s.tray is False and s.font_size == 14
    changed = []
    s.on_change(changed.append)
    s.update(tray=True)
    assert changed == [{"tray"}]


# ---------------------------------------------------------------- «Клод», Markdown, формулы

@test
def test_wake_words():
    from app.textfmt import split_wake, is_junk, strip_tail_junk
    assert split_wake("Клод, реши задачу") == "реши задачу"
    assert split_wake("Окей, Клод, объясни") == "объясни"
    assert split_wake("Кладик, что тут") == "что тут"
    assert split_wake("Claude, help") == "help"
    assert split_wake("я сказал другу что клод молодец") is None   # «Клод» не в начале
    assert split_wake("сколько будет два плюс два") is None
    assert is_junk("Продолжение следует...") and not is_junk("Клод, стоп")
    assert strip_tail_junk("Вопрос про интеграл. Продолжение следует...") == "Вопрос про интеграл."


@test
def test_markdown_and_code():
    from app.textfmt import md_segments, code_blocks, last_code_block, MATH, CODE
    src = "Ответ $x^2$ и\n$$\\frac{1}{2}$$\n```python\nprint(1)\n```\nещё\n```\nb = 2\n```"
    segs = md_segments(src, code_marks=True)
    codes = [t for s, t in segs if s == CODE]
    assert codes == [(0, "python"), (1, "")], codes
    assert code_blocks(src) == ["print(1)", "b = 2"]
    assert any(s == MATH and t == ("x^2", False) for s, t in segs)
    assert any(s == MATH and t[1] for s, t in segs)
    assert last_code_block("```js\nlet a\n") == "let a"           # блок ещё не закрыт
    assert last_code_block("без кода") is None


@test
def test_formula_shorthand_and_fallback():
    """Claude пишет \\frac52 и \\sqrt2 без скобок — раньше такие формулы печатались исходным текстом."""
    from app.textfmt import fix_shorthand, tex_rows, render_tex, tex_to_text
    assert fix_shorthand(r"\frac52") == r"\frac{5}{2}" and fix_shorthand(r"\sqrt2") == r"\sqrt{2}"
    assert fix_shorthand(r"\dfrac\pi 2+\frac{1}{\frac34}") == r"\dfrac{\pi}{2}+\frac{1}{\frac{3}{4}}"
    assert fix_shorthand(r"\sqrt[3]{8}") == r"\sqrt[3]{8}" and fix_shorthand(r"\frac{a}{b}") == r"\frac{a}{b}"
    for tex in (r"x_F=\frac{x_A+\lambda x_C}{1+\lambda}=\frac{-3+\frac52\cdot(-1)}{\frac72}=-\frac{11}{7}",
                r"\overrightarrow{BF}=\left(-\frac{11}{7}-1;\ \frac{22}{7}-4\right)=-\frac67(3;1)",
                r"\dfrac{AF}{FC}=\dfrac52=\lambda", r"\sqrt2+\sqrt[3]{8}"):
        for row in tex_rows(tex, True):
            assert render_tex(row, 14, 96, "#eeeeee", "#111111").width > 10, row
    assert tex_to_text(r"\frac{-3+\frac52\cdot(-1)}{\frac72}") == "(-3+5/2·(-1))/(7/2)"
    assert tex_to_text(r"x^2\geq0,\ \alpha\in\mathbb{R}") == "x²≥0, α∈ℝ"


@test
def test_formula_render():
    from app.textfmt import render_tex, tex_rows
    img = render_tex(r"\frac{1}{2}", 14, 96, "#e8e8e8", "#16181d")
    assert img.width > 5 and img.height > 5
    assert tex_rows(r"\begin{cases} a \\ b \end{cases}", True) == ["a", "b"]


# ---------------------------------------------------------------- клавиши

@test
def test_hotkeys():
    from app.hotkeys import parse_spec, make_spec, display, problems
    assert parse_spec("<f7>") == ((), "f7") and display("<f7>") == "F7"
    assert parse_spec("<ctrl>+<alt>+q") == (("ctrl", "alt"), "q") and display("<ctrl>+<alt>+q") == "Ctrl+Alt+Q"
    assert make_spec(("shift",), "f8") == "<shift>+<f8>"
    assert parse_spec("что-то") is None and display("") == "нет"
    pr = problems({"listen": "<f7>", "talk": "<f7>", "toggle": "a"})
    assert any("дважды" in p for p in pr) and any("нельзя" in p for p in pr)
    assert not problems({"listen": "<f7>", "talk": "<f8>", "toggle": "<f9>"})


@test
def test_hotkey_hook_esc_repeat():
    """Esc отменяет запись F7 каждый раз (раньше — только первый: отпускание Esc «залипало»)."""
    from app import hotkeys

    class Suppress(Exception):
        pass

    class FakeListener:
        def __init__(self, win32_event_filter):
            self.flt = win32_event_filter
            self.daemon = False

        def start(self):
            pass

        def suppress_event(self):
            raise Suppress()

    class FakeKB:
        Listener = FakeListener

    class Data:
        def __init__(self, vk):
            self.vkCode = vk

    hotkeys._held = lambda vks: False
    events, rec = [], {"on": False}
    hk = hotkeys.HotkeyManager(events.append, esc_active=lambda: rec["on"])
    hk.set_binds({"listen": "<f7>"})
    hk._start_win(FakeKB)
    flt = hk.listener.flt

    def press(vk, down):
        try:
            return flt(0x0100 if down else 0x0101, Data(vk))
        except Suppress:
            return "suppressed"

    for _ in range(3):
        assert press(0x76, True) == "suppressed" and press(0x76, False) == "suppressed"   # F7 — наша
        rec["on"] = True
        assert press(0x1B, True) == "suppressed"
        rec["on"] = False                                     # окно уже отменило запись
        assert press(0x1B, False) == "suppressed"
    assert events == ["listen", "listen_cancel"] * 3, events
    assert press(0x1B, True) is True and press(0x1B, False) is True   # без записи Esc — обычная клавиша
    assert press(0x41, True) is True                                  # чужие клавиши проходят


# ---------------------------------------------------------------- материалы

def _make_docx(path, paras):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def _make_pptx(path, slides):
    with zipfile.ZipFile(path, "w") as z:
        for i, text in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml",
                       '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>'
                       f"{text}</a:t></a:r></a:p></p:sld>")


@test
def test_materials_formats():
    from app.materials import extract_material
    d = os.path.join(TMP, "mats")
    os.makedirs(d, exist_ok=True)
    _make_docx(os.path.join(d, "a.docx"), ["Нормальная форма Бойса — Кодда", "Вторая строка"])
    t, kind = extract_material(os.path.join(d, "a.docx"), None)
    assert "Бойса" in t and kind == "Word"
    _make_pptx(os.path.join(d, "b.pptx"), ["Слайд про ACID", "Транзакции"])
    t, kind = extract_material(os.path.join(d, "b.pptx"), None)
    assert "[Слайд 2]" in t and "2 слайда" in kind
    open(os.path.join(d, "c.txt"), "wb").write("Привет, мир".encode("cp1251"))
    assert extract_material(os.path.join(d, "c.txt"), None)[0] == "Привет, мир"
    open(os.path.join(d, "u.txt"), "wb").write("Юникод".encode("utf-16"))
    assert extract_material(os.path.join(d, "u.txt"), None)[0] == "Юникод"
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure
    with PdfPages(os.path.join(d, "p.pdf")) as pdf:
        fig = Figure()
        fig.text(0.1, 0.5, "Lecture about transactions and isolation levels " * 3, fontsize=8)
        pdf.savefig(fig)
    t, kind = extract_material(os.path.join(d, "p.pdf"), None)
    assert "transactions" in t and kind.startswith("PDF"), (t[:80], kind)
    try:
        extract_material(os.path.join(d, "x.doc"), None)
        raise AssertionError("старый .doc должен давать понятную ошибку")
    except ValueError as e:
        assert ".docx" in str(e)


@test
def test_materials_store_and_terms():
    from app.materials import Materials, material_terms
    m = Materials()
    m.clear()
    m.add("Конспект", "## Ключевые слова\nACID, нормализация, Бойс-Кодд\n## Термины\nтекст " * 2, "текст")
    m.add("Второй", "x" * 3000, "текст")
    assert len(Materials().items) == 2                    # переживает «перезапуск»
    terms = material_terms(m.full_text()[0])
    assert "ACID" in terms and "нормализация" in terms, terms
    S.update(materials_max_chars=1000)
    text, cut = m.full_text()
    assert cut and len(text) < 1200
    S.reset("materials_max_chars")
    mid = m.items[0]["id"]
    assert "ACID" in m.text(mid) and m.remove(mid) and len(Materials().items) == 1
    m.clear()
    assert Materials().items == []


# ---------------------------------------------------------------- звук

@test
def test_audio_processing():
    from app.audio import prepare_audio, to_16k, Segmenter, SystemAudio
    sr = 48000
    t = np.arange(sr * 2) / sr
    a = (0.05 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    out = prepare_audio(a, sr)
    assert abs(len(out) - 32000) <= 2 and 0.8 < float(np.max(np.abs(out))) <= 0.91
    assert len(to_16k(a, 44100)) == int(len(a) * 16000 / 44100)
    got = []
    seg = Segmenter(16000, 3.0, 0.01, 0.5, 40, on_start=lambda: got.append("start"), on_utterance=got.append)
    silence = np.zeros(480, np.float32)
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(480) / 16000)).astype(np.float32)
    for b in [silence] * 20 + [tone] * 40 + [silence] * 30:
        seg.feed(b)
    assert got[0] == "start" and isinstance(got[1], np.ndarray) and len(got[1]) > 16000

    sa = SystemAudio(queue.Queue())
    now = time.time()
    from collections import deque
    quiet = deque((now - 3 + i * 0.05, np.full(2400, 0.001, np.float32)) for i in range(60))
    loud = deque((now - 3 + i * 0.05, np.full(2400, 0.2, np.float32)) for i in range(60))
    sa.devices = [{"name": "Тихое", "rate": 48000, "chunks": quiet}, {"name": "Громкое", "rate": 48000, "chunks": loud}]
    audio, rate, name = sa.segment(now - 2, now - 1)
    assert name == "Громкое" and rate == 48000 and abs(len(audio) / rate - 1.0) < 0.1
    assert sa.segment(now + 10, now + 11) == (None, 0, "")
    assert [n for n, _ in sa.device_levels(5)] == ["Тихое", "Громкое"]


# ---------------------------------------------------------------- Claude, установка, конфликты

@test
def test_claude_env_and_errors():
    from app.claude import clean_env, explain_error
    os.environ.update({"ANTHROPIC_API_KEY": "x", "ANTHROPIC_BASE_URL": "https://openrouter.ai", "CLAUDECODE": "1",
                       "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CODE_GIT_BASH_PATH": "C:\\git\\bash.exe"})
    env = clean_env()
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
        assert k not in env, k
    assert env["CLAUDE_CODE_GIT_BASH_PATH"] == "C:\\git\\bash.exe"
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
              "CLAUDE_CODE_GIT_BASH_PATH"):
        os.environ.pop(k, None)
    assert "чужой сервер" in explain_error('API Error: 401 {"message":"User not found."}')
    assert "не вошёл" in explain_error("Not logged in · Please run /login")
    assert "лимит" in explain_error("Claude AI usage limit reached|1793970000")
    assert "интернет" in explain_error("getaddrinfo ENOTFOUND api.anthropic.com")
    assert explain_error("что-то непонятное") == ""


@test
def test_conflicts_and_npm():
    from app import setup_tools as st
    cfg = os.path.join(TMP, "claude_cfg")
    os.makedirs(cfg, exist_ok=True)
    p = os.path.join(cfg, "settings.json")
    json.dump({"env": {"ANTHROPIC_BASE_URL": "https://openrouter.ai/api", "ANTHROPIC_AUTH_TOKEN": "sk-SECRET",
                       "OTHER": "1"}, "apiKeyHelper": "x.cmd", "model": "opus"}, open(p, "w"))
    items = st.find_conflicts(p, registry=False)
    assert {i["name"] for i in items} == {"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "apiKeyHelper"}
    assert not any("SECRET" in i["text"] for i in items)             # ключ не показывается
    log = []
    st.fix_conflicts(items, log.append)
    assert json.load(open(p)) == {"env": {"OTHER": "1"}, "model": "opus"}
    assert any(f.startswith("settings.json.bak-") for f in os.listdir(cfg))
    assert not any("SECRET" in line for line in log)
    assert st.find_conflicts(p, registry=False) == []
    old = os.environ.get("APPDATA")
    fake = os.path.join(TMP, "appdata")
    os.makedirs(os.path.join(fake, "npm"), exist_ok=True)
    open(os.path.join(fake, "npm", "claude.cmd"), "w").write("x")
    os.environ["APPDATA"] = fake
    try:
        assert [os.path.basename(x) for x in st.npm_claude_files()] == ["claude.cmd"]
        real_which = shutil.which
        st.shutil.which = lambda *a, **k: None
        try:
            assert st.remove_npm_claude(lambda s: None) and st.npm_claude_files() == []
        finally:
            st.shutil.which = real_which
    finally:
        os.environ["APPDATA"] = old


@test
def test_installer_progress_parsing():
    """Разбор вывода установщика: полоски winget с «МБ / МБ», проценты, строки текста, «молчание» установщика."""
    from app.setup_tools import _stream
    code = ("import sys, time\n"
            "print('Found Claude Code [Anthropic.ClaudeCode]', flush=True)\n"
            "for d in (10, 25, 50): sys.stdout.write(f'  ██▒▒  {d}.0 MB / 50.0 MB\\r'); sys.stdout.flush(); time.sleep(0.05)\n"
            "print('', flush=True); print('  45%', flush=True); time.sleep(3.2); print('Successfully installed', flush=True)\n")
    lines, prog, beats = [], [], []
    rc = _stream([sys.executable, "-c", code], lines.append, lambda f, t: prog.append(round(f, 2)),
                 heartbeat=beats.append)
    assert rc == 0
    assert lines == ["Found Claude Code [Anthropic.ClaudeCode]", "Successfully installed"], lines
    assert prog[:3] == [0.2, 0.5, 1.0] and 0.45 in prog, prog
    assert beats, "во время молчания установщика должен идти отсчёт «идёт установка… N с»"


class FakeOpenAI:
    """Поддельный сервис в формате OpenAI: потоковый ответ, список моделей, ошибки — как у настоящих."""

    def __init__(self):
        import http.server
        fake = self
        self.bodies, self.auth = [], []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.auth.append(self.headers.get("Authorization"))
                self._json(200, {"data": [{"id": "m1"}, {"id": "models/m2"}]})

            def do_POST(self):
                fake.auth.append(self.headers.get("Authorization"))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.bodies.append(body)
                if self.headers.get("Authorization") != "Bearer good-key":
                    return self._json(401, {"error": {"message": "Incorrect API key provided"}})
                if body["model"] == "bad":
                    return self._json(404, {"error": {"message": "The model `bad` does not exist"}})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in ("**Скажи:** ", "Процесс — ", "программа."):
                    ev = {"choices": [{"delta": {"content": piece}}]}
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b": keep-alive\n\ndata: [DONE]\n\n")

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"


@test
def test_providers():
    from app import providers as pv
    fake = FakeOpenAI()
    S.update(backend="provider", provider="custom", provider_base_url=fake.url, provider_model="m1",
             provider_vision="yes")
    assert pv.current()["model"] == "m1"
    pv.save_key("custom", "good-key")
    cfg = pv.current()
    assert cfg["key"] == "good-key" and pv.problem(cfg) == ""
    assert "good-key" not in open(os.path.join(WORKDIR, "settings.json"), encoding="utf-8").read()
    assert pv.list_models(cfg) == ["m1", "m2"]
    ok, msg = pv.check(cfg)
    assert ok and msg.startswith("**Скажи:**"), msg
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
    msgs = [{"role": "user", "content": [img, {"type": "text", "text": "вопрос"}]}]
    q, cancel = queue.Queue(), threading.Event()
    pv.provider_ask(q, cfg, 7, "m1", "инструкция", msgs, cancel)
    got = []
    while not q.empty():
        got.append(q.get())
    assert got[-1] == ("done", 7) and "".join(m[2] for m in got if m[0] == "delta") == "**Скажи:** Процесс — программа."
    sent = fake.bodies[-1]
    assert sent["stream"] and sent["messages"][0] == {"role": "system", "content": "инструкция"}
    assert sent["messages"][1]["content"][0]["image_url"]["url"] == "data:image/png;base64,QUJD"
    S.update(provider_vision="no")                                    # модель без «зрения» — картинку не шлём
    pv.provider_ask(q, pv.current(), 8, "m1", "", msgs, cancel)
    assert isinstance(fake.bodies[-1]["messages"][0]["content"], str) and "не передан" in fake.bodies[-1]["messages"][0]["content"]
    pv.provider_ask(q, pv.current(), 9, "bad", "", msgs, cancel)       # ошибки — понятным текстом
    err = [m for m in list(q.queue) if m[0] == "error"][-1][2]
    assert "404" in err and "Загрузить список" in pv.explain(err)
    pv.save_key("custom", "wrong")
    ok, msg = pv.check(pv.current())
    assert not ok and "Ключ не подходит" in pv.explain(msg)
    pv.save_key("custom", "")
    for k in ("backend", "provider", "provider_base_url", "provider_model", "provider_vision"):
        S.reset(k)
    fake.srv.shutdown()


@test
def test_prompts():
    from app import prompts
    base = prompts.listen_prompt()
    S.update(listen_style="detailed")
    assert prompts.listen_prompt() != base and "до 60 слов" in prompts.listen_prompt()
    S.update(listen_style="short", prompt_listen="Свои правила")
    assert prompts.listen_prompt() == "Свои правила"
    S.update(prompt_listen="", student_style=False)
    assert "Дано" not in prompts.system_prompt()
    S.update(student_style=True)
    assert "Дано" in prompts.system_prompt() and prompts.listen_prompt() == base


@test
def test_models_catalog():
    from app import stt
    hw_gpu = {"gpu": "RTX", "vram_mb": 8192, "cores": 12, "ram_gb": 32}
    hw_small = {"gpu": "MX", "vram_mb": 4096, "cores": 8, "ram_gb": 16}
    hw_cpu = {"gpu": "", "vram_mb": 0, "cores": 4, "ram_gb": 8}
    assert stt.recommend(hw_gpu)["listen"] == "large-v3"
    assert stt.recommend(hw_small)["listen"] == "large-v3-turbo"
    assert stt.recommend(hw_cpu)["listen"] == "medium"
    assert stt.fmt_size(3 * 2 ** 30) == "3,0 ГБ" and stt.fmt_size(500 * 2 ** 20) == "500 МБ"
    assert stt.listen_model_name("cuda") == "large-v3" and stt.listen_model_name("cpu") == "large-v3-turbo"
    S.update(listen_whisper_model="medium")
    assert stt.listen_model_name("cuda") == "medium"
    S.reset("listen_whisper_model")
    assert set(stt.MODEL_NAMES) >= {"tiny", "base", "small", "medium", "large-v3-turbo", "large-v3",
                                    "distil-large-v3"}
    try:
        stt.delete_model("small", in_use={"small"})
        raise AssertionError("работающую модель удалять нельзя")
    except RuntimeError:
        pass


# ---------------------------------------------------------------- окна (--ui)

class FakeSession:
    sent = []

    def __init__(self, ui_q, cli, prompt_file, model, effort, max_turns):
        self.ui_q = ui_q

    def alive(self):
        return True

    def start(self):
        return True

    def send(self, rid, content):
        FakeSession.sent.append(content)
        self.ui_q.put(("delta", rid, "**Скажи:** Процесс — отдельная программа, поток — её часть."))
        self.ui_q.put(("done", rid))

    def stop(self):
        pass

    def restart(self):
        pass


def fake_cli_ask(ui_q, cli, rid, content, session_id, gen, cancel, set_proc):
    fake_cli_ask.calls.append((content, session_id))
    ui_q.put(("session", gen, "sess-1"))
    for part in ("**Ответ:** 42\n", "```python\nprint(1)\n```\n", "$$\\frac{1}{2}$$\n"):
        time.sleep(0.02)
        ui_q.put(("delta", rid, part))
    ui_q.put(("done", rid))


fake_cli_ask.calls = []


class Dummy(threading.Thread):
    def __init__(self, *a, **k):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.level = 0.0
        self.device_name = "тест"
        self.model_name = "large-v3-turbo"
        self.where = "процессор"
        self.switching = None
        self.hotwords = None
        self.tap = None

    def run(self):
        pass

    def stop(self):
        pass

    def request_model(self, name):
        self.model_name = name


class DummyTranscriber(Dummy):
    def __init__(self, audio_q, ui_q, models, paused):
        super().__init__()
        self.ui_q, self.models = ui_q, models

    def run(self):
        self.models.mic_name = "small"
        self.models.mic_ready.set()
        self.ui_q.put(("ready",))


class DummyAudio:
    def __init__(self, ui_q):
        self.state, self.error, self.devices, self.default_name, self.all_names = "ok", "", [], "", ["Наушники"]
        self.seg = None

    def start(self):
        pass

    def close(self):
        pass

    def refresh_if_stale(self):
        pass

    def level(self, seconds=0.3):
        return 0.1

    def device_levels(self, seconds=0.3):
        return [("Наушники", 0.1)]

    def segment(self, t0, t1):
        return (0.1 * np.sin(np.arange(48000 * 4) / 10)).astype(np.float32), 48000, "Наушники"


class DummyHK:
    def __init__(self, on_event, esc_active=None):
        self.capture = None
        self.mode = "тест"

    def start(self, actions):
        return True

    def set_binds(self, actions):
        self.actions = actions

    def capture_next(self, cb):
        cb("<ctrl>+<f6>")


def pump(app, secs=0.5):
    t_end = time.time() + secs
    while time.time() < t_end:
        app.root.update()
        time.sleep(0.01)


def _quiet_tk():
    """Окна тестов не забирают фокус клавиатуры у программ пользователя."""
    import tkinter as tk
    tk.Misc.focus_force = lambda self: None
    tk.Misc.focus_set = lambda self: None
    orig = tk.Wm.wm_deiconify

    def deiconify(self):          # любое окно тестов показывается полностью прозрачным
        try:
            self.wm_attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        return orig(self)
    tk.Wm.wm_deiconify = tk.Wm.deiconify = deiconify


def make_app():
    from app import ui_main, stt
    _quiet_tk()
    ui_main.Listener = Dummy
    ui_main.SystemAudio = DummyAudio
    ui_main.HotkeyManager = DummyHK
    ui_main.cli_ask = fake_cli_ask
    ui_main.ClaudeSession = FakeSession
    ui_main.find_claude = lambda: sys.executable          # «Claude Code найден»
    stt.Transcriber = DummyTranscriber
    stt.ListenTranscriber = lambda ui_q, models: Dummy()
    S.update(alpha=0.0)                                   # окно прозрачное — пользователю на экране не мешает
    app = ui_main.App()
    pump(app, 1.0)
    return app


@test
def test_ui_main_window():
    if not UI:
        return "пропущен (нужен --ui)"
    from app import winsys
    app = make_app()
    try:
        assert app.ready
        assert app.text.get("1.0", "end").strip() == "", "при запуске окно должно быть пустым"
        assert app.foot.winfo_ismapped(), "нижняя строка должна быть видна"
        app.toggle_info()
        assert app.info_win is not None
        app.toggle_info()
        assert app.info_win is None
        if winsys.IS_WIN:
            h = winsys.tk_hwnd(app.root)
            assert winsys.get_affinity(h) == winsys.WDA_EXCLUDEFROMCAPTURE, "окно должно быть невидимо для захвата"
            assert winsys.is_tool_window(h), "у окна не должно быть кнопки на панели задач"
            assert app.guard.fully_hidden()
        # «Клод, …» → скриншот + ответ, продолжение диалога через session_id
        app.on_heard("Клод, реши задачу")
        pump(app, 1.0)
        content, sid = fake_cli_ask.calls[-1]
        assert any(b["type"] == "image" for b in content) and sid is None
        txt = app.text.get("1.0", "end")
        assert "реши задачу" in txt and "42" in txt and "Копировать" in txt and "Копировать ответ" in txt
        assert app.session_id == "sess-1" and app.followup_until > time.time()
        app.on_heard("и ещё без циклов")                   # дополнение без «Клод» в течение 15 с
        pump(app, 1.0)
        assert fake_cli_ask.calls[-1][1] == "sess-1"
        # голосовые команды
        app.command("скопируй код")
        assert app.root.clipboard_get() == "print(1)"
        app.command("скрой")
        assert not app.visible
        app.command("покажи")
        assert app.visible
        app.command("вниз")
        assert app.follow is False
        app.command("новая задача")
        assert app.session_id is None and "контекст очищен" in app.text.get("1.0", "end")
        app.command("без экрана, что такое интеграл")
        pump(app, 0.8)
        assert not any(b["type"] == "image" for b in fake_cli_ask.calls[-1][0])
        # F7: запись → отмена; запись → конец → распознавание → «Скажи:»
        app.listen_start()
        assert app.rec is not None and app.listen_pause.is_set()
        app.listen_cancel()
        assert app.rec is None and not app.listen_pause.is_set()
        app.listen_start()
        app.listen_finish()
        pump(app, S.listen_post_seconds + 0.5)
        job_id, audio = app.listen_tr.q.get_nowait()
        assert len(audio) > 16000 and app.last_f7_audio is not None
        app.ui_q.put(("listen_text", job_id, "чем процесс отличается от потока", "ru", 1.0, None))
        pump(app, 0.8)
        assert "Скажи:" in app.text.get("1.0", "end") and FakeSession.sent
        # окно не листается само: вопрос — в верху окна
        top = app.text.index("@0,0")
        assert app.text.compare(top, "<=", "q_start + 1 lines"), (top, app.text.index("q_start"))
        # материалы
        app.attach_text("## Ключевые слова\nACID, транзакция", "Конспект")
        pump(app, 0.8)
        assert app.materials.items and app.mat_bar.winfo_ismapped()
        app.clear_materials()
        assert not app.materials.items
        # компактный режим: полоска; при ответе — разворачивается
        S.update(compact=True)
        pump(app, 0.3)
        assert app.root.winfo_height() < 60
        app.on_heard("Клод, привет")
        pump(app, 0.8)
        assert app.root.winfo_height() > 150
        S.update(compact=False)
        pump(app, 0.3)
        # вопрос текстом: поле внизу, Enter — отправить; история сохраняется
        from app import history
        n_calls = len(fake_cli_ask.calls)
        app.focus_entry()
        app.entry.delete(0, "end")
        app.entry.insert(0, "сколько будет 2+2")
        app.submit_text()
        pump(app, 1.0)
        assert len(fake_cli_ask.calls) == n_calls + 1 and fake_cli_ask.calls[-1][0][-1]["text"] == "сколько будет 2+2"
        assert "⌨ сколько будет 2+2" in app.text.get("1.0", "end")
        recs = history.load()
        assert recs and recs[0]["q"] == "сколько будет 2+2" and recs[0]["kind"] == "text" and "42" in recs[0]["a"]
        assert history.load("2+2") and not history.load("такого точно нет")
        # кусок экрана: рамка мышкой → прикладывается к следующему вопросу вместо всего экрана
        from app.region import RegionPicker
        got = []
        picker = RegionPicker(app, got.append)
        pump(app, 0.3)
        c = picker.c
        c.event_generate("<ButtonPress-1>", x=100, y=120)
        c.event_generate("<B1-Motion>", x=300, y=260)
        c.event_generate("<ButtonRelease-1>", x=300, y=260)
        pump(app, 0.2)
        assert got and got[0].size == (200, 140), got
        app.set_pending_shot(got[0])
        app.on_heard("Клод, что тут")
        pump(app, 1.0)
        imgs = [b for b in fake_cli_ask.calls[-1][0] if b["type"] == "image"]
        import base64, io
        from PIL import Image
        assert imgs and Image.open(io.BytesIO(base64.b64decode(imgs[0]["source"]["data"]))).size == (200, 140)
        assert getattr(app, "pending_shot", None) is None
        # окно истории
        app.open_history()
        pump(app, 0.4)
        assert app.history_win is not None
        app.history_win.destroy()
        # тема меняется сразу, без перезапуска
        from app.ui_theme import THEMES
        for th in ("light", "midnight", "dark"):
            S.update(theme=th)
            pump(app, 0.3)
            assert app._head.cget("bg") == THEMES[th]["BG2"] and app.text.cget("bg") == THEMES[th]["BG"], th
            assert app.text.tag_cget("user", "background") == THEMES[th]["Q_BG"]
        # ответ через другого провайдера (поддельный сервис в формате OpenAI)
        from app import providers as pv
        fake = FakeOpenAI()
        pv.save_key("custom", "good-key")
        S.update(backend="provider", provider="custom", provider_base_url=fake.url, provider_model="m1")
        pump(app, 0.3)
        assert app.provider and not app.cli
        app.on_heard("Клод, что такое поток")
        pump(app, 1.5)
        assert "Процесс — программа." in app.text.get("1.0", "end"), app.text.get("end-6l", "end")
        assert any(p.get("type") == "image_url" for p in fake.bodies[-1]["messages"][-1]["content"])
        for k in ("backend", "provider", "provider_base_url", "provider_model"):
            S.reset(k)
        pv.save_key("custom", "")
        fake.srv.shutdown()
        pump(app, 0.3)
        # настройки на ходу
        S.update(font_size=13)
        S.update(hotkey_listen="<f6>")
        pump(app, 0.3)
        assert app.hk.actions["listen"] == "<f6>"
        S.reset("font_size", "hotkey_listen")
        pump(app, 0.2)
    finally:
        app.root.destroy()


@test
def test_ui_settings_and_dialogs():
    if not UI:
        return "пропущен (нужен --ui)"
    from app.ui_settings import SettingsWindow, TABS
    from app import ui_dialogs
    app = make_app()
    try:
        win = SettingsWindow(app)
        for key, _, _ in TABS:
            win.show(key)
            pump(app, 0.3)
        assert len(win.pages) == len(TABS)
        win.show("keys")
        win._capture_key("talk", "hotkey_talk")              # «нажатие» Ctrl+F6 из заглушки
        pump(app, 0.3)
        assert S.hotkey_talk == "<ctrl>+<f6>"
        win._set_key("hotkey_talk", "q")                     # буква без Ctrl — отказ
        assert S.hotkey_talk == "<ctrl>+<f6>"
        S.reset("hotkey_talk")
        win.close()
        ui_dialogs.show_help(app)
        pump(app, 0.3)
        assert app.help_win is not None
        app.help_win.destroy()
        shot, rect, ok, msg = app.capture_check()
        assert shot.width > 100 and isinstance(ok, bool) and msg
    finally:
        app.root.destroy()


@test
def test_ui_wizard():
    if not UI:
        return "пропущен (нужен --ui)"
    from app import ui_wizard, audio
    audio.Listener = Dummy
    audio.SystemAudio = DummyAudio
    import app.hotkeys as hk
    hk.HotkeyManager = DummyHK
    ui_wizard.HotkeyManager = DummyHK
    _quiet_tk()
    ui_wizard.Wizard._close_running_overlay = lambda self: None   # не закрывать настоящий оверлей
    S.update(alpha=0.0)
    w = ui_wizard.Wizard()
    try:
        w.root.attributes("-alpha", 0.0)
        for key in [k for k, _ in ui_wizard.STEPS] + ["finish"]:
            w.show(key)
            for _ in range(20):
                w.root.update()
                time.sleep(0.02)
        assert w.marks["keys"] == "done"
    finally:
        for fn in w.cleanups:
            fn()
        w.root.destroy()


# ---------------------------------------------------------------- настоящее распознавание (--whisper)

@test
def test_whisper_wake_phrases():
    if not WHISPER:
        return "пропущен (нужен --whisper)"
    import subprocess
    import wave
    from app import stt
    from app.audio import to_16k
    from app.textfmt import split_wake
    if not stt.model_cached("small"):
        return "пропущен (модель small не скачана)"
    phrases = ["Клод, реши задачу на экране.", "Клод, стоп.", "Клод, новая задача.", "Клод, скопируй код."]
    ok = 0
    tr = REAL_TRANSCRIBER(queue.Queue(), queue.Queue(), stt.Models(), threading.Event())
    tr.models.mic, tr.where = stt.load_whisper("small", "cpu")
    tr.models.mic_name = "small"
    for i, ph in enumerate(phrases):
        path = os.path.join(TMP, f"w{i}.wav")
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{ph}'); $s.Dispose()")
        if subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True).returncode != 0:
            return "пропущен (нет синтеза речи Windows)"
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            a = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
        text = tr.transcribe(to_16k(a, sr))
        ok += split_wake(text) is not None
    assert ok >= 3, f"«Клод» узнан только в {ok} из {len(phrases)}"
    return f"«Клод» узнан в {ok} из {len(phrases)}"


def main():
    failed = 0
    for fn in RESULTS:
        t0 = time.time()
        try:
            note = fn()
            print(f"  ✓ {fn.__name__} ({time.time() - t0:.1f} с)" + (f" — {note}" if note else ""))
        except Exception:
            failed += 1
            print(f"  ✕ {fn.__name__}\n" + "".join("      " + line for line in traceback.format_exc().splitlines(True)))
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\nИтого: {len(RESULTS) - failed} из {len(RESULTS)} прошли" + (f", {failed} с ошибками" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
