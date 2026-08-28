"""
notable_games.json / news.json から、動画のナレーション原稿を生成する。

構成:
  セグメントの配列として出力する。1セグメント = 1画面 + 1音声。
  こうしておくと、あとで音声の実測長に合わせて画面の表示時間を決められる
  (原稿の文字数から推測するのではなく、実際の音声長に合わせるのでズレない)。

出力: public/narration.json
  {
    "date_label": "08/05",
    "segments": [
      {"kind": "intro", "text": "...", "meta": {...}},
      {"kind": "game",  "text": "...", "meta": {"game_index": 0}},
      ...
    ]
  }

AIを使う箇所:
  ・各試合の紹介文を「話し言葉」に直す部分だけ。
  ・サイト用のai_summaryは書き言葉なので、そのまま読み上げると硬い。
  ・数字や固有名詞はデータ側から渡し、AIには言い回しだけを任せる
   (数字を創作させない)。

使い方:
  python3 scripts/generate_narration.py --out public/narration.json
"""

import argparse
import functools
import json
import os
import pathlib
import re
import sys
import textkey as _textkey
import unicodedata

# notability_engine.py はリポジトリの直下にある。
# `python scripts/generate_narration.py` で起動すると sys.path に載るのは
# scripts/ だけで、作業ディレクトリは載らない。この1行が無いまま
# notability_engine を import していたため、本番で毎回
# ModuleNotFoundError になり、ナレーションも音声も動画もポッドキャストも
# 作られなかった。手元では通っていた(起動の仕方が違うため)。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import post_common  # noqa: E402
import perspectives  # noqa: E402
from notability_engine import (  # noqa: E402
    MLB_NAME_READINGS as _MLB_NAME_READINGS,
    is_soccer_league as _is_soccer_league,
)

import token_log  # noqa: E402

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"
# ショート動画(60秒以内)に収まる範囲で、情報量も確保する。
# 1試合75文字前後 × 3試合 + 前後 で、1.3倍速で40秒前後になる。
MAX_GAMES = 3

# 競技の見分けは notability_engine に寄せる。ここでコードだけを並べて
# いたが、データに入っているのは日本語のリーグ名なので一度も一致せず、
# 点数の根拠の文言がサッカーでも野球のままになっていた。


# 「大谷翔平は8試合連続安打中」「アストロズは5連勝中」のように、
# 主語と内容が「は」で分かれている事実をほどく。
# 主語が長すぎるものは見出しに向かないので上限を付けている。
# 「ドジャースには〜が所属」のような「には」の形は主語の切れ目が違うため、
# 後読みで弾く(「ドジャースに」を主語として拾ってしまうのを防ぐ)。
HOOK_RE = re.compile(r"^(?P<who>.{2,14}?)(?<![にへとで])は(?P<what>.{4,28})$")

# 「アストロズ vs レンジャーズ は首位攻防戦、ゲーム差はわずか1.5」から
# ゲーム差だけを取り出す。
GAMES_BACK_RE = re.compile(r"ゲーム差はわずか([\d.]+)")


# 手書きの読み表も、正規化したキーで引けるようにしておく。
_READINGS_FOLDED = {_textkey.key(k): v for k, v in _MLB_NAME_READINGS.items()}


@functools.lru_cache(maxsize=1)
def _surname_kana() -> dict:
    """
    姓だけの読み。フルネームで引けた人から作る。

    なぜ要るのか:
      Wikidataに載っていない選手がいる。デビューしたばかりだと
      記事が無い。実際 "Rafael Flores Jr." は引けず、読み上げが
      「フロアーズ」になった。

      ところが同じ姓の "Wilmer Flores" は引けていて、
      「ウィルマー・フローレス」と分かっている。姓の読みは
      そこから取れる。1人ぶん引ければ、同じ姓の全員に効く。
    """
    out = {}
    for en, ja in _kana_table().items():
        if not ja or "・" not in ja:
            continue
        # キーは正規化して置く。アクセントを残すと "Díaz" で登録され、
        # コメントやAPIが返す "Diaz" では引けない。実際そうなっていて、
        # 手書きの表にたまたま "Diaz" があったので気付かなかった。
        last = _textkey.surname(en)
        if last:
            out.setdefault(_textkey.key(last), ja.split("・")[-1])
    return out


@functools.lru_cache(maxsize=1)
def _kana_table(path: str = "data/player_kana.json") -> dict:
    """英語名 -> 日本語表記。無ければ空の辞書。"""
    try:
        raw = json.loads(pathlib.Path(path).read_text(
            encoding="utf-8")).get("names") or {}
    except (OSError, json.JSONDecodeError):
        return {}
    # キーは正規化して持つ。APIが "Andrés Chaparro" を返す日と
    # "Andres Chaparro" を返す日があり、完全一致だと片方で引けない。
    return {_textkey.key(k): v for k, v in raw.items() if v}


