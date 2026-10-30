# その指示、ほんとうに聞いてる？

M1 Mac で動く VLA（SmolVLA × Meta-World）に日本語で指示し、「言葉の効き目」を確かめる。Physical AI 応用1 最終課題。

- **動画**：<https://youtu.be/IGzcyR98v8M>（YouTube、約 2 分）
- **レポート**：[docs/report.pdf](docs/report.pdf)（原稿は [docs/report.md](docs/report.md)）
- **分析ノートブック**：[notebooks/analysis.py](notebooks/analysis.py)（marimo）

ターミナルに日本語で指示を打つと、指示ルーターが英語の定型文に直して VLA（SmolVLA）に渡し、シミュレータ（Meta-World）の中のロボットアームが作業します。学習はせず、推論だけです。Docker も NVIDIA GPU も使わず、Mac と `uv` だけで動きます。

そのうえで、「VLA は本当に指示文を見て動いているのか、画像だけで作業を決めていないか」を、指示文を入れ替える実験（各条件 20 話、計 560 話）で確かめました。

![指示文の入れ替えテスト](docs/figures/fig1_swap_heatmap.png)

## 分かったこと

1. **言葉は効いている。** 見た目がほぼ同じ「蛇口を開ける／閉める」では、指示文を入れ替えると成功は 0/20 になりました。ハンドルを指示と逆向きに回した回は 160 回中 0 回です。
2. **見た目で作業が分かる場合でも、最初の約 2 秒は言葉が勝つ。** 引き出しは指示文を入れ替えても 20 回中 12 回は閉めてしまいますが、成功までの時間は中央値で本来の約 3 倍かかりました。入れ替えると、どの作業も最初の約 2 秒では 1 回も成功しません。
3. **言葉の効き方は、学習時の英語の定型文に強く依存する。** 日本語をそのまま渡すと、蛇口は 17/20 → 5/20、引き出しは 20/20 → 0/20 に落ちました。ルーターで定型文に直すと元に戻ります。

詳しくは[レポート](docs/report.pdf)を見てください。

## 動かし方

### 必要なもの

