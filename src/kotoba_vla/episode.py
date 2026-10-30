"""1 エピソードを実行する（VLA に渡す指示文を自由に差し替えられる）。

例:
  # シーン本来の定型文で実行
  uv run python -m kotoba_vla.episode --scene faucet-open-v3
  # 入れ替え：「開ける」シーンで「閉める」の定型文を渡す。字幕に日本語の指示も出す
  uv run python -m kotoba_vla.episode --scene faucet-open-v3 --task faucet-close-v3 --ja 蛇口を閉めて
  # 任意の文を渡す（言い換え・日本語・空文字など）
  uv run python -m kotoba_vla.episode --scene faucet-close-v3 --instruction "Turn off the tap"
  # シーンと定型文の一覧
  uv run python -m kotoba_vla.episode --list
"""
from __future__ import annotations

import argparse
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from lerobot.envs.metaworld import TASK_DESCRIPTIONS, MetaworldEnv
from lerobot.envs.utils import preprocess_observation
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.utils.constants import ACTION

from kotoba_vla.overlay import save_video

MODEL_ID = "lerobot/smolvla_metaworld"
SIM_HZ = MetaworldEnv.metadata["render_fps"]  # 80Hz（1 ステップ = 1/80 秒）


@dataclass
class VLA:
    """学習済み SmolVLA と前処理・後処理のひとまとめ。読み込みに約 16 秒かかるので、1 回だけ作って使い回す。"""

    policy: SmolVLAPolicy
    preprocess: Any
    postprocess: Any
    device: str


def load_vla(device: str = "mps") -> VLA:
    policy = SmolVLAPolicy.from_pretrained(MODEL_ID).to(device).eval()
    preprocess, postprocess = make_pre_post_processors(
        policy.config,
        MODEL_ID,
        preprocessor_overrides={"device_processor": {"device": device}},
    )
    return VLA(policy, preprocess, postprocess, device)


@dataclass
class EpisodeResult:
    scene: str
    instruction: str
    seed: int
    success: bool
    steps: int
    wall_s: float
    chunk_s: list[float]  # 重い推論（50 ステップに 1 回）にかかった秒数
    obj_pos: list[float]  # 物体の初期位置（条件間で配置がそろっているかの確認用）
    knob: float | None = None  # 蛇口シーンのみ：ハンドル角の絶対値が最大のときの値 [rad]（+ が開ける向き）
    knob_step: int | None = None  # 蛇口シーンのみ：その最大値になったステップ（動画を切る位置の目安）
    frames: list[np.ndarray] = field(default_factory=list, repr=False)

    def row(self) -> dict:
        """CSV の 1 行分（フレームは含めない）。"""
        return {
            "scene": self.scene,
            "instruction": self.instruction,
            "seed": self.seed,
            "success": int(self.success),
            "steps": self.steps,
            "wall_s": round(self.wall_s, 2),
            "chunk_ms_med": round(float(np.median(self.chunk_s)) * 1000) if self.chunk_s else None,
            "knob": None if self.knob is None else round(self.knob, 3),
            "obj": self.obj_pos,
        }


def run_episode(
    vla: VLA,
    scene: str,
    instruction: str,
    seed: int = 0,
    max_steps: int = 500,
    keep_frames: bool = True,
    hide_goal_markers: bool = False,
) -> EpisodeResult:
    """scene：どの作業台で、どの成功判定を使うか（例 'faucet-open-v3'）。
    instruction：VLA に渡す文。定型文・入れ替え文・言い換え・日本語・空文字など何でもよい。
    keep_frames=False にすると画像を保存しない（バッチ実験でメモリを節約する）。
    hide_goal_markers=True にすると、ゴール印（画面上の小さな緑・青の点）を透明にする。"""
    t_start = time.perf_counter()
    env = MetaworldEnv(task=scene, obs_type="pixels_agent_pos")
    if hide_goal_markers:  # reset の前に消しておけば、最初の画像から映らない（Meta-World は色を戻さない）
        model = env._env.unwrapped.model
        for i in range(model.nsite):
            if model.site(i).name.startswith("goal"):
                model.site_rgba[i, 3] = 0.0
    np.random.seed(seed)  # Meta-World は reset(seed=) を無視し、物体配置を np.random で決める
    torch.manual_seed(seed)  # Flow Matching の初期ノイズも固定する（MPS でも再現することを確認済み）
    obs, _ = env.reset(seed=seed)
    vla.policy.reset()  # action chunk のキューを空にする

    inner = env._env.unwrapped
    is_faucet = scene.startswith("faucet")
    obj_pos = np.round(inner.obj_init_pos, 3).tolist()
    frames = [obs["pixels"].copy()] if keep_frames else []
    chunk_s: list[float] = []
    knob, knob_step, success, steps = 0.0, 0, False, 0

    for steps in range(1, max_steps + 1):
        batch = preprocess_observation(obs)  # pixels → observation.image、agent_pos → observation.state
        batch["task"] = [instruction]  # ★ ここで指示文を差し替える
        batch = vla.preprocess(batch)  # 名前の付け替え → バッチ化 → トークナイズ → 正規化 → MPS へ
        needs_chunk = len(vla.policy._queues[ACTION]) == 0  # キューが空なら、今回は 50 ステップ分を推論する
        t0 = time.perf_counter()
        with torch.inference_mode():
            action = vla.policy.select_action(batch)
        action = vla.postprocess(action).squeeze(0).cpu().numpy()  # 正規化を戻して CPU へ
        if needs_chunk:
            chunk_s.append(time.perf_counter() - t0)

        obs, _, terminated, truncated, info = env.step(action)
        if keep_frames:
            frames.append(obs["pixels"].copy())
        if is_faucet and not (terminated or truncated):  # 終了時は env が内部で reset 済みなので読まない
            angle = float(inner.data.joint("knob_Joint_1").qpos[0])
            if abs(angle) > abs(knob):
                knob, knob_step = angle, steps
        if info["is_success"]:
            success = True
            break
        if terminated or truncated:
            break

    env.close()
    return EpisodeResult(
        scene=scene,
        instruction=instruction,
        seed=seed,
        success=success,
        steps=steps,
        wall_s=time.perf_counter() - t_start,
        chunk_s=chunk_s,
        obj_pos=obj_pos,
        knob=knob if is_faucet else None,
        knob_step=knob_step if is_faucet else None,
        frames=frames,
    )


