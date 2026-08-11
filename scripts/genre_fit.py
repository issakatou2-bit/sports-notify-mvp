#!/usr/bin/env python3
"""
コレスポの仕組みが、どのジャンルに移しやすいかを採点する。

    python3 scripts/genre_fit.py
    python3 scripts/genre_fit.py --detail 競馬

なぜスクリプトにするのか:
  「このジャンルは向いている」と文章で書くと、根拠が読めず、
  後から重みを変えて考え直すこともできない。判定条件と点を
  データとして持てば、条件を1つ足したときに順位がどう動くか
  その場で確かめられる。

重みの根拠:
  コレスポで実際に効いた・効かなかったことから決めている。
  推測で置いた重みには、下のコメントでその旨を書いてある。

点数の性格:
  各ジャンルの点は「調べれば決まる事実」(APIの有無など)と
  「こちらの見立て」(日本語情報の薄さなど)が混ざっている。
  見立ての部分は外れうるので、順位そのものより
  「どの条件で落ちたか」を読む方が使える。
"""

import argparse
import sys

# --- 判定条件 ---------------------------------------------------------------
# (キー, 表示名, 重み, なぜこの重みなのか)
CRITERIA = [
    ("api", "毎日更新される公開データがある", 5.0,
     "日次配信が成立するかどうかがここで決まる。コレスポの日次は"
     "MLB Stats APIに全面的に依存していて、これが無い日は配信自体が無い。"
     "代替不能なので最大の重み。"),

    ("choice", "1日に複数の候補があり、選ぶ余地がある", 4.0,
     "「今日のどれを見るか」が商品そのもの。MLBは1日最大15試合あり、"
     "だから選定に意味がある。候補が1つしかない日は、"
     "選定ではなく単なる告知になり、価値が落ちる。"),

    ("explainable", "選んだ理由をデータで説明できる", 4.0,
     "コレスポの独自性は理由づけにある。順位・成績・日程から"
     "理由が組み立てられないジャンルでは、感想文にしかならない。"),

    ("deadline", "見逃すと価値が消える(締め切りがある)", 3.5,
     "毎日開く理由になる。生中継のあるジャンルは強い。"
     "いつ読んでもいい情報は、日次で出す必然性が無い。"),

    ("jp_thin", "日本語の一次情報が薄い", 3.0,
     "薄いほど翻訳・要約の価値が出る。ただしコレスポでは"
     "この効果を数字で確かめられていないので、見立ての重み。"),

    ("roster", "固有名詞の名簿が有限で安定している", 2.5,
     "実装コストに直結する。MLBは30球団・日本人16人で、"
     "名簿が固定できたから成立した。名簿が数千件あったり"
     "毎週入れ替わるジャンルは、保守が回らない。"),

    ("archive", "蓄積が検索資産になる", 3.0,
     "選手ページはこの狙いで作った。日付ページだけでは"
     "「大谷翔平 今日 試合」のような最大の検索需要を取りこぼす。"
     "積み上げが効くかどうか。"),

    ("rights", "映像を使わずに、事実の提示だけで成立する", 4.0,
     "映像の権利が要るジャンルは個人では詰む。コレスポは"
     "スコアと日程と順位だけで成立している。ここが0なら"
     "他が満点でも作れないので、実質的な足切り。"),

    ("evergreen", "日付に依存しない資産(用語・歴史・一覧)が作れる", 2.5,
     "オフシーズンの在庫と検索流入。資産動画19本ぶんの効果。"
     "ただし日次が回っていることが前提の、上乗せ要素。"),
]

MAX_SCORE = sum(w for _, _, w, _ in CRITERIA) * 5

