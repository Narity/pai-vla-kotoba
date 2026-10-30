"""対話デモ：日本語の指示 → ルーター → SmolVLA → Meta-World → 字幕付き MP4。

  uv run python -m kotoba_vla.chat                          # 指示した作業のシーンで実行する
  uv run python -m kotoba_vla.chat --scene faucet-close-v3  # シーンを固定して「開けて」「閉めて」を言い分ける（見せ場）
  printf '蛇口を閉めて\\n料理を作って\\n' | uv run python -m kotoba_vla.chat   # パイプで流し込む（収録・確認用）

終了は q（または Ctrl-D）、できることの一覧は help。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from lerobot.envs.metaworld import TASK_DESCRIPTIONS

from kotoba_vla.episode import load_vla, run_episode, save_episode_video
from kotoba_vla.router import JA_NAME, capabilities, route

QUIT = {"q", "quit", "exit", "終了", "おわり"}
HELP = {"help", "h", "?", "？", "ヘルプ"}
EXAMPLES = "例：蛇口を閉めて／水を出して／引き出しを開けて／窓を閉めて"


@contextmanager
def quiet():
    """モデル読み込み中にライブラリが出す警告・進捗バーを隠す（画面を見やすくするため。--verbose で表示）。
    C 側の出力も含めて隠すため、ファイル記述子 1・2 ごと /dev/null に向ける。例外は元に戻してから伝わる。"""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, 1)
        os.dup2(null, 2)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        for fd in (*saved, null):
            os.close(fd)


def knob_text(angle: float) -> str:
    """蛇口ハンドルの回転角を言葉にする（0.3 rad 未満は「回していない」扱い。§4.1 と同じ基準）。"""
    if angle > 0.3:
        return f"開ける向きに回した（{angle:+.2f} rad）"
    if angle < -0.3:
        return f"閉める向きに回した（{angle:+.2f} rad）"
    return f"ほとんど回していない（{angle:+.2f} rad）"


def main() -> None:
    ap = argparse.ArgumentParser(description="日本語で指示して SmolVLA を動かす対話デモ")
    ap.add_argument("--scene", help="シーンを固定する（例：faucet-close-v3）。省略時は指示した作業のシーンで実行")
    ap.add_argument("--seed", type=int, default=0, help="物体配置の seed（毎回この配置で実行する）")
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--speed", type=float, default=1.0, help="動画の再生速度（1.0 = 等倍、0.5 = 2 倍スロー）")
    ap.add_argument("--device", default="mps", help="mps または cpu")
    ap.add_argument("--out-dir", type=Path, default=Path("outputs/chat"), help="動画の保存先")
    ap.add_argument("--no-video", action="store_true", help="動画を保存しない")
    ap.add_argument("--verbose", action="store_true", help="モデル読み込み中のライブラリの警告も表示する")
    args = ap.parse_args()
    if args.scene and args.scene not in TASK_DESCRIPTIONS:
        ap.error(f"--scene が不明です：{args.scene!r}（python -m kotoba_vla.episode --list で一覧を表示）")

    print("モデルを読み込んでいます（約 16 秒）…", flush=True)
    if args.verbose:
        vla = load_vla(args.device)
    else:
        with quiet():
            vla = load_vla(args.device)
    print(f"できること：{capabilities()}\n{EXAMPLES}")
    if args.scene:
        print(f"シーンは {args.scene} に固定しています（成功判定もこのシーンの基準）")
    print("終了は q、一覧は help")

    while True:
        try:
            text = input("\n指示> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not sys.stdin.isatty():  # パイプで流し込んだときは、入力した文を画面にも出す
            print(text)
        if not text:
            continue
        if text.lower() in QUIT:
            break
        if text.lower() in HELP:
            print(f"できること：{capabilities()}\n{EXAMPLES}")
            continue

        r = route(text)
        if not r.ok:
            print(f"  ✗ その作業はできません：{r.reason}")
            continue
        scene = args.scene or r.task
        obj = r.task.split("-")[0]
        if not scene.startswith(obj):
            print(f"  ✗ その作業はできません：このシーン（{scene}）には{JA_NAME[obj]}がありません")
            continue

        print(f"  → {r.task}（{r.reason}）")
        print(f'  VLA へ："{r.instruction}"' + ("" if scene == r.task else f"　シーン：{scene}"))
        print("  実行中…", flush=True)
        result = run_episode(vla, scene, r.instruction, args.seed, args.max_steps, keep_frames=not args.no_video)

        judged = "成功" if result.success else "失敗"
        if scene != r.task:
            judged += f"（{scene} の基準）"
        line = f"  {judged}：{result.steps} ステップ、{result.wall_s:.1f} 秒"
        if result.knob is not None:
            line += f"。ハンドルは{knob_text(result.knob)}"
        print(line)

        if not args.no_video:
            # シーンを固定して別の作業を頼んだときは、シーン基準の成否は誤解を招くので、成否の色を付けない
            verdict = ok = None
            if scene != r.task:
                verdict = knob_text(result.knob) if result.knob is not None else judged
                if result.knob is not None and abs(result.knob) > 0.3:
                    # 回し終えた後もアームは 500 ステップまで動き続け、蛇口を隠してしまう。
                    # 成功時の動画が成功した瞬間で終わるのに合わせて、ハンドルが回り切ったステップで切る
                    result.frames = result.frames[: result.knob_step + 1]
            path = args.out_dir / f"{time.strftime('%m%d-%H%M%S')}_{r.task}.mp4"
            save_episode_video(result, path, ja=text, speed=args.speed, max_steps=args.max_steps, verdict=verdict, ok=ok)
            print(f"  動画：{path}")


if __name__ == "__main__":
    main()
