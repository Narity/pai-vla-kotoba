import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="VLA は指示文を聞いているか")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from scipy.stats import binomtest, fisher_exact

    return binomtest, fisher_exact, go, make_subplots, mo, np, pd


@app.cell
def _(mo):
    mo.md(r"""
    # VLA は指示文を聞いているか：N=20 本番実験の分析

    SmolVLA（`lerobot/smolvla_metaworld`）を Meta-World で動かし、**指示文を入れ替えたり言い方を変えたりして**成功率を比べた実験（`kotoba_vla.experiment`、2026-10-29 実行、全 560 話）の分析です。

    **このノートブックが読むファイル**（コピーせず、そのまま読みます）

    | パス | 中身 |
    |:---|:---|
    | `results/episodes.csv` | 1 話 1 行の記録（シーン・指示文・seed・成否・ステップ数・ハンドル角など）。集計はすべてここから計算し直します |
    | `results/summary.csv` | `experiment.py` が出した条件ごとの集計。ここでは「どの条件がどの実験に属するか」の対応表としてだけ使います |

    **関連ファイル**

    | パス | 中身 |
    |:---|:---|
    | `notebooks/analysis.py` | このノートブック（marimo） |
    | `notebooks/analysis.html` | 静的 HTML 版（ウィジェットは動きませんが、図のホバー・拡大はできます） |
    | `src/kotoba_vla/experiment.py` | 実験の条件定義と実行・集計 |
    | `src/kotoba_vla/episode.py` | 1 話の実行（成否・ハンドル角の記録方法） |
    | `outputs/experiment/*.mp4` | 各条件の seed 0 の動画（Git には含めません） |
    | `notebooks/export_figures.py` | このノートブックの図をレポート用の PNG に書き出すスクリプト（`uv run python notebooks/export_figures.py`） |
    | `docs/figures/*.png` | 書き出した図（K = 500、θ = 0.3 rad の設定） |

    **開き方**：`uv run marimo edit notebooks/analysis.py`（読むだけなら `uv run marimo run notebooks/analysis.py`）。
    静的 HTML の書き出しは `uv run marimo export html notebooks/analysis.py -o notebooks/analysis.html` です。
    """)
    return


@app.cell
def _(pd):
    # 色と体裁。系列の色は 2 色だけ：本来の定型文＝青、入れ替えた定型文＝橙（色覚多様性の検証済み）
    color = {
        "ref": "#2a78d6", "swap": "#eb6834",
        "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "surface": "#fcfcfb",
    }
    blue_scale = [[0, "#cde2fb"], [0.25, "#86b6ef"], [0.5, "#3987e5"], [0.75, "#1c5cab"], [1, "#0d366b"]]
    base_layout = dict(
        font=dict(family="'Hiragino Sans', 'Hiragino Kaku Gothic ProN', system-ui, sans-serif", size=13, color=color["ink"]),
        paper_bgcolor=color["surface"], plot_bgcolor=color["surface"],
    )
    axis_style = dict(
        showline=True, linecolor=color["axis"], gridcolor=color["grid"], zerolinecolor=color["axis"],
        tickfont=dict(color=color["ink2"]),
    )
    task_ja = {
        "faucet-open-v3": "蛇口を開ける", "faucet-close-v3": "蛇口を閉める",
        "drawer-open-v3": "引き出しを開ける", "drawer-close-v3": "引き出しを閉める",
        "window-open-v3": "窓を開ける", "window-close-v3": "窓を閉める",
    }
    verb_ja = {"open": "開ける", "close": "閉める"}

    def fmt_p(p):
        """p 値の表示（検定しない条件は —）。"""
        if pd.isna(p):
            return "—"
        return "<0.001" if p < 0.001 else f"{p:.3f}"

    def quote(s):
        """指示文の表示（空文字は空文字と分かるように）。"""
        return f"“{s}”" if s else "“”（空文字）"

    def p_text(p):
        """文中での p 値の表示（p<0.001／p=0.047）。"""
        return f"p{fmt_p(p)}" if fmt_p(p).startswith("<") else f"p={fmt_p(p)}"

    return (
        axis_style,
        base_layout,
        blue_scale,
        color,
        fmt_p,
        p_text,
        quote,
        task_ja,
        verb_ja,
    )


@app.cell
def _(mo, pd):
    results_dir = mo.notebook_dir().parent / "results"
    episodes = pd.read_csv(results_dir / "episodes.csv", keep_default_na=False)  # 空文字の指示文を NaN にしない
    episodes["knob"] = pd.to_numeric(episodes["knob"], errors="coerce")  # 蛇口以外は空欄 → NaN
    conditions = pd.read_csv(results_dir / "summary.csv", keep_default_na=False)[
        ["exp", "group", "scene", "label", "instruction", "hide_markers"]
    ]
    # 条件 × seed → 1 話。同じシーン・同じ文・同じ印の有無の条件は、同じ話を共有する
    runs = conditions.merge(episodes, on=["scene", "instruction", "hide_markers"], how="left")
    return conditions, episodes, runs


