#!/usr/bin/env python3
"""
Anthropic APIを何トークン使ったかを、日ごとに残す。

なぜ要るのか:
  残高を機械的に見る方法が無い。Anthropicは残高のAPIを公開して
  いないので(GET /v1/organizations/balance は404)、
  「気づいたら切れていた」を防ぐには自分で数えるしかない。

  数えられるものは全部返ってきている。messages.create の応答には
  usage.input_tokens と usage.output_tokens が必ず入っている。
  それを足していけば、その日いくら使ったかは分かる。

  残高そのものは分からないので、人が一度入れる。
  data/credit.json に「いつ時点でいくら」を書いておけば、
  そこからの消費を引いて、あと何日持つかが出せる。

  月$1.36の出費を削ることに意味は薄い。切れたことに
  気づかないまま数日止まるほうが、はるかに高くつく。

出力: data/token_usage.json

使い方:
  import token_log
  resp = client.messages.create(...)
  token_log.record("local_voices", MODEL, resp)
"""

import json
import os
import pathlib
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
PATH = "data/token_usage.json"

# 100万トークンあたりの価格(ドル)。
# 実測(8/01-8/24で$1.09)と突き合わせて確かめられるように、
# 推定ではなく公表値をそのまま置く。
PRICES = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}
DEFAULT_PRICE = {"in": 1.00, "out": 5.00}


# 1日に使ってよい上限(ドル)。これを超えたら、その日はもう呼ばない。
#
# 実測は1日$0.045。10倍の余裕を取ってある。ここに当たるのは
# 「同じ処理が繰り返し走る」「入力が想定より桁違いに大きい」など、
# 意図しない使い方をしているときだけ。
#
# 自動リロードを入れると、残高が減っても止まらなくなる。
# 止まらないこと自体は目的どおりだが、暴走したときの歯止めが
# 無くなるということでもある。上限はこちらで持つ。
#
# 当たったときは、翻訳を飛ばして本編は出す。鍵が無い日と同じ経路で、
# 動画は出るが現地の言葉が入らない状態になる。
DAILY_LIMIT_USD = 0.50


def spent_today(path: str = PATH) -> float:
    day = datetime.now(JST).strftime("%Y-%m-%d")
    return float((_load(path).get("days") or {}).get(day, {}).get("usd", 0.0))


def allowed(who: str = "", path: str = PATH) -> bool:
    """今日はまだ呼んでよいか。上限に当たっていたら False。"""
    used = spent_today(path)
    if used < DAILY_LIMIT_USD:
        return True
    print(f"[warn] 今日の使用が${used:.3f}で上限${DAILY_LIMIT_USD:.2f}に"
          f"達したため、{who or 'この処理'}は呼びません")
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    if s:
        with open(s, "a", encoding="utf-8") as f:
            f.write(f"**API使用が1日の上限に達しました** "
                    f"(${used:.3f} / ${DAILY_LIMIT_USD:.2f})。"
                    f"{who or 'この処理'}を飛ばしました{chr(10)}")
    return False


def _load(path: str = PATH) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"days": {}}


def cost(model: str, tin: int, tout: int) -> float:
    p = PRICES.get(model, DEFAULT_PRICE)
    return tin / 1_000_000 * p["in"] + tout / 1_000_000 * p["out"]


def record(who: str, model: str, resp, path: str = PATH) -> None:
    """1回ぶんを足す。失敗しても本編は止めない。"""
    try:
        u = getattr(resp, "usage", None)
        tin = int(getattr(u, "input_tokens", 0) or 0)
        tout = int(getattr(u, "output_tokens", 0) or 0)
        if not (tin or tout):
            return
        day = datetime.now(JST).strftime("%Y-%m-%d")
        data = _load(path)
        d = data.setdefault("days", {}).setdefault(
            day, {"calls": 0, "in": 0, "out": 0, "usd": 0.0, "by": {}})
        d["calls"] += 1
        d["in"] += tin
        d["out"] += tout
        d["usd"] = round(d["usd"] + cost(model, tin, tout), 5)
        b = d["by"].setdefault(who, {"calls": 0, "in": 0, "out": 0})
        b["calls"] += 1
        b["in"] += tin
        b["out"] += tout
        # 30日より古いものは落とす。積もると読みづらくなるだけ。
        cut = (datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")
        data["days"] = {k: v for k, v in data["days"].items() if k >= cut}
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print(f"[info] {who}: 入力{tin} 出力{tout} "
              f"(${cost(model, tin, tout):.5f})")
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] 使用量を記録できませんでした: {e}")


# 単価($/百万トークン)。モデルを上げたので、1本いくらかを
# その場で出せるようにしておく。
#
# ここに無いモデルは Haiku の単価で見積もる（過小評価になるが、
# 「分からない」と出すより桁が分かるほうがよい）。
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def cost_of(model: str, tin: int, tout: int) -> float:
    """入力・出力のトークン数から金額を出す。"""
    i, o = PRICES.get(model) or PRICES["claude-haiku-4-5"]
    return tin * i / 1_000_000 + tout * o / 1_000_000


def summary_line(who: str, path: str = PATH) -> str:
    """その呼び出し元が今日いくら使ったか。1行で返す。

    実行ページに出して、モデルを上げた分が割に合っているかを
    毎日見られるようにするためのもの。
    """
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    d = _load(path).get("days", {}).get(today, {})
    by = (d.get("by") or {}).get(who) or {}
    if not by:
        return f"{who}: 今日はまだ呼んでいません"
    tin, tout = by.get("in", 0), by.get("out", 0)
    total = d.get("usd", 0.0)
    return (f"{who}: {by.get('calls', 0)}回 / 入力{tin:,} 出力{tout:,} "
            f"トークン / 今日の合計 ${total:.4f}")


def summary(path: str = PATH, credit_path: str = "data/credit.json") -> dict:
    """直近の消費と、残高が持つ日数。

    残高は data/credit.json に人が入れる。
      {"balance_usd": 3.72, "as_of": "2026-08-24"}
    Consoleの画面を見た日の数字をそのまま書けばよい。
    """
    days = (_load(path).get("days") or {})
    if not days:
        return {}
    recent = sorted(days)[-7:]
    per_day = [days[d]["usd"] for d in recent]
    avg = sum(per_day) / len(per_day)
    out = {"days": len(days), "recent": recent,
           "avg_usd": round(avg, 4), "month_usd": round(avg * 30, 2)}
    try:
        c = json.loads(pathlib.Path(credit_path).read_text(encoding="utf-8"))
        bal, since = float(c["balance_usd"]), str(c["as_of"])
        spent = sum(v["usd"] for k, v in days.items() if k >= since)
        left = bal - spent
        out.update({"balance": round(left, 2), "as_of": since,
                    "spent_since": round(spent, 2),
                    "days_left": int(left / avg) if avg > 0 else None})
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        pass
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    s = summary()
    if not s:
        print("まだ記録がありません")
    else:
        print(f"直近{len(s['recent'])}日の平均: ${s['avg_usd']:.4f}/日 "
              f"(月あたり ${s['month_usd']:.2f})")
        if "balance" in s:
            print(f"残高: ${s['balance']:.2f} "
                  f"({s['as_of']}時点の${s['balance'] + s['spent_since']:.2f}から"
                  f"${s['spent_since']:.2f}使用)")
            print(f"このペースで あと{s['days_left']}日")