# --- ジャンル ---------------------------------------------------------------
# 点は0〜5。noteには、その点にした理由のうち特に効いたものを書く。
GENRES = [
    ("NBA", dict(api=5, choice=5, explainable=5, deadline=5, jp_thin=4,
                 roster=4, archive=5, rights=4, evergreen=5),
     "MLBとほぼ同じ形。公式のStats APIがあり、1日5〜12試合、"
     "順位・連勝・個人成績がそのまま理由になる。日本人選手が少ないぶん"
     "「日本人が出る試合」という軸は弱く、代わりにスター選手軸で作る。"
     "コレスポのコードをそのまま流用できる度合いが最も高い。"),

    ("欧州サッカー(実装済み)", dict(api=4, choice=5, explainable=5, deadline=5,
                          jp_thin=3, roster=4, archive=4, rights=4, evergreen=5),
     "実装済み。football-data.orgの無料枠は順位と日程は取れるが"
     "個人成績が無く、理由づけの材料がMLBより薄い。"
     "日本人選手が25人いるので名簿軸は強い。"),

    ("NFL", dict(api=4, choice=3, explainable=5, deadline=5, jp_thin=4,
                 roster=4, archive=4, rights=4, evergreen=5),
     "週1開催なので日次の在庫が作れない(choiceが低い)。"
     "週次・レビュー中心なら成立する。データと解説の相性は非常に良い。"),

    ("競馬", dict(api=3, choice=5, explainable=5, deadline=5, jp_thin=1,
                  roster=2, archive=4, rights=3, evergreen=4),
     "毎日開催・多レース・データ豊富と、条件は非常に良い。"
     "ただし日本語の情報が飽和していて(jp_thin=1)、"
     "既存メディアと個人サイトが厚い。馬の名簿は毎年入れ替わり保守が重い。"
     "予想に踏み込むと性格が変わるので、"
     "「どのレースが注目か」に留めるなら成立する。"),

    ("F1", dict(api=3, choice=2, explainable=4, deadline=5, jp_thin=3,
                roster=5, archive=3, rights=3, evergreen=5),
     "年24戦で日次にならない。ドライバー20人・10チームと名簿が"
     "極めて安定しているので資産動画は作りやすい。"
     "レース週だけ動かす作りなら合う。"),

    ("大相撲", dict(api=2, choice=4, explainable=4, deadline=5, jp_thin=1,
                  roster=3, archive=3, rights=3, evergreen=4),
     "本場所中は毎日15日間あり日次に向く。ただし年6場所・90日で"
     "年の3/4が空く。公式APIが無くスクレイピング前提。"
     "日本語情報も厚い。"),

    ("eスポーツ(LoL/Valorant)", dict(api=4, choice=4, explainable=4, deadline=4,
                                jp_thin=4, roster=2, archive=3, rights=4,
                                evergreen=4),
     "Riotが公開APIを出していてデータは取れる。"
     "選手・チームの入れ替わりが激しく名簿の保守が重い(roster=2)。"
     "視聴者層がYouTubeと重なるのは有利。"),

    ("将棋", dict(api=2, choice=3, explainable=3, deadline=4, jp_thin=1,
                 roster=4, archive=4, rights=2, evergreen=5),
     "公式APIが無い。棋譜の扱いに権利上の注意が要る(rights=2)。"
     "対局は日に数局で選ぶ余地が小さい。棋士の名簿は安定していて"
     "用語・戦法の資産動画は非常に作りやすい。"),

    ("MLB(実装済み)", dict(api=5, choice=5, explainable=5, deadline=5,
                      jp_thin=4, roster=5, archive=5, rights=4, evergreen=5),
     "基準。全条件が揃っている。無料の公式APIが個人成績まで返し、"
     "1日15試合、日本人16人、オフに資産動画。"),

    ("天文(流星群・惑星・日食)", dict(api=4, choice=2, explainable=4, deadline=5,
                            jp_thin=2, roster=5, archive=2, rights=5,
                            evergreen=5),
     "イベントが年に数十回しかなく日次にならない(choice=2)。"
     "ただし完全に計算で決まるので、何年先まででも自動生成できる。"
     "資産動画との相性は全ジャンル中でも高い。"),

    ("新作ゲーム/大型アップデート", dict(api=3, choice=4, explainable=3, deadline=3,
                              jp_thin=3, roster=1, archive=3, rights=3,
                              evergreen=3),
     "SteamのAPIはあるが、注目度を数字で説明しにくい(explainable=3)。"
     "対象タイトルが際限なく増えるので名簿が閉じない(roster=1)。"),

    ("映画/配信作品の公開日", dict(api=4, choice=4, explainable=2, deadline=3,
                          jp_thin=2, roster=1, archive=3, rights=2,
                          evergreen=3),
     "TMDbなどでデータは取れるが、「なぜ注目か」が評価や話題性に"
     "寄るためデータで説明しづらい(explainable=2)。画像の権利も要注意。"),

    ("arXiv/論文", dict(api=5, choice=5, explainable=3, deadline=2, jp_thin=5,
                    roster=1, archive=5, rights=4, evergreen=3),
     "APIは完璧、日本語情報は最も薄い。ただし締め切りが無く"
     "(deadline=2)「今日見なければ」が作れない。"
     "重要度をデータで判定するのが難しく、被引用数は数か月遅れる。"),

    ("株式・為替", dict(api=4, choice=5, explainable=4, deadline=5, jp_thin=1,
                   roster=3, archive=4, rights=3, evergreen=4),
     "条件は揃うが、助言と受け取られる領域に踏み込みやすい。"
     "「なぜ動いたか」の説明は、外すと実害が出る。"
     "情報も飽和している。他の条件が良いだけに、"
     "避ける理由が採点の外にある例。"),

    ("気象・防災", dict(api=5, choice=3, explainable=4, deadline=5, jp_thin=1,
                   roster=2, archive=2, rights=5, evergreen=3),
     "気象庁のデータは公開されていて質も高い。"
     "ただし誤りが実害に直結し、公式が既に十分な発信をしている。"
     "個人が上乗せする余地が小さい。"),

    ("アニメ放送スケジュール", dict(api=4, choice=5, explainable=2, deadline=4,
                         jp_thin=1, roster=1, archive=3, rights=2,
                         evergreen=3),
     "しょぼいカレンダー等でデータは取れるが、"
     "注目理由がデータで出せない(explainable=2)。既存サービスが厚い。"),

    ("音楽リリース", dict(api=4, choice=5, explainable=3, deadline=2, jp_thin=2,
                    roster=1, archive=3, rights=2, evergreen=3),
     "Spotify APIはあるが締め切りが無く、対象が閉じない。"),

    ("テニス", dict(api=3, choice=4, explainable=4, deadline=5, jp_thin=4,
                 roster=3, archive=3, rights=3, evergreen=4),
     "大会期間中は毎日試合があり日次になる。ただし年間を通すと"
     "空白期が長い。無料APIの質が競技団体ごとに割れる。"),

    ("ゴルフ", dict(api=3, choice=3, explainable=4, deadline=4, jp_thin=3,
                 roster=3, archive=3, rights=3, evergreen=4),
     "木〜日の開催で週の半分が空く。日本人選手軸は作りやすい。"),

    ("NPB(日本プロ野球)", dict(api=2, choice=4, explainable=5, deadline=5,
                        jp_thin=1, roster=4, archive=3, rights=2,
                        evergreen=4),
     "無料の公式APIが無いのが致命的(api=2)。"
     "日本語情報が最も飽和しているジャンルでもある。"
     "MLBのコードが最も流用しやすいのに、入口で詰まる例。"),
]


