#!/usr/bin/env python3
"""
その日のハイライトとコメント欄から、対話の台本を作る。

なぜ対話にするのか:
  短編は「読み上げる」形式で、断りも留保も入れる場所が無い。
  「翻訳したもので、コレスポの見解ではありません」を毎回読んでいるが、
  定型文として流れていく。

  対話なら、断りが台詞になる。
    ずんだもん「これ、コレスポが言ってるのだ？」
    解説「いえ、現地の方が書いたことの翻訳です」
  同じ内容が、はるかに届く。

  そして問える相手がいると、面白い所で止まれる。
  防御率が0.05動いただけで中継が「急上昇」と出した話は、
  45秒の短編では説明する尺が無くて落ちていた。

誰が何を言うか:
  ずんだもん … 問いと相槌だけ。**何も断言しない。**
                問いは主張ではないので、事実の負担が増えない。
  解説        … 敬語。渡した数字と、翻訳したものだけを話す。
                「詳しい人」ではなく「調べたことを話す人」。

材料の渡し方:
  モデルにAPIを触らせない。データ→事実→言葉の順で、
  モデルは最後の一段だけを担当する。

  試しに書いた台本で「1978年に防御率1.74を記録した投手です」と
  書いたが、それは渡した材料に無い知識だった。裏を取ったら
  正しかったものの、それは運であって仕組みではない。
  同じことをモデルにさせれば、いつか間違える。しかも
  具体的な数字は、間違っていても本当らしく聞こえる。

  だからコメントに出てくる選手名をコードで拾い、
  MLB公式APIで数字を引いてから渡す(enrich)。
  「リーグでも指折り」は判断だが、「MLB全体で1位」は事実。

出力: build/dialogue.json（synthesize_narration.py が読む形）

使い方:
  ANTHROPIC_API_KEY=xxx python3 scripts/generate_dialogue.py \
      --out build/dialogue.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import textkey  # noqa: E402
import token_log  # noqa: E402

try:
    import anthropic
except ImportError:
    anthropic = None

# 台本だけ、いちばん良いモデルを使う。
#
# ここはニュアンスの仕事で、他の呼び出し（翻訳・要約・検算）とは
# 求めているものが違う。実際 Haiku の台本には、
#   ・コメントの意味を勝手に補う（「無名だということ」）
#   ・答えられない問いを立てて「分からないわね」で終わる
#   ・実にならない相槌が続く
# という形が繰り返し出た。指示を足しても、書き手の読みの浅さは
# 指示では埋まらない。
#
# 費用（入力6534/出力2000トークンの実測から、1日1本）:
#   Haiku 4.5  $1/$5    1本 $0.017  月 $0.50
#   Sonnet 5   $2/$10   1本 $0.033  月 $0.99
#   Opus 5     $5/$25   1本 $0.083  月 $2.48（考える分込みで月$4程度）
#
# API代の合計が月$1.34なので3倍以上になるが、それでも月$5。
# 1日1回しか呼ばないところで、ここをけちる理由が無い。
#
# 翻訳・検算・多言語化は回数が多いので Haiku のまま。
# 環境変数で差し替えられる。**比べるため。**
#
#   COLLESPO_DIALOGUE_MODEL=claude-sonnet-5  で1本作って見比べる
#
# 「Haikuからいきなり Opus か」は、もっともな問い。
# 間に Sonnet 5 があって、費用は Opus の 2.5分の1。
# ただし**どれが良いかは出来上がりを見ないと分からない**ので、
# 切り替えを1行にしておく。コードを触らずに戻せる。
MODEL = os.environ.get("COLLESPO_DIALOGUE_MODEL") or "claude-opus-5"
MLB_API = "https://statsapi.mlb.com/api/v1"

# 話者ID(VOICEVOX)。
#
# ずんだもんと四国めたんは、どちらも表記さえ出せば商用も可。
# 青山龍星のほうが解説役の声には合うが、個人事業主・法人契約は
# 許諾が要る。許諾が要るものを、自動で投稿する仕組みに入れない。
SPEAKER_ZUNDA = 3
SPEAKER_EXPLAIN = 2

# コメントから拾う名前の最短の長さ。
# 3文字以下だと "Sale" のような普通名詞と衝突する。
MIN_NAME = 5

# 1本で扱うコメントの数。
#
# 4本にしていたが、出来た台本は939字・1分46秒にしかならなかった。
# 3分に要るのは約1600字。**言葉を厚くするより、材料を増やす。**
# 水増しした一言は、聞けば分かる。
MAX_COMMENTS = 6

# 3分の動画に要る字数。実測から出した。
#
#   939字 → 106秒（ずんだもん1.5倍速・めたん1.35倍速）
#   つまり 8.9字/秒。180秒なら約1600字。
TARGET_CHARS = 1600
MIN_CHARS = 1250


def _get(url: str, timeout: int = 20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def find_players(texts: list) -> list:
    """コメントに出てくる選手名らしきものを拾う。

    ラテン文字の固有名詞だけを見る。日本語のコメントは訳文なので、
    そちらから拾うと訳のゆれをそのまま引くことになる。
    原文のほうが綴りが安定している。
    """
    try:
        from notability_engine import MLB_TEAM_NAME_EN
        teams = {textkey.key(v) for v in MLB_TEAM_NAME_EN.values() if v}
        teams |= {textkey.key(w) for v in MLB_TEAM_NAME_EN.values()
                  for w in str(v).split()}
    except ImportError:
        teams = set()
    seen, out = set(), []
    for t in texts:
        for m in re.finditer(r"[A-Z][a-zA-Z" + chr(39) + "À-ɏ-]{" +
                             str(MIN_NAME - 1) + r",}", t or ""):
            # 「Misiorowski's」の所有格を落とす。付いたままだと
            # 順位表の名前と一致しない。
            w = re.sub(r"[" + chr(39) + chr(8217) + r"]s$", "", m.group(0))
            k = textkey.key(w)
            if k in seen or k in teams:
                continue          # 球団名は選手ではない
            seen.add(k)
            out.append(w)
    return out


def _roster_team(name: str,
                 roster_path: str = "data/roster_snapshot.json") -> str:
    """手元の名簿から所属を引く。姓だけでも当てる。引けなければ空。

    名簿は毎朝取っていて1400人ぶんある。APIを叩く前にここを見る。

    **同じ姓が2人いたら諦める。**取り違えは「調べていない」より悪い。
    """
    try:
        from notability_engine import MLB_TEAM_NAME_JP
        ros = json.loads(pathlib.Path(roster_path).read_text(
            encoding="utf-8")).get("players") or {}
    except Exception:                                # noqa: BLE001
        return ""
    key = textkey.key(name)
    hits = set()
    for v in ros.values():
        full = v.get("name") or ""
        if textkey.key(full) == key or textkey.key(
                textkey.surname(full) or "") == key:
            hits.add(str(v.get("team_id") or ""))
    if len(hits) != 1:
        return ""
    return MLB_TEAM_NAME_JP.get(hits.pop(), "")


def team_standing(jp_name: str,
                  postseason_path: str = "data/postseason.json") -> dict:
    """その球団のいまの勝敗と、リーグでの立ち位置。引けなければ空。

    「レッズは今日勝率.479で、ナ・リーグ中地区最下位」のように、
    **対戦している側の球団自身の強さ**を言うのに要る。
    比較のコメントに数字で返すには、比べられている側だけでなく、
    比べている側（＝いま見ている試合の球団）の数字も要る。
    """
    try:
        teams = json.loads(pathlib.Path(postseason_path).read_text(
            encoding="utf-8")).get("teams") or {}
    except Exception:                                # noqa: BLE001
        return {}
    for t in teams.values():
        if t.get("name") == jp_name:
            return t
    return {}


def team_mentions(texts: list, exclude_jp: set,
                  postseason_path: str = "data/postseason.json") -> list:
    """コメント・返信に出てくる、対戦の2球団以外の球団と、いまの勝率。

    なぜ要るのか:
      「CincinnatiはGiantsやRockies、Angelsより良くやってる」という
      返信は、比べている側がどれだけ弱いのかが分からないと
      意味が取れない。渡していなかったので、台本はこの返信を
      そのまま読むだけで終わっていた。

      勝率はもう毎日 postseason.py が取っている順位表にある。
      比較に出てきた球団だけを渡す。全30球団を渡すと埋もれる。
    """
    try:
        from notability_engine import MLB_TEAM_NAME_EN, MLB_TEAM_NAME_JP
        teams = json.loads(pathlib.Path(postseason_path).read_text(
            encoding="utf-8")).get("teams") or {}
    except Exception:                                # noqa: BLE001
        return []
    # 「Red Sox」「White Sox」「Blue Jays」のような2語の愛称。
    # 最後の1語(「Sox」「Jays」)だけでは他球団と紛れる。
    TWO_WORD = {"Red Sox", "White Sox", "Blue Jays"}
    text = " ".join(t for t in texts if t)
    out, seen = [], set(exclude_jp)
    for tid, en in MLB_TEAM_NAME_EN.items():
        jp = MLB_TEAM_NAME_JP.get(tid, en)
        if jp in seen:
            continue
        words = en.split()
        two = " ".join(words[-2:])
        nick = two if two in TWO_WORD else words[-1]
        # 都市名（先頭の語）でも当たるようにする。「Cincinnati」は
        # 「Reds」とは別の綴りで出てくることがある。
        candidates = [nick] + [w for w in words[:-1] if len(w) >= 5]
        # 大小文字は問わない。コメントは「giants」のように
        # 小文字で書かれることがある。
        if not any(re.search(r"\b" + re.escape(c) + r"\b", text, re.I)
                  for c in candidates):
            continue
        t = teams.get(tid) or {}
        if not t.get("w"):
            continue
        seen.add(jp)
        out.append({"name": jp, "w": t["w"], "l": t["l"],
                    "pct": t.get("pct")})
    return out


def lookup(name: str) -> dict:
    """その選手の、確かめられる数字。引けなければ空。

    people/search で人を特定し、リーグの順位表に載っていれば
    その順位も付ける。ここで返すものだけが台本に出てよい。
    """
    try:
        d = _get(f"{MLB_API}/people/search?names="
                 + urllib.parse.quote(name))
    except Exception:                            # noqa: BLE001
        return {}
    ppl = d.get("people") or []
    if len(ppl) != 1:
        # 同姓が複数いるときは諦める。取り違えるくらいなら出さない。
        return {}
    p = ppl[0]
    return {"name": p.get("fullName"), "id": p.get("id"),
            "pos": (p.get("primaryPosition") or {}).get("abbreviation", "")}


def leaders(category: str, group: str, limit: int = 30) -> dict:
    """リーグ上位。名前で引けるように辞書にして返す。"""
    try:
        d = _get(f"{MLB_API}/stats/leaders?leaderCategories={category}"
                 f"&season={os.environ.get('MLB_SEASON', '2026')}"
                 f"&sportId=1&limit={limit}&statGroup={group}")
    except Exception:                            # noqa: BLE001
        return {}
    # 姓でも引けるようにする。コメントに出るのは姓だけのことが多い
    # (「Misiorowski's ERA」)。順位表はフルネームで返ってくる。
    out = {}
    for cat in d.get("leagueLeaders") or []:
        for x in cat.get("leaders") or []:
            nm = (x.get("person") or {}).get("fullName")
            if not nm:
                continue
            v = (x.get("rank"), x.get("value"), nm)
            out[textkey.key(nm)] = v
            last = textkey.surname(nm)
            if last:
                # 同姓が2人いたら、姓では引けなくする。取り違えは
                # 「調べていない」より悪い。
                lk = textkey.key(last)
                out[lk] = None if lk in out and out[lk] != v else v
    return {k: v for k, v in out.items() if v}


def team_of(name: str) -> str:
    """その選手のいまの所属。引けなければ空。

    なぜ要るのか:
      コメントに出てくる選手の所属を、モデルが対戦カードから
      推測して外していた。「これはタイガースの打者の話」と
      書かれた Kyle Tucker は、実際はドジャースの選手。

      禁じるだけでは足りない。**引いて渡せば推測する必要が無い。**
      people/search で人を特定し、そこから現所属を取る。
      同姓が複数いるときは諦める（取り違えは「調べていない」より悪い）。
    """
    # まず手元の名簿を見る。**その日の朝に取ったものが既にある。**
    #
    # ここは1人につきAPIを2回叩く。返信も見るようにして名前が
    # 増えたので、1本あたり20回になっていた。名簿(1400人)に
    # 載っていれば0回で済む。載っていない選手だけAPIへ行く。
    hit = _roster_team(name)
    if hit:
        return hit
    try:
        d = _get(f"{MLB_API}/people/search?names="
                 + urllib.parse.quote(name))
        ppl = d.get("people") or []
        if len(ppl) != 1:
            return ""
        pid = ppl[0].get("id")
        q = _get(f"{MLB_API}/people/{pid}?hydrate=currentTeam")
        en = ((q.get("people") or [{}])[0].get("currentTeam")
             or {}).get("name", "") or ""
        if not en:
            return ""
        # 日本語名に直す。英語のままだと、他は全部日本語なのに
        # ここだけ「Toronto Blue Jays」と混じって出る。
        try:
            from mlb_buzz import jp_team
            return jp_team(en)
        except ImportError:
            return en
    except Exception:                            # noqa: BLE001
        return ""


def enrich(comments: list) -> list:
    """コメントに出てくる選手について、確かめられる数字を集める。

    ここが「渡していない知識を語らせない」ための仕掛け。
    モデルに調べさせるのではなく、コードが調べてから渡す。
    """
    names = find_players([c.get("title", "") for c in comments])
    if not names:
        return []
    era = leaders("earnedRunAverage", "pitching")
    ops = leaders("onBasePlusSlugging", "hitting")
    out = []
    for n in names[:6]:
        k = textkey.key(n)
        rank = era.get(k) or ops.get(k)
        if not rank:
            continue
        stat = "防御率" if k in era else "OPS"
        # 順位表が返したフルネームをそのまま使う。
        # people/search を挟むと同姓で外れることがあり、
        # 順位表の名前のほうが確かめた出どころに近い。
        out.append({"name": rank[2], "stat": stat,
                    "rank": rank[0], "value": rank[1]})
        print(f"[info] {rank[2]}: {stat} リーグ{rank[0]}位 {rank[1]}")
    return out


def material(buzz_path: str, voices_path: str) -> dict:
    """台本の材料。全て取得済みのものだけ。"""
    def load(p):
        try:
            return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    b, v = load(buzz_path), load(voices_path)
    vids = b.get("videos") or []
    if not vids:
        return {}

    # どの動画を扱うかは mlb_buzz が決めている。
    # ここで選び直すと、local_voices が集めたコメントと
    # 別の動画になる。**並べ替えは1か所。**
    top = vids[0]
    voices = (v.get("voices") or [])[:MAX_COMMENTS]
    # コメントに日本人選手が出ていたら、その名前を残す。
    #
    # 28日間の実測で、**題に日本人選手の名前が入っている動画は
    # 再生が2.8倍（468回 vs 168回）、登録者は12人 vs 0人**だった。
    # チャンネルの登録者14人のうち12人がこの形から来ている。
    # ここまではっきり差が出ているものを、題で使わない手は無い。
    jp = []
    try:
        import mentioned
        for c in voices:
            src = (c.get("title") or "") + " " + " ".join(
                (r.get("text") or "") for r in (c.get("reply") or []))
            # **日本人選手だけ。** mentioned.find は MLB全体の名簿を
            # 見るので Tarik Skubal も返す。題に出すのは
            # 「日本人選手の名前」なので、そこを絞る。
            for nm in mentioned.japanese_in(src):
                if nm not in jp:
                    jp.append(nm)
    except Exception as e:                       # noqa: BLE001
        print(f"[info] 日本人選手の拾い出しを飛ばします({e})")
    if jp:
        print("[info] コメントに出ている日本人選手: " + "、".join(jp))
    # コメントに出てくる選手の所属を、こちらで引いておく。
    # 渡さないと、モデルが対戦カードから推測して外す。
    #
    # 返信の原文も見る。以前はコメント本文(title)しか見ておらず、
    # 返信で名前が出てきた選手（「Dylan Cease」のような）は
    # 所属を引く機会が無かった。原文は reply_texts、または
    # reply_ja[].original に入っている。
    texts = []
    for c in voices:
        texts.append(c.get("title", ""))
        texts += c.get("reply_texts") or []
        texts += [r.get("original", "") for r in (c.get("reply_ja") or [])]
    teams = {}
    for n in find_players(texts)[:10]:
        tm = team_of(n)
        if tm:
            teams[n] = tm
            print(f"[info] {n}: {tm}")

    # コメント・返信に出てくる、対戦の2球団以外の球団の勝率。
    # 「CincinnatiはGiantsより良くやってる」のような比較コメントは、
    # 比べている側の弱さが分からないと意味が取れない。
    exclude = set()
    if top.get("result"):
        exclude = {top["result"].get("away_jp"), top["result"].get("home_jp")}
    others = team_mentions(texts, exclude)
    if others:
        print("[info] コメントに出てくる他球団: "
             + "、".join(f"{o['name']}{o['pct']}" for o in others))

    return {"top": top, "voices": voices, "teams": teams, "jp": jp,
            "other_teams": others, "source": v.get("source", "")}


def situation(m: dict) -> dict:
    """その日の試合と、コメント欄の空気。**コードで決める。**

    なぜここでやるのか:
      台本が「コメントの長さ」の話になった日があった。
      いちばん短いコメント、いちばん長い返信——それはそれで
      面白いが、**その日の試合が何だったかと関係が無い。**
      材料をただ順に読むと、いつでも成り立つ形に落ちる。

      10対1の大敗で、コメント欄が荒れ気味。これはこの日にしか
      無い状況で、話し方もそこから決まる。接戦の日、誰かが
      大記録を作った日、打ち合いの日では、コメント欄の空気も、
      2人が話すことも変わる。

      **判定はコードでやる。**モデルに「今日はどういう日か」を
      決めさせると、材料に無いことを根拠にし始める。
      点差も、失策も、コメントの調子も、もう手元にある数字。
    """
    res = m.get("top", {}).get("result") or {}
    a, h = res.get("away_score"), res.get("home_score")
    out = {"shape": "", "flow": "", "mood": "", "notes": []}
    if isinstance(a, int) and isinstance(h, int):
        margin, total = abs(a - h), a + h
        win = res.get("home_jp") if h > a else res.get("away_jp")
        lose = res.get("away_jp") if h > a else res.get("home_jp")
        out["win"], out["lose"] = win, lose
        out["margin"], out["total"] = margin, total
        if margin >= 6:
            out["shape"] = f"{margin}点差の大差。{lose}の大敗"
        elif margin <= 1:
            out["shape"] = f"{margin}点差の接戦"
        else:
            out["shape"] = f"{margin}点差"
        if total >= 12:
            out["shape"] += "。両軍で%d点入った打ち合い" % total
        elif total <= 3:
            out["shape"] += "。両軍で%d点しか入らない投手戦" % total

        # 点の入り方。序盤で決まったのか、終盤に動いたのか。
        inn = [i for i in (res.get("innings") or []) if i.get("num")]
        wk = "home" if h > a else "away"
        lk = "away" if h > a else "home"
        run_w = run_l = 0
        decided = None
        for i in inn:
            run_w += i.get(wk) or 0
            run_l += i.get(lk) or 0
            if decided is None and run_w - run_l >= 3:
                decided = i["num"]
        if decided:
            when = ("序盤" if decided <= 3 else
                    "中盤" if decided <= 6 else "終盤")
            out["flow"] = f"{when}（{decided}回）には{win}が3点差をつけていた"
        # 追いかけた側が一度でも前に出ていたか
        run_w = run_l = 0
        for i in inn:
            run_w += i.get(wk) or 0
            run_l += i.get(lk) or 0
            if run_l > run_w:
                out["flow"] += f"。{lose}が先に前に出た回もある"
                break

    # 守備と安打。大敗の日はここに理由が出ていることが多い。
    for side, key in (("away_jp", "away"), ("home_jp", "home")):
        e = res.get(key + "_errors")
        if isinstance(e, int) and e >= 2:
            out["notes"].append(f"{res.get(side)}は失策{e}")

    # コメント欄の調子。local_voices が1件ずつ付けている。
    tones = {}
    for c in m.get("voices") or []:
        tones[c.get("tone") or "中立"] = tones.get(c.get("tone") or "中立",
                                                   0) + 1
    n = sum(tones.values())
    if n:
        neg, pos = tones.get("批判", 0), tones.get("称賛", 0)
        if neg >= max(2, n * 0.6):
            out["mood"] = f"{n}件中{neg}件が批判寄り。荒れ気味"
        elif pos >= max(2, n * 0.6):
            out["mood"] = f"{n}件中{pos}件が称賛寄り"
        elif neg and pos:
            out["mood"] = f"称賛{pos}件と批判{neg}件で割れている"
        else:
            out["mood"] = f"{n}件、目立った偏りは無い"
    out["tones"] = tones
    return out


def angle(sit: dict) -> list:
    """その日の切り口。situation から、話の軸を1つに決める。

    「どう料理するか」をここで決めておかないと、材料を順に
    読むだけの台本になる。**軸は1つ。**2つ立てると散る。
    """
    m = sit.get("margin")
    lose, win = sit.get("lose", ""), sit.get("win", "")
    if m is None:
        return ["軸: コメント欄でいちばん支持されている見方と、"
                "それに反対している返信。**その2つのぶつかりを追う。**"]
    if m >= 6:
        return [
            f"軸: **{lose}のファンが、この負けをどう受け止めているか。**",
            "大敗の日は、コメント欄が試合そのものより「ファンの心境」になる。",
            f"{win}を褒める話に寄せない。コメント欄がそこを見ていない。",
            "同じ負けに対して、突き放す人・かばう人・笑う人が並んでいるはず。"
            "**その温度差を並べる。**",
        ]
    if m <= 1:
        return [
            "軸: **どこで決まったか。**接戦の日は、1点の出入りが全部の意味を持つ。",
            "コメント欄も勝った側と負けた側で割れているはず。両方出す。",
        ]
    if (sit.get("total") or 0) >= 12:
        return [
            "軸: **点の取り合いそのもの。**投手が何人も出た試合なので、"
            "コメント欄は継投の話になりやすい。",
        ]
    if (sit.get("total") or 0) <= 3:
        return [
            "軸: **投げ合い。**点が入らない試合は、1点の重みが主題になる。",
            "両先発投手の投球内容から入る。",
        ]
    return [
        "軸: **コメント欄でいちばん支持されている見方と、それへの反論。**",
        "賛否が割れているところを1つ選んで、そこを掘る。",
    ]


def facts(m: dict, extra: list) -> str:
    """モデルに渡す事実。ここに無いことは書かせない。"""
    top = m["top"]
    res = top.get("result") or {}
    lines = [
        "## その日いちばん見られたハイライト（MLB公式チャンネルの動画）",
        "※ この動画を出しているのはMLB公式であって、コレスポではない。",
        "  コレスポは、その動画とコメント欄を毎日見て話す番組。",
        "  「うちのハイライト」「このチャンネルのハイライト」とは言わない。",
        f"動画の題（原文）: {top.get('title') or ''}",
        f"何の試合か: {top.get('topic_jp') or top.get('matchup')}",
        f"再生回数: {top.get('views', 0):,}回",
    ]
    if res.get("away_jp"):
        lines.append(f"結果: {res['away_jp']} {res.get('away_score')} "
                     f"- {res.get('home_score')} {res['home_jp']}")
        # 対戦している2球団自身の、いまの勝敗と地区順位。
        # コメントが「Cincinnatiはあそこよりマシ」のように自チームの
        # 強さを主張していたら、その主張を数字で受けられるようにする。
        for jp in (res["away_jp"], res["home_jp"]):
            st = team_standing(jp)
            if st.get("w"):
                where = st.get("division", "")
                if st.get("div_rank"):
                    where += f"{st['div_rank']}位"
                lines.append(
                    f"{jp}のいまの成績: {st['w']}勝{st['l']}敗"
                    f"（勝率{st.get('pct')}"
                    + (f"、{where}" if where else "") + "）")
    if top.get("game_date"):
        lines.append(f"試合が行われた日（現地）: {top['game_date']}")
    inn = [i for i in (res.get("innings") or []) if i.get("num")]
    if inn:
        # **回ごとの得点は画面のスコアボードに出る。口では言わない。**
        # 以前は「1回に2点、2回に1点で3点先取…」と全部読み上げていた。
        # 冗長なうえ、タイトル・サムネイルで本題(コメント欄)を
        # 見に来た人にとって、序盤の説明が長すぎた。
        lines.append("回ごとの得点(先攻/後攻・画面のスコアボードに出るので"
                     "逐一読み上げない): "
                     + " ".join(f"{i.get('away')}" for i in inn)
                     + " / " + " ".join(f"{i.get('home')}" for i in inn))
    # 安打と失策。**大敗の日は、たいていここに理由が出ている。**
    if isinstance(res.get("away_hits"), int):
        lines.append(f"安打: {res['away_jp']} {res['away_hits']}本 / "
                     f"{res['home_jp']} {res.get('home_hits')}本")
    if isinstance(res.get("away_errors"), int):
        lines.append(f"失策: {res['away_jp']} {res['away_errors']} / "
                     f"{res['home_jp']} {res.get('home_errors')}")
    # 両先発投手。**必ず両方渡す。**
    #
    # コメント欄は先発投手の名前で盛り上がることが多い
    # (「Mizeは災厄だった」)。目立った選手(star)は打者・投手どちらか
    # 1人しか選ばれないので、別に渡す。これがあることで、
    # 先発投手を名指しするコメントに中身のある返しができる。
    for side, label in (("away", "先攻"), ("home", "後攻")):
        st = res.get(side + "_starter")
        if st:
            lines.append(f"{label}の先発投手: "
                         f"{st['name']}（{st['team']}） {st['line']}")
    if res.get("star_name"):
        # 所属を必ず書く。書かないとモデルが対戦カードから推測して外す。
        team = res.get("star_team")
        who = f"{res['star_name']}（{team}）" if team else res["star_name"]
        lines.append(f"目立った選手: {who} {res.get('star_line', '')}")
        if not team:
            lines.append("※ この選手がどちらのチームかは分かっていません。"
                         "どちらの所属かを書かないでください")

    lines += ["", f"## コメント欄（{m.get('source')}・翻訳）"]
    for i, c in enumerate(m["voices"], 1):
        lines.append(f"{i}. [{c.get('tone', '中立')} "
                     f"高評価{c.get('likes', 0)}件 "
                     f"返信{c.get('replies', 0)}件] {c.get('ja', '')}")
        for r in (c.get("reply_ja") or [])[:2]:
            lines.append(f"   返信: {r.get('ja', '')}")

    if m.get("teams"):
        lines += ["", "## コメントに出てくる選手の、いまの所属（MLB公式）",
                  "**ここに書いてある所属だけを使うこと。**",
                  "書いていない選手は、どこの所属かに触れない。",
                  "対戦カードから推測しない"]
        for n, tm in m["teams"].items():
            lines.append(f"- {n}: {tm}")

    if m.get("other_teams"):
        lines += ["", "## コメントに出てくる、対戦の2球団以外の球団の勝率"
                  "（MLB公式）",
                  "比較のコメント（「あそこよりマシだ」のような）に"
                  "根拠を付けるための数字。使わなくてもよい"]
        for o in m["other_teams"]:
            lines.append(f"- {o['name']}: {o['w']}勝{o['l']}敗"
                         f"（勝率{o['pct']}）")

    if extra:
        lines += ["", "## コメントに出てくる選手の、確かめた数字",
                  "（MLB公式のリーグ順位。これ以外の経歴・記録は書かないこと）"]
        for e in extra:
            lines.append(f"- {e['name']}: {e['stat']} "
                         f"リーグ{e['rank']}位（{e['value']}）")

    # その日がどういう日か。**上の数字から機械的に出したもので、
    # 新しい事実ではない。**話の軸をここで1つに決める。
    sit = situation(m)
    lines += ["", "## 今日はどういう日か（上の数字から判定したもの）"]
    if sit.get("shape"):
        lines.append(f"試合の形: {sit['shape']}")
    if sit.get("flow"):
        lines.append(f"点の入り方: {sit['flow']}")
    for n in sit.get("notes") or []:
        lines.append(f"目につく数字: {n}")
    if sit.get("mood"):
        lines.append(f"コメント欄の空気: {sit['mood']}")
    lines += ["", "## この日の切り口"] + angle(sit)
    return "\n".join(lines)


def panels(m: dict, extra: list) -> dict:
    """画面中央に出す情報の札。台詞と対応させるための鍵つき。

    なぜここで作るのか:
      16:9の画面は、左右に人・下に台詞を置くと、真ん中が丸ごと空く。
      そこに「いま話していること」を出したい。

      ただし**中身をモデルに作らせない**。作らせると、画面に映る
      数字が台詞と同じ根拠を持たなくなる。ここで事実から組み立てて、
      モデルには「どれを出すか」の鍵だけを選ばせる。
      知らない鍵を返してきたら、その指定は捨てる(前の札のまま)。
    """
    top, res = m["top"], (m["top"].get("result") or {})
    out = {"topic": {"type": "topic",
                     "topic": top.get("topic_jp")
                              or top.get("matchup") or "MLB"}}

    if res.get("away_jp") and res.get("home_jp"):
        out["score"] = {
            "type": "score",
            "away": res["away_jp"], "home": res["home_jp"],
            "away_score": res.get("away_score"),
            "home_score": res.get("home_score"),
            "innings": [i for i in (res.get("innings") or []) if i.get("num")],
        }
    if top.get("views"):
        out["views"] = {
            "type": "views",
            "title": top.get("topic_jp") or top.get("matchup") or "",
            "views": top.get("views"),
        }
    if res.get("star_name"):
        out["star"] = {
            "type": "star", "name": res["star_name"],
            "team": res.get("star_team") or "",
            "line": res.get("star_line") or "",
        }
    # 両先発投手。scoreと同じ「star」の見た目で足りる
    # (名前・所属・成績の3段)ので、新しい画面は作らない。
    for side, key in (("away", "starter_away"), ("home", "starter_home")):
        st = res.get(side + "_starter")
        if st:
            out[key] = {"type": "star", "name": st["name"],
                       "team": st["team"], "line": st["line"]}
    for i, c in enumerate(m.get("voices") or [], 1):
        if not c.get("ja"):
            continue
        out["comment%d" % i] = {
            "type": "quote", "text": c["ja"],
            "tone": c.get("tone") or "", "likes": c.get("likes") or 0,
            "replies": c.get("replies") or 0,
            "source": m.get("source") or "",
        }
    for i, e in enumerate(extra, 1):
        out["stat%d" % i] = {
            "type": "stat", "name": e["name"], "stat": e["stat"],
            "rank": e["rank"], "value": e["value"],
        }
    return out


def panel_menu(ps: dict) -> str:
    """モデルに見せる、鍵の一覧。ここに無い鍵は書かせない。"""
    label = {"score": "回ごとの得点と最終スコア（画面がスコアボード。"
                      "口では逐一読まない）",
             "views": "その動画の再生回数",
             "star": "目立った選手の成績",
             "starter_away": "先攻の先発投手の成績",
             "starter_home": "後攻の先発投手の成績",
             "topic": "きょうの話（締めに使う）"}
    rows = []
    for k, v in ps.items():
        if v["type"] == "quote":
            rows.append(f"[{k}] コメント: {v['text'][:34]}")
        elif v["type"] == "stat":
            rows.append(f"[{k}] {v['name']}の{v['stat']}")
        else:
            rows.append(f"[{k}] {label.get(k, k)}")
    return "\n".join(rows)


PROMPT = """あなたは、日本語のスポーツ番組の台本を書く放送作家です。
2人の会話として書いてください。

