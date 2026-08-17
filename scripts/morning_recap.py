"""
「昨夜の日本人選手」の結果を集めて、朝のショート用データを作る。

なぜこれをやるのか:
  MLBは日本の朝に終わる。個々の選手のニュースは大量にあるが、
  日本人選手を一覧で見られるものは意外と少なく、しかも
  「昨日◯◯どうだった?」は毎朝ほぼ確実に検索される。
  19時の予告(これから)とは別に、朝の枠(終わったこと)を取れる。

  予告と違って結果は確定しているので、推測が一切入らない。
  取れなかった選手は黙って落とす(0で埋めると、出ていないのか
  データが無いのか区別できなくなる)。

出力: data/morning_recap.json

使い方:
  python3 scripts/morning_recap.py --out data/morning_recap.json
"""

import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import JP_PLAYERS_MLB, MLB_TEAM_NAME_JP  # noqa: E402

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_day_hitting(player_id: str, day: str, season: str):
    """その日の打撃成績。出場していなければ None。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "byDateRange", "group": "hitting",
                    "startDate": day, "endDate": day, "season": season},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return None
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            s = split.get("stat") or {}
            ab = int(_f(s.get("atBats")))
            pa = int(_f(s.get("plateAppearances"))) or ab
            if not pa:
                continue
            return {
                "type": "batter", "pa": pa, "ab": ab,
                "hits": int(_f(s.get("hits"))),
                "hr": int(_f(s.get("homeRuns"))),
                "rbi": int(_f(s.get("rbi"))),
                "runs": int(_f(s.get("runs"))),
                "so": int(_f(s.get("strikeOuts"))),
                "bb": int(_f(s.get("baseOnBalls"))),
                "avg": s.get("avg"),
                # 長打と、安打以外での出塁。
                #
                # 「二塁打・三塁打は取れない」と思い込んで、塁打を
                # 安打+本塁打×3で近似していたが、APIは全部返している。
                # そのせいで、たとえば大谷の8/15の三塁打が単打として
                # 採点されていた(実際の塁打3に対し、こちらの計算は1)。
                "doubles": int(_f(s.get("doubles"))),
                "triples": int(_f(s.get("triples"))),
                "tb": int(_f(s.get("totalBases"))),
                "hbp": int(_f(s.get("hitByPitch"))),
                "sb": int(_f(s.get("stolenBases"))),
            }
    return None


def fetch_day_pitching(player_id: str, day: str, season: str):
    """その日の投球成績。登板していなければ None。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "byDateRange", "group": "pitching",
                    "startDate": day, "endDate": day, "season": season},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return None
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            s = split.get("stat") or {}
            ip = s.get("inningsPitched")
            if not ip or _f(ip) <= 0:
                continue
            return {
                "type": "pitcher", "ip": ip,
                "er": int(_f(s.get("earnedRuns"))),
                "hits": int(_f(s.get("hits"))),
                "so": int(_f(s.get("strikeOuts"))),
                "bb": int(_f(s.get("baseOnBalls"))),
                "wins": int(_f(s.get("wins"))),
                "losses": int(_f(s.get("losses"))),
                # 役割を判別するための値。
                # 同じ「1回無失点」でも、先発なら物足りず、
                # クローザーなら仕事を完璧に果たしたことになる。
                # ニュースを追わなくても、この4つで機械的に分かる。
                "gs": int(_f(s.get("gamesStarted"))),
                "saves": int(_f(s.get("saves"))),
                "save_opp": int(_f(s.get("saveOpportunities"))),
                "blown": int(_f(s.get("blownSaves"))),
                "holds": int(_f(s.get("holds"))),
            }
    return None


