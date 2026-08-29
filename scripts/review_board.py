#!/usr/bin/env python3
"""
その日出したものを、立場の違う5人が見て指摘する。

なぜ要るのか:
  数字は「どうだったか」しか教えない。維持率が16%だと分かっても、
  何をどう直せばよいかは出てこない。人が見れば言えることが、
  誰も見ていないので言われないまま毎日過ぎていく。

  実際そうなっていた。「返信が54件ついた一言があります」で始まる回は
  4日間出続けたし、選手個人のハイライトの題が英語で切れたまま
  投稿されたのも、誰も見なかったからではなく、見た人がいなかったから。

  だから見る人を置く。ただし1人ではなく5人。同じ動画でも、
  何を見るかで指摘が変わる。戦略の目には「今日と昨日の繋がり」が、
  作り手の目には「1秒目の掴み」が、経営の目には「これで続くのか」が
  見える。1つの視点で回すと、その視点の死角がそのまま死角になる。

やること・やらないこと:
  ここが出すのは**制作側への指摘**であって、動画に載せる文章ではない。
  だから推測も意見も構わない。事実として視聴者に出すものとは
  扱いが違う。混ぜないために、出力先も実行ページだけにしてある。

  逆に、ここで出た指摘をそのまま動画に入れることはしない。
  入れるとしたら、人が読んで判断してからになる。

費用:
  1人1回、Haikuで5回。1日あたり$0.02前後。
  token_log の上限($0.50/日)の中に収まる。上限に当たった日は黙って
  飛ばす(動画を出すほうが先で、講評は明日でも困らない)。

出力: 実行ページ(GITHUB_STEP_SUMMARY)と標準出力

使い方:
  ANTHROPIC_API_KEY=xxx python3 scripts/review_board.py
"""

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import post_common  # noqa: E402
import token_log  # noqa: E402

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"
JST = timezone(timedelta(hours=9))

# 見る人たち。
#
# 立場と、その立場が何を見るかを書く。名前を付けるのは、指摘が
# どの角度から来たのかを読む側が分かるようにするため。
# 「誰が言ったか」ではなく「どの立場から見たか」の札。
#
# 5人にしてあるのは、これ以上増やしても指摘が重なるため。
# 実際に立場が違って、見るものが被らない組み合わせを選んである。
PANEL = (
    ("戦略",
     "チャンネル全体の設計を見る立場。1本ごとの出来ではなく、"
     "枠どうしの関係、昨日との繋がり、続けたときに積み上がるかを見る。"
     "「この枠は他の枠と何が違うのか」「毎日見る理由になっているか」を問う。"),
    ("伸ばす",
     "ショート動画で人を集めることに詳しい立場。最初の1〜2秒、題、"
     "サムネイル、離脱の起きる位置を見る。"
     "「開く理由があるか」「最後まで見る理由があるか」を問う。"),
    ("経営",
     "続けられるかを見る立場。費用、手間、失敗したときの損、"
     "規約上の危うさを見る。「これは来月も回るのか」"
     "「壊れたとき誰が気づくのか」を問う。"),
    ("作り手",
     "画面と言葉を作る立場。読み上げの流れ、言葉の選び方、"
     "画面の情報量、間の取り方を見る。"
     "「聞いて分かるか」「見て分かるか」を問う。"),
    ("運営者",
     "このチャンネルを毎日回している本人の立場。事実に基づくこと、"
     "嘘を書かないこと、視聴者に対して誠実であることを何より重んじる。"
     "「これは本当か」「言い切ってよいのか」「前提が伝わるか」を問う。"),
)

# 1人あたりの指摘の上限。多いと読まれない。
MAX_POINTS = 3


def out(line: str = "") -> None:
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + chr(10))


