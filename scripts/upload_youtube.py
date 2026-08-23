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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import post_common  # noqa: E402
from morning_recap import jst_label as _jst_label  # noqa: E402

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("[warn] Google APIライブラリが無いためアップロードをスキップします")
    print("       pip install google-api-python-client google-auth")
    sys.exit(0)

TOKEN_URI = "https://oauth2.googleapis.com/token"
# 記録のために置いてある。更新要求には渡さない(理由は下のコメント)。
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]
# MLB / 野球 のカテゴリ。17 = Sports
CATEGORY_SPORTS = "17"


# 資産動画のトピックごとのメタ情報。
# 日次・週次と違って中身が日付に依存しないため、検索から長く拾われることを
# 狙って、タイトルと説明文を固定で持つ。
ASSET_META = {
    "mlb_abbr": {
        "title": "LAD・NYY・CWSってどこの球団？｜MLB30球団の略称を地区ごとに #Shorts",
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
        "title": "MLBの球場はなぜこんなに違う？｜点が入る球場・入らない球場 #Shorts",
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
        "title": "ヤンキースvsレッドソックスはなぜ因縁？｜MLB伝統の一戦の由来 #Shorts",
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
        "title": "OPSとは？防御率・WHIPの見方｜野球の成績の数字がわかる #Shorts",
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
        "title": "ゲーム差・ワイルドカードとは？｜MLB順位表の読み方 #Shorts",
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
        "title": "MLBの30球団はどう分かれてる？｜2リーグ6地区の仕組み #Shorts",
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
    # 1球場ずつの深掘り。検索されるのは球場名なので、タイトルの先頭に置く
    "venue_coors": {
        "title": "クアーズ・フィールドはなぜ点が入る？｜標高1600mのMLB球場 #Shorts",
        "lead": [
            "コロラド州デンバー、ロッキーズの本拠地。"
            "MLBで最も打者有利とされる球場です。なぜそうなるのかを紹介します。",
            "",
            "標高およそ1600メートル / 広い外野 / 試合球の湿度管理 / 1995年開場",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "球場", "クアーズフィールド",
                 "ロッキーズ", "コレスポ"],
    },
    "venue_fenway": {
        "title": "グリーンモンスターとは？｜フェンウェイ・パークの高さ11mの壁 #Shorts",
        "lead": [
            "マサチューセッツ州ボストン、レッドソックスの本拠地。"
            "現役では最も古く、形もMLBで一番いびつな球場です。",
            "",
            "1912年開場 / グリーンモンスター / 近い左翼 / 収容およそ3万7千人",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "球場", "フェンウェイパーク",
                 "レッドソックス", "コレスポ"],
    },
    "venue_wrigley": {
        "title": "リグレー・フィールドはなぜ風で変わる？｜カブスの本拠地 #Shorts",
        "lead": [
            "イリノイ州シカゴ、カブスの本拠地。"
            "その日の風向きで、球場の性格そのものが変わります。",
            "",
            "1914年開場 / 湖からの風 / 外野フェンスのツタ / 照明は1988年から",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "球場", "リグレーフィールド",
                 "カブス", "コレスポ"],
    },
    "venue_oracle": {
        "title": "オラクル・パークはなぜ本塁打が出にくい？｜ジャイアンツの本拠地 #Shorts",
        "lead": [
            "カリフォルニア州サンフランシスコ、ジャイアンツの本拠地。"
            "海に面した、MLBでも指折りの投手有利な球場です。",
            "",
            "右翼の後ろは湾 / 深い右中間 / 海風 / 2000年開場",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "球場", "オラクルパーク",
                 "ジャイアンツ", "コレスポ"],
    },
    "venue_yankee": {
        "title": "ヤンキー・スタジアムはなぜ左打者有利？｜浅い右翼の理由 #Shorts",
        "lead": [
            "ニューヨーク州ニューヨーク、ヤンキースの本拠地。"
            "左打者にとって、MLBでも指折りに本塁打が出やすい球場です。",
            "",
            "浅い右翼 / 深い左中間 / 2009年開場 / 収容およそ4万7千人",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "球場", "ヤンキースタジアム",
                 "ヤンキース", "コレスポ"],
    },
    "jp_players": {
        "title": "MLBの日本人選手は今何人？｜2026年シーズン 全員まとめ #Shorts",
        "lead": [
            "2026年シーズン、メジャーリーグでプレーする日本人選手を"
            "投手と野手に分けて紹介します。",
            "",
            "大谷翔平 / 山本由伸 / 佐々木朗希 / 鈴木誠也 / 吉田正尚",
            "今永昇太 / 千賀滉大 / 菊池雄星 / 村上宗隆 / 岡本和真 ほか",
        ],
        "tags": ["MLB", "メジャーリーグ", "日本人選手", "大谷翔平", "山本由伸",
                 "佐々木朗希", "野球", "コレスポ"],
    },
    "mlb_watch": {
        "title": "MLBは日本でどこで見られる？｜中継・時間帯・試合数 #Shorts",
        "lead": [
            "メジャーリーグを日本で見る方法と、試合が行われる時間帯をまとめました。",
            "",
            "試合は日本時間の朝から昼 / 3月末〜9月末で162試合 /"
            " SPOTV NOW・NHK・Prime Video など",
            "",
            "毎日15試合前後あるので、どれを見るかの手がかりも紹介します。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球中継", "MLB中継",
                 "野球初心者", "コレスポ"],
    },
    "mlb_postseason": {
        "title": "MLBのポストシーズンはどう決まる？｜ワイルドカードから世界一まで #Shorts",
        "lead": [
            "レギュラーシーズンのあと、どうやって世界一が決まるのか。"
            "MLBのポストシーズンの仕組みを順に紹介します。",
            "",
            "進出は12球団 / 地区優勝6枠 + ワイルドカード6枠 /"
            " 地区シリーズ / リーグ優勝決定シリーズ / ワールドシリーズ",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "ポストシーズン",
                 "ワイルドカード", "ワールドシリーズ", "コレスポ"],
    },
    "npb_diff": {
        "title": "【MLB】日本のプロ野球と何が違う？｜球団数・試合数・DH・移動 #Shorts",
        "lead": [
            "同じ野球でも、メジャーリーグと日本のプロ野球では仕組みがかなり違います。"
            "主な違いをまとめました。",
            "",
            "30球団162試合 vs 12球団143試合 / 2リーグ6地区 vs 2リーグ",
            "3時間の時差を挟む遠征 / 指名打者の扱い / ポストシーズンの形",
            "",
            "違いが分かると、MLBの見え方が変わります。",
        ],
        "tags": ["MLB", "メジャーリーグ", "NPB", "プロ野球", "野球",
                 "野球初心者", "コレスポ"],
    },
    "mlb_advanced": {
        "title": "【MLB】OPSの次に覚えるなら｜OPS+・wRC+・WAR・FIPの意味 #Shorts",
        "lead": [
            "打率や防御率の先に、現地の中継や記事でよく出てくる指標があります。"
            "意味だけ押さえておくと、話が追えます。",
            "",
            "OPS+ / wRC+ / WAR / FIP / 打球速度と角度",
            "",
            "どれも「100が平均」「何勝ぶん」といった、"
            "比べるための物差しとして作られた数字です。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "セイバーメトリクス",
                 "WAR", "野球初心者", "コレスポ"],
    },
    "mlb_pitch": {
        "title": "【野球】今の球、何が違う？｜球種の見分け方 #Shorts",
        "lead": [
            "中継で球種が表示されても、違いが分からないと素通りしてしまいます。"
            "よく出てくるものだけまとめました。",
            "",
            "フォーシーム / シンカー / スライダー / カーブ / チェンジアップ / スプリッター",
            "",
            "球種が分かると、投手と打者の駆け引きが見えてきます。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "球種", "変化球",
                 "野球初心者", "コレスポ"],
    },
    "soccer_leagues": {
        "title": "【サッカー】欧州5大リーグ、何が違う？｜プレミア・ラリーガ・セリエA #Shorts",
        "lead": [
            "欧州サッカーは国ごとにリーグがあり、"
            "中でも規模の大きい5つが5大リーグと呼ばれます。",
            "",
            "プレミアリーグ / ラ・リーガ / セリエA / ブンデスリーガ / リーグ・アン",
            "そしてチャンピオンズリーグ",
            "",
            "違いが分かると、どの試合を見るか決めやすくなります。",
        ],
        "tags": ["サッカー", "欧州サッカー", "プレミアリーグ", "ラリーガ",
                 "セリエA", "サッカー初心者", "コレスポ"],
    },
    "soccer_jp": {
        "title": "【サッカー】欧州でプレーする日本人選手まとめ｜所属クラブ一覧 #Shorts",
        "lead": [
            "いま欧州のクラブに所属している日本人選手を、まとめて紹介します。"
            "名前と所属を知っておくと、どの試合を見るか決めやすくなります。",
            "",
            "所属クラブは移籍市場で変わります。"
            "この動画は作成時点の情報です。",
        ],
        "tags": ["サッカー", "欧州サッカー", "日本人選手", "海外組",
                 "プレミアリーグ", "サッカー初心者", "コレスポ"],
    },
    "soccer_terms": {
        "title": "【サッカー】xG って何の数字？｜期待ゴール・ポゼッションの見方 #Shorts",
        "lead": [
            "中継や記事でよく出てくる数字を、意味だけ押さえておきましょう。"
            "分かると、スコア以外の見どころが増えます。",
            "",
            "xG（期待ゴール）/ xA / ポゼッション率 / PPDA / クリーンシート",
            "",
            "どれも「どれくらい良い形を作れていたか」を測るための数字です。",
        ],
        "tags": ["サッカー", "欧州サッカー", "xG", "期待ゴール",
                 "サッカー初心者", "コレスポ"],
    },
    "soccer_opening": {
        "title": "【サッカー】欧州リーグはいつ開幕？｜序盤の注目カードまとめ #Shorts",
        "lead": [
            "欧州の各リーグの開幕日と、序盤に見ておきたいカードをまとめました。",
            "",
            "注目カードは、昨シーズンの最終順位と"
            "日本人選手の所属クラブから機械的に選んでいます。",
            "試合時刻はすべて日本時間です。",
            "",
            "日程は変更されることがあります。"
            "正式な情報は各リーグの公式発表をご確認ください。",
        ],
        "tags": ["サッカー", "欧州サッカー", "開幕", "プレミアリーグ",
                 "ラリーガ", "セリエA", "ブンデスリーガ", "コレスポ"],
    },
    "soccer_last_season": {
        "title": "【サッカー】昨シーズンの欧州5大リーグ｜優勝クラブと上位まとめ #Shorts",
        "lead": [
            "今シーズンを見る前に、昨シーズンがどう終わったかを押さえておきましょう。"
            "序盤の力関係を読む手掛かりになります。",
            "",
            "順位・勝ち点・勝敗はすべて公開データそのままです。",
        ],
        "tags": ["サッカー", "欧州サッカー", "プレミアリーグ", "ラリーガ",
                 "セリエA", "ブンデスリーガ", "リーグアン", "コレスポ"],
    },
    "collespo_guide": {
        "title": "MLBの注目試合を毎日19時に｜コレスポの使い方 #Shorts",
        "lead": [
            "コレスポは、その日の注目試合を「なぜ注目なのか」の理由つきで"
            "毎日19時にお届けするサービスです。",
            "",
            "・毎日19時の通知（MLB / サッカー 別々に登録できます）",
            "・日本人選手の出場、順位争い、連勝記録、球場の癖から自動で選出",
            "・取り上げた試合は日付ごとに残り、結果まで追記されます",
            "・日本人選手ごとのページ、用語集、球団クイズ",
            "",
            "登録は無料。collespo.com を開いて通知を有効にするだけです。",
            "アプリのインストールは要りません。",
        ],
        "tags": ["MLB", "メジャーリーグ", "野球", "野球初心者", "野球速報",
                 "MLB入門", "コレスポ"],
    },
    "mlb_position": {
        "title": "野球のSS・DHとは？｜スタメン表の守備位置の略号 #Shorts",
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


# 毎日出しているものの一覧。説明文の下部に置く。
#
# 「毎日19時ごろ、その日の注目試合を」とだけ書いていたが、いまは5本ある。
# 時刻を1つ挙げるより、毎日何が届くのかを並べる方が登録の理由になる。
# 時刻を書かないのは、増減や入れ替えのたびに全動画の説明文が
# 過去のものまで嘘になるため。
DAILY_LINEUP_LINES = [
    "コレスポは毎日、次を自動でお届けしています。",
    "",
    *post_common.lineup_lines(),
]


def generated_topic(topic: str) -> dict:
    """自動で作ったトピックの材料。無ければ空。"""
    import generated_topics as gt
    return gt.get(topic)


def asset_meta_from_spec(spec: dict) -> dict:
    """
    自動で作ったトピックのタイトルと説明文。

    手書きの24本は1本ずつ文面を用意してあるが、球場のぶんは
    公式APIから機械的に増える。文面まで手で書いていたら結局
    毎日は続かないので、材料からそのまま組む。
    書いてあるのは全部 venue_topics.json にある数字と語だけ。
    """
    label = spec.get("label", "")
    hook = spec.get("hook", "")
    where = spec.get("where", "")
    items = spec.get("items") or []
    lead = [f"{label}（{where}）を、MLB公式データの数字で見ていきます。", ""]
    lead += [f"・{head}　{body}" for head, body in items]
    return {
        "title": f"【MLB】{label}｜{hook} #Shorts",
        "lead": lead,
        "tags": ["MLB", "メジャーリーグ", "野球", label,
                 "MLB入門", "コレスポ"],
    }


def related_lines(kind: str, limit: int = 3,
                  path: str = "data/published_videos.json") -> list:
    """
    同じ枠の、少し前の回へのリンク。無ければ空。

    なぜ要るのか:
      実測では、公開から14日を過ぎた動画は1本も再生されていない。
      Shortsフィードは97%を占めるが、そこに載るのは新しいものだけで、
      古い回に辿り着く道が検索(2.3%)しか無かった。

      フィードから来た人は説明欄を開かないので、これが効くのは
      検索から来た人だけ。ただしその層は平均102秒見ている
      (フィード経由は21秒)ので、次の1本へ渡す価値がある。
    """
    try:
        rec = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    days = rec.get(kind) or {}
    out, seen = [], set()
    for day in sorted(days, reverse=True):
        if len(out) >= limit:
            break
        e = days[day]
        vid = e.get("video_id")
        # 同じ動画が2日ぶん記録されていることがある(作り直した回など)。
        # 同じリンクが並ぶと、記録が壊れているように見える。
        if not (e.get("url") and e.get("title")) or vid in seen:
            continue
        seen.add(vid)
        out.append(f"・{e['title'][:52]}" + '\n' + f"  {e['url']}")
    if not out:
        return []
    return ["", "この枠の前回まで", ""] + out


def _fit_tags(tags: list, limit: int = 460) -> list:
    """500文字の枠に収まるところまで、前から詰める。"""
    out, total = [], 0
    for x in tags:
        if not x or x in out:
            continue
        # 空白を含むタグは引用符でくくられ、2文字ぶん余計に数えられる
        cost = len(x) + 1 + (2 if " " in x else 0)
        if total + cost > limit:
            break
        out.append(x)
        total += cost
    return out


def subject_tags(kind: str, morning_mode: str, games: list,
                 morning_players: list, profile_path: str,
                 buzz_path: str) -> list:
    """
    その動画が扱っている固有名詞。検索で当たるのはここ。

    表記を1つに決めない。同じ選手を、英語のフルネーム・姓・愛称・
    カタカナで探す人がいる。実際の検索語には「今永昇太」も
    「mlb順位表」も混ざっていて、揃っていない。
    """
    out = []

    def add(*xs):
        for x in xs:
            x = (x or "").strip()
            if x and x not in out:
                out.append(x)

    if kind == "morning" and morning_mode == "player":
        prof = load_profile(profile_path)
        name = prof.get("name") or ""
        add(name)
        if " " in name:
            add(name.split()[-1])
        add((prof.get("bio") or {}).get("nickname"))
        # カタカナの姓。VOICEVOX用に持っている読みをそのまま使う。
        try:
            import generate_narration as gn
            kana = gn.speech_name(name).replace("、", "")
            if kana != name:
                add(kana)
        except Exception:  # noqa: BLE001
            pass
        add(prof.get("team"))

        return out   # 1人の回。今日の試合のチームは関係が無い

    if kind == "morning" and morning_mode in ("voices", "local"):
        top = buzz_top(buzz_path) or {}
        for part in (top.get("matchup_jp") or "").split(" vs "):
            add(part)
        return out   # 扱っているのは、その1試合のコメント欄

    # 明日の注目試合と、週間まとめ。ここは並べた試合そのものが中身。
    for g in games[:3]:
        add(g.get("home_team_name"), g.get("away_team_name"))
    return out


def build_asset_metadata(topic: str) -> dict:
    meta = ASSET_META.get(topic)
    if not meta:
        spec = generated_topic(topic)
        if spec:
            meta = asset_meta_from_spec(spec)
    if not meta:
        raise ValueError(f"ASSET_META に未登録のトピックです: {topic}")

    lines = list(meta["lead"]) + [
        "",
        "#Shorts",
        "",
        *DAILY_LINEUP_LINES,
        "",
        *OTHER_CHANNEL_LINES,
        "",
        "―――",
        "音声: VOICEVOX:ずんだもん",
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


# 投稿済みの資産動画を記録するファイル。リポジトリへコミットするので、
# 次の実行から「まだ出していないものだけ」を選べる。
PUBLISHED_PATH = "data/published_assets.json"


def load_published(path: str = PUBLISHED_PATH) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("assets") or {}
    except (json.JSONDecodeError, OSError):
        return {}


def record_published(topic: str, video_id: str, privacy: str,
                     path: str = PUBLISHED_PATH) -> None:
    """
    投稿できたトピックを控える。

    同じ資産動画を二重に投稿すると、チャンネルに重複が並ぶだけでなく
    APIの割り当ても無駄になる。実行のたびに手で覚えておく前提にすると
    いつか必ず間違えるので、記録をリポジトリに残して機械的に判断する。
    """
    from datetime import datetime, timezone

    p = pathlib.Path(path)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    assets = data.get("assets") or {}
    assets[topic] = {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy": privacy,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"assets": assets}, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    print(f"[info] 投稿済みとして記録しました: {topic} -> {path}")


# 日付ものの動画(日次・16時・週次)の投稿記録。
# 資産動画と違ってトピックではなく日付で引くので、別ファイルに分ける。
VIDEOS_PATH = "data/published_videos.json"


def record_kind(kind: str, morning_mode: str = "players",
                sport: str = "mlb") -> str:
    """
    記録上の区分。同じ日に同じ kind が複数上がるものを見分ける。

      17:00の2本 … morning / morning_player
      18:00の2本 … morning_voices / morning_press
      19:00の2本 … daily / daily_soccer

    投稿前の重複判定と投稿後の記録が、必ず同じ名前を使うようにここへ寄せる。
    別々に組み立てていると、片方だけ直したときに黙ってすれ違う。
    """
    if kind == "morning" and morning_mode != "players":
        return f"{kind}_{morning_mode}"
    if kind == "daily" and sport != "mlb":
        return f"{kind}_{sport}"
    return kind


def published_video(kind: str, date_key: str,
                    path: str = VIDEOS_PATH) -> dict:
    """その区分・その日が既に投稿済みなら記録を返す。無ければ空。"""
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return (data.get(kind) or {}).get(date_key) or {}


def resolve_publish_at(spec: str | None) -> str | None:
    """
    "17:30" のようなJST時刻を、YouTubeに渡すUTC文字列に直す。

    公開時刻をぴったりにするための仕組み。GitHubのscheduleは2〜4時間
    遅れるため(実測)、時刻をこちらで守ろうとすると外部cronを本数分だけ
    立てることになる。代わりに1回の実行でまとめて作り、公開の時刻だけ
    YouTubeに預ける。

    過ぎた時刻を渡すとAPIが弾く。予約に失敗して非公開のまま埋もれるのが
    最悪なので、その場合はNoneを返して即時公開に倒す。
    """
    if not spec:
        return None
    from datetime import datetime, timedelta, timezone

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    try:
        hh, mm = (int(x) for x in spec.split(":"))
        when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except ValueError:
        print(f"[warn] 公開時刻を読めません: {spec!r} (HH:MM で指定してください)",
              file=sys.stderr)
        return None

    # 実行が押した場合。ここで翌日に回すと、その日の成績が翌日に出てしまう。
    #
    # 余裕を5分取っていたが、それが理由で18:57に上げた回が
    # 「19:00は5分以内だから」と即時公開になり、3分早く出た。
    # 動画のアップロードはこの判定より前に終わっていて、
    # ここから先はメタデータを送るだけなので、数十秒あれば足りる。
    if when <= now + timedelta(minutes=1):
        print(f"[info] 指定の {spec} は過ぎている(現在 {now:%H:%M})ため、"
              f"予約せずそのまま公開します")
        return None
    print(f"[info] 公開を予約します: {when:%m/%d %H:%M} JST")
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_video(kind: str, date_key: str, video_id: str,
                 title: str, path: str = VIDEOS_PATH,
                 publish_at: str | None = None) -> None:
    """
    その日の動画のIDを残す。

    アーカイブページや選手ページから「この日の動画」へ辿れるようにするため。
    サイトと動画が別々に存在していて相互に行き来できない状態だったので、
    まずIDを記録するところから繋ぐ。
    """
    from datetime import datetime, timezone

    p = pathlib.Path(path)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    entry = {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "title": title,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    # 予約投稿は公開時刻まで非公開のまま。サイトがそれを知らずに並べると、
    # その間リンクを踏んだ人が見られない動画に当たる。
    if publish_at:
        entry["publish_at"] = publish_at
    data.setdefault(kind, {})[date_key] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 動画を記録しました: {kind}/{date_key} -> {path}")


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


def weekly_lead(archive_dir: str = "archive") -> str:
    """
    週次タイトルの先頭に置く、その週いちばん目立った出来事。

    「今週の注目試合まとめ」だけでは、中身が何も想像できず開く理由にならない。
    連勝がどこまで伸びたか・どこで止まったかは、その週を一言で表す事実になる。
    """
    try:
        import pathlib as _p
        import sys as _s

        _s.path.insert(0, str(_p.Path(__file__).resolve().parent))
        import weekly_stats as ws

        week = ws.load_week(_p.Path(archive_dir))
        streaks = (ws.compute_verdict(week) or {}).get("streaks") or []
    except Exception:
        return ""

    # 数字が大きいものから拾う。7連勝は3連勝より目を引く
    parts = []
    for s in sorted(streaks, key=lambda x: -x["n"])[:2]:
        if s["kind"] == "連勝":
            parts.append(f"{s['team']}{s['n'] + 1}連勝"
                         if s["won"] else f"{s['team']}連勝ストップ")
        else:
            parts.append(f"{s['team']}連敗脱出"
                         if s["won"] else f"{s['team']}{s['n'] + 1}連敗")
    return "、".join(parts)


# 競技ごとの見出しとタグ。同じ日次の仕組みを別competitionに載せるとき、
# 変わるのはここだけになるようにまとめておく。
# MLBの文言は既存のまま(過去の動画と並びを揃えるため)。
SPORTS = {
    "mlb": {
        "badge": "【MLB】",
        "source": "データ: MLB Stats API",
        "tags": ["MLB", "メジャーリーグ", "野球", "注目試合", "コレスポ"],
    },
    "soccer": {
        "badge": "【欧州サッカー】",
        "source": "データ: football-data.org",
        "tags": ["サッカー", "海外サッカー", "欧州サッカー", "プレミアリーグ",
                 "注目試合", "コレスポ"],
    },
}


def weekly_description_lines(archive_dir: str) -> list:
    """
    週次の説明文に載せる、その週の実数。

    どれもアーカイブに記録されている値を数えただけなので、言い切ってよい。
    「熱戦が続きました」のような感想は書かない。数えたことだけを書く。
    """
    try:
        import weekly_stats as ws

        week = ws.load_week(pathlib.Path(archive_dir))
        if not week:
            return []
        v = ws.compute_verdict(week)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 週の集計を作れませんでした: {e}", file=sys.stderr)
        return []

    lines = ["■ この週の数字"]
    for value, label in ws.verdict_lines(v):
        lines.append(f"・{label}: {value}")
    lines.append("")

    streaks = v.get("streaks") or []
    if streaks:
        lines.append("■ 連勝・連敗はどうなったか")
        for s in streaks[:6]:
            lines.append(f"・{s['team']} {s['n']}{s['kind']}中 "
                         f"→ {s['result']}（{s['matchup']} {s['score']}）")
        lines.append("")
    return lines


def thread_replies(path: str = "data/local_voices.json") -> int:
    """やり取りとして紹介した一言に、返信が何件付いていたか。無ければ0。"""
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    for v in d.get("voices") or []:
        if v.get("is_thread") and v.get("reply_ja"):
            try:
                return int(v.get("replies") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def load_profile(path: str) -> dict:
    """「今日の1人」の材料。無ければ空。"""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def top_headline(path: str = "data/local_reporters.json",
                 limit: int = 42, max_age_hours: int = 20) -> str:
    """その日の現地の見出し(日本語)。無ければ空。

    古いものは使わない。
      集めてくる見出しには前日のものが混ざる(実際、上位6件のうち2件が
      前日だった)。それをタイトルの先頭に置いて日付を「8月21日」と
      書くと、一昨日の出来事を今日のことのように出すことになる。

    タイトルの先頭に置くので短く切る。切るときは句点を先に探す——
    空白のほうが後ろにあっても、そちらで切ると「達成、NL」のように
    文の途中で終わる。
    """
    try:
        heads = json.loads(pathlib.Path(path).read_text(
            encoding="utf-8")).get("headlines") or []
    except (json.JSONDecodeError, OSError):
        return ""
    now = datetime.now(timezone.utc)
    for h in heads:
        jp = (h.get("jp") or "").strip()
        if not jp:
            continue
        at = h.get("at")
        if at:
            try:
                when = parsedate_to_datetime(at)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if (now - when).total_seconds() > max_age_hours * 3600:
                    continue
            except (TypeError, ValueError):
                pass
        if len(jp) <= limit:
            return jp
        head = _clip(jp, limit)
        if head:
            return head
        # 収まらない見出しは、切らずに次へ回す
    return ""


# 打ち消しの語。これが切り落とした側にあると、頭だけ読んだ人には
# 逆の意味が伝わる。
NEGATIONS = ("ない", "ません", "ではなく", "わけでは", "否定")

# 切ったあとに残す最低の長さ。「いいえ」「速報」だけ残っても意味がない。
# 10字にしていたら「大谷翔平が2本塁打」(9字)まで弾いていた。
MIN_HEAD = 8


def _clip(jp: str, limit: int) -> str:
    """収まる範囲に、文として完結している部分があれば返す。無ければ空。

    読点では切らない。
      「サミー・ソーサが大谷翔平の落選を明かし、ナ・リーグMVPを選出」を
      読点で切ると「大谷翔平の落選を明かし」になる。元は「ソーサが自分の
      投票で大谷を選ばなかった」話なのに、大谷が何かから落選したように
      読める。打ち消しが落ちる例と同じで、切った側に意味が残っている。

      同じ形で「ドジャースが大谷翔平と契約したり」も出かけた。元は
      「…したのは融資のためではない」で、否定が丸ごと落ちていた。

      句点なら文が終わっているので切ってよい。それ以外は切らずに、
      次の見出しへ回す。見出しは毎日5〜6件あるので、1つ飛ばしても
      困らない。
    """
    cut = jp.rfind("。", 0, limit)
    if cut < MIN_HEAD:
        return ""
    head, tail = jp[:cut], jp[cut:]
    if any(n in tail for n in NEGATIONS):
        return ""
    return head


def top_talked_team(path: str = "data/local_buzz.json") -> str:
    """現地で最も名前が挙がった球団。無ければ空。

    再生回数(見られた量)とは別の軸。コメント欄の回が対戦名を
    使うので、現地編はこちらを先頭に置いて、同じ日の2本が
    同じ言葉で始まらないようにする。
    """
    try:
        teams = json.loads(pathlib.Path(path).read_text(
            encoding="utf-8")).get("teams") or []
    except (json.JSONDecodeError, OSError):
        return ""
    if not teams:
        return ""
    top = max(teams, key=lambda t: t.get("mentions") or 0)
    # 1件しか挙がっていない日は「いちばん」と言うほどの差がない
    if (top.get("mentions") or 0) < 2:
        return ""
    return top.get("name") or ""


def buzz_top(path: str) -> dict:
    """
    その日いちばん見られたMLB公式ハイライト。無ければ空。

    コメント欄の回は、タイトルと説明文で「どの試合の話か」を示す必要がある。
    「現地の声」だけでは何の動画か分からず、検索にも当たらない。
    表記は日本語にする(mlb_buzz.json は英語の対戦名で持っている)。
    """
    try:
        vids = json.loads(pathlib.Path(path).read_text(
            encoding="utf-8")).get("videos") or []
    except (json.JSONDecodeError, OSError):
        return {}
    if not vids:
        return {}
    v = vids[0]
    res = v.get("result") or {}
    out = {"views": v.get("views")}
    if res.get("away_jp") and res.get("home_jp"):
        out["matchup_jp"] = f"{res['away_jp']} vs {res['home_jp']}"
        if res.get("away_score") is not None:
            out["score_line"] = (f"{res['away_jp']} {res['away_score']} - "
                                 f"{res['home_score']} {res['home_jp']}")
    elif v.get("matchup"):
        out["matchup_jp"] = v["matchup"]
    return out


# 同じ内容を、動画のほかに音声とサイトでも出している。
#
# これまで説明文に載っていたのはサイトのURLだけだった。通勤中に
# 音声で聞きたい人にも、その選択肢があること自体が伝わっていない。
# 押し付けずに、どの形で受け取れるかだけ並べる。
#
# SNSのアカウント名はここに書かない。Secretsにしか無く、
# 間違ったURLを何百本の説明文へ焼き付けることになる。
def _other_channels() -> list:
    """他のチャネルへの案内。

    同じ内容をBlueskyとThreadsにも出しているのに、動画からそこへ
    辿る道が無かった。ハンドルは投稿のときに使っている秘密から
    そのまま取る。ここへ書き写すと、変えたときに古いまま残る。
    """
    lines = ["サイト: https://collespo.com/",
             "ポッドキャスト(同じ内容を音声で): "
             "https://collespo.com/podcast/feed.xml",
             "RSS: https://collespo.com/feed.xml"]
    bsky = os.environ.get("BLUESKY_HANDLE", "").strip()
    if bsky:
        lines.append(f"Bluesky: https://bsky.app/profile/{bsky}")
    return lines


OTHER_CHANNEL_LINES = _other_channels()


def build_metadata(games_path: str, date_label: str, kind: str = "daily",
                   narration_path: str = "public/narration.json",
                   archive_dir: str = "archive",
                   morning_players: list = None,
                   morning_mode: str = "players",
                   sport: str = "mlb",
                   buzz_path: str = "data/mlb_buzz.json",
                   profile_path: str = "data/player_profile.json") -> dict:
    """タイトル・説明文・タグを、その日のデータから組み立てる"""
    try:
        data = json.loads(pathlib.Path(games_path).read_text(encoding="utf-8"))
        games = [g for g in data.get("games", []) if g.get("is_notable")][:3]
    except (json.JSONDecodeError, OSError):
        games = []

    # 日次のフック。タイトルと説明文の冒頭で同じものを使う。
    # 注目試合が取れなかった日は空のままになる。
    daily_lead = ""

    if kind == "morning" and morning_mode == "player":
        # 選手名が最も強いフックだと実測で分かっている(32ポイント差)。
        # しかもこの回は「明日の試合」と違って古くならないので、
        # あとから名前で検索した人にも同じだけ役に立つ。
        prof = load_profile(profile_path)
        who = prof.get("name") or ""
        # 到達点があれば、それをタイトルに出す。
        #
        # 実測では「パドレス 6連勝中」が50.2%、「Kevin Gausman 移籍後2登板目」が
        # 19.1%。差は名前の知名度ではなく、数字がその選手の状態を語っているか
        # どうかだった。「30本塁打30盗塁」は誰でも意味が分かる。
        # 「通算成績・今季・受賞歴まとめ」は何も言っていない。
        import player_screens as _ps
        big = _ps.milestone(prof) or prof.get("headline") or ""
        # 今季の数字には「いつ時点か」を添える。
        #
        # 「30本塁打30盗塁」は8月の数字で、9月には31本になる。この回は
        # 日付に縛られない作りにしてあるぶん、10月に見た人には
        # どの時点の話か分からない。枠の名前(今日の1人)は入れない
        # ——入れた瞬間に翌日から古い動画になる——が、
        # 数字の時点だけは書いておく。それで古びても嘘にはならない。
        asof = f"（{date_label}時点）" if big and "今シーズン" in big else ""
        title = (f"【MLB】{who}"
                 + (f"｜{big}{asof}" if big else "")
                 + "｜通算成績・受賞歴まとめ #Shorts")
    elif kind == "morning" and morning_mode == "voices":
        # コメント欄の回。何の試合かがタイトルで分かるようにする。
        # 「現地の声」だけでは、どの試合の話なのか見当が付かない。
        # 検索されるのは球団名なので、対戦を先頭へ置く。
        m = (buzz_top(buzz_path) or {})
        card = m.get("matchup_jp") or ""
        # 返信が付いた一言を扱った回は、その件数を出す。
        # 「ファンの反応」は毎日同じ言い方になるが、件数はその日だけの数字で、
        # しかも「何を言ったらそんなに返ってきたのか」が残る。
        n = thread_replies()
        tail = f"｜返信{n}件ついたコメント {date_label} #Shorts" if n else             f"｜{date_label} 最も見られたハイライトのコメント欄 #Shorts"
        if card:
            title = f"【MLB】{card} 現地のファンは何と言ったか{tail}"
        else:
            title = f"【MLB】現地で最も見られた試合のコメント欄{tail}"
    elif kind == "morning" and morning_mode == "press":
        # 言葉の回。数字の回(local)と主題を分けてあるので、
        # タイトルでも「誰が何と言ったか」を前に出す。
        #
        # 以前は枠の名前だけを先頭に置いていて、7日続けて
        # 「現地メディアは何と言っているか」で始まっていた。
        # 変わるのは日付だけなので、並んだところを見ると
        # 同じ動画を出し直しているようにしか見えない。
        # その日の見出しそのものを先頭へ出す。中身にも実際に出る。
        # 見出しは鉤括弧に入れて、誰の言葉かを先に置く。
        #
        # 「大谷翔平が2本塁打を放つ｜8月21日 …」とだけ書くと、
        # コレスポが試合を報じているように読める。事実は合っていても、
        # 開いた人が期待するのはハイライトで、中身は報道のまとめになる。
        # 引用であることが、題を読んだ時点で分かる形にする。
        head = top_headline()
        title = (f"【MLB】現地はこう報じた「{head}」"
                 f"｜{date_label} 番記者の投稿と現地の見出し #Shorts"
                 if head else
                 f"【MLB】現地メディアは何と言っているか"
                 f"｜{date_label} 番記者の投稿と現地の見出し #Shorts")
    elif kind == "morning" and morning_mode == "local":
        # 現地編は主題が違うので、選手名ではなく「現地」を前に出す。
        # 「最も見られた試合は？」だと1試合の話に見えるが、実際は
        # 再生回数の順位と、話題に挙がったチームまで扱っている。
        #
        # ここも先頭が動かない枠だった。対戦名を出すとコメント欄の回と
        # かぶるので、この回だけが持っている軸——現地で最も名前が
        # 挙がったチーム——を先頭に置く。
        team = top_talked_team()
        title = (f"【MLB】現地でいちばん名前が挙がったのは{team}"
                 f"｜{date_label} 再生回数ランキングと話題のチーム #Shorts"
                 if team else
                 f"【MLB】現地で最も注目された試合ランキング"
                 f"｜{date_label} 再生回数と話題のチーム #Shorts")
    elif kind == "morning":
        # 検索されるのは選手名なので、貢献度の高い順に先頭へ置く。
        # 「成績まとめ」だけだと淡々と読み上げるだけの動画に見えるので、
        # 順位をつけていることをタイトルにも出す。
        names = [p.get("name") for p in (morning_players or [])][:3]
        who = "・".join(n for n in names if n)
        if who:
            title = (f"【MLB】{who} ほか｜{date_label} 日本人選手 "
                     f"勝利貢献スコア ランキング #Shorts")
        else:
            title = (f"【MLB】{date_label} 日本人選手 "
                     f"勝利貢献スコア ランキング #Shorts")
    elif kind == "verdict":
        # 縦型ショート。予測の的中ではなく「その後どうなったか」を扱うので、
        # 「当たった/外れた」という言い方はタイトルでも使わない
        title = (f"【MLB】注目した試合、どうなった？"
                 f"｜{date_label} 先週の答え合わせ #Shorts")
    elif kind == "weekly":
        # 週次まとめは横型の通常動画なので #Shorts は付けない
        lead = weekly_lead(archive_dir)
        if lead:
            title = f"【MLB】{lead}｜{date_label} 1週間を振り返る"
        else:
            title = f"【MLB】今週の注目試合と答え合わせ｜{date_label} 週間まとめ"
    elif games:
        # 日付を先頭に置いていたが、「08/07」で検索する人はいない。
        # その日いちばん具体的な事実(動画の1枚目と同じもの)を先頭に出す。
        hook = load_hook(narration_path)
        big = (hook.get("big") or "").strip()
        sub = (hook.get("sub") or "").strip()
        lead = f"{sub} {big}".strip() if big else ""
        daily_lead = lead
        top = games[0]
        badge = SPORTS.get(sport, SPORTS["mlb"])["badge"]
        matchup = f"{top.get('home_team_name')} vs {top.get('away_team_name')}"
        # 「明日の注目試合」を先頭に置く。
        #
        # 以前は「パドレス 6連勝中｜ドジャース vs ブリュワーズ ほか
        # 08/16の注目試合【MLB】」の形で、一覧では前半しか見えず、
        # この動画で明日どの試合を見ればいいのかが分かる、という肝心の
        # ことが伝わっていなかった。日付は説明文にもサムネイルにもある。
        # 見出しは1試合ではなく、その回のまとまりで決める。
        # 上位1試合だけで決めると、深夜の試合が1位だった日に
        # 「今夜」へ振れて、毎日の呼び方が安定しない。
        # 競技は先頭に置く。
        #
        # 視聴の95.3%がショートフィードから来る。フィードでは
        # タイトルの先頭しか見えず、「今夜の注目試合【MLB】｜…」だと
        # 競技名が見える前に切れていた。野球だけ、サッカーだけ見たい人が
        # 0.5秒で判断できない。競技名自体が検索語でもあるので、
        # 先頭に置いても捨てた分は小さい。
        # 札は1つだけにする。【MLB】【毎日更新】と重ねると逆効果。
        when = post_common.overall_label(games) or "次"
        head = f"{badge}{when}の注目試合"
        if lead:
            title = f"{head}｜{lead}｜{matchup} ほか #Shorts"
        else:
            title = f"{head}｜{matchup} ほか #Shorts"
    else:
        title = (f"{SPORTS.get(sport, SPORTS['mlb'])['badge']}"
                 f"{date_label}の注目試合 #Shorts")
    title = title.replace("  ", " ").strip()
    title = title[:100]  # YouTubeのタイトル上限

    # 説明文の冒頭。YouTubeは「もっと見る」より前の数行しか出さないので、
    # そこに定型文を置くと、一覧でも検索結果でも情報がゼロになる。
    # タイトルと同じく、具体的な事実を先に置く。
    if kind == "morning" and morning_mode == "player":
        prof = load_profile(profile_path)
        bio = prof.get("bio") or {}
        lines = [f"{prof.get('name','')}（{prof.get('team','')}）を、"
                 "MLB公式データからまとめました。", ""]
        # 画面と同じ日本語表記にする。APIのキー名をそのまま並べると
        # 「games 1152 avg .282 hr 307」になり、検索にも読み手にも効かない。
        import player_screens as _ps
        for label, key in (("通算", "career"), ("今季", "this_season"),
                           ("昨季", "last_season")):
            s = _ps.stat_line(prof, prof.get(key) or {})
            if s:
                lines.append(f"・{label}: {s}")
        if bio.get("debut"):
            lines.append(f"・MLBデビュー: {bio['debut']}")
        if bio.get("birth_city"):
            lines.append(f"・出身: {bio['birth_city']}")
        aw = prof.get("awards") or []
        if aw:
            lines += ["", "主な受賞歴"]
            lines += [f"・{a['season']} {a['name']}" for a in aw]
        lines += ["",
                  "数字はMLB公式データをそのまま集計したものです。",
                  "現地の言葉は翻訳したもので、コレスポの見解ではありません。"]
    elif kind == "morning" and morning_mode == "voices":
        top = buzz_top(buzz_path) or {}
        lines = [f"{date_label}のメジャーリーグで、"
                 "現地で最も見られたハイライトのコメント欄を紹介します。", ""]
        if top.get("matchup_jp"):
            lines.append(f"・試合: {top['matchup_jp']}")
        if top.get("score_line"):
            lines.append(f"・結果: {top['score_line']}")
        if top.get("views"):
            lines.append(f"・MLB公式ハイライトの再生回数: {top['views']:,}回")
        n = thread_replies()
        if n:
            lines.append(f"・最も返信の付いたコメント: 返信{n}件"
                         "（その返信も訳して紹介しています）")
        lines += ["",
                  "コメントは翻訳したもので、コレスポの見解ではありません。",
                  "賛成・批判・中立の別と、高評価の数を画面に出しています。",
                  "現地の報道（番記者と見出し）は別の動画で出しています。"]
    elif kind == "morning" and morning_mode == "press":
        lines = [f"{date_label}のメジャーリーグについて、"
                 "現地の報道をまとめました。", "",
                 "・現地の番記者がSNSに書いた投稿（実名・所属媒体つき）",
                 "・現地メディアの見出し（選手名で検索して取得）", "",
                 "いずれも翻訳したもので、コレスポの見解ではありません。",
                 "ファンのコメント欄と、数字で見る「現地での注目度」は"
                 "別の動画で出しています。"]
    elif kind == "morning" and morning_mode == "local":
        lines = [f"{date_label}のメジャーリーグについて、"
                 "現地でどれだけ注目されたかをまとめました。", "",
                 "・MLB公式ハイライトの再生回数（見られた量）",
                 "・r/baseball と現地メディアでの言及数（語られた量）",
                 "・現地の投稿を翻訳した「現地の声」", "",
                 "数字はいずれも公開されているものです。"
                 "「現地の声」は翻訳であり、当チャンネルの見解ではありません。", ""]
    elif kind == "morning":
        who = "、".join(p.get("name", "") for p in (morning_players or [])[:3])
        head = f"{who}ほか。" if who else ""
        lines = [f"{head}{date_label}のメジャーリーグから、"
                 "日本人選手の成績をまとめました。", ""]
        for p in (morning_players or [])[:8]:
            lines.append(f"・{p.get('name')} … {p.get('headline')}")
        lines += ["", "数字はMLB公式データをそのまま集計したものです。", ""]
    elif kind == "verdict":
        lines = [
            "コレスポが先週「◯連勝中だから注目」として取り上げた試合が、"
            "実際どうなったかを確かめます。",
            "",
            "毎日その日の注目試合を理由つきで出し、結果まで記録しているので"
            "言える内容です。勝敗を予想しているわけではありません。",
            "",
        ]
    elif kind == "weekly":
        # 10分の動画に1行しか説明が無かった。週次はこのチャンネルの本命で、
        # 検索も関連動画も説明文を読む。中身はアーカイブに全部あるので使う。
        lines = ["この1週間の注目試合を、結果とあわせて振り返ります。", ""]
        lines += weekly_description_lines(archive_dir)
    else:
        head = f"{daily_lead}。" if daily_lead else ""
        lines = [f"{head}{date_label} の注目試合を、"
                 "なぜ注目なのかの理由つきで紹介します。", ""]
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
        *DAILY_LINEUP_LINES,
        "",
        # 同じ枠の前回まで。検索から来た人が次の1本へ行けるように。
        *related_lines("morning_" + morning_mode
                       if kind == "morning" and morning_mode
                       and morning_mode != "players"
                       else ("morning" if kind == "morning" else kind)),
        *OTHER_CHANNEL_LINES,
        "",
        "※試合データは公式のデータをもとに自動生成しています。",
        "※放送予定は変更される場合があります。各配信サービスで最新情報をご確認ください。",
        "",
        "―――",
        "音声: VOICEVOX:ずんだもん",
        # 出典は競技で変わる。サッカーの動画にMLBのAPI名が出ていては嘘になる。
        SPORTS.get(sport, SPORTS["mlb"])["source"],
    ]

    # その回の主役を先に入れる。
    #
    # これまでタグは競技ごとの固定の並びと、日本人選手の名簿だけだった。
    # Pete Crow-Armstrong を1本まるごと扱った動画のタグに、
    # 大谷翔平・吉田正尚・村上宗隆が並んでいて、本人の名前がどこにも
    # 入っていない。「PCA MLB」で検索しても上位10本に出てこない。
    #
    # 検索から来た人は平均102秒見ている。Shortsフィードから来た人の
    # 21秒に対して5倍で、いちばん濃い流入がそこだった。
    tags = subject_tags(kind, morning_mode, games, morning_players,
                        profile_path, buzz_path)
    for x in SPORTS.get(sport, SPORTS["mlb"])["tags"]:
        if x not in tags:
            tags.append(x)
    tags.append("週間まとめ" if kind == "weekly" else "Shorts")
    if kind == "morning":
        tags += [x for x in ("日本人選手", "MLB速報") if x not in tags]
        for p in (morning_players or [])[:6]:
            if p.get("name") and p["name"] not in tags:
                tags.append(p["name"])
    if not (kind == "morning" and morning_mode in ("player", "voices", "local")):
        for g in games:
            for name in (g.get("jp_players") or [])[:2]:
                if name not in tags:
                    tags.append(name)

    return {
        "snippet": {
            "title": title,
            "description": "\n".join(lines)[:5000],
            # 上限は500文字。15本に絞っていたが、主役の名前を前に置くように
            # したので、そのぶん後ろの一般語が押し出されていた。
            "tags": _fit_tags(tags),
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
                        choices=["daily", "weekly", "asset", "verdict", "morning"],
                        help="daily=ショート / weekly=週次まとめ / "
                             "asset=資産動画 / verdict=答え合わせ / morning=夕方の5本")
    parser.add_argument("--recap", default="data/morning_recap.json",
                        help="--kind morning のときの成績データ")
    parser.add_argument("--profile", default="data/player_profile.json",
                        help="--morning-mode player のときの、今日の1人")
    parser.add_argument("--buzz", default="data/mlb_buzz.json",
                        help="--morning-mode voices のときの、"
                             "その日いちばん見られたハイライト")
    parser.add_argument("--morning-mode", default="players",
                        choices=["players", "player", "local", "press",
                                 "voices", "all"],
                        help="夕方以降の3本を区別する。"
                             "players=成績 / local=注目度 / press=現地の声")
    parser.add_argument("--asset-topic", default=None,
                        help="--kind asset のときのトピック名")
    parser.add_argument("--narration", default="public/narration.json",
                        help="タイトルの先頭に使うフックの取得元")
    parser.add_argument("--archive-dir", default="archive",
                        help="週次のタイトルに入れる期間の算出元")
    parser.add_argument("--thumbnail", default=None,
                        help="設定するカスタムサムネイル(PNG)")
    parser.add_argument("--force", action="store_true",
                        help="資産動画を投稿済みでも上げ直す")
    parser.add_argument("--video-date", default=None,
                        help="記録に使う日付(既定はUTCの実行日)")
    parser.add_argument("--privacy", default="public",
                        choices=["private", "unlisted", "public"])
    parser.add_argument("--sport", default="mlb", choices=["mlb", "soccer"],
                        help="日次の競技。見出しとタグが変わる")
    parser.add_argument("--publish-at", default=None,
                        help="JSTの公開時刻 HH:MM。指定すると予約投稿になる。"
                             "過ぎている場合はそのまま公開する")
    args = parser.parse_args()

    video_path = pathlib.Path(args.video)
    if not video_path.exists():
        print(f"[info] {video_path} が無いため、アップロードをスキップします")
        return

    # 同じ資産動画を二重に上げない。作り直したい場合は --force で上書きできる。
    if args.kind == "asset" and not args.force:
        already = load_published().get(args.asset_topic or "")
        if already:
            print(f"[info] {args.asset_topic} は投稿済みのためスキップします "
                  f"({already.get('url')})")
            print("       作り直して上げ直す場合は --force を付けてください")
            return

    # 日付ものも二重に上げない。
    #
    # 資産動画にはこの守りがあったが、日次と夕方の3本には無かった。
    # ワークフローが2度走った日に、同じ内容の動画が3種類とも2本ずつ
    # チャンネルに並んだ。記録は上書きされるので、片方はサイトからも
    # 辿れないまま残る。定刻の実行と手動の実行が重なるのは普通に起きる。
    from datetime import datetime as _dt, timezone as _tz

    date_key = args.video_date or _dt.now(_tz.utc).date().isoformat()
    rec_kind = record_kind(args.kind, args.morning_mode, args.sport)
    if args.kind in ("daily", "morning") and not args.force:
        already = published_video(rec_kind, date_key)
        if already:
            print(f"[info] {rec_kind} の {date_key} は投稿済みのため"
                  f"スキップします ({already.get('url')})")
            print("       上げ直す場合は --force を付けてください")
            return

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        print("[info] YouTube認証情報が未設定のため、アップロードをスキップします")
        return

    # scopes は渡さない。
    #
    # 渡すと更新要求に scope が乗り、付与済みと一致しない場合に
    # Googleが invalid_scope を返す。トークンを youtube.upload だけで
    # 取っていた間は一致していたので通っていたが、再生リスト用に
    # youtube を足した時点で一致しなくなり、投稿まで巻き添えになる。
    # 権限はトークン側に記録されているので、こちらから送る必要は無い。
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
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
        #
        # 答え合わせショート(verdict)は同じ週を扱うのに、ここが weekly だけを
        # 見ていた。そのため題名の日付が空になり、
        # 「注目した試合、どうなった？｜ 先週の答え合わせ」と空白だけが残っていた。
        if args.kind in ("weekly", "verdict") and not date_label:
            try:
                import weekly_stats as ws

                week = ws.load_week(pathlib.Path(args.archive_dir))
                if week:
                    date_label = (f"{week[0][0][5:].replace('-', '/')}〜"
                                  f"{week[-1][0][5:].replace('-', '/')}")
            except Exception as e:
                print(f"[warn] 週の範囲を求められませんでした: {e}", file=sys.stderr)

        morning_players = []
        if args.kind == "morning":
            try:
                rec = json.loads(pathlib.Path(args.recap).read_text(encoding="utf-8"))
                morning_players = rec.get("players") or []
                # タイトルと画面で同じ日付を使う。
                # date は米国日付なので、日本の視聴者が体感する日付
                # (date_jst)を優先する。古い記録には無いので、その場合だけ
                # date から換算する。
                d = rec.get("date_jst") or _jst_label(rec.get("date", ""))
                if d:
                    from datetime import datetime as _dt
                    _p = _dt.strptime(d, "%Y-%m-%d")
                    date_label = f"{_p.month}月{_p.day}日"
            except (json.JSONDecodeError, OSError, ValueError) as e:
                print(f"[warn] 成績データを読めませんでした: {e}", file=sys.stderr)

        body = build_metadata(args.games, date_label, args.kind,
                              args.narration, args.archive_dir, morning_players,
                              args.morning_mode, args.sport, args.buzz,
                              args.profile)
    # publishAt は privacyStatus が private のときだけ有効。
    # public のまま渡すと予約は無視され、その場で公開される。
    publish_at = resolve_publish_at(args.publish_at)
    body["status"] = {
        "privacyStatus": "private" if publish_at else args.privacy,
        "selfDeclaredMadeForKids": False,
        # 「AIの使用」の申告。ここで問われているのは、実在の人物が実際には
        # していない発言・行動をしているように見せたり、実際の映像を改変したり
        # といった「誤解を招く合成コンテンツ」かどうか。
        # この動画はテキストと図形をプログラムで描いた情報グラフィックであり、
        # そうした改変は一切していないため false とする。
        "containsSyntheticMedia": False,
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

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

        if args.kind == "asset" and vid:
            record_published(args.asset_topic or "mlb_abbr", vid, args.privacy)
        elif vid:
            # 日付ものは、アーカイブページから辿れるよう日付で記録する。
            # キーはUTC日付にする。archive/YYYY-MM-DD.json と同じ決め方なので、
            # そのままアーカイブページと突き合わせられる。
            # 区分と日付は投稿前の重複判定で決めたものをそのまま使う。
            # ここで組み立て直すと、片方だけ直したときにすれ違う。
            key, rec_kind = date_key, record_kind(
                args.kind, args.morning_mode, args.sport)
            record_video(rec_kind, key, vid, body["snippet"]["title"],
                         publish_at=publish_at)
    except Exception as e:
        # アップロードに失敗しても、通知やサイト更新は既に済んでいるので
        # ワークフロー全体を落とさない
        print(f"[warn] アップロードに失敗しました: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