def _row_from_split(split: dict, group: str):
    """gameLogの1試合分を、contribution()が読める形に直す。"""
    s = split.get("stat") or {}
    if group == "pitching":
        ip = s.get("inningsPitched")
        if not ip or _f(ip) <= 0:
            return None
        return {
            "type": "pitcher", "ip": ip,
            "er": int(_f(s.get("earnedRuns"))),
            "hits": int(_f(s.get("hits"))),
            "so": int(_f(s.get("strikeOuts"))),
            "bb": int(_f(s.get("baseOnBalls"))),
            "gs": int(_f(s.get("gamesStarted"))),
            "saves": int(_f(s.get("saves"))),
            "save_opp": int(_f(s.get("saveOpportunities"))),
            "blown": int(_f(s.get("blownSaves"))),
            "holds": int(_f(s.get("holds"))),
        }
    ab = int(_f(s.get("atBats")))
    pa = int(_f(s.get("plateAppearances"))) or ab
    if not pa:
        return None
    # 当日と同じ項目を揃える。片方だけ塁打の実数を使うと、
    # 「前回より上がった/下がった」の比較が式違いの比較になってしまう。
    return {
        "type": "batter", "pa": pa, "ab": ab,
        "hits": int(_f(s.get("hits"))),
        "hr": int(_f(s.get("homeRuns"))),
        "rbi": int(_f(s.get("rbi"))),
        "runs": int(_f(s.get("runs"))),
        "so": int(_f(s.get("strikeOuts"))),
        "bb": int(_f(s.get("baseOnBalls"))),
        "doubles": int(_f(s.get("doubles"))),
        "triples": int(_f(s.get("triples"))),
        "tb": int(_f(s.get("totalBases"))),
        "hbp": int(_f(s.get("hitByPitch"))),
        "sb": int(_f(s.get("stolenBases"))),
    }


def fetch_game_log(player_id: str, group: str, season: str) -> list:
    """その選手の今季の1試合ごとの成績。取れなければ空。"""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{player_id}/stats",
            params={"stats": "gameLog", "group": group, "season": season},
            timeout=25,
        )
        resp.raise_for_status()
    except Exception:
        return []
    out = []
    for st in resp.json().get("stats", []):
        for split in st.get("splits", []):
            out.append(split)
    out.sort(key=lambda s: s.get("date") or "")
    return out


# 直近の平均を取る試合数。7試合だと、打者は約1週間、投手は先発なら
# 1か月半にあたる。投手の「直近」としては長すぎるので、登板数で分ける。
RECENT_GAMES_BATTER = 7
RECENT_GAMES_PITCHER = 3


def fetch_context(player_id: str, groups: list, season: str, day: str) -> dict:
    """
    その日より前の成績から、前回の点数と直近の平均を出す。

    点数を単独で出しても「良かったのか」が分からない。前回から増えたのか、
    いつもと比べて高いのかが並んで初めて、数字が意味を持つ。

    recap_history ではなくMLBのgameLogを見る。履歴は溜まるまで使えないし、
    実際に溜まっていなかった期間がある。原簿から引く方が確実で、
    シーズン途中から始めても過去に遡れる。

    二刀流は投打の両方を渡す。その日の点数は両方の合計なので、
    比べる相手も同じ日付で合算していないと、増減が嘘になる。
    """
    per_date: dict = {}
    team = None
    for group in groups:
        log = fetch_game_log(player_id, group, season)
        if not log:
            continue
        # 所属は最新の試合のもの。移籍した選手は移籍後の球団になる。
        # 名前ではなくIDで持つ。表記揺れで引けなくなるのを避けるため。
        team = team or (log[-1].get("team") or {}).get("id")
        for s in log:
            d = s.get("date") or ""
            if not d or d >= day:
                continue
            row = _row_from_split(s, group)
            if row:
                per_date[d] = per_date.get(d, 0) + contribution(row)

    if not per_date:
        return {"team": team} if team else {}

    scored = sorted(per_date.items())
    n = RECENT_GAMES_PITCHER if "pitching" in groups else RECENT_GAMES_BATTER
    recent = scored[-n:]
    return {
        "team": team,
        "prev_score": scored[-1][1],
        "prev_date": scored[-1][0],
        "avg_score": round(sum(v for _, v in recent) / len(recent)),
        "avg_games": len(recent),
    }


def headline(row: dict) -> str:
    """1行の見出し。数字をそのまま並べるだけで、評価はしない。"""
    if row["type"] == "pitcher":
        bits = [f"{row['ip']}回", f"{row['so']}奪三振", f"自責{row['er']}"]
        # 役割は点数を左右するので、画面にも出す。
        # 同じ「1回無失点」に別々の点が付く理由が見えないと、
        # 数字だけが動いていることになる。
        if row.get("saves"):
            bits.append("セーブ")
        elif row.get("blown"):
            bits.append("セーブ失敗")
        elif row.get("holds"):
            bits.append("ホールド")
        if row.get("wins"):
            bits.append("勝ち投手")
        elif row.get("losses"):
            bits.append("負け投手")
        return "　".join(bits)
    bits = [f"{row['ab']}打数{row['hits']}安打"]
    # 長打は種類まで出す。「1安打」だけでは、単打も三塁打も同じに見える。
    # 点数の側では塁打で差を付けているので、画面にも根拠を出しておく。
    if row.get("hr"):
        bits.append(f"{row['hr']}本塁打")
    if row.get("triples"):
        bits.append(f"{row['triples']}三塁打")
    if row.get("doubles"):
        bits.append(f"{row['doubles']}二塁打")
    if row.get("rbi"):
        bits.append(f"{row['rbi']}打点")
    # 四球は打数に入らないので、書かないと「3打数0安打」だけが残り、
    # 塁に出たことが消える。点数にも効いているので必ず出す。
    if row.get("bb"):
        bits.append(f"{row['bb']}四球")
    if row.get("hbp"):
        bits.append(f"{row['hbp']}死球")
    if row.get("sb"):
        bits.append(f"{row['sb']}盗塁")
    return "　".join(bits)


