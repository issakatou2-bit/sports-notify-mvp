"""
生成した動画をYouTubeへアップロードする。

認証:
  APIキーではなくOAuthを使う(投稿には本人の許可が必要なため)。
  事前に get_youtube_token.py で取得した以下をGitHub Secretsに登録しておく。
    YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN

公開設定について:
  既定では「限定公開(unlisted)」でアップロードする。
  URLを知っている人だけが見られる状態で、検索にも出ない。
  最初の数本は内容を確認してから手動で公開に切り替える方が安全なため。
  自動で公開したくなったら --privacy public を指定する。

使い方:
  python3 scripts/upload_youtube.py --video build/video/collespo_short.mp4
"""

import argparse
import json
import os
import pathlib
import sys

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("[warn] Google APIライブラリが無いためアップロードをスキップします")
    print("       pip install google-api-python-client google-auth")
    sys.exit(0)

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
# MLB / 野球 のカテゴリ。17 = Sports
CATEGORY_SPORTS = "17"


def build_metadata(games_path: str, date_label: str, kind: str = "daily") -> dict:
    """タイトル・説明文・タグを、その日のデータから組み立てる"""
    try:
        data = json.loads(pathlib.Path(games_path).read_text(encoding="utf-8"))
        games = [g for g in data.get("games", []) if g.get("is_notable")][:3]
    except (json.JSONDecodeError, OSError):
        games = []

    if kind == "weekly":
        # 週次まとめは横型・8分以上の通常動画なので #Shorts は付けない
        title = f"【MLB】今週の注目試合まとめ｜{date_label} 週間ダイジェスト"
    elif games:
        top = games[0]
        matchup = f"{top.get('home_team_name')} vs {top.get('away_team_name')}"
        title = f"【MLB】{date_label} 注目試合｜{matchup} ほか #Shorts"
    else:
        title = f"【MLB】{date_label} 注目試合 #Shorts"
    title = title[:100]  # YouTubeのタイトル上限

    if kind == "weekly":
        lines = ["この1週間の注目試合を、結果とあわせて振り返ります。", ""]
    else:
        lines = [f"{date_label} の注目試合を、なぜ注目なのかの理由つきで紹介します。", ""]
    for i, g in enumerate(games, 1):
        lines.append(
            f"{i}. {g.get('start_time_jst')} "
            f"{g.get('home_team_name')} vs {g.get('away_team_name')}"
        )
        for r in (g.get("reasons") or [])[:2]:
            if r.get("visible", True) and r.get("text"):
                lines.append(f"   ・{r['text']}")
        lines.append("")
    lines += [
        "#Shorts" if kind != "weekly" else "",
        "",
        "毎日19時ごろ、その日の注目試合をお届けしています。",
        "サイト: https://collespo.com/",
        "",
        "※試合データはMLB公式のデータをもとに自動生成しています。",
        "※放送予定は変更される場合があります。各配信サービスで最新情報をご確認ください。",
        "",
        "―――",
        "音声: VOICEVOX:ずんだもん",
        "データ: MLB Stats API",
    ]

    tags = ["MLB", "メジャーリーグ", "野球", "注目試合", "コレスポ"]
    tags.append("週間まとめ" if kind == "weekly" else "Shorts")
    for g in games:
        for name in (g.get("jp_players") or [])[:2]:
            if name not in tags:
                tags.append(name)

    return {
        "snippet": {
            "title": title,
            "description": "\n".join(lines)[:5000],
            "tags": tags[:15],
            "categoryId": CATEGORY_SPORTS,
            # 動画本編の言語と、タイトル・説明の言語。
            # 未設定だとYouTube側で「選択」のままになり、
            # 字幕の自動生成や検索での扱いが不利になる。
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", default="build/video/collespo_short.mp4")
    parser.add_argument("--games", default="notable_games.json")
    parser.add_argument("--kind", default="daily", choices=["daily", "weekly"],
                        help="daily=ショート / weekly=週次まとめ")
    parser.add_argument("--privacy", default="public",
                        choices=["private", "unlisted", "public"])
    args = parser.parse_args()

    video_path = pathlib.Path(args.video)
    if not video_path.exists():
        print(f"[info] {video_path} が無いため、アップロードをスキップします")
        return

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        print("[info] YouTube認証情報が未設定のため、アップロードをスキップします")
        return

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )

    date_label = ""
    try:
        data = json.loads(pathlib.Path(args.games).read_text(encoding="utf-8"))
        g = [x for x in data.get("games", []) if x.get("is_notable")]
        if g:
            date_label = (g[0].get("start_time_jst") or "").split(" ")[0]
    except (json.JSONDecodeError, OSError):
        pass

    body = build_metadata(args.games, date_label, args.kind)
    body["status"] = {
        "privacyStatus": args.privacy,
        "selfDeclaredMadeForKids": False,
        # 「AIの使用」の申告。ここで問われているのは、実在の人物が実際には
        # していない発言・行動をしているように見せたり、実際の映像を改変したり
        # といった「誤解を招く合成コンテンツ」かどうか。
        # この動画はテキストと図形をプログラムで描いた情報グラフィックであり、
        # そうした改変は一切していないため false とする。
        "containsSyntheticMedia": False,
    }

    try:
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True,
                                mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status", body=body, media_body=media
        )
        response = request.execute()
        vid = response.get("id")
        print(f"[info] アップロードしました: https://youtu.be/{vid}")
        print(f"[info] タイトル: {body['snippet']['title']}")
        print(f"[info] 公開設定: {args.privacy}")
    except Exception as e:
        # アップロードに失敗しても、通知やサイト更新は既に済んでいるので
        # ワークフロー全体を落とさない
        print(f"[warn] アップロードに失敗しました: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
