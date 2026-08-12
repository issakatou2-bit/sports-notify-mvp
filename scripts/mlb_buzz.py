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
  search.list で MLB公式チャンネルの直近のハイライトを拾い、
  videos.list でまとめて再生回数を取る。
  search が100ユニット、videos が1ユニットなので、1日1回なら
  1日の割り当て(10,000)に対して十分収まる。

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


def fetch_recent_highlights(api_key: str, hours: int = 30) -> list:
    published_after = (datetime.now(timezone.utc)
                       - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = requests.get(
            f"{YOUTUBE_API}/search",
            params={
                "key": api_key, "part": "snippet", "q": "Game Highlights",
                "type": "video", "order": "date", "maxResults": 50,
                "publishedAfter": published_after,
            },
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] ハイライトの検索に失敗しました: {e}", file=sys.stderr)
        return []

    items = []
    for it in resp.json().get("items", []):
        sn = it.get("snippet") or {}
        if sn.get("channelTitle") != OFFICIAL_CHANNEL_TITLE:
            continue
        vid = (it.get("id") or {}).get("videoId")
        if not vid:
            continue
        items.append({
            "video_id": vid,
            "title": sn.get("title", ""),
            "published_at": sn.get("publishedAt", ""),
        })
    print(f"[info] MLB公式の直近{hours}時間のハイライト: {len(items)}本")
    return items


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


def build(api_key: str, hours: int = 30, top: int = 5) -> dict:
    items = fetch_recent_highlights(api_key, hours)
    ranked = fetch_view_counts(api_key, items)
    if not ranked:
        return {}
    print(f"[info] 再生回数の取れたハイライト: {len(ranked)}本")
    for r in ranked[:top]:
        print(f"   {r['views']:>9,}回  {r['matchup']}")
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
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