def score(g: dict) -> float:
    return sum(g[k] * w for k, _, w, _ in CRITERIA)


def bar(pct: float, width: int = 24) -> str:
    n = round(pct * width)
    return "#" * n + "." * (width - n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", help="1ジャンルの内訳を出す(部分一致)")
    ap.add_argument("--criteria", action="store_true", help="判定条件と重みの根拠を出す")
    args = ap.parse_args()

    if args.criteria:
        print("判定条件と重み\n")
        for _, label, w, why in CRITERIA:
            print(f"[{w:.1f}] {label}")
            print(f"       {why}\n")
        return 0

    if args.detail:
        hit = [g for g in GENRES if args.detail in g[0]]
        if not hit:
            print(f"該当なし: {args.detail}")
            return 1
        for name, s, note in hit:
            print(f"=== {name}  {score(s):.1f} / {MAX_SCORE:.0f}\n")
            for k, label, w, _ in CRITERIA:
                print(f"  {s[k]}/5  x{w:.1f} = {s[k] * w:5.1f}   {label}")
            print(f"\n  {note}\n")
        return 0

    ranked = sorted(GENRES, key=lambda g: -score(g[1]))
    print(f"コレスポ型の仕組みが移しやすい順  (満点 {MAX_SCORE:.0f})\n")
    for i, (name, s, _) in enumerate(ranked, 1):
        v = score(s)
        print(f"{i:2}. {v:6.1f}  {bar(v / MAX_SCORE)}  {name}")

    # 足切り条件。合計点が高くても、ここが低いと成立しない。
    print("\n--- 合計点では見えない足切り ---")
    for name, s, _ in ranked:
        blockers = []
        if s["api"] <= 2:
            blockers.append("公開APIが無い(日次が組めない)")
        if s["rights"] <= 2:
            blockers.append("権利上の制約が重い")
        if s["choice"] <= 2:
            blockers.append("1日の候補が少なく日次にならない")
        if s["deadline"] <= 2:
            blockers.append("締め切りが無く毎日見る理由が作れない")
        if blockers:
            print(f"  {name}: " + " / ".join(blockers))

    print("\n判定条件の根拠は --criteria、内訳は --detail <名前> で見られます")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
