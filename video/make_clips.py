"""動画用のロボット映像のうち、対話デモ以外のもの（入れ替えテストの見本）を作る。

  uv run python video/make_clips.py      # → outputs/video/clips/*.mp4

- 引き出しを閉めるシーン（seed 10）で、本来の定型文と、入れ替えた定型文（「開ける」）を渡した 2 本。
  入れ替えたほうも最後は閉めてしまうが、本来の 3 倍以上の時間がかかる（notebooks/analysis.py §1.2）。
- 「問い」の場面で並べる、各シーンの最初の画像（seed 0）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from lerobot.envs.metaworld import TASK_DESCRIPTIONS, MetaworldEnv
from PIL import Image

from kotoba_vla.episode import load_vla, run_episode, save_episode_video

OUT_DIR = Path("outputs/video/clips")
SEED = 10
SPEED = 0.5
# 出力名 → (シーン, 渡す定型文の元タスク, 字幕の日本語, 成功したときの判定の言い方, 判定の色)
CLIPS = {
    "drawer_reference": ("drawer-close-v3", "drawer-close-v3", "引き出しを閉めて（本来の定型文）", "閉めた", True),
    "drawer_swapped": ("drawer-close-v3", "drawer-open-v3", "引き出しを開けて（入れ替えた定型文）", "閉めてしまった", False),
}
FIRST_FRAMES = ["faucet-open-v3", "faucet-close-v3", "drawer-open-v3", "drawer-close-v3"]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for scene in FIRST_FRAMES:  # 方策は使わないので、配置だけ episode.py と同じ方法で決める
        env = MetaworldEnv(task=scene, obs_type="pixels_agent_pos")
        np.random.seed(0)
        obs, _ = env.reset(seed=0)
        Image.fromarray(obs["pixels"]).save(OUT_DIR / f"scene_{scene}.png")
        env.close()

    vla = load_vla()
    for name, (scene, task, ja, done, ok) in CLIPS.items():
        result = run_episode(vla, scene, TASK_DESCRIPTIONS[task], SEED)
        verdict = f"{done}（{result.steps} ステップ）" if result.success else None
        path = save_episode_video(result, OUT_DIR / f"{name}.mp4", ja=ja, speed=SPEED, verdict=verdict, ok=ok)
        print(f"{path}：success={result.success} steps={result.steps}")


if __name__ == "__main__":
    main()