def build(day: str = None, season: str = None) -> dict:
    """
    対象日は「日本時間の昨日」ではなく、アメリカの試合日。

    米国日付Dのナイトゲームは現地19時開始で、日本時間では
    東部が翌8時〜11時、太平洋が翌11時〜14時に行われる。
    つまり全試合が出揃うのはJSTの14時ごろ。
    このスクリプトはJST 16時に走る前提で、その時点の「JSTの前日」を
    見れば、ちょうど終わったばかりの試合日にあたる。
    """
    season = season or str(datetime.now(timezone.utc).year)
    target = day or (datetime.now(JST).date() - timedelta(days=1)).isoformat()
    print(f"[info] 対象日(米国日付): {target}")

    try:
        resp = requests.get(f"{MLB_API_BASE}/sports/1/players",
                            params={"season": season}, timeout=30)
        resp.raise_for_status()
        by_name = {p.get("fullName"): str(p.get("id"))
                   for p in resp.json().get("people", [])}
    except Exception as e:
        print(f"[warn] 選手一覧の取得に失敗しました: {e}", file=sys.stderr)
        return {"date": target, "players": []}

    rows = []
    for p in JP_PLAYERS_MLB:
        pid = by_name.get(p["name_en"])
        if not pid:
            continue
        # 投げて打った日は両方を持つ。
        # 以前は or で繋いでいたため、投げた日は打撃成績が丸ごと消えていた。
        # 二刀流はその日がいちばん見どころなのに、片方しか出せていなかった。
        pit = fetch_day_pitching(pid, target, season)
        bat = fetch_day_hitting(pid, target, season)
        if not pit and not bat:
            continue

        if pit and bat:
            row = {**pit, "type": "two_way", "pitching": pit, "batting": bat}
            row["headline"] = (headline({"name": p["name_jp"], **pit})
                               + "／"
                               + headline({"name": p["name_jp"], **bat}))
        else:
            stat = pit or bat
            row = {**stat}
            row["headline"] = headline({"name": p["name_jp"], **stat})

        rows.append({"name": p["name_jp"], "name_en": p["name_en"],
                     "player_id": pid, **row})

    # 前回・直近と比べる材料と、所属を足す。
    # 「62点」だけでは高いのか低いのか分からないが、「前回44点」が
    # 隣にあれば伸びが見える。所属は、名前を知らない選手が出た日に
    # どのチームの話なのかを伝える。
    for r in rows:
        groups = (["pitching", "hitting"] if r["type"] == "two_way"
                  else ["pitching"] if r["type"] == "pitcher"
                  else ["hitting"])
        try:
            ctx = fetch_context(r["player_id"], groups, season, target)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {r['name']} の過去成績を取れません: {e}",
                  file=sys.stderr)
            continue
        if ctx.get("team"):
            r["team_id"] = str(ctx["team"])
            r["team_jp"] = MLB_TEAM_NAME_JP.get(r["team_id"], "")
        for k in ("prev_score", "prev_date", "avg_score", "avg_games"):
            if ctx.get(k) is not None:
                r[k] = ctx[k]

    # 打点が「どういう場面で入ったか」を足す。
    # 同じ3ランでも逆転と大差では試合への効き方が違うのに、
    # 成績の合計値だけでは区別できなかった。
    # 取れなくても、その加点が乗らないだけで他は通る。
    try:
        import clutch
        cl = clutch.build(target, [r["player_id"] for r in rows])
        for r in rows:
            e = cl.get(r["player_id"])
            if e:
                r["clutch_points"] = e["points"]
                r["clutch_label"] = e["label"]
                r["clutch_note"] = e.get("note", "")
                r["clutch_plays"] = e["plays"]
                print(f"[info] {r['name']}: {e['label']} (+{e['points']})")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 場面の判定を取得できませんでした: {e}", file=sys.stderr)

    # 投手を先に、打者は安打数の多い順。出場者が少ない日でも形になる並びにする
    rows.sort(key=lambda r: (r["type"] != "pitcher", -r.get("hits", 0)))

    print(f"[info] 出場していた日本人選手: {len(rows)}名")
    for r in rows:
        print(f"   {r['name']}  {r['headline']}")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date": target,
        "date_jst": jst_label(target),
        "players": rows,
    }


