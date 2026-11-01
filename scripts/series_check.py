"""同じシリーズの次の試合が始まったか（公式の日程で）。訂正の差し替えと、試合の話題を選ぶところで使う。"""


def later_games(game_pk, fetch=None):
    """同じシリーズで、この試合のあとに始まった・終わった試合（gamePk の一覧）。

    10/8、パドレスの訂正版（10/7 第3戦「1勝2敗に」）を出したのは第4戦の最中で、
    その日のうちにパドレスは敗退した。敗退した日に前日の途中経過が新しい動画として並んだ。
    差し替える前に、次の試合が始まっていないかを公式の日程で確かめる（途中でも結果が変わる）。
    """
    import datetime as dt
    import json
    import urllib.request
    get = fetch or (lambda url: json.load(urllib.request.urlopen(url, timeout=30)))
    one = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk={game_pk}")
    g = one["dates"][0]["games"][0]
    ids = sorted(g["teams"][s]["team"]["id"] for s in ("home", "away"))
    day = dt.date.fromisoformat(g["officialDate"])
    end = day + dt.timedelta(days=12)
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={ids[0]}&gameType={g['gameType']}"
           f"&startDate={day.isoformat()}&endDate={end.isoformat()}")
    out = []
    for d in get(url).get("dates", []):
        for x in d.get("games", []):
            pair = sorted(x["teams"][s]["team"]["id"] for s in ("home", "away"))
            if (pair == ids and x["gamePk"] != game_pk and x["gameDate"] > g["gameDate"]
                    and x.get("status", {}).get("abstractGameState") in ("Live", "Final")):
                out.append(x["gamePk"])
    return out
