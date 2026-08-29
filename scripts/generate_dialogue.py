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

# 1本で扱うコメントの数。多いと3分に収まらない。
MAX_COMMENTS = 4


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
    return {"top": top, "voices": (v.get("voices") or [])[:MAX_COMMENTS],
            "source": v.get("source", "")}


def facts(m: dict, extra: list) -> str:
    """モデルに渡す事実。ここに無いことは書かせない。"""
    top = m["top"]
    res = top.get("result") or {}
    lines = [
        "## その日いちばん見られたハイライト",
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

    if extra:
        lines += ["", "## コメントに出てくる選手の、確かめた数字",
                  "（MLB公式のリーグ順位。これ以外の経歴・記録は書かないこと）"]
        for e in extra:
            lines.append(f"- {e['name']}: {e['stat']} "
                         f"リーグ{e['rank']}位（{e['value']}）")
    return "\n".join(lines)


PROMPT = """あなたは、日本語のスポーツ番組の台本を書く放送作家です。
2人の会話として書いてください。

登場人物:
- ずんだもん … 聞き手。語尾は「〜のだ」「〜なのだ」。
  **問いと相槌だけを言う。断言も説明もしない。**
  素朴に驚いたり、分からないことを聞いたりする役。
- 解説 … 語り手。敬語。落ち着いた口調。
  下の事実だけを話す。「調べたことを話す人」であって、
  「何でも知っている人」ではない。

{facts}

条件:
- 「話者：台詞」の形で、1行に1つ。それ以外は書かない
- 全体で900〜1100文字。3分の動画になる長さ
- **上に書かれていない事実を絶対に足さない。**
  選手の経歴、過去の記録、他の試合、順位、年度——
  上に無いものは一切書かない。知っていても書かない
- コメントの訳文は、上のものをそのまま使う。言い換えない
- コメントを紹介するときは「翻訳です」「現地の方の言葉です」と
  分かる形にする。ただし毎回同じ言い方にしない
- 賛否が割れているときは、両方そのまま出す。どちらかに寄らない
- 数字は上のものだけ。丸めたり足したりしない
- **選手の所属チームは、上に書いてあるものだけを使う。**
  書いていなければ、どちらの所属かに触れない
  （試作では「タイガースの先発、Tarik Skubal」と書かれたが、
  実際はドジャースの投手で、古巣相手に投げていた。
  対戦カードから推測して外した）
- 再生回数は「およそ32万回」のように丸めて読む。
  「31万8千754回」は耳で聞いて頭に入らない
- 最後は「コレスポ」の案内で締める。**番組名は必ず「コレスポ」**。
  「このハイライトチャンネル」のような言い換えをしない
  （試作では「このハイライトチャンネルでは」と書かれた。
  名前が出ないと、誰の番組か分からないまま終わる）
- コレスポが毎日出しているのは、日本人選手の成績、今日の1人、
  ファンのコメント欄、明日の注目試合、欧州サッカー、現地の報道。
  これ以外を挙げない
- 前置きや説明は書かない。台本だけを出力する

書き出しの例（この通りでなくてよい）:
ずんだもん：今日のコメント欄、なんか揉めてるのだ。
解説：ええ。勝っている試合なんですが、いちばん支持されている
コメントが、こうなんです。
"""


def parse(text: str) -> list:
    """「話者：台詞」の行を、区間の配列にする。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(ずんだもん|解説)\s*[：:]\s*(.+)$", line)
        if not m:
            continue
        who, said = m.group(1), m.group(2).strip()
        if not said:
            continue
        out.append({
            "kind": "line",
            "text": said,
            "speaker": SPEAKER_ZUNDA if who == "ずんだもん" else SPEAKER_EXPLAIN,
            "meta": {"who": who},
        })
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
    print("--- モデルに渡す事実 ---")
    print(body)

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not (key and anthropic is not None):
        print("[info] ANTHROPIC_API_KEY未設定のため、台本は作りません")
        return 0
    if not token_log.allowed("dialogue"):
        return 0

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=MODEL, max_tokens=2500,
        messages=[{"role": "user",
                   "content": PROMPT.format(facts=body)}],
    )
    token_log.record("dialogue", MODEL, resp)
    text = "".join(b.text for b in resp.content if b.type == "text")

    segs = parse(text)
    print("\n--- できた台本 ---")
    for s in segs:
        print(f"{s['meta']['who']}：{s['text']}")
    chars = sum(len(s["text"]) for s in segs)
    print(f"\n[info] {len(segs)}行 / {chars}字 → 7字/秒で約{chars / 7:.0f}秒")

    if len(segs) < 8:
        print("[warn] 行が少なすぎます。台本として使いません")
        return 1
    if args.print_only:
        return 0

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"kind": "dialogue", "segments": segs,
         "top": m["top"].get("topic_jp") or m["top"].get("matchup"),
         "source": m.get("source")},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 台本を出力しました -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
