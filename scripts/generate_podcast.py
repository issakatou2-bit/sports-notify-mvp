"""
毎日のナレーション音声を、ポッドキャストとして配信できる形に変換する。

なぜこれができるのか:
  動画用に生成しているナレーション音声を、動画に埋め込んで終わりにせず
  mp3として書き出すだけで、そのままポッドキャストの1エピソードになる。
  追加のAI呼び出しも音声合成も不要で、実質コストはゼロ。

配信の仕組み:
  Spotify / Apple Podcast などは「RSSフィードのURL」を登録すると、
  そこに並んだ音声を自動で取り込んでくれる。
  つまり feed.xml と mp3 を公開しておけば、各サービスへの個別投稿は要らない。

保存期間:
  mp3はリポジトリにコミットして残す(1本あたり約1MB)。
  際限なく増やすとリポジトリが肥大化するため、
  KEEP_DAYS を超えた古いエピソードは自動で削除する。

出力:
  podcast/YYYY-MM-DD.mp3   … エピソード本体(リポジトリにコミット)
  public/podcast/          … 公開用にコピーされたもの
  public/podcast/feed.xml  … 各サービスに登録するRSS

使い方:
  python3 scripts/generate_podcast.py \
      --audio-dir build/audio --store podcast --public public/podcast
"""

import argparse
import html
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

SITE_URL = "https://collespo.com/"
PODCAST_BASE = SITE_URL + "podcast/"

TITLE = "コレスポ｜今日の注目試合"
DESCRIPTION = (
    "MLBと欧州サッカーの「今日の注目試合」を、なぜ注目なのかの理由つきで"
    "毎日お届けします。野球・サッカーに触れ始めた方が、生中継をもっと"
    "楽しめるようになるためのお供です。"
)
AUTHOR = "コレスポ"
EMAIL = "issakatou2@gmail.com"
# Appleは1400x1400〜3000x3000pxのカバー画像を要求する。
# PWA用のアイコン(512px)では小さすぎて登録が弾かれるため、専用画像を用意している。
IMAGE_URL = SITE_URL + "icons/podcast-cover.png"

# 古いエピソードを残す日数。1本約1MBなので、90日で約90MB。
KEEP_DAYS = 90

JST = timezone(timedelta(hours=9))


def concat_to_mp3(audio_dir: pathlib.Path, out_path: pathlib.Path) -> bool:
    """セグメントごとのwavを1本のmp3にまとめる"""
    files = sorted(audio_dir.glob("seg_*.wav"))
    if not files:
        print("[info] 音声ファイルが無いため、ポッドキャストは作りません")
        return False

    list_path = audio_dir / "podcast_list.txt"
    list_path.write_text(
        "\n".join(f"file '{f.resolve()}'" for f in files), encoding="utf-8"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c:a", "libmp3lame", "-b:a", "128k", str(out_path)],
            check=True, capture_output=True,
        )
        return True
    except Exception as e:
        print(f"[warn] mp3への変換に失敗しました: {e}", file=sys.stderr)
        return False


