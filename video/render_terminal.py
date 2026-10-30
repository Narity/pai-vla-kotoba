"""record_terminal.py の記録（asciicast）を、ターミナル風の MP4 に描き直す。動画編集用の目印（cues）も書き出す。

  uv run python video/render_terminal.py outputs/video/session_a.cast   # → session_a.mp4 と session_a.cues.json

- 記録された文字を、時刻どおりに 1 文字ずつ画面に出す（打ち込みの速さ・実行の待ち時間も実際のまま）。
- cues.json には、モデルの読み込み・各指示の実行開始と結果・断った時刻と、保存されたロボット動画のパスを書く。
  実際の画面収録に差し替えるときは、その動画に合わせて cues.json の時刻を書き直す。
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 30
FONT_SIZE = 22
CELL_W, CELL_H, BASELINE = 13, 28, 21  # Menlo 22 px の文字幅は約 13 px
PAD, TITLE_H, RADIUS = 18, 36, 12
ROWS = 26
BG, FG = (30, 31, 34), (222, 225, 230)
TITLE_BG, TITLE_FG, FRAME = (48, 50, 55), (160, 163, 170), (70, 72, 78)
DOTS = [(255, 95, 87), (254, 188, 46), (40, 200, 64)]
FONTS = {
    "mono": "/System/Library/Fonts/Menlo.ttc",
    "cjk": "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "sym": "/System/Library/Fonts/Apple Symbols.ttf",
}
# 色・カーソル移動などの制御シーケンス（このデモでは使わないので読み飛ばす）
ESC_RE = re.compile(r"\x1b(\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[()][0-9A-Za-z]|[=>78])")


@lru_cache(maxsize=None)
def font(name: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[name], FONT_SIZE)


def glyph(f: ImageFont.FreeTypeFont, ch: str) -> bytes:
    img = Image.new("L", (2 * FONT_SIZE, 2 * FONT_SIZE))
    ImageDraw.Draw(img).text((0, 0), ch, font=f, fill=255)
    return img.tobytes()


@lru_cache(maxsize=None)
def font_for(ch: str) -> ImageFont.FreeTypeFont:
    """その文字を持っているフォント（等幅 → 日本語 → 記号の順に探す）。持っていなければ豆腐と同じ形になるので比べる。"""
    for name in ("mono", "cjk", "sym"):
        f = font(name)
        if glyph(f, ch) != glyph(f, "\U0010fffd"):
            return f
    return font("cjk")


def width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


class Term:
    """必要最小限の端末：改行・復帰・後退・自動折り返し・スクロールだけ扱う。"""

    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        self.grid = [[None] * cols for _ in range(rows)]  # 各セルは文字。全角の右半分は ""
        self.r = self.c = 0

    def newline(self) -> None:
        self.r += 1
        if self.r == self.rows:
            self.grid.pop(0)
            self.grid.append([None] * self.cols)
            self.r -= 1

    def feed(self, text: str) -> None:
        for ch in ESC_RE.sub("", text):
            if ch == "\r":
                self.c = 0
            elif ch == "\n":
                self.newline()
            elif ch == "\b":
                self.c = max(0, self.c - 1)
            elif ord(ch) < 32 or ch == "\x7f":
                continue
            else:
                w = width(ch)
                if self.c + w > self.cols:
                    self.c = 0
                    self.newline()
                self.grid[self.r][self.c] = ch
                if w == 2:
                    self.grid[self.r][self.c + 1] = ""
                self.c += w


def window(cols: int, rows: int, title: str) -> tuple[Image.Image, tuple[int, int]]:
    """ウィンドウの枠（タイトルバーと 3 つの丸）を描いた下地と、文字を置き始める位置。"""
    w = cols * CELL_W + 2 * PAD
    h = TITLE_H + rows * CELL_H + 2 * PAD
    w, h = (w + 15) // 16 * 16, (h + 15) // 16 * 16  # 動画のエンコードで扱いやすい大きさにそろえる
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], RADIUS, fill=BG, outline=FRAME)
    d.rounded_rectangle([0, 0, w - 1, TITLE_H], RADIUS, fill=TITLE_BG, corners=(True, True, False, False))
    for i, color in enumerate(DOTS):
        cx = 20 + i * 22
        d.ellipse([cx - 7, TITLE_H // 2 - 7, cx + 7, TITLE_H // 2 + 7], fill=color)
    title_font = ImageFont.truetype(FONTS["mono"], 15)
    d.text((w // 2, TITLE_H // 2), title, font=title_font, fill=TITLE_FG, anchor="mm")
    return img, (PAD, TITLE_H + PAD)


def draw(base: Image.Image, origin: tuple[int, int], term: Term, cursor: bool) -> np.ndarray:
    img = base.copy()
    d = ImageDraw.Draw(img)
    x0, y0 = origin
    for r, row in enumerate(term.grid):
        for c, ch in enumerate(row):
            if ch:
                x = x0 + c * CELL_W
                if width(ch) == 2:  # 全角は 2 マスの中央に置く
                    x += (2 * CELL_W - font_for(ch).getlength(ch)) / 2
                d.text((x, y0 + r * CELL_H + BASELINE), ch, font=font_for(ch), fill=FG, anchor="ls")
    if cursor:
        x, y = x0 + term.c * CELL_W, y0 + term.r * CELL_H
        d.rectangle([x, y + 3, x + CELL_W - 1, y + CELL_H - 3], fill=(200, 203, 208))
    return np.asarray(img)


def cues_from(events: list[list]) -> dict:
    """画面に出た文字から、動画編集で使う時刻を拾う。"""
    out = {"command_end": None, "load_start": None, "loaded": None, "prompts": [], "runs": [], "refusals": []}
    line, line_t = "", 0.0
    for t, _, text in events:
        for ch in ESC_RE.sub("", text):
            if ch == "\n":
                s = line.strip()
                if out["command_end"] is None:  # 1 行目は「$ コマンド」
                    out["command_end"] = t
                elif s.startswith("モデルを読み込んでいます") and out["load_start"] is None:
                    out["load_start"] = line_t
                elif s.startswith("できること") and out["loaded"] is None:
                    out["loaded"] = line_t
                elif s.startswith("指示>"):
                    out["prompts"][-1]["text"] = s.removeprefix("指示>").strip()
                elif s.startswith("実行中"):
                    out["runs"].append({"input": out["prompts"][-1]["text"], "start": line_t})
                elif s.startswith(("成功", "失敗")) and out["runs"]:
                    out["runs"][-1]["result"] = line_t
                    out["runs"][-1]["result_text"] = s
                elif s.startswith("動画：") and out["runs"]:
                    out["runs"][-1]["clip"] = s.removeprefix("動画：")
                elif s.startswith("✗"):
                    out["refusals"].append({"input": out["prompts"][-1]["text"], "time": line_t, "text": s})
                line = ""
            elif ch != "\r":
                if not line:
                    line_t = t  # 行の最初の文字が出た時刻
                line += ch
                if line == "指示> ":
                    out["prompts"].append({"time": t, "text": ""})
    out["end"] = events[-1][0]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="asciicast をターミナル風の MP4 に描き直す")
    ap.add_argument("cast", type=Path)
    ap.add_argument("--rows", type=int, default=ROWS, help="画面の行数（記録時より少なくてもよい）")
    ap.add_argument("--tail", type=float, default=1.5, help="最後の出力のあと、画面を止めておく秒数")
    args = ap.parse_args()

    lines = args.cast.read_text().splitlines()
    header = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:]]
    cols = header["width"]
    title = header.get("title", "").replace("uv run python -m ", "")
    base, origin = window(cols, args.rows, title)
    term = Term(cols, args.rows)

    duration = events[-1][0] + args.tail
    out = args.cast.with_suffix(".mp4")
    writer = imageio.get_writer(out, fps=FPS, quality=9, macro_block_size=16)
    i_ev, last_key, frame = 0, None, None
    for i in range(int(duration * FPS) + 1):
        t = i / FPS
        while i_ev < len(events) and events[i_ev][0] <= t:
            term.feed(events[i_ev][2])
            i_ev += 1
        recent = i_ev > 0 and t - events[i_ev - 1][0] < 0.6  # 文字が出た直後はカーソルを点けたまま
        cursor = recent or int(t * 2) % 2 == 0
        key = (i_ev, cursor)
        if key != last_key:
            frame = draw(base, origin, term, cursor)
            last_key = key
        writer.append_data(frame)
    writer.close()

    cues = cues_from(events) | {"video": out.name, "fps": FPS, "size": list(base.size)}
    cue_path = args.cast.with_suffix(".cues.json")
    cue_path.write_text(json.dumps(cues, ensure_ascii=False, indent=2))
    print(f"{out}（{duration:.1f} 秒、{base.size[0]}×{base.size[1]}）と {cue_path}")


if __name__ == "__main__":
    main()
