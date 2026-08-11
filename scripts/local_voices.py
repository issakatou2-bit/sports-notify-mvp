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
  r/baseball のRSSから投稿の見出しを取る(認証不要)。
  MLBの話題に関係するものだけを選び、AIで自然な日本語にする。
  原文は必ず併記し、出典としてsubreddit名を残す。

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
    items = fetch_titles()
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
        "source": SOURCE[0],
        "source_url": f"https://www.reddit.com/{SOURCE[0]}/",
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
