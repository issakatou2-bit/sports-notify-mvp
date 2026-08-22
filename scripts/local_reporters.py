#!/usr/bin/env python3
"""
現地の番記者が今日書いたことを拾い、日本語に直す。

    python3 scripts/local_reporters.py --out data/local_reporters.json

なぜこれを足すのか:
  コレスポがこれまで拾っていた「現地」は、再生回数(mlb_buzz)と
  名前の登場回数(local_buzz)、つまり量だけだった。
  何を言っているかは、ファンの投稿を翻訳する local_voices しか無い。

  番記者は、その球団を毎日追っている人が実名で書いている一次情報で、
  日本語にはほぼ流れてこない。取材した人が「今日はこうだった」と
  書いた内容は、数字の裏側を埋める材料になる。

どう取るか:
  BlueskyのAT Protocolは、公開エンドポイントに認証が要らない。
    app.bsky.feed.getAuthorFeed  … 特定アカウントの投稿(認証なしで通る)
    app.bsky.actor.searchActors  … 記者を名前で探す(同上)
  検索(searchPosts)は403で使えないので、こちらから見に行く形にする。
  そのため名簿が要る。下のREPORTERSは searchActors で洗い出し、
  実際に投稿を取得できることまで確認したもの。

  いいね数とリポスト数が付いてくるので、どれが刺さった投稿かを
  こちらの判断ではなく現地の反応で並べられる。
"""

import argparse
import functools
import json
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import JP_PLAYERS_MLB, MLB_TEAM_NAME_JP  # noqa: E402

BASE = "https://public.api.bsky.app/xrpc"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}

# 番記者の名簿。
# scripts/local_reporters.py --discover で洗い出せるが、
# 同名の他競技(NFLのGiants・Cardinals)が混ざるため、最後は人が選ぶ。
# 所属は確認した時点のもので、移籍する。取れなくなったら外すこと。
REPORTERS = [
    # (handle, 球団, 媒体)
    ("billplunkett.bsky.social", "ドジャース", "Southern California News Group"),
    ("chriskirschner.bsky.social", "ヤンキース", "The Athletic"),
    ("garyhphillips.bsky.social", "ヤンキース", "New York Daily News"),
    ("jcmccaffrey.bsky.social", "レッドソックス", "The Athletic"),
    ("timbhealey.bsky.social", "レッドソックス", "Boston Globe"),
    ("maccerullo.bsky.social", "レッドソックス", "Boston Herald"),
    ("peteabeglobeew.bsky.social", "レッドソックス", "Boston Globe"),
    ("keeganmatheson.bsky.social", "ブルージェイズ", "MLB.com"),
    ("jefffletcherocr.bsky.social", "エンゼルス", "Orange County Register"),
    ("samblum3.bsky.social", "エンゼルス", "The Athletic"),
    ("chandlerrome.bsky.social", "アストロズ", "The Athletic"),
    ("mmontemurro.bsky.social", "カブス", "Chicago Tribune"),
    ("tonyandracki23.bsky.social", "カブス", "Marquee Sports Network"),
    ("miguardado.bsky.social", "ジャイアンツ", "MLB.com"),
    ("ewebeck.bsky.social", "ジャイアンツ", "San Jose Mercury News"),
    ("timstebbins.bsky.social", "ガーディアンズ", "MLB.com"),
    ("lalbanese.bsky.social", "メッツ", "Newsday"),
    ("mannygo3.bsky.social", "メッツ", "NJ Advance Media"),
    ("afkostka.bsky.social", "オリオールズ", "Baltimore Banner"),
    ("jakerill.bsky.social", "オリオールズ", "MLB.com"),
    ("danielleallentuck.bsky.social", "オリオールズ", "Baltimore Banner"),
    ("sdutkevinacee.bsky.social", "パドレス", "San Diego Union Tribune"),
    ("mattgelb.bsky.social", "フィリーズ", "The Athletic"),
    ("toddzolecki.bsky.social", "フィリーズ", "MLB.com"),
    ("jasonbeck.bsky.social", "タイガース", "MLB.com"),
    ("daniel-guerrero.bsky.social", "カージナルス", "St. Louis Post-Dispatch"),

    # 球団を持たない全国担当。特定の球団に張り付いていないぶん、
    # 日本人選手のように球団をまたぐ話題を拾いやすい。
    ("feinsand.bsky.social", "全国", "MLB.com"),
    ("samdykstramilb.bsky.social", "全国", "MLB Pipeline"),
    ("jimcallis.bsky.social", "全国", "MLB Pipeline"),

    # 日本人選手が所属する球団を厚くする
    ("bastianmlb.bsky.social", "カブス", "MLB.com"),          # 鈴木誠也・今永昇太
    ("ianmbrowne.bsky.social", "レッドソックス", "MLB.com"),      # 吉田正尚
    ("willsammon.bsky.social", "メッツ", "The Athletic"),      # 千賀滉大
    ("annerogers.bsky.social", "ロイヤルズ", "MLB.com"),
    ("kennlandry.bsky.social", "レンジャーズ", "MLB.com"),
    ("adammccalvy.bsky.social", "ブルワーズ", "MLB.com"),
    ("patricksaundersdp.bsky.social", "ロッキーズ", "Denver Post"),
    ("nightengalejr.bsky.social", "ツインズ", "Star Tribune"),
    ("gdubmlb.bsky.social", "レッズ", "Cincinnati Enquirer"),
]