この番組は「解説」ではなく、**野球を見ている2人の雑談**です。
ニュースを読み上げる番組ではありません。

登場人物:
- ずんだもん … 聞き手。語尾は「〜のだ」「〜なのだ」。
  **問いと相槌だけを言う。断言も説明もしない。**
  野球は**ひととおり知っている**。日本人選手の名前も、球団も、
  基本的な用語も分かっている。ただし詳しくはない。
  「Yamamotoって日本人の選手なのだ？」のような、
  知らないふりの質問はしない。視聴者を子供扱いしていることになる。
  聞くのは「その数字はどれくらい珍しいのか」「なぜそうなるのか」
  「他と比べてどうなのか」といった、**踏み込んだこと**。
  素朴に、しかし的を外さずに突っ込む役。
- めたん … 語り手。**落ち着いた大人の女性で、野球に詳しい**。
  語尾は「〜わね」「〜よ」「〜のよ」「〜かしら」。**敬語にはしない。**
  ただし砕けすぎない。詳しく、冷静に、順序立てて話す人。
  下の事実だけを話す。「調べたことを話す人」であって、
  「何でも知っている人」ではない。

2人の距離感:
  かしこまった質疑応答にしない。**知っている人と、そこそこ知っている人が、
  同じ画面を見ながら話している**形にする。
  めたんは、聞かれたことに答えるだけでなく、
  「そこじゃなくて、こっちを見て」と話を引っ張ってよい。

