"""API のモデルと呼び方を、役割ごとに1か所で決める。

10/13 本人 OK「新しいモデルにするのは当然として、Sonnet など他のいいモデルも検討。試してもいい」。
使うのは新しい月100ドルのクレジット（10/11 に GitHub の ANTHROPIC_API_KEY を差し替え済み）。
それまでは各処理が claude-haiku-4-5 を直接書いていた。

- モデルだけ差し替えるときは、リポジトリ変数 COLLESPO_LLM_<役割>（例 COLLESPO_LLM_REVIEW=claude-opus-5-5）。
- 新しいモデルは「考える分」も max_tokens に数える。考える役割は下限 floor まで上げて、途中で切れないようにする。
- 考えない役割は、Sonnet 5.5 なら thinking=between_tools、Haiku 5.5 なら disabled（どちらも effort high 以下でだけ通る）。
- Haiku 4.5 などの旧モデルは effort を受け付けないので付けない（差し戻したとき用）。
"""
import os

ROLES = {
    # 原稿の読み返し（sanity）。判断が要る。10/11・10/12 に旧モデルの誤った指摘（LCS をベストオブ5 等）で回が止まった。
    "review": dict(model="claude-sonnet-5-5", effort="medium", think=True, floor=4000),
    # 健康診断の AI のコメント（review_board）。10/13 に出ている動画を「出ていない」と書いた。
    "board": dict(model="claude-sonnet-5-5", effort="medium", think=True, floor=3000),
    # 訳（現地のファンの声・番記者・話題）。観客の発言を選手と訳す誤りがあった。正確さと自然な日本語。
    "translate": dict(model="claude-sonnet-5-5", effort="medium", think=False, floor=0),
    # 読み上げの原稿（ショート・週次）。
    "narration": dict(model="claude-sonnet-5-5", effort="medium", think=False, floor=0),
    # 英語の題・説明文（海外からの検索の入口）。
    "localize": dict(model="claude-sonnet-5-5", effort="medium", think=False, floor=0),
    # ハイライト動画の題を日本語のひと言に。短く単純。
    "topic": dict(model="claude-haiku-5-5", effort="low", think=False, floor=0),
}


def model(role):
    return os.environ.get(f"COLLESPO_LLM_{role.upper()}") or ROLES[role]["model"]


def params(role, max_tokens):
    """messages.create に渡す model・max_tokens・考え方の設定。"""
    spec, name = ROLES[role], model(role)
    out = {"model": name, "max_tokens": max(int(max_tokens), spec["floor"])}
    if name.startswith(("claude-haiku-4", "claude-sonnet-4", "claude-opus-4-5")):
        return out  # 旧モデルは effort も新しい thinking も付けない
    out["output_config"] = {"effort": spec["effort"]}
    if not spec["think"]:
        if name.startswith("claude-sonnet-5-5"):
            out["thinking"] = {"type": "between_tools"}
        elif name.startswith(("claude-haiku-5", "claude-sonnet-5", "claude-opus-5")) and not name.startswith("claude-opus-5-5"):
            out["thinking"] = {"type": "disabled"}
        # Opus 5.5・Fable は考えるのを止められない。effort を低めにして使う。
    return out
