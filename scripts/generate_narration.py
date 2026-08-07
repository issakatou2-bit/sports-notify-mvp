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

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"
# ショート動画(60秒以内)に収まる範囲で、情報量も確保する。
# 1試合75文字前後 × 3試合 + 前後 で、1.3倍速で40秒前後になる。
MAX_GAMES = 3


# 「大谷翔平は8試合連続安打中」「アストロズは5連勝中」のように、
# 主語と内容が「は」で分かれている事実をほどく。
# 主語が長すぎるものは見出しに向かないので上限を付けている。
# 「ドジャースには〜が所属」のような「には」の形は主語の切れ目が違うため、
# 後読みで弾く(「ドジャースに」を主語として拾ってしまうのを防ぐ)。
HOOK_RE = re.compile(r"^(?P<who>.{2,14}?)(?<![にへとで])は(?P<what>.{4,28})$")

# 「アストロズ vs レンジャーズ は首位攻防戦、ゲーム差はわずか1.5」から
# ゲーム差だけを取り出す。
GAMES_BACK_RE = re.compile(r"ゲーム差はわずか([\d.]+)")


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
        f"開始時刻: {game.get('start_time_jst')} 日本時間",
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
    lead = f"{hook['sub']}は{_big}。" if hook["sub"] else f"{_big}。"
    segments.append({
        "kind": "intro",
        "text": f"{lead}コレスポ、{date_label}の注目試合です。",
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

    # --- ニュース(検証済みのものだけ) ---
    for n in news:
        segments.append({"kind": "news", "text": n["text"] + "です。", "meta": {}})

    # --- クロージング ---
    segments.append({
        "kind": "outro",
        "text": "コレスポでは毎日19時に、その日の注目試合を"
                "なぜ注目なのかの理由つきでお届けしています。",
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
        f"{game.get('start_time_jst', '')}から、"
        f"{game.get('home_team_name')}対{game.get('away_team_name')}。"
    ]
    for r in (game.get("reasons") or [])[:2]:
        if r.get("visible", True) and r.get("text"):
            parts.append(r["text"] + "。")
    return "".join(parts)


if __name__ == "__main__":
    main()
