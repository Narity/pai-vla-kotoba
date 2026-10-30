import pytest

from kotoba_vla.router import route


@pytest.mark.parametrize(
    "text, task",
    [
        ("蛇口を閉めて", "faucet-close-v3"),
        ("蛇口を開けて", "faucet-open-v3"),
        ("じゃぐちをあけて", "faucet-open-v3"),
        ("水を止めて", "faucet-close-v3"),
        ("水を出してください", "faucet-open-v3"),
        ("蛇口を反時計回りに回して", "faucet-open-v3"),  # 「反時計回り」の中の「時計回り」を数えない
        ("蛇口を時計回りに回して", "faucet-close-v3"),
        ("引き出しを閉めて", "drawer-close-v3"),  # 「引き出し」の中の「出し」を「開ける」と数えない
        ("ひきだしをあけて", "drawer-open-v3"),
        ("窓を開けてください", "window-open-v3"),
        ("まどをしめて", "window-close-v3"),
        ("ｳｲﾝﾄﾞｳを閉じて", "window-close-v3"),  # 半角カナ
        ("　蛇口を 閉めて　", "faucet-close-v3"),  # 全角・半角の空白
        ("ドアを開けて", "door-open-v3"),
        ("扉を閉めてください", "door-close-v3"),
        ("ボタンを押して", "button-press-v3"),
    ],
)
def test_routes(text, task):
    r = route(text)
    assert r.ok and r.task == task
    assert r.instruction  # 英語の定型文が付いている


@pytest.mark.parametrize(
    "text",
    [
        "",
        "料理を作って",  # 対象なし
        "蛇口",  # 動作なし
        "蛇口と窓を開けて",  # 対象が複数
        "蛇口を開けて閉めて",  # 動作が両方
        "蛇口を開けないで",  # 否定
        "ボタンを開けて",  # 対応していない組み合わせ
    ],
)
def test_refuses(text):
    r = route(text)
    assert not r.ok and r.task is None and r.reason
