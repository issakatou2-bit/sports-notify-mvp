"""

YouTubeのカスタムサムネイル(1280×720)を作る。



なぜ必要か:

  指定しないとYouTubeが動画中のコマを自動で選ぶ。ショートでも

  検索結果・関連動画・チャンネルページではサムネイルが出るため、

  そこが自動選択のままだと「たまたま切り取られた1コマ」で

  クリックされるかどうかが決まってしまう。



設計:

  ・動画の1枚目と同じフックを使う。サムネで見た話とタイトル・中身が

    一致しないと、開いた瞬間に閉じられる

  ・スマホの検索結果では横幅が小さいので、文字は極端に大きく、

    要素は3つまで(フック / 対戦カード / 日付)に絞る

  ・写真素材は使わない。著作権上の懸念が無く、毎日同じ品質で出せる



使い方:

  # 日次(ナレーション原稿のフックを使う)

  python3 scripts/generate_thumbnail.py --kind daily \

      --games notable_games.json --narration public/narration.json \

      --out build/video/thumb.png

  # 資産動画

  python3 scripts/generate_thumbnail.py --kind asset --asset-topic mlb_abbr \

      --out build/asset/thumb.png

"""



import argparse

import json

import os

import pathlib
import re

import subprocess

from morning_recap import jst_label as _jst_label  # noqa: E402



import video_common



from PIL import Image, ImageDraw



# フォントと ease_out は video_common に1つだけ置いてある。

#

# ここに自前で持っていたときは、候補の一覧が3〜6件でばらつき、

# キャッシュが付いているものと付いていないものがあった。

# 直したものが他へ届かない、という形をここで断つ。

font = video_common.font

ease_out = video_common.ease_out

FONT_CANDIDATES = video_common.FONT_CANDIDATES





# YouTube推奨サイズ。2MB以内に収める必要がある(PNGでも十分収まる)

W, H = 1280, 720



# ここで作る16:9は、いまYouTubeへは上げていない。

#

# ショートのサムネイルは9:16でないと形が合わない。16:9を渡すと、

# ショート棚とチャンネルのショートタブでは中央だけが切り抜かれる。

# 1280×720なら中央405px、つまり x=437〜842 の帯だけが残る。

# ここの文字は全部 x=70 から始まるので、丸ごと切り抜きの外へ出る。

# 文字の無い絵が並んでいたのはそのため。

#

# 上げているのは動画の1枚目(scripts/shorts_thumbnail.sh)。

# 既に1080×1920で、その回のフックが大きく出ていて、

# 動画とサムネイルが食い違いようがない。

#

# この16:9は、見比べるために残してある(artifactに入る)。

# 縦向きに描き直すか、1枚目のままでよいかは、見てから決める。

#

# ショートのサムネイルは9:16でないと受け付けられない。

#

# ここは16:9の座標で描いているので、縦に伸ばすと下半分が空く。

# 縦向きは動画の1枚目をそのまま使う(scripts/shorts_thumbnail.sh)。

# 同じ絵を2か所で作り直すより、既にある1枚目を取り出す方が確実で、

# 動画とサムネイルが必ず一致する。



BG = (11, 14, 20)

SURF = (18, 22, 31)

TEXT = (242, 240, 230)

DIM = (136, 145, 163)

ACCENT = (255, 176, 32)

JP = (73, 197, 182)







# 資産動画のサムネ文言。動画の中身と一致させる。

def _generated_thumb(topic: str):

    """

    venue_topics.py が作ったトピックのサムネ文言。無ければ None。



    手書きの分は1本ずつ考えてあるが、球場は公式APIから増え続けるので、

    材料の hook と label をそのまま置く。数字が入っているぶん、

    どの球場かが縮小しても見分けられる。

    """

    import generated_topics as gt

    spec = gt.get(topic)

    if spec:

        hook = spec.get("hook", "")

        # 「中堅420フィート、30球場でいちばん深い」を2行に割る。

        # 1行に押し込むと字が小さくなって、サムネでは読めない。

        head, _, tail = hook.partition("、")

        if "　" in hook and not tail:

            head, _, tail = hook.partition("　")

        return (head or spec.get("label", ""),

                spec.get("label", ""),

                tail or spec.get("where", ""))

    return None





