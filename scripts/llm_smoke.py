#!/usr/bin/env python3
"""役割ごとのモデルと設定が、API に受け付けられるかを1回ずつ確かめる（手動の道具、費用は1回1セント未満）。

python scripts/llm_smoke.py  → 各役割に短い問いを投げ、モデル・止まった理由・文字・トークン数を表示する。
1つでも失敗・空の返事なら終了コード1。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_models  # noqa: E402

QUESTION = {
    "review": "次の原稿に、数字の明らかな矛盾があれば1行で指摘し、無ければ「なし」とだけ答えて。\n原稿：ドジャースはリーグ優勝決定シリーズ（7戦制）でブリュワーズに0勝1敗。次は明日、第2戦。",
    "board": "再生数 120・340・90 の3本の中央値を数字だけで答えて。",
    "translate": "次の英語を自然な日本語1文に訳して：The crowd went wild after Ohtani's homer.",
    "narration": "「大谷翔平が今日2安打」を、ニュースの読み上げ風の1文にして。",
    "localize": "次の日本語の題を英語の YouTube の題にして：大谷翔平、今日の成績まとめ",
    "topic": "次の動画の題を日本語のひと言（15字以内）に：Shohei Ohtani crushes a 450-foot homer!",
}


def main():
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ok = True
    for role in llm_models.ROLES:
        params = llm_models.params(role, 400)
        try:
            resp = client.messages.create(messages=[{"role": "user", "content": QUESTION[role]}], **params)
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            good = bool(text) and resp.stop_reason == "end_turn"
            print(f"{'ok' if good else 'NG'}  {role:9s} {resp.model} 止まった理由={resp.stop_reason} "
                  f"入力{resp.usage.input_tokens} 出力{resp.usage.output_tokens} → {text[:80]}")
        except Exception as e:  # noqa: BLE001
            good = False
            print(f"NG  {role:9s} {params['model']} {type(e).__name__}: {str(e)[:200]}")
        ok = ok and good
    print("ALL OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
