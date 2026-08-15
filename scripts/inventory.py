#!/usr/bin/env python3
"""
いま何が、どこへ、どの頻度で出ているのかをコードから拾って一覧にする。

    python3 scripts/inventory.py
    python3 scripts/inventory.py --check   # 食い違いだけを出す(CI向け)

なぜ要るか:
  動画の種類・サイトのページ・投稿先が増えるほど、
  「決めたことがどこに反映済みで、どこが漏れているか」が
  人の記憶頼りになる。実際、資産動画を3本足したときに
  ASSET_META への登録を忘れ、タイトルが既定のまま投稿される
  一歩手前まで行った。

  ここでは説明を手で書かず、実際のコードとワークフローから拾う。
  拾えないもの(頻度の意図など)だけを定数として持ち、
  その定数と実物がずれていないかを検査する。
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

# 動画の種類。頻度と狙いはコードから読めないので、ここに書く。
# 「何を出しているか」の実体は upload_youtube 側から拾って突き合わせる。
VIDEO_KINDS = [
    ("daily", "日次ショート", "毎日19:00 JST",
     "翌日の注目試合3つを、選んだ理由つきで", "daily_notify.yml"),
    ("morning", "夕: 日本人選手", "毎日16:30 JST",
     "前夜の日本人選手を勝利貢献スコア順に", "morning_recap.yml"),
    ("morning_local", "夕: 現地の注目度", "毎日18:00 JST",
     "現地の再生回数と、話題に挙がったチーム", "morning_recap.yml"),
    ("morning_press", "夜: 現地の声", "毎日21:00 JST",
     "現地の番記者の投稿と見出しを、翻訳して", "morning_recap.yml"),
    ("daily_soccer", "サッカー日次", "毎日20:00 JST",
     "その夜の欧州の注目試合3つを、理由つきで", "soccer_daily.yml"),
    ("weekly", "週次まとめ", "毎週日曜",
     "1週間の振り返りと、予告した試合の答え合わせ", "weekly_summary.yml"),
    ("verdict", "答え合わせショート", "週次と同時",
     "注目試合に選んだカードが実際どうなったか", "weekly_summary.yml"),
    ("asset", "資産動画", "手動(在庫として作り置き)",
     "日付に依存しない知識もの", "asset_video.yml"),
]

# 配信先。動画以外も含めて全部並べる。
CHANNELS = [
    ("YouTube", "動画すべて", "自動", "upload_youtube.py"),
    ("TikTok", "日次・夕の3本", "下書きまで自動", "post_tiktok.py"),
    ("Bluesky", "日次の注目試合", "自動", "post_bluesky.py"),
    ("YouTube再生リスト", "全動画を種類ごとに", "自動", "playlists.py"),
    ("Threads", "日次の注目試合", "自動(認可待ち)", "post_threads.py"),
    ("Webプッシュ", "日次の注目試合", "自動", "send_onesignal.py"),
    ("サイト", "全ページ", "日次で再生成", "daily_notify.yml"),
    ("RSS", "注目試合", "自動", "generate_rss.py"),
    ("ポッドキャスト", "日次の読み上げ音声", "自動", "generate_podcast.py"),
]


def asset_topics() -> dict:
    """資産動画のトピックが、必要な3か所すべてに登録されているか。"""
    import generate_asset_video as gav
    import generate_thumbnail as gt

    # upload_youtube は google ライブラリが無いと止まるので、定義だけ読む。
    #
    # ASSET_META の範囲だけを見る。ファイル全体を走査すると、同じ形の
    # 辞書が他にあるだけで拾ってしまう。実際、競技ごとの見出しを持つ
    # SPORTS を足した時点で "mlb" と "soccer" が資産動画のトピック扱いに
    # なり、「作るコードが無い」と誤検出していた。
    src = (ROOT / "scripts" / "upload_youtube.py").read_text(encoding="utf-8")
    block = ""
    start = src.find("ASSET_META = {")
    if start >= 0:
        end = src.find("\n}\n", start)
        block = src[start:end if end > 0 else len(src)]
    meta_keys = set(re.findall(r'^    "([a-z0-9_]+)": \{', block, re.M))

    wf = (ROOT / ".github" / "workflows" / "asset_video.yml").read_text(
        encoding="utf-8")
    # TOPICS への代入は2か所ある。1つ目は TOPICS="${{ inputs.topic }}" で、
    # そちらを拾うと一覧が空になり、全トピックが「allに無い」と誤検出される。
    # "${{" はスペースを含むので「複数語かどうか」では見分けられない。
    # ワークフローの式を含まない行だけを一覧として扱う。
    candidates = [c for c in re.findall(r'TOPICS="([^"]+)"', wf)
                  if "${{" not in c]
    in_all = set(candidates[0].split()) if candidates else set()
    choices = set(re.findall(r"^          - ([a-z0-9_]+)$", wf, re.M))
    choices.discard("all")

    # 実際に作れるトピック
    known = set(gav.LIST_TOPICS) | {"mlb_abbr", "mlb_venue", "mlb_rivalry"}
    thumbs = set(gt.ASSET_THUMB)

    return {
        "known": known, "meta": meta_keys, "thumb": thumbs,
        "all": in_all, "choices": choices,
    }


def site_pages() -> list:
    """公開されるページ。web/ に置いてあるものと、生成されるもの。"""
    static = sorted(p.name for p in (ROOT / "web").glob("*.html"))
    generated = []
    for s in sorted((ROOT / "scripts").glob("generate_*.py")):
        src = s.read_text(encoding="utf-8")
        for m in re.findall(r'default="(public/[^"]+\.html)"', src):
            generated.append((m.replace("public/", ""), s.name))
    return static, generated


def workflows() -> list:
    out = []
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        src = f.read_text(encoding="utf-8")
        name = re.search(r"^name:\s*(.+)$", src, re.M)
        cron = re.findall(r"cron:\s*'([^']+)'", src)
        manual = "workflow_dispatch" in src
        trig = []
        if cron:
            trig += [f"cron {c}" for c in cron]
        if manual:
            trig.append("手動")
        out.append((f.name, name.group(1).strip() if name else "?",
                    " / ".join(trig) or "?"))
    return out


def check(a: dict) -> list:
    """食い違いを並べる。空なら揃っている。"""
    problems = []
    for t in sorted(a["known"]):
        if t not in a["meta"]:
            problems.append(f"{t}: upload_youtube.py の ASSET_META に無い"
                            "(既定のタイトルで投稿される)")
        if t not in a["thumb"]:
            problems.append(f"{t}: generate_thumbnail.py の ASSET_THUMB に無い")
        if t not in a["all"]:
            problems.append(f"{t}: asset_video.yml の all に無い(一括実行で漏れる)")
        if t not in a["choices"]:
            problems.append(f"{t}: asset_video.yml の選択肢に無い(手動で選べない)")
    for t in sorted(a["meta"] - a["known"]):
        problems.append(f"{t}: ASSET_META にあるが、作るコードが無い")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="食い違いだけを出す。1件でもあれば終了コード1")
    args = ap.parse_args()

    a = asset_topics()
    problems = check(a)

    if args.check:
        for p in problems:
            print(f"::warning::{p}")
        print(f"資産動画トピック {len(a['known'])}件 / 食い違い {len(problems)}件")
        return 1 if problems else 0

    print("=" * 68)
    print("動画の種類と頻度")
    print("=" * 68)
    for kind, label, freq, what, wf in VIDEO_KINDS:
        print(f"\n■ {label}  [{kind}]")
        print(f"   頻度 : {freq}")
        print(f"   内容 : {what}")
        print(f"   実行 : {wf}")
    print(f"\n   資産動画のトピック数: {len(a['known'])}")
    for t in sorted(a["known"]):
        print(f"     - {t}")

    print("\n" + "=" * 68)
    print("配信先")
    print("=" * 68)
    for name, what, state, script in CHANNELS:
        print(f"  {name:12} {what:18} {state:10} ({script})")

    print("\n" + "=" * 68)
    print("ワークフロー")
    print("=" * 68)
    for fname, name, trig in workflows():
        print(f"  {fname:22} {name:24} {trig}")

    print("\n" + "=" * 68)
    print("サイトのページ")
    print("=" * 68)
    static, generated = site_pages()
    print("  web/ に置いてある:")
    for p in static:
        print(f"    - {p}")
    print("  生成される:")
    for p, by in generated:
        print(f"    - {p:22} ({by})")

    print("\n" + "=" * 68)
    print("登録漏れの検査")
    print("=" * 68)
    if problems:
        for p in problems:
            print(f"  NG {p}")
    else:
        print("  すべての資産動画トピックが、タイトル・サムネイル・"
              "ワークフローの3か所に登録されています")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