@functools.lru_cache(maxsize=1)
def _jp_kana() -> dict:
    """日本人選手の、漢字表記 → 読み(カタカナ)。

    野球とサッカー、両方の名簿が持っている。
    _MLB_NAME_READINGS のほうは英語名を引くための表なので、
    漢字で来る日本人選手はそちらでは引けない。
    """
    out = {}
    try:
        from notability_engine import JP_PLAYERS_MLB, JP_PLAYERS_SOCCER
    except ImportError:
        return out
    for p in list(JP_PLAYERS_SOCCER) + list(JP_PLAYERS_MLB):
        if p.get("kana") and p.get("name_jp"):
            out[p["name_jp"]] = p["kana"]
    return out


def speech_name(name: str) -> str:
    """
    読み上げに渡す用に、外国人選手の名前を整える。画面表示には使わない。

    VOICEVOXは「José Soriano」を「ジェーオーエス、ソリアーノ」と読む。
    アクセント付きの文字で辞書を外し、そこだけアルファベットの
    1文字読みに落ちるため。冒頭のフックは動画の最初の2秒なので、
    ここが崩れるのはいちばん痛い。

    やっていることは2つだけ:
      1. アクセント記号を落とす (José -> Jose)
      2. 2語以上なら姓だけにする (Jose Soriano -> Soriano)

    姓だけにするのは、VOICEVOXが姓は概ね読めているのと、
    日本の野球中継でも姓で呼ぶのが普通のため。
    日本人選手は漢字で来るので、先に _jp_kana() で読みに置き換える
    (置き換えないと「田中碧」の読みをVOICEVOXが推測することになる)。

    根本的には選手ごとのカタカナ表記を持つのが正しいが、
    先発投手は誰でもフックに出るので、名簿を用意しても漏れる。
    """
    # 日本人選手は漢字で持っている。そのまま渡すとVOICEVOXが読みを
    # 推測して、「田中碧」を「たなかみどり」のように外す。人名の読みは
    # 規則で決まらないので、推測に任せてはいけない。
    #
    # 名簿にローマ字表記があるので、読みはそこから決まっている。
    # こちらで当てているわけではない (Ao Tanaka → タナカ・アオ)。
    got = _jp_kana().get(name.strip())
    if got:
        return got
    if not name or not any(c.isascii() and c.isalpha() for c in name):
        return name
    # 集めたカタカナがあれば、それがいちばん正しい。
    # player_kana.py が Wikidata から引いて残している。
    got = _kana_table().get(_textkey.key(name))
    if got:
        return got
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    parts = [p for p in folded.split() if p]
    # 読みを持っている姓は、カタカナに置き換える。
    # 姓だけに削るのは「アルファベットのままよりはまし」という妥協で、
    # 1本まるごと同じ名前を読む回には足りない。
    for part in reversed(parts):
        key = part.rstrip(".")
        if key in ("Jr", "Sr", "II", "III", "IV"):
            continue
        k = _textkey.key(key)
        got = (_MLB_NAME_READINGS.get(key)
               or _READINGS_FOLDED.get(k)
               or _surname_kana().get(k))
        if got:
            return got
    if len(parts) >= 2:
        # "Jr." のような接尾辞は落として、その手前を姓とみなす
        while len(parts) >= 2 and parts[-1].rstrip(".").lower() in ("jr", "sr", "ii", "iii"):
            parts.pop()
        return parts[-1]
    return folded


def display_name(name: str) -> str:
    """画面と題に出す名前。ラテン文字ならカタカナ、日本語ならそのまま。

    speech_name は読み上げ用なので「山本由伸」を「ヤマモト・ヨシノブ」に
    する。声に出すぶんにはそれでよいが、目で読む題は漢字のほうがよい。
    直すのはラテン文字の綴りだけ。実測で、題の先頭がラテン文字だった回は
    視聴継続が16.9% / 19.0% / 19.1% と3本ともそろって低かった。
    """
    if not name:
        return ""
    if not any(c.isascii() and c.isalpha() for c in name):
        return name
    kana = speech_name(name)
    if any(c.isascii() and c.isalpha() for c in kana):
        return name          # カタカナに直せなかったときは綴りのまま
    return kana


