# -*- coding: utf-8 -*-
"""Распознавание речи (faster-whisper): модели, видеокарта NVIDIA, загрузка моделей с прогрессом.

Важно (см. CLAUDE.md):
- модели грузятся строго по очереди (_LOAD_LOCK), импорт faster-whisper — под _IMPORT_LOCK: одновременный импорт
  из двух потоков давал взаимную блокировку импорта в Python;
- проверка видеокарты — в ОТДЕЛЬНОМ процессе: нехватка DLL cuDNN роняет процесс без исключения Python;
- cuDNN ставится ровно той версии, что диспетчер cudnn64_9.dll внутри ctranslate2."""

import glob
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from .config import S, WORKDIR, HERE, read_text, write_text
from .textfmt import strip_tail_junk
from .winsys import IS_WIN, NO_WINDOW

GPU_OK = os.path.join(WORKDIR, "gpu_ok.txt")
GPU_FAIL = os.path.join(WORKDIR, "gpu_fail.txt")
MODELS_INFO = os.path.join(WORKDIR, "models_info.json")

# ---------------------------------------------------------------- каталог моделей

# Размеры — примерные (настоящие берутся из HuggingFace и кэшируются в workspace/models_info.json)
MODELS = [
    # имя, хранилище, ~МБ, скорость, точность, когда брать
    ("tiny", "Systran/faster-whisper-tiny", 75, "мгновенно", "слабая", "очень слабый ПК, только команды"),
    ("base", "Systran/faster-whisper-base", 145, "очень быстро", "средняя", "слабый ПК без видеокарты"),
    ("small", "Systran/faster-whisper-small", 480, "быстро", "хорошая", "команды «Клод, …» (по умолчанию)"),
    ("medium", "Systran/faster-whisper-medium", 1500, "средне", "высокая", "F7 без видеокарты, если turbo медленно"),
    ("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1600,
     "быстро на видеокарте, несколько секунд на процессоре", "почти как large-v3", "F7 без мощной видеокарты"),
    ("large-v3", "Systran/faster-whisper-large-v3", 3100, "~1 с на видеокарте, медленно на процессоре",
     "самая высокая, лучше всех с невнятной речью", "F7 с видеокартой NVIDIA (по умолчанию)"),
    ("distil-large-v3", "Systran/faster-distil-whisper-large-v3", 1500, "быстро", "высокая",
     "только английский"),
]
MODEL_NAMES = [m[0] for m in MODELS]
REPOS = {m[0]: m[1] for m in MODELS}
NEEDED_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json")

# Подсказка распознаванию команд. НЕ заканчивать её словом «Клод,»: тогда Whisper считает слово уже сказанным
# и выкидывает его из текста — проверено на 10 озвученных командах: старая подсказка «Клод,» — 0 из 10 узнано,
# эта — 9 из 10 (как и без подсказки, но написание «Клод» подсказывает).
WAKE_PROMPT = "Это команды голосовому помощнику Клоду."


def model_meta(name):
    for m in MODELS:
        if m[0] == name:
            return {"name": m[0], "repo": m[1], "approx_mb": m[2], "speed": m[3], "accuracy": m[4], "when": m[5]}
    return {"name": name, "repo": REPOS.get(name, name), "approx_mb": 0, "speed": "", "accuracy": "", "when": ""}


def hf_cache_dir():
    try:
        from huggingface_hub import constants as hfc
        return hfc.HF_HUB_CACHE
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def model_cache_path(name):
    return os.path.join(hf_cache_dir(), "models--" + REPOS.get(name, name).replace("/", "--"))


def model_cached(name):
    """Скачана ли модель целиком (без запуска faster-whisper — быстро)."""
    repo = REPOS.get(name)
    if not repo:
        return False
    snaps = os.path.join(model_cache_path(name), "snapshots")
    try:
        for snap in os.listdir(snaps):
            d = os.path.join(snaps, snap)
            if all(os.path.isfile(os.path.join(d, f)) for f in ("config.json", "model.bin", "tokenizer.json")):
                return True
    except OSError:
        pass
    return False


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path or ""):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def model_disk_size(name):
    return dir_size(model_cache_path(name)) if os.path.isdir(model_cache_path(name)) else 0


