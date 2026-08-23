"""
資産動画(日付に依存しない、作り置きできる動画)を生成する。

日次のショートとの違い:
  日次は「その日の試合」なので、翌日には価値が落ちる。
  こちらは「知識」を扱うため、1年後に見られても内容が古くならない。
  検索から継続的に流入することを狙う、いわば在庫になる動画。

第1弾: MLB30球団の略称
  中継のスコアボードやこのサイトの通知では、球団名が3文字前後の略称で
  出てくる。ここが読めないと情報が頭に入ってこないため、
  「野球に触れ始めた人が生中継をもっと楽しめるようになる」という
  コンセプトの入口として、まずここを扱う。

内容の作り方について:
  原稿はAIに書かせず、notability_engine.py が持っている球団テーブルから
  機械的に組み立てる。事実(略称・地区・球団名)の羅列でしかないため
  文章を考える余地が無く、AIを挟むと誤りが混ざる余地が増えるだけだから。
  結果としてAPIコストもゼロになる。

使い方(2段階):
  # 1. 読み上げ原稿を書き出す
  python3 scripts/generate_asset_video.py --topic mlb_abbr \
      --narration-out build/asset_narration.json
  # 2. synthesize_narration.py で音声化した後、動画を書き出す
  python3 scripts/generate_asset_video.py --topic mlb_abbr \
      --audio-dir build/asset_audio --out build/asset
"""

import argparse
import datetime as dt
import functools
import json
import os
import pathlib
import re
import subprocess
import sys
import wave

import usmap

from PIL import Image, ImageDraw, ImageFont

import soccer_preview
import venue_stats

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notability_engine import (  # noqa: E402
    JP_PLAYERS_MLB,
    JP_PLAYERS_SOCCER,
    MLB_DIVISION_NAME_JP,
    MLB_DIVISIONS,
    MLB_RIVALRIES,
    MLB_RIVALRY_NOTES,
    MLB_TEAM_ABBR,
    MLB_TEAM_COLOR,
    MLB_TEAM_NAME_JP,
    MLB_VENUE_NOTES,
    SOCCER_LEAGUE_NAME_JP,
    club_name_jp,
)

# 縦型(ショート向け)
W, H = 1080, 1920
FPS = 24
ANIM_END = 0.45

# 種別ごとの最低表示秒数。読み上げが終わった瞬間に切り替わると
# 略称を目で追う時間が無いため、下限を設けている。
MIN_DURATION = {"intro": 5.0, "division": 9.0,
                # 地図は寄る動きが中身なので、他より長く取る
                "map": 13.0, "venue": 10.0,
                "list": 10.0, "rivalry": 9.0, "outro": 6.0}

BG = (11, 14, 20)
SURF = (18, 22, 31)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
JP = (73, 197, 182)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None

# 略称を読み上げさせるためのアルファベット読み。
# VOICEVOXにローマ字をそのまま渡すと読み方が安定しないため、
# 日本語話者が実際に口にする読み(NYY→エヌワイワイ)へ開いておく。
LETTER_KANA = {
    "A": "エー", "B": "ビー", "C": "シー", "D": "ディー", "E": "イー",
    "F": "エフ", "G": "ジー", "H": "エイチ", "I": "アイ", "J": "ジェー",
    "K": "ケー", "L": "エル", "M": "エム", "N": "エヌ", "O": "オー",
    "P": "ピー", "Q": "キュー", "R": "アール", "S": "エス", "T": "ティー",
    "U": "ユー", "V": "ブイ", "W": "ダブリュー", "X": "エックス",
    "Y": "ワイ", "Z": "ゼット",
}

# 画面に出す地区の順番。ア・リーグ→ナ・リーグ、東→中→西で固定する。
DIVISION_ORDER = ["ALE", "ALC", "ALW", "NLE", "NLC", "NLW"]


def _resolve_font() -> str:
    global _FONT_FILE
    if _FONT_FILE:
        return _FONT_FILE
    # 手元で動作確認するとき用の逃げ道。CIではLinuxの候補が先に見つかる。
    env = os.environ.get("COLLESPO_FONT")
    if env and pathlib.Path(env).exists():
        _FONT_FILE = env
        return _FONT_FILE
    for p in FONT_CANDIDATES:
        if pathlib.Path(p).exists():
            _FONT_FILE = p
            return p
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                           capture_output=True, text=True, check=True)
        if r.stdout.strip():
            _FONT_FILE = r.stdout.strip()
            return _FONT_FILE
    except Exception:
        pass
    raise RuntimeError("日本語フォントが見つかりません")


# フォントは1度読んだら使い回す。
#
# ImageFont.truetype はそのつどファイルを開いて読む。描画1枚のうちに
# 何十回も呼ぶので、1本の動画で数万回ファイルを開いていた。
# 大きさの種類は10個ほどしかない。読み直す理由が無い。
@functools.lru_cache(maxsize=64)
def font(size: int):
    path = _resolve_font()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        for i in (1, 2, 3):
            try:
                return ImageFont.truetype(path, size, index=i)
            except OSError:
                continue
        raise


def ease_out(t):
    return 1 - (1 - t) ** 3


def spell(abbr: str) -> str:
    """'NYY' -> 'エヌワイワイ'"""
    return "".join(LETTER_KANA.get(c, c) for c in abbr)


def teams_by_division() -> dict:
    """地区コード -> [(abbr, 日本語名, 色), ...] を、画面順で返す"""
    out = {code: [] for code in DIVISION_ORDER}
    for team_id, div in MLB_DIVISIONS.items():
        if div not in out:
            continue
        out[div].append((
            MLB_TEAM_ABBR.get(team_id, ""),
            MLB_TEAM_NAME_JP.get(team_id, ""),
            MLB_TEAM_COLOR.get(team_id),
        ))
    # 同じ地区の中は略称のアルファベット順にする。
    # 順位で並べると毎回変わってしまい、作り置きできる動画にならない。
    for code in out:
        out[code].sort(key=lambda t: t[0])
    return out


# ---------------------------------------------------------------------------
# 原稿
# ---------------------------------------------------------------------------

