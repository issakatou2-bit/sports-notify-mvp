#!/usr/bin/env python3
"""
MLBと欧州サッカーを、1つのチャンネルでやるか分けるかを比べる。

    python3 scripts/channel_split_sim.py
    python3 scripts/channel_split_sim.py --overlap 0.15
    python3 scripts/channel_split_sim.py --calendar

なぜスクリプトにするか:
  「分けたほうが伸びる」「まとめたほうがいい」はどちらも言えてしまう。
  何を仮定するとどちらが勝つのかを、動かして確かめられる形にする。

このモデルが答えるのは1つだけ:
  365日でチャンネル全体の総再生数がどちらが多いか。
  収益条件や運用の手間は入れていない(最後にコメントで触れる)。

数字の性格:
  シーズンの日程は事実。視聴者の重なりや推薦の効き方は見立てで、
  外れうる。だからこそ --overlap などで振って、
  「どこで結論がひっくり返るか」を見るために作ってある。
"""

import argparse
import datetime as dt
import sys

# --- シーズン日程(事実) -----------------------------------------------------
# MLB: 3月下旬開幕 〜 10月上旬レギュラー終了、ポストシーズンは11月上旬まで
# 欧州サッカー: 8月中旬開幕 〜 5月下旬終了(CL決勝は5月末)
#
# ここが今回の検討で最も効く。両者の端境期が噛み合っていて、
# 合わせると1年365日が埋まる。
MLB_SEASON = ((3, 25), (11, 5))
SOCCER_SEASON = ((8, 14), (5, 31))   # 年をまたぐ


def in_range(day: dt.date, span) -> bool:
    (m1, d1), (m2, d2) = span
    start = (m1, d1)
    end = (m2, d2)
    cur = (day.month, day.day)
    if start <= end:
        return start <= cur <= end
    # 年をまたぐ場合(サッカー)
    return cur >= start or cur <= end


def calendar_summary():
    day = dt.date(2026, 1, 1)
    both = mlb_only = soc_only = neither = 0
    for _ in range(365):
        m = in_range(day, MLB_SEASON)
        s = in_range(day, SOCCER_SEASON)
        if m and s:
            both += 1
        elif m:
            mlb_only += 1
        elif s:
            soc_only += 1
        else:
            neither += 1
        day += dt.timedelta(days=1)
    return both, mlb_only, soc_only, neither


# --- 視聴の仕組み -----------------------------------------------------------
# 投稿した動画は、まず狭い範囲(登録者と過去の視聴者)に出る。
# そこでの反応がよければフィードへ広がる。つまり
#   最初に見せる相手のうち、何割がその題材に興味があるか
# が、その後の伸びを決める。
#
# ショートはフィード配信の比率が高く、フィードは動画単位で判断される。
# チャンネルが何を扱っているかの影響は、長尺より小さい。
# (コレスポの実測でも、ショートのフィード比率は16.7%→31.5%と上昇中)

DEFAULTS = dict(
    days=365,
    start_subs=20,          # 現状はごく初期。ここが小さいほど分割の損は小さい
    seed_rate=0.35,         # 登録者のうち、投稿直後に接触する割合
    feed_share=0.60,        # 再生のうちフィード由来の割合(ショート主体)
    feed_pool=900.0,        # 反応が良いときにフィードから来る上限の目安
    conv_rate=0.010,        # 再生あたりの登録転換率
    overlap=0.25,           # MLB目当ての人が欧州サッカーも見る確率
    mlb_posts=3,            # MLB開催期間中の1日の本数(日次1＋朝2)
    soc_posts=1,            # サッカー開催期間中の1日の本数
    cold_start_days=45,     # 新チャンネルがフィードに乗り始めるまで
    churn=0.0015,           # 題材違いを見せられた登録者が離れる率
    seed_gate=0.5,          # フィードへの広がりが、登録者の反応にどれだけ縛られるか
)

# seed_gate について
# ---------------------------------------------------------------------------
# この検討で結論を分けるのは、実はここ1点。
#
#   1.0 … フィードへ広がるかどうかは、最初に見せた登録者の反応で決まる。
#         題材違いの動画は登録者に刺さらず、そこで止まる。
#         → 単一題材のチャンネルが有利。
#   0.0 … フィードは動画そのものを見て判断する。チャンネルが何を扱って
#         いるかは関係ない。 → 登録者の多い1チャンネルが有利。
#
# ショートは他人のフィードへ出る比率が高く、そこに映るのは
# 登録していない人が大半なので、実際は0寄り。ただし投稿直後の
# 一定量は登録者と過去の視聴者に出るので、0ではない。
# 手元のアナリティクスからは、この値を直接は測れない。
# 既定を0.5に置いてあるのは中間というだけで、根拠のある数字ではない。