def audio_meta(path: pathlib.Path):
    """再生時間(秒)とファイルサイズを返す"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip()), path.stat().st_size
    except Exception:
        return 0.0, path.stat().st_size if path.exists() else 0


def episode_description(games_path: str) -> str:
    """その日の注目試合を、エピソードの説明文にする"""
    try:
        data = json.loads(pathlib.Path(games_path).read_text(encoding="utf-8"))
        games = [g for g in data.get("games", []) if g.get("is_notable")][:3]
    except (json.JSONDecodeError, OSError):
        return DESCRIPTION

    if not games:
        return DESCRIPTION

    lines = []
    for g in games:
        lines.append(
            f"{g.get('start_time_jst')} "
            f"{g.get('home_team_name')} vs {g.get('away_team_name')}"
        )
        for r in (g.get("reasons") or [])[:2]:
            if r.get("visible", True) and r.get("text"):
                lines.append(f"　・{r['text']}")
    lines.append("")
    lines.append("詳しくは https://collespo.com/")
    lines.append("音声: VOICEVOX:ずんだもん / データ: MLB Stats API")
    return "\n".join(lines)


def prune_old(store: pathlib.Path) -> int:
    """保存期間を過ぎたエピソードを削除する"""
    limit = datetime.now(JST).date() - timedelta(days=KEEP_DAYS)
    removed = 0
    for f in store.glob("????-??-??.mp3"):
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < limit:
            f.unlink()
            removed += 1
    return removed


def build_feed(episodes: list) -> str:
    """
    ポッドキャスト用のRSSを組み立てる。
    itunes名前空間の項目は、Apple Podcast等が取り込む際に参照する。
    """
    items = []
    for ep in episodes:
        pub = ep["date"].strftime("%a, %d %b %Y 19:00:00 +0900")
        mins, secs = divmod(int(ep["duration"]), 60)
        items.append(f"""    <item>
      <title>{html.escape(ep['title'])}</title>
      <description><![CDATA[{ep['description']}]]></description>
      <pubDate>{pub}</pubDate>
      <guid isPermaLink="true">{PODCAST_BASE}{ep['file']}</guid>
      <enclosure url="{PODCAST_BASE}{ep['file']}" length="{ep['size']}" type="audio/mpeg"/>
      <itunes:duration>{mins:02d}:{secs:02d}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>""")

    last_build = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{html.escape(TITLE)}</title>
    <link>{SITE_URL}</link>
    <description>{html.escape(DESCRIPTION)}</description>
    <language>ja</language>
    <lastBuildDate>{last_build}</lastBuildDate>
    <itunes:author>{html.escape(AUTHOR)}</itunes:author>
    <itunes:summary>{html.escape(DESCRIPTION)}</itunes:summary>
    <itunes:owner>
      <itunes:name>{html.escape(AUTHOR)}</itunes:name>
      <itunes:email>{EMAIL}</itunes:email>
    </itunes:owner>
    <itunes:image href="{IMAGE_URL}"/>
    <itunes:category text="Sports">
      <itunes:category text="Baseball"/>
    </itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
{chr(10).join(items)}
  </channel>
</rss>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default="build/audio")
    parser.add_argument("--store", default="podcast")
    parser.add_argument("--public", default="public/podcast")
    parser.add_argument("--games", default="notable_games.json")
    args = parser.parse_args()

    audio_dir = pathlib.Path(args.audio_dir)
    store = pathlib.Path(args.store)
    store.mkdir(parents=True, exist_ok=True)

    today = datetime.now(JST).date()
    mp3_path = store / f"{today.isoformat()}.mp3"

    if audio_dir.exists():
        if concat_to_mp3(audio_dir, mp3_path):
            dur, size = audio_meta(mp3_path)
            print(f"[info] エピソードを作成: {mp3_path.name} "
                  f"({dur:.0f}秒 / {size / 1024:.0f}KB)")
    else:
        print(f"[info] {audio_dir} が無いため、今回はエピソードを作りません")

    removed = prune_old(store)
    if removed:
        print(f"[info] 保存期間({KEEP_DAYS}日)を過ぎたエピソードを{removed}件削除しました")

    # --- フィードを組み立てる(新しい順) ---
    desc = episode_description(args.games)
    episodes = []
    for f in sorted(store.glob("????-??-??.mp3"), reverse=True):
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        dur, size = audio_meta(f)
        # ファイル名は作った日(JST)だが、中身はその翌日の試合。
        # 19時に配信して、扱うのは翌朝から始まる試合なので1日ずれる。
        # ファイル名のまま題名にしていたため、8月11日の回が
        # 「8月11日の注目試合」と出ていた。実際は8月12日の試合。
        # YouTube側は既に翌日の日付を使っており、そちらと食い違っていた。
        g = d + timedelta(days=1)
        episodes.append({
            "date": d,
            "file": f.name,
            "title": f"{g.month}月{g.day}日の注目試合",
            # 説明文は当日分のみ実データ、過去分は汎用文にしておく
            # (過去のnotable_games.jsonを読み直すのはコストに見合わないため)
            "description": desc if f.name == mp3_path.name else DESCRIPTION,
            "duration": dur,
            "size": size,
        })

    if not episodes:
        print("[info] エピソードが1件も無いため、フィードは作りません")
        return

    public = pathlib.Path(args.public)
    public.mkdir(parents=True, exist_ok=True)
    for f in store.glob("*.mp3"):
        shutil.copy2(f, public / f.name)
    (public / "feed.xml").write_text(build_feed(episodes), encoding="utf-8")

    total_mb = sum(e["size"] for e in episodes) / 1024 / 1024
    print(f"[info] ポッドキャストを出力しました"
          f"({len(episodes)}エピソード / 合計{total_mb:.1f}MB)")
    print(f"[info] フィードURL: {PODCAST_BASE}feed.xml")


if __name__ == "__main__":
    main()