# 「見出し + 説明」を並べるだけで作れるトピック。
# 画面のレイアウトは共通なので、増やすときはここにデータを足すだけでよい。
# 中身はすべて、検証を必要としない一般的な用語・仕組みの説明に限る
# (今季の成績や順位のような、都度確かめないと正しさを保証できない数字は
#  入れない。資産動画は作り置きして長く使うため、古くなる情報を載せない)。
LIST_TOPICS = {
    "mlb_stats": {
        "label": "成績の数字の見方",
        "hook": "OPS って何の数字？",
        "heading": "この数字だけ分かればいい",
        "intro": "中継やネットで見かける成績の数字。よく出てくるものだけ、"
                 "意味と目安をまとめます。",
        "items": [
            ("OPS", "出塁率と長打率を足した、打者の総合力を表す数字。"
                    "0.900を超えると一流の目安です"),
            ("打率", "安打の数を打数で割った数字。3割を超えると好打者とされます"),
            ("防御率 ERA", "投手が9イニングを投げた場合に、平均で何点取られるかを表す数字。"
                          "低いほど優秀で、3点台前半なら好投手の目安です"),
            ("WHIP", "投手が1イニングあたりに許した四球と安打の合計。"
                     "1.00を切ると支配的な投球とされます"),
            ("打点 RBI", "自分の打撃で味方を本塁に還した数。"
                        "チャンスでの強さを示す数字の一つです"),
            ("奪三振", "投手が三振を奪った数。球威と決め球の質が表れます"),
        ],
    },
    "mlb_terms": {
        "label": "順位表の読み方",
        "hook": "ゲーム差って何？",
        "heading": "順位表、こう読む",
        "intro": "順位表に並ぶ言葉が分かると、その日の試合が"
                 "どれくらい重いのかが見えてきます。",
        "items": [
            ("ゲーム差", "上位チームとの差を表す数字。1ゲーム差は、"
                       "直接対決に1つ勝てば並べる距離です"),
            ("地区首位", "所属する地区で1位のこと。MLBは6つの地区に分かれており、"
                       "各地区の1位はプレーオフに進めます"),
            ("ワイルドカード", "地区1位になれなかったチームのうち、"
                             "勝率上位に与えられるプレーオフ出場枠です"),
            ("直近10試合", "最近10試合の勝敗。シーズン通算の成績では見えない、"
                         "今の調子が分かります"),
            ("インターリーグ", "ア・リーグとナ・リーグをまたぐ対戦のこと。"
                             "普段は当たらない組み合わせが実現します"),
            ("同地区対決", "同じ地区のチーム同士の対戦。"
                         "勝てば相手を直接引き離せるので、順位争いでは特に重みがあります"),
        ],
    },
    "mlb_league": {
        "label": "MLBの仕組み",
        "hook": "30球団、どう分かれてる？",
        "heading": "30球団、どう分かれている？",
        "intro": "MLBは30球団。2つのリーグと6つの地区に分かれています。"
                 "この構造が分かると、順位表が一気に読めるようになります。",
        "items": [
            ("2つのリーグ", "ア・リーグ(アメリカン)とナ・リーグ(ナショナル)。"
                          "それぞれ15球団ずつに分かれています"),
            ("6つの地区", "各リーグが東・中・西の3地区に分かれ、"
                        "1地区あたり5球団。合わせて30球団です"),
            ("指名打者の違い", "かつてはア・リーグだけが投手の代わりに打つ"
                            "指名打者を使えましたが、現在は両リーグで採用されています"),
            ("レギュラーシーズン", "3月末から9月末まで、1球団あたり162試合。"
                                "ほぼ毎日試合があるのがMLBの特徴です"),
            ("ポストシーズン", "各地区の1位とワイルドカードの計12球団が進出。"
                            "勝ち上がった2球団がワールドシリーズを戦います"),
        ],
    },
    # --- 1球場ずつの深掘り ---
    # 19球場を1本にまとめたものとは別に、1球場を1本で扱う。
    # まとめ版は「そんな球場があるのか」で終わるが、こちらは
    # なぜそうなるのかまで踏み込める。
    # 数字(開場年・標高・距離)は広く知られている値のみを載せ、
    # 年によって変わる収容人数は「約」で丸める。
    "venue_coors": {
        "label": "クアーズ・フィールド",
        "hook": "なぜ点が入る？",
        "heading": "クアーズ・フィールド",
        "venue_en": "Coors Field",
        # 「MLBで最も打者有利」と断定していたが、実測では2位だった。
        # 数字を併記する以上、言い伝えの方は断定を避ける。
        "intro": "コロラド州デンバー、ロッキーズの本拠地。"
                 "打者有利の代名詞とされる球場です。なぜそうなるのか見ていきます。",
        "items": [
            ("標高およそ1600メートル", "MLBで群を抜いて高い場所にあります。"
                                 "空気が薄いぶん打球の抵抗が小さく、"
                                 "同じ打球でも他の球場より遠くまで飛びます"),
            ("外野が広い", "打球が飛ぶぶん、外野手の守る範囲を広く取ってあります。"
                       "その結果、本塁打にならなかった打球が長打になりやすい"),
            ("試合球を湿度管理している", "飛びすぎを抑えるため、試合で使うボールを"
                                 "湿度を保った保管庫に入れています。"
                                 "他球場にはあまり無い工夫です"),
            ("1995年開場", "収容はおよそ5万人。デンバーの市街地にあります"),
        ],
    },
    "venue_fenway": {
        "label": "フェンウェイ・パーク",
        "hook": "この壁、高さ11m",
        "heading": "フェンウェイ・パーク",
        "venue_en": "Fenway Park",
        "intro": "マサチューセッツ州ボストン、レッドソックスの本拠地。"
                 "現役では最も古く、形もMLBで一番いびつな球場です。",
        "items": [
            ("1912年開場", "MLBで現役最古の球場です。"
                        "街の区画に合わせて作られたため、左右非対称な形になりました"),
            ("グリーンモンスター", "左翼にそびえる高さおよそ11メートルの緑の壁。"
                             "本塁打になりそうな打球が跳ね返り、"
                             "逆に平凡な飛球が二塁打になることもあります"),
            ("左翼までが非常に近い", "他の球場より短く、右打者の打球が壁に届きやすい。"
                              "その代わり壁が高く、越えるのは簡単ではありません"),
            ("収容はおよそ3万7千人", "MLBでは小さい部類で、観客席とグラウンドが近いことでも知られます"),
        ],
    },
    "venue_wrigley": {
        "label": "リグレー・フィールド",
        "hook": "風で試合が変わる",
        "heading": "リグレー・フィールド",
        "venue_en": "Wrigley Field",
        "intro": "イリノイ州シカゴ、カブスの本拠地。"
                 "その日の風向きで、球場の性格そのものが変わります。",
        "items": [
            ("1914年開場", "フェンウェイ・パークに次いで古い現役球場です"),
            ("風で試合が変わる", "近くのミシガン湖から吹く風の向き次第で、"
                          "外野へ吹く日は打撃戦、内野へ吹き込む日は"
                          "投手戦になりやすいことで知られます"),
            ("外野フェンスのツタ", "壁一面にツタが生えており、"
                           "打球が中に入り込むと二塁打の扱いになります"),
            ("照明が付いたのは1988年", "長くデーゲーム専用の球場で、"
                                "ナイターができるようになったのは比較的最近です"),
        ],
    },
    "venue_oracle": {
        "label": "オラクル・パーク",
        "hook": "打球が海に落ちる",
        "heading": "オラクル・パーク",
        "venue_en": "Oracle Park",
        # 「MLBでも指折りの投手有利」と書いていたが、実測は30球場中17位で
        # 中位だった。言い伝えのまま断定すると、直後に出る数字と食い違う。
        "intro": "カリフォルニア州サンフランシスコ、ジャイアンツの本拠地。"
                 "海に面した、本塁打が出にくいことで知られる球場です。",
        "items": [
            ("右翼のすぐ後ろが海", "場外へ飛んだ打球がサンフランシスコ湾に落ちます。"
                            "ボートで球を拾いに来る人がいることでも知られます"),
            ("右中間が非常に深い", "MLBでも屈指の深さで、本塁打になりにくい一方、"
                           "三塁打が出やすい球場になっています"),
            ("海風が打球を止める", "湾から吹く冷たい風が外野方向へ抜けにくく、"
                           "飛距離が伸びにくい要因になっています"),
            ("2000年開場", "収容はおよそ4万1千人。街の中心部から歩いて行ける立地です"),
        ],
    },
    "venue_yankee": {
        "label": "ヤンキー・スタジアム",
        "hook": "左打者が有利な理由",
        "heading": "ヤンキー・スタジアム",
        "venue_en": "Yankee Stadium",
        "intro": "ニューヨーク州ニューヨーク、ヤンキースの本拠地。"
                 "左打者にとって、MLBでも指折りに本塁打が出やすい球場です。",
        "items": [
            ("右翼が浅い", "本塁からの距離が短く、"
                       "左打者の引っ張った打球が本塁打になりやすい形です"),
            ("2009年開場", "旧ヤンキー・スタジアムの向かいに建てられました。"
                        "旧球場は1923年開場で、長くヤンキースの本拠地でした"),
            ("収容はおよそ4万7千人", "MLBでも大きい部類の球場です"),
            ("左中間は深い", "右翼が浅い一方で左中間は距離があり、"
                       "右打者と左打者で本塁打の出やすさが大きく違います"),
        ],
    },
    # --- 検索需要が明確なもの ---
    # 実測で、疑問形のタイトル(「〜とは」「なぜ〜」)を持つ資産動画は
    # そうでないものの6倍見られていた。流入の57%が検索なので、
    # 「視聴者が実際に打ち込む言葉」を扱うトピックを優先する。
    "jp_players": {
        "label": "MLBの日本人選手",
        "hook": "今、何人いる？",
        "dynamic": "jp_players",
        "intro": "2026年シーズン、メジャーリーグでプレーする日本人選手を"
                 "投手と野手に分けて紹介します。",
        "items": [],   # 名簿から組み立てるので、ここは空でよい
    },
    "mlb_watch": {
        "label": "MLBの見かた",
        "hook": "日本でどこで見られる？",
        "intro": "メジャーリーグを日本で見る方法と、"
                 "試合が行われる時間帯をまとめました。",
        "items": [
            ("試合は日本の朝から昼", "アメリカの夜の試合が、日本時間の朝8時ごろから"
                               "始まります。西海岸の試合は昼過ぎまでかかります"),
            ("平日でも毎日ある", "3月末から9月末まで、1球団あたり162試合。"
                           "ほぼ毎日どこかで試合が行われています"),
            ("配信サービスで見る", "SPOTV NOW、NHK、Prime Video(SPOTVチャンネル)などで"
                            "中継されています。放送予定は日によって変わります"),
            ("どの試合を見るか", "毎日15試合前後あるので、全部は追えません。"
                          "日本人選手の出場、順位争い、連勝などを手がかりに選ぶと"
                          "見どころのある試合に当たりやすくなります"),
        ],
    },
    "mlb_postseason": {
        "label": "MLBのポストシーズン",
        "hook": "どうやって優勝が決まる？",
        "intro": "レギュラーシーズンのあと、どうやって世界一が決まるのか。"
                 "MLBのポストシーズンの仕組みを順に見ていきます。",
        "items": [
            ("進出できるのは12球団", "各リーグ6球団ずつ。30球団のうち"
                               "5球団に2球団が勝ち残る計算になります"),
            ("地区優勝が6枠", "ア・リーグとナ・リーグ、それぞれ東・中・西の"
                         "3地区で1位になった球団が進みます"),
            ("ワイルドカードが6枠", "地区優勝を逃した中で勝率上位の3球団が、"
                             "各リーグから進出します。地区2位でも進めるのがこの枠です"),
            ("勝ち抜き方式", "ワイルドカードシリーズ、地区シリーズ、"
                        "リーグ優勝決定シリーズと勝ち上がります"),
            ("ワールドシリーズ", "両リーグの勝者が対戦し、先に4勝した方が世界一。"
                          "10月末に行われます"),
        ],
    },
    "npb_diff": {
        "label": "MLBとNPB、何が違う？",
        "hook": "日本の野球と何が違う？",
        "heading": "MLBとNPBの違い",
        "intro": "同じ野球でも、メジャーリーグと日本のプロ野球では"
                 "仕組みがかなり違います。主な違いを見ていきましょう。",
        "items": [
            ("球団数と試合数", "MLBは30球団で1シーズン162試合。"
                          "NPBは12球団で143試合。"
                          "MLBの方が球団も試合も多く、ほぼ毎日試合があります"),
            ("リーグの分かれ方", "MLBはア・リーグとナ・リーグが15球団ずつ、"
                          "さらに東・中・西の3地区に分かれます。"
                          "NPBはセ・パ2リーグが6球団ずつで、地区はありません"),
            ("移動の負担", "MLBは国土が広く、東海岸と西海岸では3時間の時差があります。"
                       "遠征のたびに飛行機で移動し、時差も伴います"),
            ("指名打者", "MLBは両リーグとも投手の代わりに打つ指名打者を採用しています。"
                     "NPBでは採用しているリーグとそうでないリーグがあります"),
            ("ポストシーズン", "MLBは12球団が進出し、勝ち上がった2球団が"
                          "ワールドシリーズを戦います。"
                          "NPBは各リーグ3球団によるクライマックスシリーズを経て"
                          "日本シリーズへ進みます"),
            ("球場の個性", "MLBは球場ごとに広さも形も大きく異なり、"
                       "同じ打球でも球場によって結果が変わります"),
        ],
    },
    "mlb_advanced": {
        "label": "現地で使われる指標",
        "hook": "OPSの次に覚えるなら",
        "heading": "現地で使われる指標",
        "intro": "打率や防御率の先に、現地の中継や記事でよく出てくる"
                 "指標があります。意味だけ押さえておくと、話が追えます。",
        "items": [
            ("OPS＋（オーピーエスプラス）", "OPSを、球場の広さやその年のリーグ全体の"
                                  "水準で補正した数字。100がちょうど平均で、"
                                  "150なら平均より5割優れている、という読み方をします"),
            ("wRC＋（ダブリューアールシープラス）", "打者がどれだけ得点を生み出したかを"
                                     "表す数字。こちらも100が平均です。"
                                     "現地では打者の総合評価によく使われます"),
            ("WAR（ウォー）", "その選手がいることで、代わりの選手に比べて"
                          "何勝ぶん多く勝てたかを表す数字。"
                          "打撃・守備・走塁をまとめて1つにした評価です"),
            ("FIP（フィップ）", "投手の成績から、守備の影響を取り除いた指標。"
                          "防御率が良くても守備に助けられていた場合、"
                          "FIPは高めに出ます"),
            ("打球速度と角度", "打った瞬間の速さと角度を計測したもの。"
                        "そこから「本来ならヒットになっていたはず」の"
                        "期待値も算出されます"),
        ],
    },
    "mlb_pitch": {
        "label": "投げている球の種類",
        "hook": "今の球、何が違う？",
        "heading": "投げている球の種類",
        "intro": "中継で球種が表示されても、違いが分からないと素通りしてしまいます。"
                 "よく出てくるものだけまとめました。",
        "items": [
            ("フォーシーム", "いわゆる真っすぐ。回転で落ちにくくなるため、"
                       "打者からは浮き上がってくるように見えます。"
                       "最も速く、球速表示が出るのはたいていこれです"),
            ("シンカー / ツーシーム", "真っすぐに近い速さで、打者の手元で沈む球。"
                              "ゴロを打たせたいときに使われます"),
            ("スライダー", "横に滑るように曲がる球。速球と組み合わせて"
                      "空振りを取る、最もよく使われる変化球です"),
            ("カーブ", "大きく縦に落ちる球。速球との球速差が大きく、"
                   "打者のタイミングを外します"),
            ("チェンジアップ", "腕の振りは速球と同じまま、球速だけ落とす球。"
                        "打者は速球だと思って振ってしまいます"),
            ("スプリッター", "打者の手前で急に落ちる球。"
                      "日本の投手が得意とすることで知られています"),
        ],
    },
    # --- 欧州サッカー ---
    # MLBがオフに入る10月以降、コレスポの主戦場はサッカーになる。
    # 開幕(8月下旬)前に、見るための前提を揃えておく回。
    "soccer_leagues": {
        "label": "欧州5大リーグ",
        "hook": "5大リーグって何が違う？",
        "heading": "欧州5大リーグ",
        "intro": "欧州サッカーは国ごとにリーグがあり、"
                 "中でも規模の大きい5つが5大リーグと呼ばれます。",
        "items": [
            ("プレミアリーグ（イングランド）", "20クラブ。放映権収入が最も大きく、"
                                     "資金力の面で世界最高峰とされます。"
                                     "日本人選手が多く在籍するリーグでもあります"),
            ("ラ・リーガ（スペイン）", "20クラブ。技術と戦術を重んじる作りで、"
                               "レアル・マドリードとバルセロナの2強が長く中心にいます"),
            ("セリエA（イタリア）", "20クラブ。守備の組織を重視する伝統があり、"
                             "戦術的な駆け引きが見どころとされます"),
            ("ブンデスリーガ（ドイツ）", "18クラブ。観客動員が多く、"
                                "若手が出場機会を得やすいリーグとして知られます"),
            ("リーグ・アン（フランス）", "18クラブ。育成に定評があり、"
                                "ここから他リーグへ移る選手が多く出ます"),
            ("チャンピオンズリーグ", "各国リーグの上位クラブが集まる大会。"
                              "火曜と水曜に開催されるので、"
                              "週末のリーグ戦と合わせるとほぼ毎日試合があります"),
        ],
    },
    "soccer_jp": {
        "label": "欧州の日本人選手",
        "hook": "欧州に何人いる？",
        "heading": "欧州でプレーする日本人選手",
        "intro": "いま欧州のクラブに所属している日本人選手を、まとめて見ていきます。"
                 "名前と所属を知っておくと、どの試合を見るか決めやすくなります。",
        # 項目は名簿(JP_PLAYERS_SOCCER)から自動で組み立てる
        "dynamic": "soccer_jp",
        "items": [],
    },
    "soccer_terms": {
        "label": "サッカーで使われる指標",
        "hook": "xG って何の数字？",
        "heading": "サッカーで使われる指標",
        "intro": "中継や記事でよく出てくる数字を、意味だけ押さえておきましょう。"
                 "分かると、スコア以外の見どころが増えます。",
        "items": [
            ("xG（期待ゴール）", "そのシュートが決まる確率を、位置や状況から見積もった数字。"
                          "0.8なら「8割方入る場面」。"
                          "試合のxGを足すと「本来何点入ってもおかしくなかったか」が見えます"),
            ("xA（期待アシスト）", "そのパスがアシストになる確率。"
                           "得点に結びつかなくても、良い形を作れていたかが分かります"),
            ("ポゼッション率", "ボールを保持していた時間の割合。"
                        "ただし高いほど強いとは限らず、"
                        "あえて持たせて守る戦い方もあります"),
            ("PPDA", "相手が何本パスを通すごとに守備を仕掛けたかを表す数字。"
                     "小さいほど前から激しく追っている、という読み方をします"),
            ("クリーンシート", "無失点で試合を終えること。"
                        "守備陣とGKの評価によく使われます"),
        ],
    },
    # 以下2つは data/soccer_preview.json を読む。
    # 中身が無い環境では原稿の段階で止まり、動画は作られない。
    # 開幕日程も昨季順位も、こちらで書き起こす部分は無い。
    "soccer_opening": {
        "label": "今シーズンの開幕と序盤の注目カード",
        "hook": "開幕はいつ？",
        "heading": "欧州サッカー 開幕ガイド",
        "intro": "欧州の各リーグがいつ始まるのか、"
                 "そして序盤に見ておきたいカードを確認しておきましょう。",
        "dynamic": "soccer_opening",
        "items": [],
    },
    "soccer_last_season": {
        "label": "昨シーズンはどうだったか",
        "hook": "昨季の王者は？",
        "heading": "昨シーズンの結果",
        "intro": "今シーズンを見る前に、昨シーズンがどう終わったかを"
                 "押さえておきましょう。序盤の力関係を読む手掛かりになります。",
        "dynamic": "soccer_last_season",
        "items": [],
    },
    "collespo_guide": {
        "label": "コレスポの使い方",
        "hook": "毎日19時に届きます",
        "heading": "毎日19時に届きます",
        "intro": "コレスポは、その日の注目試合を「なぜ注目なのか」の理由つきで"
                 "毎日19時にお届けするサービスです。何ができるのか紹介します。",
        "items": [
            ("毎日19時の通知", "その日の注目試合が、理由つきでスマホに届きます。"
                            "MLBとサッカーは別々に登録できます"),
            ("なぜ注目かが分かる", "日本人選手の出場、順位争い、連勝記録、球場の癖。"
                               "何を見れば楽しめるかが先に分かります"),
            ("過去の試合も残る", "取り上げた試合は日付ごとに残り、"
                             "結果が出たあとにスコアまで追記されます"),
            ("選手ごとにまとまる", "日本人選手ごとのページがあり、"
                              "その選手が取り上げられた試合を辿れます"),
            ("用語集とクイズ", "略称や成績の見方を調べられる用語集と、"
                           "球団を当てるクイズもあります"),
            ("登録は無料", "collespo.com を開いて、通知を有効にするだけです。"
                        "アプリのインストールは要りません"),
        ],
    },
    "mlb_position": {
        "label": "守備位置の略号",
        "hook": "SS ってどこの守備？",
        "heading": "スタメン表が読める",
        "intro": "スタメン表や速報では、守備位置も略号で書かれます。"
                 "9つの位置を順に見ていきましょう。",
        "items": [
            ("P / C", "ピッチャー(投手)と、キャッチャー(捕手)。"
                     "この2人をバッテリーと呼びます"),
            ("1B / 2B", "ファースト(一塁手)とセカンド(二塁手)。"
                       "数字は塁の番号にそのまま対応しています"),
            ("3B / SS", "サード(三塁手)とショート(遊撃手)。"
                       "ショートだけはSSで、ショートストップの略です"),
            ("LF / CF / RF", "レフト、センター、ライト。"
                            "左翼・中堅・右翼の3つの外野の位置です"),
            ("DH", "指名打者。守備につかず、打つことだけを担当します"),
        ],
    },
}


