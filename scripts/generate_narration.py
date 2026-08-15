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
import json
import os
import pathlib
import re
import sys
import unicodedata

import post_common  # noqa: E402
from notability_engine import (  # noqa: E402
    is_soccer_league as _is_soccer_league,
)

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
    日本人選手はJP_PLAYER_READINGSでカタカナに置き換わるので、
    ここへは来ない(来ても漢字はそのまま返る)。

    根本的には選手ごとのカタカナ表記を持つのが正しいが、
    先発投手は誰でもフックに出るので、名簿を用意しても漏れる。
    """
    if not name or not any(c.isascii() and c.isalpha() for c in name):
        return name
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    parts = [p for p in folded.split() if p]
    if len(parts) >= 2:
        # "Jr." のような接尾辞は落として、その手前を姓とみなす
        while len(parts) >= 2 and parts[-1].rstrip(".").lower() in ("jr", "sr", "ii", "iii"):
            parts.pop()
        return parts[-1]
    return folded


def pick_hook(games: list) -> dict:
    """
    動画の1枚目に出す「最も具体的な事実」を選ぶ。

    なぜ必要か:
      これまで1枚目は「コレスポ / 08/07の注目試合」というロゴと日付だけで、
      視聴者にとっては何の情報も無かった。ショートは最初の1秒で
      スワイプされるかが決まるので、そこを名乗りに使うのは最ももったいない。

    選ぶ順番は「具体性が高い順」。選手名と数字が入っているものが一番強く、
    次に連勝・連敗、日本人選手の先発、首位攻防戦、と続く。
    いずれも既に検証済みのデータで、ここで新しく何かを判断したり
    生成したりはしない。

    最後の日本人選手名は「所属している」ことしか分からないため、
    名前を並べるだけにして「出場」「先発」とは書かない
    (打者のスタメンは19時の生成時点ではまだ公表されていない)。
    """
    # 1. 連続安打・移籍後初登板などの個人記録(選手名 + 数字で最も具体的)
    for g in games:
        for note in g.get("log_notes") or []:
            m = HOOK_RE.match((note or "").strip())
            if m:
                return {"big": m.group("what"), "sub": m.group("who")}

    # 2. 連勝・連敗
    for g in games:
        for r in g.get("reasons") or []:
            if r.get("tag") != "streak":
                continue
            m = HOOK_RE.match((r.get("text") or "").strip())
            if m:
                return {"big": m.group("what"), "sub": m.group("who")}

    # 3. 日本人投手の先発予定(これはAPIで確認できている事実)
    for g in games:
        for p in g.get("jp_starters") or []:
            if p.get("name"):
                return {"big": "先発予定", "sub": p["name"]}

    # 4. 首位攻防戦(ゲーム差という具体的な数字が入る)
    for g in games:
        for r in g.get("reasons") or []:
            if r.get("tag") != "div":
                continue
            m = GAMES_BACK_RE.search(r.get("text") or "")
            if m:
                return {"big": f"ゲーム差{m.group(1)}の首位攻防戦", "sub": ""}

    # 4.5 ダービー・伝統の一戦。名前そのものが最も具体的で、検索もされる。
    #     サッカーには「連続安打」「移籍後初登板」に当たる個人記録が
    #     APIから取れないので、上の1〜3は発火しない。ここが実質の先頭になる。
    for g in games:
        for r in g.get("reasons") or []:
            if r.get("tag") == "rivalry" and r.get("text"):
                name = r["text"].strip()
                if 3 <= len(name) <= 20:
                    return {"big": name, "sub": ""}

    # 4.6 サッカーで日本人選手が所属している場合。
    #     「先発予定」とは書かない。スタメンは前日には分からない。
    for g in games:
        for r in g.get("reasons") or []:
            if r.get("tag") != "jp_team":
                continue
            m = re.match(r"^(?P<club>.+?)には(?P<who>.+?)が所属$",
                         (r.get("text") or "").strip())
            if m:
                return {"big": f"{m.group('club')}の試合",
                        "sub": m.group("who").split("・")[0]}

    # 5. AIのフック文(短くまとまっているものだけ)
    for g in games:
        h = (g.get("notification_hook") or "").strip().rstrip("。")
        if 6 <= len(h) <= 32:
            return {"big": h, "sub": ""}

    # 6. 日本人選手の名前を並べるだけ(所属以上のことは書かない)
    for g in games:
        names = [n for n in (g.get("jp_players") or []) if n]
        if names:
            return {"big": "・".join(names[:3]), "sub": ""}

    return {"big": "今日の注目試合", "sub": ""}


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
    for key, label in (("home_probable", "ホーム先発"), ("away_probable", "アウェイ先発")):
        p = game.get(key)
        if p and p.get("name"):
            era = f"、今季防御率{p['era']}" if p.get("era") else ""
            lines.append(f"{label}: {p['name']}{era}")
    if game.get("venue_note"):
        lines.append(f"球場: {game.get('venue_jp')}。{game['venue_note']}")
    for n in (game.get("log_notes") or []):
        lines.append(f"見どころ: {n}")
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
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", default="notable_games.json")
    parser.add_argument("--news", default="public/news.json")
    parser.add_argument("--out", default="public/narration.json")
    args = parser.parse_args()

    data = _load(args.games, {})
    games = [g for g in data.get("games", []) if g.get("is_notable")][:MAX_GAMES]
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
    hook = pick_hook(games)
    # フック文が既に句点で終わっている場合があるので、重ねないよう剥がす
    _big = hook["big"].rstrip("。")
    # 読み上げでは姓だけにする。画面は meta 経由で hook をそのまま受け取るので、
    # フルネームのまま表示される。
    _sub = speech_name(hook["sub"])
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
        "text": f"{lead}注目の{len(games)}試合を、理由つきで。",
        "meta": {"date_label": date_label, "hook": hook},
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
            segments.append({"kind": "game", "text": text, "meta": {"game_index": i}})
    else:
        print("[info] ANTHROPIC_API_KEY未設定のため、簡易的な原稿で生成します")
        for i, g in enumerate(games):
            segments.append({
                "kind": "game",
                "text": _fallback_game_text(g),
                "meta": {"game_index": i},
            })

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
    for r in (game.get("reasons") or [])[:2]:
        if r.get("visible", True) and r.get("text"):
            parts.append(r["text"] + "。")
    return "".join(parts)


if __name__ == "__main__":
    main()
