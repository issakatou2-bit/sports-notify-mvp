#!/usr/bin/env python3
"""
クラブ名の照合を、football-data.org が返す「正式名称」の形で検証する。

    python3 scripts/test_club_match.py

なぜ要るか:
  名簿(JP_PLAYERS_SOCCER)の team_en は人が読むための表記で、
  APIが返す name は正式名称。以前は両者を完全一致で突き合わせており、
  このテストを書いた時点では20クラブ中1つしか当たっていなかった。
  開幕前は試合が0件で、疎通確認では表面化しない類の不具合なので、
  実データが流れる前に固定しておく。

APIキーが無くても走る。ここで使う名称は実レスポンスではないが、
確かめたいのは「FCやウムラウトが付いても当たること」と
「別クラブに誤爆しないこと」の2点なので、それには足りる。
名簿を更新したら、CASESにも1行足すこと。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import notability_engine as ne  # noqa: E402
from checks_report import check, note, section, done, passed, fail  # noqa: E402

# (APIが返しうる正式名称, 期待する日本人選手)
CASES = [
    ("Liverpool FC", ["遠藤航"]),
    ("Brighton & Hove Albion FC", ["三笘薫"]),
    ("Crystal Palace FC", ["鎌田大地", "冨安健洋"]),
    # 2026年9月9日に足した選手のクラブ。
    # クラブ名は football-data.org が実際に返した表記そのまま。
    ("Lille OSC", ["上田綺世"]),
    ("Cagliari Calcio", ["菅原由勢"]),
    ("Burnley FC", ["旗手怜央"]),
    ("Southampton FC", ["松木玖生"]),
    ("Queens Park Rangers FC", ["斉藤光毅"]),
    ("Blackburn Rovers FC", ["森下龍矢", "大橋祐紀"]),
    ("Bolton Wanderers FC", ["伊藤敦樹"]),
    ("Birmingham City FC", ["藤本寛也", "岩田智輝"]),
    ("Bristol City FC", ["平川怜"]),
    ("Tottenham Hotspur FC", ["高井幸大"]),
    ("Leeds United FC", ["田中碧"]),
    ("Coventry City FC", ["坂元達裕"]),
    ("Ipswich Town FC", ["前田大然"]),
    ("Hull City AFC", ["守田英正"]),
    ("Real Sociedad de Fútbol", ["久保建英"]),
    ("Valencia CF", ["佐藤龍之介"]),
    ("FC Bayern München", ["伊藤洋輝"]),
    ("TSG 1899 Hoffenheim", ["町田浩樹"]),
    ("SC Freiburg", ["鈴木唯人", "後藤啓介", "山本理仁"]),
    ("Eintracht Frankfurt", ["堂安律", "小杉啓太"]),
    ("1. FSV Mainz 05", ["佐野海舟", "川﨑颯太"]),
    ("Borussia Mönchengladbach",
     ["町野修斗", "宇野禅斗", "橋岡大樹", "板倉滉"]),
    ("FC Schalke 04", ["田中聡"]),
    ("Parma Calcio 1913", ["鈴木ザイオン"]),
    ("AS Monaco FC", ["南野拓実"]),
    ("Le Havre AC", ["瀬古歩夢", "中村草太", "水多海斗"]),
]

# 日本人選手が居ないクラブ。1人でも当たったら誤爆。
#
# 2026年9月9日、移籍市場ぶん16人を名簿へ足したので、ここからも
# バーンリー(旗手怜央)とリール(上田綺世)を外した。
# **「居ない」は名簿の写しではなく、その時点の事実。**
# 名簿を増やしたら、ここも一緒に見直す。
NEGATIVE = [
    "Arsenal FC", "Manchester City FC", "Manchester United FC", "Chelsea FC",
    "Newcastle United FC", "Aston Villa FC", "Everton FC", "Fulham FC",
    "West Ham United FC", "Nottingham Forest FC", "AFC Bournemouth",
    "Wolverhampton Wanderers FC", "Brentford FC",
    "Real Madrid CF", "FC Barcelona", "Club Atlético de Madrid",
    "Athletic Club", "Villarreal CF", "Real Betis Balompié", "Sevilla FC",
    "Borussia Dortmund", "Bayer 04 Leverkusen", "RB Leipzig",
    "VfB Stuttgart", "VfL Wolfsburg", "SV Werder Bremen", "FC Augsburg",
    "1. FC Union Berlin", "1. FC Köln", "FC St. Pauli",
    "Juventus FC", "AC Milan", "FC Internazionale Milano", "SSC Napoli",
    "AS Roma", "SS Lazio", "Atalanta BC", "ACF Fiorentina", "Bologna FC 1909",
    "Paris Saint-Germain FC", "Olympique de Marseille", "Olympique Lyonnais",
    "Stade Rennais FC 1901", "OGC Nice", "RC Lens",
    "FC Nantes", "Toulouse FC", "Stade Brestois 29",
]

section("クラブ名から日本人選手を引く")
missed = 0
for api_name, expected in CASES:
    got = [p["name_jp"] for p in ne.jp_players_for_club(api_name)]
    if not check(api_name, sorted(got), sorted(expected)):
        missed += 1

section("名簿にいないクラブで誤爆しない")
for api_name in NEGATIVE:
    check("誤爆しない: " + api_name,
          [p["name_jp"] for p in ne.jp_players_for_club(api_name)], [])

# 完全一致に戻したら何件当たるか。この差が、この照合が要る理由そのもの。
# **合わなかったときだけ**、どれだけ落ちたかを添える。
if missed:
    old = sum(1 for n, _ in CASES
              if n in {p["team_en"] for p in ne.JP_PLAYERS_SOCCER})
    note("正規化照合での的中 %d/%d（完全一致なら %d/%d）"
         % (len(CASES) - missed, len(CASES), old, len(CASES)))

# 名簿の全員がいずれかのケースで拾えているか
covered = set()
for api_name, _ in CASES:
    covered.update(p["name_jp"] for p in ne.jp_players_for_club(api_name))
check("名簿の全員がどこかのクラブで拾える",
      [p["name_jp"] for p in ne.JP_PLAYERS_SOCCER
       if p["name_jp"] not in covered], [])


# ---------------------------------------------------------------------------
# 日本語表記(club_name_jp)
# ---------------------------------------------------------------------------
# 取り違えが起きやすい組み合わせを重点的に見る。
# 特に "AC Milan" と "FC Internazionale Milano" は、
# 短いキー("milan")を先に見ると両方ミランになる。

NAME_CASES = [
    ("FC Internazionale Milano", "インテル"),
    ("AC Milan", "ACミラン"),
    ("Real Madrid CF", "レアル・マドリード"),
    ("Club Atlético de Madrid", "アトレティコ・マドリード"),
    ("Real Sociedad de Fútbol", "レアル・ソシエダ"),
    ("Real Betis Balompié", "レアル・ベティス"),
    ("Athletic Club", "アスレティック・ビルバオ"),
    ("Paris Saint-Germain FC", "パリ・サンジェルマン"),
    ("Paris FC", "パリFC"),
    ("Manchester City FC", "マンチェスター・シティ"),
    ("Manchester United FC", "マンチェスター・ユナイテッド"),
    ("Bayer 04 Leverkusen", "レバークーゼン"),
    ("FC Bayern München", "バイエルン"),
    ("Borussia Dortmund", "ドルトムント"),
    ("Borussia Mönchengladbach", "ボルシアMG"),
    ("1. FC Köln", "ケルン"),
    ("Olympique Lyonnais", "リヨン"),
    ("Olympique de Marseille", "マルセイユ"),
    ("LOSC Lille", "リール"),
    ("Stade Rennais FC 1901", "レンヌ"),
    ("Le Havre AC", "ル・アーブル"),
    ("AS Roma", "ローマ"),
    ("SV Werder Bremen", "ブレーメン"),
    ("1. FC Union Berlin", "ウニオン・ベルリン"),
    ("FC St. Pauli", "ザンクトパウリ"),
    ("Hamburger SV", "ハンブルク"),

    # 実データ(data/soccer_preview.json)で実際に取り違えていた組。
    # 短いキーだと、長い正式名称の一部として飲み込まれる。
    ("FC Barcelona", "バルセロナ"),
    ("RCD Espanyol de Barcelona", "エスパニョール"),
    ("RC Deportivo La Coruña", "デポルティボ"),
    ("Deportivo Alavés", "アラベス"),

    # NFKDで分解されない文字。ø は独立した字なので、
    # 結合記号を落とすだけでは o にならない。
    ("FC København", "コペンハーゲン"),
    ("FK Bodø/Glimt", "ボドー／グリムト"),

    # CLに出てくる5大リーグ以外のクラブ
    ("Sport Lisboa e Benfica", "ベンフィカ"),
    ("Sporting Clube de Portugal", "スポルティング"),
    ("FK Shakhtar Donetsk", "シャフタール"),
    ("Qarabağ Ağdam FK", "カラバフ"),

    # 一覧に無いクラブは、そのまま返る(欠けても落ちない)
    ("Some Unknown FC", "Some Unknown FC"),
]

section("クラブ名の日本語表記")
for api_name, want in NAME_CASES:
    check(api_name, ne.club_name_jp(api_name), want)

# 名簿にいるクラブは名簿の team_jp と必ず一致すること。
# ここが割れると、同じクラブが動画とサイトで別名になる。
for p in ne.JP_PLAYERS_SOCCER:
    check("表記が名簿と揃う: " + p["team_en"],
          ne.club_name_jp(p["team_en"]), p["team_jp"])

# 1つの日本語名に2つ以上の「別クラブ」が割り当たっていないか。
# 個別ケースを増やすより、こちらの方が新しい取り違えを拾える。
# (実データ134クラブでこれを回して、バルセロナとデポルティボの2件が出た)
#
# 対象はAPIが返す形の名前だけにする。名簿の team_en を混ぜると
# "Bayern Munich" と "FC Bayern München" が別クラブとして数えられ、
# 同じ日本語名になるのが正しいのに失敗として出る。
api_names = {n for n, _ in CASES} | {n for n, _ in NAME_CASES}
seen: dict = {}
for api_name in api_names:
    jp = ne.club_name_jp(api_name)
    if jp == api_name:      # 変換されなかったものは対象外
        continue
    seen.setdefault(jp, set()).add(api_name)
# 同じクラブの別表記。取り違えではない。
#
# football-data.org は時期や口によって表記が揺れる。
# "LOSC Lille" と "Lille OSC" はどちらもリールで、正規化すれば
# 同じところへ落ちる。**違うクラブが同じ日本語名になる**のが
# ここで捕まえたいことなので、別表記は先に除く。
ALIASES = [{"LOSC Lille", "Lille OSC"}]

for jp, sources in seen.items():
    if len(sources) > 1 and not any(sources <= a for a in ALIASES):
        fail(f"取り違え: {jp} <- {sorted(sources)}")
    else:
        passed()

sys.exit(done())