def _load(path: str, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def gather(day: str = None) -> str:
    """その日出したものと、いまの数字を並べる。これが講評の材料になる。"""
    day = day or datetime.now(JST).strftime("%Y-%m-%d")
    lines = [f"## {day} に出したもの", ""]

    vids = _load("data/published_videos.json")
    at = {k: t for k, _, _, t in post_common.DAILY_LINEUP}
    for kind, name, what, when in post_common.DAILY_LINEUP:
        rec = (vids.get(kind) or {}).get(day)
        if rec:
            lines.append(f"- {when} {name}: {rec.get('title', '')}")
        else:
            lines.append(f"- {when} {name}: **出ていない**")

    # 枠ごとの実測。指摘を「なんとなく」ではなく数字に紐づけるため。
    an = _load("data/analytics.json").get("days") or {}
    if an:
        latest = sorted(an)[-1]
        rows = [v for v in (an[latest].get("videos") or [])
                if (v.get("views") or 0) >= 50 and v.get("averageViewPercentage")]
        if rows:
            lines += ["", f"## 視聴の実測（{latest} 時点・50回以上）", ""]
            kind_of = {}
            for k, by_day in vids.items():
                if isinstance(by_day, dict):
                    for r in by_day.values():
                        if isinstance(r, dict) and r.get("video_id"):
                            kind_of[r["video_id"]] = k
            agg = {}
            for v in rows:
                k = kind_of.get(v.get("video"))
                if not k:
                    continue
                pct = v["averageViewPercentage"]
                agg.setdefault(k, []).append(
                    (pct, (v.get("averageViewDuration") or 0) / (pct / 100),
                     v.get("views") or 0))
            # 中央値で出す。平均だと繰り返し見られた動画(100%超)に
            # 引っ張られる。実際 morning は平均106%で、それを見せられても
            # 「10割を超えている」としか読めない。
            def _med(xs):
                xs = sorted(xs)
                m = len(xs)
                return xs[m // 2] if m % 2 else (xs[m // 2 - 1] + xs[m // 2]) / 2

            for k, vs in sorted(agg.items(),
                                key=lambda x: -_med([y[0] for y in x[1]])):
                lines.append(
                    f"- {at.get(k, '—')} {k}: 視聴継続 "
                    f"{_med([y[0] for y in vs]):.1f}% / "
                    f"長さ {_med([y[1] for y in vs]):.0f}秒 / "
                    f"再生 {_med([y[2] for y in vs]):.0f}回（{len(vs)}本）")

    # 使っている費用。経営の目に要る。
    s = token_log.summary()
    if s:
        lines += ["", "## 費用", "",
                  f"- APIの使用: ${s['avg_usd']:.3f}/日（月あたり "
                  f"${s['month_usd']:.2f}）"]
        if s.get("days_left") is not None:
            lines.append(f"- 残高 ${s['balance']:.2f}、このペースで"
                         f"あと{s['days_left']}日")
    return chr(10).join(lines)


def ask(client, label: str, stance: str, material: str) -> str:
    """1人ぶんの講評。"""
    prompt = (
        "コレスポという日本語のスポーツ動画チャンネルの、今日の成果物です。"
        "MLBと欧州サッカーを扱い、全て自動生成しています。"
        "登録者は14人、視聴の97.6%が日本からです。" + chr(10) + chr(10)
        + f"あなたの立場: {stance}" + chr(10) + chr(10)
        + material + chr(10) + chr(10)
        + "この立場から見て、直すべきところを指摘してください。" + chr(10)
        + "条件:" + chr(10)
        + f"- {MAX_POINTS}点まで。少なくてよい。無ければ「無し」と書く" + chr(10)
        + "- 上に出ている題・数字を必ず名指しする。一般論を書かない" + chr(10)
        + "- 「良かった」で終わらせない。直す先を書く" + chr(10)
        + "- 1点につき2文まで" + chr(10)
        + "- 他の立場が言いそうなことは書かない。自分の立場に絞る" + chr(10)
        + "- 箇条書き。前置きは不要"
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    token_log.record(f"review:{label}", MODEL, resp)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="見る日 (既定は今日のJST)")
    ap.add_argument("--only", help="この立場だけ (戦略/伸ばす/経営/作り手/運営者)")
    args = ap.parse_args()

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not (key and anthropic is not None):
        out("**講評: ANTHROPIC_API_KEY が渡っていません**")
        return 0
    if not token_log.allowed("review_board"):
        return 0

    material = gather(args.date)
    print(material)
    client = anthropic.Anthropic(api_key=key)

    out("## 今日の講評")
    out()
    out("立場の違う5人が、今日出したものを見て指摘したものです。"
        "**動画に載せる文章ではありません**。制作側への指摘なので、"
        "推測や意見も含みます。")
    out()
    for label, stance in PANEL:
        if args.only and args.only != label:
            continue
        try:
            said = ask(client, label, stance, material)
        except Exception as e:                   # noqa: BLE001
            out(f"### {label}")
            out(f"（講評できませんでした: {type(e).__name__}）")
            out()
            continue
        out(f"### {label}")
        out()
        out(said)
        out()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
