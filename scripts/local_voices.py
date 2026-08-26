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
from datetime import datetime, timedelta, timezone

import requests

# notability_engine はリポジトリ直下にある。
# python scripts/local_voices.py で起動すると scripts/ しか経路に入らず、
# jp_mentioned() の中の取り込みが ModuleNotFoundError になる。
# 翻訳が終わったあとに落ちるので、API呼び出しごと無駄になる。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

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


WORD = chr(92) + "b"   # 単語境界。書き換えの経路で消えやすいので定数で持つ


def note(line: str) -> None:
    """出なかった理由を実行ページにも出す。

    ここは continue-on-error で走らせている。止めたくないからで、
    その判断は変えない。ただ黙って抜けると、前の日のファイルが
    そのまま残り、翌朝の診断は「55時間前・古い」としか言わない。
    なぜ古いのかはログの奥にしか無く、誰も開かない。
    実際そうやって3日ぶん止まっていた。
    """
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + chr(10))


def jp_mentioned(text: str) -> list:
    """そのコメントに名前が出ている日本人選手。

    姓と名を、語として丸ごと一致するときだけ拾う。愛称は追わない。
    「Yoshi」が吉田なのか他の誰かなのかは文面からは決まらないので、
    取り違えるくらいなら拾わないほうがよい。

    正規表現は使わない。単語境界の書き方が、書き換えの経路で
    何度も消えた。語で切って集合で突き合わせれば同じことができる。
    """
    import textkey
    from notability_engine import JP_PLAYERS_MLB

    words = set()
    cur = []
    for ch in textkey.key(text or ""):
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            words.add("".join(cur))
            cur = []
    if cur:
        words.add("".join(cur))

    out = []
    for pl in JP_PLAYERS_MLB:
        for w in (pl.get("name_en") or "").split():
            if len(w) >= 4 and textkey.key(w) in words:
                out.append(pl["name_jp"])
                break
    return out

