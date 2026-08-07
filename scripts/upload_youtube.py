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


# 資産動画のトピックごとのメタ情報。
# 日次・週次と違って中身が日付に依存しないため、検索から長く拾われることを
# 狙って、タイトルと説明文を固定で持つ。
ASSET_META = {
    "mlb_abbr": {
        "title": "【MLB】30球団の略称、地区ごとに覚える｜LAD・NYY・CWSってどこ？ #Shorts",
        "lead": [
            "野球中継のスコアボードや速報では、球団名がアルファベットの略称で"
            "表示されます。この動画では、MLB30球団の略称を地区ごとに整理して"
            "紹介します。",
            "",
            "ア・リーグ東地区 / 中地区 / 西地区",
            "ナ・リーグ東地区 / 中地区 / 西地区",
            "",
            "略称が読めるようになると、中継の情報がそのまま頭に入ってきます。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球初心者", "球団略称",
                 "MLB入門", "コレスポ"],
    },
    "mlb_venue": {
        "title": "【MLB】球場でこんなに変わる｜点が入る球場・入らない球場 #Shorts",
        "lead": [
            "同じ野球でも、球場によって試合の性格はまったく変わります。"
            "標高、風向き、フェンスの形。MLBを代表する球場の特徴を紹介します。",
            "",
            "クアーズ・フィールド / フェンウェイ・パーク / リグレー・フィールド",
            "オラクル・パーク / ヤンキー・スタジアム ほか",
            "",
            "球場の癖が分かると、点の入り方の理由が見えてきます。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球初心者", "球場",
                 "MLB入門", "コレスポ"],
    },
    "mlb_rivalry": {
        "title": "【MLB】伝統の一戦、なぜ因縁？｜ヤンキースvsレッドソックスほか #Shorts",
        "lead": [
            "MLBには、勝ち負け以上の意味を持つカードがあります。"
            "なぜ因縁の対決と呼ばれるのか、その由来を紹介します。",
            "",
            "ヤンキース vs レッドソックス / ドジャース vs ジャイアンツ",
            "カブス vs カージナルス / サブウェイ・シリーズ ほか",
            "",
            "背景が分かると、ただの1試合が特別な1試合に見えてきます。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球初心者", "ライバル",
                 "MLB入門", "コレスポ"],
    },
    "mlb_stats": {
        "title": "【野球】この数字だけ分かればいい｜OPS・防御率・WHIPの見方 #Shorts",
        "lead": [
            "中継やネットで見かける成績の数字。よく出てくるものだけ、"
            "意味と「どこからが凄いのか」の目安をまとめました。",
            "",
            "OPS / 打率 / 防御率(ERA) / WHIP / 打点(RBI) / 奪三振",
            "",
            "数字が読めると、試合の見え方が変わります。",
        ],
        "tags": ["MLB", "野球", "野球初心者", "OPS", "防御率", "野球用語",
                 "MLB入門", "コレスポ"],
    },
    "mlb_terms": {
        "title": "【MLB】順位表、こう読む｜ゲーム差・ワイルドカードとは #Shorts",
        "lead": [
            "順位表に並ぶ言葉が分かると、その日の試合がどれくらい重いのかが"
            "見えてきます。",
            "",
            "ゲーム差 / 地区首位 / ワイルドカード / 直近10試合 /"
            " インターリーグ / 同地区対決",
            "",
            "コレスポでは毎日、この観点から注目試合を選んでいます。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球初心者", "順位表",
                 "ワイルドカード", "MLB入門", "コレスポ"],
    },
    "mlb_league": {
        "title": "【MLB】30球団どう分かれてる？｜2リーグ6地区の仕組み #Shorts",
        "lead": [
            "MLBは30球団。2つのリーグと6つの地区に分かれています。"
            "この構造が分かると、順位表が一気に読めるようになります。",
            "",
            "ア・リーグ / ナ・リーグ / 東・中・西の6地区 /"
            " 162試合 / ポストシーズン",
            "",
            "まずここから知ると、あとが早いです。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球初心者", "地区",
                 "MLB入門", "コレスポ"],
    },
    "mlb_position": {
        "title": "【野球】スタメン表が読める｜守備位置の略号 C・SS・DHとは #Shorts",
        "lead": [
            "スタメン表や速報では、守備位置も略号で書かれます。"
            "9つの位置を順に見ていきましょう。",
            "",
            "P / C / 1B / 2B / 3B / SS / LF / CF / RF / DH",
            "",
            "略号が読めると、速報がそのまま頭に入ってきます。",
        ],
        "tags": ["MLB", "野球", "野球初心者", "守備位置", "野球用語",
                 "MLB入門", "コレスポ"],
    },
}


def build_asset_metadata(topic: str) -> dict:
    meta = ASSET_META.get(topic)
    if not meta:
        raise ValueError(f"ASSET_META に未登録のトピックです: {topic}")

    lines = list(meta["lead"]) + [
        "",
        "#Shorts",
        "",
        "コレスポでは毎日19時に、その日の注目試合を"
        "「なぜ注目なのか」の理由つきでお届けしています。",
        "サイト: https://collespo.com/",
        "",
        "―――",
        "音声: VOICEVOX:ずんだもん",
        "データ: MLB Stats API",
    ]
    return {
        "snippet": {
            "title": meta["title"][:100],
            "description": "\n".join(lines)[:5000],
            "tags": meta["tags"][:15],
            "categoryId": CATEGORY_SPORTS,
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        }
    }


