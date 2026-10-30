"""日本語の指示 → Meta-World のタスク名と、VLA に渡す英語の定型文（キーワード辞書版）。

「対象」と「動作」をそれぞれ 1 つだけ見つけられたときに限って実行する。
見つからない・複数ある・否定の指示は、実行せずに理由を返す（安全側の設計）。

  uv run python -m kotoba_vla.router 蛇口を閉めて 料理を作って
"""
from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass

from lerobot.envs.metaworld import TASK_DESCRIPTIONS

# 対象：表記ゆれ → 内部名
OBJECTS = {
    "faucet": ("蛇口", "じゃぐち", "ジャグチ", "水道", "すいどう", "水"),
    "drawer": ("引き出し", "引出し", "引出", "ひきだし", "ヒキダシ", "抽斗"),
    "window": ("窓", "まど", "マド", "ウィンドウ", "ウインドウ"),
    "door": ("ドア", "どあ", "扉", "とびら"),
    "button": ("ボタン", "ぼたん", "スイッチ"),
}
# 動作：表記ゆれ → 内部名（「水を出して」「水を止めて」「時計回りに回して」も拾う）
ACTIONS = {
    "open": ("開け", "開い", "開く", "あけ", "ひらい", "ひらく", "出し", "出す", "反時計回り", "反時計", "左回り", "左に回"),
    "close": ("閉め", "閉じ", "閉ま", "しめ", "とじ", "止め", "とめ", "時計回り", "右回り", "右に回"),
    "press": ("押し", "押す", "おし", "おす"),
}
NEGATIONS = ("ないで", "ないように", "なくていい", "なくて良い", "するな", "やめて")

TASKS = {
    ("faucet", "open"): "faucet-open-v3",
    ("faucet", "close"): "faucet-close-v3",
    ("drawer", "open"): "drawer-open-v3",
    ("drawer", "close"): "drawer-close-v3",
    ("window", "open"): "window-open-v3",
    ("window", "close"): "window-close-v3",
    ("door", "open"): "door-open-v3",
    ("door", "close"): "door-close-v3",
    ("button", "press"): "button-press-v3",
}
JA_NAME = {
    "faucet": "蛇口", "drawer": "引き出し", "window": "窓", "door": "ドア", "button": "ボタン",
    "open": "開ける", "close": "閉める", "press": "押す",
}


@dataclass(frozen=True)
class Route:
    task: str | None  # Meta-World のタスク名（実行しないときは None）
    instruction: str | None  # VLA に渡す英語の定型文
    reason: str  # 判定の根拠、または断った理由（画面表示・レポート用）

    @property
    def ok(self) -> bool:
        return self.task is not None


def _find(text: str, table: dict[str, tuple[str, ...]]) -> tuple[set[str], str]:
    """table のキーワードを長い順に探し、見つかったラベルの集合と「使った部分を伏せた」文を返す。
    伏せるのは、「引き出し」の中の「出し」や「反時計回り」の中の「時計回り」を二重に数えないため。"""
    found = set()
    pairs = sorted(((kw, label) for label, kws in table.items() for kw in kws), key=lambda p: -len(p[0]))
    for kw, label in pairs:
        if kw in text:
            found.add(label)
            text = text.replace(kw, "＿" * len(kw))
    return found, text


def route(text: str) -> Route:
    t = "".join(unicodedata.normalize("NFKC", text).split())  # 全角・半角をそろえ、空白を除く
    if not t:
        return Route(None, None, "指示が空です")
    if any(neg in t for neg in NEGATIONS):
        return Route(None, None, "否定の指示（〜しないで など）は実行しません")

    objs, rest = _find(t, OBJECTS)
    acts, _ = _find(rest, ACTIONS)
    if not objs:
        return Route(None, None, f"対象（{'・'.join(JA_NAME[o] for o in OBJECTS)}）が見つかりません")
    if len(objs) > 1:
        return Route(None, None, f"対象が複数あります（{'・'.join(JA_NAME[o] for o in sorted(objs))}）")
    if not acts:
        return Route(None, None, f"動作（{'・'.join(JA_NAME[a] for a in ACTIONS)}）が見つかりません")
    if len(acts) > 1:
        return Route(None, None, f"動作が複数あります（{'・'.join(JA_NAME[a] for a in sorted(acts))}）")

    obj, act = objs.pop(), acts.pop()
    task = TASKS.get((obj, act))
    if task is None:
        return Route(None, None, f"{JA_NAME[obj]}を{JA_NAME[act]}作業には対応していません")
    return Route(task, TASK_DESCRIPTIONS[task], f"対象＝{JA_NAME[obj]}、動作＝{JA_NAME[act]}")


def capabilities() -> str:
    """できる作業の一覧（ヘルプ表示用）。"""
    by_obj: dict[str, list[str]] = {}
    for obj, act in TASKS:
        by_obj.setdefault(JA_NAME[obj], []).append(JA_NAME[act])
    return "、".join(f"{obj}を{'／'.join(acts)}" for obj, acts in by_obj.items())


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["蛇口を閉めて"]:
        r = route(arg)
        print(f"{arg!r:24s} → {r.task or '（実行しない）'}  {r.instruction or ''}  ［{r.reason}］")
