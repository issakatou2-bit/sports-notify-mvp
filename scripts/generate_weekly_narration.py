"""
週次まとめ動画用のナレーション原稿を、アーカイブから生成する。

日次(generate_narration.py)との違い:
  ・日次は「これから行われる試合」の予告なので、注目理由が中心
  ・週次は「既に終わった試合」を振り返るので、結果まで語れる
  そのため、同じスクリプトを使い回さず別に用意している。

出力: build/weekly_narration.json
  generate_weekly.py のセグメント構成(intro / day×N / ranking / news / outro)と
  1対1で対応させる。順序がずれると音声と画面が食い違うため、
  ここで組み立てた順序をそのまま動画側でも使う。

使い方:
  python3 scripts/generate_weekly_narration.py \
      --archive-dir archive --out build/weekly_narration.json
"""

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-haiku-4-5-20251001"
DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")
JST = timezone(timedelta(hours=9))


def load_week(archive_dir: pathlib.Path, days: int = 7):
    """generate_weekly.py と同じ条件で読み込む(順序を一致させるため)"""
    entries = []
    for f in sorted(archive_dir.glob("*.json")):
        if DATE_FILE_RE.match(f.name):
            entries.append((f.name[:10], f))
    entries.sort(key=lambda x: x[0], reverse=True)
    out = []
    for date_str, path in entries[:days]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for g in [x for x in data.get("games", []) if x.get("is_notable")][:2]:
            out.append((date_str, g))
    out.reverse()
    return out


def game_facts(date_str: str, g: dict) -> str:
    y, m, d = date_str.split("-")
    lines = [
        f"日付: {int(m)}月{int(d)}日",
        f"対戦: {g.get('home_team_name')} 対 {g.get('away_team_name')}",
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
    for r in (g.get("reasons") or [])[:3]:
        if r.get("visible", True) and r.get("text"):
            lines.append(f"注目理由: {r['text']}")
    return "\n".join(lines)


def narrate(client, date_str: str, g: dict, index: int, total: int) -> str:
    prompt = (
        "あなたは日本のスポーツ番組で、1週間を振り返るコーナーの"
        "ナレーション原稿を書く放送作家です。\n"
        "以下の事実だけを使って、読み上げ用の原稿を書いてください。\n\n"
        f"{game_facts(date_str, g)}\n\n"
        "条件:\n"
        f"- 1週間の振り返りのうち{index + 1}試合目({total}試合中)です\n"
        "- 110文字から140文字\n"
        "- 既に終わった試合を振り返る口調で書く"
        "(「〜でした」「〜が勝利しました」など)\n"
        "- 結果が分かっている場合は必ず触れる\n"
        "- 上に書かれていない数字・成績は絶対に書かない\n"
        "- 選手名は上の表記のまま使う。英語表記をカタカナに変換しない\n"
        "- 記号や箇条書きは使わず、そのまま読める文章だけを出力する\n"
        "- 前置きや説明は不要。原稿本文のみ"
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def fallback(date_str: str, g: dict) -> str:
    y, m, d = date_str.split("-")
    parts = [f"{int(m)}月{int(d)}日、{g.get('home_team_name')}対{g.get('away_team_name')}。"]
    fs = g.get("final_score")
    if fs:
        winner = (g.get("home_team_name") if fs.get("winner") == "home"
                  else g.get("away_team_name"))
        parts.append(f"{fs.get('home')}対{fs.get('away')}で{winner}が勝利しました。")
    for r in (g.get("reasons") or [])[:1]:
        if r.get("visible", True) and r.get("text"):
            parts.append(r["text"] + "。")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default="archive")
    parser.add_argument("--news", default="public/news.json")
    parser.add_argument("--out", default="build/weekly_narration.json")
    args = parser.parse_args()

    archive_dir = pathlib.Path(args.archive_dir)
    week = load_week(archive_dir)
    if len(week) < 2:
        print(f"[info] アーカイブが{len(week)}件しか無いため、原稿は作りません")
        return

    label = (f"{week[0][0][5:].replace('-', '/')}〜"
             f"{week[-1][0][5:].replace('-', '/')}")

    news_items = []
    npath = pathlib.Path(args.news)
    if npath.exists():
        try:
            news_items = [n["text"] for n in
                          (json.loads(npath.read_text(encoding="utf-8")).get("news") or [])]
        except (json.JSONDecodeError, OSError):
            pass

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key) if (api_key and anthropic) else None
    if client is None:
        print("[info] ANTHROPIC_API_KEY未設定のため、簡易的な原稿で生成します")

    segments = [{
        "kind": "intro",
        "text": f"コレスポ、今週のまとめです。{label}の注目試合を振り返ります。",
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

    # ランキングとニュースは、動画側のセグメント構成と順序を合わせる
    segments.append({
        "kind": "ranking",
        "text": "今週、注目試合として多く取り上げた球団を振り返ります。",
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
        "text": "詳しくはコレスポドットコムへ。毎日19時に、その日の注目試合をお届けしています。",
        "meta": {},
    })

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"label": label, "segments": segments}, ensure_ascii=False),
        encoding="utf-8",
    )
    chars = sum(len(s["text"]) for s in segments)
    print(f"[info] 週次ナレーション原稿を生成しました"
          f"({len(segments)}セグメント / 計{chars}文字 / 読み上げ推定{chars / 6 / 1.3:.0f}秒)")


if __name__ == "__main__":
    main()
