"""入れ替えテスト（実験 1〜3）をまとめて回し、結果を CSV に記録・集計する。

  uv run python -m kotoba_vla.experiment --dry-run        # 回す条件・話数・所要時間の見積もりだけ表示
  uv run python -m kotoba_vla.experiment                  # 実験 1〜3 を N=20 で実行（約 1 時間）
  uv run python -m kotoba_vla.experiment --exp 1 --n 5    # 一部の実験だけ、少ない N で試す
  uv run python -m kotoba_vla.experiment --summary-only   # 記録済みの結果から集計だけやり直す

実験 1：見た目が同じ組（蛇口）と、見た目で区別できる組（引き出し・窓）で指示文を入れ替える 2×2
実験 2：本来のシーンで、指示文の言い方を変える（定型文・言い換え・日本語・無関係・空文字・ルーター経由）
実験 3：実験 1 の蛇口を、ゴール印（画面上の小さな緑・青の点）を消して回す（見た目の手がかりを除く）

記録は 1 エピソード 1 行（results/episodes.csv）に追記する。シーン・指示文・seed・ゴール印の有無が
同じエピソードは再実行しないので、途中で止めても続きから再開でき、条件が重なる分は使い回される
（例：ルーター経由は定型文と同じ入力になるので、実行は 1 回だけ）。
"""
from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from pathlib import Path

from lerobot.envs.metaworld import TASK_DESCRIPTIONS
from scipy.stats import fisher_exact

from kotoba_vla.episode import load_vla, run_episode, save_episode_video
from kotoba_vla.router import route

PAIRS = {
    "faucet": ("faucet-open-v3", "faucet-close-v3"),  # 見た目がほぼ同じ
    "drawer": ("drawer-open-v3", "drawer-close-v3"),  # 見た目で区別できる
    "window": ("window-open-v3", "window-close-v3"),  # 見た目で区別できる
}
# 実験 2：定型文での成功率が高いシーン（§4.1）を選び、言い換えと日本語を用意する
VARIANTS = {
    "faucet-open-v3": {"言い換え": "Turn on the tap", "ja": "蛇口を開けて"},
    "drawer-close-v3": {"言い換え": "Shut the drawer", "ja": "引き出しを閉めて"},
    "window-close-v3": {"言い換え": "Shut the window", "ja": "窓を閉めて"},
}
UNRELATED = TASK_DESCRIPTIONS["basketball-v3"]  # "Dunk the basketball into the basket"
KNOB_TH = 0.3  # 蛇口ハンドルを「回した」とみなす角度 [rad]（§4.1 と同じ）
SEC_PER_EPISODE = 7.0  # 所要時間の見積もり用（成功 2〜4 秒、失敗 約 10 秒の平均くらい）

EPISODE_FIELDS = ["scene", "instruction", "seed", "hide_markers", "success", "steps", "wall_s", "chunk_ms_med", "knob", "obj"]


@dataclass(frozen=True)
class Condition:
    exp: str  # "1" / "2" / "3"
    group: str  # 表のまとまり（faucet など、または実験 2 のシーン名）
    scene: str
    label: str  # 表の列名（実験 1・3 は指示文の元タスク名、実験 2 は「言い換え」など）
    instruction: str
    hide_markers: bool = False

    @property
    def is_reference(self) -> bool:
        """シーン本来の定型文を渡す条件か（検定の比較相手）。"""
        return self.instruction == TASK_DESCRIPTIONS[self.scene]


def build_conditions(exps: list[str]) -> list[Condition]:
    conds = []
    for exp, hide, groups in (("1", False, PAIRS), ("3", True, {"faucet": PAIRS["faucet"]})):
        if exp not in exps:
            continue
        for group, tasks in groups.items():
            for scene in tasks:
                for instr_task in tasks:
                    conds.append(Condition(exp, group, scene, instr_task, TASK_DESCRIPTIONS[instr_task], hide))
    if "2" in exps:
        for scene, v in VARIANTS.items():
            r = route(v["ja"])
            assert r.task == scene, f"ルーターが {v['ja']!r} を {r.task} に振り分けました（期待は {scene}）"
            for label, text in (
                ("定型文", TASK_DESCRIPTIONS[scene]),
                ("言い換え", v["言い換え"]),
                ("日本語のまま", v["ja"]),
                ("無関係な文", UNRELATED),
                ("空文字", ""),
                ("ルーター経由", r.instruction),
            ):
                conds.append(Condition("2", scene, scene, label, text))
    return conds


