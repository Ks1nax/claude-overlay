# -*- coding: utf-8 -*-
"""Claude: через Claude Code по подписке Pro/Max (по умолчанию) или через API-ключ.

Claude Code вызывается так (см. CLAUDE.md):
  claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages
         --system-prompt-file <файл> --tools "" --strict-mcp-config --no-session-persistence --model … --effort …
--effort передаём всегда явно: у пользователя в настройках Claude Code может стоять xhigh — ответы очень медленные."""

import glob
import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque

from .config import S, WORKDIR, MATERIALS_DIR
from .winsys import IS_WIN, NO_WINDOW

_KEEP_CLAUDE_VARS = {"CLAUDE_CODE_GIT_BASH_PATH", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
                     "CLAUDE_CODE_OAUTH_TOKEN"}  # вход по токену подписки (claude setup-token) — оставляем


def clean_env():
    """Окружение для Claude Code: без ключей и чужого адреса сервера (иначе он идёт не в подписку) и без переменных
    родительской сессии Claude Code (если оверлей запущен из неё — например, из приложения Claude)."""
    env = dict(os.environ)
    for k in list(env):
        up = k.upper()
        if up in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_PID") \
                or (up.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_", "CLAUDE_PREVIEW_"))
                    and up not in _KEEP_CLAUDE_VARS) \
                or up in ("MCP_CONNECTION_NONBLOCKING", "MCP_SERVER_CONNECTION_BATCH_SIZE"):
            env.pop(k, None)
    return env


def claude_candidates():
    """Где может лежать Claude Code (сначала настоящие .exe, потом что найдётся в PATH)."""
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    out = []
    if S.claude_cmd and os.path.isfile(S.claude_cmd):
        out.append(S.claude_cmd)
    if IS_WIN:
        out += [os.path.join(home, ".local", "bin", "claude.exe"),
                os.path.join(local, "Microsoft", "WinGet", "Links", "claude.exe")]
        out += sorted(glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "Anthropic.ClaudeCode*",
                                             "claude.exe")))
    else:
        out += [os.path.join(home, ".local", "bin", "claude"), "/usr/local/bin/claude"]
    w = shutil.which("claude")
    if w:
        out.append(w)
    seen, res = set(), []
    for p in out:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and os.path.isfile(p):
            seen.add(key)
            res.append(p)
    # сломанная копия из npm (claude.cmd / claude.ps1) — в самый конец
    res.sort(key=lambda p: 1 if os.path.normcase(p).endswith((".cmd", ".ps1", ".bat")) or
             os.path.normcase(os.path.join("npm", "")) in os.path.normcase(p) else 0)
    return res


def find_claude():
    c = claude_candidates()
    return c[0] if c else None


