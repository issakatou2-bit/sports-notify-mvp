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
from notability_engine import JP_PLAYERS_MLB  # noqa: E402

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
            }
    return None


def headline(row: dict) -> str:
    """1行の見出し。数字をそのまま並べるだけで、評価はしない。"""
    if row["type"] == "pitcher":
        bits = [f"{row['ip']}回", f"{row['so']}奪三振", f"自責{row['er']}"]
        if row.get("wins"):
            bits.append("勝ち投手")
        elif row.get("losses"):
            bits.append("負け投手")
        return "　".join(bits)
    bits = [f"{row['ab']}打数{row['hits']}安打"]
    if row.get("hr"):
        bits.append(f"{row['hr']}本塁打")
    if row.get("rbi"):
        bits.append(f"{row['rbi']}打点")
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
    打者は塁打を軸に、打点と四球を足して三振を引く。
    長打の内訳(二塁打・三塁打)はAPIのこの呼び出しでは取れないので、
    本塁打だけを塁打に上乗せしている。ここは近似。

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
        # 定数(先発想定の45)にしていたとき、1回を無失点で抑えた中継ぎが
        # 4打数2安打1打点の打者を上回った。1イニングは、良い内容でも
        # その試合に効いた量としては小さい。5回を投げ切って満額になる形にする。
        base = 25 + 20 * min(1.0, outs / 15)
        score = base + raw * 1.2
    else:
        # 二塁打・三塁打が取れないため、塁打は安打+本塁打×3で近似する
        tb = row.get("hits", 0) + 3 * row.get("hr", 0)
        raw = (2 * tb
               + 2 * row.get("rbi", 0)
               + row.get("bb", 0)
               - row.get("so", 0))
        score = 30 + raw * 2.4
    return max(0, round(score + bonus))


# この点を超えたら「突き抜けた日」として画面で強調する。
# 完封級・3本塁打級がここに入る。
STANDOUT = 100

# これを下回る日は、点数を出さずに成績だけ載せる。
# 0点と書くこと自体には意味が無く、出場した選手に対して不必要に厳しい。
# 順位の並びには使うので、点そのものは計算し続ける。
HIDE_BELOW = 25


def score_label(row: dict) -> str:
    """画面に出す点数。低い日は数字を伏せる。"""
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


if __name__ == "__main__":
    main()