def pick_hook(games: list) -> dict:
    """
    動画の1枚目に出す「最も具体的な事実」を選ぶ。

    なぜ必要か:
      これまで1枚目は「コレスポ / 08/07の注目試合」というロゴと日付だけで、
      視聴者にとっては何の情報も無かった。ショートは最初の1秒で
      スワイプされるかが決まるので、そこを名乗りに使うのは最ももったいない。

    選ぶ順番は「日本の視聴者が知っている順」。実測でそう決めてある
    (下の1番の説明を参照)。いずれも既に検証済みのデータで、
    ここで新しく何かを判断したり生成したりはしない。

    最後の日本人選手名は「所属している」ことしか分からないため、
    名前を並べるだけにして「出場」「先発」とは書かない
    (打者のスタメンは19時の生成時点ではまだ公表されていない)。
    """
    # 1. 日本人投手の先発予定(APIで確認できている事実)
    #
    # 以前は「具体性が高い順」として、外国人選手の個人記録を先頭に置いていた。
    # 実測はその逆だった。同じ「明日の注目試合」でも:
    #
    #   パドレス 6連勝中             視聴継続 50.2%(738回)
    #   Kevin Gausman 移籍後2登板目  視聴継続 19.1%(1203回)
    #   Clay Holmes 移籍後2登板目    視聴継続 16.9%(208回)
    #
    # 32ポイント差。1203回配られて19%しか残らないのは、配られ方ではなく
    # 1枚目の問題で、「Kevin Gausman」で止まる人が日本の視聴者には多い。
    # 視聴の97.6%が日本からで、検索されるのも日本人選手の名前。
    # 知っている名前を先に出す。
    for at, g in enumerate(games):
        for p in g.get("jp_starters") or []:
            if p.get("name"):
                return {"big": "先発予定", "sub": p["name"], "at": at}

    # 2. 連勝・連敗。チームの話なので、選手を知らなくても意味が通る。
    for at, g in enumerate(games):
        for r in g.get("reasons") or []:
            if r.get("tag") != "streak":
                continue
            m = HOOK_RE.match((r.get("text") or "").strip())
            if m:
                return {"big": m.group("what"), "sub": m.group("who"), "at": at}

    # 3. 首位攻防戦(ゲーム差という具体的な数字が入る)
    #
    #    所属より上に置く。「◯◯が所属」はシーズンを通してほぼ毎日
    #    どこかで成り立つので、その日を選んだ理由になっていない。
    #    ゲーム差はその日その時点の数字で、なぜ今日この試合なのかに
    #    答えている。所属は見どころの一つとして、本編で触れれば足りる。
    for at, g in enumerate(games):
        for r in g.get("reasons") or []:
            if r.get("tag") != "div":
                continue
            m = GAMES_BACK_RE.search(r.get("text") or "")
            if m:
                return {"big": f"ゲーム差{m.group(1)}の首位攻防戦", "sub": "", "at": at}

    # 4. ダービー・伝統の一戦。名前そのものが最も具体的で、検索もされる。
    #
    #    理由の文は説明つきで長い。
    #      「カブス vs ホワイトソックス は同都市対決 —
    #        シカゴ市内を二分する『クロスタウン・クラシック』」
    #    20字の上限で弾いていたので、シカゴ対決の日でもここが発火せず、
    #    その下の個人記録(外国人選手名)へ落ちていた。
    #    鉤括弧の中に呼び名が入っているので、そこを取り出す。
    for at, g in enumerate(games):
        for r in g.get("reasons") or []:
            if r.get("tag") != "rivalry" or not r.get("text"):
                continue
            text = r["text"].strip()
            m = re.search(chr(12300) + "([^" + chr(12301) + "]{3,20})"
                          + chr(12301), text)
            name = m.group(1) if m else text
            if 3 <= len(name) <= 20:
                return {"big": name, "sub": "", "at": at}

    # 5. 連続安打・移籍後初登板などの個人記録。
    #    外国人選手が主語になりやすく、実測どおり弱いので後ろに置く。
    for at, g in enumerate(games):
        for note in g.get("log_notes") or []:
            m = HOOK_RE.match((note or "").strip())
            if m:
                return {"big": m.group("what"), "sub": m.group("who"), "at": at}

    # 6. 日本人選手が所属しているチームの試合。
    #    打者のスタメンは前日には分からないので、「出場」「先発」とは書かない。
    #    ここまで何も無かった日の受け皿。
    for at, g in enumerate(games):
        for name in (g.get("jp_players") or []):
            if name:
                return {"big": "所属チームの一戦", "sub": name, "at": at}

    # 7. サッカーで日本人選手が所属している場合。
    #     「先発予定」とは書かない。スタメンは前日には分からない。
    for at, g in enumerate(games):
        for r in g.get("reasons") or []:
            if r.get("tag") != "jp_team":
                continue
            m = re.match(r"^(?P<club>.+?)には(?P<who>.+?)が所属$",
                         (r.get("text") or "").strip())
            if m:
                return {"big": f"{m.group('club')}の試合",
                        "sub": m.group("who").split("・")[0]}

    # 8. AIのフック文(短くまとまっているものだけ)
    for at, g in enumerate(games):
        h = (g.get("notification_hook") or "").strip().rstrip("。")
        if 6 <= len(h) <= 32:
            return {"big": h, "sub": "", "at": at}

    # 9. 日本人選手の名前を並べるだけ(所属以上のことは書かない)
    for at, g in enumerate(games):
        names = [n for n in (g.get("jp_players") or []) if n]
        if names:
            return {"big": "・".join(names[:3]), "sub": "", "at": at}

    # 10. サッカーは、大会名を最後の手がかりにする。
    #     クラブ名だけのタイトルだと、どのリーグの話か分からない。
    #     MLBは札で分かるので、ここはサッカーだけ。
    for at, g in enumerate(games):
        lg = g.get("league")
        if lg and _is_soccer_league(lg):
            return {"big": f"{lg}の一戦", "sub": "", "at": at}

    # 何も当てはまらない日。
    #
    # ここで「今日の注目試合」を返していたため、タイトルが
    # 「今夜の注目試合｜今日の注目試合｜デポルティボ vs エルチェ」と
    # 見出しを2回言う形になって公開された。見出しはタイトル側が
    # 別に付けるので、材料が無いなら何も返さない方がよい。
    # 画面側は big が空なら日付入りの見出しに落ちる。
    return {"big": "", "sub": "", "at": None}