# 取り込む時間幅。朝の枠で使うので、前夜の試合を含む長さにする。
HOURS = 30

# 1人あたり何件見るか。多くしても、古い投稿が増えるだけ。
PER_AUTHOR = 12

# 翻訳して出す件数。動画1画面に載る量。
TOP_N = 6


def fetch_author(handle: str, limit: int = PER_AUTHOR) -> list:
    r = requests.get(f"{BASE}/app.bsky.feed.getAuthorFeed",
                     params={"actor": handle, "limit": limit},
                     headers=UA, timeout=20)
    r.raise_for_status()
    return r.json().get("feed", [])


# 1つの投稿から拾う返信の上限。全部拾うと、その1件で画面が埋まる。
REPLIES_PER_POST = 4

# 返信を拾う投稿の数。多いと呼び出しが増えるので、反応の大きい順に絞る。
THREADS_TO_OPEN = 3


def fetch_replies(uri: str) -> list:
    """
    その投稿に付いた返信を、いいね数つきで返す。

    なぜ要るのか:
      番記者が何を書いたかは取れていたが、それを読んだ人が何を言ったかは
      取れていなかった。議論や言い合いはそちらにある。

      Blueskyの公開エンドポイントは認証が要らず、返信も、それぞれの
      いいね数も付いてくる。何人が同意したかが分かるので、
      「誰か1人がそう言った」と「多くがそう思った」を区別できる。

      Redditはコメント本文がRSSに含まれず、Xは有料。
      いま無料で議論そのものが取れるのはここだけ。
    """
    try:
        r = requests.get(f"{BASE}/app.bsky.feed.getPostThread",
                         params={"uri": uri, "depth": 1},
                         headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 返信を取れませんでした: {e}", file=sys.stderr)
        return []
    out = []
    for item in ((r.json().get("thread") or {}).get("replies") or []):
        post = item.get("post") or {}
        text = ((post.get("record") or {}).get("text") or "").strip()
        if not text:
            continue
        out.append({
            "text": text,
            "likes": post.get("likeCount") or 0,
            "author": ((post.get("author") or {}).get("handle") or ""),
        })
    # 支持された順。1件しか賛同の無い返信と、100件のものは重みが違う。
    out.sort(key=lambda x: -x["likes"])
    return out[:REPLIES_PER_POST]


def _recent(iso: str, hours: int) -> bool:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    return t >= datetime.now(timezone.utc) - timedelta(hours=hours)


def _keywords() -> list:
    """拾う対象。日本人選手の英語名と、球団の英語側の手掛かり。"""
    out = [p["name_en"] for p in JP_PLAYERS_MLB]
    # 姓だけでも拾う(記者は姓で書くことが多い)
    out += [p["name_en"].split()[-1] for p in JP_PLAYERS_MLB]
    return sorted(set(out), key=len, reverse=True)


def collect(hours: int = HOURS, sleep: float = 0.3) -> list:
    """名簿を回って、直近の投稿を集める。"""
    kws = _keywords()
    out = []
    for handle, team, outlet in REPORTERS:
        try:
            feed = fetch_author(handle)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] @{handle}: {e}", file=sys.stderr)
            time.sleep(sleep)
            continue

        for item in feed:
            p = item.get("post") or {}
            rec = p.get("record") or {}
            # 投稿は改行を含む。PILは改行入りの文字列の幅を測れず、
            # 折り返し処理がそこで落ちる。取り込む時点で1行に均す。
            text = re.sub(r"\s*\n+\s*", " ", (rec.get("text") or "")).strip()
            if not text or not _recent(rec.get("createdAt", ""), hours):
                continue
            # リポストは本人の言葉ではないので外す
            if item.get("reason"):
                continue

            hit = [k for k in kws if re.search(rf"\b{re.escape(k)}\b", text)]
            out.append({
                "handle": handle,
                "author": (p.get("author") or {}).get("displayName", handle),
                "team": team,
                "outlet": outlet,
                "text": text,
                "likes": p.get("likeCount", 0),
                "reposts": p.get("repostCount", 0),
                "replies": p.get("replyCount", 0),
                "at": rec.get("createdAt", ""),
                "uri": p.get("uri", ""),
                "jp_players": hit,
            })
        time.sleep(sleep)
    return out


