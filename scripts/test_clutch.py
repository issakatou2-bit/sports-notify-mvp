"""clutch の判定を、まず合成データで固めてから実データに当てる。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")
import clutch
from checks_report import check, done  # noqa: E402


print("=== classify ===")
check("2点ビハインド→1点リード(逆転)", clutch.classify(-2, 1), "逆転")
check("同点→1点リード(勝ち越し)", clutch.classify(0, 1), "勝ち越し")
check("1点ビハインド→同点", clutch.classify(-1, 0), "同点")
check("3点リード→5点リード(通常)", clutch.classify(3, 5), "")
check("3点ビハインド→1点ビハインド(通常)", clutch.classify(-3, -1), "")
check("同点→同点(打点0はここに来ない)", clutch.classify(0, 0), "")

print("\n=== 見出し ===")
check("逆転3ラン",
      clutch._label([{"kind": "逆転", "event_type": "home_run", "rbi": 3}]),
      "逆転3ラン")
check("勝ち越し打点",
      clutch._label([{"kind": "勝ち越し", "event_type": "single", "rbi": 1}]),
      "勝ち越し打点")
check("重い方を選ぶ",
      clutch._label([{"kind": "同点", "event_type": "single", "rbi": 1},
                     {"kind": "逆転", "event_type": "home_run", "rbi": 2}]),
      "逆転2ラン")
check("該当なし", clutch._label([]), "")

print("\n=== 決勝点 ===")


def _p(half, inning, a, h, batter=1, rbi=0, ev="single"):
    return {"about": {"halfInning": half, "inning": inning},
            "result": {"awayScore": a, "homeScore": h, "rbi": rbi,
                       "eventType": ev, "event": ev},
            "matchup": {"batter": {"id": batter}}}


# 10/3 CWS 3-0 CLE の形: 4回表の2ラン（先制）がそのまま決勝点
g1 = [_p("top", 1, 0, 0), _p("top", 4, 2, 0, 9, 2, "home_run"),
      _p("top", 7, 3, 0, 5, 1, "double"), _p("bottom", 9, 3, 0)]
check("先制の2ランが決勝点", clutch.winning_play(g1), 1)
got = clutch.scan_plays(g1, {"9"})
check("先制本塁打と決勝打の両方", sorted(x["kind"] for x in got), ["先制本塁打", "決勝打"])
check("決勝打は見出しを変えない", clutch._label(got), "先制本塁打2ラン")
# 逆転された後に勝ち越した場合、決勝点は後の得点
g2 = [_p("top", 1, 1, 0, 9, 1), _p("bottom", 3, 1, 2, 7, 2),
      _p("top", 8, 3, 2, 9, 2, "home_run"), _p("bottom", 9, 3, 2)]
check("逆転し返した一打が決勝点", clutch.winning_play(g2), 2)
check("引き分け・同点は無し", clutch.winning_play([_p("top", 1, 1, 1)]), None)
check("得点の無いプレーだけなら無し", clutch.winning_play([]), None)
import numbers_material as nm  # noqa: E402
check("長編の材料の言い方",
      nm.scenes({"clutch_plays": got}),
      ["4回表に先制の2点本塁打。これが決勝点（相手はこのあと同点にも追いつけなかった）"])
check("決勝点だけのとき",
      nm.scenes({"clutch_plays": [{"kind": "決勝打", "event_type": "sac_fly", "rbi": 1,
                                   "inning": 7, "half": "bottom"}]}),
      ["7回裏の犠牲フライが決勝点（相手はこのあと同点にも追いつけなかった）"])

print("\n=== 実データ(2026-08-10 の全試合を走査) ===")
# その日出場していた日本人選手のIDを、保存済みの記録から取る
rec = json.load(open("data/morning_recap.json", encoding="utf-8"))
ids = [p["player_id"] for p in rec["players"]]
print("  対象:", [(p["name"], p["player_id"]) for p in rec["players"]])

data = clutch.build(rec["date"], ids)
if not data:
    print("  この日は、逆転・勝ち越し・同点に該当する打席なし")
else:
    for pid, e in data.items():
        name = next((p["name"] for p in rec["players"]
                     if p["player_id"] == pid), pid)
        print(f"  {name}: +{e['points']}点  {e['label']}")
        for p in e["plays"]:
            print(f"      {p['inning']}回 {p['kind']} {p['event']} 打点{p['rbi']}")
sys.exit(done())