def outs_from_ip(ip) -> int:
    """
    MLBの投球回表記をアウト数に直す。"6.1" は6回3分の1で19アウト。
    小数として読むと6.1回になり、3分の1と10分の1を取り違える。
    """
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) * 3 + (int(frac[0]) if frac else 0)
    except (ValueError, TypeError):
        return 0


# 救援の基準点。投球回ではなく「その役割を果たしたか」で置く。
#   closer  … セーブ機会で登板した。締めれば試合が終わる
#   setup   … ホールドが付く場面。リードを次へ渡す役
#   reliever… それ以外の救援
RELIEF_BASE = {"closer": 58, "setup": 50, "reliever": 38}


def pitcher_role(row: dict) -> str:
    """
    その登板の役割。MLB APIの値だけで決まる。

    先発かどうかは gamesStarted、抑えかどうかは saves と
    saveOpportunities で分かる。セーブが付かなくても、セーブ機会で
    投げていれば抑えの仕事をしている(同点で登板した場合など)。
    """
    if row.get("gs"):
        return "starter"
    if row.get("saves") or row.get("save_opp") or row.get("blown"):
        return "closer"
    if row.get("holds"):
        return "setup"
    return "reliever"


ROLE_LABEL = {"closer": "セーブ", "setup": "ホールド"}