def load_generated_topics() -> dict:
    """
    自動で作ったトピックを読み込む。

    なぜ自動なのか:
      手で書いた資産動画は24本作って、24本とも出し終えた。在庫がゼロ。
      常緑ものは実測で維持率76.3%と、日次の倍以上まで見られている。
      見られれば最後まで見られるのに、出す玉が無い状態だった。

      球場は30あって、収容人数もフィールドの寸法も標高も公式APIから
      取れる。しかも全部の球場で数字が違うので、1つの型で中身の違う
      ものが並ぶ。書き方は venue_topics.py に置いてある。

    読めなければ何も足さない。手書きのぶんはそのまま使える。
    """
    import generated_topics as gt
    out = {}
    for key, spec in gt.all_topics().items():
        if key in LIST_TOPICS:
            continue   # 手書きのぶんが先。あちらの方が踏み込んでいる。
        out[key] = {k: v for k, v in spec.items() if k != "key"}
        out[key]["items"] = [tuple(x) for x in spec.get("items") or []]
    return out


# 起動時に1度だけ足す。以降 LIST_TOPICS を引くところは全部そのまま動く。
LIST_TOPICS.update(load_generated_topics())


def venue_items() -> list:
    """
    球場の特徴。notability_engine の MLB_VENUE_NOTES をそのまま使う。

    見出しには「どのチームの本拠地で、どこにあるか」を必ず付ける。
    球場の癖だけを聞いても、それがどこの話なのか分からないと頭に残らない。
    表示順は登録順のまま固定し、作り置きできる動画として
    毎回同じ内容になるようにしている。

    同じ球場が改称前後で2件登録されている場合があるので、
    本拠地球団が重複するものは先に出てきた方だけを使う。
    """
    out, seen = [], set()
    for v in MLB_VENUE_NOTES.values():
        jp, note = v[0], v[1]
        team_id = v[2] if len(v) > 2 else None
        place = v[3] if len(v) > 3 else None
        if team_id and team_id in seen:
            continue
        if team_id:
            seen.add(team_id)
        team = MLB_TEAM_NAME_JP.get(team_id or "", "")
        head = f"{jp}｜{team}" if team else jp
        body = f"{place}。{note}" if place else note
        out.append((head, body))
    return out