{facts}

## 画面に出せる札
台詞の頭に [鍵] を付けると、その台詞のあいだ、画面の中央に
その札が出る。**話していることと札を合わせる。**
付けなければ、直前の札がそのまま残る。ここに無い鍵は使わない。

{menu}

条件:
- **上の「この日の切り口」に従う。**
  材料を上から順に読むと、いつでも成り立つ形の台本になる。
  ある回は「いちばん短いコメントに、いちばん長い返信がついている」
  という話になった。面白くはあるが、**その日の試合と関係が無い。**
  10対1の大敗でコメント欄が荒れているなら、そこが今日の話。

  **コメントの長短・件数そのものを話の軸にしない。**
  長い短いは、その日の試合が何だったかを何も言わない。
- **皮肉ってよい。**
  コメント欄は不特定多数の書き込みで、そこには筋の通らない
  言い分も、都合のいい言い分も混じっている。
  それを黙って読み上げるだけでは、2人がそこにいる意味が無い。

  めたんは軽く突っ込む。ずんだもんは素朴に指摘する。
  例:
    めたん「10対1で負けた試合の下に『上り調子だ』ですって」
    ずんだもん「どのあたりが上り調子なのだ？」
  くらいの温度。**冷笑にはしない。**笑いながら見ている人の側に立つ。

  **やらないこと:**
  ・選手個人を貶さない（「下手」「終わっている」は書かない）
  ・コメントを書いた人そのものを馬鹿にしない。
    突っ込む相手は**言い分**であって、人ではない
  ・特定の球団のファン全体を悪く言わない