def remote_sizes(refresh=False):
    """Настоящие размеры моделей (байты) из HuggingFace; ответ кэшируется в workspace/models_info.json."""
    cached = {}
    try:
        with open(MODELS_INFO, encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        pass
    if cached and not refresh and all(n in cached for n in MODEL_NAMES):
        return cached
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        for name in MODEL_NAMES:
            if name in cached and not refresh:
                continue
            info = api.model_info(REPOS[name], files_metadata=True)
            cached[name] = sum((sb.size or 0) for sb in info.siblings
                               if sb.rfilename in NEEDED_FILES or sb.rfilename.startswith("vocabulary"))
        write_text(MODELS_INFO, json.dumps(cached))
    except Exception as e:
        print("[модели] не удалось узнать размеры из HuggingFace:", e)
    return cached


def cached_sizes():
    """Размеры из кэша без сети (можно звать из потока окна)."""
    try:
        with open(MODELS_INFO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def model_size_bytes(name, sizes=None):
    """Без сети: из переданного словаря или кэша, иначе примерный размер. Свежие размеры — remote_sizes() в потоке."""
    sizes = sizes if sizes is not None else cached_sizes()
    return sizes.get(name) or model_meta(name)["approx_mb"] * 2 ** 20


def fmt_size(b):
    if b >= 2 ** 30:
        return f"{b / 2 ** 30:.1f} ГБ".replace(".", ",")
    return f"{max(1, round(b / 2 ** 20))} МБ"


def delete_model(name, in_use=()):
    """Удаляет скачанную модель из кэша HuggingFace. Модель, которая сейчас работает, удалить нельзя."""
    if name in in_use:
        raise RuntimeError("эта модель сейчас используется — сначала выбери другую")
    path = model_cache_path(name)
    if not os.path.isdir(path):
        return
    shutil.rmtree(path)


def download_with_progress(name, report, every=1.0):
    """Скачивает модель Whisper; раз в секунду report({"done", "total", "speed", "text"}) — по размеру папки кэша
    (загрузка HuggingFace без xet пишет файл по мере скачивания, HF_HUB_DISABLE_XET=1 задаётся в overlay.py).
    Прерванная загрузка при следующем запуске продолжается с того же места."""
    repo = REPOS.get(name, name)
    total = model_size_bytes(name, remote_sizes())  # рабочий поток — сеть можно
    cache = model_cache_path(name)
    done_ev = threading.Event()
    start = dir_size(cache)

    def poll():
        last_t, last_b = time.time(), dir_size(cache)
        speed = 0.0
        while not done_ev.wait(every):
            b, now = dir_size(cache), time.time()
            inst = (b - last_b) / max(0.1, now - last_t)
            speed = inst if speed == 0 else 0.6 * speed + 0.4 * inst
            last_t, last_b = now, b
            pct = min(99, int(b * 100 / total)) if total else 0
            txt = f"{fmt_size(b)} из {fmt_size(total)} ({pct}%)" if total else fmt_size(b)
            if speed > 1024:
                txt += f", {speed / 2 ** 20:.1f} МБ/с".replace(".", ",")
                left = (total - b) / speed if total and speed > 0 else 0
                if left > 5:
                    txt += f", ещё ~{int(left // 60)} мин" if left >= 90 else f", ещё ~{int(left)} с"
            report({"done": b, "total": total, "speed": speed, "pct": pct, "text": txt})

    threading.Thread(target=poll, daemon=True, name="download-progress").start()
    try:
        from huggingface_hub import snapshot_download
        path = snapshot_download(repo, allow_patterns=list(NEEDED_FILES) + ["vocabulary*"])
        print(f"[модели] {name} скачана ({fmt_size(dir_size(cache) - start)} за этот раз)")
        return path
    finally:
        done_ev.set()
        report({"done": total, "total": total, "speed": 0, "pct": 100, "text": ""})


# ---------------------------------------------------------------- железо и рекомендации

_HW = None


def hardware_info(refresh=False):
    """Что есть в компьютере: видеокарта NVIDIA и её память, ядра процессора, память."""
    global _HW
    if _HW is not None and not refresh:
        return _HW
    hw = {"gpu": "", "vram_mb": 0, "cores": os.cpu_count() or 4, "ram_gb": 0.0, "cuda_ready": False}
    try:
        exe = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if IS_WIN else "")
        if exe and os.path.isfile(exe):
            r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10, **NO_WINDOW)
            line = (r.stdout or "").strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
            if line:
                name, mem = [x.strip() for x in line.split(",")[:2]]
                hw["gpu"], hw["vram_mb"] = name, int(float(mem))
    except Exception as e:
        print("[железо] nvidia-smi:", e)
    if IS_WIN:
        try:
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            hw["ram_gb"] = round(m.ullTotalPhys / 2 ** 30, 1)
        except Exception:
            pass
    hw["cuda_ready"] = bool(read_text(GPU_OK))
    _HW = hw
    return hw


