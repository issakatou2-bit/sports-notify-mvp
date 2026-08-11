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

# (APIが返しうる正式名称, 期待する日本人選手)
CASES = [
    ("Liverpool FC", ["遠藤航"]),
    ("Brighton & Hove Albion FC", ["三笘薫"]),
    ("Crystal Palace FC", ["鎌田大地"]),
    ("Tottenham Hotspur FC", ["高井幸大"]),
    ("Leeds United FC", ["田中碧"]),
    ("Coventry City FC", ["坂元達裕"]),
    ("Ipswich Town FC", ["前田大然"]),
    ("Hull City AFC", ["守田英正"]),
    ("Real Sociedad de Fútbol", ["久保建英"]),
    ("Valencia CF", ["佐藤龍之介"]),
    ("FC Bayern München", ["伊藤洋輝"]),
    ("TSG 1899 Hoffenheim", ["町田浩樹"]),
    ("SC Freiburg", ["鈴木唯人"]),
    ("Eintracht Frankfurt", ["堂安律"]),
    ("1. FSV Mainz 05", ["佐野海舟", "川﨑颯太"]),
    ("Borussia Mönchengladbach", ["町野修斗", "宇野禅斗", "橋岡大樹"]),
    ("FC Schalke 04", ["田中聡"]),
    ("Parma Calcio 1913", ["鈴木ザイオン"]),
    ("AS Monaco FC", ["南野拓実"]),
    ("Le Havre AC", ["瀬古歩夢", "中村草太", "水多海斗"]),
]

# 日本人選手が居ないクラブ。1人でも当たったら誤爆。
NEGATIVE = [
    "Arsenal FC", "Manchester City FC", "Manchester United FC", "Chelsea FC",
    "Newcastle United FC", "Aston Villa FC", "Everton FC", "Fulham FC",
    "West Ham United FC", "Nottingham Forest FC", "AFC Bournemouth",
    "Wolverhampton Wanderers FC", "Brentford FC", "Burnley FC",
    "Real Madrid CF", "FC Barcelona", "Club Atlético de Madrid",
    "Athletic Club", "Villarreal CF", "Real Betis Balompié", "Sevilla FC",
    "Borussia Dortmund", "Bayer 04 Leverkusen", "RB Leipzig",
    "VfB Stuttgart", "VfL Wolfsburg", "SV Werder Bremen", "FC Augsburg",
    "1. FC Union Berlin", "1. FC Köln", "FC St. Pauli",
    "Juventus FC", "AC Milan", "FC Internazionale Milano", "SSC Napoli",
    "AS Roma", "SS Lazio", "Atalanta BC", "ACF Fiorentina", "Bologna FC 1909",
    "Paris Saint-Germain FC", "Olympique de Marseille", "Olympique Lyonnais",
    "LOSC Lille", "Stade Rennais FC 1901", "OGC Nice", "RC Lens",
    "FC Nantes", "Toulouse FC", "Stade Brestois 29",
]

fails = 0
for api_name, expected in CASES:
    got = [p["name_jp"] for p in ne.jp_players_for_club(api_name)]
    ok = sorted(got) == sorted(expected)
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {api_name:32} -> {got}"
          + ("" if ok else f"   expected {expected}"))

print()
for api_name in NEGATIVE:
    got = [p["name_jp"] for p in ne.jp_players_for_club(api_name)]
    if got:
        fails += 1
        print(f"NG  誤爆: {api_name} -> {got}")
print(f"誤爆チェック {len(NEGATIVE)}クラブ: "
      f"{'問題なし' if not any(ne.jp_players_for_club(n) for n in NEGATIVE) else '誤爆あり'}")

# 完全一致に戻したら何件当たるか。この差が、この照合が要る理由そのもの。
old = sum(1 for n, _ in CASES if n in {p["team_en"] for p in ne.JP_PLAYERS_SOCCER})
print(f"\n完全一致だった場合の的中: {old}/{len(CASES)} クラブ")
print(f"正規化照合での的中: {len(CASES) - fails}/{len(CASES)} クラブ")

# 名簿の全員がいずれかのケースで拾えているか
covered = set()
for api_name, _ in CASES:
    covered.update(p["name_jp"] for p in ne.jp_players_for_club(api_name))
missing = [p["name_jp"] for p in ne.JP_PLAYERS_SOCCER if p["name_jp"] not in covered]
print("未カバーの選手:", missing or "なし")
if missing:
    fails += 1


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
    # 一覧に無いクラブは、そのまま返る(欠けても落ちない)
    ("Some Unknown FC", "Some Unknown FC"),
]

print()
for api_name, want in NAME_CASES:
    got = ne.club_name_jp(api_name)
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {api_name:28} -> {got}"
          + ("" if ok else f"  (期待 {want})"))

# 名簿にいるクラブは名簿の team_jp と必ず一致すること。
# ここが割れると、同じクラブが動画とサイトで別名になる。
for p in ne.JP_PLAYERS_SOCCER:
    got = ne.club_name_jp(p["team_en"])
    if got != p["team_jp"]:
        fails += 1
        print(f"NG  表記割れ: {p['team_en']} -> {got} (名簿は {p['team_jp']})")

print("\nALL OK" if fails == 0 else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