- **コメントが自チームの強さを主張していたら、上の勝率で受ける。**
  「Cincinnatiはあそこよりマシだ」のような比較コメントには、
  「対戦の2球団自身の成績」「対戦の2球団以外の勝率」が渡っていれば
  それを使い、ずんだもんに数字で聞き返させてよい。
  例（この通りでなくてよい。数字は渡されたものを使う）:
    めたん[comment]「つまり、Cincinnati（レッズ）は
    Giantsより良くやってるって」
    ずんだもん「レッズは今日勝率いくつなのだ？」
    めたん「.479よ。それでもGiantsの.414より上ではあるわね」
  数字が渡っていなければ、この形はやらない（無い数字を作らない）。
- **野球の決まりごとは、話の流れで要るときだけ説明する。**
  「後攻が勝てば9回裏は行われない」のように、点差だけで
  分かることをわざわざ説明しない。説明するとしても、
  1本の動画に1つまで。
  **「珍しい」「多くない」「一流だ」のような評価はしない。**
  それは数えないと言えないことで、ここに数字が無い。
- **最初の2行で「何の動画のコメント欄を読むのか」を言う。**
  上の「動画の題（原文）」がそれ。日本語にして言う。
  見ている人は、どの動画の話なのかを知らないまま始まる
  （試作では最後まで何の動画か分からなかった、と言われた）