def attach_replies(posts: list, sleep: float = 0.3) -> list:
    """
    反応の大きい投稿に、その返信を足す。

    全部の投稿で開くと呼び出しが投稿数ぶん増える。議論が起きているのは
    返信数の多い投稿なので、そこだけ開く。返信数はもう取れている。
    """
    targets = sorted((p for p in posts if p.get("replies")),
                     key=lambda p: -(p.get("replies") or 0))[:THREADS_TO_OPEN]
    for p in targets:
        if not p.get("uri"):
            continue
        p["reply_texts"] = fetch_replies(p["uri"])
        if p["reply_texts"]:
            print(f"[info] @{p['handle']} の投稿に返信 "
                  f"{len(p['reply_texts'])}件 "
                  f"(最多いいね {p['reply_texts'][0]['likes']})")
        time.sleep(sleep)
    return posts


def rank(posts: list, top: int = TOP_N) -> list:
    """
    どれを出すか。こちらの好みではなく、現地の反応の大きさで決める。

    日本人選手に触れている投稿は優先する。日本語圏に向けて出すので、
    同じ反応量なら、そちらの方が読む理由がある。
    """
    def key(p):
        engage = p["likes"] + p["reposts"] * 2 + p["replies"]
        return (-(1 if p["jp_players"] else 0), -engage)

    seen, out = set(), []
    for p in sorted(posts, key=key):
        # 同じ記者ばかりにならないよう2件まで
        if sum(1 for x in out if x["handle"] == p["handle"]) >= 2:
            continue
        if p["text"][:40] in seen:
            continue
        seen.add(p["text"][:40])
        out.append(p)
        if len(out) >= top:
            break
    return out


def _jp_name_hint() -> str:
    """日本人選手の「英語名 → 日本語表記」を、訳す側へ渡す形にする。"""
    try:
        from notability_engine import JP_PLAYERS_MLB
    except ImportError:
        return ""
    return "\n".join("  %s → %s" % (p["name_en"], p["name_jp"])
                     for p in JP_PLAYERS_MLB)