def recommend(hw=None):
    """→ {"mic": модель для команд, "listen": модель для F7, "why": пояснение}."""
    hw = hw or hardware_info()
    gpu = hw["gpu"] and hw["vram_mb"] >= 3500
    if gpu and hw["vram_mb"] >= 6000:
        return {"mic": "small", "listen": "large-v3",
                "why": f"есть видеокарта {hw['gpu']} ({hw['vram_mb'] // 1024} ГБ) — самая точная модель работает за секунду"}
    if gpu:
        return {"mic": "small", "listen": "large-v3-turbo",
                "why": f"видеокарта {hw['gpu']} с небольшой памятью — turbo почти так же точна и легче"}
    if hw["cores"] >= 8:
        return {"mic": "small", "listen": "large-v3-turbo",
                "why": f"видеокарты NVIDIA нет, процессор {hw['cores']} потоков — turbo распознаёт за несколько секунд"}
    if hw["cores"] >= 4:
        return {"mic": "base", "listen": "medium",
                "why": "видеокарты NVIDIA нет, процессор слабый — модели полегче"}
    return {"mic": "tiny", "listen": "small", "why": "очень слабый компьютер — самые лёгкие модели"}


# ---------------------------------------------------------------- видеокарта

def pe_file_version(path):
    """Версия из ресурсов DLL (строка FileVersion) — без Windows API, просто по байтам файла."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    key = "FileVersion".encode("utf-16-le") + b"\x00\x00"
    i = data.find(key)
    if i < 0:
        return None
    i += len(key)
    while i < len(data) - 1 and data[i:i + 2] == b"\x00\x00":
        i += 2
    j = i
    while j < len(data) - 1 and data[j:j + 2] != b"\x00\x00":
        j += 2
    ver = data[i:j].decode("utf-16-le", "ignore").strip()
    return ver.replace(", ", ".").replace(",", ".") or None


def installed_version(dist):
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        return None


def site_dirs():
    import site
    dirs = []
    try:
        dirs += site.getsitepackages()
    except Exception:
        pass
    try:
        dirs.append(site.getusersitepackages())
    except Exception:
        pass
    return [d for d in dirs if d and os.path.isdir(d)]


def nvidia_dirs():
    """Папки с библиотеками CUDA из pip-пакетов nvidia-*."""
    out = []
    for sp in site_dirs():
        for sub in ("cudnn", "cublas", "cuda_nvrtc", "cuda_runtime"):
            for leaf in ("bin", "lib"):
                d = os.path.join(sp, "nvidia", sub, leaf)
                if os.path.isdir(d) and d not in out:
                    out.append(d)
    return out


def cublas_available():
    names = ("cublas64_12.dll",) if IS_WIN else ("libcublas.so.12",)
    dirs = nvidia_dirs() + [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    if os.environ.get("CUDA_PATH"):
        dirs.append(os.path.join(os.environ["CUDA_PATH"], "bin"))
    return any(os.path.isfile(os.path.join(d, n)) for d in dirs for n in names)


_GPU_LIBS_DONE = False
_DLL_DIR_HANDLES = []


def gpu_libs_setup():
    """Показывает Windows, где лежат cuBLAS/cuDNN, и заранее подгружает их по полному пути."""
    global _GPU_LIBS_DONE
    if _GPU_LIBS_DONE:
        return
    _GPU_LIBS_DONE = True
    pip_dirs = nvidia_dirs()
    cuda = os.environ.get("CUDA_PATH")
    sys_dirs = [os.path.join(cuda, "bin")] if cuda and os.path.isdir(os.path.join(cuda, "bin")) else []
    dirs = pip_dirs + [d for d in sys_dirs if d not in pip_dirs]
    if not dirs:
        return
    os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    if not IS_WIN:
        return
    import ctypes
    for d in dirs:
        try:
            _DLL_DIR_HANDLES.append(os.add_dll_directory(d))
        except Exception:
            pass
    loaded = set()
    order = ("cublasLt64_*.dll", "cublas64_*.dll", "cudnn_graph64_*.dll", "cudnn_engines_runtime_compiled64_*.dll",
             "cudnn_engines_precompiled64_*.dll", "cudnn_heuristic64_*.dll", "cudnn_ops64_*.dll",
             "cudnn_cnn64_*.dll", "cudnn_adv64_*.dll")
    for pat in order:
        for d in dirs:
            if pat.startswith("cudnn") and d in sys_dirs and d not in pip_dirs:
                continue  # cuDNN берём только той версии, что поставила программа
            for f in sorted(glob.glob(os.path.join(d, pat))):
                name = os.path.basename(f).lower()
                if name in loaded:
                    continue
                try:
                    ctypes.WinDLL(f)
                    loaded.add(name)
                except OSError as e:
                    print(f"[видеокарта] не загрузилась {name}: {e}")


_DEVICE_LOCK = threading.Lock()
_DEVICE = None
_IMPORT_LOCK = threading.RLock()
_LOAD_LOCK = threading.Lock()     # модели грузятся строго по одной


def import_whisper():
    """faster-whisper импортируем строго по одному потоку за раз (иначе _DeadlockError при импорте)."""
    import importlib
    with _IMPORT_LOCK:
        for mod in ("ctranslate2", "faster_whisper", "faster_whisper.utils"):
            importlib.import_module(mod)
        from faster_whisper import WhisperModel
        return WhisperModel


def ctranslate2_version():
    try:
        with _IMPORT_LOCK:
            import ctranslate2
        return ctranslate2.__version__
    except Exception:
        return ""


def whisper_device():
    """"cuda", если видеокарта NVIDIA прошла проверку, иначе "cpu"."""
    global _DEVICE
    with _DEVICE_LOCK:
        if _DEVICE is None:
            _DEVICE = "cpu"
            if S.whisper_device == "cuda":
                _DEVICE = "cuda"
            elif S.whisper_device == "auto":
                try:
                    with _IMPORT_LOCK:
                        import ctranslate2
                    if (ctranslate2.get_cuda_device_count() > 0
                            and read_text(GPU_OK) == ctranslate2.__version__):
                        _DEVICE = "cuda"
                except Exception:
                    pass
            if _DEVICE == "cuda":
                gpu_libs_setup()
        return _DEVICE


def load_whisper(name, device, cpu_threads=0):
    """Загружает модель Whisper; если на видеокарте не вышло — на процессоре. → (модель, где)."""
    WhisperModel = import_whisper()
    with _LOAD_LOCK:
        if device == "cuda":
            try:
                return WhisperModel(name, device="cuda", compute_type="float16"), "видеокарта"
            except Exception as e:
                print(f"[whisper] {name} на видеокарте не загрузилась ({e}) — беру процессор")
        return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=cpu_threads), "процессор"


def listen_model_name(device):
    """«Авто» = то, что помечено «рекомендуем» для этого компьютера (а без готовой видеокарты — не тяжелее turbo)."""
    if S.listen_whisper_model and S.listen_whisper_model != "auto":
        return S.listen_whisper_model
    rec = recommend()["listen"]
    if device != "cuda" and rec == "large-v3":
        return "large-v3-turbo"
    return rec


def console_python():
    """python.exe рядом с текущим (pythonw.exe не годится для pip с выводом)."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        alt = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(alt):
            return alt
    return exe