def contribution(row: dict) -> int:
    """
    その日の「勝利貢献スコア」。投手と打者を同じ物差しに載せる。

    名前について:
      「コレスポpt」のような身内向けの呼び方は避ける。初めて見た人には
      何の点数か分からず、内輪の遊びに見える。何を測っているかが
      名前だけで伝わる方がよい。計算方法は web/score.html で公開する。


    なぜ作るか:
      成績をそのまま並べると「1.0回2奪三振」「4打数2安打」が横に並ぶだけで、
      どちらがその日効いたのかが伝わらない。順位がつくと、
      淡々とした一覧が「誰がいちばんだったか」の話になる。

    投手はビル・ジェームズのゲームスコアを土台にしている(広く使われていて、
    こちらで重みを考えた部分が少ない)。50を平均点として、
      アウト数 + 5回を超えた分の加点 + 奪三振 - 被安打×2 - 自責×4 - 四球
    打者は塁打を軸に、打点・四球・死球・盗塁を足して、凡退と三振を引く。
    塁打はAPIの実数(totalBases)なので、単打2点・二塁打4点・三塁打6点・
    本塁打8点と、同じ1安打でも進んだ塁の数で差が付く。
    (長らく「二塁打・三塁打は取れない」と思い込んで安打+本塁打×3で
     近似しており、三塁打が単打と同じ点になっていた)

    倍率は、好投・好打が70〜90に収まるように置いた。
    絶対的な意味は無く、その日の中で並べるための数字。

    上限は設けない。完封や3本塁打のような日は100を超えてよく、
    投げて打った日は両方を足すので200近くになる。
    「今日は突き抜けている」が数字の大きさで伝わる方が面白い。
    下限だけ0で止める。マイナスは順位以上の意味を持たないため。
    """
    # 逆転・勝ち越し・同点の加点。clutch.py が付ける。
    # 打点の合計だけでは、どういう場面だったかが分からない。
    bonus = row.get("clutch_points") or 0

    # 投げて打った日は両方を足す。7回10奪三振に3本塁打が乗れば200点前後になる。
    if row.get("type") == "two_way":
        return (contribution({**row["pitching"], "type": "pitcher"})
                + contribution({**row["batting"], "type": "batter"})
                + bonus)

    if row.get("type") == "pitcher":
        outs = outs_from_ip(row.get("ip"))
        raw = (outs
               + 2 * max(0, outs - 12)
               + row.get("so", 0)
               - 2 * row.get("hits", 0)
               - 4 * row.get("er", 0)
               - row.get("bb", 0))
        # 基準点は投球回に応じて動かす。
        # 基準点は役割で変える。
        #
        # 投球回だけで決めていたとき、1回を無失点に抑えた抑え投手が
        # 30点そこそこにしかならなかった。実際にはその日の勝ちを
        # 締めていて、仕事は完璧に果たしている。逆に先発の1回無失点は
        # 早々に降板したということなので、同じ点であるはずがない。
        #
        # 役割はAPIの値で判別できる(gamesStarted / saves / holds)。
        # 「守護神に転向した」といった記事を追わなくても分かる。
        role = pitcher_role(row)
        if role == "starter":
            # 5回を投げ切って満額。ビル・ジェームズのゲームスコアと同じ発想。
            base = 25 + 20 * min(1.0, outs / 15)
        else:
            # 締めた回数ではなく、締めきったかどうかで見る。
            base = RELIEF_BASE[role]
            if row.get("blown"):
                # 逆転を許した登板。抑えの失敗はその試合を落とす。
                base -= 35
        score = base + raw * 1.2
    else:
        # 塁打はAPIの実数を使う。単打2点、二塁打4点、三塁打6点、本塁打8点。
        # 同じ「1安打」でも、どこまで進んだかで価値が違う。
        # 取れないと思い込んで安打+本塁打×3で近似していたぶん、
        # 二塁打と三塁打が単打と同じ扱いになっていた。
        tb = row.get("tb")
        if tb is None:  # 古い記録には項目が無い
            tb = row.get("hits", 0) + 3 * row.get("hr", 0)

        # 凡退そのものを引く。
        #
        # 以前は三振だけを引いていたため、3打数0安打でも28点が付き、
        # 画面に出ていた。全打席凡退した日に点が残るのは実態と合わない。
        # 四球は塁に出ているので、安打ほどではないが確かな加点にする。
        # 死球も出塁なので同じ扱い。盗塁は自力で1つ先の塁へ進んだぶん。
        outs_made = max(0, row.get("ab", 0) - row.get("hits", 0))
        raw = (2 * tb
               + 2 * row.get("rbi", 0)
               + 2 * row.get("bb", 0)
               + 2 * row.get("hbp", 0)
               + 1 * row.get("sb", 0)
               - outs_made
               - row.get("so", 0))

        # 出場したこと自体を50点として、そこから積む。
        #
        # 以前は30を土台に2.4倍で積んでいた。その結果:
        #   4打数1安打  25点
        #   4打数1安打 1本塁打  44点
        # 1本打っても19点しか増えず、しかも1安打が25点というのは、
        # 数字の見え方として実感と合っていなかった。
        #
        # 土台を50に上げ、倍率も上げる。50を「出場した日の基準」として、
        # 良い日はそこから上へ、悪い日は下へ動く。1本塁打で80点前後、
        # 3本塁打で200点近く、無安打なら50を割って非表示側へ落ちる。
        score = BATTER_BASE + raw * BATTER_SCALE
    return max(0, round(score + bonus))


# この点を超えたら「突き抜けた日」として画面で強調する。
# 土台を50へ上げたので、境目も上げる。本塁打1本で80点前後になるため
# 100のままだと「よくある日」が突き抜け扱いになってしまう。
# 完封級・2本塁打級がここに入る。
STANDOUT = 130

# これを下回る日は、点数を出さずに成績だけ載せる。
# 0点と書くこと自体には意味が無く、出場した選手に対して不必要に厳しい。
# 順位の並びには使うので、点そのものは計算し続ける。
#
# 打者の点数の土台と倍率。
#
# 公開している計算式のページ(generate_score_page.py)は、ここを読んで
# 文面を作る。以前は両方に数字を手で書いており、片方を変えたときに
# もう片方が古いまま残った。数字の出どころは1つにする。
BATTER_BASE = 50
BATTER_SCALE = 3.6

# 投手にだけ使う。打者は score_label が「塁に出たか」で判断する
# (点数で切ると、1安打や四球だけの日が消えてしまうため)。
HIDE_BELOW = 40


def reached_base(row: dict) -> bool:
    """その打者が、その日1度でも塁に出たか。"""
    return (row.get("hits", 0) + row.get("bb", 0)
            + row.get("hbp", 0)) > 0