def translate(posts: list, api_key: str) -> list:
    """
    まとめて1回で訳す。1件ずつ呼ぶと件数ぶん課金される。

    訳文は事実の提示ではなく、誰かが書いたことの翻訳なので、
    出す側で「記者の発言」と分かる形にすること(動画では画面を分ける)。
    """
    if not posts or not api_key:
        return posts
    try:
        import anthropic
    except ImportError:
        print("[warn] anthropic が無いため翻訳しません", file=sys.stderr)
        return posts

    numbered = "\n".join(f"{i + 1}. {p['text']}" for i, p in enumerate(posts))
    prompt = (
        "次はMLBの番記者がSNSに書いた投稿です。"
        "それぞれを日本語に訳してください。\n"
        "・1行に1件、番号をつけて出力\n"
        "・意訳しすぎず、書かれていないことを足さない\n"
        "・80文字以内に収める\n"
        "・URLや記事へのリンクは訳さず省く\n"
        # 「ショウヘイ・オータニが2本塁打」という題が実際に出た。
        # 音写されると日本語の題として読みにくく、検索にも当たらない。
        # 正しい表記を渡しておけば、選ぶだけで済む。
        "・日本人選手は必ず次の表記を使う(音写しない):\n"
        + _jp_name_hint() + "\n\n"
        + numbered
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        if msg.stop_reason == "max_tokens":
            print("[warn] 翻訳が途中で切れたため使いません", file=sys.stderr)
            return posts
        body = msg.content[0].text
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 翻訳に失敗しました: {e}", file=sys.stderr)
        return posts

    lines = {}
    for line in body.splitlines():
        m = re.match(r"\s*(\d+)[.):]\s*(.+)", line)
        if m:
            lines[int(m.group(1))] = m.group(2).strip()
    for i, p in enumerate(posts, 1):
        if i in lines:
            p["jp"] = lines[i]
    return posts


# ---------------------------------------------------------------------------
# 現地の見出し(Google ニュース RSS)
# ---------------------------------------------------------------------------
# 記者の名簿は「誰を見るか」を先に決める方式なので、名簿の外で起きたことは
# 拾えない。こちらは逆に「何を探すか」を指定でき、選手名で直接引ける。
# キーもアカウントも要らず、1クエリで100件前後返る。
#
# 見出しだけを使い、本文は取りに行かない。見出しは事実の要約で、
# 誰の解釈も入っていないため、そのまま訳せる。

NEWS_RSS = ("https://news.google.com/rss/search?q={q}"
            "&hl=en-US&gl=US&ceid=US:en")


def fetch_headlines(query: str, limit: int = 8) -> list:
    import urllib.parse
    url = NEWS_RSS.format(q=urllib.parse.quote(f"{query} when:1d"))
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    items = re.findall(r"<item>(.*?)</item>", r.text, re.S)
    out = []
    for it in items[:limit]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        s = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        if not t:
            continue
        title = t.group(1).strip()
        # Google ニュースの見出しは "本文 - 媒体名" の形
        source = s.group(1).strip() if s else ""
        if source and title.endswith(f"- {source}"):
            title = title[: -len(source) - 2].strip()
        out.append({"query": query, "title": title,
                    "source": source, "at": d.group(1) if d else ""})
    return out


# 野球の記事だと分かる語。球団名は notability_engine から取る。
_BALL_WORDS = ("mlb", "pitcher", "pitching", "homer", "home run", "strikeout",
               "strikeouts", " ks", "inning", "innings", "bullpen", "lineup",
               "shutout", "rbi", "no-hitter", "rotation", "all-star",
               "world series", "playoff", "postseason", "baseball")


@functools.lru_cache(maxsize=1)
def _ball_terms() -> tuple:
    try:
        from notability_engine import MLB_TEAM_NAME_EN
        teams = tuple(v.lower() for v in MLB_TEAM_NAME_EN.values() if v)
    except ImportError:
        teams = ()
    return _BALL_WORDS + teams


def _mentions(title: str, name_en: str) -> bool:
    """その見出しを、この枠に載せてよいか。

    Googleニュースは検索語と緩く結びついたものも返す。
    「Yu Darvish」で引いたら「Chicago home prices spike…」が来た。
    ダルビッシュが昔シカゴにいたというだけで、野球ですらない。
    それが「現地メディアは何と言っているか」に並んでいた。

    残すのは、その選手の姓が入っているか、野球の記事だと分かるもの。
    姓だけを条件にすると、デグロムの2000奪三振のような、
    日本人選手の話ではないがこの枠に合う記事まで落ちる。
    """
    low = (title or "").lower()
    parts = [x for x in name_en.split() if len(x) > 2]
    if parts and parts[-1].lower() in low:
        return True
    return any(w in low for w in _ball_terms())


def collect_headlines(sleep: float = 0.4) -> list:
    """日本人選手の名前で、現地の見出しを引く。"""
    out, dropped = [], 0
    for p in JP_PLAYERS_MLB:
        try:
            got = fetch_headlines(p["name_en"], limit=4)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {p['name_en']}: {e}", file=sys.stderr)
            time.sleep(sleep)
            continue
        keep = [h for h in got if _mentions(h.get("title", ""), p["name_en"])]
        dropped += len(got) - len(keep)
        out += keep
        time.sleep(sleep)
    if dropped:
        print(f"[info] 選手名の入っていない見出しを{dropped}件外しました")

    # 同じ見出しが複数の選手で出ることがある。
    # 媒体によって "Exclusive | " のような枕が付くので、そこも落として比べる。
    seen, uniq = set(), []
    for h in out:
        k = _dedupe_key(h["title"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    return uniq


def _dedupe_key(title: str) -> str:
    """見出しの同一判定に使う形。枕と記号を落とす。

    「Sammy Sosa reveals…」と「Exclusive | Sammy Sosa reveals…」が
    別物として2件並んでいた。同じ記事なので1件にする。
    """
    t = re.sub(r"^[^|]{0,18}\|\s*", "", (title or "").strip())
    t = re.sub(r"[^a-z0-9]+", "", t.lower())
    return t[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/local_reporters.json")
    ap.add_argument("--hours", type=int, default=HOURS)
    ap.add_argument("--top", type=int, default=TOP_N)
    ap.add_argument("--discover", action="store_true",
                    help="Blueskyから番記者を探して候補を出す(名簿の更新用)")
    args = ap.parse_args()

    if args.discover:
        teams = ["Dodgers", "Yankees", "Red Sox", "Cubs", "Padres", "Mets",
                 "Blue Jays", "Angels", "Mariners", "Braves", "Phillies"]
        for t in teams:
            r = requests.get(f"{BASE}/app.bsky.actor.searchActors",
                             params={"q": f"{t} beat writer", "limit": 8},
                             headers=UA, timeout=20)
            if not r.ok:
                continue
            for a in r.json().get("actors", []):
                d = (a.get("description") or "").replace("\n", " ")
                if re.search(r"beat (writer|reporter)|reporter for", d, re.I):
                    print(f"  {t:12} @{a['handle']:34} {d[:70]}")
            time.sleep(0.3)
        return 0

    posts = collect(hours=args.hours)
    # 反応の大きい投稿には、その返信(ファンの議論)も足す。
    # 記者が何を書いたかだけでなく、それを読んだ人が何と言ったか。
    posts = attach_replies(posts)
    print(f"[info] 直近{args.hours}時間の投稿: {len(posts)}件"
          f" (名簿 {len(REPORTERS)}人)")
    jp_hits = [p for p in posts if p["jp_players"]]
    print(f"[info] 日本人選手に触れているもの: {len(jp_hits)}件")

    top = rank(posts, args.top)

    # 選手名で直接引く見出し。名簿の外で起きたことを拾う。
    heads = collect_headlines()
    print(f"[info] 現地の見出し(直近1日): {len(heads)}件")

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    top = translate(top, key)
    # 見出しも同じ形に詰めて、まとめて1回で訳す
    head_items = [{"text": h["title"]} for h in heads[:args.top]]
    head_items = translate(head_items, key)
    for h, t in zip(heads, head_items):
        if t.get("jp"):
            h["jp"] = t["jp"]

    for p in top:
        print(f"   ♥{p['likes']:4} RT{p['reposts']:3}  @{p['handle'][:22]:24}"
              f" {p.get('jp') or p['text'][:60]}")
    for h in heads[:args.top]:
        print(f"   [見出し] {h['source'][:18]:20} "
              f"{h.get('jp') or h['title'][:60]}")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hours": args.hours,
        "reporters": len(REPORTERS),
        "collected": len(posts),
        "posts": top,
        "headlines": heads[:args.top],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