ASSET_THUMB = {

    "mlb_abbr": ("LAD って どこ？", "MLB30球団の略称", "地区ごとに覚える"),

    "mlb_venue": ("点が入る球場", "入らない球場", "MLBの球場の癖"),

    "mlb_rivalry": ("なぜ因縁の対決？", "MLB 伝統の一戦", "由来から知る"),

    "mlb_stats": ("OPS って何？", "この数字だけ分かればいい", "防御率・WHIPも"),

    "mlb_terms": ("順位表、こう読む", "ゲーム差・ワイルドカード", "試合の重みが分かる"),

    "mlb_league": ("30球団の分かれ方", "2リーグ 6地区", "まずここから"),

    "mlb_position": ("SS ってどこ？", "守備位置の略号", "スタメン表が読める"),

    "collespo_guide": ("毎日19時に届く", "今日の注目試合を理由つきで", "登録は無料"),

    "npb_diff": ("日本の野球と何が違う？", "MLBとNPBの違い", "球団数・試合数・DH"),

    "soccer_leagues": ("5大リーグの違い", "欧州サッカー入門", "どこを見ればいい？"),

    "soccer_jp": ("欧州に何人いる？", "日本人選手まとめ", "名前と所属クラブ"),

    "soccer_terms": ("xG って何の数字？", "サッカーの指標", "スコア以外の見どころ"),

    "soccer_opening": ("開幕はいつ？", "欧州サッカー開幕ガイド", "序盤の注目カード"),

    "soccer_last_season": ("昨季の王者は？", "昨シーズンの結果", "5大リーグまとめ"),

    "mlb_advanced": ("OPSの次に覚えるなら", "現地で使われる指標", "OPS+ / wRC+ / WAR"),

    "mlb_pitch": ("今の球、何が違う？", "球種の見分け方", "6つだけ覚えれば足りる"),

    # 1球場ずつの深掘り。サムネでは「なぜそうなるのか」を問いの形で出す

    "venue_coors": ("なぜ点が入る？", "クアーズ・フィールド", "標高1600mの球場"),

    "venue_fenway": ("この壁、高さ11m", "フェンウェイ・パーク", "MLB現役最古"),

    "venue_wrigley": ("風で試合が変わる", "リグレー・フィールド", "ツタの生えた球場"),

    "venue_oracle": ("打球が海に落ちる", "オラクル・パーク", "MLB屈指の投手有利"),

    "venue_yankee": ("左打者天国の理由", "ヤンキー・スタジアム", "右翼が浅い"),

    "jp_players": ("今、何人いる？", "MLBの日本人選手", "2026年シーズン"),

    "mlb_watch": ("どこで見られる？", "日本でMLBを見る", "中継・時間帯"),

    "mlb_postseason": ("どう決まる？", "MLBのポストシーズン", "ワイルドカードとは"),

}





def fit(d, text: str, max_w: int, sizes) -> int:

    """1行に収まる最大のフォントサイズを実測で選ぶ"""

    for s in sizes:

        if d.textlength(text, font=font(s)) <= max_w:

            return s

    return sizes[-1]





def base():

    im = Image.new("RGB", (W, H), BG)

    d = ImageDraw.Draw(im)

    for i in range(-1, 7):

        x = i * 250

        d.polygon([(x, H), (x + 105, H), (x + 290, 0), (x + 185, 0)],

                  fill=(14, 18, 26))

    d.rectangle([0, H - 14, W, H], fill=ACCENT)

    return im, d





def load_hook(narration_path: str) -> dict:

    try:

        data = json.loads(pathlib.Path(narration_path).read_text(encoding="utf-8"))

    except (json.JSONDecodeError, OSError):

        return {}

    for s in data.get("segments", []):

        if s.get("kind") == "intro":

            return (s.get("meta") or {}).get("hook") or {}

    return {}