- **回ごとの得点を1回ずつ読み上げない。**
  [score]の札を出しながら「試合の流れはこうだったわ」くらいの
  短い一言で済ませる。回ごとの数字は画面のスコアボードに出ている。
  タイトルとサムネイルで見に来た人は本題（コメント欄）を見たいので、
  試合経過の説明で前半を使い切らない。
  そのあと、両先発投手の成績（[starter_away] [starter_home]。
  無ければ省く）へ進み、そこから目立った選手（[star]）か
  コメント欄へ入る。導入は合わせて4〜6行に収める。
- 「話者[鍵]：台詞」または「話者：台詞」の形で、1行に1つ。
  それ以外は書かない
- **話題が変わる行には必ず鍵を付ける。** 得点の話なら[score]、
  コメントを読むならそのコメントの鍵、成績なら[stat1]のように。
  同じ話が続くあいだは付けない
- **最後のコレスポの案内には [topic] を付ける。**
  付けないと、締めのあいだ選手の成績が画面に出たままになる
- **全体で1600〜1900文字。26〜32行。** 3分の動画にこれだけ要る。
  実測で8.9文字/秒。939文字だと1分46秒にしかならない。
  ただし**水増しはしない。** 上にある材料を使い切ること。
  コメントは6件あるので、面白いものは返信まで読む。
  1件を紹介して終わりにせず、「この人はこう言っているが、
  返信では別の見方が出ている」まで行く