def _top_game_meta(games: list) -> dict:
    """1枚目に添える、その回のいちばんの試合。"""
    if not games:
        return {}
    g = games[0]
    start = g.get("start_time_jst") or ""
    return {
        "matchup": g.get("matchup") or "",
        "time": (start.split(" ")[1] + " JST") if " " in start else "",
    }


def _with_team(row) -> str:
    """「レンジャーズのジェイコブ・デグロム」。所属が無ければ名前だけ。"""
    who = speech_name(row.get("name", ""))
    team = (row.get("team") or "").strip()
    return f"{team}の{who}" if team else who


def _who(row) -> dict:
    """画面に出す用の、選手名と成績。無ければ空。"""
    if not row or not row.get("headline"):
        return {}
    return {"name": row.get("name", ""), "team": row.get("team", ""),
            "headline": row["headline"]}


def _spoken_stats(headline: str) -> str:
    """
    画面用の成績文を、読み上げ用に整える。

    画面では「5打数4安打　2本塁打　3打点」のように全角の空白で区切って
    いるが、読み上げに渡すと切れ目が無く一息で流れる。
    耳で聞く方には、読点が入っていないと数字の切れ目が分からない。
    """
    out = "、".join(x for x in headline.replace(chr(0x3000), " ").split() if x)
    # 投球回は野球独特の書き方で、小数点以下はアウトの数を表す。
    # 「6.1回」は6と3分の1回であって6.1回ではない。
    # 画面はこの書き方のままでよいが、読み上げは「ろくてんいち」と
    # 読まれてしまい、意味が変わって聞こえる。
    for dec, word in (("0", "回"), ("1", "回3分の1"), ("2", "回3分の2")):
        pat = r"(\d+)\." + dec + r"回"
        out = re.sub(pat, r"\1" + word, out)
    return out


def _how_many(games: list, total: int) -> str:
    """
    「何試合あるうちの何試合を紹介するか」。

    欧州は日によって0試合の日も19試合の日もある。3試合と言われても、
    それが全部なのか一部なのかが分からない。総数が分かれば、
    選んだという行為そのものにも意味が出る。

    MLBは毎日15試合前後で変わらないので、そちらには足さない。
    毎回同じ数を言うことになって、尺だけ食う。
    """
    n = len(games)
    if not (games and _is_soccer_league(games[0].get("league"))):
        return f"注目の{n}試合を、理由つきで。"
    if not total or total <= n:
        # 全部紹介する日。「1試合から1試合を選ぶ」とは言わない。
        return f"今夜あるのはこの{n}試合です。理由つきで見ていきます。"
    return f"今夜は{total}試合。そこから{n}試合を、理由つきで。"


