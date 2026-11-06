# -*- coding: utf-8 -*-
"""Звук: микрофон (команды «Клод, …»), звук компьютера (F7, WASAPI loopback) и подготовка звука к распознаванию.
Обработчики звука — быстрые: только кладут кусок в очередь/буфер, вся тяжёлая работа — в других потоках."""

import math
import queue
import threading
import time
from collections import deque

import numpy as np

from .config import S
from .winsys import IS_WIN


class Segmenter:
    """Режет поток звука на фразы по громкости. Блоки могут быть разной длины."""

    def __init__(self, sr, thr_mult, min_level, end_silence, max_len, on_start, on_utterance, floor=1e-4):
        self.sr, self.thr_mult, self.min_level = sr, thr_mult, min_level
        self.end_silence, self.max_len = end_silence, max_len
        self.on_start, self.on_utterance = on_start, on_utterance
        self.floor = floor
        self.pre = deque()
        self.pre_sec = 0.0
        self.rec, self.rec_sec = [], 0.0
        self.speaking, self.voiced_sec, self.silence_sec = False, 0.0, 0.0

    @staticmethod
    def rms(b):
        return float(np.sqrt(np.mean(b * b)) + 1e-9) if len(b) else 0.0

    def feed(self, b):
        dur = len(b) / self.sr
        e = self.rms(b)
        thr = max(self.floor * self.thr_mult, self.min_level)
        if not self.speaking:
            self.pre.append(b)
            self.pre_sec += dur
            while self.pre_sec > 0.4 and len(self.pre) > 1:
                self.pre_sec -= len(self.pre.popleft()) / self.sr
            if e > thr:
                self.voiced_sec += dur
                if self.voiced_sec >= 0.09:  # ~90 мс звука подряд
                    self.speaking, self.silence_sec = True, 0.0
                    self.rec, self.rec_sec = list(self.pre), self.pre_sec
                    self.on_start()
            else:
                self.voiced_sec = 0.0
                self.floor = 0.995 * self.floor + 0.005 * e
        else:
            self.rec.append(b)
            self.rec_sec += dur
            self.silence_sec = self.silence_sec + dur if e < thr * 0.7 else 0.0
            if self.silence_sec >= self.end_silence or self.rec_sec >= self.max_len:
                audio = np.concatenate(self.rec)
                useful = self.rec_sec - self.silence_sec
                self.speaking, self.voiced_sec = False, 0.0
                self.pre.clear()
                self.pre_sec = 0.0
                self.rec, self.rec_sec = [], 0.0
                self.on_utterance(audio if useful > 0.35 else None)


