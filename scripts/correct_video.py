#!/usr/bin/env python3
"""公開済みの動画に誤りが見つかったとき、直した版を作って差し替える。

なぜ要るのか:
  10/7 の試合の話題 bLEENICgueo で、決勝点が「ミゲル・アンドゥハーの失策」と
  画面に約10秒出て、読み上げもそう言っていた（正しくはブリュワーズの遊撃手
  プラットの送球失策。アンドゥハーは打者）。題と説明は直せても、画面と声は残る。

  YouTube は公開後に動画のファイルを差し替えられない（Studio でできるのは
  一部を切る・ぼかすだけ。API ではそれもできない）。画面に誤りが出続ける回は、
  **当時の材料を直して本番と同じ道具で作り直し、新しい動画を出して、古い動画は
  非公開にする（消さない）**。毎回その場で手順を組まないよう、ここに1か所にする。

直し方は data/corrections/<名前>.json に書く:
  {"kind": "asset", "topic": "season_game_849826", "old_video": "bLEENICgueo",
   "material": {"commit": "b0ddf3f", "path": "data/ps_game_topics.json"},
   "edits": [{"where": ["items", 1, 1], "from": "直す前の文", "to": "直した文"}],
   "note": "説明欄の頭に足す一文", "reason": "..."}
  where は話題（topic）の中の位置。from が今の値と一致しなければ止まる
  （別の版の材料を直してしまわないように）。

手順（.github/workflows/correct_video.yml）:
  prepare  当時の材料を取り出し、edits を当てて data/ に置く（作業用の取り出しの中だけ）
  （制作）  generate_asset_video → sanity → 音声 → 動画（本番と同じ）
  note     新しい動画の説明欄の頭に、作り直した理由を足す
  古い動画は hold_video.py で非公開に戻す（消さない）

いまは資産動画（試合の話題など）だけ。夕方の4本は材料が多く別の作り方なので、
必要になったら kind を足す。
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_fix(name):
    return json.loads((ROOT / "data" / "corrections" / f"{name}.json").read_text(encoding="utf-8"))


def material_at(commit, path):
    raw = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True,
                         capture_output=True).stdout
    return json.loads(raw.decode("utf-8"))


def apply_edits(target, edits):
    """edits を当てる。直す前の文が一致しなければ止める。"""
    for e in edits:
        *head, last = e["where"]
        node = target
        for k in head:
            node = node[k]
        if node[last] != e["from"]:
            raise ValueError(f"直す前の文が材料と違います: {e['where']} = {node[last]!r}")
        node[last] = e["to"]
    return target


def prepare(fix):
    if fix.get("kind") != "asset":
        raise SystemExit(f"[error] kind={fix.get('kind')} はまだ作り直せません（資産動画だけ）")
    m = fix["material"]
    data = material_at(m["commit"], m["path"])
    topics = data.get("topics") or []
    hit = [t for t in topics if t.get("key") == fix["topic"]]
    if len(hit) != 1:
        raise SystemExit(f"[error] {m['commit']}:{m['path']} に {fix['topic']} が1つありません")
    apply_edits(hit[0], fix.get("edits") or [])
    # 当時の材料で作り直す。ほかの話題が混ざらないよう、この話題だけを置く。
    data["topics"] = hit
    (ROOT / m["path"]).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] {fix['topic']} の材料を {m['commit']} から取り出して {len(fix.get('edits') or [])} か所直しました")
    for e in fix.get("edits") or []:
        print(f"   {e['from']} → {e['to']}")


def note(fix, video_id):
    """新しい動画の説明欄の頭に、作り直した理由を足す（同じ文が既にあれば足さない）。"""
    import hold_video
    yt = hold_video.client()
    if yt is None or not fix.get("note"):
        return
    items = yt.videos().list(part="snippet", id=video_id).execute().get("items") or []
    if not items:
        raise SystemExit(f"[error] {video_id} が見つかりません")
    sn = items[0]["snippet"]
    if fix["note"] in (sn.get("description") or ""):
        print("[info] 説明欄には既に書いてあります")
        return
    body = {"id": video_id, "snippet": {"title": sn["title"], "categoryId": sn["categoryId"],
                                        "description": fix["note"] + "\n\n" + (sn.get("description") or ""),
                                        "tags": sn.get("tags") or [],
                                        "defaultLanguage": sn.get("defaultLanguage") or "ja"}}
    yt.videos().update(part="snippet", body=body).execute()
    print(f"[info] 説明欄の頭に足しました: {fix['note']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["prepare", "show", "note"])
    ap.add_argument("--fix", required=True, help="data/corrections/<名前>.json の名前")
    ap.add_argument("--video", help="note: 新しい動画のID")
    a = ap.parse_args()
    fix = load_fix(a.fix)
    if a.command == "prepare":
        prepare(fix)
    elif a.command == "show":
        # ワークフローが使う値だけを出す（KEY=値）
        print(f"TOPIC={fix['topic']}\nOLD_VIDEO={fix['old_video']}")
    else:
        note(fix, a.video)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    main()