def draw_daily(d, hook: dict, games: list, date_label: str):

    sub = (hook.get("sub") or "").strip()

    big = (hook.get("big") or "今日の注目試合").strip()



    y = 90

    if sub:

        s = fit(d, sub, W - 140, (76, 64, 56, 48))

        d.text((70, y), sub, font=font(s), fill=JP)

        y += s + 24



    # フックは可能な限り大きく。スマホの一覧でも読めることが最優先

    s = fit(d, big, W - 140, (150, 132, 116, 100, 88, 76))

    d.text((70, y), big, font=font(s), fill=ACCENT)

    y += s + 40



    # 対戦カードは2試合まで。3つ並べると字が小さくなり読めない

    for g in games[:2]:

        line = f"{g.get('home_team_name')} vs {g.get('away_team_name')}"

        ls = fit(d, line, W - 200, (54, 48, 42, 38))

        d.rounded_rectangle([70, y, W - 70, y + ls + 26], 12, fill=SURF)

        d.text((96, y + 12), line, font=font(ls), fill=TEXT)

        y += ls + 40



    d.text((70, H - 78), f"{date_label}  コレスポ", font=font(40), fill=DIM)





def draw_weekly(d, label: str):

    d.text((70, 110), "今週の", font=font(80), fill=TEXT)

    d.text((70, 210), "答え合わせ", font=font(124), fill=ACCENT)

    d.text((70, 400), "注目した試合は、実際どうだったか", font=font(50), fill=TEXT)

    d.text((70, H - 130), label, font=font(50), fill=JP)

    d.text((70, H - 66), "コレスポ 週間まとめ", font=font(32), fill=DIM)





def draw_morning(d, day: str, players: list):

    d.text((70, 90), day, font=font(50), fill=DIM)

    d.text((70, 170), "日本人選手の成績", font=font(100), fill=ACCENT)



    # 名前と成績を2人ぶんだけ。サムネで読ませられるのはこのくらい

    y = 340

    for p in players[:2]:

        line = f"{p.get('name', '')}　{p.get('headline', '')}"

        s = fit(d, line, W - 200, (58, 52, 46, 40))

        d.rounded_rectangle([70, y, W - 70, y + s + 34], 14, fill=SURF)

        d.text((100, y + 14), line, font=font(s), fill=TEXT)

        y += s + 56



    d.text((70, H - 78), f"出場 {len(players)}人　コレスポ", font=font(40), fill=JP)





def draw_morning_local(d, day: str):

    """現地編。主題が違うので、選手名ではなく問いを前に出す"""

    d.text((70, 90), day, font=font(50), fill=DIM)

    d.text((70, 170), "現地で最も", font=font(100), fill=TEXT)

    d.text((70, 280), "見られた試合は？", font=font(100), fill=ACCENT)

    d.text((70, 440), "公式ハイライトの再生回数で見る", font=font(50), fill=TEXT)

    d.text((70, H - 78), "コレスポ  現地での注目度", font=font(40), fill=JP)





def draw_morning_press(d, day: str):

    """言葉の回。数字の回と主題を分けてあるので、そこが分かる出し方にする"""

    d.text((70, 90), day, font=font(50), fill=DIM)

    d.text((70, 170), "現地メディアは", font=font(100), fill=TEXT)

    d.text((70, 280), "何と言っている？", font=font(100), fill=JP)

    d.text((70, 440), "番記者の投稿と見出しを翻訳", font=font(50), fill=TEXT)

    d.text((70, H - 78), "コレスポ  現地の声", font=font(40), fill=JP)





