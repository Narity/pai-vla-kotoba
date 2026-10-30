"""デモ動画（約 2 分、1920×1080、30 fps、字幕を焼き込み）を組み立てる。

  uv run python video/make_video.py                  # → outputs/video/demo.mp4
  uv run python video/make_video.py --preview 40 75  # 40 秒目と 75 秒目のコマだけ PNG で確認する
  uv run python video/make_video.py --list           # 場面ごとの開始時刻を表示する

材料（先に作っておく）
- outputs/video/session_a.{mp4,cues.json}：対話デモの端末（record_terminal.py → render_terminal.py）
- outputs/video/session_b.{mp4,cues.json}：見せ場（蛇口のシーンを固定して「開けて」「閉めて」）
- outputs/video/clips/：入れ替えテストの見本と、各シーンの最初の画像（make_clips.py）
- docs/figures/：実験結果の図（notebooks/export_figures.py）

端末の画面を実際の画面収録に差し替えるときは、--session-a / --session-b にその動画を渡す。
同じ場所・同じ名前の .cues.json（コマンドを打ち終えた時刻、読み込みの開始と終了、各指示の実行開始と結果、
ロボット動画のパス）を、その動画の時刻に合わせて用意する。動画は 1008×800 に合わせて縮小・余白づけされる。
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H, FPS = 1920, 1080, 30
MARGIN = 72
OUT = Path("outputs/video/demo.mp4")
VIDEO_DIR = Path("outputs/video")
FIG_DIR = Path("docs/figures")
FONT_W3 = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
FONT_W6 = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
BG, INK, INK2, MUTED = (17, 21, 27), (240, 242, 245), (190, 196, 205), (120, 128, 140)
ACCENT, PANEL, CHIP = (42, 120, 214), (28, 33, 41), (250, 200, 70)
TERM_BOX = (MARGIN, 120, 1008, 800)  # 端末の枠（左上 x, y, 幅, 高さ）
ROBOT_BOX = (MARGIN + 1008 + 48, 120, 720, 816)  # ロボット映像（480×544 を 1.5 倍）
FADE = 0.3


@lru_cache(maxsize=None)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_W6 if bold else FONT_W3, size)


class Stream:
    """MP4 を前から順に読み、t 秒目のコマを返す（巻き戻さない。最後を過ぎたら最後のコマのまま）。"""

    def __init__(self, path: Path | str, box: tuple[int, int] | None = None):
        self.reader = imageio.get_reader(path)
        self.fps = self.reader.get_meta_data()["fps"]
        self.n = self.reader.count_frames()
        self.frames = self.reader.iter_data()
        self.box, self.idx, self.img = box, -1, None

    def at(self, t: float) -> Image.Image:
        idx = min(max(int(t * self.fps), 0), self.n - 1)
        if idx != self.idx or self.img is None:
            frame = None
            while self.idx < idx:
                frame = next(self.frames)
                self.idx += 1
            if frame is not None:
                img = Image.fromarray(frame)
                self.img = ImageOps.pad(img, self.box, color=BG) if self.box and img.size != self.box else img
        return self.img


@dataclass
class Segment:
    name: str
    duration: float
    draw: Callable[[float], Image.Image]  # その場面の t 秒目の絵（字幕とフェードは後で重ねる）
    subs: list[tuple[float, float, str]] = field(default_factory=list)  # (開始, 終了, 字幕)
    chips: list[tuple[float, float, str]] = field(default_factory=list)  # 端末の右上に出す小さな注記


# ---------- 描画の部品 ----------

def background(label: str = "", title: str = "") -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    if label or title:
        d = ImageDraw.Draw(img)
        x = MARGIN
        if label:
            w = d.textlength(label, font=font(26)) + 32
            d.rounded_rectangle([x, 40, x + w, 84], 10, fill=ACCENT)
            d.text((x + w / 2, 62), label, font=font(26), fill=INK, anchor="mm")
            x += w + 20
        d.text((x, 62), title, font=font(40), fill=INK, anchor="lm")
    return img


def centered_text(img: Image.Image, y: int, text: str, size: int, color=INK, bold=True, spacing=14) -> None:
    ImageDraw.Draw(img).multiline_text((W / 2, y), text, font=font(size, bold), fill=color, anchor="ma",
                                       align="center", spacing=spacing)


@lru_cache(maxsize=None)
def subtitle_overlay(text: str) -> Image.Image:
    """画面下の字幕（半透明の黒い帯に白文字）。"""
    f = font(38)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = probe.multiline_textbbox((0, 0), text, font=f, spacing=12, align="center")
    pad_x, pad_y = 32, 16
    box_w, box_h = r - l + 2 * pad_x, b - t + 2 * pad_y
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    x0, y0 = (W - box_w) / 2, H - 36 - box_h
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], 14, fill=(0, 0, 0, 200))
    d.multiline_text((W / 2, y0 + pad_y - t), text, font=f, fill=(255, 255, 255, 255), anchor="ma",
                     align="center", spacing=12)
    return overlay


@lru_cache(maxsize=None)
def chip_overlay(text: str) -> Image.Image:
    """端末の枠の右上に出す注記（早送り・省略など）。"""
    f = font(26)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    w = d.textlength(text, font=f) + 36
    x1 = TERM_BOX[0] + TERM_BOX[2] - 20
    y0 = TERM_BOX[1] + 52
    d.rounded_rectangle([x1 - w, y0, x1, y0 + 46], 23, fill=CHIP + (240,))
    d.text((x1 - w / 2, y0 + 23), text, font=f, fill=(30, 30, 30, 255), anchor="mm")
    return overlay


def placeholder(box: tuple[int, int, int, int], text: str) -> Image.Image:
    img = Image.new("RGB", box[2:], BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, box[2] - 1, box[3] - 1], 16, fill=PANEL)
    d.text((box[2] / 2, box[3] / 2), text, font=font(30, bold=False), fill=MUTED, anchor="mm")
    return img


def figure_card(path: Path, max_w: int, max_h: int) -> Image.Image:
    """白い角丸のカードに図を載せる（レポート用の白背景の PNG をそのまま使う）。"""
    fig = Image.open(path).convert("RGB")
    fig.thumbnail((max_w - 48, max_h - 48), Image.LANCZOS)
    card = Image.new("RGB", (fig.width + 48, fig.height + 48), BG)
    ImageDraw.Draw(card).rounded_rectangle([0, 0, card.width - 1, card.height - 1], 18, fill=(255, 255, 255))
    card.paste(fig, (24, 24))
    return card


# ---------- 端末とロボット映像を並べる場面 ----------

def time_map(pieces: list[tuple[float, float, float]]):
    """端末の動画のうち使う区間 (開始, 終了, 速さ) をつなぎ、出力の時刻 ⇔ 端末の時刻を変換する関数を返す。"""
    table, out_t = [], 0.0
    for t0, t1, rate in pieces:
        table.append((out_t, out_t + (t1 - t0) / rate, t0, rate))
        out_t += (t1 - t0) / rate

    def to_term(t: float) -> float:
        for o0, o1, s0, rate in table:
            if t < o1:
                return s0 + (t - o0) * rate
        o0, o1, s0, rate = table[-1]
        return s0 + (o1 - o0) * rate

    def to_out(s: float) -> float:  # 端末の時刻 → 出力の時刻（使わない区間なら、次に使う区間の頭）
        for o0, o1, s0, rate in table:
            s1 = s0 + (o1 - o0) * rate
            if s < s1:
                return o0 + max(0.0, s - s0) / rate
        return table[-1][1]

    return to_term, to_out, out_t


def session_segment(name: str, label: str, title: str, video: Path, fast: list[tuple[float, float]],
                    subs: Callable[[dict], list[tuple[float, float, str]]]) -> Segment:
    """端末（左）とロボット映像（右）。起動とモデルの読み込みは省き、長い待ち時間は早送りする。"""
    cues = json.loads(video.with_suffix(".cues.json").read_text())
    keep = [(0.0, cues["command_end"] + 0.8), (cues["load_start"], cues["load_start"] + 1.5),
            (cues["loaded"] - 0.2, cues["end"] + 1.2)]
    pieces = []
    for t0, t1 in keep:  # 早送りする区間で分ける
        cuts = sorted([(a, b) for a, b in fast if t0 < a < b < t1])
        for a, b in cuts:
            pieces += [(t0, a, 1.0), (a, b, 4.0)]
            t0 = b
        pieces.append((t0, t1, 1.0))
    to_term, to_out, duration = time_map(pieces)

    term = Stream(video, TERM_BOX[2:])
    clips = [Stream(run["clip"], ROBOT_BOX[2:]) for run in cues["runs"]]
    starts = [run["start"] for run in cues["runs"]]
    base = background(label, title)
    waiting = placeholder(ROBOT_BOX, "ロボットの映像（実行すると表示）")

    def draw(t: float) -> Image.Image:
        s = to_term(t)
        img = base.copy()
        img.paste(term.at(s), TERM_BOX[:2])
        started = [i for i, st in enumerate(starts) if s >= st]
        robot = clips[started[-1]].at(t - to_out(starts[started[-1]])) if started else waiting
        img.paste(robot, ROBOT_BOX[:2])
        return img

    chips = [(to_out(cues["command_end"] + 0.8) - 0.01, to_out(cues["command_end"] + 0.8) + 1.4, "起動中…"),
             (to_out(cues["loaded"] - 0.2) - 0.01, to_out(cues["loaded"] - 0.2) + 2.5,
              f"起動とモデルの読み込み（約 {cues['loaded'] - cues['command_end']:.0f} 秒）を省略")]
    chips += [(to_out(a), to_out(b), "4 倍速で早送り") for a, b in fast]
    out_subs = [(to_out(a), to_out(b), text) for a, b, text in subs(cues)]
    return Segment(name, duration, draw, out_subs, chips)


def side_by_side(name: str, label: str, title: str, left: Path, right: Path, captions: tuple[str, str],
                 duration: float, subs, delay: float = 0.6, timer: Path | None = None) -> Segment:
    """2 本のロボット映像を並べて同時に再生する。timer を渡すと、その映像の経過時間（シミュレーション内）を出す。"""
    size = (540, 612)  # 480×544 の 1.125 倍
    gap = 140
    x0 = (W - 2 * size[0] - gap) // 2
    y0 = 175
    streams = [Stream(left, size), Stream(right, size)]
    base = background(label, title)
    d = ImageDraw.Draw(base)
    for i, text in enumerate(captions):
        d.text((x0 + i * (size[0] + gap) + size[0] / 2, y0 - 22), text, font=font(32), fill=INK2, anchor="ms")

    def draw(t: float) -> Image.Image:
        img = base.copy()
        for i, st in enumerate(streams):
            img.paste(st.at(t - delay), (x0 + i * (size[0] + gap), y0))
        if timer is not None:
            st = streams[1]
            moving = (st.n - 1 - round(1.5 * st.fps)) / st.fps  # save_video は最後のコマを 1.5 秒止めるので、その手前まで数える
            sim_t = max(0.0, min(t - delay, moving)) * 0.5  # 映像は 0.5 倍速
            ImageDraw.Draw(img).text((W / 2, y0 + size[1] + 42), f"シミュレーション内の経過時間　{sim_t:4.1f} 秒",
                                     font=font(30), fill=INK2, anchor="mm")
        return img

    return Segment(name, duration, draw, subs)


# ---------- 絵だけの場面 ----------

def still(name: str, img: Image.Image, duration: float, subs=()) -> Segment:
    return Segment(name, duration, lambda t: img, list(subs))


def title_card() -> Image.Image:
    img = background()
    centered_text(img, 360, "その指示、ほんとうに聞いてる？", 96)
    centered_text(img, 520, "M1 Mac で動く VLA（SmolVLA × Meta-World）に日本語で指示を出し、\n言葉の効き目を確かめる",
                  40, INK2, bold=False, spacing=20)
    centered_text(img, 720, "画像と指示文からロボットの動きを出すモデル（VLA）は、本当に「言葉」を見ているのか", 30, MUTED,
                  bold=False)
    return img


def question_card() -> Image.Image:
    img = background("問い", "見た目が同じ作業と、見た目で分かる作業")
    d = ImageDraw.Draw(img)
    rows = [
        (("faucet-open-v3", "蛇口を開ける"), ("faucet-close-v3", "蛇口を閉める"),
         "見た目がほぼ同じ", "どちらの作業かは、指示文でしか分からない"),
        (("drawer-open-v3", "引き出しを開ける"), ("drawer-close-v3", "引き出しを閉める"),
         "見た目で分かる", "引き出しの状態を見れば、やることが決まる"),
    ]
    side, y = 330, 140
    for left, right, head, body in rows:
        for i, (scene, text) in enumerate((left, right)):
            x = MARGIN + 40 + i * (side + 30)
            pic = Image.open(VIDEO_DIR / "clips" / f"scene_{scene}.png").resize((side, side), Image.LANCZOS)
            img.paste(pic, (x, y))
            d.text((x + side / 2, y + side + 12), text, font=font(28), fill=INK2, anchor="ma")
        tx = MARGIN + 40 + 2 * (side + 30) + 40
        d.text((tx, y + 110), head, font=font(48), fill=INK)
        d.text((tx, y + 185), body, font=font(32, bold=False), fill=INK2)
        y += side + 70
    return img


def figure_slide(label: str, title: str, fig: str, max_h: int = 800) -> Image.Image:
    img = background(label, title)
    card = figure_card(FIG_DIR / fig, W - 2 * MARGIN, max_h)
    img.paste(card, ((W - card.width) // 2, 110 + (810 - card.height) // 2))  # 見出しと字幕のあいだの中央
    return img


def summary_card() -> Image.Image:
    img = background("まとめ", "分かったこと")
    d = ImageDraw.Draw(img)
    points = [
        ("言葉は効いている", "指示文を入れ替えると、どの作業も最初の約 2 秒では 1 回も成功しない。\n蛇口では、指示と逆向きにハンドルを回した回が 160 回中 0"),
        ("ただし英語の定型文に強く依存", "言い換えや日本語のままだと失敗が増える（引き出し：日本語のまま 0/20）"),
        ("日本語ルーターと「断る」設計が有効", "日本語 → 英語の定型文に直すと成績が戻る。分からない指示は実行しない"),
    ]
    y = 170
    for i, (head, body) in enumerate(points, start=1):
        d.ellipse([MARGIN + 20, y + 4, MARGIN + 76, y + 60], fill=ACCENT)
        d.text((MARGIN + 48, y + 32), str(i), font=font(32), fill=INK, anchor="mm")
        d.text((MARGIN + 110, y), head, font=font(46), fill=INK)
        d.multiline_text((MARGIN + 110, y + 70), body, font=font(32, bold=False), fill=INK2, spacing=12)
        y += 190 if "\n" not in body else 230
    d.line([MARGIN, y + 10, W - MARGIN, y + 10], fill=(50, 56, 66), width=2)
    d.text((MARGIN + 20, y + 40), "限界：シミュレータのみ・1 つのモデル・各条件 20 回　／　次：言い換えデータでの追加学習、実機（SO-101 など）",
           font=font(28, bold=False), fill=MUTED)
    return img


def end_card() -> Image.Image:
    img = background()
    centered_text(img, 380, "コードとレポートは GitHub で公開しています（説明欄のリンク）", 44)
    centered_text(img, 500, "使用：SmolVLA（lerobot/smolvla_metaworld）・LeRobot・Meta-World・MuJoCo\n"
                            "実行環境：Apple M1 の Mac（MPS）・uv（Docker なし）・推論のみ（追加学習なし）",
                  30, INK2, bold=False, spacing=18)
    return img


# ---------- 絵コンテ ----------

def storyboard(session_a: Path, session_b: Path) -> list[Segment]:
    clips = VIDEO_DIR / "clips"
    b_cues = json.loads(session_b.with_suffix(".cues.json").read_text())
    b_open, b_close = b_cues["runs"][0], b_cues["runs"][1]

    def subs_a(c):
        r = c["runs"]
        return [
            (0.0, c["command_end"] + 0.8, "ターミナルで対話デモを起動する（ロボットの映像は 0.5 倍速）"),
            (c["loaded"], r[0]["start"], "日本語で指示を入力する"),
            (r[0]["start"], r[0]["result"] + 1.5, "ルーターが日本語を英語の定型文に直し、VLA に渡す"),
            (c["refusals"][0]["time"] - 2.0, c["refusals"][0]["time"] + 2.5, "何をすればよいか分からない指示は、実行せずに断る"),
            (r[1]["start"] - 0.5, c["end"] + 1.2, "引き出しも窓も、同じ 1 つのモデルが指示に合わせて動かす"),
        ]

    def subs_b(c):
        r = c["runs"]
        return [
            (0.0, r[0]["start"], "次は、シーンを「蛇口を閉める」に固定して、言葉だけを変える"),
            (r[0]["start"], r[0]["result"] + 0.5, "「開けて」→ ハンドルを開ける向き（反時計回り）に回す\n（シーンの基準は「閉める」なので、判定は失敗）"),
            (r[1]["start"] - 1.0, c["end"] + 1.2, "「閉めて」→ 閉める向き（時計回り）に回して成功"),
        ]

    fast_b = [(b_open["start"] + 1.5, b_open["result"] - 0.6)]  # 500 ステップ回し切る 12 秒の待ち時間
    return [
        still("タイトル", title_card(), 6.0),
        still("問い", question_card(), 10.0, [
            (0.3, 5.0, "VLA は、カメラ画像と指示文からロボットの動きを出すモデル"),
            (5.0, 9.8, "見た目が同じ蛇口と、見た目で分かる引き出し。\n指示文だけを入れ替えたら、ロボットはどう動く？"),
        ]),
        session_segment("対話デモ", "デモ 1", "日本語で指示する", session_a, [], subs_a),
        session_segment("見せ場", "デモ 2", "同じシーンで、言葉だけを変える", session_b, fast_b, subs_b),
        side_by_side("見せ場（並べて再生）", "デモ 2", "同じシーン・同じ配置、違うのは言葉だけ",
                     Path(b_open["clip"]), Path(b_close["clip"]), ("「蛇口を開けて」", "「蛇口を閉めて」"), 7.5,
                     [(0.3, 7.3, "言葉に従って、ハンドルを逆向きに回している")]),
        still("入れ替えテスト", figure_slide("実験 1", "指示文の入れ替えテスト（各セル 20 回）", "fig1_swap_heatmap.png", 600), 11.0, [
            (0.3, 5.5, "シーンはそのままで、組の相手（開ける ⇔ 閉める）の定型文を渡す"),
            (5.5, 10.8, "蛇口は入れ替えると 0/20。\n指示と逆向きにハンドルを回した回は 160 回中 0"),
        ]),
        side_by_side("引き出しの入れ替え", "実験 1", "引き出し：入れ替えても、最後は閉めてしまう",
                     clips / "drawer_reference.mp4", clips / "drawer_swapped.mp4",
                     ("本来の定型文「閉めて」", "入れ替えた定型文「開けて」"), 10.0, [
                         (0.3, 5.0, "左は約 1 秒で閉める。右は「開けて」と言われ、しばらく迷う"),
                         (5.0, 9.8, "最後は見た目どおり閉めてしまうが、約 3 倍の時間がかかる\n（20 回中 12 回。最初の 2 秒で閉めた回は 0）"),
                     ], timer=clips / "drawer_swapped.mp4"),
        still("言い方", figure_slide("実験 2", "指示文の言い方を変える（各 20 回）", "fig4_wording.png", 680), 10.0, [
            (0.3, 5.0, "日本語のまま渡すと、成功率が大きく下がる\n（蛇口 17 → 5、引き出し 20 → 0）"),
            (5.0, 9.8, "ルーターで英語の定型文に直すと元に戻る。言い換えにも弱い"),
        ]),
        still("まとめ", summary_card(), 14.0),
        still("おわり", end_card(), 5.0),
    ]


# ---------- 書き出し ----------

def render_frame(seg: Segment, t: float) -> Image.Image:
    img = seg.draw(t).convert("RGBA")
    for t0, t1, text in seg.chips:
        if t0 <= t < t1:
            img.alpha_composite(chip_overlay(text))
    for t0, t1, text in seg.subs:
        if t0 <= t < t1:
            img.alpha_composite(subtitle_overlay(text))
    img = img.convert("RGB")
    fade = min(1.0, t / FADE, (seg.duration - t) / FADE)
    if fade < 1.0:
        img = Image.blend(Image.new("RGB", img.size, (0, 0, 0)), img, max(fade, 0.0))
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description="デモ動画を組み立てる")
    ap.add_argument("--session-a", type=Path, default=VIDEO_DIR / "session_a.mp4", help="対話デモの端末の動画")
    ap.add_argument("--session-b", type=Path, default=VIDEO_DIR / "session_b.mp4", help="見せ場の端末の動画")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--preview", type=float, nargs="*", help="この秒数のコマだけを PNG で書き出す")
    ap.add_argument("--list", action="store_true", help="場面ごとの開始時刻を表示する")
    args = ap.parse_args()

    segments = storyboard(args.session_a, args.session_b)
    starts = np.cumsum([0.0] + [s.duration for s in segments])
    if args.list or args.preview is None:
        for seg, st in zip(segments, starts):
            print(f"{int(st // 60)}:{st % 60:04.1f}  {seg.name}（{seg.duration:.1f} 秒）")
        print(f"合計 {starts[-1]:.1f} 秒")
        if args.list:
            return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.preview is not None:
        for t in args.preview:
            i = int(np.searchsorted(starts, t, side="right")) - 1
            path = args.out.with_name(f"preview_{t:05.1f}.png")
            render_frame(segments[i], t - starts[i]).save(path)
            print(path)
        return

    writer = imageio.get_writer(args.out, fps=FPS, quality=8, macro_block_size=8)  # 1080 は 16 の倍数でないので 8
    for seg in segments:
        for k in range(int(round(seg.duration * FPS))):
            writer.append_data(np.asarray(render_frame(seg, k / FPS)))
    writer.close()
    print(f"書き出しました：{args.out}（{starts[-1]:.1f} 秒）")


if __name__ == "__main__":
    main()
