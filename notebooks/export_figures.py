"""分析ノートブックの図を、レポート用の PNG に書き出す。

  uv run python notebooks/export_figures.py

analysis.py を既定の設定（K = 500 ステップ、θ = 0.3 rad）で実行し、できた図の体裁だけをレポート向けに整えて
docs/figures/ に保存する。幅 900 px の図を A4 縦の本文幅（約 16 cm）に置くと、1 px ≒ 0.5 pt になる。
PNG の書き出しには kaleido を使う（Mac に入っている Google Chrome で描画する）。
"""
from __future__ import annotations

from pathlib import Path

from analysis import app  # 同じフォルダの marimo ノートブック

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
WIDTH = 900  # px
SCALE = 2  # 解像度を 2 倍にして、印刷でもにじまないようにする
# 出力名 → (ノートブックの変数名, 高さ px, 上の余白 px)
FIGURES = {
    "fig1_swap_heatmap": ("fig_swap", 290, 40),
    "fig2_success_curves": ("fig_curve", 640, 80),
    "fig3_knob_angle": ("fig_knob", 600, 40),
    "fig4_wording": ("fig_wording", 360, 40),
}


def main() -> None:
    _, defs = app.run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (var, height, top) in FIGURES.items():
        fig = defs[var]
        # 図のタイトルはレポートのキャプションに書くので消す。背景は紙に合わせて白にする
        fig.update_layout(title_text="", width=WIDTH, height=height, margin_t=top, font_size=16,
                          paper_bgcolor="white", plot_bgcolor="white")
        fig.update_xaxes(tickfont_size=14, title_font_size=15)
        fig.update_yaxes(tickfont_size=14, title_font_size=15)
        # 注釈は 2 種類：サブプロットの見出しと、図中の小さなラベル（ノートブックでは 11 px）
        fig.for_each_annotation(lambda a: a.update(font_size=13 if a.font.size == 11 else 16))
        fig.update_traces(textfont_size=20, selector=dict(type="heatmap"))
        fig.update_traces(textfont_size=14, selector=dict(mode="text"))
        path = OUT_DIR / f"{name}.png"
        fig.write_image(path, scale=SCALE)
        print(f"{path}（{WIDTH * SCALE}×{height * SCALE} px）")


if __name__ == "__main__":
    main()
