"""フレームの上に字幕帯（日本語の指示・VLA に渡した文・結果）を足して MP4 に保存する。

OpenCV の putText は日本語を描けないので、Pillow と macOS 標準のヒラギノフォントで描く。
"""
from __future__ import annotations

from pathlib import Path

import imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
BAND_H = 64  # 480 + 64 = 544 は 16 の倍数なので、エンコーダが画像サイズを勝手に変えない
PAD = 8
BG = (20, 20, 24)
TOP_COLOR = (255, 255, 255)
BOTTOM_COLOR = (170, 210, 255)
BADGE_COLOR = (200, 200, 200)
RESULT_BG = {True: (30, 150, 110), False: (205, 60, 55), None: (60, 85, 130)}  # None は成否を付けない表示

_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype(FONT_PATH, size)
        except OSError:  # ヒラギノが無い環境では日本語が表示されない（落ちはしない）
            _fonts[size] = ImageFont.load_default(size=size)
    return _fonts[size]


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: float, size: int, min_size: int = 11):
    """幅 max_w に収まるまでフォントを小さくする。"""
    while size > min_size and draw.textlength(text, font=_font(size)) > max_w:
        size -= 1
    return _font(size)


def caption(
    frame: np.ndarray,
    top: str,
    bottom: str,
    badge: str | None = None,
    result: str | None = None,
    ok: bool | None = None,
) -> np.ndarray:
    """frame の上に 2 行の字幕帯を足した画像を返す。
    badge：字幕帯の右上に出す短い表示（例：'0.5倍速'）。
    result：画像の下中央に出す結果ラベル（例：'成功（56 ステップ）'）。ok で緑／赤（None なら紺）を切り替える。"""
    h, w = frame.shape[:2]
    im = Image.new("RGB", (w, h + BAND_H), BG)
    im.paste(Image.fromarray(frame), (0, BAND_H))
    d = ImageDraw.Draw(im)
    top_max_w = w - 2 * PAD
    if badge:
        bf = _font(16)
        bw = d.textlength(badge, font=bf)
        d.text((w - PAD - bw, 9), badge, font=bf, fill=BADGE_COLOR)
        top_max_w -= bw + 12
    d.text((PAD, 6), top, font=_fit(d, top, top_max_w, 22), fill=TOP_COLOR)
    d.text((PAD, 37), bottom, font=_fit(d, bottom, w - 2 * PAD, 18), fill=BOTTOM_COLOR)
    if result:
        rf = _fit(d, result, w - 4 * PAD - 28, 24)
        x0, y0, x1, y1 = d.textbbox((0, 0), result, font=rf)
        bw, bh = x1 - x0 + 28, y1 - y0 + 16
        left, upper = (w - bw) // 2, BAND_H + h - bh - 16
        d.rounded_rectangle([left, upper, left + bw, upper + bh], radius=8, fill=RESULT_BG[ok])
        d.text((left + 14 - x0, upper + 8 - y0), result, font=rf, fill=(255, 255, 255))
    return np.asarray(im)


def save_video(
    frames: list[np.ndarray],
    path: Path,
    top: str,
    bottom: str,
    *,
    result: str | None = None,
    ok: bool | None = None,
    speed: float = 1.0,
    sim_hz: int = 80,
    hold_s: float = 1.5,
) -> Path:
    """字幕付き MP4 を書き出す。

    speed: 再生速度（1.0 = 等倍、0.5 = 2 倍スロー）。等倍以外のときは右上に「0.5倍速」などと出す。
    最後のフレームは hold_s 秒止めて、右上に結果（result）を出す。
    """
    stride = max(1, round(sim_hz * speed / 40))  # 40fps 前後になるようにフレームを間引く
    fps = sim_hz * speed / stride
    speed_badge = None if speed == 1.0 else f"{speed:g}倍速"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(path, fps=fps, macro_block_size=16) as writer:
        for f in frames[::stride]:
            writer.append_data(caption(f, top, bottom, speed_badge))
        last = caption(frames[-1], top, bottom, speed_badge, result, ok)
        for _ in range(round(fps * hold_s)):
            writer.append_data(last)
    return path