- **上に書かれていない事実を絶対に足さない。**
  選手の経歴、過去の記録、他の試合、順位、年度——
  上に無いものは一切書かない。知っていても書かない
- コメントの訳文は、上のものをそのまま使う。言い換えない
- **コメントが何を意味するかを、勝手に説明しない。**
  書いてあること以上を読み取らない
  （試作では「Shoって誰？」という返信に対して
  「打者の名前が分からないほど無名だということ」と説明したが、
  そんなことはどこにも書いていない）
- **ただし「分かりません」を繰り返さない。**
  これが前回いちばん目立った問題だった。
  「コメント欄だけからは読み取れないわね」「真意は分かりません」
  「そこまで詳しくは分からないわね」が3回出て、
  会話が実にならなかった。

  直し方は答えのほうではなく**問いのほう**。
  **上の材料で答えられない問いを、ずんだもんに言わせない。**
  所属が書いていない選手について「どこの選手なのだ？」と
  聞かせない。意味の取れない一言について「どういう意味なのだ？」と
  聞かせない。**そういうコメントは、そもそも取り上げない。**

  取り上げるコメントは、上のコメントから選んでよい。全部使う必要は無い。
  **話が続くものだけを選ぶ。**
- **返信は、意味が取れるものだけ拾う。**
  返信の中には、この試合にもコメント全体の話題にも関係の無い
  固有名詞が出てくることがある（渡した「所属」に無い選手・球団を
  引き合いに出す、内輪の言い回しなど）。**それが誰・何なのか
  上の材料だけでは判断できないなら、その返信は使わない。**
  無理に訳して読み上げると、見ている側には意味不明な一文になる。

  逆に、その選手の所属が上の「いまの所属」に書いてあるなら、
  それは使ってよい材料になる。**「Mizeは災厄だった」に対して、
  上に先攻の先発投手としてMizeの成績が渡っていれば、
  「それ、今日の先発投手のことなのだ」と繋げてよい。**
  渡っていなければ、その名前には触れない。