def draw_morning_player(d, day: str, profile_path="data/player_profile.json"):

    """今日の1人。名前がそのまま検索語になる枠なので、名前を最大に出す。"""

    name = team = ""

    try:

        prof = json.loads(

            pathlib.Path(profile_path).read_text(encoding="utf-8"))

        name, team = prof.get("name", ""), prof.get("team", "")

    except (OSError, json.JSONDecodeError):

        pass

    d.text((70, 90), day, font=font(50), fill=DIM)

    if name:

        s = fit(d, name, W - 140, (150, 132, 116, 100, 88))

        d.text((70, 180), name, font=font(s), fill=JP)

        if team:

            d.text((70, 360), team, font=font(64), fill=TEXT)

    else:

        d.text((70, 180), "今日の1人", font=font(124), fill=JP)

    d.text((70, 460), "通算・今季・受賞歴まで", font=font(50), fill=TEXT)

    d.text((70, H - 78), "コレスポ  今日の1人", font=font(40), fill=DIM)





def draw_morning_voices(d, day: str, buzz_path="data/mlb_buzz.json"):

    """ファンのコメント欄。どの試合の反応なのかを出す。"""

    card = ""

    try:

        b = json.loads(pathlib.Path(buzz_path).read_text(encoding="utf-8"))

        top = (b.get("videos") or [{}])[0]

        res = top.get("result") or {}

        away, home = res.get("away_jp", ""), res.get("home_jp", "")

        if away and home:

            card = f"{away} 対 {home}"

    except (OSError, json.JSONDecodeError, IndexError):

        pass

    d.text((70, 90), day, font=font(50), fill=DIM)

    d.text((70, 165), "現地のファンは", font=font(100), fill=TEXT)

    d.text((70, 275), "何と言った？", font=font(124), fill=JP)

    if card:

        s = fit(d, card, W - 140, (60, 54, 48, 42))

        d.text((70, 440), card, font=font(s), fill=TEXT)

    d.text((70, 520), "コメント欄を翻訳。高評価の数つき", font=font(50), fill=DIM)

    d.text((70, H - 78), "コレスポ  現地の声", font=font(40), fill=JP)



# 長編のサムネイル。

#

# 16:9はショート棚のように中央だけ切り抜かれることが無いので、

# 画面をぜんぶ使える。

#

#   ┌────────────────────────────────┐

#   │ 8/30  ドジャース vs タイガース  │ ← ここだけ日によって変わる

#   │                                │

#   │ 公式ハイライトの      ｜立ち絵 │

#   │ コメント欄を          ｜       │

#   │ 読み解く              ｜       │

#   │              by コレスポ       │

#   └────────────────────────────────┘

#

# **大きい文字を固定にしたのが肝。**

# 前は対戦カードを大きく出していたので、球団名が長い日に

# 立ち絵へ文字が食い込んだ。長さが変わるものを小さい行へ回して、

# 大きい行は毎日同じにする。これで被りようがない。

#

# 文字には縁取りと影を付ける(video_common.pop_text)。

# 書体は源ノ角ゴシック Heavy のままで、処理だけ足している。

# 階段を1段ずつ下る。TYPE_SCALE の隣を引くための表。

TYPE_SCALE_DOWN = {b: a for a, b in zip(video_common.TYPE_SCALE, video_common.TYPE_SCALE[1:])}



LF_ART_H = 660

LF_ART_X = 1010         # 立ち絵2人の中心

LF_TEXT_R = 760         # 文字が使ってよい右端





def _lf_art(who: str, portrait_dir: str):

    """立ち絵。無ければ None。"""

    if not portrait_dir:

        return None

    base_dir = pathlib.Path(portrait_dir)

    for cand in (base_dir / who / "体.png", base_dir / (who + ".png")):

        if not cand.exists():

            continue

        try:

            art = Image.open(cand).convert("RGBA")

        except Exception:                        # noqa: BLE001

            return None

        # 部品の「体」には顔が入っていないので、重ねる。

        if cand.name == "体.png":

            try:

                spec = json.loads(

                    (base_dir / who / "parts.json").read_text(

                        encoding="utf-8"))

                for g, tag in (("眉", "基本"), ("目", "開"), ("口", "笑")):

                    fn = (spec.get(g) or {}).get(tag)

                    if fn:

                        art = Image.alpha_composite(

                            art, Image.open(

                                base_dir / who / fn).convert("RGBA"))

            except Exception:                    # noqa: BLE001

                pass

        k = LF_ART_H / art.height

        return art.resize((max(1, int(art.width * k)), LF_ART_H),

                          Image.LANCZOS)

    return None





