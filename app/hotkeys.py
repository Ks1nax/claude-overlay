# -*- coding: utf-8 -*-
"""Горячие клавиши. На Windows — низкоуровневый хук pynput с win32_event_filter: наши клавиши перехватываются
целиком и не доходят до других программ (F7 в браузере не включает «режим каретки»).
Обработчик хука — быстрый: только смотрит в словарь и кладёт событие в очередь (иначе Windows отключит хук).

Формат клавиш как у pynput: "<f7>", "<ctrl>+<alt>+q", "<shift>+<f8>"."""

import sys

IS_WIN = sys.platform == "win32"

VK_CODES = {f"f{i}": 0x6F + i for i in range(1, 25)}
VK_CODES.update({"esc": 0x1B, "pause": 0x13, "scroll_lock": 0x91, "insert": 0x2D, "home": 0x24, "end": 0x23,
                 "page_up": 0x21, "page_down": 0x22, "space": 0x20, "enter": 0x0D, "tab": 0x09,
                 "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
                 "print_screen": 0x2C, "caps_lock": 0x14, "num_lock": 0x90, "menu": 0x5D})
VK_CODES.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})
VK_CODES.update({str(d): 0x30 + d for d in range(10)})
VK_CODES.update({f"num_{d}": 0x60 + d for d in range(10)})
VK_CODES.update({"num_*": 0x6A, "num_+": 0x6B, "num_-": 0x6D, "num_.": 0x6E, "num_/": 0x6F})
VK_NAMES = {v: k for k, v in VK_CODES.items()}

MOD_VKS = {"ctrl": (0x11, 0xA2, 0xA3), "alt": (0x12, 0xA4, 0xA5), "shift": (0x10, 0xA0, 0xA1), "cmd": (0x5B, 0x5C)}
ALL_MOD_VKS = {vk for vks in MOD_VKS.values() for vk in vks}
MOD_ORDER = ("ctrl", "alt", "shift", "cmd")
MOD_TITLES = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}

ACTION_TITLES = {
    "listen": "Вопрос со звука компьютера (начать / закончить)",
    "talk": "Следующая фраза — команда без «Клод»",
    "toggle": "Спрятать / показать окно",
    "region": "Выделить кусок экрана для вопроса",
    "type": "Написать вопрос текстом",
}
# действие → имя настройки (порядок — как в окне настроек)
ACTIONS = [("listen", "hotkey_listen"), ("talk", "hotkey_talk"), ("toggle", "hotkey_toggle"),
           ("region", "hotkey_region"), ("type", "hotkey_type")]


def current_binds(S):
    return {a: S.get(k) for a, k in ACTIONS}

# Клавиши, которые обычно нужны другим программам: предупреждаем
BUSY_KEYS = {
    ((), "f1"): "справка во многих программах", ((), "f5"): "обновить страницу в браузере",
    ((), "f11"): "полный экран в браузере", ((), "f12"): "инструменты разработчика в браузере",
    ((), "f2"): "переименовать в Проводнике", ((), "f3"): "поиск", ((), "f4"): "адресная строка",
    ((), "f10"): "меню программы", ((), "esc"): "отмена во всех программах",
    (("alt",), "f4"): "закрыть окно", (("ctrl",), "c"): "копировать", (("ctrl",), "v"): "вставить",
    (("ctrl",), "x"): "вырезать", (("ctrl",), "z"): "отменить", (("ctrl",), "a"): "выделить всё",
    (("ctrl",), "s"): "сохранить", (("ctrl",), "f"): "поиск", (("ctrl",), "w"): "закрыть вкладку",
    (("ctrl",), "t"): "новая вкладка", (("alt",), "tab"): "переключение окон",
}


def parse_spec(spec):
    """"<ctrl>+<f7>" → (кортеж модификаторов, имя клавиши) или None."""
    s = (spec or "").strip().lower()
    if not s:
        return None
    parts = [p.strip() for p in s.split("+") if p.strip()]
    mods, key = [], None
    for p in parts:
        name = p[1:-1] if p.startswith("<") and p.endswith(">") else p
        if name in ("ctrl_l", "ctrl_r", "control"):
            name = "ctrl"
        if name in ("alt_l", "alt_r", "alt_gr"):
            name = "alt"
        if name in ("shift_l", "shift_r"):
            name = "shift"
        if name in ("win", "cmd_l", "cmd_r", "super"):
            name = "cmd"
        if name in MOD_VKS:
            mods.append(name)
        else:
            key = name
    if key is None or key not in VK_CODES:
        return None
    return tuple(m for m in MOD_ORDER if m in mods), key


def make_spec(mods, key):
    return "+".join([f"<{m}>" for m in MOD_ORDER if m in mods] + [f"<{key}>" if len(key) > 1 else key])


def display(spec):
    """"<ctrl>+<f7>" → "Ctrl+F7"; пусто — «нет»."""
    p = parse_spec(spec)
    if not p:
        return "нет"
    mods, key = p
    title = key.upper() if (len(key) == 1 or key.startswith("f")) else key.replace("_", " ").title()
    return "+".join([MOD_TITLES[m] for m in mods] + [title])