- **英語のコメントは、意味が伝わる日本語にする。単語を1対1で
  置き換えない。**
  「a glorified beer league team」は「自称ビールリーグチーム」ではなく、
  「格下扱いされるようなチーム」のように、**言いたいことが伝わる形**
  にする。直訳すると原文の意味が消えるものは、意味を汲んで言い換える。
  ただし**新しい主張を足さない**。「弱いチームに負けて恥だ」という
  皮肉の温度はそのまま、日本語として通る言い方にするだけ。
  それでも「翻訳」「現地の言葉」という断りは付ける（コレスポの
  意見ではないため）。
- **選手の所属は、上の「いまの所属」に書いてあるものだけを使う。**
  書いていない選手の所属には触れない。対戦カードから推測しない
  （試作では Kyle Tucker を「タイガースの打者」と書いたが、
  実際はドジャースの選手だった）
- コメントを紹介するときは「翻訳です」「現地の方の言葉です」と
  分かる形にする。ただし毎回同じ言い方にしない
- 賛否が割れているときは、両方そのまま出す。どちらかに寄らない
- 数字は上のものだけ。丸めたり足したりしない
- **書かれていない因果を作らない。**
  とくに**再生回数と試合の中身を結びつけない。**
  接戦だから、負けたから、大差だから再生数がどうこう、という
  事実はどこにも無い。上にあるのは「何回見られたか」だけで、
  「なぜ見られたか」は書いていない
  （試作では「接戦なのに、そんなに見られてるのだ？」、
  次の回では「負けてるのに、そんなに見られてるのだ？」と
  書かれた。**同じ形が2回出た。** ハイライトはどちらが勝っても
  出るので、勝ち負けと再生数に関係は無い）
- 結果は「◯◯が△対□で勝ち」と、勝った側をはっきり言う。
  「A 2 - 1 B」の形をそのまま読み上げない
- **選手の所属チームは、上に書いてあるものだけを使う。**
  書いていなければ、どちらの所属かに触れない
  （試作では「タイガースの先発、Tarik Skubal」と書かれたが、
  実際はドジャースの投手で、古巣相手に投げていた。
  対戦カードから推測して外した）
- 再生回数は「およそ32万回」のように**丸めた数だけ**を読む。
  **正確な数を続けて言わない。**
  「およそ26万回ね。正確には257,422回よ」と書かれた日があったが、
  ・耳で聞いて頭に入らない
  ・桁区切りのカンマが検算に引っかかって、その日の動画が出なかった
  丸めるのは読みやすさのためであって、正確さを補う必要は無い
- **締めは短く。1行だけ。**
  「毎日出しているもの」を並べ立てない。名前と、また明日、で足りる。
  例:「コレスポでは毎日こうやってコメント欄を読んでいるわ。
  また明日ね」くらい。**番組名は必ず「コレスポ」**
  （試作の締めは「こうしたコメント欄の反応をはじめ、日本人選手の
  最新成績、そして明日の注目試合まで、毎日お伝えしていますので
  ぜひご覧ください」で、案内が長すぎた。
  この後に2人で「コレスポ」と言う画面が入るので、そこで足りる）
- **ハイライト動画はMLB公式のもので、コレスポのものではない。**
  「うちのハイライト」「このチャンネルのハイライト」は間違い。
  コレスポは、その動画とコメント欄を毎日見て話す番組
  （試作では最後にこの2つが混ざった。見ている人は、
  どっちのチャンネルの話をされているのか分からなくなる）
- コレスポが毎日出しているのは、日本人選手の成績、今日の1人、
  ファンのコメント欄、明日の注目試合、欧州サッカー、現地の報道。
  これ以外を挙げない
- **ずんだもんの一言に、毎回なにか足す。**
  「そうなのだ」「いろいろあるのだ」だけの行を続けない。
  聞き手の役目は、**次に何を知りたいかを示すこと**。
  直前に出た数字や言葉のどこが引っかかったのかを言ってから聞く
- 前置きや説明は書かない。台本だけを出力する