def _lowpass_kernel(sr, cutoff_hz=7200.0, taps=161):
    """Фильтр нижних частот (окно Хэмминга): срезает всё выше ~7 кГц перед переходом на 16 кГц."""
    fc = cutoff_hz / sr
    n = np.arange(taps) - (taps - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(taps)
    return h / h.sum()


def _fft_filter(a, h, nfft=1 << 16):
    """Свёртка блоками через БПФ (overlap-save) — быстро и для двухминутных записей. Выход выровнен как «same»."""
    taps = len(h)
    half = (taps - 1) // 2
    block = nfft - taps + 1
    H = np.fft.rfft(h, nfft)
    padded = np.concatenate([np.zeros(half), a, np.zeros(taps - 1 - half + block)])
    out = np.empty(len(a))
    for i in range(0, len(a), block):
        y = np.fft.irfft(np.fft.rfft(padded[i:i + nfft], nfft) * H, nfft)
        n = min(block, len(a) - i)
        out[i:i + n] = y[taps - 1:taps - 1 + n]
    return out


def to_16k(a, sr):
    """Пересчёт в 16 кГц с фильтром от наложения частот (без него шипящие и свистящие превращаются в помехи)."""
    a = np.asarray(a, dtype=np.float64)
    if sr == 16000 or len(a) == 0:
        return a.astype(np.float32)
    if sr > 16000:
        a = _fft_filter(a, _lowpass_kernel(sr))
    if sr % 16000 == 0:
        out = a[:: sr // 16000]
    else:
        n = int(len(a) * 16000 / sr)
        out = np.interp(np.arange(n) * (sr / 16000), np.arange(len(a)), a)
    return out.astype(np.float32)


def _highpass(a, sr=16000, f0=70.0, f1=110.0):
    """Срезает гул и рокот ниже ~100 Гц (сеть 50 Гц, кулер, стук по столу) — речи там почти нет."""
    n = len(a)
    if n < 256:
        return a
    spec = np.fft.rfft(a)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    spec *= np.clip((f - f0) / (f1 - f0), 0.0, 1.0)
    return np.fft.irfft(spec, n)


def _level_speech(a, sr=16000, win=0.4, max_gain=4.0):
    """Подтягивает тихие куски речи к громким (до +12 дБ). Паузы и ровный шум не трогает."""
    w, hop = int(sr * win), int(sr * win / 2)
    if len(a) < 2 * w:
        return a
    starts = np.arange(0, len(a) - w + 1, hop)
    rms = np.array([np.sqrt(np.mean(a[s0:s0 + w] ** 2)) + 1e-9 for s0 in starts])
    noise, loud = np.percentile(rms, 15), np.percentile(rms, 90)
    speech = rms > max(noise * 2.5, loud * 0.02)
    gains = np.ones_like(rms)
    gains[speech] = np.clip(loud / rms[speech], 1.0, max_gain)
    return a * np.interp(np.arange(len(a)), starts + w / 2, gains)


def prepare_audio(a, sr):
    """Звук компьютера → 16 кГц моно: без гула, тихая речь подтянута, громкость к норме."""
    a = to_16k(a, sr)
    if len(a) == 0:
        return a
    a = a.astype(np.float64)
    a = a - float(np.mean(a))
    a = _highpass(a)
    a = _level_speech(a)
    peak = float(np.max(np.abs(a)))
    if peak > 1e-5:
        a = a * min(0.9 / peak, 50.0)
    return a.astype(np.float32)


def level_bars(rms, n_bars=8):
    """Громкость для строки состояния: ▮▮▮▯▯▯▯▯."""
    n = level_fraction(rms, n_bars)
    return "▮" * n + "▯" * (n_bars - n)


def level_fraction(rms, steps=None):
    """Громкость 0…1 (−60 дБ → 0, −10 дБ → 1); steps — округлить до целого числа делений."""
    db = 20 * math.log10(max(rms, 1e-6))
    f = max(0.0, min(1.0, (db + 60) / 50))
    return int(round(f * steps)) if steps else f


def save_wav(path, audio, sr=16000):
    """Последняя запись F7 — для кнопки «Сравнить модели» в настройках."""
    import wave
    a = np.clip(np.asarray(audio, dtype=np.float32), -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((a * 32767).astype("<i2").tobytes())


def load_wav(path):
    import wave
    with wave.open(path, "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        a = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return to_16k(a, sr) if sr != 16000 else a


# ---------------------------------------------------------------- микрофон

def list_input_devices():
    """Названия микрофонов (полные имена из WASAPI; если его нет — все устройства ввода)."""
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        apis = sd.query_hostapis()
    except Exception as e:
        print("[mic] список устройств недоступен:", e)
        return []
    wasapi = next((i for i, a in enumerate(apis) if "WASAPI" in a.get("name", "")), None)
    names = []
    for d in devs:
        if d.get("max_input_channels", 0) < 1:
            continue
        if wasapi is not None and d.get("hostapi") != wasapi:
            continue
        if d["name"] not in names:
            names.append(d["name"])
    return names


def open_input_stream(name, sr, block, callback):
    """Открывает микрофон по части названия ("" — по умолчанию). Сначала MME, потом WASAPI с пересчётом частоты,
    потом остальные. → (поток, настоящее название)."""
    import sounddevice as sd
    if not name:
        st = sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=block, callback=callback)
        st.start()
        try:
            return st, sd.query_devices(kind="input")["name"]
        except Exception:
            return st, "по умолчанию"
    want = name.lower()
    devs = list(enumerate(sd.query_devices()))
    apis = sd.query_hostapis()
    cands = [(i, d) for i, d in devs if d.get("max_input_channels", 0) > 0 and want in d["name"].lower()]
    # MME обрезает названия до 31 знака — ищем и по началу названия
    cands += [(i, d) for i, d in devs if d.get("max_input_channels", 0) > 0 and len(d["name"]) >= 20
              and want.startswith(d["name"].lower()) and (i, d) not in cands]
    if not cands:
        raise RuntimeError(f"не нашёл микрофон «{name}»")
    errors = []
    # Порядок: MME (как было всегда — Windows сам пересчитывает частоту), потом WASAPI с пересчётом, потом остальное.
    # Проверено: на некоторых устройствах (VB-Cable) WASAPI с пересчётом частоты открывается, но отдаёт тишину.
    order = {"MME": 0, "Windows WASAPI": 1, "Windows DirectSound": 2}
    for i, d in sorted(cands, key=lambda c: order.get(apis[c[1]["hostapi"]]["name"], 3)):
        kw = {}
        if "WASAPI" in apis[d["hostapi"]]["name"]:
            try:
                kw["extra_settings"] = sd.WasapiSettings(auto_convert=True)
            except Exception:
                pass
        try:
            st = sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=block, device=i,
                                callback=callback, **kw)
            st.start()
            return st, d["name"]
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(f"микрофон «{name}» не открылся: " + "; ".join(errors[-2:]))


class Listener(threading.Thread):
    """Слушает микрофон и режет поток на фразы по громкости. stop() — остановить (при смене микрофона)."""

    SR = 16000
    BLOCK = 480  # 30 мс

    def __init__(self, audio_q, ui_q):
        super().__init__(daemon=True, name="mic")
        self.audio_q = audio_q
        self.ui_q = ui_q
        self.stop_ev = threading.Event()
        self.level = 0.0          # громкость последнего кусочка — для индикатора в настройках
        self.device_name = ""
        self.tap = None           # проверка в мастере: сюда отдаются готовые фразы вместо очереди

    def stop(self):
        self.stop_ev.set()

    def run(self):
        blocks = queue.Queue()

        def cb(indata, frames, t, status):
            blocks.put(indata[:, 0].copy())

        try:
            stream, self.device_name = open_input_stream(S.mic_device, self.SR, self.BLOCK, cb)
        except Exception as e:
            self.ui_q.put(("mic_error", f"Не удалось открыть микрофон: {e}. Выбери другой: ⚙ → Звук."))
            return
        print(f"[mic] микрофон: {self.device_name}")
        try:
            levels = []
            t_end = time.time() + 1.0
            while time.time() < t_end and not self.stop_ev.is_set():
                try:
                    levels.append(Segmenter.rms(blocks.get(timeout=0.5)))
                except queue.Empty:
                    continue
            floor = max(float(np.median(levels)), 1e-4) if levels else 1e-3
            print(f"[mic] фоновый шум: {floor:.4f}")

            def done(audio):
                self.ui_q.put(("mic", False))
                if audio is not None:
                    if self.tap is not None:
                        self.tap(audio)
                    else:
                        self.audio_q.put(("mic", audio))

            seg = Segmenter(self.SR, S.mic_threshold_mult, S.mic_min_level, S.end_silence, S.max_utterance,
                            on_start=lambda: self.ui_q.put(("mic", True)), on_utterance=done, floor=floor)
            n = 0
            while not self.stop_ev.is_set():
                try:
                    b = blocks.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.level = Segmenter.rms(b)
                n += 1
                if n % 30 == 0:  # чувствительность можно менять в настройках на ходу
                    seg.thr_mult, seg.min_level = S.mic_threshold_mult, S.mic_min_level
                    seg.end_silence, seg.max_len = S.end_silence, S.max_utterance
                seg.feed(b)
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            print("[mic] микрофон закрыт")


# ---------------------------------------------------------------- звук компьютера (F7)

class SystemAudio:
    """Постоянно держит в памяти последние ~2 минуты звука, который играет на компьютере (WASAPI loopback, Windows).
    Слушает все устройства вывода сразу (колонки, наушники, HDMI…) и для вопроса берёт самое громкое.
    Пока не нажата F7, ничего не распознаётся и никуда не отправляется."""

    def __init__(self, ui_q):
        self.ui_q = ui_q
        self.lock = threading.Lock()
        self._open_lock = threading.Lock()
        self.devices = []           # [{"name", "rate", "chunks": deque[(время конца куска, np.ndarray)]}]
        self.pa = None
        self.streams = []
        self.state = "starting"     # starting / ok / error
        self.error = ""
        self.default_name = ""
        self.all_names = []         # все устройства вывода (для выбора в настройках)
        self.last_open = 0.0
        self.keep = 0.0

    def start(self):
        self.state = "starting"
        threading.Thread(target=self._open_serial, daemon=True, name="sys-audio-open").start()

    def _open_serial(self):
        """Открытия устройств идут строго по одному: два одновременных Pa_Initialize/Terminate опасны."""
        with self._open_lock:
            self._open()

    def update_keep(self):
        """Сколько секунд держать в памяти — меняется на ходу, без переоткрытия (буфер не теряется)."""
        self.keep = S.listen_pre_seconds + S.listen_max_seconds + S.listen_post_seconds + 10

    def _fail(self, msg):
        self.state, self.error = "error", msg
        self.ui_q.put(("sys_audio",))

    @staticmethod
    def _close_streams(streams, pa):
        """Вызывать БЕЗ self.lock: остановка потока ждёт конца обработчика звука, а он сам берёт lock."""
        for st in streams:
            try:
                st.stop_stream()
                st.close()
            except Exception:
                pass
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    def close(self):
        with self.lock:
            old_streams, old_pa = self.streams, self.pa
            self.streams, self.pa, self.devices = [], None, []
        self._close_streams(old_streams, old_pa)

    def _open(self):
        self.last_open = time.time()
        self.update_keep()
        if not IS_WIN:
            return self._fail("Запись звука компьютера (F7) пока работает только на Windows.")
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            return self._fail("Нет библиотеки PyAudioWPatch для записи звука компьютера — "
                              "запусти «Установить.bat», он её поставит.")
        self.close()
        try:
            pa = pyaudio.PyAudio()
            infos = list(pa.get_loopback_device_info_generator())
        except Exception as e:
            return self._fail(f"Не удалось получить список устройств звука: {e}")
        try:
            self.default_name = pa.get_default_wasapi_loopback().get("name", "")
        except Exception:
            self.default_name = ""
        self.all_names = [clean_loopback_name(d.get("name", "")) for d in infos]
        want = (S.listen_device or "").lower()
        if want:
            infos = [d for d in infos if want in d.get("name", "").lower()]
        devices, streams = [], []
        for info in infos:
            rate = int(info.get("defaultSampleRate") or 48000)
            ch = max(1, int(info.get("maxInputChannels") or 2))
            dev = {"name": info.get("name", "?"), "rate": rate, "chunks": deque()}
            try:
                st = pa.open(format=pyaudio.paInt16, channels=ch, rate=rate, input=True,
                             input_device_index=info["index"], frames_per_buffer=max(256, int(rate * 0.05)),
                             stream_callback=self._make_callback(dev, ch, pyaudio.paContinue))
            except Exception as e:
                print(f"[звук] не открылось устройство «{dev['name']}»: {e}")
                continue
            devices.append(dev)
            streams.append(st)
        if not devices:
            self._close_streams(streams, pa)
            return self._fail("Не нашёл ни одного устройства вывода звука для записи"
                              + (f" с названием «{S.listen_device}» — выбери другое: ⚙ → Звук" if want else "")
                              + ".")
        with self.lock:
            self.pa, self.streams, self.devices = pa, streams, devices
        self.state, self.error = "ok", ""
        print("[звук] слушаю устройства:", "; ".join(d["name"] for d in devices))
        self.ui_q.put(("sys_audio",))

    def _make_callback(self, dev, ch, cont):
        def cb(data, frame_count, time_info, status):
            try:
                a = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                if ch > 1:
                    a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
                now = time.time()
                keep = self.keep
                with self.lock:
                    q = dev["chunks"]
                    q.append((now, a))
                    while q and q[0][0] < now - keep:
                        q.popleft()
            except Exception:
                pass
            return (None, cont)

        return cb

    def last_activity(self):
        with self.lock:
            ts = [d["chunks"][-1][0] for d in self.devices if d["chunks"]]
        return max(ts) if ts else 0.0

    def refresh_if_stale(self):
        """Если звук давно не приходил (переключили наушники/колонки) — заново открыть устройства."""
        now = time.time()
        if self.state == "starting" or now - self.last_open < 10:
            return
        if self.state == "ok" and now - self.last_activity() < 3:
            return
        self.start()

    def level(self, seconds=0.3):
        return max([lv for _, lv in self.device_levels(seconds)] or [0.0])

    def device_levels(self, seconds=0.3):
        """[(название, громкость)] — для индикаторов в настройках и мастере."""
        now = time.time()
        out = []
        with self.lock:
            for d in self.devices:
                acc, n = 0.0, 0
                for t, a in reversed(d["chunks"]):
                    if t < now - seconds:
                        break
                    acc += float(np.dot(a, a))
                    n += len(a)
                out.append((clean_loopback_name(d["name"]), (acc / n) ** 0.5 if n else 0.0))
        return out

    def segment(self, t0, t1):
        """Звук за отрезок [t0, t1] с самого громкого устройства → (массив, частота, имя) или (None, 0, "")."""
        with self.lock:
            snap = []
            for d in self.devices:
                rate = d["rate"]
                chunks = [(t, a) for t, a in d["chunks"] if t >= t0 and t - len(a) / rate <= t1]
                snap.append((d["name"], rate, chunks))
        best = None
        for name, rate, chunks in snap:
            if not chunks:
                continue
            energy = sum(float(np.dot(a, a)) for _, a in chunks) / rate
            if best is None or energy > best[0]:
                best = (energy, name, rate, chunks)
        if best is None or best[0] <= 1e-7:  # ничего не играло (или играла цифровая тишина)
            return None, 0, ""
        _, name, rate, chunks = best
        parts, prev_end = [], None
        for t_end, a in chunks:
            t_start = t_end - len(a) / rate
            if t_start < t0:
                a = a[int((t0 - t_start) * rate):]
                t_start = t0
            if t_end > t1:
                a = a[: max(0, len(a) - int((t_end - t1) * rate))]
                t_end = t1
            if not len(a):
                continue
            if prev_end is not None and t_start - prev_end > 0.25:  # пауза, когда звук не шёл
                parts.append(np.zeros(int(min(t_start - prev_end, 0.5) * rate), np.float32))
            parts.append(a)
            prev_end = t_end
        if not parts:
            return None, 0, ""
        return np.concatenate(parts), rate, name


def clean_loopback_name(name):
    return (name or "").replace(" [Loopback]", "").strip()