def fetch_youtube_comments(buzz_path: str = "data/mlb_buzz.json",
                           per_video: int = 20) -> list:
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
                # replies も取る。賛否が割れたコメントは返信が伸びるので、
                # 「どれだけ受けたか」を見るのに件数が効く。
                params={"part": "snippet,replies", "videoId": vid,
                        "key": api_key, "order": "relevance",
                        "maxResults": per_video, "textFormat": "plainText"},
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
            replies = [
                (rc.get("snippet") or {}).get("textOriginal", "").strip()
                for rc in ((item.get("replies") or {}).get("comments") or [])
            ]
            out.append({
                # コメントの投稿時刻。動画の公開からどれだけ経って
                # 書かれたかを見るのに要る。何時に取りにいくのが
                # いちばん溜まっているのかは、これでしか分からない。
                "at": c.get("publishedAt", ""),
                "video_published_at": v.get("published_at", ""),
                "title": " ".join(text.split()),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "likes": int(c.get("likeCount") or 0),
                "replies": int((item.get("snippet") or {})
                               .get("totalReplyCount") or 0),
                "reply_texts": [" ".join(x.split())
                                for x in replies if 4 <= len(x) <= 200][:3],
                "author": c.get("authorDisplayName", ""),
                "source": "MLB公式ハイライトのコメント",
                "matchup": v.get("matchup") or v.get("title", "")[:40],
            })

    # 賛同の多い順。少数の意見を上に置くと、選び方の恣意が入る。
    out.sort(key=lambda x: -x["likes"])

    # ただし先頭だけは、返信のいちばん多い一言に譲る。
    #
    # 高評価は「そう思う」を押した人の数で、一人が言い切って終わる。
    # 返信が付くのは、誰かがそれに言い返したということ。
    # ファンが盛り上がっているかを見たいとき、後者の方が近い。
    # 入れ替えるのは1件だけで、残りは賛同順のまま触らない。
    threads = [c for c in out if c["replies"] > 0 and c["reply_texts"]]
    if threads:
        top = max(threads, key=lambda x: (x["replies"], x["likes"]))
        top["is_thread"] = True
        out.remove(top)
        out.insert(0, top)
        print(f"[info] 返信の付いた一言を先頭に: 返信{top['replies']}件 "
              f"/ 高評価{top['likes']}件")

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
    # 訳すのは本文だけではない。返信まで訳して初めて、
    # 「この一言に、こう返ってきた」というやり取りとして出せる。
    # 別の呼び出しに分けると、同じ話題を2つの文脈で訳すことになる。
    flat = []  # (何件目の投稿か, 返信なら何件目か / 本文は -1, 原文)
    for n, it in enumerate(items):
        flat.append((n, -1, it["title"]))
        for j, rt in enumerate(it.get("reply_texts") or []):
            flat.append((n, j, rt))
    numbered = "\n".join(f"{n + 1}. {txt}"
                         for n, (_, _, txt) in enumerate(flat))
    # 訳と同時に、その一言が肯定寄りか否定寄りかも付けてもらう。
    # 別々に呼ぶと回数が倍になるうえ、訳文と判定が違う読み方で付く。
    prompt = (
        "以下は、アメリカの野球ファンが書いた短い書き込みです。"
        "日本語に訳し、書き手の調子を判定してください。\n\n"
        f"{numbered}\n\n"
        "条件:\n"
        "- 1行につき1件、「番号|調子|訳文」の形式だけを出力する\n"
        "- 調子は 称賛 / 批判 / 中立 のいずれか1つ\n"
        "  称賛=選手やプレーを褒めている、批判=不満や非難、"
        "中立=事実の指摘や質問\n"
        "- 意訳しすぎず、元の言い回しの雰囲気を残す\n"
        "- スラングや略語は、日本語として自然な範囲で分かるように訳す\n"
        "- 訳せない固有名詞(選手名・球団名)は英語のまま残してよい\n"
        "- 感想や補足は加えない。書かれていないことを足さない\n"
        "- 前置きや説明は不要"
    )
    resp = client.messages.create(
        # 4件の本文と、それぞれの返信3件まで。最大16行を訳す。
        # 元が220字まで許してあるので、日本語にすると1行200字近くなる
        # ことがあり、2500では足りない日が出る。上限を上げても
        # 出力した分しか課金されないので、増やして困らない。
        model=MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    cut = resp.stop_reason == "max_tokens"
    text = "".join(b.text for b in resp.content if b.type == "text")

    translated = {}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(\d+)\s*[|｜]\s*(\S+?)\s*[|｜]\s*(.+)", line)
        if m:
            translated[int(m.group(1))] = (m.group(2), m.group(3).strip())
            continue
        # 調子を付け忘れた行も拾う。訳文だけでも動画には使える。
        m = re.match(r"(\d+)[.、]\s*(.+)", line)
        if m:
            translated[int(m.group(1))] = ("中立", m.group(2).strip())

    def clean(pair):
        tone, ja = pair
        return {"ja": ja,
                "tone": tone if tone in ("称賛", "批判", "中立") else "中立"}

    # 途中で切れた日は、最後に拾えた1行だけを落とす。
    #
    # 以前は切れたら全部捨てていた。だが切れるのは最後の1行で、
    # そこまでに揃った訳は正しい。丸ごと捨てると、その日は
    # 「ファンのコメント欄」が1本出ない。1件減るのと0本になるのでは
    # 落とすものの大きさが違う。
    if cut and translated:
        last = max(translated)
        translated.pop(last, None)
        note(f"[warn] 訳が{len(flat)}行のうち{last - 1}行で切れました。"
             f"切れた行だけ落として続けます")

    out = [None] * len(items)
    for n, (i, j, _) in enumerate(flat, 1):
        got = translated.get(n)
        if not got:
            continue
        if j < 0:
            out[i] = {**items[i], **clean(got), "reply_ja": []}
        elif out[i] is not None:
            out[i]["reply_ja"].append({**clean(got),
                                       "original": items[i]["reply_texts"][j]})
    return [x for x in out if x]


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
        note("**現地の声: コメントもRSSも取れませんでした**")
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or anthropic is None:
        note("**現地の声: ANTHROPIC_API_KEY が渡っていません**")
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    try:
        voices = translate(client, items[:limit])
    except Exception as e:
        note(f"**現地の声: 翻訳に失敗しました** {type(e).__name__}: "
             f"{str(e)[:160]}")
        return {}

    if not voices:
        note("**現地の声: 1件も訳せませんでした**")
        return {}
    print(f"[info] 訳せた見出し: {len(voices)}件")
    for v in voices:
        print(f"   {v['ja']}")
        print(f"     原文: {v['title'][:70]}")

    # 日本人選手に触れた称賛だけを、別に持つ。
    #
    # 「voices」の側は一切絞らない。試合そのもののコメントは、
    # 賛否も不満も含めてそのまま見せる枠で、そこを称賛に寄せると
    # 現地の空気ではなくこちらの編集になる。
    #
    # 一方こちらは「日本人選手が現地でどう言われたか」という別の話で、
    # 貢献スコアの枠に添えるもの。用途が違うので置き場も分ける。
    for v in voices:
        v["jp_players"] = jp_mentioned(v.get("title", "") + " " + v.get("ja", ""))
    praise = [v for v in voices
              if v.get("jp_players") and v.get("tone") == "称賛"]
    if praise:
        print(f"[info] 日本人選手への称賛: {len(praise)}件")
        for v in praise:
            print(f"   {'、'.join(v['jp_players'])}: {v['ja'][:44]}")

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_name,
        "source_url": source_url,
        "voices": voices,
        "jp_praise": praise,
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
    age = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
    if age > max_age_hours:
        print("[info] 現地の声のデータが古いため使いません")
        return {}

    # 前日のコメントに今日の日付を付けて出さない。
    #
    # 8/24の17:30は、8/23と同じ試合・同じ返信件数のまま題だけ日付が
    # 変わっていた。取得に失敗した日に、前日のファイルがそのまま
    # 使われたため。30時間という幅は、前日の同じ時刻(27時間前)を
    # 通してしまう。時間ではなく、日で見る。
    jst = timezone(timedelta(hours=9))
    if updated.astimezone(jst).date() != datetime.now(jst).date():
        print(f"[info] 現地の声は{updated.astimezone(jst).date()}のものです。"
              "今日の分が取れていないので使いません")
        return {}
    return data


def _timing_lines(raw: list) -> list:
    """コメントが、ハイライト公開から何時間後に書かれたか。

    「何時に取りにいけばいちばん溜まっているか」は、こちらの想像では
    決まらない。試合直後に集中するのか、現地の夜に伸びるのかで、
    枠を何時に置くかの答えが変わる。
    """
    import datetime as _dt
    rows = []
    for c in raw:
        a, v = c.get("at"), c.get("video_published_at")
        if not (a and v):
            continue
        try:
            ta = _dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
            tv = _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            continue
        rows.append((ta - tv).total_seconds() / 3600)
    if not rows:
        return ["- コメントの投稿時刻が取れませんでした", ""]

    rows.sort()
    buckets = [(0, 1), (1, 3), (3, 6), (6, 12), (12, 24), (24, 999)]
    out = ["### いつ書かれたか(ハイライト公開からの経過)", "",
           "|経過|件数|割合|", "|---|--:|--:|"]
    for lo, hi in buckets:
        n = sum(1 for x in rows if lo <= x < hi)
        label = f"{lo}〜{hi}時間" if hi < 999 else f"{lo}時間以降"
        out.append(f"|{label}|{n}|{n / len(rows) * 100:.0f}%|")
    half = rows[len(rows) // 2]
    out += ["", f"- 中央値: 公開から **{half:.1f}時間後**",
            f"- 最も遅いもの: {rows[-1]:.1f}時間後", ""]
    return out


def report(raw: list, voices: list) -> str:
    """
    集めたコメントの素の姿を書き出す。

    動画に載るのは訳した数件だけなので、そもそもどれくらいの反応が
    付いているのか、賛否はどちらに寄っているのかが分からない。
    採用したものだけでなく、拾った全体の分布を出す。
    """
    if not raw:
        return "コメントは取れませんでした。"
    likes = sorted((c.get("likes", 0) for c in raw), reverse=True)
    replies = sum(c.get("replies", 0) for c in raw)
    tones = {}
    for v in voices:
        tones[v.get("tone", "中立")] = tones.get(v.get("tone", "中立"), 0) + 1

    lines = ["## 公式ハイライトのコメント", ""]
    lines += _timing_lines(raw)
    lines += [
        f"- 拾った件数: **{len(likes)}件**",
        f"- いいね 最大: **{likes[0]:,}** / 中央値: **{likes[len(likes) // 2]:,}**"
        f" / 平均: **{sum(likes) / len(likes):.0f}**",
        f"- いいね0件: {sum(1 for x in likes if x == 0)}件",
        f"- 返信の合計: {replies}件", "",
        "### 訳したもの", "",
        "| 調子 | いいね | 返信 | 訳 | 原文 |", "|---|---:|---:|---|---|",
    ]
    for v in voices:
        lines.append(
            f"| {v.get('tone', '?')} | {v.get('likes', 0):,} |"
            f" {v.get('replies', 0)} | {v.get('ja', '')[:44]} |"
            f" {v.get('title', '')[:44]} |")
    if tones:
        lines += ["", "調子の内訳: "
                  + " / ".join(f"{k} {n}件" for k, n in tones.items())]

    lines += ["", "### いいねの多い順(上位10件・原文)", ""]
    for c in raw[:10]:
        lines.append(f"- **{c.get('likes', 0):,}** いいね"
                     f"（返信{c.get('replies', 0)}）… {c.get('title', '')[:96]}")
        for rt in c.get("reply_texts", [])[:1]:
            lines.append(f"    - 返信: {rt[:80]}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/local_voices.json")
    parser.add_argument("--limit", type=int, default=MAX_VOICES)
    parser.add_argument("--report", action="store_true",
                        help="集めたコメントの分布を実行ページへ書き出す")
    args = parser.parse_args()

    if args.report:
        raw = fetch_youtube_comments()
        voices = []
        key = os.environ.get("ANTHROPIC_API_KEY")
        if raw and key and anthropic is not None:
            try:
                voices = translate(anthropic.Anthropic(api_key=key),
                                   raw[:args.limit])
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 翻訳に失敗: {e}", file=sys.stderr)
        text = report(raw, voices)
        print(text)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        return

    data = build(limit=args.limit)
    if not data:
        note("現地の声は更新しません(前日のファイルが残ります)。"
             "18:00の「ファンのコメント欄」は、鮮度が足りなければ出ません")
        return

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[info] 現地の声を出力しました -> {out}")


if __name__ == "__main__":
    main()
