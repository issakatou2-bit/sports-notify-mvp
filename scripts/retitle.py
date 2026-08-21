#!/usr/bin/env python3
"""
公開済みの動画の題を、いまの作り方で付け直す。

なぜ要るのか:
  題の作り方は何度も変えている。「現地で最も注目された試合ランキング」を
  7日続けたのも、報道の見出しを地の文で置いて自分が報じたように読めたのも、
  直したのは作り方のほうで、すでに出た動画は古い題のまま残る。

  1本ずつ手で打ち直すと、打ち間違えるし、そのうちやらなくなる。
  同じ作り方から作り直せば、いま出す動画と揃う。

  題を書き換えても再生数や維持率は消えない。ただし、伸びている動画の
  題を触るのは避ける——並びが変わって、拾われ方が変わることがある。
  既定では再生数の少ないものだけを対象にする。

安全のため:
  既定は下読みだけ。--write を付けたときだけ実際に変える。

使い方:
  python3 scripts/retitle.py --date 2026-08-21            # 下読み
  python3 scripts/retitle.py --date 2026-08-21 --write
  python3 scripts/retitle.py --video jfm6WCejPjg --write
"""

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("[warn] Google APIライブラリが無いためスキップします")
    sys.exit(0)

import upload_youtube as uy  # noqa: E402

TOKEN_URI = "https://oauth2.googleapis.com/token"
RECORD = "data/published_videos.json"
ANALYTICS = "data/analytics.json"

# これより見られている動画は触らない。
#
# 題を変えると並びの中での拾われ方が変わることがある。伸びている
# ものを触って落ちても、元には戻せない。落ちても失うものが無い
# ところだけを直す。
SAFE_VIEWS = 300

# 記録の種類から、題を組み立てるときの引数へ
KIND_ARGS = {
    "daily": ("daily", ""),
    "daily_soccer": ("daily_soccer", ""),
    "morning": ("morning", "players"),
    "morning_player": ("morning", "player"),
    "morning_voices": ("morning", "voices"),
    "morning_local": ("morning", "local"),
    "morning_press": ("morning", "press"),
}


def client():
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secret and token):
        print("[info] YouTube認証情報が未設定のためスキップします")
        return None
    creds = Credentials(None, refresh_token=token, token_uri=TOKEN_URI,
                        client_id=cid, client_secret=secret)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def date_label(key: str) -> str:
    """記録の日付キーを、題に入れる形へ。"2026-08-21" -> "8月21日"

    jst_label() は通さない。あれは米国日付を日本の日付へ直すもので、
    記録のキーはすでに日本の日付になっている。通すと1日進んで、
    今日出した動画に「8月22日」と書き込むことになる。
    """
    try:
        y, m, d = key.split("-")
        return "%d月%d日" % (int(m), int(d))
    except (ValueError, AttributeError):
        return key


