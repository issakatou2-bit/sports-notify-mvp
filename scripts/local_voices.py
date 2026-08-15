"""
現地のファンが実際に何と言っているかを集めて、日本語にする。

このシリーズの位置づけ:
  コレスポの他のコンテンツは、APIから取った数字だけで作っている。
  こちらは違う。現地の投稿を翻訳して紹介するので、訳し方の加減は
  こちらの手に委ねられていて、数字のように検証はできない。

  だから事実のコーナーと混ぜない。「現地の声」として独立させ、
  画面にも出典と「翻訳」であることを必ず出す。
  読み手が「これは誰かの感想であって記録ではない」と分かる状態にする。

  逆に言えば、そう切り分けてあるからこそ扱える。
  数字だけでは出てこない熱量や温度は、ここでしか伝えられない。

取り方:
  MLB公式ハイライトのコメント欄を読む。その試合を見た人が、見た直後に
  書いた言葉が集まる場所で、賛同の多い順に取る。動画IDは mlb_buzz.py が
  既に取っているので、探し直す必要はない。

  取れなかった日は r/baseball のRSSに落ちる。ただしそちらで取れるのは
  投稿の見出しだけで、その多くは定型スレッドの名前であり、
  「ファンが何を言ったか」としては弱い。あくまで予備。

  原文は必ず併記し、出典を残す。

出力: data/local_voices.json

使い方:
  ANTHROPIC_API_KEY=xxx python3 scripts/local_voices.py --out data/local_voices.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"
UA = {"User-Agent": "collespo/1.0 (+https://collespo.com)"}
SOURCE = ("r/baseball", "https://www.reddit.com/r/baseball/.rss")

# 紹介する件数。多いと1本の動画に入らないうえ、
# 拾う数を増やすほど「都合のいいものを選んだ」余地も広がる。
MAX_VOICES = 4

# 定型の運営スレッドは反応ではないので除く
SKIP_PATTERNS = [
    r"^\[?General Discussion\]?",
    r"Game Thread Index",
    r"^Daily Discussion",
    r"^Monthly",
    r"America's Pastime",
]


def fetch_youtube_comments(buzz_path: str = "data/mlb_buzz.json",
                           per_video: int = 6) -> list:
    """
    MLB公式ハイライトに付いたコメントを取る。

    なぜここを見るのか:
      r/baseball のRSSから取れるのは投稿の見出しだけで、その多くは
      「OFFICIAL FRIDAY TRASH TALK THREAD」のような定型スレッドの名前。
      ファンが試合を見て何を言ったか、ではない。
      公式ハイライトのコメント欄は、その試合を見た人がその場で書いた
      言葉が集まる。母数も大きく、日ごとに必ず湧く。

      動画IDは mlb_buzz.py が既に取っているので、追加の検索は要らない。
      commentThreads.list は1本1ユニットで、割り当てへの影響はほぼ無い。

    コメントを切っている動画は403が返る。その動画だけ飛ばす。
    """
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("[info] YOUTUBE_API_KEY未設定のため、コメントは取りません")
        return []
    try:
        videos = json.loads(
            pathlib.Path(buzz_path).read_text(encoding="utf-8")).get("videos", [])
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] {buzz_path} を読めませんでした: {e}", file=sys.stderr)
        return []

    out = []
    for v in videos[:4]:
        vid = v.get("video_id")
        if not vid:
            continue
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params={"part": "snippet", "videoId": vid, "key": api_key,
                        "order": "relevance", "maxResults": per_video,
                        "textFormat": "plainText"},
                timeout=25)
            if r.status_code == 403:
                print(f"[info] {vid}: コメントが取れません(無効化されている可能性)")
                continue
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {vid} のコメント取得に失敗: {e}", file=sys.stderr)
            continue

        for item in data.get("items", []):
            c = ((item.get("snippet") or {}).get("topLevelComment") or {}
                 ).get("snippet") or {}
            text = (c.get("textOriginal") or "").strip()
            # 短すぎるものは訳しても中身が無い。長すぎるものは読み上げに載らない。
            if not (12 <= len(text) <= 220):
                continue
            out.append({
                "title": " ".join(text.split()),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "likes": int(c.get("likeCount") or 0),
                "source": "MLB公式ハイライトのコメント",
                "matchup": v.get("matchup") or v.get("title", "")[:40],
            })

    # 賛同の多い順。少数の意見を上に置くと、選び方の恣意が入る。
    out.sort(key=lambda x: -x["likes"])
    print(f"[info] 公式ハイライトのコメント: {len(out)}件")
    return out


def fetch_titles() -> list:
    name, url = SOURCE
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[warn] {name} の取得に失敗しました: {e}", file=sys.stderr)
        return []

    out = []
    for entry in root.iter():
        if not entry.tag.endswith("entry"):
            continue
        title = link = None
        for child in entry:
            if child.tag.endswith("title") and child.text:
                title = child.text.strip()
            elif child.tag.endswith("link"):
                link = child.attrib.get("href")
        if not title:
            continue
        if any(re.search(p, title, re.I) for p in SKIP_PATTERNS):
            continue
        out.append({"title": title, "url": link})
    print(f"[info] {name}: {len(out)}件(定型スレッドを除く)")
    return out


def translate(client, items: list) -> list:
    """
    見出しをまとめて日本語にする。1件ずつ呼ぶとAPI呼び出しが増えるので、
    1回のやり取りで全件を訳させる。
    """
    numbered = "\n".join(f"{i + 1}. {it['title']}" for i, it in enumerate(items))
    prompt = (
        "以下は、アメリカの野球ファンが集まる掲示板 r/baseball に"
        "投稿された見出しです。日本語に訳してください。\n\n"
        f"{numbered}\n\n"
        "条件:\n"
        "- 1行につき1件、「番号. 訳文」の形式だけを出力する\n"
        "- 意訳しすぎず、元の言い回しの雰囲気を残す\n"
        "- スラングや略語は、日本語として自然な範囲で分かるように訳す\n"
        "- 訳せない固有名詞(選手名・球団名)は英語のまま残してよい\n"
        "- 感想や補足は加えない。書かれていないことを足さない\n"
        "- 前置きや説明は不要"
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "max_tokens":
        print("[warn] 訳が途中で切れたため、この回は使いません", file=sys.stderr)
        return []
    text = "".join(b.text for b in resp.content if b.type == "text")

    translated = {}
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[.、]\s*(.+)", line.strip())
        if m:
            translated[int(m.group(1))] = m.group(2).strip()

    out = []
    for i, it in enumerate(items, 1):
        ja = translated.get(i)
        if ja:
            out.append({**it, "ja": ja})
    return out


def build(limit: int = MAX_VOICES) -> dict:
    # 公式ハイライトのコメントを先に見る。試合を見た人が書いた言葉が
    # 集まる場所で、r/baseball の見出しより「反応」に近い。
    # 取れなかった日はRSSに落ちる(どちらも無い日は何も作らない)。
    items = fetch_youtube_comments()
    source_name, source_url = "MLB公式ハイライトのコメント", "https://www.youtube.com/@MLB"
    if not items:
        items = fetch_titles()
        source_name = SOURCE[0]
        source_url = f"https://www.reddit.com/{SOURCE[0]}/"
    if not items:
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or anthropic is None:
        print("[info] ANTHROPIC_API_KEY未設定のため、翻訳はしません")
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    try:
        voices = translate(client, items[:limit])
    except Exception as e:
        print(f"[warn] 翻訳に失敗しました: {e}", file=sys.stderr)
        return {}

    if not voices:
        return {}
    print(f"[info] 訳せた見出し: {len(voices)}件")
    for v in voices:
        print(f"   {v['ja']}")
        print(f"     原文: {v['title'][:70]}")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_name,
        "source_url": source_url,
        "voices": voices,
    }


def load(path: str = "data/local_voices.json", max_age_hours: int = 30) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(data.get("updated_at", ""))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    if (datetime.now(timezone.utc) - updated).total_seconds() / 3600 > max_age_hours:
        print("[info] 現地の声のデータが古いため使いません")
        return {}
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/local_voices.json")
    parser.add_argument("--limit", type=int, default=MAX_VOICES)
    args = parser.parse_args()

    data = build(limit=args.limit)
    if not data:
        print("[info] 取得できなかったため、ファイルは更新しません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[info] 現地の声を出力しました -> {out}")


if __name__ == "__main__":
    main()