def save_episode_video(
    result: EpisodeResult,
    path: Path,
    ja: str = "",
    speed: float = 1.0,
    max_steps: int = 500,
    verdict: str | None = None,
    ok: bool | None = None,
) -> Path:
    """字幕付き MP4 を保存する。上段は日本語の指示（無ければシーン名）、下段は VLA に実際に渡した文。
    verdict を渡すと、最後に出す結果ラベルを差し替える（ok=None なら成否の色を付けない）。"""
    top = f"指示：{ja}" if ja else f"シーン：{result.scene}"
    bottom = f"VLA へ：{result.instruction}" if result.instruction else 'VLA へ：""（空文字）'
    if verdict is None:
        ok = result.success
        if result.success:
            verdict = f"成功（{result.steps} ステップ）"
        elif result.steps >= max_steps:
            verdict = f"失敗（{max_steps} ステップで打ち切り）"
        else:
            verdict = f"失敗（{result.steps} ステップ）"
    return save_video(result.frames, path, top, bottom, result=verdict, ok=ok, speed=speed, sim_hz=SIM_HZ)


def main() -> None:
    ap = argparse.ArgumentParser(description="SmolVLA × Meta-World を 1 エピソード実行し、字幕付き MP4 を保存する")
    ap.add_argument("--scene", help="シーン（どの作業台で、どの成功判定を使うか）。例：faucet-open-v3")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--task", help="このタスクの定型文を VLA に渡す（入れ替えテスト用）。例：faucet-close-v3")
    src.add_argument("--instruction", help="VLA に渡す文をそのまま指定（言い換え・日本語・空文字など）")
    ap.add_argument("--ja", default="", help="字幕に出す日本語の指示（表示用。VLA には渡らない）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--speed", type=float, default=1.0, help="動画の再生速度（1.0 = 等倍、0.5 = 2 倍スロー）")
    ap.add_argument("--device", default="mps", help="mps または cpu")
    ap.add_argument("--out", type=Path, help="MP4 の保存先（省略時は outputs/episodes/ 以下）")
    ap.add_argument("--no-video", action="store_true", help="動画を保存しない")
    ap.add_argument("--list", action="store_true", help="シーン名と定型文の一覧を表示して終了")
    args = ap.parse_args()

    if args.list:
        for name, text in TASK_DESCRIPTIONS.items():
            print(f"{name:28s} {text}")
        return
    if args.scene not in TASK_DESCRIPTIONS:
        ap.error(f"--scene が不明です：{args.scene!r}（--list で一覧を表示）")
    if args.task and args.task not in TASK_DESCRIPTIONS:
        ap.error(f"--task が不明です：{args.task!r}（--list で一覧を表示）")

    if args.instruction is not None:
        instruction = args.instruction
        label = "custom-" + hashlib.md5(instruction.encode()).hexdigest()[:6]
    else:
        task = args.task or args.scene
        instruction, label = TASK_DESCRIPTIONS[task], task

    t0 = time.perf_counter()
    vla = load_vla(args.device)
    print(f"[load] {time.perf_counter() - t0:.1f} 秒（device={args.device}）")

    result = run_episode(vla, args.scene, instruction, args.seed, args.max_steps, keep_frames=not args.no_video)
    chunk_ms = result.row()["chunk_ms_med"]
    knob = "" if result.knob is None else f"  ハンドル角={result.knob:+.2f} rad"
    print(
        f"[{'成功' if result.success else '失敗'}] scene={result.scene}  seed={result.seed}  "
        f"steps={result.steps}  {result.wall_s:.1f} 秒  推論 {chunk_ms} ms/回{knob}\n"
        f"  VLA へ：{instruction!r}"
    )
    if not args.no_video:
        out = args.out or Path("outputs/episodes") / f"{args.scene}__{label}__s{args.seed}.mp4"
        save_episode_video(result, out, ja=args.ja, speed=args.speed, max_steps=args.max_steps)
        print(f"[video] {out}")


if __name__ == "__main__":
    main()
