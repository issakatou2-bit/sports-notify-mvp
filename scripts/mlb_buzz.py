"""
MLB公式YouTubeのハイライト動画の再生回数から、
「現地でどの試合が最も見られたか」を集める。

なぜこの形にするのか:
  「現地の反応」を伝えたいが、SNSの書き込みを拾って紹介するのは避けたい。
  本物か・代表的かを確かめられないうえ、翻訳の加減で印象が変わり、
  都合のいいものだけ拾えば実態と違うものになる。
  一方、公式ハイライトの再生回数は誰でも同じ数字を確認でき、
  「現地でどれだけ見られたか」をそのまま表す。
  感想を代弁せずに注目度だけを示せる。

  ただしこれは「注目度」であって「面白さ」や「重要さ」ではない。
  人気球団の試合は内容に関わらず伸びる。その旨は表示側で断る。

取り方:
  MLB公式の投稿一覧(playlistItems)から直近のハイライトを読み、
  videos.list でまとめて再生回数を取る。どちらも1ユニット。

  以前は「Game Highlights」で全チャンネルを検索して、そのあと
  公式だけを残していた。他所が同じ語で投稿した日は公式のぶんが
  50件の外へ押し出され、8/21は1本しか残らなかった。
  「再生回数ランキング」が1位だけの動画になる。
  チャンネルを直に読めば押し出されようがない。

出力: data/mlb_buzz.json

使い方:
  YOUTUBE_API_KEY=xxx python3 scripts/mlb_buzz.py --out data/mlb_buzz.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

# 公式以外(まとめ・転載)を除くため、チャンネル名が完全一致するものだけ使う。
OFFICIAL_CHANNEL_TITLE = "MLB"

# ハイライトのタイトルは "Angels vs. Dodgers Game Highlights (8/9/26) | MLB Highlights"
# のような形をしている。対戦カード部分だけを取り出す。
MATCHUP_RE = re.compile(r"^(.+?)\s+Game Highlights", re.I)


def fetch_recent_highlights(api_key: str, hours: int = 30,
                            state_path: str = "data/mlb_buzz.json") -> list:
    """MLB公式の直近のハイライト。

    以前は「Game Highlights」で全チャンネルを新着順に50件取り、
    そのあとMLB公式だけを残していた。他所が同じ語で投稿した日は、
    公式のぶんが50件の外へ押し出される。8/21はそれで1本しか残らず、
    「再生回数ランキング」が1位だけの動画になった。

    チャンネルの投稿一覧を直に読む形にする。押し出されようがなく、
    しかも search(100ユニット)ではなく playlistItems(1ユニット)で済む。
    チャンネルIDは一度引いたら覚えておく。
    """
    cid = _official_channel_id(api_key, state_path)
    if not cid:
        return []
    # 投稿一覧のプレイリストIDは、チャンネルIDの2文字目をUに変えたもの。
    # channels.list を1回叩いても取れるが、この対応は公開仕様。
    uploads = "UU" + cid[2:]
    after = datetime.now(timezone.utc) - timedelta(hours=hours)

    items = []
    try:
        resp = requests.get(
            f"{YOUTUBE_API}/playlistItems",
            params={"key": api_key, "part": "snippet",
                    "playlistId": uploads, "maxResults": 50},
            timeout=20)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 投稿一覧を取れません: {e}", file=sys.stderr)
        return []

    for it in resp.json().get("items", []):
        sn = it.get("snippet") or {}
        vid = (sn.get("resourceId") or {}).get("videoId")
        pub = sn.get("publishedAt", "")
        if not vid or not pub:
            continue
        try:
            when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < after:
            continue
        # 公式は試合以外(特集・記者会見)も出す。ランキングに混ぜない。
        if "Highlights" not in sn.get("title", ""):
            continue
        items.append({"video_id": vid, "title": sn.get("title", ""),
                      "published_at": pub})
    print(f"[info] MLB公式の直近{hours}時間のハイライト: {len(items)}本")
    return items


def _official_channel_id(api_key: str, state_path: str) -> str:
    """MLB公式のチャンネルID。一度引いたら覚えておく。"""
    try:
        got = json.loads(pathlib.Path(state_path).read_text(
            encoding="utf-8")).get("channel_id")
        if got:
            return got
    except (OSError, json.JSONDecodeError):
        pass
    try:
        resp = requests.get(
            f"{YOUTUBE_API}/search",
            params={"key": api_key, "part": "snippet",
                    "q": "MLB Game Highlights", "type": "video",
                    "order": "date", "maxResults": 50},
            timeout=20)
        resp.raise_for_status()
        for it in resp.json().get("items", []):
            sn = it.get("snippet") or {}
            if sn.get("channelTitle") == OFFICIAL_CHANNEL_TITLE:
                cid = sn.get("channelId")
                if cid:
                    print(f"[info] MLB公式のチャンネルIDを覚えました: {cid}")
                    return cid
    except Exception as e:  # noqa: BLE001
        print(f"[warn] チャンネルIDを引けません: {e}", file=sys.stderr)
    return ""


def fetch_view_counts(api_key: str, items: list) -> list:
    """再生回数をまとめて取る。1回の呼び出しで50本まで。"""
    if not items:
        return []
    ids = ",".join(i["video_id"] for i in items[:50])
    try:
        resp = requests.get(
            f"{YOUTUBE_API}/videos",
            params={"key": api_key, "part": "statistics", "id": ids},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] 再生回数の取得に失敗しました: {e}", file=sys.stderr)
        return []

    counts = {}
    for it in resp.json().get("items", []):
        st = it.get("statistics") or {}
        try:
            counts[it.get("id")] = int(st.get("viewCount", 0))
        except (TypeError, ValueError):
            continue

    out = []
    for i in items:
        v = counts.get(i["video_id"])
        if v is None:
            continue
        out.append({**i, "views": v, "matchup": extract_matchup(i["title"])})
    out.sort(key=lambda x: -x["views"])
    return out


MLB_API = "https://statsapi.mlb.com/api/v1"


def game_date_from_title(title: str, published_at: str = "") -> str:
    """
    ハイライトのタイトルから試合日を取る。

    MLB公式は "(August 10)" のように必ず日付を入れている。
    投稿日から引き算する方法もあるが、投稿が翌日にずれる試合があるので、
    書いてある日付を読む方が確実。読めなければ空を返す。
    """
    m = re.search(r"\(([A-Z][a-z]+)\s+(\d{1,2})\)", title)
    if not m:
        return ""
    year = (published_at or "")[:4] or str(datetime.now(timezone.utc).year)
    try:
        return datetime.strptime(
            f"{m.group(1)} {int(m.group(2))} {year}", "%B %d %Y"
        ).date().isoformat()
    except ValueError:
        return ""


def _performer_line(players: dict) -> list:
    """出場選手から、目立った成績を点数付きで並べる。"""
    out = []
    for pl in players.values():
        s = pl.get("stats") or {}
        bat, pit = s.get("batting") or {}, s.get("pitching") or {}
        name = (pl.get("person") or {}).get("fullName", "")
        if not name:
            continue
        if bat.get("atBats"):
            score = (bat.get("hits", 0) * 2 + bat.get("homeRuns", 0) * 4
                     + bat.get("rbi", 0) * 2)
            line = (f"{bat.get('atBats')}打数{bat.get('hits', 0)}安打"
                    + (f" {bat['rbi']}打点" if bat.get("rbi") else "")
                    + (f" {bat['homeRuns']}本塁打" if bat.get("homeRuns") else ""))
            out.append((score, name, line))
        ip = pit.get("inningsPitched")
        # 短いリリーフは「活躍」として出すには根拠が薄いので4回以上に限る
        if ip and _f(ip) >= 4:
            score = (int(_f(ip)) * 2 + pit.get("strikeOuts", 0)
                     - pit.get("earnedRuns", 0) * 3)
            out.append((score, name,
                        f"{ip}回 {pit.get('strikeOuts', 0)}奪三振"
                        f" 自責{pit.get('earnedRuns', 0)}"))
    out.sort(reverse=True)
    return out


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_result(date: str, teams: list) -> dict:
    """
    その日のその対戦の結果と、最も目立った選手を取る。

    再生回数は「見られた量」でしかない。何が起きた試合なのかが
    並んでいないと、順位に説得力が出ない。
    取れなければ空を返し、順位だけをこれまで通り出す。
    """
    if not date or len(teams) < 2:
        return {}
    try:
        sch = requests.get(f"{MLB_API}/schedule",
                           params={"sportId": 1, "date": date}, timeout=25)
        sch.raise_for_status()
        games = [g for d in sch.json().get("dates", [])
                 for g in d.get("games", [])]
    except Exception:
        return {}

    for g in games:
        away = ((g.get("teams") or {}).get("away") or {})
        home = ((g.get("teams") or {}).get("home") or {})
        an = (away.get("team") or {}).get("name", "")
        hn = (home.get("team") or {}).get("name", "")
        if not all(any(t.lower() in x.lower() for x in (an, hn))
                   for t in teams):
            continue
        if away.get("score") is None or home.get("score") is None:
            return {}
        res = {
            "away_jp": jp_team(an), "home_jp": jp_team(hn),
            "away_score": away["score"], "home_score": home["score"],
        }
        # イニングごとの点。スコアボードを描くのに要る。
        # 最終スコアだけだと「7対6だった」しか言えないが、
        # 回ごとの並びがあれば、どこで動いた試合なのかが一目で分かる。
        try:
            ls = requests.get(f"{MLB_API}/game/{g['gamePk']}/linescore",
                              timeout=25)
            ls.raise_for_status()
            line = ls.json()
            res["innings"] = [
                {"num": i.get("num"),
                 "away": (i.get("away") or {}).get("runs"),
                 "home": (i.get("home") or {}).get("runs")}
                for i in (line.get("innings") or [])]
            for side in ("away", "home"):
                t = (line.get("teams") or {}).get(side) or {}
                res[side + "_hits"] = t.get("hits")
                res[side + "_errors"] = t.get("errors")
        except Exception:
            pass

        try:
            bx = requests.get(f"{MLB_API}/game/{g['gamePk']}/boxscore",
                              timeout=25)
            bx.raise_for_status()
            data = bx.json()
            best = []
            for side in ("away", "home"):
                best += _performer_line(
                    (data.get("teams", {}).get(side, {}).get("players") or {}))
            best.sort(reverse=True)
            if best:
                res["star_name"] = best[0][1]
                res["star_line"] = best[0][2]
        except Exception:
            pass
        return res
    return {}


def jp_team(full_name: str) -> str:
    """"Texas Rangers" → "レンジャーズ"。引けなければ英語のまま。"""
    for en, jp in TEAM_EN_TO_JP.items():
        if full_name.endswith(en):
            return jp
    return full_name


def build(api_key: str, hours: int = 30, top: int = 5,
          state_path: str = "data/mlb_buzz.json") -> dict:
    cid = _official_channel_id(api_key, state_path)
    items = fetch_recent_highlights(api_key, hours, state_path)
    ranked = fetch_view_counts(api_key, items)
    if not ranked:
        return {}
    print(f"[info] 再生回数の取れたハイライト: {len(ranked)}本")

    # 上位だけ結果を引く。全部引くと呼び出しが増えるうえ、
    # 画面に出るのは上位だけなので意味がない。
    for r in ranked[:top]:
        date = game_date_from_title(r.get("title", ""), r.get("published_at", ""))
        names = [t.strip() for t in
                 str(r.get("matchup", "")).split(":")[0].split("vs.")]
        try:
            res = fetch_result(date, [n for n in names if n])
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 結果を取れません ({r.get('matchup')}): {e}",
                  file=sys.stderr)
            res = {}
        if res:
            r["result"] = res

    for r in ranked[:top]:
        res = r.get("result") or {}
        tail = ""
        if res:
            tail = (f"  {res['away_jp']} {res['away_score']}"
                    f"-{res['home_score']} {res['home_jp']}")
            if res.get("star_name"):
                tail += f" / {res['star_name']} {res['star_line']}"
        print(f"   {r['views']:>9,}回  {r['matchup']}{tail}")
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        # 覚えておく。次からは search を打たずに済む(100 -> 1ユニット)。
        "channel_id": cid,
        "videos": ranked[:top],
    }


# MLB公式のタイトルは英語表記。日本で通じる球団名に直す。
# 引き当てられないものは英語のまま扱う(勝手な当て字はしない)。
TEAM_EN_TO_JP = {
    "Angels": "エンゼルス", "D-backs": "ダイヤモンドバックス",
    "Diamondbacks": "ダイヤモンドバックス", "Orioles": "オリオールズ",
    "Red Sox": "レッドソックス", "Cubs": "カブス", "Reds": "レッズ",
    "Guardians": "ガーディアンズ", "Rockies": "ロッキーズ",
    "Tigers": "タイガース", "Astros": "アストロズ", "Royals": "ロイヤルズ",
    "Dodgers": "ドジャース", "Nationals": "ナショナルズ", "Mets": "メッツ",
    "Athletics": "アスレチックス", "Pirates": "パイレーツ",
    "Padres": "パドレス", "Mariners": "マリナーズ", "Giants": "ジャイアンツ",
    "Cardinals": "カージナルス", "Rays": "レイズ", "Rangers": "レンジャーズ",
    "Blue Jays": "ブルージェイズ", "Twins": "ツインズ",
    "Phillies": "フィリーズ", "Braves": "ブレーブス",
    "White Sox": "ホワイトソックス", "Marlins": "マーリンズ",
    "Yankees": "ヤンキース", "Brewers": "ブリュワーズ",
}


def extract_matchup(title: str) -> str:
    """
    ハイライトのタイトルから対戦カードの部分だけを取り出す。

    MLB公式のタイトルは書式が一定ではない。
      "Angels vs. Dodgers Game Highlights (8/9/26) | MLB Highlights"
      "RANGERS vs. ANGELS: Official Full Game Highlights (August 10) | ..."
    後者のように ":" 区切りの但し書きが挟まることがあり、
    そのまま持つと「... 対 ...: Official Full」と読み上げてしまう。
    """
    m = MATCHUP_RE.match(title)
    raw = m.group(1).strip() if m else title[:40]
    return raw.split(":")[0].strip()


def jp_matchup(matchup: str) -> str:
    """"Angels vs. Dodgers" -> "エンゼルス 対 ドジャース\""""
    # 保存済みの data/mlb_buzz.json には、但し書きが付いたままの
    # matchup が入っていることがある(取り出し側を直す前に保存された分)。
    # 取り出し時にも切っておかないと、次に取り直すまで
    # 「... 対 ...: Official Full」と読み上げ続けることになる。
    out = str(matchup).split(":")[0].strip()
    # 長い名前から先に置換する。"Red Sox" より先に "Sox" を処理すると壊れる。
    #
    # 大文字小文字は無視する。MLB公式のタイトルは球団名を
    # "RANGERS vs. ANGELS" と全て大文字で書くことがあり、
    # そのまま完全一致で探していたため日本語に変換されず、
    # 英語のまま読み上げていた。順位の突き合わせ(cross_check)も
    # 同じ理由で当たらなくなっていた。
    for en, jp in sorted(TEAM_EN_TO_JP.items(), key=lambda x: -len(x[0])):
        out = re.sub(re.escape(en), jp, out, flags=re.I)
    return re.sub(r"\s*\bvs\.?\s*", " 対 ", out, flags=re.I).strip()


