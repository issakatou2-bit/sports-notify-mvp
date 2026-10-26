#!/usr/bin/env python3
"""自チャンネルの訂正らしい公開コメントをActions要約へ。AI・返信・動画変更なし。"""
import argparse
import html
import os
from pathlib import Path
import re
import sys

import comment_seeds as cs

RULES = (
    ("誤り・訂正", r"誤り|間違[いうえっ]|違[うい]|訂正|誤解|誤情報|不正確|正確には|正しく[は言]|ではなく|じゃなく|でなく|incorrect|\bwrong\b|\bcorrection\b"),
    ("紛らわしさ・区別", r"紛らわし|まぎらわし|混同|区別|勘違い|confus(?:ing|ion|ed)"),
    ("表記・読み", r"誤字|脱字|誤植|表記[がのを].{0,12}(?:違|誤)|読み[方がは].{0,12}(?:違|誤)|発音.{0,12}(?:違|誤)|typo|misspell"),
    ("数値・日付", r"(?:数字|数値|成績|日付|日時|人数|得点|スコア).{0,16}(?:違[うい]|誤|おかし|逆)|(?:違[うい]|誤).{0,16}(?:数字|数値|日付|スコア)"),
    # 明示的な「誤り」がなくても、AはB。CはDです、という呼び分けを拾う。
    ("名称の区別", r"[^。\n]{1,40}は[^。\n]{1,40}[。\n]\s*[^。\n]{1,40}は[^。\n]{1,40}(?:です|だよ|だと思|ですよ)"),
)


def classify(text):
    value = cs.normalize(text)
    kinds = [kind for kind, pattern in RULES if re.search(pattern, value, re.I)]
    if not kinds:
        return None
    return dict(text=str(text), kinds=kinds)


def collect(**kwargs):
    payload = cs.collect(classifier=classify, include_comments=True, **kwargs)
    payload["corrections"] = payload.pop("seeds")
    return payload


def escaped(text):
    # 任意のMarkdown、HTML、@mentionを解釈させない。改行は本文として残す。
    return html.escape(str(text)).replace("@", "&#64;")


def render(payload):
    coverage = payload["coverage"]
    lines = ["## 訂正コメントの候補", "", "未検証の指摘です。動画の修正・返信は行っていません。",
             "", f"対象期間（UTC）: {escaped(payload['scope']['since'])} ～ {escaped(payload['scope']['until'])}",
             f"公開トップレベルのみ／確認 {coverage['scanned']}件・{coverage['pages']}ページ", ""]
    if not coverage["complete"]:
        lines += ["**取得範囲が不完全です。該当なし・全件確認とは判断できません。**", ""]
    for row in payload["corrections"]:
        vid = row["source_video_id"]
        lines += [f"動画ID: <code>{escaped(vid)}</code>",
                  f"<pre>{escaped(row['source_video_title'])}</pre>",
                  f"指摘の種類: {escaped('／'.join(row['kinds']))}",
                  '件数: 1', ""]
    if not payload["corrections"]:
        lines.append("この取得範囲では候補なし。")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()
    if not 1 <= args.days <= 7 or not 1 <= args.max_pages <= 10:
        ap.error("daysは1〜7、max-pagesは1〜10です")
    if os.environ.get("COLLESPO_CORRECTION_WATCH", "off") != "on":
        print("[info] 訂正コメントの確認は既定オフです")
        return 0
    try:
        if not os.environ.get("YOUTUBE_API_KEY"):
            raise ValueError("missing key")
        payload = collect(days=args.days, max_pages=args.max_pages)
    except Exception:
        # 鍵を含むURLやAPI応答・投稿者情報を例外ログへ出さない。
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as out:
                out.write("## 訂正コメントの候補\n\n取得失敗。候補の有無は未確認です。\n")
        print("::error::訂正コメントを取得できませんでした（本文・鍵はログに出しません）")
        return 1
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(render(payload))
    else:
        print(render(payload))
    count = len(payload["corrections"])
    # 既存のActions注記経路。一般視聴者向けOneSignalには送らない。
    if count:
        print(f"::warning::訂正らしいコメントが{count}件あります。Actionsの要約を確認してください。")
    if not payload["coverage"]["complete"]:
        print("::warning::コメント取得範囲が不完全です。Actionsの要約を確認してください。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