def problems(binds):
    """binds: {действие: spec} → список предупреждений (повторы, занятые клавиши, буквы без Ctrl/Alt)."""
    out = []
    seen = {}
    for action, spec in binds.items():
        p = parse_spec(spec)
        if not spec:
            continue
        if not p:
            out.append(f"«{spec}» — не понимаю такую клавишу ({ACTION_TITLES.get(action, action)}).")
            continue
        if p in seen:
            out.append(f"{display(spec)} назначена дважды: «{ACTION_TITLES.get(seen[p], seen[p])}» и "
                       f"«{ACTION_TITLES.get(action, action)}».")
        seen[p] = action
        mods, key = p
        if not mods and (len(key) == 1 or key in ("space", "enter", "tab", "backspace", "delete", "up", "down",
                                                  "left", "right")):
            out.append(f"{display(spec)} без Ctrl/Alt нельзя: эта клавиша перестанет печатать в других программах.")
        why = BUSY_KEYS.get((mods, key))
        if why:
            out.append(f"{display(spec)} обычно нужна другим программам ({why}) — пока оверлей запущен, "
                       "она будет только у него.")
    return out


def _held(vks):
    import ctypes
    gaks = ctypes.windll.user32.GetAsyncKeyState
    return any(gaks(v) & 0x8000 for v in vks)


class HotkeyManager:
    """on_event(имя) вызывается из потока хука — должен быть мгновенным (положить в очередь)."""

    def __init__(self, on_event, esc_active=lambda: False):
        self.on_event = on_event
        self.esc_active = esc_active
        self.binds = {}          # (mods, vk) → действие
        self.vks = set()
        self.capture = None      # переназначение: callback(spec или None)
        self.listener = None
        self.mode = ""
        self._pressed = set()
        self._gh = None

    def set_binds(self, actions):
        """actions: {действие: spec}."""
        binds = {}
        for action, spec in actions.items():
            p = parse_spec(spec)
            if p:
                binds[(p[0], VK_CODES[p[1]])] = action
        self.binds = binds
        self.vks = {vk for _, vk in binds}
        if self.mode == "global":  # без перехвата (не Windows) — перезапускаем
            self._start_global(actions)

    def start(self, actions):
        self.set_binds(actions)
        try:
            from pynput import keyboard
        except Exception as e:
            print("[клавиши] недоступны:", e)
            return False
        if IS_WIN:
            try:
                self._start_win(keyboard)
                self.mode = "hook"
                return True
            except Exception as e:
                print("[клавиши] перехват клавиш не запустился, обычный режим:", e)
        self._start_global(actions)
        return self.mode == "global"

    def _start_win(self, keyboard):
        pressed = self._pressed
        holder = {}

        def flt(msg, data):
            vk = data.vkCode
            down = msg in (0x0100, 0x0104)  # WM_KEYDOWN, WM_SYSKEYDOWN
            cap = self.capture
            if cap is not None and vk not in ALL_MOD_VKS:
                if down:
                    if vk == 0x1B:
                        self.capture = None
                        cap(None)
                    else:
                        mods = tuple(m for m in MOD_ORDER if _held(MOD_VKS[m]))
                        name = VK_NAMES.get(vk)
                        if name:
                            self.capture = None
                            cap(make_spec(mods, name))
                    pressed.add(("cap", vk))
                else:
                    pressed.discard(("cap", vk))
                holder["l"].suppress_event()
            if ("cap", vk) in pressed and not down:  # отпускание клавиши, нажатой при переназначении
                pressed.discard(("cap", vk))
                holder["l"].suppress_event()
            if not down and vk in pressed:   # отпускание нашей клавиши (в т. ч. Esc, когда запись уже отменена)
                pressed.discard(vk)
                holder["l"].suppress_event()
            ev = None
            if down and vk in self.vks:
                mods = tuple(m for m in MOD_ORDER if _held(MOD_VKS[m]))
                ev = self.binds.get((mods, vk))
            if ev is None and down and vk == 0x1B and self.esc_active():  # Esc — только пока идёт запись F7
                ev = "listen_cancel"
            if ev is None:
                return True
            if down:
                if vk not in pressed:            # автоповтор при удержании клавиши не считаем
                    pressed.add(vk)
                    self.on_event(ev)
            else:
                pressed.discard(vk)
            holder["l"].suppress_event()         # дальше событие не идёт (бросает исключение — так задумано)

        listener = keyboard.Listener(win32_event_filter=flt)
        holder["l"] = listener
        listener.daemon = True
        listener.start()
        self.listener = listener

    def _start_global(self, actions):
        from pynput import keyboard
        if self._gh is not None:
            try:
                self._gh.stop()
            except Exception:
                pass
        keys = {spec: (lambda a=a: self.on_event(a)) for a, spec in actions.items() if parse_spec(spec)}
        keys.setdefault("<esc>", lambda: self.esc_active() and self.on_event("listen_cancel"))
        try:
            self._gh = keyboard.GlobalHotKeys(keys)
            self._gh.daemon = True
            self._gh.start()
            self.mode = "global"
        except Exception as e:
            print("[клавиши] недоступны:", e)

    def capture_next(self, callback):
        """Следующее нажатие (не Esc) не идёт в программы, а отдаётся callback(spec); Esc — callback(None)."""
        self.capture = callback