def posts_for(day: dt.date, cfg: dict) -> list:
    """
    その日に作る動画の題材リスト。

    ここが「分ける/まとめる」より手前にあるのが肝心なところ。
    作れる本数はパイプラインが決めるもので、チャンネルを分けても
    増えない。最初のモデルは分割側だけ本数が倍になっており、
    どの条件でも分割が勝つという当たり前の結果を出していた。
    """
    out = []
    if in_range(day, MLB_SEASON):
        out += ["mlb"] * cfg["mlb_posts"]
    if in_range(day, SOCCER_SEASON):
        out += ["soc"] * cfg["soc_posts"]
    return out


def amplify(match: float) -> float:
    """
    最初に見せた相手のうち、その題材に興味がある割合を
    フィードでの伸びに変換する。

    直線ではなく閾値のある形にしてある。反応が一定を下回ると
    そもそも広がらない、という挙動を写すため。
    """
    if match <= 0.30:
        return match * 0.4
    return 0.12 + (match - 0.30) ** 1.35


def simulate(cfg: dict, split: bool) -> dict:
    """
    split=False … 1チャンネルでMLBもサッカーも出す
    split=True  … 2チャンネルに分ける
    """
    day = dt.date(2026, 1, 1)

    if split:
        # 2チャンネル。登録者は最初に山分けし、それぞれ単一題材。
        chans = [
            {"subs": cfg["start_subs"] / 2, "topic": "mlb", "age": 0, "views": 0.0},
            {"subs": cfg["start_subs"] / 2, "topic": "soc", "age": 0, "views": 0.0},
        ]
    else:
        chans = [{"subs": cfg["start_subs"], "topic": "both", "age": 0,
                  "views": 0.0, "mix": 0.5}]

    total = 0.0
    dark_days = 0          # そのチャンネルに出すものが無い日
    n_posts = 0

    for _ in range(cfg["days"]):
        todays = posts_for(day, cfg)
        n_posts += len(todays)

        for ch in chans:
            # このチャンネルが今日出す動画。分割時は題材で振り分けるだけで、
            # 合計本数は1チャンネルのときと変わらない。
            if ch["topic"] == "both":
                mine = todays
            else:
                mine = [t for t in todays if t == ch["topic"]]

            if not mine:
                # 出すものが無い日。登録者はゆっくり離れ、
                # 再開したときにフィードへの乗りも鈍る。
                dark_days += 1
                ch["subs"] *= (1 - cfg["churn"] * 2)
                ch["age"] = max(0, ch["age"] - 1)
                continue

            ch["age"] += 1
            warmup = min(1.0, ch["age"] / cfg["cold_start_days"])

            for topic in mine:
                if ch["topic"] == "both":
                    # 登録者のうち、その題材に興味がある割合。
                    # 目当てでない側の人も、重なりぶんは見る。
                    same = ch["mix"] if topic == "mlb" else (1 - ch["mix"])
                    match = same + (1 - same) * cfg["overlap"]
                else:
                    match = 1.0

                seed = ch["subs"] * cfg["seed_rate"]
                seed_views = seed * match

                # フィードの広がり。seed_gate のぶんだけ登録者の反応に縛られ、
                # 残りは動画そのものの出来で決まる(=題材違いでも減らない)。
                g = cfg["seed_gate"]
                reach = g * amplify(match) + (1 - g) * amplify(1.0)
                feed_views = cfg["feed_pool"] * cfg["feed_share"] * reach * warmup

                v = seed_views + feed_views
                ch["views"] += v
                total += v

                gained = v * cfg["conv_rate"]
                if ch["topic"] == "both":
                    # 題材違いを見せられた登録者が少しずつ離れる
                    ch["subs"] -= ch["subs"] * cfg["churn"] * (1 - match)
                    # 登録者の構成も、来た人の題材へ寄っていく
                    w = gained / max(ch["subs"] + gained, 1e-9)
                    tgt = 1.0 if topic == "mlb" else 0.0
                    ch["mix"] = ch["mix"] * (1 - w) + tgt * w
                ch["subs"] += gained

        day += dt.timedelta(days=1)

    return {
        "total_views": total,
        "subs": sum(c["subs"] for c in chans),
        "dark_days": dark_days,
        "posts": n_posts,
        "per_channel": [(c["topic"], round(c["views"]), round(c["subs"], 1))
                        for c in chans],
    }