def view_counts() -> dict:
    """動画IDごとの再生数。取れなければ空。"""
    try:
        store = json.loads(pathlib.Path(ANALYTICS).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    days = store.get("days") or {}
    if not days:
        return {}
    latest = days[sorted(days)[-1]]
    return {v["video"]: v.get("views", 0) for v in (latest.get("videos") or [])
            if v.get("video")}


def wanted_title(kind: str, date_label: str):
    """いまの作り方で組み立て直した題。組み立てられなければ空。

    材料はいま手元にあるものを使う。過去日を作り直すと、その日の
    材料ではなく今日の材料で題が付く——だから既定は当日だけにする。
    """
    args = KIND_ARGS.get(kind)
    if not args:
        return ""
    k, mode = args
    # 選手名は別で渡さないと題から落ちる。渡さずに作り直すと
    # 「今井達也・岡本和真・村上宗隆 ほか｜…」が「8月21日 日本人選手…」に
    # なる——付け直したせいで題が弱くなる。
    players = []
    try:
        players = json.loads(pathlib.Path("data/morning_recap.json")
                             .read_text(encoding="utf-8")).get("players") or []
    except (OSError, json.JSONDecodeError):
        pass
    try:
        meta = uy.build_metadata("notable_games.json", date_label,
                                 kind=k, morning_mode=mode,
                                 morning_players=players)
    except Exception as e:
        print("[warn] %s の題を組み立てられません: %s" % (kind, str(e)[:120]))
        return ""
    return (meta.get("snippet") or {}).get("title") or ""


def apply(yt, video_id: str, title: str, dry: bool) -> bool:
    """題だけ差し替える。説明もタグも触らない。"""
    try:
        res = yt.videos().list(part="snippet", id=video_id).execute()
    except HttpError as e:
        print("[warn] %s を読めません: %s" % (video_id, str(e)[:120]))
        return False
    items = res.get("items") or []
    if not items:
        print("[warn] %s が見つかりません" % video_id)
        return False
    sn = items[0]["snippet"]
    if sn.get("title") == title:
        print("  変更なし %s" % video_id)
        return False

    print("  %s" % video_id)
    print("    いま  %s" % sn.get("title", "")[:72])
    print("    こう  %s" % title[:72])
    if dry:
        return False

    body = {"id": video_id,
            "snippet": {**sn, "title": title}}
    try:
        yt.videos().update(part="snippet", body=body).execute()
    except HttpError as e:
        print("[warn] %s を更新できません: %s" % (video_id, str(e)[:160]))
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="この日に出した分を対象にする (YYYY-MM-DD)")
    ap.add_argument("--video", help="この動画IDだけを対象にする")
    ap.add_argument("--kind", help="種類を1つに絞る (morning_press など)")
    ap.add_argument("--title", help="--video のときに、この題をそのまま付ける")
    ap.add_argument("--write", action="store_true",
                    help="実際に変える(既定は下読みだけ)")
    ap.add_argument("--force", action="store_true",
                    help="よく見られている動画も対象にする")
    args = ap.parse_args()

    yt = client()
    if yt is None:
        return 0

    if args.video and args.title:
        apply(yt, args.video, args.title, not args.write)
        return 0

    try:
        rec = json.loads(pathlib.Path(RECORD).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("[warn] %s が読めません" % RECORD)
        return 1

    # 対象を集める
    targets = []
    for kind, days in rec.items():
        if not isinstance(days, dict):
            continue
        if args.kind and kind != args.kind:
            continue
        for date, v in days.items():
            if not isinstance(v, dict) or not v.get("video_id"):
                continue
            if args.video and v["video_id"] != args.video:
                continue
            if args.date and date != args.date:
                continue
            targets.append((date, kind, v["video_id"]))

    if not targets:
        print("対象がありません")
        return 0

    views = view_counts()
    changed = skipped = 0
    # 変えたら記録も直す。YouTube側だけ変えると、published_videos.json が
    # 古い題を持ったまま残り、あとから読む側は実物と違うものを見る。
    # 「1つの問いに答えが2つある」形をここで作らない。
    touched = []
    for date, kind, vid in sorted(targets):
        got = views.get(vid)
        if got is not None and got > SAFE_VIEWS and not args.force:
            print("%s / %s は %d回見られているので触りません" % (date, kind, got))
            skipped += 1
            continue
        title = args.title or wanted_title(kind, date_label(date))
        if not title:
            continue
        print("%s / %s" % (date, kind))
        if apply(yt, vid, title, not args.write):
            changed += 1
            touched.append((kind, date, title))

    if touched and args.write:
        for kind, date, title in touched:
            rec.setdefault(kind, {}).setdefault(date, {})["title"] = title
        pathlib.Path(RECORD).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("記録も%d件そろえました" % len(touched))

    print()
    print("%d本を%s" % (changed, "変えました" if args.write else "変えます"))
    if skipped:
        print("%d本は見られているので触っていません(--force で対象にできます)"
              % skipped)
    if not args.write:
        print("(下読みだけです。実際に変えるには --write)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n## 題の付け直し\n\n")
            f.write("- %d本を%s\n" % (changed,
                                      "変えました" if args.write else "変えます"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
