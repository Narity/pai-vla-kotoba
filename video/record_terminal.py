"""疑似端末（pty）の中でコマンドを実際に動かし、画面に出た文字を時刻つきで記録する（asciinema と同じ方式）。

  uv run python video/record_terminal.py outputs/video/session_a.cast \\
      --input 水を出して --input 料理を作って --input q \\
      -- uv run python -m kotoba_vla.chat --speed 0.5

- 最初に「$ コマンド」を打ち込む様子を入れてから、そのコマンドを疑似端末の中で起動する。
- 画面に「指示> 」が出るたびに、--input の文を 1 文字ずつ打ち込んで Enter を押す（人が打つくらいの速さ）。
- 記録は asciicast v2 形式：1 行目がヘッダ（幅・高さ）、2 行目以降が [経過秒, "o", 画面に出た文字列]。
  render_terminal.py でターミナル風の動画に描き直す。
"""
from __future__ import annotations

import argparse
import codecs
import fcntl
import json
import os
import pty
import random
import select
import shlex
import signal
import struct
import sys
import termios
import time
import unicodedata
from pathlib import Path


def type_delay(ch: str, base: float, rng: random.Random) -> float:
    """1 文字を打つ間隔。全角は少し遅く、ゆらぎを付けて人が打つ感じにする。"""
    wide = unicodedata.east_asian_width(ch) in "WF"
    return base * (1.5 if wide else 0.6) * rng.uniform(0.7, 1.3)


def main() -> None:
    ap = argparse.ArgumentParser(description="疑似端末でコマンドを動かし、画面の出力を asciicast に記録する")
    ap.add_argument("out", type=Path, help="記録の保存先（.cast）")
    ap.add_argument("--input", action="append", default=[], help="プロンプトが出たら打ち込む文（指定した順に使う）")
    ap.add_argument("--prompt", default="指示> ", help="入力を待っている合図になる文字列")
    ap.add_argument("--cols", type=int, default=74)
    ap.add_argument("--rows", type=int, default=27)
    ap.add_argument("--char-delay", type=float, default=0.12, help="1 文字を打つ間隔の目安 [秒]")
    ap.add_argument("--think", type=float, default=1.2, help="プロンプトが出てから打ち始めるまで [秒]")
    ap.add_argument("--timeout", type=float, default=600, help="これを超えたら打ち切る [秒]")
    argv = sys.argv[1:]
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        ap.error("起動するコマンドを -- の後に指定してください")
    split = argv.index("--")
    args = ap.parse_args(argv[:split])
    cmd = argv[split + 1:]

    rng = random.Random(0)
    events: list[list] = []
    t0 = time.monotonic()

    def emit(text: str) -> None:
        events.append([round(time.monotonic() - t0, 4), "o", text])

    # 1) シェルのプロンプトと、コマンドを打ち込む様子（実際に起動するコマンドそのもの）
    time.sleep(0.5)
    emit("$ ")
    time.sleep(0.8)
    for ch in shlex.join(cmd):
        emit(ch)
        time.sleep(type_delay(ch, args.char_delay, rng) * 0.6)
    time.sleep(0.4)
    emit("\r\n")

    # 2) 疑似端末の中で起動する（子プロセス側で画面の大きさを設定してから exec）
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", args.rows, args.cols, 0, 0))
        os.environ["TERM"] = "xterm-256color"
        os.execvp(cmd[0], cmd)

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = list(args.input)
    queue: list[tuple[float, bytes]] = []  # (書き込む時刻, バイト列)：打鍵の予定
    since_enter = ""  # 最後に Enter を押してから画面に出た文字
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.01)
        if ready:
            try:
                data = os.read(fd, 4096)
            except OSError:  # 子プロセスが終わると EIO になることがある
                data = b""
            if not data:
                break
            text = decoder.decode(data)
            if text:
                emit(text)
                since_enter += text
        if pending and not queue and since_enter.endswith(args.prompt):
            line = pending.pop(0)
            at = time.monotonic() + args.think
            for ch in line:
                queue.append((at, ch.encode()))
                at += type_delay(ch, args.char_delay, rng)
            queue.append((at + 0.35, b"\r"))
        while queue and queue[0][0] <= time.monotonic():
            _, data = queue.pop(0)
            os.write(fd, data)
            if data == b"\r":
                since_enter = ""
    else:
        os.kill(pid, signal.SIGTERM)
        print(f"{args.timeout} 秒で打ち切りました")
    os.waitpid(pid, 0)
    os.close(fd)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        f.write(json.dumps({"version": 2, "width": args.cols, "height": args.rows, "title": shlex.join(cmd)}, ensure_ascii=False) + "\n")
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    print(f"記録しました：{args.out}（{events[-1][0]:.1f} 秒、{len(events)} 件）")


if __name__ == "__main__":
    main()
