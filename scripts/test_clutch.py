"""clutch の判定を、まず合成データで固めてから実データに当てる。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")
import clutch

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'ok ' if ok else 'NG '} {label}: {got!r}" +
          ("" if ok else f" (期待 {want!r})"))


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

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
