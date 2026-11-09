# -*- coding: utf-8 -*-
"""Рисует значок программы и картинки в высоком разрешении (запуск: .venv\\Scripts\\python.exe setup\\make_art.py).
  app/icon.ico, app/icon.png          — значок программы (ярлык, окна)
  branding/telegram_avatar_1024.png   — аватарка канала (Telegram обрезает кругом — рисунок в центре)
  branding/icon_2048.png, icon_512.png — значок крупно (прозрачный фон)
  setup/wizard_large.png, wizard_small.png — картинки для окна EXE-установщика"""

import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C1, C2 = (240, 148, 112), (196, 88, 58)          # коралловый градиент (цвет Claude), сверху-слева → снизу-справа
BARS = [0.30, 0.56, 0.80, 0.56, 0.30]            # звуковая волна


def gradient(size, c1=C1, c2=C2):
    """Диагональный градиент."""
    import numpy as np
    w, h = size
    t = (np.arange(w)[None, :] + np.arange(h)[:, None]) / float(max(1, w + h - 2))  # 0 — левый верх, 1 — правый низ
    t = t[..., None]
    rgb = (1 - t) * np.array(c1, float) + t * np.array(c2, float)
    return Image.fromarray(rgb.astype("uint8"), "RGB")


def bars_layer(S, scale=1.0, cy=None):
    """Белая звуковая волна с мягкой тенью, по центру квадрата S×S."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shadow)
    bw, gap = int(0.102 * S * scale), int(0.053 * S * scale)
    total = len(BARS) * bw + (len(BARS) - 1) * gap
    x = (S - total) // 2
    cy = cy or S // 2
    for hfrac in BARS:
        hh = int(hfrac * S * 0.92 * scale)
        y0 = cy - hh // 2
        ds.rounded_rectangle((x, y0 + int(0.012 * S), x + bw, y0 + hh + int(0.012 * S)), radius=bw // 2,
                             fill=(90, 30, 10, 90))
        d.rounded_rectangle((x, y0, x + bw, y0 + hh), radius=bw // 2, fill=(255, 255, 255, 255))
        x += bw + gap
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.012))
    return Image.alpha_composite(shadow, layer)


def app_icon(S=2048):
    """Скруглённый квадрат с градиентом и волной (прозрачные углы)."""
    pad = int(S * 0.04)
    grad = gradient((S, S)).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, S - pad, S - pad), radius=int(S * 0.225), fill=255)
    # лёгкий блик сверху
    gloss = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    ImageDraw.Draw(gloss).ellipse((-S * 0.3, -S * 0.75, S * 1.3, S * 0.42), fill=(255, 255, 255, 26))
    body = Image.alpha_composite(grad, gloss)
    body = Image.alpha_composite(body, bars_layer(S))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(body, (0, 0), mask)
    return out


def telegram_avatar(S=2048):
    """Квадрат на всю площадь (Telegram показывает кругом): градиент + волна в безопасной середине."""
    grad = gradient((S, S)).convert("RGBA")
    glow = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    ImageDraw.Draw(glow).ellipse((S * 0.18, S * 0.18, S * 0.82, S * 0.82), fill=(255, 255, 255, 34))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.09))
    img = Image.alpha_composite(grad, glow)
    img = Image.alpha_composite(img, bars_layer(S, scale=0.78))
    return img.convert("RGB")


def main():
    os.makedirs(os.path.join(ROOT, "branding"), exist_ok=True)
    icon = app_icon()
    icon.save(os.path.join(ROOT, "branding", "icon_2048.png"))
    icon.resize((512, 512), Image.LANCZOS).save(os.path.join(ROOT, "branding", "icon_512.png"))
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, "app", "icon.png"))
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, "app", "icon.ico"), sizes=sizes)
    telegram_avatar().resize((1024, 1024), Image.LANCZOS).save(os.path.join(ROOT, "branding", "telegram_avatar_1024.png"))
    # окно установщика: высокая картинка слева (приветствие) и маленький значок справа вверху
    W, H = 328, 628
    big = gradient((W * 4, H * 4)).convert("RGBA")
    ic = app_icon(1024).resize((W * 4 * 70 // 100, W * 4 * 70 // 100), Image.LANCZOS)
    big.alpha_composite(ic, ((W * 4 - ic.width) // 2, int(H * 4 * 0.30)))
    big.resize((W, H), Image.LANCZOS).convert("RGB").save(os.path.join(ROOT, "setup", "wizard_large.png"))
    small = Image.new("RGB", (110, 110), (255, 255, 255))
    s_ic = app_icon(1024).resize((104, 104), Image.LANCZOS)
    small.paste(s_ic, (3, 3), s_ic)
    small.save(os.path.join(ROOT, "setup", "wizard_small.png"))
    print("готово")


if __name__ == "__main__":
    main()
