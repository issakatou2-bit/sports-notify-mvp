#!/usr/bin/env python3
"""
欧州サッカーの「シーズン前情報」を football-data.org から取得する。

日次の notability_engine が扱うのは「今日の試合」だけなので、
開幕前の期間は出せる情報が何も無い。ここで扱うのは、
その日付に依存しない次の4つ:

  season      今季の開幕日・最終日・現在の節
  openers     開幕節の全カード(日時つき)
  early       開幕から数節のうち、注目度の高いカード
  last_season 昨季の最終順位

いずれも実データで、こちらで書き起こす部分は無い。
開幕日程を手で書くと、発表前の推測を書いてしまうか、
日程変更に追従できなくなる。

注意: 無料枠では過去シーズンが403になる競技会がある。
その場合 last_season は空になり、他の項目だけが残る。
落とさずに続けるのは、1つ取れないせいで全部出せなくなるのを避けるため。

使い方:
  FOOTBALL_DATA_API_KEY=xxx python3 scripts/soccer_preview.py \
      --out data/soccer_preview.json
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from notability_engine import (  # noqa: E402
    FOOTBALL_DATA_BASE,
    SOCCER_COMPETITIONS,
    _football_data_get,
    jp_players_for_club,
)

# 開幕節に加えて何節ぶんを「序盤」として見るか。
# 3節あるとカードの当たり外れがならされ、かつリクエスト数が増えすぎない。
EARLY_MATCHDAYS = 3

# 「注目カード」を選ぶための重み。
# 昨季順位が上位同士ほど高く、日本人選手が絡むと加点する。
# 開幕前は今季の順位が存在しないので、昨季順位以外に序列の手掛かりが無い。
W_LAST_SEASON_TOP = 40.0   # 両チームとも昨季上位
W_JP_PLAYER = 30.0         # 日本人選手の所属クラブ
W_SAME_CITY = 0.0          # ダービーは別途扱う(ここでは加点しない)


def _headers(api_key: str) -> dict:
    return {"X-Auth-Token": api_key}


def fetch_competition(code: str, api_key: str) -> dict:
    """
    競技会1つぶんの前情報を取る。取れなかった部分は空のまま返す。

    リクエストは最大3回(competition / matches / 昨季standings)。
    無料枠は10リクエスト/分なので、6競技会だと分をまたぐ。
    _football_data_get 側が残量を見て待つ。
    """
    h = _headers(api_key)
    out: dict = {"code": code, "name_jp": SOCCER_COMPETITIONS.get(code, code)}

    # 1) 今季の期間と現在の節。currentSeason にすべて入っている。
    try:
        comp = _football_data_get(
            f"{FOOTBALL_DATA_BASE}/competitions/{code}", headers=h
        ).json()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {code}: 競技会情報を取得できませんでした ({e})")
        return out

    cs = comp.get("currentSeason") or {}
    out["season"] = {
        "start": cs.get("startDate"),
        "end": cs.get("endDate"),
        "matchday": cs.get("currentMatchday"),
        "year": _season_year(cs.get("startDate")),
    }

    # currentSeason が既に終わっている競技会は、APIがまだ次シーズンへ
    # 切り替えていない状態。実際CLは、5大リーグが2026-27を返している時点でも
    # 2025-09-16〜2026-05-30(終了済み)を返していた。
    # そのまま出すと「9月16日に始まります」と過去の日付を告知してしまう。
    # 昨季順位も1シーズンぶんずれるので、競技会ごと落とす。
    out["stale"] = _ended(cs.get("endDate"))
    if out["stale"]:
        print(f"[info] {code}: currentSeasonが終了済み"
              f"({cs.get('startDate')}〜{cs.get('endDate')})のため対象外にします")
        out["openers"] = []
        out["early"] = []
        out["last_season"] = []
        return out

    # 2) 開幕から EARLY_MATCHDAYS 節ぶんの試合。
    #    matchday を1節ずつ引くとリクエストが3倍になるので、
    #    節の指定なしで取って手元で絞る。
    try:
        data = _football_data_get(
            f"{FOOTBALL_DATA_BASE}/competitions/{code}/matches", headers=h
        ).json()
        matches = data.get("matches", [])
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {code}: 日程を取得できませんでした ({e})")
        matches = []

    early = [
        m for m in matches
        if isinstance(m.get("matchday"), int) and m["matchday"] <= EARLY_MATCHDAYS
    ]
    out["openers"] = [_match_row(m) for m in early if m.get("matchday") == 1]
    out["early"] = [_match_row(m) for m in early]

    # 3) 昨季の最終順位。無料枠では403になることがあるので、失敗を許容する。
    year = out["season"].get("year")
    if year:
        try:
            st = _football_data_get(
                f"{FOOTBALL_DATA_BASE}/competitions/{code}/standings",
                headers=h,
                params={"season": year - 1},
            ).json()
            out["last_season"] = _table_rows(st)
            out["last_season_year"] = year - 1
        except Exception as e:  # noqa: BLE001
            print(f"[info] {code}: 昨季順位は取得できませんでした ({e})")
            out["last_season"] = []
    else:
        out["last_season"] = []

    return out


def _ended(end_date) -> bool:
    """そのシーズンが既に終わっているか。日付が読めなければ終了扱いにしない。"""
    if not end_date:
        return False
    try:
        end = dt.datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return end < dt.date.today()


def _season_year(start_date) -> int | None:
    """'2026-08-21' → 2026。開幕年がそのままシーズンの呼称になる。"""
    if not start_date:
        return None
    try:
        return int(str(start_date)[:4])
    except ValueError:
        return None


def _match_row(m: dict) -> dict:
    """必要な項目だけに削る。生のレスポンスは1試合1KB近くあり、保存すると重い。"""
    return {
        "matchday": m.get("matchday"),
        "utc": m.get("utcDate"),
        "home": (m.get("homeTeam") or {}).get("name"),
        "away": (m.get("awayTeam") or {}).get("name"),
        "home_short": (m.get("homeTeam") or {}).get("shortName"),
        "away_short": (m.get("awayTeam") or {}).get("shortName"),
    }


def _table_rows(standings_json: dict) -> list:
    """TOTALテーブルだけを使う。ホーム/アウェー別は今のところ使い道が無い。"""
    for group in standings_json.get("standings", []):
        if group.get("type") != "TOTAL":
            continue
        return [
            {
                "position": r.get("position"),
                "team": (r.get("team") or {}).get("name"),
                "played": r.get("playedGames"),
                "won": r.get("won"),
                "draw": r.get("draw"),
                "lost": r.get("lost"),
                "points": r.get("points"),
                "gf": r.get("goalsFor"),
                "ga": r.get("goalsAgainst"),
            }
            for r in group.get("table", [])
        ]
    return []


# ---------------------------------------------------------------------------
# 注目カードの選定
# ---------------------------------------------------------------------------

def score_matches(comp: dict) -> list:
    """
    序盤の試合に点をつけて並べる。

    開幕前は今季の戦績が存在しないので、材料は昨季順位と選手の所属しかない。
    どちらも実データで、こちらの印象は入っていない。
    昨季順位が取れなかった競技会では、日本人選手の所属だけで並ぶ。
    """
    rank = {r["team"]: r["position"] for r in comp.get("last_season", []) if r.get("team")}

    scored = []
    for m in comp.get("early", []):
        home, away = m.get("home"), m.get("away")
        if not home or not away:
            continue

        pts = 0.0
        reasons = []

        hr, ar = rank.get(home), rank.get(away)
        if hr and ar:
            # 両チームの昨季順位が上位なほど高い。1位同士で満点。
            worst = max(hr, ar)
            if worst <= 6:
                pts += W_LAST_SEASON_TOP * (7 - worst) / 6
                reasons.append(f"昨季{hr}位と{ar}位")
            elif worst <= 10:
                pts += W_LAST_SEASON_TOP * 0.2
                reasons.append(f"昨季{hr}位と{ar}位")

        # クラブ名は正式名称で返ってくるので、名簿とは正規化して突き合わせる
        jp = jp_players_for_club(home) + jp_players_for_club(away)
        if jp:
            pts += W_JP_PLAYER
            names = "・".join(p["name_jp"] for p in jp)
            reasons.append(f"{names}の所属クラブ")

        if pts <= 0:
            continue
        scored.append({**m, "score": round(pts, 1), "reasons": reasons})

    scored.sort(key=lambda x: (-x["score"], x.get("utc") or ""))

    # 同じカードが2度出ないようにする。リーグ戦なら序盤3節に同じ組み合わせは
    # 来ないはずだが、APIが重複を返しても壊れないようにしておく。
    #
    # 併せて、1クラブが上位を占めないよう2件までに抑える。
    # 日本人選手のいるクラブは全試合に加点が付くので、対策しないと
    # 同じクラブの試合だけが並び、「注目カード」の一覧にならない。
    seen_pairs = set()
    club_count: dict = {}
    out = []
    for m in scored:
        pair = frozenset((m["home"], m["away"]))
        if pair in seen_pairs:
            continue
        if any(club_count.get(t, 0) >= 2 for t in (m["home"], m["away"])):
            continue
        seen_pairs.add(pair)
        for t in (m["home"], m["away"]):
            club_count[t] = club_count.get(t, 0) + 1
        out.append(m)
    return out


def build(api_key: str) -> dict:
    comps = []
    for code in SOCCER_COMPETITIONS:
        c = fetch_competition(code, api_key)
        c["highlights"] = score_matches(c)[:5]
        comps.append(c)
        n_open = len(c.get("openers", []))
        n_last = len(c.get("last_season", []))
        print(f"[ok] {code}: 開幕{n_open}試合 / 序盤{len(c.get('early', []))}試合 "
              f"/ 昨季順位{n_last}チーム")
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "competitions": comps,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/soccer_preview.json")
    ap.add_argument(
        "--max-age-days", type=float, default=None,
        help="出力先がこの日数より新しければ、取得せず終了する",
    )
    args = ap.parse_args()

    # 中身は日単位ではほとんど動かない(開幕日程と昨季順位)。
    # 毎日取ると6競技会×3で18リクエストを使い、無料枠(10/分)の
    # 待機で実行時間も伸びる。日次から呼ぶときは鮮度だけ見て打ち切る。
    if args.max_age_days is not None:
        p = pathlib.Path(args.out)
        if p.exists():
            age = (dt.datetime.now().timestamp() - p.stat().st_mtime) / 86400
            if age < args.max_age_days:
                print(f"[skip] {args.out} は{age:.1f}日前の取得なので、そのまま使います")
                return 0

    api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not api_key:
        print("[error] FOOTBALL_DATA_API_KEY が設定されていません")
        return 1

    data = build(api_key)

    # 全競技会で何も取れなかったときは、既存のファイルを上書きしない。
    # 中身が空のJSONで置き換えると、動画やサイトから項目が消える。
    got = sum(len(c.get("early", [])) + len(c.get("last_season", []))
              for c in data["competitions"])
    if got == 0:
        print("[error] 取得できたデータが1件もありません。ファイルは更新しません")
        return 1

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {out} ({got}件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
