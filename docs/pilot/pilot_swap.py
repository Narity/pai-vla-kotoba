"""検証用: 指示文の入れ替え 2x2 を少数 seed で回し、成功率と所要時間を測る。

uv run python docs/pilot/pilot_swap.py --pair faucet --seeds 0 1 2 3 4 5 6 7 8 9 --out outputs/pilot
"""
import argparse
import csv
import time
from pathlib import Path

import imageio.v3 as iio
import numpy as np
import torch
from lerobot.envs.metaworld import TASK_DESCRIPTIONS, MetaworldEnv
from lerobot.envs.utils import preprocess_observation
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

PAIRS = {
    "faucet": ("faucet-open-v3", "faucet-close-v3"),
    "drawer": ("drawer-open-v3", "drawer-close-v3"),
    "window": ("window-open-v3", "window-close-v3"),
}


def run_episode(policy, preprocess, postprocess, scene, instruction, seed, max_steps):
    env = MetaworldEnv(task=scene, obs_type="pixels_agent_pos")
    np.random.seed(seed)  # Meta-World は reset(seed=) を無視し、物体配置を np.random で決める
    obs, _ = env.reset(seed=seed)
    torch.manual_seed(seed)
    policy.reset()
    frames = [obs["pixels"].copy()]
    chunk_times, step_times, success, t = [], [], False, 0
    inner = env._env.unwrapped
    obj_pos = np.round(inner.obj_init_pos, 3).tolist()
    has_knob = "faucet" in scene
    knob = 0.0  # 蛇口ハンドルの角度（+ が開ける＝反時計回り、- が閉める）。絶対値最大の値を記録
    for t in range(max_steps):
        batch = preprocess_observation(obs)
        batch["task"] = [instruction]
        batch = preprocess(batch)
        need_chunk = len(policy._queues["action"]) == 0
        t0 = time.perf_counter()
        with torch.inference_mode():
            action = policy.select_action(batch)
        action = postprocess(action).squeeze(0).cpu().numpy()
        if need_chunk:
            chunk_times.append(time.perf_counter() - t0)
        t1 = time.perf_counter()
        obs, reward, terminated, truncated, info = env.step(action)
        step_times.append(time.perf_counter() - t1)
        frames.append(obs["pixels"].copy())
        if has_knob and not (terminated or truncated):
            ang = float(inner.data.joint("knob_Joint_1").qpos[0])
            if abs(ang) > abs(knob):
                knob = ang
        if info["is_success"]:
            success = True
            break
        if terminated or truncated:
            break
    env.close()
    return success, t + 1, frames, chunk_times, step_times, knob, obj_pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="faucet", choices=PAIRS)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--video-seed", type=int, default=0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_metaworld").to(args.device).eval()
    preprocess, postprocess = make_pre_post_processors(
        policy.config, "lerobot/smolvla_metaworld",
        preprocessor_overrides={"device_processor": {"device": args.device}},
    )
    print(f"[load] {time.perf_counter() - t0:.1f}s  device={args.device}", flush=True)

    rows = []
    a, b = PAIRS[args.pair]
    for scene in (a, b):
        for instr_task in (a, b):
            instruction = TASK_DESCRIPTIONS[instr_task]
            for seed in args.seeds:
                te = time.perf_counter()
                ok, steps, frames, ct, st, knob, obj_pos = run_episode(
                    policy, preprocess, postprocess, scene, instruction, seed, args.max_steps)
                wall = time.perf_counter() - te
                row = dict(scene=scene, instruction=instruction, seed=seed, success=int(ok), steps=steps,
                           wall_s=round(wall, 1), n_chunks=len(ct),
                           chunk_ms_first=round(ct[0] * 1000), chunk_ms_med=round(float(np.median(ct[1:] or ct)) * 1000),
                           step_ms_med=round(float(np.median(st)) * 1000, 1), knob=round(knob, 2), obj=obj_pos)
                rows.append(row)
                print(row, flush=True)
                if seed == args.video_seed:
                    name = f"{scene}__{instr_task.replace('-v3', '')}__s{seed}.mp4"
                    iio.imwrite(args.out / name, np.stack(frames[::2]), fps=40)

    with open(args.out / f"{args.pair}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("\n2x2 success (scene x instruction):")
    for scene in (a, b):
        cells = []
        for instr_task in (a, b):
            r = [x["success"] for x in rows if x["scene"] == scene and x["instruction"] == TASK_DESCRIPTIONS[instr_task]]
            cells.append(f"{sum(r)}/{len(r)}")
        print(f"  {scene:18s}  instr={a}: {cells[0]:5s}  instr={b}: {cells[1]}")
    if args.pair == "faucet":
        print("knob angle by instruction (rad, + = open):")
        for instr_task in (a, b):
            k = [x["knob"] for x in rows if x["instruction"] == TASK_DESCRIPTIONS[instr_task]]
            print(f"  instr={instr_task:16s} mean={np.mean(k):+.2f}  n(+>0.3)={sum(v > 0.3 for v in k)}  n(-<-0.3)={sum(v < -0.3 for v in k)}  n={len(k)}")


if __name__ == "__main__":
    main()
