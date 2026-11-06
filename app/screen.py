# -*- coding: utf-8 -*-
"""Скриншот для Claude: монитор под курсором (mss)."""

import base64
import io

from .config import S


def _mss():
    import mss
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


def grab_screen(mouse_xy, max_side=None):
    from PIL import Image

    max_side = max_side or S.max_image_side
    with _mss() as sct:
        mons = sct.monitors
        if S.monitor == "all" or len(mons) < 2:
            mon = mons[0]
        elif S.monitor == "primary":
            mon = mons[1]
        else:
            mon = mons[1]
            x, y = mouse_xy
            for m in mons[1:]:
                if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                    mon = m
                    break
        shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def encode_image(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data, media = buf.getvalue(), "image/png"
    if len(data) > 4_500_000:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        data, media = buf.getvalue(), "image/jpeg"
    return base64.b64encode(data).decode("ascii"), media