def run_pip(args, report=print):
    """pip install … без окна консоли; строки вывода — в report (мастер показывает прогресс)."""
    cmd = [console_python(), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "raw", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", bufsize=1, **NO_WINDOW)
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            report(line)
    return proc.wait()


def setup_gpu(report=print, force=False):
    """Если есть NVIDIA — докачать cuBLAS/cuDNN нужной версии и проверить в отдельном процессе.
    → "ok" / "cpu" (видеокарты нет или выбрано «процессор») / "fail" (не заработала)."""
    if S.whisper_device == "cpu":
        report("[видеокарта] В настройках выбран процессор — видеокарту не настраиваю.")
        return "cpu"
    try:
        with _IMPORT_LOCK:
            import ctranslate2
        count = ctranslate2.get_cuda_device_count()
    except Exception:
        count = 0
    if count <= 0:
        report("[видеокарта] NVIDIA не найдена — распознавание будет на процессоре.")
        return "cpu"
    ver = ctranslate2.__version__
    if force:
        for f in (GPU_OK, GPU_FAIL):
            try:
                os.remove(f)
            except OSError:
                pass
    if read_text(GPU_OK) == ver:
        report("[видеокарта] Распознавание на видеокарте NVIDIA — готово.")
        return "ok"
    if read_text(GPU_FAIL) == ver:
        report("[видеокарта] Раньше не заработала — распознавание на процессоре. Попробовать снова — "
               "кнопка «Проверить заново».")
        return "fail"
    need = pe_file_version(os.path.join(os.path.dirname(ctranslate2.__file__), "cudnn64_9.dll")) if IS_WIN else None
    have = installed_version("nvidia-cudnn-cu12")
    pkgs = []
    if need:
        if have != need:
            pkgs.append(f"nvidia-cudnn-cu12=={need}")
    elif not (have or "").startswith("9."):
        pkgs.append("nvidia-cudnn-cu12==9.*")
    if not cublas_available():
        pkgs.append("nvidia-cublas-cu12")
    if pkgs:
        report("[видеокарта] Нашёл видеокарту NVIDIA. Докачиваю библиотеки CUDA, чтобы распознавание шло на ней "
               "(0,7–1,2 ГБ, только один раз): " + " ".join(pkgs))
        if run_pip(pkgs, report) != 0:
            report("[видеокарта] Не получилось поставить библиотеки — распознавание будет на процессоре.")
            return "fail"

    def test():
        report("[видеокарта] Проверяю распознавание на видеокарте…")
        r = subprocess.run([console_python(), os.path.join(HERE, "overlay.py"), "--gpu-test"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=900, **NO_WINDOW)
        for line in (r.stdout + r.stderr).strip().splitlines()[-5:]:
            report("    " + line)
        return r.returncode == 0 and read_text(GPU_OK) == ver

    ok = test()
    if not ok and installed_version("nvidia-cublas-cu12") is None:
        report("[видеокарта] Пробую с отдельной библиотекой cuBLAS (~0,5 ГБ)…")
        if run_pip(["nvidia-cublas-cu12"], report) == 0:
            ok = test()
    if ok:
        report("[видеокарта] Готово: распознавание будет на видеокарте.")
        return "ok"
    write_text(GPU_FAIL, ver)
    report("[видеокарта] Не заработала — распознавание будет на процессоре (тоже работает, только медленнее).")
    return "fail"


def gpu_selftest():
    """Отдельный процесс: если CUDA упадёт, это не уронит сам оверлей."""
    try:
        os.remove(GPU_OK)
    except OSError:
        pass
    try:
        gpu_libs_setup()
        import ctranslate2
        from faster_whisper import WhisperModel
        name = next((n for n in ("tiny", "base", "small", "large-v3-turbo", "medium", "large-v3")
                     if model_cached(n)), "tiny")
        model = WhisperModel(name, device="cuda", compute_type="float16")
        noise = (np.random.default_rng(0).standard_normal(16000 * 2) * 0.02).astype(np.float32)
        segs, _ = model.transcribe(noise, language="ru", beam_size=1, vad_filter=False)
        list(segs)
        write_text(GPU_OK, ctranslate2.__version__)
        print(f"[видеокарта] проверка пройдена (модель {name})")
        return 0
    except Exception as e:
        print("[видеокарта] ошибка:", e)
        return 1


# ---------------------------------------------------------------- распознавание

def pick_language(model, audio, allowed, vad=None):
    """Язык — только из разрешённых. → код языка или None."""
    probs = None
    for kw in (({"vad_filter": True, "vad_parameters": vad},) if vad else ()) + ({},):
        try:
            _, _, probs = model.detect_language(audio=audio, **kw)
            break
        except Exception:
            continue
    if not probs:
        return None
    ok = [p for p in probs if p[0] in allowed] if allowed else list(probs)
    return max(ok, key=lambda p: p[1])[0] if ok else None


class Models:
    def __init__(self):
        self.mic = None
        self.mic_name = ""
        self.mic_ready = threading.Event()


class Transcriber(threading.Thread):
    """Распознаёт фразы с микрофона (команды «Клод, …»). Модель можно сменить на ходу: request_model()."""

    def __init__(self, audio_q, ui_q, models, paused):
        super().__init__(daemon=True, name="stt-mic")
        self.audio_q = audio_q
        self.ui_q = ui_q
        self.models = models
        self.paused = paused
        self.pending = None
        self.where = ""

    def request_model(self, name):
        """Сменить модель команд: качается и грузится в отдельном потоке, команды тем временем распознаёт старая."""
        self.pending = name
        if not getattr(self, "_switcher_alive", False):
            self._switcher_alive = True
            threading.Thread(target=self._switcher, daemon=True, name="stt-mic-switch").start()

    def _switcher(self):
        try:
            while self.pending:
                name, self.pending = self.pending, None
                if name != self.models.mic_name or self.models.mic is None:
                    self._switch(name)
        finally:
            self._switcher_alive = False
            if self.pending:  # выбрали ещё одну модель в последний момент
                self.request_model(self.pending)

    def _load(self, name):
        err = None
        for attempt in (1, 2):
            try:
                return load_whisper(name, whisper_device())
            except Exception as e:
                err = e
                print(f"[whisper] модель {name} не загрузилась (попытка {attempt}): {e}")
                time.sleep(1.0)
        raise err

    def run(self):
        name = S.whisper_model
        cached = model_cached(name)
        self.ui_q.put(("status", "loading", "Загружаю распознавание речи…" if cached
                       else f"Скачиваю модель распознавания {name} (один раз)…"))
        model = err = None
        try:
            if not cached:
                download_with_progress(name, lambda p: self.ui_q.put(("mic_model", "progress", p)))
            model, self.where = self._load(name)
        except Exception as e:
            err = e
        self.models.mic, self.models.mic_name = model, name
        self.models.mic_ready.set()  # теперь может грузиться точная модель для F7
        if model is None:
            self.ui_q.put(("fatal", f"Не удалось загрузить распознавание речи ({name}): {err}. "
                                    "Проверь интернет и место на диске, затем выбери модель в "
                                    "⚙ → «Распознавание речи» (она скачается)."))
            while self.models.mic is None:  # ждём, пока в настройках выберут модель — тогда оживаем
                time.sleep(0.5)
        else:
            print(f"[whisper] микрофон: {name} · {self.where}")
            self.ui_q.put(("mic_model", "ready", f"{name} · {self.where}"))
        self.ui_q.put(("ready",))
        while True:  # фразы, сказанные, пока модель грузилась, не выполняем задним числом
            try:
                self.audio_q.get_nowait()
            except queue.Empty:
                break
        while True:
            try:
                kind, audio = self.audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.paused.is_set():  # идёт запись/распознавание вопроса с компьютера — микрофон подождёт
                continue
            self.ui_q.put(("stt", True))
            text = self.transcribe(audio)
            self.ui_q.put(("stt", False))
            self.ui_q.put(("heard", text))

    def _switch(self, name):
        self.ui_q.put(("mic_model", "loading", name))
        try:
            if not model_cached(name):
                download_with_progress(name, lambda p: self.ui_q.put(("mic_model", "progress", p)))
            model, where = self._load(name)
        except Exception as e:
            self.ui_q.put(("mic_model", "error", f"{name}: {e}"))
            return
        old = self.models.mic
        self.models.mic, self.models.mic_name, self.where = model, name, where
        del old
        print(f"[whisper] микрофон: теперь {name} · {where}")
        self.ui_q.put(("mic_model", "ready", f"{name} · {where}"))

    def transcribe(self, audio):
        model = self.models.mic
        lang = S.language if S.language != "auto" else None
        for attempt in (1, 2):
            try:
                if lang is None:
                    lang = pick_language(model, audio, S.listen_languages)
                segs, _ = model.transcribe(audio, language=lang, beam_size=5, vad_filter=True,
                                           condition_on_previous_text=False, initial_prompt=WAKE_PROMPT,
                                           hotwords=(S.mic_hint or "").strip() or None)
                return " ".join(seg.text.strip() for seg in segs).strip()
            except Exception as e:
                print("[stt] ошибка:", e)
                if attempt == 1 and self.where == "видеокарта":  # видеокарта сбоит — переходим на процессор
                    try:
                        model, self.where = load_whisper(self.models.mic_name, "cpu")
                        self.models.mic = model
                        continue
                    except Exception as e2:
                        print("[stt] и на процессоре не вышло:", e2)
                break
        return ""


class ListenTranscriber(threading.Thread):
    """Распознаёт куски звука компьютера (F7) — целиком, с контекстом. Пока качается нужная модель,
    работает на той, что уже скачана, и подменяет её без перезапуска."""

    # мягкий фильтр тишины: убирает только долгие паузы, тихую и невнятную речь оставляет
    VAD = {"threshold": 0.12, "min_silence_duration_ms": 2000, "speech_pad_ms": 800}

    def __init__(self, ui_q, models):
        super().__init__(daemon=True, name="stt-listen")
        self.ui_q = ui_q
        self.models = models
        self.q = queue.Queue()
        self.model = None
        self.where = self.model_name = ""
        self.lock = threading.Lock()
        self.hotwords = None  # приложение дополняет терминами из материалов
        self.threads = max(4, (os.cpu_count() or 8) // 2)  # на процессоре — все физические ядра
        self.switching = None

    def _load(self, name, device):
        err = None
        for attempt in (1, 2):
            try:
                return load_whisper(name, device, cpu_threads=self.threads)
            except Exception as e:
                err = e
                print(f"[whisper] не удалось загрузить {name} (попытка {attempt}): {e}")
                time.sleep(1.0)
        raise err

    def run(self):
        # Сначала дожидаемся модели микрофона: так библиотека распознавания грузится одним потоком,
        # а голосовые команды начинают работать сразу.
        self.models.mic_ready.wait()
        device = whisper_device()
        want = listen_model_name(device)
        model = where = name = None
        upgrade = False
        if want != self.models.mic_name:
            if model_cached(want):
                self.ui_q.put(("listen_model", "loading", want))
                try:
                    model, where = self._load(want, device)
                    name = want
                except Exception as e:
                    self.ui_q.put(("listen_model", "fallback", f"{want}: {e}"))
            else:
                # пока качается нужная модель — работаем на уже скачанной
                for alt in ("large-v3-turbo", "large-v3", "medium", "small"):
                    if alt not in (want, self.models.mic_name) and model_cached(alt):
                        try:
                            model, where = self._load(alt, device)
                            name = alt
                            break
                        except Exception:
                            continue
                upgrade = True
        if model is None:
            model, where, name = self.models.mic, "та же, что для микрофона", self.models.mic_name
        if model is None:
            err = "модель распознавания не загрузилась"
            self.ui_q.put(("listen_model", "error", err))
            while True:  # не оставляем задания висеть — отвечаем ошибкой
                job_id, _ = self.q.get()
                self.ui_q.put(("listen_text", job_id, "", "", 0.0, err))
        with self.lock:
            self.model, self.where, self.model_name = model, where, name
        print(f"[whisper] звук компьютера: {name} · {where}")
        self.ui_q.put(("listen_model", "ready", f"{name} · {where}"))
        if upgrade:
            self.request_model(want)
        while True:
            job_id, audio = self.q.get()
            t0 = time.time()
            with self.lock:
                text, lang, err = self._transcribe(audio)
            self.ui_q.put(("listen_text", job_id, text, lang or "", time.time() - t0, err))

    def request_model(self, want):
        """Сменить модель F7 (скачает, если нужно); старая работает, пока новая не готова."""
        if want == self.model_name or want == self.switching:
            return
        self.switching = want
        threading.Thread(target=self._upgrade, args=(want, whisper_device()), daemon=True,
                         name="stt-listen-switch").start()

    def _upgrade(self, want, device):
        try:
            if not model_cached(want):
                self.ui_q.put(("listen_model", "download", want))
                download_with_progress(want, lambda p: self.ui_q.put(("listen_model", "progress", p)))
            if want == self.models.mic_name and self.models.mic is not None:
                model, where = self.models.mic, "та же, что для микрофона"
            else:
                model, where = self._load(want, device)
        except Exception as e:
            print(f"[whisper] {want} не скачалась/не загрузилась: {e}")
            self.ui_q.put(("listen_model", "upgrade_fail", f"{want}: {e}"))
            self.switching = None
            return
        with self.lock:  # подменяем между заданиями
            self.model, self.where, self.model_name = model, where, want
        self.switching = None
        print(f"[whisper] звук компьютера: теперь {want} · {where}")
        self.ui_q.put(("listen_model", "upgraded", f"{want} · {where}"))

    def _vad_ok(self, audio):
        """Можно ли доверять фильтру тишины. Если он выкидывает хотя бы полсекунды звука, который явно слышен
        над шумом, — значит, путает тихую или невнятную речь с тишиной. Тогда распознаём всю запись без него."""
        try:
            from faster_whisper.vad import get_speech_timestamps, VadOptions
            ts = get_speech_timestamps(audio, VadOptions(**self.VAD))
        except Exception:
            return True
        w = 1600  # окна по 0,1 с
        n = len(audio) // w
        if n < 5:
            return True
        covered = np.zeros(n * w, bool)
        for t in ts:
            covered[t["start"]:t["end"]] = True
        rms = np.sqrt(np.mean(audio[: n * w].reshape(n, w).astype(np.float64) ** 2, axis=1))
        audible = rms > max(float(np.percentile(rms, 10)) * 2, 1e-3)
        dropped = audible & (covered.reshape(n, w).mean(axis=1) < 0.5)
        return dropped.sum() * 0.1 < 0.3

    def _transcribe(self, audio, model=None):
        """→ (текст, язык, ошибка). При сбое видеокарты — переходит на процессор и повторяет."""
        lang = S.listen_language if S.listen_language not in ("", "auto", None) else None
        err = None
        own = model is None
        model = model or self.model
        # Короткая запись (вопрос + 2 с до и 1 с после) идёт в распознавание целиком: длинных пауз в ней нет,
        # а фильтр тишины на тихой/невнятной речи выкидывает слова. Для длинных записей — фильтр со страховкой.
        use_vad = bool(len(audio) > 20 * 16000 and self._vad_ok(audio))
        for attempt in (1, 2):
            try:
                if not lang:
                    det = model
                    if whisper_device() == "cpu" and self.models.mic is not None:
                        det = self.models.mic  # на процессоре язык определяет маленькая модель — быстрее
                    lang = pick_language(det, audio, S.listen_languages, self.VAD if use_vad else None)
                segs, info = model.transcribe(
                    audio, language=lang, beam_size=5, vad_filter=use_vad,
                    vad_parameters=self.VAD if use_vad else None,
                    condition_on_previous_text=False, hotwords=self.hotwords or None)
                text = strip_tail_junk(" ".join(seg.text.strip() for seg in segs))
                return text, lang or getattr(info, "language", ""), None
            except Exception as e:
                err = f"ошибка распознавания: {e}"
                print("[stt]", err)
                if own and attempt == 1 and self.where == "видеокарта":  # видеокарта сбоит — на процессор
                    try:
                        self.model, self.where = load_whisper(self.model_name, "cpu", cpu_threads=self.threads)
                        model = self.model
                        self.ui_q.put(("listen_model", "ready", f"{self.model_name} · процессор (видеокарта дала сбой)"))
                        continue
                    except Exception as e2:
                        err = f"ошибка распознавания: {e2}"
                break
        return "", lang, err

    def compare(self, audio, names, report):
        """«Сравнить»: распознать одну запись несколькими моделями. report(имя, текст, секунды распознавания, ошибка, секунды всего)."""
        device = whisper_device()
        for name in names:
            t0 = time.time()
            try:
                if name == self.model_name:
                    model = self.model
                elif name == self.models.mic_name and self.models.mic is not None:
                    model = self.models.mic
                else:
                    if not model_cached(name):
                        report(name, "", 0.0, "модель не скачана", 0.0)
                        continue
                    model, _ = self._load(name, device)
                t1 = time.time()
                with self.lock:
                    text, lang, err = self._transcribe(audio, model=model)
                report(name, text, time.time() - t1, err, time.time() - t0)
            except Exception as e:
                report(name, "", 0.0, str(e), time.time() - t0)
            finally:
                model = None


def short_err(e):
    s = str(e).strip().splitlines()
    return re.sub(r"\s+", " ", s[-1] if s else repr(e))[:200]