書き出しの例（この通りでなくてよい）:
ずんだもん：今日のコメント欄、なんか揉めてるのだ。
めたん[comment1]：そうなのよ。勝っている試合なんだけど、
いちばん支持されているコメントが、これなの。
"""


def parse(text: str, keys=()) -> list:
    """「話者[鍵]：台詞」の行を、区間の配列にする。

    鍵は無くてもよい(直前の札が残る)。知らない鍵は捨てる。
    捨てるだけで落とさないのは、画面の指定が1つ外れただけで
    台本まるごとを失うのは割に合わないため。
    """
    out, unknown = [], []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(
            r"^(ずんだもん|めたん|四国めたん|解説)"
            r"(?:\s*[\[［]\s*([A-Za-z0-9_]+)\s*[\]］])?"
            r"\s*[：:]\s*(.+)$", line)
        if not m:
            continue
        who, key, said = m.group(1), m.group(2), m.group(3).strip()
        if not said:
            continue
        if key and keys and key not in keys:
            unknown.append(key)
            key = None
        out.append({
            "kind": "line",
            "text": said,
            "speaker": (SPEAKER_ZUNDA if who == "ずんだもん"
                        else SPEAKER_EXPLAIN),
            "panel": key or None,
            "meta": {"who": "ずんだもん" if who == "ずんだもん" else "めたん"},
        })
    if unknown:
        print("[warn] 知らない画面の鍵を捨てました: %s"
              % "、".join(sorted(set(unknown))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buzz", default="data/mlb_buzz.json")
    ap.add_argument("--voices", default="data/local_voices.json")
    ap.add_argument("--out", default="build/dialogue.json")
    ap.add_argument("--print-only", action="store_true",
                    help="材料と台本を出すだけで、保存しない")
    args = ap.parse_args()

    m = material(args.buzz, args.voices)
    if not m or not m.get("voices"):
        print("[info] ハイライトかコメントが無いため、作りません")
        return 0

    extra = enrich(m["voices"])
    body = facts(m, extra)
    ps = panels(m, extra)
    print("--- モデルに渡す事実 ---")
    print(body)
    print("\n--- 画面に出せる札 ---")
    print(panel_menu(ps))

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not (key and anthropic is not None):
        print("[info] ANTHROPIC_API_KEY未設定のため、台本は作りません")
        return 0
    if not token_log.allowed("dialogue"):
        return 0

    client = anthropic.Anthropic(api_key=key)
    ask = PROMPT.format(facts=body, menu=panel_menu(ps))
    resp = client.messages.create(
        model=MODEL, max_tokens=16000,
        messages=[{"role": "user", "content": ask}],
    )
    token_log.record("dialogue", MODEL, resp)
    text = "".join(b.text for b in resp.content if b.type == "text")

    segs = parse(text, keys=set(ps))
    chars = sum(len(s["text"]) for s in segs)

    # 短ければ、1度だけ書き足してもらう。
    #
    # 「1600〜1900字」と書いても939字で返ってきた。指示だけでは
    # 長さは決まらない。ただし**足りないぶんを言葉で埋めさせない。**
    # 使っていない材料を指して、そこを書けと言う。
    # それでも足りなければ、短いまま出す。水増しよりましなので。
    if chars < MIN_CHARS and token_log.allowed("dialogue"):
        unused = [k for k in ps if k not in
                  {s.get("panel") for s in segs if s.get("panel")}]
        print(f"\n[info] {chars}字で短いので、書き足してもらいます"
              f"（未使用の材料 {len(unused)}件）")
        more = client.messages.create(
            model=MODEL, max_tokens=16000,
            messages=[
                {"role": "user", "content": ask},
                {"role": "assistant", "content": text},
                {"role": "user", "content": (
                    f"いまの台本は{chars}字で、"
                    f"{TARGET_CHARS}字に足りません。\n"
                    "**同じ形式のまま、全部を書き直してください。**\n"
                    "足すのは中身であって、言葉数ではありません。\n"
                    + ("まだ触れていない材料があります: "
                       + "、".join(unused) + "\n" if unused else "")
                    + "・コメントは返信まで読む\n"
                    "・賛否が割れているところを、両方そのまま出す\n"
                    "・上に無い事実は、やはり一切足さない\n"
                    "台本だけを出力してください。")},
            ],
        )
        token_log.record("dialogue", MODEL, more)
        text2 = "".join(b.text for b in more.content if b.type == "text")
        segs2 = parse(text2, keys=set(ps))
        chars2 = sum(len(s["text"]) for s in segs2)
        if chars2 > chars and len(segs2) >= 8:
            print(f"[info] {chars}字 → {chars2}字")
            segs, text = segs2, text2
        else:
            print(f"[info] 書き足しても{chars2}字だったので、"
                  f"最初のものを使います")
    print("\n--- できた台本 ---")
    for s in segs:
        tag = "[%s]" % s["panel"] if s.get("panel") else ""
        print(f"{s['meta']['who']}{tag}：{s['text']}")
    # この1本にいくらかかったか。実行ページで見えるようにする。
    # モデルを上げたので、割に合っているかを毎日見られる状態にしておく。
    print(f"[info] モデル: {MODEL}")
    print("[info] " + token_log.summary_line("dialogue"))
    used = {s["panel"] for s in segs if s.get("panel")}
    print("[info] 画面の札 %d枚のうち %d枚を使いました"
          % (len(ps), len(used)))
    if ps and not used:
        print("[warn] 札が1枚も指定されませんでした。中央は既定の札になります")
    chars = sum(len(s["text"]) for s in segs)
    # 8.9字/秒は実測(ずんだもん1.5倍速・めたん1.35倍速)。
    # 7字/秒で見積もっていたので、いつも長めに出ていた。
    print(f"\n[info] {len(segs)}行 / {chars}字 → 8.9字/秒で約{chars / 8.9:.0f}秒")
    if chars < MIN_CHARS:
        print(f"::warning::台本が{chars}字しかありません(目安{TARGET_CHARS}字)")

    if len(segs) < 8:
        print("[warn] 行が少なすぎます。台本として使いません")
        return 1
    if args.print_only:
        return 0

    # 冒頭の1.8秒。2人が同時に「コレスポ」と言う。
    #
    # なぜ要るのか:
    #   登録者が14人の段階で、チャンネル名が音として一度も出ていない。
    #   題と説明欄には書いてあるが、見ている人は読んでいない。
    #   1.8秒で名前が耳に入るなら、そのぶんは払う価値がある。
    #
    #   もう1つ、サムネイルと同じ絵を最初に出す意味がある。
    #   押して開いた人が「さっき見たやつだ」と確かめられる。
    #
    #   VOICEVOXは1回に1人しか喋らないので、2つ作って
    #   generate_longform 側で重ねる(video_common.mix_wavs)。
    def _call(kind):
        return [{"kind": kind, "text": "コレスポ", "speaker": SPEAKER_ZUNDA,
                 "panel": None, "meta": {"who": "ずんだもん"}},
                {"kind": kind, "text": "コレスポ", "speaker": SPEAKER_EXPLAIN,
                 "panel": None, "meta": {"who": "めたん"}}]

    # 最後も同じ形で閉じる。始まりと終わりが揃うと、1本として
    # まとまって見える。台本側の締めは1行に短くしてある。
    segs = _call("intro") + segs + _call("outro")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"kind": "dialogue", "segments": segs, "panels": ps,
         "top": m["top"].get("topic_jp") or m["top"].get("matchup"),
         "title": m["top"].get("title") or "",
         "jp": m.get("jp") or [],
         # サムネイルに載せる一言。いちばん支持されたコメント。
         # 「何の動画か」より「何が言われているか」のほうが、
         # 一目で押す理由になる。
         "pick": ((m.get("voices") or [{}])[0].get("ja") or "")[:60],
         "source": m.get("source")},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 台本を出力しました -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
