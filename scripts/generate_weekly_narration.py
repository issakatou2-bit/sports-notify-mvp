"""
週次まとめ動画用のナレーション原稿を、アーカイブから生成する。

日次(generate_narration.py)との違い:
  ・日次は「これから行われる試合」の予告なので、注目理由が中心
  ・週次は「既に終わった試合」を振り返るので、結果まで語れる
  そのため、同じスクリプトを使い回さず別に用意している。

原稿の厚みについて:
  以前は1試合110〜140文字しか書かせておらず、画面の表示時間(30秒)に対して
  読み上げが16秒しかなかった。差は無音で埋まり、8分の動画の半分近くが
  沈黙という状態になっていた。アーカイブには先発投手の成績・球場の特徴・
  連続安打・シリーズの経過まで記録されているのに、その大半を使わずに
  尺だけ伸ばしていたことになる。今は素材を全部渡して厚く書かせ、
  尺は原稿の長さから決まるようにしてある。

出力: build/weekly_narration.json
  generate_weekly.py のセグメント構成
  (intro / day×N / ranking / verdict / news / outro)と1対1で対応させる。
  順序がずれると音声と画面が食い違うため、週の読み込みと集計は
  weekly_stats.py に集約し、両方が同じ結果を見るようにしている。

使い方:
  python3 scripts/generate_weekly_narration.py \
      --archive-dir archive --out build/weekly_narration.json
"""

import argparse
import json
import os
import pathlib
import sys

import weekly_ops
import weekly_stats as ws

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"

# 1試合あたりの目標文字数。VOICEVOXの読み上げ速度(speedScale=1.3)では
# おおよそ 6文字/秒 × 1.3 ≒ 7.8文字/秒 なので、220文字で約28秒になる。
# 画面に載る情報(対戦・スコア・注目理由)を読み終えるのにちょうど良い長さ。
TARGET_CHARS = (190, 240)


def game_facts(date_str: str, g: dict) -> str:
    """
    AIに渡す事実。ここに書かれていないことは書かせない。

    アーカイブに入っているものは、日によって欠けるものがある
    (先発投手は生成時点で未発表のことがある、球場の特徴は登録済みの
     球場だけ、など)。欠けているものは行ごと出さず、AIには
     「無い情報は書かない」という形で伝わるようにしている。
    """
    y, m, d = date_str.split("-")
    lines = [
        f"日付: {int(m)}月{int(d)}日",
        f"対戦: {g.get('home_team_name')}(ホーム) 対 {g.get('away_team_name')}(ビジター)",
    ]

    fs = g.get("final_score")
    if fs:
        winner = (g.get("home_team_name") if fs.get("winner") == "home"
                  else g.get("away_team_name"))
        lines.append(
            f"結果: {g.get('home_team_name')} {fs.get('home')} - "
            f"{fs.get('away')} {g.get('away_team_name')}、{winner}の勝利"
        )
    else:
        lines.append("結果: まだ記録されていない")

    sc = g.get("series_context") or {}
    if sc.get("series_game_number") and sc.get("games_in_series"):
        lines.append(
            f"シリーズ: 全{sc['games_in_series']}戦中の第{sc['series_game_number']}戦"
        )

    for side, label in (("home", "ホーム"), ("away", "ビジター")):
        p = g.get(f"{side}_probable") or {}
        if p.get("name"):
            bits = [f"{label}先発: {p['name']}"]
            if p.get("era"):
                bits.append(f"防御率{p['era']}")
            if p.get("wins") is not None and p.get("losses") is not None:
                bits.append(f"{p['wins']}勝{p['losses']}敗")
            if p.get("strikeouts"):
                bits.append(f"奪三振{p['strikeouts']}")
            lines.append("、".join(bits))

    if g.get("venue_jp") and g.get("venue_note"):
        lines.append(f"球場: {g['venue_jp']} — {g['venue_note']}")

    for note in (g.get("log_notes") or [])[:2]:
        lines.append(f"記録: {note}")

    for r in (g.get("reasons") or [])[:3]:
        if r.get("visible", True) and r.get("text"):
            lines.append(f"注目理由: {r['text']}")

    return "\n".join(lines)