def score_label(row: dict) -> str:
    """
    画面に出す点数。何もできなかった日は数字を伏せる。

    伏せる条件を点数の閾値で決めていたが、それだと
    「3打数0安打 1四球」も「4打数1安打」も閾値を割って消えていた。
    塁に出たかどうかは点数と別の話で、四球は打率に残らないぶん
    こちらが書かないとどこにも残らない。

    打者は「1度でも塁に出たか」で決める。安打・四球・死球のどれでもよい。
    全打席で塁に出られなかった日だけ、数字を出さずに成績だけ載せる。
    投手は登板した時点で仕事をしているので、これまでどおり点数で見る。
    """
    if row.get("type") == "batter":
        return str(contribution(row)) if reached_base(row) else ""
    v = contribution(row)
    return "" if v < HIDE_BELOW else str(v)


def jst_label(us_date: str) -> str:
    """
    米国日付を、日本の視聴者が体感する日付へ直す。

    米国日付Dの試合はほぼ全て日本時間D+1の朝に行われる
    (現地19時開始 = JST翌8時)。ところがタイトルにもサムネイルにも
    米国日付をそのまま出していたため、日本時間8月11日の朝に見た試合を
    その日の夜に「8月10日の成績」として出していた。
    サイトも動画も他は全てJST基準なので、ここだけ1日ずれて見える。

    日付として読めなければ、そのまま返す(欠けても落とさない)。
    """
    try:
        d = datetime.strptime(str(us_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return us_date
    return (d + timedelta(days=1)).isoformat()


def save_history(data: dict, out_dir: str = "data/recap_history",
                 keep_days: int = 40) -> None:
    """
    その日の記録を日付ごとに残す。週間ランキングの材料になる。

    data/morning_recap.json は毎日上書きされるので、前日以前が残らない。
    週や月でまとめるには、日ごとに取っておく必要がある。

    1日あたり数KBなので、40日ぶん置いても軽い。
    古いものは消す(リポジトリが際限なく膨らむのを防ぐ)。
    """
    day = data.get("date")
    if not day:
        return
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{day}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")

    files = sorted(d.glob("????-??-??.json"))
    for f in files[:-keep_days]:
        f.unlink()
        print(f"[info] 古い記録を削除: {f.name}")


def load_history(out_dir: str = "data/recap_history", days: int = 7) -> list:
    """新しい順に days 日ぶん読む。足りなければあるだけ返す。"""
    d = pathlib.Path(out_dir)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("????-??-??.json"), reverse=True)[:days]:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def weekly_ranking(days: int = 7, out_dir: str = "data/recap_history") -> list:
    """
    直近の記録から、選手ごとの合計と平均を出す。

    合計だけだと出場機会の多い選手が並ぶだけになり、
    平均だけだと1試合しか出ていない選手が上に来る。
    両方持たせて、使う側で選べるようにする。
    """
    hist = load_history(out_dir, days)
    agg: dict = {}
    for d in hist:
        for p in d.get("players") or []:
            e = agg.setdefault(p["name"], {
                "name": p["name"], "total": 0, "games": 0,
                "best": 0, "best_day": "", "labels": [],
            })
            v = contribution(p)
            e["total"] += v
            e["games"] += 1
            if v > e["best"]:
                e["best"] = v
                e["best_day"] = d.get("date_jst") or d.get("date", "")
            if p.get("clutch_label"):
                e["labels"].append(p["clutch_label"])

    rows = list(agg.values())
    for e in rows:
        e["avg"] = round(e["total"] / e["games"]) if e["games"] else 0
    rows.sort(key=lambda e: (-e["total"], -e["avg"], e["name"]))
    return rows


def load(path: str, day: str = None) -> list:
    """朝のショート側から読む。日付が食い違う場合は使わない。"""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if day and data.get("date") != day:
        print(f"[info] 記録が別の日({data.get('date')})なので使いません")
        return []
    return data.get("players") or []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/morning_recap.json")
    parser.add_argument("--date", default=None, help="米国日付 YYYY-MM-DD")
    parser.add_argument("--season", default=None)
    args = parser.parse_args()

    data = build(day=args.date, season=args.season)
    if not data["players"]:
        print("[info] 出場した日本人選手がいないため、ファイルは更新しません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[info] 朝のまとめを出力しました({len(data['players'])}名) -> {out}")

    # 週間ランキングの材料。こちらは日付ごとに残す。
    save_history(data)
    week = weekly_ranking()
    if week:
        print(f"[info] 直近7日の合計上位: "
              + " / ".join(f"{e['name']}{e['total']}" for e in week[:3]))


if __name__ == "__main__":
    main()