def cross_check(buzz: list, games: list) -> list:
    """
    コレスポが注目試合として取り上げたカードが、
    現地の再生回数で何位だったかを突き合わせる。

    予告と結果の両方を持っているからこそできる照合になる。
    コレスポの選定はルール(日本人選手・順位・連勝など)で決めていて、
    現地の再生回数は人気球団に強く引かれるので、両者は一致しない方が普通。
    ずれること自体が「日本から見た注目」と「現地の注目」の違いを表す。

    MLB公式のタイトルは「ビジター vs. ホーム」の並びだが、
    順序に依存せず両チーム名が含まれるかで照合する。
    """
    ranked = [(i, b, jp_matchup(b.get("matchup", "")))
              for i, b in enumerate(buzz, 1)]
    out = []
    for g in games:
        home = (g.get("home_team_name") or "").strip()
        away = (g.get("away_team_name") or "").strip()
        if not home or not away:
            continue
        for rank, b, jp in ranked:
            if home in jp and away in jp:
                out.append({
                    "matchup": f"{home} 対 {away}",
                    "rank": rank,
                    "views": b.get("views", 0),
                    "total": len(buzz),
                })
                break
    return out


def load(path: str = "data/mlb_buzz.json", max_age_hours: int = 30) -> list:
    """
    表示側から読む。古い記録は使わない
    (昨日の「最も見られた試合」を今日のものとして出さないため)。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    try:
        updated = datetime.fromisoformat(data.get("updated_at", ""))
    except ValueError:
        return []
    age = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
    if age > max_age_hours:
        print(f"[info] 注目度データが古いため使いません({age:.0f}時間前)")
        return []
    return data.get("videos") or []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/mlb_buzz.json")
    parser.add_argument("--hours", type=int, default=30)
    args = parser.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("[info] YOUTUBE_API_KEY未設定のためスキップします")
        return

    data = build(api_key, hours=args.hours)
    if not data:
        print("[info] 取得できなかったため、ファイルは更新しません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 注目度を出力しました({len(data['videos'])}本) -> {out}")


if __name__ == "__main__":
    main()