def run(cfg: dict, quiet=False) -> tuple:
    one = simulate(cfg, split=False)
    two = simulate(cfg, split=True)
    # 本数が揃っていなければ比較が成立しない。最初のモデルはここが崩れていた。
    assert one["posts"] == two["posts"], (one["posts"], two["posts"])
    if not quiet:
        print(f"  投稿本数は両者とも {one['posts']:,}本\n")
        print(f"  1チャンネル : 再生 {one['total_views']:>9,.0f}   "
              f"登録 {one['subs']:>6.0f}   休止日 {one['dark_days']:>3}")
        print(f"  2チャンネル : 再生 {two['total_views']:>9,.0f}   "
              f"登録 {two['subs']:>6.0f}   休止日 {two['dark_days']:>3}")
        for t, v, s in two["per_channel"]:
            print(f"       └ {t:4} 再生 {v:>9,}   登録 {s:>6.1f}")
    return one, two


def main():
    ap = argparse.ArgumentParser()
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    ap.add_argument("--calendar", action="store_true",
                    help="シーズンの重なりだけを出す")
    args = vars(ap.parse_args())
    calendar_only = args.pop("calendar")
    cfg = {k: args[k] for k in DEFAULTS}

    both, mlb_only, soc_only, neither = calendar_summary()
    print("シーズンの重なり(365日)\n")
    print(f"  両方ある日           {both:>3}日")
    print(f"  MLBだけ              {mlb_only:>3}日")
    print(f"  欧州サッカーだけ     {soc_only:>3}日")
    print(f"  どちらも無い日       {neither:>3}日")
    print(f"\n  1チャンネルなら      {365 - neither}日 出せる")
    print(f"  MLB単独チャンネルは  {both + mlb_only}日  "
          f"(残り{365 - both - mlb_only}日は休止)")
    print(f"  サッカー単独は       {both + soc_only}日  "
          f"(残り{365 - both - soc_only}日は休止)")
    if calendar_only:
        return 0

    print("\n" + "=" * 66)
    print(f"365日シミュレーション  (重なり={cfg['overlap']:.0%}, "
          f"フィード比率={cfg['feed_share']:.0%}, "
          f"開始登録者={cfg['start_subs']:.0f})\n")
    run(cfg)

    # --- 感度分析 -----------------------------------------------------------
    # 見立てで置いた値ほど、振って確かめる価値がある。
    print("\n" + "=" * 66)
    print("重なり(MLB目当ての人がサッカーも見る確率)を振る\n")
    print("  重なり   1ch再生    2ch再生   どちらが有利")
    for ov in (0.05, 0.10, 0.15, 0.25, 0.40, 0.60):
        c = dict(cfg, overlap=ov)
        one, two = run(c, quiet=True)
        d = one["total_views"] / two["total_views"]
        who = f"1ch {d:.2f}倍" if d >= 1 else f"2ch {1 / d:.2f}倍"
        print(f"  {ov:>5.0%}  {one['total_views']:>9,.0f}  "
              f"{two['total_views']:>9,.0f}   {who}")

    print("\n開始時点の登録者数を振る(規模が大きいほど分割の損が増える)\n")
    print("  登録者   1ch再生    2ch再生   どちらが有利")
    for s in (20, 200, 2000, 20000, 100000):
        c = dict(cfg, start_subs=s)
        one, two = run(c, quiet=True)
        d = one["total_views"] / two["total_views"]
        who = f"1ch {d:.2f}倍" if d >= 1 else f"2ch {1 / d:.2f}倍"
        print(f"  {s:>6}  {one['total_views']:>9,.0f}  "
              f"{two['total_views']:>9,.0f}   {who}")

    print("\nseed_gate を振る(結論を最も左右する。0=動画で決まる 1=登録者で決まる)\n")
    print("  gate     1ch再生    2ch再生   どちらが有利")
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        c = dict(cfg, seed_gate=g)
        one, two = run(c, quiet=True)
        d = one["total_views"] / two["total_views"]
        who = f"1ch {d:.2f}倍" if d >= 1 else f"2ch {1 / d:.2f}倍"
        print(f"  {g:>5.2f}  {one['total_views']:>9,.0f}  "
              f"{two['total_views']:>9,.0f}   {who}")

    print("\n2年目以降(登録2000人まで育った状態)で、同じ2軸を振る\n")
    print("  gate \\ 重なり   " + "".join(f"{o:>8.0%}" for o in
                                        (0.10, 0.25, 0.40, 0.60)))
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        row = []
        for ov in (0.10, 0.25, 0.40, 0.60):
            c = dict(cfg, seed_gate=g, overlap=ov, start_subs=2000)
            one, two = run(c, quiet=True)
            d = one["total_views"] / two["total_views"]
            row.append(f"{'1ch' if d >= 1 else '2ch':>4}{max(d, 1 / d):>4.1f}")
        print(f"  {g:>5.2f}         " + "".join(row))

    print("\n※ 収益条件・運用の手間・ブランドの分かりやすさは入れていません")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
