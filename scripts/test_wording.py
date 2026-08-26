"""
公開する文章に、書いてはいけない語が混ざっていないかの検査。

なぜ要るのか:
  「数えたことしか言わない」と名乗っている以上、数字の裏付けが無い評価と、
  結果の言い当ては書けない。プロンプトでは禁じていたが、守られたかを
  誰も見ていなかった。22日分を数えたら、13本に「〜だろう」「予想される」、
  5本に「正念場」「危機一髪」「圧倒的」「絶好調」が残っていた。

  頼むだけでは足りないので、出力を機械的に見る。
"""

import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import notability_engine as ne  # noqa: E402

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {label}: {got}" + ("" if ok else f" (期待 {want})"))


print("--- 結果の言い当て ---")
for w in ("だろう", "予想される", "必至", "間違いなく"):
    check(f"{w} を弾く",
          w in ne.forbidden_wording(f"投手戦になる{w}。"), True)

print("\n--- 裏付けの無い評価 ---")
for w in ("圧倒的", "絶好調", "正念場", "危機一髪"):
    check(f"{w} を弾く",
          w in ne.forbidden_wording(f"{w}の一戦である。"), True)

print("\n--- 事実の記述は通す ---")
ok_text = ("ドジャースは2位に8.0ゲーム差をつけて西地区首位に立つ。"
           "先発は防御率2.92のSorokaで、今季8勝3敗。"
           "投手戦になるかに注目したい。")
check("数字だけの文は通る", ne.forbidden_wording(ok_text), [])

print("\n--- サッカーに野球の語が混ざっていないか ---")
soccer_bad = "今シーズンは同地区内で1.0ゲーム差の3位同士で対峙する。"
got = ne.forbidden_wording(soccer_bad, soccer=True)
check("ゲーム差を弾く", "ゲーム差" in got, True)
check("地区を弾く", "地区" in got, True)
check("MLBの文では弾かない", ne.forbidden_wording(soccer_bad, soccer=False), [])

print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