def load_hook(narration_path: str) -> dict:
    """
    動画の1枚目に使ったフックを、ナレーション原稿から読む。

    タイトルと動画の冒頭を同じ文言にするため。別々に組み立てると
    「サムネでは連続安打の話なのにタイトルは日付だけ」といった食い違いが出る。
    """
    try:
        data = json.loads(pathlib.Path(narration_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    for s in data.get("segments", []):
        if s.get("kind") == "intro":
            return (s.get("meta") or {}).get("hook") or {}
    return {}


def build_metadata(games_path: str, date_label: str, kind: str = "daily",
                   narration_path: str = "public/narration.json") -> dict:
    """タイトル・説明文・タグを、その日のデータから組み立てる"""
    try:
        data = json.loads(pathlib.Path(games_path).read_text(encoding="utf-8"))
        games = [g for g in data.get("games", []) if g.get("is_notable")][:3]
    except (json.JSONDecodeError, OSError):
        games = []

    if kind == "verdict":
        # 縦型ショート。予測の的中ではなく「その後どうなったか」を扱うので、
        # 「当たった/外れた」という言い方はタイトルでも使わない
        title = (f"注目した試合、どうなった？｜{date_label} "
                 f"先週の答え合わせ【MLB】#Shorts")
    elif kind == "weekly":
        # 週次まとめは横型の通常動画なので #Shorts は付けない
        title = f"今週の注目試合と答え合わせ｜{date_label}【MLB週間まとめ】"
    elif games:
        # 日付を先頭に置いていたが、「08/07」で検索する人はいない。
        # その日いちばん具体的な事実(動画の1枚目と同じもの)を先頭に出す。
        hook = load_hook(narration_path)
        big = (hook.get("big") or "").strip()
        sub = (hook.get("sub") or "").strip()
        lead = f"{sub} {big}".strip() if big else ""
        top = games[0]
        matchup = f"{top.get('home_team_name')} vs {top.get('away_team_name')}"
        if lead:
            title = f"{lead}｜{matchup} ほか {date_label}の注目試合【MLB】#Shorts"
        else:
            title = f"{matchup} ほか｜{date_label}の注目試合【MLB】#Shorts"
    else:
        title = f"{date_label}の注目試合【MLB】#Shorts"
    title = title[:100]  # YouTubeのタイトル上限

    if kind == "verdict":
        lines = [
            "コレスポが先週「◯連勝中だから注目」として取り上げた試合が、"
            "実際どうなったかを確かめます。",
            "",
            "毎日その日の注目試合を理由つきで出し、結果まで記録しているので"
            "言える内容です。勝敗を予想しているわけではありません。",
            "",
        ]
    elif kind == "weekly":
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
    parser.add_argument("--kind", default="daily",
                        choices=["daily", "weekly", "asset", "verdict"],
                        help="daily=ショート / weekly=週次まとめ / "
                             "asset=資産動画 / verdict=答え合わせショート")
    parser.add_argument("--asset-topic", default=None,
                        help="--kind asset のときのトピック名")
    parser.add_argument("--narration", default="public/narration.json",
                        help="タイトルの先頭に使うフックの取得元")
    parser.add_argument("--archive-dir", default="archive",
                        help="週次のタイトルに入れる期間の算出元")
    parser.add_argument("--thumbnail", default=None,
                        help="設定するカスタムサムネイル(PNG)")
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

    if args.kind == "asset":
        # 資産動画は試合データを一切参照しない(日付に依存しないため)
        body = build_asset_metadata(args.asset_topic or "mlb_abbr")
    else:
        date_label = ""
        try:
            data = json.loads(pathlib.Path(args.games).read_text(encoding="utf-8"))
            g = [x for x in data.get("games", []) if x.get("is_notable")]
            if g:
                date_label = (g[0].get("start_time_jst") or "").split(" ")[0]
        except (json.JSONDecodeError, OSError):
            pass

        # 週次ワークフローには notable_games.json が存在しない(あれは日次側が
        # その日に作るもの)。そのままだとタイトルから日付が丸ごと落ちるので、
        # 動画と同じ週の範囲をアーカイブから求める。
        if args.kind == "weekly" and not date_label:
            try:
                import weekly_stats as ws

                week = ws.load_week(pathlib.Path(args.archive_dir))
                if week:
                    date_label = (f"{week[0][0][5:].replace('-', '/')}〜"
                                  f"{week[-1][0][5:].replace('-', '/')}")
            except Exception as e:
                print(f"[warn] 週の範囲を求められませんでした: {e}", file=sys.stderr)

        body = build_metadata(args.games, date_label, args.kind, args.narration)
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

        # サムネイルは動画の登録が終わってからでないと設定できない。
        # ここで失敗しても動画自体は上がっているので、警告に留める。
        thumb = pathlib.Path(args.thumbnail) if args.thumbnail else None
        if thumb and thumb.exists() and vid:
            try:
                youtube.thumbnails().set(
                    videoId=vid,
                    media_body=MediaFileUpload(str(thumb), mimetype="image/png"),
                ).execute()
                print(f"[info] サムネイルを設定しました: {thumb}")
            except Exception as e:
                # カスタムサムネイルはアカウントの電話番号確認が必要。
                # 未確認だとここで必ず失敗するので、原因が分かるように書く
                print(f"[warn] サムネイルの設定に失敗しました: {e}", file=sys.stderr)
                print("       YouTubeアカウントの電話番号確認が済んでいるか"
                      "確認してください(未確認だとカスタムサムネイルは使えません)",
                      file=sys.stderr)
        elif thumb:
            print(f"[info] サムネイル画像が無いためスキップします: {thumb}")
    except Exception as e:
        # アップロードに失敗しても、通知やサイト更新は既に済んでいるので
        # ワークフロー全体を落とさない
        print(f"[warn] アップロードに失敗しました: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