def episode_key(scene: str, instruction: str, seed: int, hide: bool) -> tuple:
    return (scene, instruction, int(seed), int(hide))


def load_episodes(path: Path) -> dict[tuple, dict]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {episode_key(r["scene"], r["instruction"], r["seed"], r["hide_markers"]): r for r in csv.DictReader(f)}


def run(conds: list[Condition], seeds: list[int], args) -> None:
    done = load_episodes(args.episodes)
    todo, first_cond = [], {}
    for seed in seeds:  # seed を外側にして、途中で止めても全条件の N がだいたいそろうようにする
        for c in conds:
            key = episode_key(c.scene, c.instruction, seed, c.hide_markers)
            if key not in done and key not in first_cond:
                todo.append(key)
                first_cond[key] = c
    n_unique = len({episode_key(c.scene, c.instruction, s, c.hide_markers) for c in conds for s in seeds})
    print(f"条件 {len(conds)} 個 × seed {len(seeds)} 個 → 異なるエピソード {n_unique} 話"
          f"（記録済み {n_unique - len(todo)} 話、これから {len(todo)} 話）")
    print(f"所要時間の見積もり：約 {len(todo) * SEC_PER_EPISODE / 60:.0f} 分 ＋ モデル読み込み 16 秒")
    if args.dry_run or not todo:
        return

    vla = load_vla(args.device)
    args.episodes.parent.mkdir(parents=True, exist_ok=True)
    new_file = not args.episodes.exists()
    t_start = time.perf_counter()
    with args.episodes.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EPISODE_FIELDS)
        if new_file:
            writer.writeheader()
        try:
            for i, (scene, instruction, seed, hide) in enumerate(todo, 1):
                video = seed == args.video_seed
                res = run_episode(vla, scene, instruction, seed, args.max_steps, keep_frames=video, hide_goal_markers=bool(hide))
                writer.writerow({**res.row(), "hide_markers": hide})
                f.flush()  # 1 話ごとに書き出す（途中で止めても失わない）
                if video:
                    c = first_cond[(scene, instruction, seed, hide)]
                    name = f"exp{c.exp}_{c.group}_{c.scene}_{c.label}_s{seed}.mp4".replace(" ", "_").replace("/", "_")
                    save_episode_video(res, args.video_dir / name, max_steps=args.max_steps)
                eta = (time.perf_counter() - t_start) / i * (len(todo) - i) / 60
                print(f"[{i}/{len(todo)}] {'成功' if res.success else '失敗'} {res.steps:3d} ステップ {res.wall_s:4.1f} 秒 | "
                      f"{scene} | {instruction[:36]!r} | seed {seed}{' | 印なし' if hide else ''} | 残り約 {eta:.0f} 分",
                      flush=True)
        except KeyboardInterrupt:
            print("\n中断しました。同じコマンドをもう一度実行すると、続きから再開します。")


def summarize(conds: list[Condition], seeds: list[int], args) -> None:
    episodes = load_episodes(args.episodes)
    rows = []
    for c in conds:
        eps = [episodes[k] for s in seeds if (k := episode_key(c.scene, c.instruction, s, c.hide_markers)) in episodes]
        knobs = [float(e["knob"]) for e in eps if e["knob"] not in ("", "None")]
        rows.append({
            "exp": c.exp, "group": c.group, "scene": c.scene, "label": c.label, "instruction": c.instruction,
            "hide_markers": int(c.hide_markers), "n": len(eps), "success": sum(int(e["success"]) for e in eps),
            "knob_open": sum(k > KNOB_TH for k in knobs) if knobs else "",
            "knob_close": sum(k < -KNOB_TH for k in knobs) if knobs else "",
        })
    # 同じ実験・同じシーンで「本来の定型文」を渡した条件と比べる（Fisher の正確確率検定、両側）
    for c, r in zip(conds, rows):
        ref = next((rr for cc, rr in zip(conds, rows) if cc.exp == c.exp and cc.scene == c.scene and cc.is_reference), None)
        r["rate"] = round(r["success"] / r["n"], 3) if r["n"] else ""
        r["p_vs_template"] = ""
        if ref and not c.is_reference and r["n"] and ref["n"]:
            table = [[r["success"], r["n"] - r["success"]], [ref["success"], ref["n"] - ref["success"]]]
            r["p_vs_template"] = float(f"{fisher_exact(table)[1]:.3g}")  # 小さい p が 0.0 に丸められないよう有効数字で

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with args.summary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print_tables(conds, rows)
    print(f"\n集計を書き出しました：{args.summary}")