- Apple シリコンの Mac（M1 で確認）
- [uv](https://docs.astral.sh/uv/)（Python 3.12 も uv が用意します）
- 空きディスク 約 5 GB（Python の環境 約 2 GB と、初回実行時に Hugging Face から自動でダウンロードされるモデル 約 3 GB）
- 図の PNG とレポートの PDF を作り直すときだけ、Google Chrome

### セットアップ

```bash
git clone https://github.com/Narity/pai-vla-kotoba.git
cd pai-vla-kotoba
uv sync
```

### 対話デモ

```bash
uv run python -m kotoba_vla.chat --speed 0.5
```

`指示> ` に続けて、「蛇口を閉めて」「水を出して」「引き出しを開けて」「窓を閉めて」などと入力します。`help` でできることの一覧、`q` で終了です。ロボットの動画（字幕つき MP4）は `outputs/chat/` に保存されます。

シーンを固定して、言葉だけを変えることもできます（デモ動画の見せ場）。

```bash
uv run python -m kotoba_vla.chat --scene faucet-close-v3 --speed 0.5
# 指示> 蛇口を開けて   → 開ける向きに回す
# 指示> 蛇口を閉めて   → 閉める向きに回す
```

### 1 話だけ実行する

```bash
uv run python -m kotoba_vla.episode --list                                     # シーン名と定型文の一覧
uv run python -m kotoba_vla.episode --scene faucet-open-v3 --seed 0             # 本来の定型文で実行
uv run python -m kotoba_vla.episode --scene faucet-open-v3 --task faucet-close-v3   # 定型文を入れ替える
uv run python -m kotoba_vla.episode --scene drawer-close-v3 --instruction "引き出しを閉めて"   # 好きな文を渡す
```

### 実験を再現する

```bash
uv run python -m kotoba_vla.experiment --dry-run        # 条件と所要時間の見積もりだけ表示
uv run python -m kotoba_vla.experiment                  # 実験 1〜3 を各 20 話（M1 で約 70 分）
uv run python -m kotoba_vla.experiment --summary-only   # 記録済みの結果から集計だけする
```

1 話ごとの記録は `results/episodes.csv` に追記され、条件ごとの集計は `results/summary.csv` に書き出されます。途中で止めても、同じコマンドで続きから再開できます。同じ seed なら毎回まったく同じ結果になります。

### 分析とレポート

```bash
uv run marimo edit notebooks/analysis.py     # 分析ノートブック（スライダーで条件を変えて再計算できる）
uv run python notebooks/export_figures.py    # レポート用の図 → docs/figures/*.png
uv run python docs/build_report.py           # レポート → docs/report.pdf
```

### デモ動画を作り直す

```bash
# 1. 対話デモを疑似端末の中で実際に動かし、画面の出力を記録する（指示は自動で打ち込む）
uv run python video/record_terminal.py outputs/video/session_a.cast \
    --input 水を出して --input 料理を作って --input 引き出しを閉めて --input 窓を閉めて --input q \
    -- uv run python -m kotoba_vla.chat --speed 0.5
uv run python video/record_terminal.py outputs/video/session_b.cast \
    --input 蛇口を開けて --input 蛇口を閉めて --input q \
    -- uv run python -m kotoba_vla.chat --scene faucet-close-v3 --speed 0.5
# 2. 記録をターミナル風の動画に描き直す
uv run python video/render_terminal.py outputs/video/session_a.cast
uv run python video/render_terminal.py outputs/video/session_b.cast
# 3. 入れ替えテストの見本の映像を作り、全体を組み立てる
uv run python video/make_clips.py
uv run python video/make_video.py            # → outputs/video/demo.mp4（約 2 分、字幕つき）
```

### テスト

```bash
uv run pytest
```

## フォルダ構成

```
├── src/kotoba_vla/
│   ├── episode.py       # 1 話を実行する（指示文を差し替えられる）。字幕つき MP4 の保存
│   ├── router.py        # 日本語 → タスク名と英語の定型文（キーワード辞書）。分からない指示は断る
│   ├── chat.py          # 対話デモ
│   ├── experiment.py    # 実験 1〜3 の一括実行と集計
│   └── overlay.py       # 動画に日本語の字幕を描く
├── tests/               # ルーターのテスト
├── results/             # 実験の記録（episodes.csv）と集計（summary.csv）
├── notebooks/           # 分析ノートブック（marimo）と、レポート用の図の書き出し
├── video/               # デモ動画の収録と編集
└── docs/
    ├── report.md / report.pdf      # レポート
    ├── figures/                    # レポートの図
    ├── proposal.md / proposal.html # 企画書
    └── pilot/                      # 予備実験（N=10）のスクリプトと結果
```

`outputs/`（動画など）は Git に含めていません。

## Mac で動かすときの注意

- SmolVLA の評価によく使われる LIBERO は Linux 専用なので、Mac では Meta-World を使っています。
- MuJoCo は 3.8.1 に固定しています（3.17 では Meta-World 3.0.0 が動きません）。
- 公式の評価コマンド `lerobot-eval` を使う場合は、`--rename_map='{"observation.image": "observation.images.camera1"}'` が必要です（このリポジトリのスクリプトでは不要）。
- pyenv を使っている場合、`uv init` が作る `.python-version` が pyenv と衝突することがあります。このリポジトリには `.python-version` を置いていません。
- 実行中はメモリを多く使い、スワップがディスクの空きを圧迫することがあります。
- `chat.py` は、モデル読み込み中のライブラリの警告を隠しています。すべて表示するときは `--verbose` を付けます。

## 使用したもの

- [SmolVLA](https://huggingface.co/lerobot/smolvla_metaworld)（`lerobot/smolvla_metaworld`）
- [LeRobot](https://github.com/huggingface/lerobot) 0.5.1
- [Meta-World](https://github.com/Farama-Foundation/Metaworld) 3.0.0
- [MuJoCo](https://github.com/google-deepmind/mujoco) 3.8.1

それぞれのライセンスに従って利用しています。