def _jp_from_dialogue(path: str):

    """台本に残しておいた、コメントに出ている日本人選手。



    generate_dialogue が mentioned.find で拾って書いてある。

    ここで拾い直すと、題とサムネイルで別の名前が出かねない。

    """

    if not path:

        return []

    try:

        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

    except (OSError, json.JSONDecodeError):

        return []

    out = []

    for n in (d.get("jp") or [])[:2]:

        try:

            import upload_youtube as uy

            n = uy.title_name(n)

        except Exception:                        # noqa: BLE001

            pass

        out.append(n)

    return out



SPLIT = re.compile(r"\s+(?:vs|VS|対)\s+")


def _short_matchup(topic: str) -> str:

    """対戦カードを短くする。「サンディエゴ・パドレス」→「パドレス」。



    都市名まで入れると2球団で20字を超えて、いちばん小さい字でも

    右へはみ出した。サムネイルで都市名を読ませる必要は無い。

    """

    parts = []

    for side in SPLIT.split(str(topic or "")):

        side = side.strip()

        if "・" in side:

            side = side.split("・")[-1]

        parts.append(side)

    return " vs ".join(p for p in parts if p)





def draw_longform(im, d, topic: str, day: str, portrait_dir: str,

                  jp_names=None):

    """長編（対話）。サムネイルは「目に入った瞬間」だけを担当する。



    題（検索）とサムネイル（一目）で役割が違う。

    題に書いても検索の人は増えないが一目で知りたいもの——**日付**——は

    こちらに置く。逆に検索語（「海外の反応」）は題にもここにも要る。



    調べた実務の目安を、そのまま当ててある:



      ・文字は最長20字程度。理想は6〜8字

      ・**重要なものは左上70%。右下30%は再生時間の表示と重なる**

      ・色は3色まで。背景と文字のコントラストは4.5:1以上

      ・大小の差をはっきり付ける（ヒエラルキー）



    前の版は「8月31日　ドジャース vs タイガース／大谷翔平／

    への現地の声を／読み解く」で35字あった。多すぎたし、

    左下が空いていて締まらなかった。



    いまの形:



      [8/31] ドジャース vs タイガース      ← 日付は塗りの札。一目で最新と分かる

      大谷翔平                            ← 124 / JP

      海外の反応                          ← 156 / ACCENT（いちばん大きい）

      公式コメント欄を読む                 ← 40 / DIM（説明。小さくてよい）

      コレスポ



    大きい2行で9字。目安に収まる。

    """

    import video_common as vc



    # 立ち絵。画面の下端まで出して、切れているところを作る。

    # 収まりよく置くより、画面を使い切るほうが目を引く。

    arts = [_lf_art(who, portrait_dir)

            for who in ("ずんだもん", "四国めたん")]

    arts = [a for a in arts if a is not None]

    if arts:

        span = sum(a.width for a in arts) - 90 * (len(arts) - 1)

        x = LF_ART_X - span // 2

        for a in arts:

            im.paste(a, (int(x), H - LF_ART_H + 30), a)

            x += a.width - 90



    # 日付の札。塗りつぶした四角に濃い字。

    #

    # 「8月31日」を細い字で小さく置いていたが、縮小されると読めない。

    # 一覧に並んだとき「今日の最新か」を知りたいので、ここは

    # 読めないと意味が無い。「8/31」に詰めて、塗りの中へ入れる。

    short = day.replace("月", "/").replace("日", "")

    fd = font(56)

    bw = d.textlength(short, font=fd) + 44

    d.rounded_rectangle([70, 44, 70 + bw, 44 + 76], 14, fill=ACCENT)

    d.text((70 + 22, 44 + 8), short, font=fd, fill=(12, 14, 20))



    short_topic = _short_matchup(topic)

    jp = [n for n in (jp_names or []) if n][:2]



    # 対戦カード。日付の右。

    # **名前が取れない日は、対戦カードが大きい行のほうへ回る。**

    # 両方に出すと同じ言葉が2回並ぶ。前の版がそうなっていた。

    if short_topic and jp:

        tx = 70 + bw + 20

        s = fit(d, short_topic, 880 - 120 - tx, (44, 40, 34, 30, 26))

        vc.pop_text(d, (tx, 44 + 20), short_topic, font(s), TEXT,

                    stroke=(8, 10, 15), stroke_w=5, shadow=(0, 0, 0),

                    shadow_off=(3, 4))



    # 大きい2行。ここだけで9字。

    avail = 880 - 120 - 70



    def shrink(text, start):

        s = start

        while s > 32 and d.textlength(text, font=font(s)) > avail:

            s = TYPE_SCALE_DOWN.get(s, s - 8)

        return s



    lines = []

    if jp:

        who = "・".join(jp)

        lines.append((who, shrink(who, 124), JP))

    else:

        who = short_topic or "MLB"

        lines.append((who, shrink(who, 100), TEXT))

    lines.append(("海外の反応", 156, ACCENT))



    y = 168

    for text, size, color in lines:

        vc.pop_text(d, (70, y), text, font(size), color,

                    stroke=(8, 10, 15), stroke_w=11, shadow=(0, 0, 0),

                    shadow_off=(7, 8))

        y += size + 18



    # 説明の1行。小さくてよい。ここを読ませたいわけではなく、

    # 「何の動画か」が分かれば足りる。

    vc.pop_text(d, (70, y + 8), "公式コメント欄を読む", font(40), DIM,

                stroke=(8, 10, 15), stroke_w=6, shadow=(0, 0, 0))



    # 番組名は左下。右下は再生時間の表示と重なるので置かない。

    vc.pop_text(d, (70, H - 88), "コレスポ", font(50), JP,

                stroke=(8, 10, 15), stroke_w=7, shadow=(0, 0, 0))