def _yesterday_recap(archive_dir: str, games: list,
                     base_rates_path: str = "data/base_rates.json",
                     best_path: str = "data/best_of_day.json"
                     ) -> dict:
    """
    昨日「注目」として出した試合の結果を、1つのセグメントにまとめる。

    結果が入っていない試合は扱わない。19時の時点では、前日に予告した
    試合(日本時間の未明〜午前)は終わっているので、その日の分だけ言える。
    """
    import datetime as _dt
    import pathlib as _p

    import weekly_stats as ws

    sport = ("soccer" if any(_is_soccer_league(g.get("league")) for g in games)
             else "mlb")
    jst = _dt.timezone(_dt.timedelta(hours=9))
    yesterday = (_dt.datetime.now(jst) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")

    picked = ws.load_day(_p.Path(archive_dir), yesterday, sport=sport)
    lines = ws.day_lines(picked)
    if not lines:
        return {}

    # 読み上げには正式名を渡す。画面は略称のままにする。
    # 「LAD」は「エルエーディー」と読まれてしまい、耳では意味が通らない。
    # 「6対4」だけでは、どちらの数字か分からない。勝った側まで言う。
    spoken = "。".join(
        f"{spoken_m or m}は{sc.replace(' - ', '対')}"
        + (f"で{won}の勝ち" if won else "")
        + (f"、{note}" if note else "")
        for m, sc, note, spoken_m, won in lines[:3])
    # 通算の記録も渡す。毎日1つずつ増える数字で、
    # 続けて見ている人にだけ育っているのが見える。
    base = {}
    try:
        base = (json.loads(pathlib.Path(base_rates_path).read_text(
            encoding="utf-8")).get("overall") or {})
    except (json.JSONDecodeError, OSError):
        pass

    # その日いちばん活躍した選手を1人添える。
    #
    # スコアの羅列だけだと「6対5でした」が3回続いて終わる。
    # ヒーローと呼べる日ばかりではないが、最低でもマルチ安打や
    # 奪三振の多い投手はいる。全MLBの採点は既に取ってあるので、
    # その1位を引くだけで済む(こちらで選び直さない)。
    best = ""
    top = arm = None
    # best_of_day.py が採点しているのはMLBの選手だけ。
    #
    # sport を見ずに読んでいたので、サッカーの答え合わせに
    # 「この日いちばんはクロウ、アームストロングで、5打数4安打」が
    # 入っていた。サッカーの動画に打数と本塁打が出る。
    #
    # サッカー側に同じものを出すなら、得点者を別に取ってくることになる。
    # いまは無いので、サッカーは試合結果だけを並べる。
    if sport != "mlb":
        return {
            "kind": "recap",
            "text": f"昨日この番組で選んだ{len(lines)}試合は、こうなりました。"
                    f"{spoken}。今夜の結果も、また明日この時間に出します。",
            "meta": {"lines": [{"matchup": m, "score": sc, "note": n,
                                "won": w}
                               for m, sc, n, _, w in lines[:3]],
                     "base": base},
        }
    try:
        b = json.loads(_p.Path(best_path).read_text(encoding="utf-8"))
        top = (b.get("players") or [None])[0]
        if top and top.get("headline"):
            # 所属を必ず言う。
            #
            # 直前に選んだ3試合を読み上げているので、そこへ名前だけ
            # 続けると、その試合に出ていた選手に聞こえる。実際は
            # MLB全体の1位で、別の試合のことが多い。
            # デグロムはレンジャーズなのに、エンゼルスの試合の直後に
            # 名前だけ出たので、エンゼルスの投手として聞こえていた。
            best = ("この日のMLB全体でいちばんは"
                    f"{_with_team(top)}で、{_spoken_stats(top['headline'])}。")
        # 投手は打者と別枠で持っている。採点に打者の土台点があるため、
        # 混ぜて並べると上位が打者で埋まり、何人抑えた投手がいた日も
        # その話が一度も出てこない。1人だけ、打者の後ろに足す。
        arm = (b.get("pitchers") or [None])[0]
        if arm and arm.get("headline"):
            best += (f"投手では{_with_team(arm)}が"
                     f"{_spoken_stats(arm['headline'])}。")
    except (json.JSONDecodeError, OSError, KeyError, IndexError):
        pass

    tail = best + "明日の結果も、また明日この時間に出します。"
    if base.get("games"):
        tail = (best + "この番組が選んで結果まで記録した試合は、これで"
                f"{base['games']}試合になりました。"
                "明日の結果も、また明日この時間に出します。")
    return {
        "kind": "recap",
        "text": f"昨日この番組で選んだ{len(lines)}試合は、こうなりました。"
                f"{spoken}。{tail}",
        # 読み上げで名前を出した選手は、画面にも出す。
        # 耳だけに残る名前は、聞き取れなかった人には無かったのと同じ。
        "meta": {"lines": [{"matchup": m, "score": sc, "note": n, "won": w}
                           for m, sc, n, _, w in lines[:3]],
                 "base": base,
                 "best": _who(top), "arm": _who(arm)},
    }


def _load(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def build_game_facts(game: dict) -> str:
    """AIに渡す事実だけを列挙する。ここに無い数字は書かせない。"""
    lines = [
        f"対戦: {game.get('home_team_name')} 対 {game.get('away_team_name')}",
        f"開始時刻: {post_common.kickoff_display(game.get('start_time_jst') or '')}"
        f" 日本時間",
    ]
    for r in (game.get("reasons") or [])[:4]:
        if r.get("visible", True) and r.get("text"):
            lines.append(f"注目理由: {r['text']}")

    # 同じ試合を、いくつかの角度から読んだもの。
    #
    # 注目理由は「◯◯が所属」「連勝中」のような1行の事実で、
    # なぜ今日その試合なのかまでは届いていなかった。
    # 順位・勢い・先発・連戦・球場を並べると、シーズンの中の
    # どこにある試合なのかが見える。
    #
    # いちばん効くのは食い違いで、「順位では上だが直近は負け越し」は
    # その日その試合を見る理由そのものになる。先に置く。
    for label, text in perspectives.read(game):
        lines.append(f"{label}から見ると: {text}")
    _t = perspectives.tension(game)
    if _t:
        lines.append(f"見どころ(食い違い): {_t}")
    for key, label in (("home_probable", "ホーム先発"), ("away_probable", "アウェイ先発")):
        p = game.get(key)
        if p and p.get("name"):
            era = f"、今季防御率{p['era']}" if p.get("era") else ""
            lines.append(f"{label}: {p['name']}{era}")
    if game.get("venue_note"):
        lines.append(f"球場: {game.get('venue_jp')}。{game['venue_note']}")
    # コレスポ自身の記録から言えること。予測ではなく、こちらの集計。
    # 「この球場は打高です」と言い切ると根拠の無い断定になるが、
    # 「取り上げた5試合は平均13.4得点でした」なら数えただけの事実で、
    # 読んだ人が自分で先を考えられる。件数を必ず添えるのはそのため。
    if game.get("base_rate_note"):
        lines.append(f"これまでの記録: {game['base_rate_note']}")
    # その時刻・その球場の天気。観測と予報の数字だけを渡す。
    # 「打者有利」のような判断は書かない。風速と風向きがあれば、
    # どう読むかは見る人が決められる。
    if game.get("weather_note"):
        lines.append(f"試合開始時の天気: {game['weather_note']}")
    for n in (game.get("log_notes") or []):
        lines.append(f"見どころ: {n}")

    # 「所属」と「先発予定」は違う、と書き添える。
    #
    # 8/20の回で、両チームに日本人投手が所属している試合を
    # 「日本人投手対決」と紹介してしまった。先発は Peter Lambert と
    # Grayson Rodriguez で、2人とも投げない試合だった。
    #
    # 事実の並びが誘っている。「所属」の行と「先発」の行が別々に
    # 置いてあるだけでは、繋げて読まれる。
    jp_start = any((game.get(k) or {}).get("name_jp")
                   for k in ("home_probable", "away_probable"))
    if not jp_start and sum(1 for x in lines if "が所属" in x) >= 2:
        lines.append("補足: 上の「所属」は在籍しているという意味で、"
                     "この試合に出るとは限りません。先発は上の投手です。")
    return "\n".join(lines)
def narrate_game(client, game: dict, index: int, total: int) -> str:
    facts = build_game_facts(game)
    prompt = (
        "あなたは日本のスポーツ情報番組のナレーション原稿を書く放送作家です。\n"
        "以下の事実だけを使って、読み上げ用の原稿を書いてください。\n\n"
        f"{facts}\n\n"
        "条件:\n"
        f"- これは{total}試合の紹介のうち{index + 1}番目です\n"
        "- 70文字から85文字。短くテンポよく。長い説明は不要\n"
        "- 一番の見どころを1つに絞る。あれもこれも詰め込まない\n"
        "- 耳で聞いて分かる話し言葉。「〜です」「〜ます」調で書く\n"
        "- 上に書かれていない数字・成績・順位は絶対に書かないこと\n"
        "- 「所属」は在籍の意味で、出場や先発とは違う。所属の選手を"
        "「対決」「投げ合い」「登板」と書かないこと\n"
        "- 選手名は上の表記をそのまま使う。英語表記の名前をカタカナに"
        "変換しないこと(日本のメディアの表記と食い違うため)\n"
        "- 記号(【】・「」等)や箇条書きは使わず、そのまま読める文章だけを書く\n"
        "- 前置きや説明は不要。原稿本文のみを出力する"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    token_log.record("narration", MODEL, resp)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", default="notable_games.json")
    parser.add_argument("--news", default="public/news.json")
    parser.add_argument("--best", default="data/best_of_day.json",
                        help="その日いちばん活躍した選手(best_of_day.py の出力)")
    parser.add_argument("--weather", default="data/venue_weather.json",
                        help="球場の天気(venue_weather.py の出力)")
    parser.add_argument("--base-rates", default="data/base_rates.json",
                        help="これまでの実測(scripts/base_rates.py の出力)")
    parser.add_argument("--out", default="public/narration.json")
    parser.add_argument("--archive-dir", default="archive",
                        help="昨日の答え合わせに使う")
    args = parser.parse_args()

    data = _load(args.games, {})
    games = [g for g in data.get("games", []) if g.get("is_notable")][:MAX_GAMES]

    # コレスポがこれまで取り上げた試合の実測を添える。
    # 予測はしない。数えた結果を、件数つきで置くだけ。
    # 天気。取れていなければ、その行が出ないだけ。
    weather = (_load(args.weather, {}).get("venues") or {})
    for g in games:
        w = weather.get(g.get("game_id") or g.get("venue_name") or "")
        if w and w.get("text"):
            g["weather_note"] = w["text"]

    rates = _load(args.base_rates, {})
    if rates:
        import base_rates as _br
        for g in games:
            venue = g.get("venue_jp") or g.get("venue_name")
            note = _br.venue_line(rates, venue) if venue else ""
            if note:
                g["base_rate_note"] = note
    if not games:
        print("[info] 注目試合が無いため、ナレーション原稿は作りません")
        return

    date_label = (games[0].get("start_time_jst") or "").split(" ")[0]
    news = (_load(args.news, {}).get("news") or [])[:1]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    segments = []

    # --- オープニング ---
    # 名乗りから入らず、その日いちばん具体的な事実から入る。
    # 画面側(generate_video.py)も同じ hook を meta 経由で受け取るので、
    # 読み上げと1枚目の表示が必ず一致する。
    # その日にあった試合の総数。サッカーで「何試合中の何試合か」を言う。
    total_today = len([g for g in data.get("games", [])
                       if _is_soccer_league(g.get("league"))])

    hook = pick_hook(games)

    # 1枚目で名乗った試合を、そのまま2枚目に持ってくる。
    #
    # なぜか:
    #   実測の離脱曲線を見ると、どの回も動画の12〜21%地点、およそ8〜14秒で
    #   一気に人が減る。ちょうど1枚目が終わって試合の紹介が始まる位置。
    #
    #   ところが過去17日のうち7日は、冒頭で名前を出した試合が2試合目や
    #   3試合目に置かれていた。「山本由伸 先発予定」で入ってきた人には、
    #   山本の試合が始まる前に別の試合が2つ流れる。崖はその手前にある。
    #   つまり、その人は山本を一度も見ずに去っている。
    #
    #   並びの根拠は点数順だったが、点数の話は最後の画面で別にしている。
    #   「言った試合をすぐ見せる」方を優先する。
    #   画面側(generate_video.py)は notable_games.json をそのまま読むので、
    #   ここで並べ替えるだけだと読み上げと画面が別の試合を指す。
    #   元の位置を覚えて meta で渡す。
    order = list(range(len(games)))
    at = hook.get("at")
    if isinstance(at, int) and 0 < at < len(games):
        games.insert(0, games.pop(at))
        order.insert(0, order.pop(at))
        print(f"[info] 冒頭で名乗った試合を1つ目に移しました "
              f"({at + 1}番目 -> 1番目)")

    # フック文が既に句点で終わっている場合があるので、重ねないよう剥がす
    _big = hook["big"].rstrip("。")
    # 読み上げでは姓だけにする。画面は meta 経由で hook をそのまま受け取るので、
    # フルネームのまま表示される。
    _sub = speech_name(hook["sub"])
    # 画面と題にもカタカナを渡す。
    #
    # これまで読み上げだけカタカナで、画面と題は綴りのままだった。
    # 実測では題の先頭がラテン文字だった回の視聴継続が
    # 16.9% / 19.0% / 19.1% と3本ともそろって低い。
    # 日本からの視聴が97.6%で、検索されるのもカタカナ。
    # 読み上げているのと同じ表記を出す。
    hook = dict(hook, sub_jp=display_name(hook.get("sub", "")))
    lead = f"{_sub}は{_big}。" if _sub else f"{_big}。"

    # 冒頭は「具体的な事実 → 何の動画か」の順で、2文だけにする。
    #
    # 以前は「コレスポ、8月12日の注目試合です」と名乗りと日付を読んでいた。
    # 日付は画面にも出ているので聞かせる必要が無く、名乗りは最後にもある。
    # 直近28日のショートは40.6%が途中でスワイプされており、
    # 最初の数秒に中身の無い時間を置く余裕は無い。
    #
    # 代わりに「これから何本の試合を、どういう基準で見るのか」を置く。
    # 続けて見る理由になるのは名乗りではなくこちら。
    segments.append({
        "kind": "intro",
        # サッカーは「今夜あるうちの何試合か」を添える。
        #
        # 欧州は日によって0試合の日も19試合の日もある。3試合と言われても、
        # それが全部なのか一部なのかが分からない。全体の数が分かれば、
        # 選んだという行為の意味も伝わる。
        # MLBは毎日15試合前後で変わらないので、そちらには足さない。
        "text": f"{lead}{_how_many(games, total_today)}",
        # 1枚目にその日いちばんの試合も渡す。画面の下半分が空いており、
        # 「で、どの試合なの」に答えられていなかった。
        "meta": {"date_label": date_label, "hook": hook,
                 "top_game": _top_game_meta(games)},
    })
    print(f"[info] 冒頭のフック: {lead}")

    # --- 各試合 ---
    if api_key and anthropic is not None:
        client = anthropic.Anthropic(api_key=api_key)
        for i, g in enumerate(games):
            try:
                text = narrate_game(client, g, i, len(games))
            except Exception as e:
                print(f"[warn] 原稿生成に失敗、簡易版で代替します: {e}", file=sys.stderr)
                text = None
            if not text:
                text = _fallback_game_text(g)
            segments.append({"kind": "game", "text": text,
                             "meta": {"game_index": order[i], "order": i}})
    else:
        print("[info] ANTHROPIC_API_KEY未設定のため、簡易的な原稿で生成します")
        for i, g in enumerate(games):
            segments.append({
                "kind": "game",
                "text": _fallback_game_text(g),
                "meta": {"game_index": order[i], "order": i},
            })

    # --- 昨日の答え合わせ ---
    #
    # 毎回その日で完結していると、明日また来る理由が無い。実際、
    # 48時間で3,995回見られて登録は+2人だった(0.054%。ショートの
    # 一般的な転換率0.3〜0.8%の10分の1)。
    #
    # コレスポは「なぜ注目か」を書いて出しているので、その検算ができる。
    # 昨日出した3試合がどうなったかを見せれば、「言いっぱなしではない」が
    # 毎日示せる。他所には出せない内容でもある。
    #
    # 置く場所はアウトロの直前。冒頭のフックは動画で最も重要なので、
    # そこと本編の間には何も挟まない。
    recap = _yesterday_recap(args.archive_dir, games,
                             args.base_rates, args.best)
    if recap:
        segments.append(recap)

    # --- コレスポ指数 ---
    # なぜこの試合を選んだのかは、実際には点数で決まっている。
    # その基準を隠さずに見せる。独自の指標なので他所には出せない内容になる。
    if any(g.get("score") for g in games):
        top = max(games, key=lambda g: g.get("score") or 0)
        # 何に点をつけているかは競技で違う。サッカーは連勝記録が取れない
        # (無料枠にフォームデータが無い)ので、そこを挙げると嘘になる。
        soccer = any(_is_soccer_league(g.get("league")) for g in games)
        basis = ("日本人選手の所属、順位、伝統の一戦かどうか" if soccer
                 else "日本人選手の出場、順位争い、連勝記録")
        segments.append({
            "kind": "score",
            "text": f"コレスポは、{basis}などに"
                    "点数をつけて注目試合を選んでいます。"
                    f"今日の最高点は{top.get('score')}点、"
                    f"{top.get('home_team_name')}対{top.get('away_team_name')}でした。",
            "meta": {},
        })

    # --- ニュース(検証済みのものだけ) ---
    for n in news:
        segments.append({"kind": "news", "text": n["text"] + "です。", "meta": {}})

    # --- クロージング ---
    segments.append({
        "kind": "outro",
        # 日次のアウトロ。翌日に結果の枠があるので、そこへ繋ぐ。
        # 「毎日19時に出しています」という説明より、
        # 次に何が見られるかを言う方が、登録する理由になる。
        #
        # 「朝」と言っていたが、実際に出るのは16時半。MLBの最終試合が
        # 終わるのがJST 14時25分ごろなので、朝の時点ではその日の成績が
        # まだ揃っていない。言えない時刻を約束しない。
        #
        # 「方」は「ほう」と読まれるため仮名で書く。
        "text": "明日の夕方には、日本人選手の成績と現地の反応を出します。"
                "毎日見たいかたは、チャンネル登録をお願いします。",
        "meta": {},
    })

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"date_label": date_label, "segments": segments}, f, ensure_ascii=False)

    total_chars = sum(len(s["text"]) for s in segments)
    print(f"[info] ナレーション原稿を生成しました({len(segments)}セグメント、"
          f"計{total_chars}文字、読み上げ推定{total_chars / 6:.0f}秒) -> {out}")


def _fallback_game_text(game: dict) -> str:
    """AIが使えない場合の、事実の読み上げだけの原稿"""
    parts = [
        f"{post_common.kickoff_display(game.get('start_time_jst') or '')}から、"
        f"{game.get('home_team_name')}対{game.get('away_team_name')}。"
    ]
    # 角度から読んだものを先に。無い日は元の注目理由に落ちる。
    #
    # ここは1試合70〜85字に収める枠なので、1つだけ選ぶ。
    # 食い違いがあればそれが最も強い。無ければ最初の角度。
    said = perspectives.tension(game)
    if said:
        parts.append(said)
    else:
        got = perspectives.read(game, limit=1)
        if got:
            parts.append(got[0][1])
    if len(parts) == 1:
        for r in (game.get("reasons") or [])[:2]:
            if r.get("visible", True) and r.get("text"):
                parts.append(r["text"] + "。")
    return "".join(parts)


if __name__ == "__main__":
    main()