def cell(r: dict) -> str:
    p = r["p_vs_template"]
    p = "" if p == "" else " (p<0.001)" if float(p) < 0.001 else f" (p={float(p):.3f})"
    return f"{r['success']}/{r['n']}{p}"


def print_tables(conds: list[Condition], rows: list[dict]) -> None:
    by = {(c.exp, c.group, c.scene, c.label): r for c, r in zip(conds, rows)}
    for exp, title in (("1", "実験 1：指示文の入れ替え（行＝シーン、列＝渡した定型文の元タスク）"),
                       ("3", "実験 3：実験 1 の蛇口をゴール印なしで")):
        groups = dict.fromkeys(c.group for c in conds if c.exp == exp)
        if not groups:
            continue
        print(f"\n■ {title}　※ p は同じ行の「本来の定型文」との差の検定")
        for g in groups:
            tasks = PAIRS[g]
            print(f"  [{g}]")
            for scene in tasks:
                print(f"    {scene:16s} " + "   ".join(f"{t}: {cell(by[(exp, g, scene, t)]):16s}" for t in tasks))
            if g == "faucet":
                for t in tasks:
                    rs = [by[(exp, g, scene, t)] for scene in tasks]
                    n = sum(r["n"] for r in rs)
                    print(f"    ハンドル（{t} の定型文、両シーン計 {n} 話）："
                          f"開ける向き {sum(r['knob_open'] or 0 for r in rs)}、閉める向き {sum(r['knob_close'] or 0 for r in rs)}")
    scenes = dict.fromkeys(c.scene for c in conds if c.exp == "2")
    if scenes:
        labels = list(dict.fromkeys(c.label for c in conds if c.exp == "2"))
        print("\n■ 実験 2：指示文の言い方（行＝シーン）　※ p は「定型文」との差の検定")
        for scene in scenes:
            print(f"  {scene}")
            for label in labels:
                r = by[("2", scene, scene, label)]
                print(f"    {label:8s} {cell(r):18s} {r['instruction']!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="入れ替えテスト（実験 1〜3）をまとめて実行・集計する")
    ap.add_argument("--exp", nargs="+", default=["1", "2", "3"], choices=["1", "2", "3"])
    ap.add_argument("--n", type=int, default=20, help="1 条件あたりの話数（seed 0〜n-1）")
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--device", default="mps", help="mps または cpu")
    ap.add_argument("--episodes", type=Path, default=Path("results/episodes.csv"), help="1 話ごとの記録（追記）")
    ap.add_argument("--summary", type=Path, default=Path("results/summary.csv"), help="条件ごとの集計")
    ap.add_argument("--video-seed", type=int, help="この seed のエピソードだけ動画も保存する")
    ap.add_argument("--video-dir", type=Path, default=Path("outputs/experiment"))
    ap.add_argument("--dry-run", action="store_true", help="条件と見積もりを表示するだけ")
    ap.add_argument("--summary-only", action="store_true", help="実行せず、記録済みの結果から集計だけする")
    args = ap.parse_args()

    conds = build_conditions(args.exp)
    seeds = list(range(args.n))
    if not args.summary_only:
        run(conds, seeds, args)
    if not args.dry_run:
        summarize(conds, seeds, args)


if __name__ == "__main__":
    main()
