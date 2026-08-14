#!/usr/bin/env python3
"""
勝利貢献スコアの計算方法を公開するページ public/score.html を作る。

なぜ生成するのか:
  独自の点数を出す以上、「どう計算したのか」を誰でも確かめられる状態に
  しておかないと、都合よく決めた数字と区別がつかない。

  そのうえで、説明を手で書くと必ずコードとずれる。重みを1つ変えたときに
  ページの更新を忘れれば、公開している式と実際の計算が違うことになり、
  黙って嘘をついている状態になる。だからこのページは
  scripts/morning_recap.py と scripts/clutch.py の定数から組み立てる。

  例に出す点数も、その場で contribution() を呼んで計算する。
  ページに載っている数字は、実際に動画で使われる数字と必ず一致する。

使い方:
  python3 scripts/generate_score_page.py --out public/score.html
"""

import argparse
import html
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import clutch  # noqa: E402
import morning_recap as mr  # noqa: E402

SITE_URL = "https://collespo.com/"

STYLE = """
  :root {
    color-scheme: dark;
    --bg: #0B0E14; --surface: #12161F; --border: #232838;
    --text: #F2F0E6; --text-dim: #8891A3; --accent: #FFB020; --jp: #49C5B6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0 auto; padding: 1.5rem 1.25rem 3rem; max-width: 720px;
    background: var(--bg); color: var(--text); line-height: 1.8;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
  }
  a { color: var(--accent); }
  .back { display: inline-block; font-size: 0.85rem; color: var(--text-dim);
          text-decoration: none; margin-bottom: 1.2rem; }
  h1 { font-family: 'Oswald', sans-serif; font-size: 1.6rem;
       color: var(--accent); margin: 0 0 0.3rem; }
  .lead { color: var(--text-dim); font-size: 0.9rem; margin: 0 0 2rem; }
  h2 { font-family: 'Oswald', sans-serif; font-size: 1.2rem; color: var(--text);
       border-bottom: 1px solid var(--border); padding-bottom: 0.4rem;
       margin: 2.4rem 0 1rem; }
  h3 { font-size: 1rem; color: var(--jp); margin: 1.4rem 0 0.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem;
          margin: 0.5rem 0 1rem; }
  th, td { text-align: left; padding: 0.5rem 0.6rem;
           border-bottom: 1px solid var(--border); }
  th { color: var(--text-dim); font-weight: 500; font-size: 0.8rem;
       white-space: nowrap; }
  td.num { text-align: right; font-variant-numeric: tabular-nums;
           white-space: nowrap; }
  .formula { background: #0E121A; border: 1px solid var(--border);
             border-radius: 10px; padding: 0.9rem 1rem; margin: 0.6rem 0;
             font-family: ui-monospace, SFMono-Regular, monospace;
             font-size: 0.85rem; overflow-x: auto; white-space: pre; }
  .note { color: var(--text-dim); font-size: 0.85rem; }
  .big { color: var(--jp); font-weight: 700; }
  .updated { color: var(--text-dim); font-size: 0.8rem; margin-top: 2.5rem; }
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


# 例に出す成績。点数はここでは書かず、その場で計算する。
EXAMPLES = [
    ("9回 13奪三振 被安打0 自責0 四球0",
     dict(type="pitcher", ip="9.0", so=13, hits=0, er=0, bb=0)),
    ("9回 12奪三振 被安打2 自責0 四球1",
     dict(type="pitcher", ip="9.0", so=12, hits=2, er=0, bb=1)),
    ("7回 8奪三振 被安打4 自責1 四球2",
     dict(type="pitcher", ip="7.0", so=8, hits=4, er=1, bb=2)),
    ("6回 5奪三振 被安打6 自責3 四球2",
     dict(type="pitcher", ip="6.0", so=5, hits=6, er=3, bb=2)),
    ("1回 2奪三振 無失点（中継ぎ）",
     dict(type="pitcher", ip="1.0", so=2, hits=0, er=0, bb=1)),
    ("3回 被安打9 自責7 四球4",
     dict(type="pitcher", ip="3.0", so=2, hits=9, er=7, bb=4)),
    ("5打数3安打 3本塁打 7打点",
     dict(type="batter", ab=5, hits=3, hr=3, rbi=7, bb=0, so=1)),
    ("4打数2安打 1本塁打 3打点",
     dict(type="batter", ab=4, hits=2, hr=1, rbi=3, bb=0, so=1)),
    ("4打数2安打 1本塁打 3打点（逆転3ラン）",
     dict(type="batter", ab=4, hits=2, hr=1, rbi=3, bb=0, so=1,
          clutch_points=clutch.CLUTCH_POINTS["逆転"])),
    ("4打数2安打 1打点",
     dict(type="batter", ab=4, hits=2, hr=0, rbi=1, bb=0, so=1)),
    ("5打数0安打 3三振",
     dict(type="batter", ab=5, hits=0, hr=0, rbi=0, bb=0, so=3)),
]

TWO_WAY_EXAMPLE = {
    "type": "two_way",
    "pitching": dict(type="pitcher", ip="7.0", so=10, hits=3, er=0, bb=1),
    "batting": dict(type="batter", ab=4, hits=3, hr=3, rbi=6, bb=0, so=0),
}


def render() -> str:
    rows = []
    for label, row in EXAMPLES:
        v = mr.contribution(row)
        shown = mr.score_label(row) or "非表示"
        cls = ' class="big"' if v >= mr.STANDOUT else ""
        rows.append(f"<tr><td>{esc(label)}</td>"
                    f'<td class="num"{cls}>{v}</td>'
                    f'<td class="num">{esc(shown)}</td></tr>')

    two = mr.contribution(TWO_WAY_EXAMPLE)

    clutch_rows = "".join(
        f"<tr><td>{esc(k)}</td><td class=\"num\">+{v}</td>"
        f"<td class=\"note\">{esc(clutch.CLUTCH_NOTES.get(k, ''))}</td></tr>"
        for k, v in sorted(clutch.CLUTCH_POINTS.items(),
                           key=lambda x: -x[1])
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
<title>勝利貢献スコアの計算方法 | コレスポ</title>
<meta name="description" content="コレスポが日本人選手の1日を採点している「勝利貢献スコア」の計算式を全て公開しています。投手と打者を同じ物差しに載せ、逆転・サヨナラなどの場面を加点します。" />
<link rel="canonical" href="{SITE_URL}score.html" />
<meta property="og:title" content="勝利貢献スコアの計算方法 | コレスポ" />
<meta property="og:description" content="投手と打者を同じ物差しで採点する計算式を公開しています。" />
<meta property="og:url" content="{SITE_URL}score.html" />
<link rel="apple-touch-icon" href="icons/icon-192.png" />
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{STYLE}</style>
</head>
<body>
  <a class="back" href="index.html">&larr; コレスポ トップへ</a>
  <h1>勝利貢献スコアの計算方法</h1>
  <p class="lead">コレスポが日本人選手の1日を採点している数字です。
  投手と打者を同じ物差しに載せて、その日いちばん効いた選手を並べるために使います。
  公式の指標ではなく、コレスポが決めた計算です。だからこそ、
  計算式を全部そのまま載せています。</p>

  <h2>考え方</h2>
  <p>その日の成績だけで決まります。人気や知名度、期待、印象は一切入りません。
  同じ成績なら、誰であっても同じ点になります。</p>
  <p class="note">このページは計算しているコードそのものから自動で作っています。
  重みを変えればこのページの数字も変わるので、
  ここに書いてある式と実際の計算がずれることはありません。</p>

  <h2>投手</h2>
  <p>ビル・ジェームズが考案したゲームスコアを土台にしています。
  広く使われている計算なので、こちらで重みを決めた部分がほとんどありません。</p>
  <div class="formula">アウト数 = 投球回 × 3（"6.1" は6回3分の1＝19アウト）

素点 = アウト数
     + 2 × (アウト数 - 12 を下回らない分)   ← 5回を超えて投げた分
     + 奪三振
     - 2 × 被安打
     - 4 × 自責点
     - 四球

基準点 = 25 + 20 × min(1, アウト数 ÷ 15)    ← 5回で満額
スコア = 基準点 + 素点 × 1.2</div>
  <p class="note">基準点が投球回で動くのは、1イニングの好投と7イニングの好投を
  同じ扱いにしないためです。基準点を固定にしていたとき、
  1回を無失点で抑えた中継ぎが4打数2安打1打点の打者を上回りました。</p>

  <h2>打者</h2>
  <div class="formula">塁打 = 安打 + 3 × 本塁打
       ↑ 二塁打・三塁打はこの取得方法では分からないため、近似しています

素点 = 2 × 塁打 + 2 × 打点 + 四球 - 三振
スコア = 30 + 素点 × 2.4</div>

  <h2>場面による加点</h2>
  <p>同じ3ランでも、逆転と大差での1本では試合への効き方が違います。
  打った時点の点差から、次のように加点します。</p>
  <table>
    <tr><th>場面</th><th>加点</th><th>意味</th></tr>
    {clutch_rows}
  </table>
  <p class="note">点差はMLB公式のプレーごとの記録から機械的に判定しています。
  1日に複数該当した場合は、それぞれ加算されます。</p>

  <h2>投げて打った日</h2>
  <p>両方に出場した日は、投手としてのスコアと打者としてのスコアを足します。</p>
  <p>例）7回10奪三振無失点 ＋ 4打数3安打3本塁打6打点
  → <span class="big">{two}点</span></p>

  <h2>上限と下限</h2>
  <p>上限はありません。完封や3本塁打のような日は100を超えます。
  {mr.STANDOUT}点以上は、画面でも色と大きさを変えて表示します。</p>
  <p>下限は0で止めます。また{mr.HIDE_BELOW}点を下回る日は、
  成績だけを載せて点数を表示しません。0点と書くことに意味が無いためです。
  順位の並びには使います。</p>

  <h2>実際の点数</h2>
  <table>
    <tr><th>成績</th><th>スコア</th><th>画面表示</th></tr>
    {''.join(rows)}
  </table>

  <h2>前回との比較</h2>
  <p>点数の隣に「前回◯◯」と増減を出しています。前回とは、
  投手ならその選手の前の登板、打者なら前の出場試合です。
  出ていない日は数えません。</p>
  <p>比べる相手の点数も、同じ計算式で出しています。
  投げて打った日は投打を合計した点数どうしを比べます。</p>

  <h2>直近の平均</h2>
  <p>投手は直近{mr.RECENT_GAMES_PITCHER}登板、
  打者は直近{mr.RECENT_GAMES_BATTER}試合の平均です。
  いずれもその日を含まず、それより前だけを見ています。</p>
  <p>投手だけ本数が少ないのは、先発投手の{mr.RECENT_GAMES_BATTER}登板が
  1か月半前まで遡ってしまい、「直近」と呼べなくなるためです。</p>
  <p>元にしているのはMLB公式の1試合ごとの成績で、
  シーズン開幕まで遡って計算しています。</p>

  <h2>所属</h2>
  <p>選手名の下に出している所属は、その選手が最後に出場した試合の球団です。
  移籍した場合は移籍後の球団になります。</p>

  <h2>この数字でできないこと</h2>
  <p>守備、走塁、四球を選んで繋いだ場面、球数、相手打線の強さは入っていません。
  取得している成績にそれらが含まれていないためです。
  1日の中で並べるための数字で、シーズンを通した選手の評価には使えません。</p>

  <p class="note">用語の意味は<a href="glossary.html">用語集</a>にまとめています。</p>
  <a class="back" href="index.html">&larr; コレスポ トップへ</a>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public/score.html")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    print(f"[done] {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