def draw_verdict(d, label: str):

    d.text((70, 110), "注目した試合", font=font(80), fill=TEXT)

    d.text((70, 210), "どうなった？", font=font(124), fill=ACCENT)

    d.text((70, 400), "連勝は続いたのか、止まったのか", font=font(50), fill=TEXT)

    d.text((70, H - 130), label, font=font(50), fill=JP)

    d.text((70, H - 66), "コレスポ 先週の答え合わせ", font=font(32), fill=DIM)





def draw_asset(d, topic: str):

    big, mid, small = ASSET_THUMB.get(topic) or _generated_thumb(topic) or (

        "コレスポ", "MLB入門", "collespo.com")

    s = fit(d, big, W - 140, (150, 132, 116, 100))

    d.text((70, 120), big, font=font(s), fill=ACCENT)

    s2 = fit(d, mid, W - 140, (84, 72, 64, 56))

    d.text((70, 320), mid, font=font(s2), fill=TEXT)

    d.text((70, 440), small, font=font(50), fill=JP)

    d.text((70, H - 78), "コレスポ  collespo.com", font=font(40), fill=DIM)





def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--kind", default="daily",

                        choices=["daily", "weekly", "asset", "verdict", "morning",

                                 "longform"])

    parser.add_argument("--recap", default="data/morning_recap.json")

    # 選択肢は post_common.DAILY_LINEUP と揃える。

    #

    # ここに player と voices が無かった。ワークフローは4つのmodeを

    # 順に渡しているので、その2つでargparseが終了コード2で落ちる。

    # ループは set +e で回っているため次へ進み、投稿側は

    # 「サムネイル画像が無いためスキップします」と1行出して公開する。

    # 結果、今日の1人とファンのコメント欄には最初からサムネイルが無かった。

    #

    # 同じことが --morning-mode でも起きている(press が選択肢に無く、

    # 現地の声の動画が2日ぶん作られては捨てられていた)。

    # 今度は run_checks.py が突き合わせる。

    parser.add_argument("--mode", default="players",

                        choices=["players", "player", "voices",

                                 "local", "press", "all"])

    parser.add_argument("--games", default="notable_games.json")

    parser.add_argument("--narration", default="public/narration.json")

    parser.add_argument("--asset-topic", default="mlb_abbr")

    parser.add_argument("--topic", default="",

                        help="長編で出す主題(その日のハイライト)")

    parser.add_argument("--portrait-dir", default="assets/portraits")

    parser.add_argument("--dialogue", default="",

                        help="長編の台本。名前をサムネイルに出す")

    parser.add_argument("--label", default="")

    parser.add_argument("--archive-dir", default="archive",

                        help="週次で --label を省いたときの期間の算出元")

    parser.add_argument("--out", default="build/thumb.png")

    args = parser.parse_args()



    im, d = base()



    if args.kind == "longform":

        day = _jst_label(None) if not args.label else args.label

        try:

            from datetime import datetime as _dt, timezone, timedelta

            n = _dt.now(timezone(timedelta(hours=9)))

            day = f"{n.month}月{n.day}日"

        except Exception:  # noqa: BLE001

            day = ""

        draw_longform(im, d, args.topic, day, args.portrait_dir,

                      _jp_from_dialogue(args.dialogue))

    elif args.kind == "morning":

        try:

            rec = json.loads(pathlib.Path(args.recap).read_text(encoding="utf-8"))

        except (json.JSONDecodeError, OSError):

            print("[info] 成績データが読めないため、サムネイルは作りません")

            return

        players = rec.get("players") or []

        if not players:

            print("[info] 出場選手がいないため、サムネイルは作りません")

            return

        # 米国日付ではなく、日本時間で試合が行われた日を出す。

        # 動画・タイトル・サムネイルで日付が食い違うと、

        # どれが正しいのか視聴者には分からない。

        day = rec.get("date_jst") or _jst_label(rec.get("date", ""))

        try:

            from datetime import datetime as _dt

            _p = _dt.strptime(day, "%Y-%m-%d")

            day = f"{_p.month}月{_p.day}日"

        except ValueError:

            pass

        if args.mode == "press":

            draw_morning_press(d, day)

        elif args.mode == "player":

            draw_morning_player(d, day)

        elif args.mode == "voices":

            draw_morning_voices(d, day)

        elif args.mode == "local":

            draw_morning_local(d, day)

        else:

            draw_morning(d, day, players)

    elif args.kind == "asset":

        draw_asset(d, args.asset_topic)

    elif args.kind in ("weekly", "verdict"):

        label = args.label

        if not label:

            # 動画・タイトルと同じ条件で週の範囲を求める。

            # ここだけ別に計算すると、サムネの日付だけずれる

            try:

                import sys



                sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

                import weekly_stats as ws



                week = ws.load_week(pathlib.Path(args.archive_dir))

                if week:

                    label = (f"{week[0][0][5:].replace('-', '/')}〜"

                             f"{week[-1][0][5:].replace('-', '/')}")

            except Exception as e:

                print(f"[warn] 週の範囲を求められませんでした: {e}")

        if args.kind == "verdict":

            draw_verdict(d, label)

        else:

            draw_weekly(d, label)

    else:

        try:

            data = json.loads(pathlib.Path(args.games).read_text(encoding="utf-8"))

            games = [g for g in data.get("games", []) if g.get("is_notable")]

        except (json.JSONDecodeError, OSError):

            games = []

        if not games:

            print("[info] 注目試合が無いため、サムネイルは作りません")

            return

        date_label = args.label or (games[0].get("start_time_jst") or "").split(" ")[0]

        draw_daily(d, load_hook(args.narration), games, date_label)



    out = pathlib.Path(args.out)

    out.parent.mkdir(parents=True, exist_ok=True)

    im.save(out, optimize=True)

    kb = out.stat().st_size / 1024

    print(f"[info] サムネイルを生成しました: {out} "

          f"({im.width}×{im.height}, {kb:.0f}KB)")

    if kb > 2048:

        print("::warning title=サムネイルが大きすぎる::"

              "YouTubeの上限は2MBです")





if __name__ == "__main__":

    main()