def rivalry_items() -> list:
    """伝統の一戦と、その由来"""
    out = []
    for pair, kind in MLB_RIVALRIES.items():
        note = MLB_RIVALRY_NOTES.get(pair)
        if not note:
            continue
        names = sorted(MLB_TEAM_NAME_JP.get(t, "") for t in pair)
        colors = [MLB_TEAM_COLOR.get(t) for t in sorted(pair)]
        out.append({
            "title": " vs ".join(n for n in names if n),
            "kind": "伝統の一戦" if kind == "historic" else "同都市対決",
            "note": note,
            "colors": colors,
        })
    # 由来の短いものから並べると尻すぼみになるので、種別でまとめる
    out.sort(key=lambda x: (x["kind"] != "伝統の一戦", x["title"]))
    return out


def build_narration(topic: str) -> dict:
    if topic in LIST_TOPICS:
        return _narration_list(topic)
    if topic == "mlb_venue":
        return _narration_venue()
    if topic == "mlb_rivalry":
        return _narration_rivalry()
    if topic != "mlb_abbr":
        raise ValueError(f"未対応のトピックです: {topic}")

    by_div = teams_by_division()
    segments = [{
        "kind": "intro",
        "text": "野球中継のスコアボードでは、球団名がアルファベットの略称で"
                "表示されます。三十球団ぶん、地区ごとに見ていきましょう。",
        "meta": {},
    }]

    for i, code in enumerate(DIVISION_ORDER):
        teams = by_div[code]
        parts = [MLB_DIVISION_NAME_JP[code] + "。"]
        for abbr, name_jp, _ in teams:
            parts.append(f"{name_jp}は、{spell(abbr)}。")
        segments.append({
            "kind": "division",
            "text": "".join(parts),
            "meta": {"division_index": i},
        })

    segments.append(_outro_segment())
    return {"label": "MLB30球団の略称", "segments": segments}


def _outro_segment() -> dict:
    return {
        "kind": "outro",
        "text": "コレスポでは、毎日午後七時に、その日の注目試合を"
                "理由つきでお届けしています。",
        "meta": {},
    }


def _jp_player_items() -> list:
    """
    日本人選手の名簿を、投手と野手に分けて並べる。

    notability_engine の JP_PLAYERS_MLB をそのまま使う。
    毎日の注目試合の判定に使っているのと同じ名簿なので、
    動画とサイトで人数が食い違うことがない。
    """
    pitchers = [p["name_jp"] for p in JP_PLAYERS_MLB
                if p.get("type") == "pitcher"]
    batters = [p["name_jp"] for p in JP_PLAYERS_MLB
               if p.get("type") == "batter"]

    def chunk(names, size=5):
        return ["、".join(names[i:i + size]) for i in range(0, len(names), size)]

    items = [(f"全部で{len(pitchers) + len(batters)}人",
              f"投手が{len(pitchers)}人、野手が{len(batters)}人です")]
    for i, line in enumerate(chunk(pitchers)):
        items.append((f"投手 {i + 1}" if i else "投手", line))
    for i, line in enumerate(chunk(batters)):
        items.append((f"野手 {i + 1}" if i else "野手", line))
    return items


def soccer_jp_items() -> list:
    """
    欧州でプレーする日本人選手の一覧を、名簿から組み立てる。

    JP_PLAYERS_SOCCER をそのまま使うので、選手リストを更新すれば
    動画の内容も自動で追従する。手で書き写すと、移籍のたびに
    どちらかが古くなる。

    リーグごとにまとめる。人数で機械的に4人ずつ区切ると
    「1〜4人目」という、視聴者にとって意味のない見出しになり、
    最後の画面が1人だけになることもある。リーグで分ければ
    見出しがそのまま「どこのリーグの話か」になる。

    クラブ名は日本語表記(team_jp)を使う。読み上げが英字を
    正しく読めないため。所属クラブは移籍市場で変わるので、
    市場が閉じた直後(例年9月上旬)に作り直すこと。
    """
    order = ["PL", "PD", "SA", "BL1", "FL1"]
    # 2部リーグは各国1〜3人しかいない。リーグごとに項目を立てると
    # 「1人だけの画面」ができてしまうので、ひとまとめにする。
    second_tier = ["ELC", "BL2"]

    by_league: dict = {}
    for p in JP_PLAYERS_SOCCER:
        by_league.setdefault(p["league"], []).append(p)

    # 名簿に想定外のリーグコードが増えても落とさない
    for code in by_league:
        if code not in order and code not in second_tier:
            order.append(code)

    def names(members):
        return "／".join(f"{p['name_jp']}（{p['team_jp']}）" for p in members)

    out = []
    for code in order:
        members = by_league.get(code)
        if not members:
            continue
        head = f"{SOCCER_LEAGUE_NAME_JP.get(code, code)}（{len(members)}人）"
        out.append((head, names(members)))

    lower = [(c, by_league[c]) for c in second_tier if by_league.get(c)]
    if lower:
        total = sum(len(m) for _, m in lower)
        body = "。".join(
            f"{SOCCER_LEAGUE_NAME_JP.get(c, c)}は{names(m)}" for c, m in lower
        )
        out.append((f"2部リーグ（{total}人）", body))
    return out