def claude_version(cli, timeout=30):
    try:
        r = subprocess.run([cli, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=clean_env(), **NO_WINDOW)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ""
    except Exception as e:
        return f"ошибка: {e}"


def explain_error(text):
    """Ошибка Claude Code/API → понятное объяснение и что делать."""
    t = (text or "").strip()
    low = t.lower()
    if "user not found" in low:
        return ("Claude Code ходит не в твою подписку, а на чужой сервер (в настройках прописан чужой адрес или ключ). "
                "Открой мастер (⚙ → «Невидимость и система» → «Проверить и починить»), шаг «Конфликты настроек».")
    if "/login" in low or "not logged in" in low or "please run" in low and "login" in low:
        return ("Claude Code не вошёл в аккаунт. Открой мастер (⚙ → «Невидимость и система» → «Проверить и починить»), "
                "шаг 1 → «Открыть окно входа» — там подсказка, что ввести.")
    if "401" in low or "invalid api key" in low or "authentication" in low or "oauth token" in low:
        return ("Claude Code не может войти (ошибка 401). Войди заново: мастер, шаг 1 → «Открыть окно входа». "
                "Если не помогает — шаг «Конфликты настроек».")
    if "usage limit" in low or "limit reached" in low or "rate limit" in low or "429" in low:
        return "Закончился лимит подписки на ближайшие часы. Подожди, пока он обновится (время — в сообщении выше)."
    if "credit balance" in low:
        return "На счёте API закончились деньги. Пополни баланс или переключись на подписку: ⚙ → Claude."
    if "overloaded" in low or "529" in low:
        return "Серверы Claude перегружены. Попробуй ещё раз через минуту."
    if any(w in low for w in ("enotfound", "econnrefused", "etimedout", "connection error", "fetch failed",
                              "network", "getaddrinfo")):
        return "Нет связи с Claude. Проверь интернет (и VPN, если он нужен)."
    if "не найден claude code" in low or "no such file" in low or "winerror 2" in low:
        return "Не найден Claude Code. Запусти «Установить.bat» или мастер — он поставит Claude Code."
    return ""


def check_login(cli, timeout=120):
    """Пробный запрос (мастер): → (успех, ответ или текст ошибки)."""
    cmd = [cli, "-p", "ответь одним словом: ок", "--output-format", "json", "--model", "haiku",
           "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=clean_env(), cwd=WORKDIR if os.path.isdir(WORKDIR) else None, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, "Claude Code не ответил за 2 минуты (нет интернета или он ждёт входа)."
    except Exception as e:
        return False, f"не удалось запустить Claude Code: {e}"
    data = {}
    for line in reversed((r.stdout or "").strip().splitlines()):
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
    if data and not data.get("is_error") and (data.get("result") or "").strip():
        return True, data["result"].strip()
    msg = (data.get("result") or "").strip() or (r.stderr or r.stdout or "").strip()[-500:] \
        or f"Claude Code завершился с кодом {r.returncode}"
    return False, msg


class ClaudeSession:
    """Постоянно запущенный Claude Code: без затрат на запуск, первые слова ответа через ~1 секунду."""

    def __init__(self, ui_q, cli, prompt_file, model, effort, max_turns):
        self.ui_q, self.cli = ui_q, cli
        self.prompt_file, self.model, self.effort, self.max_turns = prompt_file, model, effort, max_turns
        self.proc = None
        self.rid = None
        self.turns = 0
        self.streamed = False

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        cmd = [self.cli, "-p", "--input-format", "stream-json",
               "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--system-prompt-file", self.prompt_file,
               "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        try:
            proc = subprocess.Popen(cmd, cwd=WORKDIR, env=clean_env(), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, **NO_WINDOW)
        except Exception as e:
            print("[claude] не удалось запустить Claude Code:", e)
            return False
        self.proc, self.turns = proc, 0
        err = deque(maxlen=20)
        threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True).start()
        threading.Thread(target=self._reader, args=(proc, err), daemon=True).start()
        return True

    def send(self, rid, content):
        if not self.alive() and not self.start():
            self.ui_q.put(("error", rid, "Claude Code не запустился"))
            return
        self.rid, self.streamed = rid, False
        self.turns += 1
        try:
            msg = {"type": "user", "message": {"role": "user", "content": content}}
            self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            self.rid = None
            self.ui_q.put(("error", rid, f"Claude Code не принял сообщение: {e}"))
            self.restart()

    def _reader(self, proc, err):
        q = self.ui_q
        for line in proc.stdout:
            if proc is not self.proc:
                return
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            t, rid = ev.get("type"), self.rid
            if rid is None:
                continue
            if t == "stream_event":
                d = ((ev.get("event") or {}).get("delta") or {})
                if d.get("type") == "text_delta" and d.get("text"):
                    self.streamed = True
                    q.put(("delta", rid, d["text"]))
            elif t == "assistant" and not self.streamed:
                for blk in (ev.get("message") or {}).get("content") or []:
                    if blk.get("type") == "text" and blk.get("text"):
                        q.put(("delta", rid, blk["text"]))
                        self.streamed = True
            elif t == "result":
                self.rid = None
                if ev.get("is_error"):
                    q.put(("error", rid, ev.get("result") or ev.get("subtype") or "ошибка"))
                else:
                    q.put(("done", rid))
                if self.turns >= self.max_turns:
                    threading.Thread(target=self.restart, daemon=True).start()
        if proc is self.proc and self.rid is not None:
            tail = "".join(err).strip()[-600:]
            q.put(("error", self.rid, "Claude Code закрылся. " + tail))
            self.rid = None

    def restart(self):
        self.stop()
        self.start()

    def stop(self):
        proc, self.proc, rid, self.rid = self.proc, None, self.rid, None
        if rid is not None:  # ответ шёл — окно не должно вечно «думать»
            self.ui_q.put(("interrupted", rid))
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass


def cli_ask(ui_q, cli, rid, content, session_id, gen, cancel, set_proc):
    """Разовый запрос через Claude Code (claude -p с --resume) — обычный режим «Клод, …»."""
    cmd = [cli, "-p",
           "--input-format", "stream-json",
           "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--system-prompt-file", os.path.join(WORKDIR, "system_prompt.txt"),
           "--tools", "Read", "--allowedTools", "Read",
           "--strict-mcp-config"]
    if S.cli_model:
        cmd += ["--model", S.cli_model]
    if S.cli_effort:
        cmd += ["--effort", S.cli_effort]
    if session_id:
        cmd += ["--resume", session_id]
    try:
        proc = subprocess.Popen(cmd, cwd=WORKDIR, env=clean_env(), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, **NO_WINDOW)
    except Exception as e:
        ui_q.put(("error", rid, f"не удалось запустить Claude Code: {e}"))
        return
    set_proc(proc)
    err_lines = []
    threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True).start()

    try:
        msg = {"type": "user", "message": {"role": "user", "content": content}}
        proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        proc.stdin.close()
    except Exception as e:
        ui_q.put(("error", rid, f"Claude Code не принял сообщение: {e}"))
        return

    streamed = got_text = False
    error = None
    for line in proc.stdout:
        if cancel.is_set():
            break
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("session_id") and ev["session_id"] != session_id:
            session_id = ev["session_id"]
            ui_q.put(("session", gen, session_id))
        t = ev.get("type")
        if t == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "message_start" and got_text:
                ui_q.put(("delta", rid, "\n\n"))
            elif e.get("type") == "content_block_delta":
                d = e.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    streamed = got_text = True
                    ui_q.put(("delta", rid, d["text"]))
        elif t == "assistant" and not streamed:
            for blk in (ev.get("message") or {}).get("content") or []:
                if blk.get("type") == "text" and blk.get("text"):
                    ui_q.put(("delta", rid, ("\n\n" if got_text else "") + blk["text"]))
                    got_text = True
        elif t == "result":
            if ev.get("is_error"):
                error = ev.get("result") or ev.get("subtype") or "ошибка"
            elif not got_text and ev.get("result"):
                ui_q.put(("delta", rid, ev["result"]))
                got_text = True

    if cancel.is_set():
        try:
            proc.kill()
        except Exception:
            pass
        return
    proc.wait()
    if error is None and proc.returncode and not got_text:
        tail = "".join(err_lines[-15:]).strip()
        error = tail or f"Claude Code завершился с кодом {proc.returncode}"
    if error:
        ui_q.put(("error", rid, error))
    else:
        ui_q.put(("done", rid))


def api_ask(ui_q, client, rid, system, messages, cancel):
    """Запрос через API-ключ (оплата за каждый запрос)."""
    try:
        with client.messages.stream(model=S.api_model, max_tokens=S.max_tokens,
                                    system=system, messages=messages) as stream:
            for chunk in stream.text_stream:
                if cancel.is_set():
                    return
                ui_q.put(("delta", rid, chunk))
        ui_q.put(("done", rid))
    except Exception as e:
        if not cancel.is_set():
            ui_q.put(("error", rid, str(e)))


def claude_read_file(cli, path, timeout=900):
    """Картинки, сканы и прочее читает сам Claude (инструментом Read) и выписывает текст."""
    src_dir = os.path.join(MATERIALS_DIR, "src")
    os.makedirs(src_dir, exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    tmp = os.path.join(src_dir, f"file_{int(time.time() * 1000)}{ext}")
    shutil.copyfile(path, tmp)
    rel = os.path.relpath(tmp, WORKDIR).replace("\\", "/")
    prompt = (f"Прочитай файл {rel} инструментом Read (если это PDF — все страницы по порядку) и выпиши его содержимое "
              "обычным текстом: весь текст дословно и по порядку, формулы — в LaTeX, таблицы — построчно, рисунки и схемы — "
              "одной строкой описания в квадратных скобках. Ничего не добавляй от себя, без вступлений и комментариев.")
    cmd = [cli, "-p", prompt, "--output-format", "json", "--tools", "Read", "--allowedTools", "Read",
           "--strict-mcp-config", "--no-session-persistence", "--model", S.listen_model or "sonnet", "--effort", "low"]
    try:
        r = subprocess.run(cmd, cwd=WORKDIR, env=clean_env(), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, **NO_WINDOW)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    data = {}
    for line in reversed(r.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
    text = (data.get("result") or "").strip()
    if data.get("is_error") or not text:
        raise RuntimeError(text or r.stderr.strip()[-300:] or "Claude не смог прочитать файл")
    return text