def narrate(client, date_str: str, g: dict, index: int, total: int) -> str:
    lo, hi = TARGET_CHARS
    prompt = (
        "あなたは日本のスポーツ番組で、1週間を振り返るコーナーの"
        "ナレーション原稿を書く放送作家です。\n"
        "以下の事実だけを使って、読み上げ用の原稿を書いてください。\n\n"
        f"{game_facts(date_str, g)}\n\n"
        "条件:\n"
        f"- 1週間の振り返りのうち{index + 1}試合目({total}試合中)です\n"
        f"- {lo}文字から{hi}文字。短すぎると間が持たないので、"
        "上に挙げた事実をできるだけ拾って厚く書くこと\n"
        "- 既に終わった試合を振り返る口調で書く"
        "(「〜でした」「〜が勝利しました」など)\n"
        "- 結果が分かっている場合は必ずスコアに触れる\n"
        "- 先発投手・球場の特徴・連続安打などの記録が上にある場合は、"
        "できるだけ盛り込んで、試合の様子が浮かぶようにすること\n"
        "- 上に書かれていない数字・成績は絶対に書かない。"
        "誰が打ったか、何回に点が入ったかは記録が無いので書かないこと\n"
        "- 選手名は上の表記のまま使う。英語表記をカタカナに変換しない\n"
        "- 記号や箇条書きは使わず、そのまま読める文章だけを出力する\n"
        "- 前置きや説明は不要。原稿本文のみ"
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "max_tokens":
        # 途中で切れた原稿は、読み上げると文の途中で終わる。
        # 使わずに簡易版へ落とす(notability_engine.py と同じ考え方)。
        print("[warn] 原稿が上限で切れたため、簡易版で代替します", file=sys.stderr)
        return ""
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def fallback(date_str: str, g: dict) -> str:
    """AIが使えないときの原稿。事実を並べるだけだが、厚みは確保する。"""
    y, m, d = date_str.split("-")
    parts = [f"{int(m)}月{int(d)}日、{g.get('home_team_name')}対{g.get('away_team_name')}。"]

    sc = g.get("series_context") or {}
    if sc.get("series_game_number") and sc.get("games_in_series"):
        parts.append(f"全{sc['games_in_series']}戦中の第{sc['series_game_number']}戦です。")

    fs = g.get("final_score")
    if fs:
        winner = (g.get("home_team_name") if fs.get("winner") == "home"
                  else g.get("away_team_name"))
        parts.append(f"{fs.get('home')}対{fs.get('away')}で{winner}が勝利しました。")

    for side in ("home", "away"):
        p = g.get(f"{side}_probable") or {}
        if p.get("name") and p.get("era"):
            parts.append(f"先発は{p['name']}、防御率{p['era']}。")

    for r in (g.get("reasons") or [])[:2]:
        if r.get("visible", True) and r.get("text"):
            parts.append(r["text"] + "。")

    for note in (g.get("log_notes") or [])[:1]:
        parts.append(note + "。")

    if g.get("venue_jp") and g.get("venue_note"):
        parts.append(f"舞台は{g['venue_jp']}。{g['venue_note']}球場です。")

    return "".join(parts)


def ops_text(players: list) -> str:
    """
    週間OPSの読み上げ。数字を並べるだけなのでAIは使わない。

    OPSは初心者向けの指標ではないので、最初に一言で何を表すかを添える。
    ここを飛ばすと、数字だけ読み上げても意味が伝わらない。
    """
    top = players[0]
    parts = [
        "続いて、今週の日本人打者です。",
        "OPSは、出塁率と長打率を足した、打者の総合力を表す数字です。",
        f"今週最も打ったのは{top['name']}。OPS{top.get('ops')}、"
        f"{top.get('hits')}安打{top.get('hr')}本塁打でした。",
    ]
    for p in players[1:3]:
        parts.append(f"続いて{p['name']}がOPS{p.get('ops')}、"
                     f"{p.get('hits')}安打です。")
    return "".join(parts)


def league_ops_text(players: list) -> str:
    """
    MLB全体で今週最も打った打者。選手名は英語表記のまま読ませる。
    カタカナへ勝手に直すと、日本のメディアの表記と食い違うため。
    """
    top = players[0]
    parts = [
        "こちらはMLB全体です。",
        f"今週最も打ったのは{top['name']}。OPS{top.get('ops')}、"
        f"{top.get('hits')}安打{top.get('hr')}本塁打でした。",
    ]
    for p in players[1:3]:
        parts.append(f"続いて{p['name']}がOPS{p.get('ops')}です。")
    return "".join(parts)


def verdict_text(v: dict) -> str:
    """
    答え合わせの原稿。数字を読み上げるだけなのでAIは使わない。

    ここはコレスポが自分で出した注目理由の検証にあたる部分なので、
    表現の揺れよりも、数字がそのまま伝わることを優先する。
    """
    parts = ["ここからは、今週の答え合わせです。"]
    if v["decided"]:
        parts.append(
            f"取り上げた{v['picked']}試合のうち、{v['decided']}試合で結果が出ました。"
            f"ホームチームの成績は{v['home_wins']}勝{v['away_wins']}敗です。"
        )
    if v["one_run"]:
        parts.append(f"そのうち1点差の接戦が{v['one_run']}試合ありました。")
    if v["shutouts"]:
        parts.append(f"完封試合は{v['shutouts']}試合です。")
    if v["top_game"]:
        t = v["top_game"]
        parts.append(
            f"最も点が入ったのは{t['home_name']}対{t['away_name']}で、"
            f"{t['home']}対{t['away']}、合わせて{t['total']}点が入りました。"
        )

    # 連勝・連敗を理由に取り上げた試合の行方。コレスポにしか言えない部分。
    for s in v["streaks"][:3]:
        parts.append(
            f"{s['n']}{s['kind']}中として取り上げた{s['team']}は、{s['spoken']}。"
        )

    return "".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--news", default="public/news.json")
    parser.add_argument("--news-log", default="data/news_log.json")
    parser.add_argument("--weekly-ops", default="data/weekly_ops.json")
    parser.add_argument("--out", default="build/weekly_narration.json")
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    week = ws.load_week(archive_dir)
    if len(week) < 2:
        print(f"[info] アーカイブが{len(week)}件しか無いため、原稿は作りません")
        return

    label = (f"{week[0][0][5:].replace('-', '/')}〜"
             f"{week[-1][0][5:].replace('-', '/')}")

    # 動画側と同じ関数で拾う。ここでニュース枠の有無がずれると、
    # 原稿と画面のセグメント数が食い違って以降が全部ずれる。
    news_items = ws.load_news_items(args.news, args.news_log, week[0][0], week[-1][0])
    verdict = ws.compute_verdict(week)
    # 動画側と同じ条件で読む。片方だけセグメントが増減すると全体がずれる
    ops_players = weekly_ops.load(args.weekly_ops, until=week[-1][0])[:5]
    league_players = weekly_ops.load_league(args.weekly_ops, until=week[-1][0])[:5]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key) if (api_key and anthropic) else None
    if client is None:
        print("[info] ANTHROPIC_API_KEY未設定のため、簡易的な原稿で生成します")

    segments = [{
        "kind": "intro",
        "text": f"コレスポ、今週のまとめです。{label}の注目試合を、"
                "結果とあわせて振り返ります。",
        "meta": {},
    }]

    for i, (date_str, g) in enumerate(week):
        text = None
        if client:
            try:
                text = narrate(client, date_str, g, i, len(week))
            except Exception as e:
                print(f"[warn] 原稿生成に失敗、簡易版で代替します: {e}", file=sys.stderr)
        segments.append({
            "kind": "day",
            "text": text or fallback(date_str, g),
            "meta": {"day_index": i},
        })

    # ランキング・答え合わせ・ニュースは、動画側のセグメント構成と順序を合わせる
    segments.append({
        "kind": "ranking",
        "text": "今週、注目試合として多く取り上げた球団を振り返ります。",
        "meta": {},
    })
    if ops_players:
        segments.append({
            "kind": "ops",
            "text": ops_text(ops_players),
            "meta": {},
        })
    if league_players:
        segments.append({
            "kind": "league_ops",
            "text": league_ops_text(league_players),
            "meta": {},
        })
    segments.append({
        "kind": "verdict",
        "text": verdict_text(verdict),
        "meta": {},
    })
    if news_items:
        segments.append({
            "kind": "news",
            "text": "今週の動きです。" + "。".join(news_items[:2]) + "。",
            "meta": {},
        })
    segments.append({
        "kind": "outro",
        "text": "コレスポでは毎日午後7時に、その日の注目試合を"
                "なぜ注目なのかの理由つきでお届けしています。",
        "meta": {},
    })

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"label": label, "segments": segments}, ensure_ascii=False),
        encoding="utf-8",
    )
    chars = sum(len(s["text"]) for s in segments)
    day_chars = [len(s["text"]) for s in segments if s["kind"] == "day"]
    print(f"[info] 週次ナレーション原稿を生成しました"
          f"({len(segments)}セグメント / 計{chars}文字 / "
          f"読み上げ推定{chars / 6 / 1.3:.0f}秒)")
    if day_chars:
        print(f"[info] 1試合あたり {min(day_chars)}〜{max(day_chars)}文字 "
              f"(平均{sum(day_chars) / len(day_chars):.0f}文字)")


if __name__ == "__main__":
    main()