def load_soccer_preview(path: str = "data/soccer_preview.json") -> dict:
    """
    scripts/soccer_preview.py が書いた前情報。無ければ空。

    COLLESPO_SOCCER_PREVIEW で場所を差し替えられる。
    APIキーが手元に無い環境で、保存済みの応答を使って
    描画だけを確認するため。
    """
    p = pathlib.Path(os.environ.get("COLLESPO_SOCCER_PREVIEW", path))
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _jp_date(utc: str) -> str:
    """
    '2026-08-21T19:00:00Z' → '8月22日 4時'(日本時間)。

    欧州の試合は現地の夜に始まるので、日本時間では翌日の早朝になる。
    現地の日付のまま出すと「その日に見られる」と誤解されるため、
    日本時間へ直してから出す。
    """
    if not utc:
        return ""
    try:
        t = dt.datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""
    t = t.replace(tzinfo=dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=9))
    )
    return f"{t.month}月{t.day}日 {t.hour}時"


def _jp_day(date_str: str) -> str:
    """'2026-08-21' → '8月21日'。開幕日は現地の日付のまま扱う。"""
    if not date_str:
        return ""
    try:
        t = dt.datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{t.month}月{t.day}日"


def soccer_opening_items() -> list:
    """開幕日と、序盤の注目カードを並べる。"""
    data = load_soccer_preview()
    items = []

    # リーグ戦とCLを分けるのは、性格が違うからというより画面の都合。
    # 6件を1項目にすると1画面ぶんの分量になり、注目カードが同じ画面へ
    # はみ出す。2項目に割ると、開幕日だけで1画面になる。
    league_starts, cup_starts = [], []
    for c in data.get("competitions", []):
        # APIがまだ次シーズンへ切り替えていない競技会は飛ばす。
        # 飛ばさないと、既に終わったシーズンの開幕日を
        # 「これから始まります」として読み上げてしまう。
        if soccer_preview.is_stale(c):
            continue
        start = _jp_day((c.get("season") or {}).get("start"))
        if not start:
            continue
        name = c.get("name_jp", c.get("code"))
        (cup_starts if c.get("code") == "CL" else league_starts).append(
            (name, start)
        )
    if league_starts:
        items.append((
            "リーグ戦の開幕",
            "。".join(f"{n}は{d}" for n, d in league_starts),
        ))
    for name, day in cup_starts:
        items.append((name, f"{day}に始まります。火曜と水曜の開催なので、"
                            f"週末のリーグ戦と合わせるとほぼ毎日試合があります"))

    # 注目カードは競技会をまたいで点の高い順に並べる。
    # ただし1リーグ2件までにする。単純に点順で取ると、昨季順位が
    # 揃っているリーグや日本人選手の多いリーグだけで埋まり、
    # 「どのリーグを見るか」を決める材料にならない。
    picks = []
    for c in data.get("competitions", []):
        if soccer_preview.is_stale(c):
            continue
        for m in c.get("highlights", []):
            picks.append((c.get("name_jp", c.get("code")), m))
    picks.sort(key=lambda x: -x[1].get("score", 0))

    per_league: dict = {}
    limited = []
    for league, m in picks:
        if per_league.get(league, 0) >= 2:
            continue
        per_league[league] = per_league.get(league, 0) + 1
        limited.append((league, m))

    for league, m in limited[:6]:
        home = club_name_jp(m.get("home") or "")
        away = club_name_jp(m.get("away") or "")
        when = _jp_date(m.get("utc") or "")
        head = f"{home} 対 {away}"
        why = "、".join(m.get("reasons", [])) or "序盤の注目カード"
        body = f"{league}。{why}"
        if when:
            body += f"。日本時間{when}から"
        items.append((head, body))

    return items


def soccer_last_season_items() -> list:
    """昨季の最終順位から、リーグごとに上位と得点力を1行にまとめる。"""
    data = load_soccer_preview()
    items = []
    for c in data.get("competitions", []):
        if soccer_preview.is_stale(c):
            continue
        table = c.get("last_season") or []
        if not table:
            continue
        top = table[0]
        champ = club_name_jp(top.get("team") or "")
        parts = [f"優勝は{champ}"]
        if top.get("points") is not None:
            parts.append(f"勝ち点{top['points']}")
        if top.get("won") is not None and top.get("lost") is not None:
            parts.append(f"{top['won']}勝{top.get('draw', 0)}分{top['lost']}敗")

        rest = [club_name_jp(r.get("team") or "") for r in table[1:4]]
        if rest:
            parts.append("以下、" + "、".join(rest) + "と続きました")

        year = c.get("last_season_year")
        head = c.get("name_jp", c.get("code"))
        if year:
            head = f"{head}（{year}-{str(year + 1)[-2:]}）"
        items.append((head, "。".join(parts)))
    return items


def list_items(topic: str) -> list:
    """
    そのトピックで実際に表示する項目リスト。

    原稿と画面が必ず同じものを見るよう、加工はここだけで行う。
    最初は原稿側にだけ実測値を足してしまい、画面側は元のリストを
    見ていたため、項目数が食い違って描画が範囲外で落ちた。
    週次動画で一度直したのと同じ形の失敗なので、同じやり方で防ぐ。
    """
    spec = LIST_TOPICS[topic]

    # 名簿から組み立てるトピック。静的に書くと二重管理になり、
    # 選手が入れ替わったときに片方だけ古くなる。
    if spec.get("dynamic") == "jp_players":
        items = _jp_player_items()
    elif spec.get("dynamic") == "soccer_jp":
        items = soccer_jp_items()
    elif spec.get("dynamic") == "soccer_opening":
        items = soccer_opening_items()
    elif spec.get("dynamic") == "soccer_last_season":
        items = soccer_last_season_items()
    else:
        items = list(spec["items"])

    # 外部データが要るトピックで中身が空なら、ここで止める。
    # 見出しだけの動画を投稿してしまうより、作らない方がよい。
    if spec.get("dynamic", "").startswith("soccer_") and not items:
        raise SystemExit(
            f"[skip] {topic}: data/soccer_preview.json に必要なデータがありません。"
            "先に scripts/soccer_preview.py を実行してください"
        )

    # 球場の回は、その年の全試合から集計した実測値を先頭に置く。
    # 「打者有利とされる」で終わらせず、実際どうだったのかまで出す。
    # 集計データが無い環境では、何も足さずに従来どおりの内容になる。
    venue_en = spec.get("venue_en")
    if venue_en:
        desc = venue_stats.describe(venue_stats.load(), venue_en)
        if desc:
            items.insert(0, ("実際に何点入っているか", desc))
    return items


# 冒頭で読み上げる項目の数と、1項目あたりの長さの上限。
INTRO_PREVIEW_ITEMS = 4
INTRO_HEAD_MAX = 12

# 冒頭の読み上げの長さの上限(かな換算)。
# 話速1.38で約5秒。ここを超えると、本題に入る前に離脱される。
INTRO_BUDGET = 50


def _spoken_len(text: str) -> int:
    """読み上げの長さの目安。句読点と拗音は数えない。"""
    t = re.sub(r"[、。！？\s]", "", text)
    return len(re.sub(r"[ァィゥェォャュョぁぃぅぇぉゃゅょ]", "", t))


def _first_sentence(text: str) -> str:
    head = text.split("。")[0].strip()
    return head + "。" if head else text


def _intro_text(topic: str, items: list) -> str:
    """
    冒頭の読み上げを組む。「問い → 何を扱うか」の順。

    これまでは「中継やネットで見かける成績の数字。よく出てくるものだけ、
    意味と目安をまとめます」のように、一般論から入っていた。
    直近28日でショートの40.6%が途中でスワイプされていて、
    ここに一般論を置く余裕は無い。

    先頭に置く問い(hook)は、サムネイル用に既に書いてあるもの。
    「OPS って何の数字？」のように、検索して来る人がまさに知りたいことが
    そのまま入っている。読み上げでは使っていなかったので、ここでも使う。

    続けて扱う項目を並べる。ただしこれが効くのは、項目名が
    用語のように短いトピックだけ。開幕カードの回のように項目が
    「バイエルン 対 シュツットガルト」だと、並べた瞬間に冒頭が
    6秒を超えて逆効果になる。長さで選び分け、収まらなければ
    元の説明文の1文目に戻す。
    """
    spec = LIST_TOPICS[topic]
    hook = (spec.get("hook") or "").strip()
    if hook and not hook.endswith(("？", "。", "！")):
        hook += "。"

    # 問いが説明文の言い換えでしかない場合は重ねない
    # (collespo_guideの「毎日19時に届きます」など)
    if hook and hook.rstrip("。？！") in spec["intro"]:
        hook = ""

    # 問いに出てくる語が項目にもある場合(「OPS って何の数字？」と項目「OPS」)、
    # 一度それを省いてみたが、いちばん肝心な項目が一覧から消えるだけだった。
    # 重なっていても自然に読めるので、そのまま並べる。
    heads = []
    for h, _ in items:
        # 「xG（期待ゴール）」→「xG」。読み上げでは括弧の中まで要らない。
        head = re.split(r"[（(]", h)[0].strip()
        # 「投手 2」は画面を分けるための連番で、内容の区別ではない。
        # 読み上げると「投手、投手 2」と重なって聞こえる。
        head = re.sub(r"\s*\d+$", "", head).strip()
        if head and head not in heads:
            heads.append(head)
        if len(heads) >= INTRO_PREVIEW_ITEMS:
            break

    candidates = []
    if heads and len(items) >= 3 and all(len(h) <= INTRO_HEAD_MAX for h in heads):
        more = "ほか" if len(items) > INTRO_PREVIEW_ITEMS else ""
        candidates.append(f"{hook}{'、'.join(heads)}{more}、まとめて見ていきます。")
    if hook:
        candidates.append(f"{hook}{_first_sentence(spec['intro'])}")
    candidates.append(spec["intro"])

    for c in candidates:
        if _spoken_len(c) <= INTRO_BUDGET:
            return c
    # どれも収まらなければ、いちばん短いものを使う
    return min(candidates, key=_spoken_len)


