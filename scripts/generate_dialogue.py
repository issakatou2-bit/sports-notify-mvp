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

MODEL = "claude-haiku-4-5-20251001"
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
    try:
        d = _get(f"{MLB_API}/people/search?names="
                 + urllib.parse.quote(name))
        ppl = d.get("people") or []
        if len(ppl) != 1:
            return ""
        pid = ppl[0].get("id")
        q = _get(f"{MLB_API}/people/{pid}?hydrate=currentTeam")
        return ((q.get("people") or [{}])[0].get("currentTeam")
                or {}).get("name", "") or ""
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
    top = vids[0]
    voices = (v.get("voices") or [])[:MAX_COMMENTS]
    # コメントに出てくる選手の所属を、こちらで引いておく。
    # 渡さないと、モデルが対戦カードから推測して外す。
    teams = {}
    for n in find_players([c.get("title", "") for c in voices])[:8]:
        tm = team_of(n)
        if tm:
            teams[n] = tm
            print(f"[info] {n}: {tm}")
    return {"top": top, "voices": voices, "teams": teams,
            "source": v.get("source", "")}


def facts(m: dict, extra: list) -> str:
    """モデルに渡す事実。ここに無いことは書かせない。"""
    top = m["top"]
    res = top.get("result") or {}
    lines = [
        "## その日いちばん見られたハイライト（MLB公式チャンネルの動画）",
        "※ この動画を出しているのはMLB公式であって、コレスポではない。",
        "  コレスポは、その動画とコメント欄を毎日見て話す番組。",
        "  「うちのハイライト」「このチャンネルのハイライト」とは言わない。",
        f"何の動画か: {top.get('topic_jp') or top.get('matchup')}",
        f"再生回数: {top.get('views', 0):,}回",
    ]
    if res.get("away_jp"):
        lines.append(f"結果: {res['away_jp']} {res.get('away_score')} "
                     f"- {res.get('home_score')} {res['home_jp']}")
    inn = [i for i in (res.get("innings") or []) if i.get("num")]
    if inn:
        lines.append("回ごとの得点(先攻/後攻): "
                     + " ".join(f"{i.get('away')}" for i in inn)
                     + " / " + " ".join(f"{i.get('home')}" for i in inn))
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

    if extra:
        lines += ["", "## コメントに出てくる選手の、確かめた数字",
                  "（MLB公式のリーグ順位。これ以外の経歴・記録は書かないこと）"]
        for e in extra:
            lines.append(f"- {e['name']}: {e['stat']} "
                         f"リーグ{e['rank']}位（{e['value']}）")
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
    label = {"score": "回ごとの得点と最終スコア",
             "views": "その動画の再生回数",
             "star": "目立った選手の成績",
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

登場人物:
- ずんだもん … 聞き手。語尾は「〜のだ」「〜なのだ」。
  **問いと相槌だけを言う。断言も説明もしない。**
  ただし**野球は知っている**。日本人選手の名前も、球団も、
  基本的な用語も分かっている。
  「Yamamotoって日本人の選手なのだ？」のような、
  知らないふりの質問はしない。視聴者を子供扱いしていることになる。
  聞くのは「その数字はどれくらい珍しいのか」「なぜそうなるのか」
  「他と比べてどうなのか」といった、**踏み込んだこと**。
- めたん … 語り手。**落ち着いた大人の女性**。
  語尾は「〜わね」「〜よ」「〜のよ」「〜かしら」。**敬語にはしない。**
  ただし砕けすぎない。詳しく、冷静に、順序立てて話す人。
  下の事実だけを話す。「調べたことを話す人」であって、
  「何でも知っている人」ではない。

{facts}

## 画面に出せる札
台詞の頭に [鍵] を付けると、その台詞のあいだ、画面の中央に
その札が出る。**話していることと札を合わせる。**
付けなければ、直前の札がそのまま残る。ここに無い鍵は使わない。

{menu}

条件:
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
  書いてあること以上を読み取らない。
  （試作では「Shoって誰？」という返信に対して
  「打者の名前が分からないほど無名だということ」と説明したが、
  そんなことはどこにも書いていない。分からない一言は
  「こう書いてあるだけで、真意は分かりません」でよい）
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
- 再生回数は「およそ32万回」のように丸めて読む。
  「31万8千754回」は耳で聞いて頭に入らない
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
        model=MODEL, max_tokens=4000,
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
            model=MODEL, max_tokens=4000,
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
         "source": m.get("source")},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 台本を出力しました -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
