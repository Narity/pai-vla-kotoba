"""docs/report.md から、提出用の PDF（docs/report.pdf）を作る。

  uv run python docs/build_report.py

Markdown を HTML（docs/report.html）に変換し、Google Chrome のヘッドレスモードで A4 の PDF に印刷する。
mermaid の図は印刷の前に mermaid.js（CDN）で描くので、インターネット接続が必要。
"""
from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
CSS = """
@page { size: A4; margin: 15mm 16mm 16mm; }
body { font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", sans-serif; font-size: 9.6pt; line-height: 1.7;
       color: #1b1d21; margin: 0; }
h1 { font-size: 19pt; margin: 0 0 2pt; letter-spacing: 0.02em; }
h1 + h2 { font-size: 11.5pt; font-weight: 600; color: #3b4048; border: none; margin: 0 0 4pt; padding: 0; }
h2 { font-size: 12.5pt; margin: 14pt 0 5pt; padding-bottom: 2pt; border-bottom: 1.5px solid #2a78d6; break-after: avoid; }
h3 { font-size: 10.5pt; margin: 10pt 0 3pt; break-after: avoid; }
p { margin: 4pt 0; }
ul, ol { margin: 3pt 0; padding-left: 18pt; }
li { margin: 1.5pt 0; }
.meta { color: #5a6270; font-size: 8.8pt; margin-bottom: 8pt; }
table { border-collapse: collapse; width: 100%; font-size: 8.6pt; margin: 6pt 0; break-inside: avoid; }
th, td { border: 1px solid #c9ced6; padding: 2.5pt 6pt; vertical-align: top; text-align: left; }
th { background: #eef3fb; }
code { font-family: Menlo, monospace; font-size: 8.2pt; background: #f2f4f7; padding: 0 2px; border-radius: 2px; }
figure { margin: 8pt 0; break-inside: avoid; text-align: center; }
figure img { width: 100%; }
figure.narrow img { width: 82%; }
figcaption, .caption { font-size: 8.4pt; color: #4a515c; text-align: left; margin: 3pt 0 6pt; }
pre.mermaid { background: none; text-align: center; margin: 6pt 0 0; font-size: 9pt; }
"""
TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>その指示、ほんとうに聞いてる？（最終課題レポート）</title>
<style>{css}</style>
<script src="{mermaid}"></script>
<script>mermaid.initialize({{ startOnLoad: true, theme: "neutral",
  fontFamily: '"Hiragino Sans", sans-serif', flowchart: {{ htmlLabels: true }} }});</script>
</head>
<body>
{body}
</body>
</html>
"""


def main() -> None:
    text = (DOCS / "report.md").read_text()
    # ```mermaid のブロックは、mermaid.js が描く <pre class="mermaid"> に置き換える
    text = re.sub(r"```mermaid\n(.*?)```", lambda m: f'<pre class="mermaid">{html.escape(m.group(1))}</pre>',
                  text, flags=re.S)
    body = markdown.markdown(text, extensions=["tables"])
    page = DOCS / "report.html"
    page.write_text(TEMPLATE.format(css=CSS, mermaid=MERMAID, body=body))
    pdf = DOCS / "report.pdf"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=20000",
                    f"--print-to-pdf={pdf}", page.as_uri()], check=True, capture_output=True)
    print(f"{page.name} と {pdf.name} を書き出しました")


if __name__ == "__main__":
    main()