def _narration_list(topic: str) -> dict:
    """LIST_TOPICS のデータから原稿を組む。1画面に2項目ずつ。"""
    spec = LIST_TOPICS[topic]
    items = list_items(topic)
    if spec.get("venue_en") and items and items[0][0] == "実際に何点入っているか":
        print(f"[info] 実測値を追加: {items[0][1]}")
    segments = [{"kind": "intro", "text": _intro_text(topic, items),
                 "meta": {}}]

    # 球団の回は、どこにあるかを先に見せる。
    #
    # 「カリフォルニア州アナハイム」と読み上げても、アメリカの地理を
    # 知らないと像を結ばない。西の端なのか東の端なのかが先に分かると、
    # そのあとの数字も置き場所ができる。
    m = spec.get("map") or {}
    if m.get("lat") is not None:
        near = "、".join(x["name"] for x in (m.get("near") or [])[:4])
        parts = ["まず場所から。アメリカ、MLBは30球団。"]
        if m.get("division"):
            parts.append(f"{m['division']}。")
        if near:
            parts.append(f"同じ地区には{near}。")
        parts.append(f"{spec.get('where', '')}。ここが{spec['label']}の本拠地です。")
        segments.insert(1, {"kind": "map", "text": "".join(parts),
                            "meta": {"topic": topic}})
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        segments.append({
            "kind": "list",
            "text": "".join(f"{t.replace('｜', '、')}。{b}。" for t, b in chunk),
            "meta": {"topic": topic, "start": i, "count": len(chunk)},
        })
    # 数字のあとに、人を出す。
    #
    # 創設年・収容人数・地区が並ぶだけだと、その球団が何者なのかが
    # 残らない。殿堂入りと、いま実際に打って抑えている選手を1画面ずつ。
    # テンポを落とさないよう、それぞれ1画面に収める。
    legends = (spec.get("legends") or [])[:3]
    said = [s for s in (_say(x["name"]) for x in legends) if s]
    if legends and said:
        segments.append({
            "kind": "people",
            "text": "この球団の殿堂入りは、" + "、".join(said) + "。",
            "meta": {"topic": topic, "group": "legends",
                     "heading": "殿堂入り"},
        })
    stars = (spec.get("stars") or [])[:2]
    parts = [f"{_say(x['name'])}が{x.get('why', '')}。"
             for x in stars if _say(x["name"])]
    if parts:
        segments.append({
            "kind": "people",
            "text": "いまの中心は、" + "".join(parts),
            "meta": {"topic": topic, "group": "stars",
                     "heading": "今シーズンの中心"},
        })

    segments.append(_outro_segment())
    return {"label": spec["label"], "segments": segments}


def _say(name: str) -> str:
    """読み上げ用の名前。読みが分からなければ空を返す。

    英字のまま渡すと1文字ずつ読まれる。「リッキー・ヘンダーソン、
    ウィリアムズ、Ginn」のように1つ混じるだけで、その並びが崩れる。
    読めないものは読み上げから外す(画面には正しい綴りで出す)。
    """
    try:
        from generate_narration import speech_name
        said = speech_name(name)
    except Exception:  # noqa: BLE001
        return ""
    return "" if any(c.isascii() and c.isalpha() for c in said) else said


def _narration_venue() -> dict:
    items = venue_items()
    segments = [{
        "kind": "intro",
        "text": "野球は、球場によって試合の性格が変わります。"
                "点が入りやすい球場と、入りにくい球場を見ていきましょう。",
        "meta": {},
    }]
    # 1画面に2球場ずつ。1つずつだと画面数が増えすぎて冗長になる
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        # 見出しの「｜」は画面用の区切りで、読み上げには向かない。
        # 音声側では読点に置き換える。
        text = "".join(f"{jp.replace('｜', '、')}。{note}。" for jp, note in chunk)
        segments.append({
            "kind": "venue",
            "text": text,
            "meta": {"start": i, "count": len(chunk)},
        })
    segments.append(_outro_segment())
    return {"label": "球場でこんなに変わる", "segments": segments}


def _narration_rivalry() -> dict:
    items = rivalry_items()
    segments = [{
        "kind": "intro",
        "text": "MLBには、勝ち負け以上の意味を持つカードがあります。"
                "なぜ因縁の対決と呼ばれるのか、由来から見ていきましょう。",
        "meta": {},
    }]
    for i, it in enumerate(items):
        segments.append({
            "kind": "rivalry",
            "text": f"{it['title']}。{it['note']}。",
            "meta": {"index": i},
        })
    segments.append(_outro_segment())
    return {"label": "MLB 伝統の一戦", "segments": segments}


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------

def base(progress):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # 背景はANIM_ENDで動きを止める。動き続けると全フレームが微妙に異なり、
    # 描画結果を使い回せなくなって生成時間がそのまま伸びる。
    off = int(min(progress, ANIM_END) * 240)
    for i in range(-2, 6):
        x = i * 340 + off
        d.polygon([(x, H), (x + 150, H), (x + 400, 0), (x + 250, 0)],
                  fill=(14, 18, 26))
    d.rectangle([0, H - 22, W, H], fill=ACCENT)
    return im, d


def team_color(spec: dict):
    """
    その球団の色。暗い背景で読める明るさに持ち上げて返す。

    公式の色をそのまま使うと、濃紺(#0C2C56)や濃緑(#003831)、
    濃茶(#2F241D)が背景(#0B0E14)に沈んで見えない。
    色みは保ったまま明るさだけ上げる。

    色が無い球団や、球団以外の回では既定のオレンジに落とす。
    """
    import colorsys
    hexv = (spec or {}).get("color") or ""
    if not hexv.startswith("#") or len(hexv) != 7:
        return ACCENT
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v = max(v, 0.72)
    s = min(s, 0.78)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def render_map(p, spec):
    """
    その球団がどこにあるかを、寄りながら見せる。

    なぜ地図なのか:
      「カリフォルニア州アナハイム」と読み上げても、アメリカの地理を
      知らないと像を結ばない。日本の視聴者には州の名前より、
      西の端なのか東の端なのかの方が早い。

      地図の画像は使わない。海岸線を粗い多角形で持っているだけなので、
      出どころを確かめる必要も、外部への通信も無い。

    3段階に切ってある:
      0.00-0.30  国全体。30球場が散らばっているのが見える
      0.30-0.65  その地区へ。同地区の5球団が収まる範囲まで
      0.65-1.00  その球場へ

      連続で寄せると、序盤で中心が動いた時点で端の球団
      (シアトル、マイアミ)が画面の外へ出てしまう。実際そうなった。
      全体を見せる区間は、中心も倍率も動かさない。
    """
    im, d = base(min(p, ANIM_END))
    col = team_color(spec)
    m = spec.get("map") or {}
    lat, lon = m.get("lat"), m.get("lon")
    if lat is None:
        return im

    country = ((usmap.LAT_RANGE[0] + usmap.LAT_RANGE[1]) / 2,
               (usmap.LON_RANGE[0] + usmap.LON_RANGE[1]) / 2)
    near = m.get("near") or []
    # 地区の真ん中。5球団の平均。
    if near:
        div_c = ((lat + sum(n["lat"] for n in near)) / (len(near) + 1),
                 (lon + sum(n["lon"] for n in near)) / (len(near) + 1))
    else:
        div_c = (lat, lon)

    if p < 0.30:
        center, zoom, stage = country, 1.0, 0
    elif p < 0.65:
        e = ease_out((p - 0.30) / 0.35)
        center = (country[0] + (div_c[0] - country[0]) * e,
                  country[1] + (div_c[1] - country[1]) * e)
        zoom, stage = 1.0 + e * 1.1, 1
    else:
        e = ease_out(min(1.0, (p - 0.65) / 0.30))
        center = (div_c[0] + (lat - div_c[0]) * e,
                  div_c[1] + (lon - div_c[1]) * e)
        zoom, stage = 2.1 + e * 2.2, 2

    # 州境。Natural Earth から取ってコミットしてあるので通信は無い。
    # 州の形があると、寄っても「どのあたりか」の手がかりが残る。
    polys = usmap.state_polygons(W, H, center, zoom)
    edge = 40 + int(26 * min(1.0, (zoom - 1) / 3.5))
    for poly in polys:
        d.polygon(poly, fill=(16, 21, 30), outline=(edge, edge + 8, edge + 20))
    if not polys:   # データが無い日は手書きの輪郭に落ちる
        d.polygon(usmap.outline_points(W, H, center, zoom),
                  fill=(16, 21, 30), outline=(60, 70, 90))

    def put(la, lo, r, fill, label=""):
        x, y = usmap.project(la, lo, W, H, center, zoom)
        if not (-150 < x < W + 150 and -150 < y < H + 150):
            return
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
        if label:
            d.text((x + r + 8, y - 16), label, font=font(30), fill=DIM)

    # 全体のときは30球場を打つ。「MLBは30球団」と言う場所なので、
    # 数がそのまま画面に出ている方がよい。
    if stage == 0:
        for la, lo in (m.get("all") or []):
            put(la, lo, 7, (58, 70, 92))
    else:
        for n in near:
            put(n["lat"], n["lon"], 7 + 4 * (stage - 1), (58, 70, 92),
                n["abbr"] if stage >= 1 else "")

    x, y = usmap.project(lat, lon, W, H, center, zoom)
    for i in range(3):
        rr = 24 + i * 24 + zoom * 6
        d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=col, width=2)
    d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col)

    if stage == 0:
        big, small = "アメリカ", "MLBは30球団"
    elif stage == 1:
        big, small = m.get("division", ""), "同じ地区の4球団"
    else:
        big, small = (spec.get("where") or m.get("city", "")), spec.get("label", "")
    size = next((s for s in (84, 72, 60, 50)
                 if d.textlength(big, font=font(s)) <= W - 140), 50)
    d.text((70, 150), big, font=font(size), fill=col)
    if small:
        d.text((74, 260), small, font=font(40), fill=DIM)
    return im