@app.cell
def _(conditions, episodes, mo, runs):
    _per_cond = runs.groupby(["exp", "scene", "label"]).size()
    mo.vstack([
        mo.md(f"""
    ## 0. データの確認

    - 記録された話：**{len(episodes)} 話**（シーン × 指示文 × ゴール印の有無 × seed の組み合わせに重複なし）
    - 条件：**{len(conditions)} 個**（実験 1：{(conditions.exp == 1).sum()}、実験 2：{(conditions.exp == 2).sum()}、実験 3：{(conditions.exp == 3).sum()}）
    - 1 条件あたり {_per_cond.min()}〜{_per_cond.max()} 話（seed {runs.seed.min()}〜{runs.seed.max()}）。欠けた話：{runs.success.isna().sum()} 話
    - 条件 × seed にすると {len(runs)} 行です。{len(episodes)} 話より多いのは、実験 2 の「定型文」が実験 1 の本来の定型文と、「ルーター経由」が「定型文」と、同じ話を共有しているためです。

    下の表は 1 話 1 行の生データです（列名をクリックすると並べ替えられます）。
    """),
        episodes,
    ])
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### 用語

    | 用語 | 定義 |
    |:---|:---|
    | シーン | Meta-World のタスク（例：`faucet-open-v3`）。物の初期状態と、**成功判定の基準**が決まる |
    | 定型文 | 学習データで各タスクに付いていた英語の指示文（例：“Rotate the faucet counter-clockwise”）。LeRobot の `TASK_DESCRIPTIONS` |
    | 本来の定型文／入れ替えた定型文 | シーンと同じタスクの定型文／組の相手（開ける ⇔ 閉める）の定型文 |
    | 成功 | 500 ステップ以内に Meta-World の成功判定が立ったか。判定は**シーンの作業**が基準（指示文の内容ではない） |
    | ステップ | 制御の 1 刻み。80 Hz なので 80 ステップ＝1 秒、500 ステップ＝6.25 秒。成功した話は成功した時点のステップ、失敗した話は 500 |
    | 打ち切りステップ K | このノートブックの設定。「K ステップ以内に成功した話」だけを成功と数える（既定 500＝実験と同じ） |
    | ハンドル角 | 蛇口のハンドル関節 `knob_Joint_1` の角度 [rad]。1 話の中で絶対値が最大になったときの値。**＋が開ける向き**（反時計回り） |
    | しきい値 θ | このノートブックの設定。ハンドル角が ＋θ を超えたら「開ける向きに回した」、−θ 未満なら「閉める向きに回した」と数える（既定 0.3 rad ≒ 17°） |
    | ゴール印 | シーンに描かれた目標位置の印（`goal_open` 緑・`goal_close` 青）。蛇口の 2 シーンでは奥行きが 5 cm 入れ替わる。実験 3 では透明にした |
    | seed | 物の初期配置と方策の乱数を決める番号（0〜19）。同じ seed なら毎回まったく同じ結果になる |
    | 95% 信頼区間 | 成功率の Wilson 区間 |
    | p（Fisher） | 同じシーンで本来の定型文を渡した条件との、成功数の差の Fisher の正確確率検定（両側） |
    | p（McNemar） | 同じ seed どうしを対にした検定（正確二項検定、両側）。成否が分かれた対だけを使う |
    | Holm 補正 | このノートブックで行う検定すべてをまとめて多重比較の補正をした p |
    """)
    return


@app.cell
def _(binomtest, mo):
    _ci75 = binomtest(15, 20).proportion_ci(method="wilson")
    _ci50 = binomtest(10, 20).proportion_ci(method="wilson")
    mo.md(f"""
    ### 統計的な注意点

    - **20 話は「20 通りの配置」です。** 同じ seed なら MPS でも完全に同じ結果になります。ばらつきは物の配置と方策の乱数（どちらも seed で決まる）だけから来るので、同じ条件を回し直しても情報は増えません。
    - **条件どうしは対応があります。** 全条件で seed 0〜19 を共通に使っているので、同じ seed の話は同じ配置です。Fisher の検定は独立な 2 群を仮定するため、対応を使う McNemar の検定も並べます。
    - **N=20 は小さいです。** 成功率 75%（15/20）の 95% 信頼区間は {_ci75.low:.0%}〜{_ci75.high:.0%}、50%（10/20）では {_ci50.low:.0%}〜{_ci50.high:.0%} です。差が 20 ポイント程度だと検出できません。
    - **多重比較**：検定は 20 本あります（§4 の表）。Holm 補正後の p も載せます。
    - **ルーター経由は独立した証拠ではありません。** ルーターが出す文は定型文そのもので、実行も決定的なので、定型文の条件と同じ話を共有しています（検定しません）。言えるのは「日本語をそのまま渡したときの成績が、ルーターを通すと定型文の成績まで戻る」ことです。
    - **成功判定はシーンが基準です。** 蛇口を閉めるシーンに「開ける」文を渡すと、言葉どおりに開けても失敗になります。言葉に従ったかどうかは、ハンドル角で見ます（§2）。
    - **基準の成功率が低い条件があります。** 窓を開けるシーンは本来の定型文でも 6/20、蛇口を閉めるシーンは 5/20 です。この 2 つの行では、入れ替えの効果を成功率から判定しにくいです。
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### 仮説と根拠

    | 仮説 | 内容 | 根拠（なぜそう考えたか） |
    |:---|:---|:---|
    | H1 | 見た目で区別できる組（引き出し・窓）では、VLA は指示文を**無視しても**成功してしまう | これらのシーンは初期画像だけで作業が決まる（引き出しが開いていれば、やることは「閉める」しかない）。学習データでは画像と指示が常に一致していたので、方策は言葉を使わずに画像だけで行動を決める近道を覚えているかもしれない |
    | H2 | 見た目が同じ組（蛇口）では、指示文を入れ替えると成功率が大きく下がる（言葉を使っている） | faucet-open と faucet-close の初期画像はほぼ同じ（違いは置き場所の範囲とゴール印の奥行きだけ）。画像から作業が決まらないので、正しく動くには言葉を使うしかない |
    | H3 | 日本語の文をそのまま渡すと失敗が増える | 学習時の指示文は英語の定型文だけ。言語モデル部（SmolVLM2）が日本語をある程度読めても、行動との対応は英語の定型文でしか学んでいない |
    | 実験 3 の問い | 蛇口で効いているのは、言葉ではなくゴール印では？ | 予備実験で、蛇口の 2 シーンはゴール印の奥行きが 5 cm 入れ替わると分かった。方策がこの印を手がかりに向きを決めている可能性を、印を消して確かめる |

    分析の過程で浮かんだ新しい仮説は、末尾（§6）にまとめます。
    """)
    return


@app.cell
def _(mo):
    k_slider = mo.ui.slider(
        50, 500, step=10, value=500, show_value=True,
        label="打ち切りステップ K（この数以内に成功した話だけを成功と数える）",
    )
    theta_slider = mo.ui.slider(
        0.05, 1.5, step=0.05, value=0.3, show_value=True,
        label="ハンドル角のしきい値 θ [rad]（これを超えて回したら「回した」と数える）",
    )
    return k_slider, theta_slider


@app.cell
def _(binomtest, fisher_exact, k_slider, np, runs):
    k = k_slider.value
    runs_k = runs.assign(ok=(runs["success"] == 1) & (runs["steps"] <= k))
    stats = (
        runs_k.groupby(["exp", "group", "scene", "label", "instruction", "hide_markers"], sort=False)
        .agg(n=("ok", "size"), success=("ok", "sum"))
        .reset_index()
    )
    stats["rate"] = stats["success"] / stats["n"]
    # 比較相手：同じ実験・同じシーンで本来の定型文を渡した条件（実験 2 では label が「定型文」）
    stats["ref_label"] = np.where(stats["exp"] == 2, "定型文", stats["scene"])
    stats["is_reference"] = stats["label"] == stats["ref_label"]
    _ok_by_seed = runs_k.sort_values("seed").groupby(["exp", "scene", "label"])["ok"].apply(lambda s: s.to_numpy())
    _ci_lo, _ci_hi, _p_fisher, _p_mcnemar = [], [], [], []
    for _r in stats.itertuples():
        _ci = binomtest(int(_r.success), int(_r.n)).proportion_ci(method="wilson")
        _ci_lo.append(_ci.low)
        _ci_hi.append(_ci.high)
        _ref = stats[(stats.exp == _r.exp) & (stats.scene == _r.scene) & stats.is_reference].iloc[0]
        if _r.instruction == _ref.instruction:  # 本来の定型文そのもの・ルーター経由（同じ話）は検定しない
            _p_fisher.append(np.nan)
            _p_mcnemar.append(np.nan)
            continue
        _table = [[_r.success, _r.n - _r.success], [_ref.success, _ref.n - _ref.success]]
        _p_fisher.append(fisher_exact(_table).pvalue)
        _a = _ok_by_seed[(_r.exp, _r.scene, _r.label)]
        _b = _ok_by_seed[(_r.exp, _r.scene, _ref.label)]
        _n10, _n01 = int((_a & ~_b).sum()), int((~_a & _b).sum())  # 同じ seed で成否が分かれた対
        _p_mcnemar.append(binomtest(_n10, _n10 + _n01).pvalue if _n10 + _n01 else 1.0)
    stats["ci_lo"], stats["ci_hi"] = _ci_lo, _ci_hi
    stats["p_fisher"], stats["p_mcnemar"] = _p_fisher, _p_mcnemar
    # Holm 補正：p を小さい順に並べ、(検定数 − 順位) 倍して単調にそろえる
    for _col in ("fisher", "mcnemar"):
        _p = stats[f"p_{_col}"].dropna().sort_values()
        _adj = np.maximum.accumulate((len(_p) - np.arange(len(_p))) * _p.to_numpy()).clip(max=1)
        stats.loc[_p.index, f"holm_{_col}"] = _adj
    return k, stats


@app.cell
def _(k_slider, mo):
    mo.vstack([
        mo.md(r"""
    ## 1. 実験 1・3：指示文の入れ替え

    蛇口・引き出し・窓の 3 組それぞれで、**シーン（行）× 渡す定型文（列）** を総当たりにしました（各セル 20 話）。
    左上と右下が本来の定型文、右上と左下が入れ替えです。実験 3 は、蛇口の 2 シーンからゴール印を消して同じことをしたものです。

    - **対角が高く、非対角が低い** → 言葉を聞いている
    - **非対角も高い** → 見た目だけで作業を決めている

    下のスライダーで K を縮めると、「K ステップ以内の成功」だけを数え直します（§1.2・§3・§4 のスライダーと連動）。
    """),
        k_slider,
    ])
    return


@app.cell
def _(
    axis_style,
    base_layout,
    blue_scale,
    fmt_p,
    go,
    k,
    make_subplots,
    quote,
    stats,
    task_ja,
    verb_ja,
):
    _panels = [(1, "faucet", "蛇口"), (3, "faucet", "蛇口（ゴール印なし）"), (1, "drawer", "引き出し"), (1, "window", "窓")]
    fig_swap = make_subplots(rows=1, cols=4, subplot_titles=[_t for _, _, _t in _panels], horizontal_spacing=0.05)
    for _i, (_exp, _group, _title) in enumerate(_panels, start=1):
        _s = stats[(stats.exp == _exp) & (stats.group == _group)].set_index(["scene", "label"])
        _tasks = [f"{_group}-open-v3", f"{_group}-close-v3"]
        _z, _text, _hover = [], [], []
        for _scene in _tasks:
            _cells = [_s.loc[(_scene, _t)] for _t in _tasks]
            _z.append([_c["rate"] for _c in _cells])
            _text.append([f"{_c['success']}/{_c['n']}" for _c in _cells])
            _hover.append([
                f"シーン：{task_ja[_scene]}<br>渡した文：{quote(_c['instruction'])}<br>"
                f"成功：{_c['success']}/{_c['n']}（{_c['rate']:.0%}、95% 信頼区間 {_c['ci_lo']:.0%}〜{_c['ci_hi']:.0%}）<br>"
                f"本来の定型文との差：p（Fisher）{fmt_p(_c['p_fisher'])}、p（McNemar）{fmt_p(_c['p_mcnemar'])}"
                for _c in _cells
            ])
        fig_swap.add_trace(go.Heatmap(
            z=_z, x=[verb_ja["open"], verb_ja["close"]], y=[verb_ja["open"], verb_ja["close"]],
            text=_text, texttemplate="%{text}", textfont=dict(size=17),
            customdata=_hover, hovertemplate="%{customdata}<extra></extra>",
            zmin=0, zmax=1, colorscale=blue_scale, xgap=3, ygap=3,
            showscale=_i == len(_panels),
            colorbar=dict(tickformat=".0%", thickness=12, len=0.85),
        ), row=1, col=_i)
    fig_swap.update_xaxes(**axis_style, showgrid=False, side="bottom", tickangle=0, title_text="渡した定型文")
    fig_swap.update_yaxes(**axis_style, showgrid=False, autorange="reversed")
    fig_swap.update_yaxes(title_text="シーン", col=1)
    fig_swap.update_yaxes(showticklabels=False, col=2)
    fig_swap.update_yaxes(showticklabels=False, col=3)
    fig_swap.update_yaxes(showticklabels=False, col=4)
    fig_swap.update_layout(
        **base_layout, height=360, margin=dict(t=70, b=50, l=70, r=30),
        title=dict(text=f"数字＝成功数 / 20、色＝成功率（K = {k} ステップ以内）　行＝シーン、列＝渡した定型文", x=0, font=dict(size=15)),
    )
    fig_swap
    return


@app.cell
def _(k, mo, p_text, runs, stats):
    _names = {(1, "faucet"): "蛇口", (3, "faucet"): "蛇口（印なし）", (1, "drawer"): "引き出し", (1, "window"): "窓"}
    _lines = []
    for (_e, _g), _name in _names.items():
        _s = stats[(stats.exp == _e) & (stats.group == _g)].sort_values("scene", ascending=False)  # 開ける → 閉めるの順
        _ref, _swp = _s[_s.is_reference], _s[~_s.is_reference]
        _lines.append(
            f"- **{_name}**：本来の定型文 " + "・".join(f"{_r.success}/{_r.n}" for _r in _ref.itertuples())
            + " → 入れ替え " + "・".join(f"{_r.success}/{_r.n}（{p_text(_r.p_fisher)}）" for _r in _swp.itertuples())
        )
    _sw = runs[runs.exp.isin([1, 3]) & (runs.label != runs.scene)]
    _dg = runs[runs.exp.isin([1, 3]) & (runs.label == runs.scene)]
    _trend = ["| K（ステップ） | " + " | ".join(_names.values()) + " |", "|:---" * (len(_names) + 1) + "|"]
    for _k in (100, 150, 200, 300, 500):
        _cells = []
        for _e, _g in _names:
            _d = _dg[(_dg.exp == _e) & (_dg.group == _g)]
            _w = _sw[(_sw.exp == _e) & (_sw.group == _g)]
            _cells.append(f"{((_d.success == 1) & (_d.steps <= _k)).sum()} → {((_w.success == 1) & (_w.steps <= _k)).sum()}")
        _trend.append(f"| {_k}（{_k / 80:.1f} 秒） | " + " | ".join(_cells) + " |")
    _nl = "\n"
    mo.md(f"""
    **分析方法**：行＝シーン（成功判定の基準）、列＝渡した定型文。セルの数字は「K ステップ以内に成功した話数 / 20」、色は成功率です。
    p は同じ行の本来の定型文との Fisher の検定（両側）で、ホバーすると McNemar の p と信頼区間も出ます。

    **現在の設定（K = {k}）**：成功数は「開けるシーン・閉めるシーン」の順

    {_nl.join(_lines)}

    **K を振ったときの成功数**（各組 40 話中。「本来の定型文 → 入れ替え」）

    {_nl.join(_trend)}

    **示唆**

    - **蛇口（H2 を支持）**：入れ替えると、どの K でも 0 です。見た目がほぼ同じシーンでは、方策は言葉で作業を決めています。ゴール印を消しても 0 のままなので、入れ替えで失敗する理由は印ではありません（向きについては §2）。
    - **引き出し（H1 は部分的）**：K = 500 では入れ替えても 12/20・7/20 がシーンの作業を達成します。ところが **K = 150（約 1.9 秒）で切ると、本来の定型文の成功は 1 話も減らないのに、入れ替えの成功は 0 になります**。入れ替えたときの成功は、すべて時間のかかった「遅い成功」です（§1.2）。
    - **窓**：閉めるシーンに「開ける」文を渡すと 0/20 で、引き出しよりも言葉に強く従います。開けるシーンはもともと 6/20 しか成功しないので、この行からは判断できません。
    - まとめると、H1 の「言葉を無視する」は言いすぎです。**最初の 1〜2 秒は、どの組でも言葉が行動を決めています。** 見た目が勝つのは、時間をかけたあとの引き出しだけです。
    """)
    return


@app.cell
def _(k_slider, mo):
    mo.vstack([
        mo.md(r"""
    ### 1.2 いつ成功したか（実験 1）

    各シーンで、「何ステップ目までに何割の話が成功したか」を線で描きます。青が本来の定型文、橙が入れ替えた定型文です。灰色の縦線は K です。
    """),
        k_slider,
    ])
    return


@app.cell
def _(axis_style, base_layout, color, go, k, make_subplots, np, runs, task_ja):
    _x = np.arange(0, 501)
    _layout = [("faucet", "open"), ("faucet", "close"), ("drawer", "open"), ("drawer", "close"), ("window", "open"), ("window", "close")]
    fig_curve = make_subplots(
        rows=3, cols=2, shared_xaxes=True, shared_yaxes=True, vertical_spacing=0.09, horizontal_spacing=0.17,
        subplot_titles=[f"{task_ja[f'{_g}-{_a}-v3']}シーン" for _g, _a in _layout],
    )
    for _idx, (_g, _a) in enumerate(_layout):
        _row, _col = _idx // 2 + 1, _idx % 2 + 1
        _scene = f"{_g}-{_a}-v3"
        _r1 = runs[(runs.exp == 1) & (runs.scene == _scene)]
        _ends = []
        for _kind, _name, _sel in (("ref", "本来の定型文", _r1.label == _scene), ("swap", "入れ替えた定型文", _r1.label != _scene)):
            _e = _r1[_sel]
            _steps = _e.loc[_e.success == 1, "steps"].to_numpy()
            _y = (_steps[:, None] <= _x).sum(axis=0) / len(_e)
            fig_curve.add_trace(go.Scatter(
                x=_x, y=_y, mode="lines", name=_name, legendgroup=_kind, showlegend=_idx == 0,
                line=dict(color=color[_kind], width=2, shape="hv"),
                hovertemplate=f"{_name}<br>%{{x}} ステップまでに %{{y:.0%}} が成功<extra></extra>",
            ), row=_row, col=_col)
            _ends.append((_name.replace("の定型文", "").replace("た定型文", ""), _y[-1], len(_steps), len(_e)))
        # 線の右端に直接ラベル（2 本が近いときは上下にずらす）
        _close = abs(_ends[0][1] - _ends[1][1]) < 0.12
        for _j, (_label, _yend, _ns, _n) in enumerate(_ends):
            fig_curve.add_annotation(
                x=500, y=_yend, text=f"{_label} {_ns}/{_n}", showarrow=False, xanchor="left", xshift=6,
                yshift=(9 if _j == 0 else -9) if _close else 0, font=dict(size=11, color=color["ink2"]),
                row=_row, col=_col,
            )
    fig_curve.add_vline(x=k, line=dict(color=color["muted"], width=1), row="all", col="all")
    fig_curve.update_xaxes(**axis_style, range=[0, 500], showgrid=False)
    fig_curve.update_xaxes(title_text="ステップ（80 ステップ＝1 秒）", row=3)
    fig_curve.update_yaxes(**axis_style, range=[-0.03, 1.03], tickformat=".0%", dtick=0.5)
    fig_curve.update_yaxes(title_text="成功した割合", col=1)
    fig_curve.update_layout(
        **base_layout, height=660, margin=dict(t=95, b=50, l=70, r=110),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.1, font=dict(color=color["ink2"])),
    )
    fig_curve
    return


@app.cell
def _(k, mo, runs, task_ja):
    _rows = ["| シーン | 本来の定型文：成功数・成功ステップの中央値（最小〜最大） | 入れ替え：成功数・成功ステップの中央値（最小〜最大） | K より後に成功（本来・入れ替え） |", "|:---|:---|:---|:---|"]
    _late = {"ref": 0, "swap": 0}
    for _scene in task_ja:
        _r1 = runs[(runs.exp == 1) & (runs.scene == _scene) & (runs.success == 1)]
        _cells = []
        _late_here = []
        for _kind, _sel in (("ref", _r1.label == _scene), ("swap", _r1.label != _scene)):
            _st = _r1.loc[_sel, "steps"]
            _cells.append(f"{len(_st)} 話・{_st.median():.0f}（{_st.min()}〜{_st.max()}）" if len(_st) else "0 話")
            _late_here.append(int((_st > k).sum()))
            _late[_kind] += int((_st > k).sum())
        _rows.append(f"| {task_ja[_scene]} | {_cells[0]} | {_cells[1]} | {_late_here[0]}・{_late_here[1]} |")
    _nl = "\n"
    mo.md(f"""
    **分析方法**：実験 1 の各条件（20 話）について、成功した話の成功ステップを小さい順に積み上げました（成功しなかった話は 500 まで上がりません）。線が早く立ち上がるほど、早く作業を終えています。

    {_nl.join(_rows)}

    **現在の設定（K = {k}）**：K より後に成功した話は、本来の定型文で {_late['ref']} 話、入れ替えで {_late['swap']} 話です。

    **示唆**

    - 本来の定型文の成功は、どのシーンでも 150 ステップ（約 1.9 秒）以内にほぼ出そろいます。
    - **引き出しで入れ替えたときの成功は、中央値で約 260 ステップ**かかり、本来の定型文（80〜100 ステップ）の約 3 倍です。最も早い話でも 189 ステップです。
    - 「最初は言葉どおりに動こうとし、作業が進まないうちに画像に合わせて動きを切り替える」という解釈と矛盾しません。ただし、この図だけでは「最初は迷っていただけ」と区別できないので、動画か手先位置の時系列で確かめる必要があります（§6）。
    """)
    return


@app.cell
def _(mo, theta_slider):
    mo.vstack([
        mo.md(r"""
    ## 2. 蛇口：ハンドルをどちら向きに回したか（実験 1・3）

    蛇口では「シーンの作業ができたか」だけでは、言葉に従ったかどうかが分かりません（閉めるシーンで言葉どおりに開けると失敗になるため）。
    そこで、1 話の中でハンドルを最も大きく回した角度を見ます。**＋が開ける向き、−が閉める向き**です。灰色の帯（±θ）の中は「ほとんど回していない」とみなします。
    """),
        theta_slider,
    ])
    return


@app.cell
def _(
    axis_style,
    base_layout,
    color,
    go,
    make_subplots,
    np,
    runs,
    theta_slider,
    verb_ja,
):
    theta = round(theta_slider.value, 2)
    faucet_runs = runs[(runs.group == "faucet") & runs.exp.isin([1, 3])].copy()
    faucet_runs["said"] = np.where(faucet_runs.label.str.contains("open"), "open", "close")  # 渡した定型文の向き
    faucet_runs["scene_dir"] = np.where(faucet_runs.scene.str.contains("open"), "open", "close")
    faucet_runs["turned"] = np.select([faucet_runs.knob > theta, faucet_runs.knob < -theta], ["open", "close"], "none")
    faucet_runs["against"] = (faucet_runs.turned != "none") & (faucet_runs.turned != faucet_runs.said)

    _cats = [("open", "open"), ("open", "close"), ("close", "open"), ("close", "close")]  # (渡した文, シーン)
    fig_knob = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                             subplot_titles=["ゴール印あり（実験 1）", "ゴール印なし（実験 3）"])
    for _row, _exp in enumerate((1, 3), start=1):
        _f = faucet_runs[faucet_runs.exp == _exp]
        for _ci, (_said, _scene) in enumerate(_cats):
            _c = _f[(_f.said == _said) & (_f.scene_dir == _scene)]
            fig_knob.add_trace(go.Scatter(
                x=_ci + (_c.seed - 9.5) * 0.022, y=_c.knob, mode="markers", showlegend=False,
                marker=dict(size=8, color=color["ref"], line=dict(width=1, color=color["surface"])),
                customdata=np.stack([_c.seed, _c.success, _c.steps], axis=1),
                hovertemplate=(f"「{verb_ja[_said]}」の文 × {verb_ja[_scene]}シーン<br>"
                               "seed %{customdata[0]}：ハンドル角 %{y:+.2f} rad<br>シーンの成功 %{customdata[1]}（%{customdata[2]} ステップ）<extra></extra>"),
            ), row=_row, col=1)
            fig_knob.add_annotation(
                x=_ci, y=2.15, showarrow=False, font=dict(size=11, color=color["ink2"]),
                text=f"開 {(_c.turned == 'open').sum()}・閉 {(_c.turned == 'close').sum()}・逆 {_c.against.sum()}",
                row=_row, col=1,
            )
    fig_knob.add_hrect(y0=-theta, y1=theta, fillcolor=color["grid"], opacity=0.6, line_width=0, layer="below", row="all", col="all")
    fig_knob.update_xaxes(
        **axis_style, showgrid=False, zeroline=False, range=[-0.6, 3.6], tickvals=list(range(4)),
        ticktext=[f"「{verb_ja[_a]}」の文<br>{verb_ja[_s]}シーン" for _a, _s in _cats],
    )
    fig_knob.update_yaxes(**axis_style, range=[-2.1, 2.35], zeroline=True, dtick=0.5)
    fig_knob.update_yaxes(title_text="ハンドル角 [rad]<br>（＋＝開ける向き）")
    fig_knob.update_layout(**base_layout, height=620, margin=dict(t=70, b=60, l=90, r=20),
                           title=dict(text=f"1 点＝1 話（各列 20 話）。各列の上の数字は θ = {theta} rad での「開ける向き・閉める向き・指示と逆向き」の話数",
                                      x=0, font=dict(size=14)))
    fig_knob
    return faucet_runs, theta


@app.cell
def _(binomtest, faucet_runs, fisher_exact, mo, np, theta, verb_ja):
    _rows = ["| 実験 | 渡した文 | シーン | 開ける向き | 閉める向き | 回していない | 指示と逆向き |", "|:---|:---|:---|:---|:---|:---|:---|"]
    for (_exp, _said, _scene), _c in faucet_runs.groupby(["exp", "said", "scene_dir"], sort=False):
        _rows.append(
            f"| {_exp} | 「{verb_ja[_said]}」 | {verb_ja[_scene]}シーン | {(_c.turned == 'open').sum()} | "
            f"{(_c.turned == 'close').sum()} | {(_c.turned == 'none').sum()} | {_c.against.sum()} |"
        )
    _along = (faucet_runs.turned == faucet_runs.said).sum()
    _against = faucet_runs.against.sum()
    _max_against = (-faucet_runs.knob * np.where(faucet_runs.said == "open", 1, -1)).max()
    _sweep = ["| θ [rad] | 指示どおりの向き | 指示と逆向き | 回していない |", "|:---|:---|:---|:---|"]
    for _t in (0.05, 0.1, 0.2, 0.3, 0.5, 1.0):
        _turned = np.select([faucet_runs.knob > _t, faucet_runs.knob < -_t], ["open", "close"], "none")
        _sweep.append(f"| {_t} | {(_turned == faucet_runs.said).sum()} | {((_turned != 'none') & (_turned != faucet_runs.said)).sum()} | {(_turned == 'none').sum()} |")
    # 印の有無で比べる：「閉める」文 × 閉めるシーン（閉める向きに回せたか）と「開ける」文 × 開けるシーン
    _cmp = []
    for _said in ("close", "open"):
        _c1 = faucet_runs[(faucet_runs.exp == 1) & (faucet_runs.said == _said) & (faucet_runs.scene_dir == _said)].sort_values("seed")
        _c3 = faucet_runs[(faucet_runs.exp == 3) & (faucet_runs.said == _said) & (faucet_runs.scene_dir == _said)].sort_values("seed")
        _a, _b = (_c1.turned == _said).to_numpy(), (_c3.turned == _said).to_numpy()
        _pf = fisher_exact([[_a.sum(), len(_a) - _a.sum()], [_b.sum(), len(_b) - _b.sum()]]).pvalue
        _n10, _n01 = int((_a & ~_b).sum()), int((~_a & _b).sum())
        _pm = binomtest(_n10, _n10 + _n01).pvalue if _n10 + _n01 else 1.0
        _cmp.append(f"- 「{verb_ja[_said]}」の文 × {verb_ja[_said]}シーンで{verb_ja[_said]}向きに回せた話：印あり **{_a.sum()}/20** → 印なし **{_b.sum()}/20**（p（Fisher）{_pf:.3f}、p（McNemar）{_pm:.3f}）")
    _nl = "\n"
    mo.md(f"""
    **分析方法**：横軸は「渡した定型文 × シーン」、縦軸はハンドル角です。点は seed ごとに少し横にずらしています。ハンドル角が ±θ の外なら、その向きに回したと数えます。

    **現在の設定（θ = {theta} rad）**：指示どおりの向きに回した話は 160 話中 **{_along} 話**、指示と逆向きに回した話は **{_against} 話**です。

    {_nl.join(_rows)}

    **θ を振ったとき**（実験 1・3 の 160 話）。指示と逆向きに最も大きく回した話でも {_max_against:.3f} rad（{np.degrees(_max_against):.1f}°）です。

    {_nl.join(_sweep)}

    **ゴール印の有無で比べると**（同じ seed どうしの対）

    {_nl.join(_cmp)}

    **示唆**

    - **回す向きは、言葉だけで決まっています（H2 を強く支持）。** どの θ でも、指示と逆向きに回した話は 0 です。閉めるシーンに「開ける」文を渡すと、言葉どおりに開けます（成功判定上は失敗）。
    - **ゴール印は向きの手がかりではありません。** 印を消しても、逆向きは 0 のままです。
    - **ただし、印を消すと「閉める」だけが弱くなります。** 閉めるシーンで閉める向きに回せた話は、印ありの 11/20 から印なしで 2/20 に減りました（θ = 0.3）。「開ける」はほとんど変わりません。
      - 解釈は 2 通り考えられます。「閉める動きをやり切るのに、青いゴール印を目標として使っている」か、「印のない画像が学習時と違って見え、もともと苦手な閉める動作が先に崩れた」かです。
      - この実験だけでは区別できません（§6）。
    """)
    return


@app.cell
def _(k_slider, mo):
    mo.vstack([
        mo.md(r"""
    ## 3. 実験 2：指示文の言い方を変える

    3 つのシーン（蛇口を開ける・引き出しを閉める・窓を閉める）で、本来の定型文の代わりに次の文を渡しました。

    | 条件 | 渡した文 |
    |:---|:---|
    | 定型文 | 学習データの英語の定型文 |
    | 言い換え | 意味が同じ別の英語（“Turn on the tap”／“Shut the drawer”／“Shut the window”） |
    | 日本語のまま | ルーターに入れる前の日本語（「蛇口を開けて」など） |
    | 無関係な文 | 別タスクの定型文 “Dunk the basketball into the basket” |
    | 空文字 | 何も渡さない |
    | ルーター経由 | 日本語 → ルーター → 定型文（文は定型文と同じ） |
    """),
        k_slider,
    ])
    return


@app.cell
def _(
    axis_style,
    base_layout,
    color,
    fmt_p,
    go,
    k,
    make_subplots,
    quote,
    stats,
    task_ja,
):
    _scenes = list(dict.fromkeys(stats.loc[stats.exp == 2, "scene"]))
    fig_wording = make_subplots(rows=1, cols=len(_scenes), shared_yaxes=True, horizontal_spacing=0.03,
                                subplot_titles=[task_ja[_s] + "シーン" for _s in _scenes])
    for _i, _scene in enumerate(_scenes, start=1):
        _s = stats[(stats.exp == 2) & (stats.scene == _scene)]
        _ref_rate = _s.loc[_s.is_reference, "rate"].iloc[0]
        fig_wording.add_trace(go.Scatter(
            x=_s.rate, y=_s.label, mode="markers", showlegend=False,
            marker=dict(size=10, color=color["ref"], line=dict(width=2, color=color["surface"])),
            error_x=dict(type="data", symmetric=False, array=_s.ci_hi - _s.rate, arrayminus=_s.rate - _s.ci_lo,
                         color=color["ref"], thickness=1.5, width=0),
            customdata=[[quote(_r.instruction), f"{_r.success}/{_r.n}", f"{_r.ci_lo:.0%}〜{_r.ci_hi:.0%}",
                         fmt_p(_r.p_fisher), fmt_p(_r.p_mcnemar)] for _r in _s.itertuples()],
            hovertemplate=("%{y}：%{customdata[0]}<br>成功 %{customdata[1]}（95% 信頼区間 %{customdata[2]}）<br>"
                           "定型文との差：p（Fisher）%{customdata[3]}、p（McNemar）%{customdata[4]}<extra></extra>"),
        ), row=1, col=_i)
        fig_wording.add_trace(go.Scatter(
            x=[1.08] * len(_s), y=_s.label, mode="text", text=[f"{_r.success}/{_r.n}" for _r in _s.itertuples()],
            textfont=dict(size=12, color=color["ink2"]), textposition="middle right", showlegend=False, hoverinfo="skip",
        ), row=1, col=_i)
        fig_wording.add_vline(x=_ref_rate, line=dict(color=color["muted"], width=1), layer="below", row=1, col=_i)
    fig_wording.update_xaxes(**axis_style, zeroline=False, range=[-0.04, 1.42], tickvals=[0, 0.25, 0.5, 0.75, 1], tickformat=".0%")
    fig_wording.update_yaxes(**axis_style, autorange="reversed", showgrid=False)
    fig_wording.update_layout(**base_layout, height=380, margin=dict(t=70, b=40, l=110, r=20),
                              title=dict(text=f"成功率と 95% 信頼区間（K = {k} ステップ以内、各 20 話）。灰色の縦線は定型文の成功率",
                                         x=0, font=dict(size=14)))
    fig_wording
    return


@app.cell
def _(fmt_p, k, mo, p_text, runs, stats, task_ja):
    _lines = []
    for _scene in dict.fromkeys(stats.loc[stats.exp == 2, "scene"]):
        _s = stats[(stats.exp == 2) & (stats.scene == _scene)]
        _parts = [f"{_r.label} {_r.success}" + ("" if fmt_p(_r.p_fisher) == "—" else f"（{p_text(_r.p_fisher)}）")
                  for _r in _s.itertuples()]
        _lines.append(f"- **{task_ja[_scene]}**：" + "、".join(_parts))
    _r2 = runs[runs.exp == 2]
    _hdr = "| K（ステップ） | " + " | ".join(f"{task_ja[_s]}：{_l}" for _s in dict.fromkeys(_r2.scene) for _l in ("定型文", "日本語のまま")) + " |"
    _trend = [_hdr, "|:---" * (1 + 2 * _r2.scene.nunique()) + "|"]
    for _k in (100, 150, 200, 300, 500):
        _cells = []
        for _scene in dict.fromkeys(_r2.scene):
            for _l in ("定型文", "日本語のまま"):
                _e = _r2[(_r2.scene == _scene) & (_r2.label == _l)]
                _cells.append(str(((_e.success == 1) & (_e.steps <= _k)).sum()))
        _trend.append(f"| {_k} | " + " | ".join(_cells) + " |")
    _med = _r2[(_r2.success == 1)].groupby(["scene", "label"]).steps.median()
    _nl = "\n"
    mo.md(f"""
    **分析方法**：シーンごとに、6 種類の文での成功率（点）と Wilson の 95% 信頼区間（横線）を並べました。灰色の縦線は定型文の成功率です。p は定型文との比較で、ホバーすると渡した文そのものと McNemar の p も出ます。

    **現在の設定（K = {k}）**：成功数 / 20

    {_nl.join(_lines)}

    **K を振ったときの「定型文」と「日本語のまま」の成功数**（各 20 話中）

    {_nl.join(_trend)}

    窓を閉めるシーンで「日本語のまま」が成功するまでのステップは中央値 {_med.get(("window-close-v3", "日本語のまま"), float("nan")):.0f}（定型文は {_med.get(("window-close-v3", "定型文"), float("nan")):.0f}）です。

    **示唆**

    - **H3 は 3 シーン中 2 シーンで当たりました。** 日本語をそのまま渡すと、蛇口は 17 → 5、引き出しは 20 → **0** に落ちます。ルーターを通して定型文に直すと、定型文の成績に戻ります。
    - **引き出しを閉める作業は、ほぼ文を見ていません。** 空文字 20/20、無関係な文 18/20、言い換え 20/20 です。それなのに日本語だと 0/20 です。**日本語の文は「何も言わない」よりも悪く、動作を積極的に乱しています。**
    - **窓を閉める作業は、逆に文がないとできません**（無関係な文 0/20、空文字 3/20）。それなのに日本語は 18/20 成功します（ただし定型文の約 2 倍のステップ）。この組み合わせは、今の仮説では説明できません（§6）。
    - **言い換えへの強さは、タスクで大きく違います。** 蛇口 7/20、窓 11/20、引き出し 20/20 です。文への依存が大きいタスクほど、言い方の違いにも弱いのかもしれません（§6 の仮説 5）。いずれにしても、日本語をルーターで定型文に直す設計には意味があります。
    """)
    return


@app.cell
def _(fmt_p, k_slider, mo, quote, stats, task_ja, verb_ja):
    _t = stats.copy()
    _t["シーン"] = _t.scene.map(task_ja) + _t.hide_markers.map({0: "", 1: "（印なし）"})
    _t["渡した文"] = [
        _r.label if _r.exp == 2 else f"「{verb_ja[_r.label.split('-')[1]]}」の定型文" for _r in _t.itertuples()
    ]
    _t["指示文"] = _t.instruction.map(quote)
    _t["成功"] = _t.success.astype(str) + "/" + _t.n.astype(str)
    _t["95% 信頼区間"] = [f"{_r.ci_lo:.0%}〜{_r.ci_hi:.0%}" for _r in _t.itertuples()]
    for _src, _dst in (("p_fisher", "p（Fisher）"), ("p_mcnemar", "p（McNemar）"),
                       ("holm_fisher", "Holm 補正 p（Fisher）"), ("holm_mcnemar", "Holm 補正 p（McNemar）")):
        _t[_dst] = _t[_src].map(fmt_p)
    test_table = _t[["exp", "シーン", "渡した文", "指示文", "成功", "95% 信頼区間",
                     "p（Fisher）", "p（McNemar）", "Holm 補正 p（Fisher）", "Holm 補正 p（McNemar）"]].rename(columns={"exp": "実験"})
    mo.vstack([
        mo.md("## 4. 全条件の検定一覧\n\n比較相手は、同じ実験・同じシーンで本来の定型文を渡した条件です（— は比較相手そのもの、またはルーター経由で同じ話を共有するもの）。"),
        k_slider,
        mo.ui.table(test_table, selection=None, page_size=40),
    ])
    return


@app.cell
def _(k, mo, stats, task_ja, verb_ja):
    _tested = stats.dropna(subset=["p_fisher"])
    _sig = {
        _c: int((_tested[_c] < 0.05).sum())
        for _c in ("p_fisher", "p_mcnemar", "holm_fisher", "holm_mcnemar")
    }
    _survive = _tested[_tested.holm_fisher < 0.05]
    _nl = "\n"
    mo.md(f"""
    **分析方法**：検定は {len(_tested)} 本です。Holm 補正は、この {len(_tested)} 本をまとめて行いました。

    **現在の設定（K = {k}）**：p < 0.05 の条件数は、Fisher {_sig['p_fisher']}、McNemar {_sig['p_mcnemar']}、Holm 補正後 Fisher {_sig['holm_fisher']}、Holm 補正後 McNemar {_sig['holm_mcnemar']} です。

    Holm 補正後も Fisher で p < 0.05 の条件：

    {_nl.join(f"- 実験 {_r.exp}・{task_ja[_r.scene]}シーン{'（印なし）' if _r.hide_markers else ''}・" + (_r.label if _r.exp == 2 else f"「{verb_ja[_r.label.split('-')[1]]}」の定型文") + f"：{_r.success}/{_r.n}" for _r in _survive.itertuples())}

    **示唆**（K = 500 のとき）

    - 補正後も残るのは、蛇口を開けるシーンの入れ替え（実験 1・3）、窓を閉めるシーンの入れ替え、実験 2 で言い方を大きく変えた条件（蛇口の言い換え・日本語のまま・無関係な文・空文字、引き出しの日本語のまま、窓の無関係な文・空文字）です。
    - **蛇口を閉めるシーンの入れ替え（5/20 → 0/20）は、補正すると有意ではありません。** 本来の成功率が低いためです。蛇口で言葉が効いている根拠としては、成功率よりもハンドルの向き（§2）のほうが強いです。
    - 引き出しの入れ替えは、閉めるシーン（20 → 12）が補正の境目（Fisher では残り、McNemar では残らない）、開けるシーン（15 → 7）は補正後は有意ではありません。
    - この実験では、McNemar の p は Fisher とほぼ同じか、やや大きめでした。成否が分かれた対だけを使う正確検定なので、そうした対が少ないと保守的になります。
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. まとめ（実験の設定：K = 500、θ = 0.3 rad）

    | 仮説 | 判定 | 根拠 |
    |:---|:---|:---|
    | H2：見た目が同じ蛇口では言葉が効く | **支持** | 回した向きは 160 話すべてで指示どおり（逆向きは最大でも 0.013 rad）。入れ替えると成功 0/20・0/20（ただし閉めるシーンは本来も 5/20 と低く、補正後は有意差なし） |
    | H1：見た目で区別できる組では言葉を無視する | **部分的（言いすぎ）** | 引き出しは入れ替えても 12/20・7/20 成功するが、すべて 189 ステップ以降の遅い成功。窓（閉めるシーン）は入れ替えると 0/20 |
    | H3：日本語のままだと失敗が増える | **3 シーン中 2 シーンで支持** | 蛇口 17 → 5、引き出し 20 → 0。窓だけは 15 → 18 で例外 |
    | 実験 3：蛇口で効いているのはゴール印？ | **向きについては否定** | 印を消しても逆向きは 0。ただし「閉める」動作は 11/20 → 2/20 と弱くなる |

    **一言でいうと**：SmolVLA は指示文を聞いています。少なくとも最初の 1〜2 秒の行動は、どの組でも言葉で決まっています。ただし言葉の効き方は「学習時の英語の定型文」に強く結びついていて、言い換えや日本語には弱いです。そのため、日本語の指示をルーターで定型文に直す設計が効いてきます。
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. 分析中に浮かんだ新しい仮説（次に検証する候補）

    1. **日本語の文は「何も言わない」より悪いことがある**（引き出し：空文字 20/20、日本語 0/20）。英語以外の文字列が言語の特徴量を学習時の範囲の外へ押し出し、画像だけで決まるはずの動作まで乱している？
       - 検証：意味のない英字列、ローマ字（“hikidashi wo shimete”）、中国語、絵文字を引き出しを閉めるシーンに渡す。
    2. **窓だけは日本語でも成功する**（18/20）のはなぜか。無関係な英文では 0/20 なので、「何か文があれば閉める」わけでもない。
       - 検証：窓を閉めるシーンに無関係な日本語（「バスケットボールを入れて」）を渡す。日本語なら何でも成功するのか、「窓」「閉めて」が効いているのかを分ける。
    3. **ゴール印を消すと「閉める」だけが弱くなる**のは、青い印を目標に使っているからか、画像が見慣れないからか。
       - 検証：`goal_close` だけ消す条件と、`goal_open` だけ消す条件を比べる。
    4. **引き出しの「遅い成功」は、最初に言葉どおりに動いてから切り替えているのか。**
       - 検証：手先位置（`agent_pos`）の時系列を記録し、最初の 150 ステップで引き出しを押す向き・引く向きのどちらに動いたかを数える。
    5. **言い換えに弱いタスクほど、定型文に強く結びついている？**（蛇口 7/20、窓 11/20、引き出し 20/20）
       - 検証：言い換えを 1 タスクあたり 5 通りに増やし、空文字のときの成功率（文への依存度）との関係を見る。
    """)
    return


@app.cell
def _(episodes, mo):
    _ok = episodes[episodes.success == 1]
    _ng = episodes[episodes.success == 0]
    mo.md(f"""
    ## 付録：計算時間（M1 Mac、MPS）

    - 全 {len(episodes)} 話の実行時間の合計：**{episodes.wall_s.sum() / 60:.0f} 分**（モデルの読み込みは別に約 16 秒）
    - 1 話あたり：成功した話は中央値 {_ok.wall_s.median():.1f} 秒、失敗した話（500 ステップまで）は中央値 {_ng.wall_s.median():.1f} 秒
    - 50 ステップ分の行動をまとめて推論する 1 回あたり：中央値 {episodes.chunk_ms_med.median():.0f} ms
    """)
    return


if __name__ == "__main__":
    app.run()
