#!/usr/bin/env python3
"""しばらく出ていない日本人打者を見つける。

なぜ要るのか:
  9/7、ユーザーから「明日のLADで言えば大谷が4試合ぶりにスタメン復帰する、
  そういったトピックを扱いたい」と言われた。実際その日の「現地の報道」は
  「大谷翔平が4試合連続でスタメン外れる。ロバーツ監督は月曜日の復帰に
  希望的」を扱っている。**同じ材料が、明日の試合を薦める回では使えて
  いなかった。**

  戻ってくる日は、その選手を追っている人がいちばん見に来る日でもある。

どこから取るか:
  APIは足さない。`data/recap_history/` に、その日出場した日本人選手が
  毎日そのまま残っている。名簿と突き合わせるまでもなく、
  **載っていない日=出ていない日**として数えられる。

  8/07〜9/07の23日ぶんで、日ごとに2〜10人。上位N人に絞ったものではなく、
  その日出場した全員が入っている。

分かることと、分からないこと:
  分かるのは「何日出ていないか」まで。**明日出るかどうかは前日には
  分からない。**打者のスタメンは当日発表なので、ここで言えるのは
  「そろそろ戻ってくるかもしれない」という問いの形だけ。

  投手は見ない。中5日で回るので、5日空くのがふつう。
  空きが長すぎる選手も見ない。故障者リスト入りが長引いている人を、
  毎日「そろそろ」と書くことになる。
"""

import datetime
import json
import pathlib

# 何日空いていたら「そろそろ」と言えるか。
#
# 下限3日: 1〜2日の休養は毎週あるので、その日を選んだ理由にならない。
# 上限10日: これを超えると故障者リストで、戻る日は前日には読めない。
#           吉田正尚(8/16が最後)、佐々木朗希(8/27が最後)がこれに当たる。
MIN_GAP = 3
MAX_GAP = 10

HISTORY = "data/recap_history"


def last_seen(folder: str = HISTORY) -> dict:
    """日本人選手ごとの、最後に出場した日。

    返すのは {名前: {"date": 日付, "player_id": ..., "type": ...}}。
    """
    out = {}
    for f in sorted(pathlib.Path(folder).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = d.get("date_jst") or f.stem
        for p in (d.get("players") or []):
            name = p.get("name")
            if not name:
                continue
            out[name] = {"date": day,
                         "player_id": p.get("player_id"),
                         "type": p.get("type") or ""}
    return out


def _parse(day: str):
    try:
        return datetime.date.fromisoformat(day)
    except (TypeError, ValueError):
        return None


def gaps(target_day, folder: str = HISTORY) -> dict:
    """その日に出れば「何日ぶり」になるかを、打者について返す。

    target_day は日付か "2026-09-08" の文字列。
    明日の回で使うので、渡すのは**明日**の日付。
    """
    if isinstance(target_day, str):
        target_day = _parse(target_day)
    if not target_day:
        return {}
    out = {}
    for name, info in last_seen(folder).items():
        if info.get("type") == "pitcher":
            continue
        seen = _parse(info.get("date"))
        if not seen:
            continue
        gap = (target_day - seen).days
        if MIN_GAP <= gap <= MAX_GAP:
            out[name] = {"gap": gap, "since": info["date"],
                         "player_id": info.get("player_id")}
    return out


def hook_for(names, target_day, folder: str = HISTORY) -> dict:
    """名前の並びから、いちばん長く空いている選手を選ぶ。

    同じ試合に2人いる日は、空きが長いほうを採る。
    戻ってくる話としては、そちらのほうが強い。
    """
    found = gaps(target_day, folder)
    best = None
    for name in (names or []):
        info = found.get(name)
        if info and (best is None or info["gap"] > best[1]["gap"]):
            best = (name, info)
    if not best:
        return {}
    name, info = best
    return {"name": name, "gap": info["gap"], "since": info["since"],
            "text": "%d日ぶりの出場なるか" % info["gap"]}