def abbr_badge(d, x, y, abbr, color, w=250, h=130):
    col = color or (60, 66, 80)
    if isinstance(col, str) and col.startswith("#"):
        col = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
    lum = (0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]) / 255
    fg = (17, 17, 17) if lum > 0.6 else (255, 255, 255)
    d.rounded_rectangle([x, y, x + w, y + h], 18, fill=col)
    f = font(72)
    d.text((x + (w - d.textlength(abbr, font=f)) / 2, y + 24), abbr, font=f, fill=fg)


# LIST_TOPICS を使わない(専用の構成を持つ)トピックのフック。
# サムネイルの文言と揃える。サムネで見た問いと1枚目が違うと、
# 開いた瞬間に別物に見えてしまう。
EXTRA_HOOKS = {
    "mlb_abbr": "LAD って どこ？",
    "mlb_venue": "点が入る球場、入らない球場",
    "mlb_rivalry": "なぜ因縁の対決？",
}


def hook_for(topic: str, label: str) -> str:
    spec = LIST_TOPICS.get(topic) or {}
    return spec.get("hook") or EXTRA_HOOKS.get(topic) or label


def render_intro(p, label, hook=None):
    """
    1枚目。ここで見るかどうかが決まる。

    以前は「コレスポ」の名乗りから始めていたが、日次ショートで同じ作りを
    やめたところ、平均視聴率が15.5%から平均69%へ上がった(実測)。
    視聴者にとって名乗りは情報がゼロなので、その日いちばん引きのある
    一言を先に出し、ブランドは下に小さく置く。
    """
    im, d = base(p)
    hook = hook or label
    e = ease_out(min(1.0, p * 2.6))
    slide = int((1 - e) * 70)

    # 1行に収まる最大のサイズを実測で選ぶ
    max_w = W - 160
    size = 64
    for s in (116, 104, 92, 80, 72, 64):
        if d.textlength(hook, font=font(s)) <= max_w:
            size = s
            break
    lines = _wrap(d, hook, font(size), max_w)[:3]

    line_h = int(size * 1.24)
    y = max(420, (H - (len(lines) * line_h + 220)) // 2 - 60)
    for line in lines:
        d.text((80, y + slide), line, font=font(size), fill=ACCENT)
        y += line_h

    if p > 0.14:
        d.text((80, y + 50), label, font=font(56), fill=TEXT)

    d.text((80, H - 170), "コレスポ　collespo.com", font=font(38), fill=DIM)
    return im


def render_division(p, code, teams):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 210), MLB_DIVISION_NAME_JP[code], font=font(76), fill=ACCENT)

    # 「今どこまで来たか」を出す。6地区を順に流すだけの動画なので、
    # 残りが見えないと途中で離脱されやすい。
    idx = DIVISION_ORDER.index(code) + 1
    f = font(40)
    prog = f"{idx} / {len(DIVISION_ORDER)}"
    d.text((W - 70 - d.textlength(prog, font=f), 84), prog, font=f, fill=DIM)

    y = 420
    for i, (abbr, name_jp, color) in enumerate(teams):
        appear = 0.05 + i * 0.06
        if p < appear:
            continue
        # 行ごとのスライドインは ANIM_END までに終わらせる。
        # そこを過ぎたフレームは描き直さず使い回すため、間に合わないと
        # 途中の位置で固まってしまう。
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 120)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 150], 20, fill=SURF)
        abbr_badge(d, 90 - dx, y + 10, abbr, color)
        d.text((370 - dx, y + 36), name_jp, font=font(58), fill=TEXT)
        y += 250

    # ショートは切り抜き・スクショで出回るので、どの画面にも出典を残す
    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def fit(d, text: str, max_w: int, sizes) -> int:
    """その幅に収まる、いちばん大きい文字の大きさ。

    同じことを画面ごとにその場で書いていた。選手名は長さの幅が
    大きい(「Ben Rice」と「Cam Schlittler」)ので、収まらないと
    はみ出す。1か所にまとめる。
    """
    for s in sizes:
        if d.textlength(text, font=font(s)) <= max_w:
            return s
    return sizes[-1]


def render_people(p, rows, heading, sub=""):
    """殿堂入り、または今シーズンの中心。名前と成績を並べるだけ。

    数字ばかりの画面が続くと、その球団が何者なのかが残らない。
    人の名前が1画面あるだけで、あとの数字に置き場所ができる。
    尺は増やさないので、1画面に3人まで。
    """
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    d.text((70, 190), heading, font=font(64), fill=ACCENT)
    if sub:
        d.text((74, 276), sub, font=font(32), fill=DIM)

    y = 380
    for i, r in enumerate(rows[:3]):
        appear = 0.06 + i * 0.08
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 120)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + 190], 20, fill=SURF)

        name = r.get("name", "")
        d.text((100 - dx, y + 26), name,
               font=font(fit(d, name, W - 260, (56, 50, 44, 38))), fill=TEXT)
        line = r.get("line", "")
        if line:
            d.text((100 - dx, y + 104), line,
                   font=font(fit(d, line, W - 260, (38, 34, 30, 26))),
                   fill=DIM)
        # 殿堂入りの年、または「今季チーム最多本塁打」のような選んだ理由。
        # なぜこの人なのかを画面にも置いておく。
        tag = r.get("hof_year") and f"殿堂{r['hof_year']}年" or r.get("why", "")
        if tag:
            tw = d.textlength(tag, font=font(30))
            d.text((W - 100 - dx - tw, y + 32), tag, font=font(30),
                   fill=ACCENT)
        y += 214

    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def _wrap(d, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=fnt) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def render_list(p, items, start, count, page, pages, heading):
    """
    「見出し + 説明」を2件ずつ並べる共通の画面。

    資産動画のほとんどはこの形で足りるので、トピックを増やすときに
    描画を書き足さずに済むよう、1つの関数にまとめてある。
    """
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    f = font(40)
    prog = f"{page} / {pages}"
    d.text((W - 70 - d.textlength(prog, font=f), 84), prog, font=f, fill=DIM)

    # 見出しは長いものがあるので、収まるサイズを実測で選ぶ
    hs = 72
    for s in (72, 64, 56, 48):
        if d.textlength(heading, font=font(s)) <= W - 140:
            hs = s
            break
    d.text((70, 210), heading, font=font(hs), fill=ACCENT)

    # カードの高さは中身に合わせる。固定にすると、説明が2行のトピックで
    # カードの下半分が丸ごと空き、間延びして見える。
    # 先に全カードの高さを出し、塊が縦の中央に来るよう開始位置を決める。
    heights = []
    for i in range(count):
        note = items[start + i][1]
        n = len(_wrap(d, note, font(42), W - 220)[:6])
        heights.append(130 + n * 62 + 34)
    # 見出しのすぐ下から積む。中央に寄せると、項目が短いトピックで
    # 見出しとカードの間が大きく空いてしまう。
    gap = 46
    y = 430

    for i in range(count):
        jp, note = items[start + i]
        appear = 0.06 + i * 0.10
        if p < appear:
            continue
        e = ease_out(min(1.0, max(0.0, (p - appear) * 9)))
        dx = int((1 - e) * 120)
        d.rounded_rectangle([60 - dx, y, W - 60 - dx, y + heights[i]], 22, fill=SURF)
        # 見出しは「球場名｜球団名」のように長くなることがあるので、
        # 収まるサイズを実測で選ぶ(固定だと右端で切れる)
        hs = 40
        for s in (56, 50, 46, 42, 40):
            if d.textlength(jp, font=font(s)) <= W - 240:
                hs = s
                break
        d.text((100 - dx, y + 34), jp, font=font(hs), fill=JP)
        yy = y + 130
        for line in _wrap(d, note, font(42), W - 220)[:6]:
            d.text((100 - dx, yy), line, font=font(42), fill=TEXT)
            yy += 62
        y += heights[i] + gap

    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def render_rivalry(p, item, index, total):
    im, d = base(p)
    d.text((70, 70), "コレスポ", font=font(46), fill=ACCENT)
    f = font(40)
    prog = f"{index + 1} / {total}"
    d.text((W - 70 - d.textlength(prog, font=f), 84), prog, font=f, fill=DIM)

    e = ease_out(min(1.0, p * 3))
    dx = int((1 - e) * 130)

    # 両球団のカラーを帯で示す。ロゴは使わず色だけを借りる
    for i, col in enumerate(item["colors"][:2]):
        c = col or "#3C4250"
        if isinstance(c, str) and c.startswith("#"):
            c = tuple(int(c[j:j + 2], 16) for j in (1, 3, 5))
        d.rounded_rectangle([70 - dx + i * 130, 210, 190 - dx + i * 130, 290], 12, fill=c)

    d.text((70 - dx, 340), item["kind"], font=font(44), fill=JP)

    y = 430
    for line in _wrap(d, item["title"], font(84), W - 160)[:3]:
        d.text((70 - dx, y), line, font=font(84), fill=ACCENT)
        y += 104

    if p > 0.14:
        y += 50
        d.rounded_rectangle([60, y - 30, W - 60, y + 350], 22, fill=SURF)
        yy = y + 10
        for line in _wrap(d, item["note"], font(46), W - 200)[:6]:
            d.text((100, yy), line, font=font(46), fill=TEXT)
            yy += 68

    d.text((70, H - 130), "collespo.com", font=font(38), fill=DIM)
    return im


def render_outro(p):
    im, d = base(p)
    d.text((80, 640), "コレスポ", font=font(120), fill=ACCENT)
    d.text((80, 800), "collespo.com", font=font(58), fill=TEXT)
    if p > 0.12:
        d.text((80, 910), "毎日19時 更新", font=font(46), fill=DIM)
    # VOICEVOXの利用規約で、動画内または説明欄へのクレジット表記が
    # 求められているため、アウトロに必ず表示する
    d.text((80, 1150), "音声: VOICEVOX:ずんだもん", font=font(40), fill=DIM)
    d.text((80, 1220), "データ: MLB Stats API", font=font(40), fill=DIM)
    return im


# ---------------------------------------------------------------------------
# 尺と音声
# ---------------------------------------------------------------------------

def plan_durations(segs: list) -> list:
    return [max(MIN_DURATION.get(s.get("kind") or "division", 6.0),
                float(s.get("duration") or 0), 3.0)
            for s in segs]


def build_narration_track(segs, durations, out_dir):
    """
    各セグメントの音声を、その区間の長さまで無音で埋めてから連結する。

    画面は下限秒数で表示されるので、読み上げより画面の方が長い。
    音声を詰めて繋ぐと差が積み上がって画面と音がずれ、さらに音声トラックが
    映像より短くなるため ffmpeg の -shortest が出力を音声の長さで
    打ち切ってしまう(週次動画で実際に起きた)。
    """
    if not any(s.get("file") for s in segs):
        return None

    params = None
    for s in segs:
        if s.get("file") and pathlib.Path(s["file"]).exists():
            with wave.open(s["file"], "rb") as w:
                params = w.getparams()
            break
    if params is None:
        return None

    pad_dir = out_dir / "silence"
    pad_dir.mkdir(parents=True, exist_ok=True)

    parts = []
    for i, (seg, dur) in enumerate(zip(segs, durations)):
        spoken = 0.0
        path = seg.get("file")
        if path and pathlib.Path(path).exists():
            with wave.open(path, "rb") as w:
                spoken = w.getnframes() / float(w.getframerate())
            parts.append(pathlib.Path(path).resolve())
        gap = dur - spoken
        if gap <= 0.02:
            continue
        sil = pad_dir / f"pad_{i:03d}.wav"
        with wave.open(str(sil), "wb") as w:
            w.setnchannels(params.nchannels)
            w.setsampwidth(params.sampwidth)
            w.setframerate(params.framerate)
            frames = int(gap * params.framerate)
            w.writeframes(b"\x00" * (frames * params.nchannels * params.sampwidth))
        parts.append(sil.resolve())

    lst = out_dir / "audio_list.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    audio_path = out_dir / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(audio_path)],
                   check=True, capture_output=True)
    return audio_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="mlb_abbr")
    parser.add_argument("--narration-out", default=None,
                        help="指定すると原稿だけ書き出して終了する")
    parser.add_argument("--audio-dir", default="build/asset_audio")
    parser.add_argument("--out", default="build/asset")
    args = parser.parse_args()

    narration = build_narration(args.topic)

    if args.narration_out:
        p = pathlib.Path(args.narration_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(narration, ensure_ascii=False), encoding="utf-8")
        chars = sum(len(s["text"]) for s in narration["segments"])
        print(f"[info] 原稿を書き出しました: {p} "
              f"({len(narration['segments'])}セグメント / 計{chars}文字)")
        return

    by_div = teams_by_division()
    venues = venue_items()
    rivalries = rivalry_items()
    label = narration["label"]

    manifest = pathlib.Path(args.audio_dir) / "manifest.json"
    if manifest.exists():
        segs = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
    else:
        print(f"[warn] 音声manifestが見つかりません: {manifest.resolve()}")
        print("       音声なし・固定秒数で作ります")
        segs = [{"kind": s["kind"], "file": None, "duration": 0.0,
                 "meta": s["meta"]} for s in narration["segments"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"collespo_asset_{args.topic}.mp4"

    durations = plan_durations(segs)
    audio_path = build_narration_track(segs, durations, out_dir)

    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-"]
    if audio_path:
        cmd += ["-i", str(audio_path)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [str(video_path)]

    # stderrはパイプではなくファイルへ逃がす。
    # パイプのままだと、こちらが読まない限りバッファが埋まって止まる。
    err_path = out_dir / "ffmpeg_error.log"
    err_file = open(err_path, "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=err_file)
    total = 0
    try:
        for seg, dur in zip(segs, durations):
            n = int(dur * FPS)
            kind, meta = seg.get("kind"), seg.get("meta") or {}
            cached = None
            for k in range(n):
                pp = k / max(1, n - 1)
                # 地図は最後まで動く。他の画面は途中で絵が止まるので
                # 描き直さずに使い回すが、ここでそれをやると寄るのが
                # 止まってしまう。
                if kind != "map" and pp > ANIM_END and cached is not None:
                    proc.stdin.write(cached)
                    total += 1
                    continue
                if kind == "intro":
                    im = render_intro(pp, label, hook_for(args.topic, label))
                elif kind == "division":
                    code = DIVISION_ORDER[meta.get("division_index", 0)]
                    im = render_division(pp, code, by_div[code])
                elif kind == "venue":
                    im = render_list(pp, venues, meta.get("start", 0),
                                     meta.get("count", 1),
                                     meta.get("start", 0) // 2 + 1,
                                     (len(venues) + 1) // 2,
                                     "球場でこんなに変わる")
                elif kind == "map":
                    im = render_map(pp, LIST_TOPICS[meta.get("topic",
                                                             args.topic)])
                elif kind == "list":
                    t = meta.get("topic", args.topic)
                    # 原稿と同じ関数で組み立てる。別々に作ると項目数がずれる
                    items = list_items(t)
                    # heading は画面上部の見出し。省略されたら label を使う
                    # (トピックを足すたびに書き忘れると、生成の途中で落ちる)
                    ts = LIST_TOPICS[t]
                    im = render_list(pp, items, meta.get("start", 0),
                                     meta.get("count", 1),
                                     meta.get("start", 0) // 2 + 1,
                                     (len(items) + 1) // 2,
                                     ts.get("heading") or ts.get("label", ""))
                elif kind == "people":
                    ts = LIST_TOPICS[meta.get("topic", args.topic)]
                    rows = ts.get(meta.get("group", "legends")) or []
                    im = render_people(pp, rows,
                                       meta.get("heading", ""),
                                       ts.get("label", ""))
                elif kind == "rivalry":
                    idx = meta.get("index", 0)
                    im = render_rivalry(pp, rivalries[idx], idx, len(rivalries))
                else:
                    im = render_outro(pp)
                cached = im.tobytes()
                proc.stdin.write(cached)
                total += 1
            print(f"[info] {kind}: {dur:.1f}秒")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()
        err_file.close()

    if proc.returncode != 0:
        print(f"[error] 書き出しに失敗:\n"
              f"{err_path.read_text(encoding='utf-8', errors='ignore')[-1500:]}",
              file=sys.stderr)
        sys.exit(1)

    secs = total / FPS
    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"[info] 資産動画を生成しました: {video_path} "
          f"({size_mb:.1f}MB, {secs:.0f}秒)")


if __name__ == "__main__":
    main()

