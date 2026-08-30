"""
ナレーション原稿から音声ファイルを合成する。

VOICEVOXについて:
  GitHub Actions上でVOICEVOX ENGINE(Docker)を起動し、そこへ問い合わせる。
  エンジンが起動していない場合は、音声なしで処理を続ける(動画自体は作れる)。

  ★重要★
  VOICEVOXおよび各キャラクター(ずんだもん等)には、それぞれ利用規約がある。
  収益化を伴う利用ではクレジット表記が必要になる場合があるため、
  実際に公開する前に必ず規約を確認すること。
  このスクリプトは技術的な連携のみを行い、規約の遵守は利用者の責任となる。

出力:
  build/audio/seg_000.wav ... セグメントごとの音声
  build/audio/manifest.json ... 各音声の実際の長さ(秒)

  動画側はこのmanifestを見て画面の表示時間を決めるので、
  原稿の文字数から推測する必要がなく、音声と画面がズレない。

使い方:
  python3 scripts/synthesize_narration.py \
      --narration public/narration.json --out-dir build/audio
"""

import argparse
import json
import pathlib
import subprocess
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    from notability_engine import apply_readings
except ImportError:  # 読みの表が引けなくても、音声そのものは作れるようにする
    def apply_readings(text):
        return text

VOICEVOX_URL = "http://127.0.0.1:50021"
# 話者ID。VOICEVOXのspeakersエンドポイントで確認できる。
# 3 = ずんだもん(ノーマル)が一般的だが、環境により異なる場合がある。
DEFAULT_SPEAKER = 3
# ショート動画はテンポが命なので速めにする。
#
# 1.3 → 1.38 → 1.5 と上げてきた(2026年8月)。
# 1.38は数字だけを見て決めた値で、出来上がりを聞いた上での判断ではなかった。
# 実際に聞いた上で「もう少し速くてよい」という指摘があり、1.5にした。
#
# 上げる根拠:
#   直近28日のショートは77.7%がスワイプで消されている(視聴継続22.3%)。
#   ショートの目安は40〜50%なので半分以下で、最初の数秒で判断されている。
#   同じ内容を速く言えば、同じ秒数でより先まで進める。
#
# 上限について:
#   ずんだもんは1.6を超えると子音が潰れて聞き取りにくくなる。
#   1.5はその手前。速すぎると感じたらここだけ戻せばよい。
#
# 週次の横型動画への影響:
#   9分54秒だったものが約9分になる。8分は超えたままなので問題ない。
SPEED_SCALE = 1.5

# 間の詰め方
# ---------------------------------------------------------------------------
# 話速だけ上げると、語りは速いのに切れ目で止まる、という妙な間になる。
# VOICEVOXは1回の合成ごとに前後へ無音を付けるので、画面が10枚あれば
# その分だけ積み上がる。読み上げの中身を削らずに尺を詰められるのは、
# まずここ。
#
#   prePhonemeLength  … 発話の前に入る無音(既定0.1秒)
#   postPhonemeLength … 発話の後に入る無音(既定0.1秒)
#   pauseLengthScale  … 「、」「。」で入る間の倍率(既定1.0)
#
# 後ろは完全に0にはしない。次の画面と音が地続きになって、
# 区切りが聞き取れなくなるため。
PRE_PHONEME = 0.0
POST_PHONEME = 0.05
PAUSE_SCALE = 0.85


def engine_available() -> bool:
    try:
        r = requests.get(f"{VOICEVOX_URL}/version", timeout=5)
        return r.ok
    except Exception:
        return False


def synth_one(text: str, speaker: int, out_path: pathlib.Path) -> bool:
    """
    1セグメント分の音声を合成する。成功したらTrue。

    選手名は読み仮名へ置き換えてから渡す。VOICEVOXは漢字の人名を
    正しく読めないことがあり(「朗希」「滉大」など)、画面の表記は
    正しいのに音だけ違う、という状態になるため。
    """
    text = apply_readings(text)
    try:
        q = requests.post(
            f"{VOICEVOX_URL}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=30,
        )
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = SPEED_SCALE

        # 応答に無いキーを送るとエンジンが422を返すことがある。
        # pauseLengthScale は新しめのVOICEVOXにしか無いので、
        # 返ってきたキーだけを上書きする。
        for key, value in (("prePhonemeLength", PRE_PHONEME),
                           ("postPhonemeLength", POST_PHONEME),
                           ("pauseLengthScale", PAUSE_SCALE)):
            if key in query:
                query[key] = value

        s = requests.post(
            f"{VOICEVOX_URL}/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=120,
        )
        s.raise_for_status()
        out_path.write_bytes(s.content)
        return True
    except Exception as e:
        print(f"[warn] 音声合成に失敗しました: {e}", file=sys.stderr)
        return False


def audio_duration(path: pathlib.Path) -> float:
    """ffprobeで実際の音声長(秒)を測る"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration", default="public/narration.json")
    parser.add_argument("--out-dir", default="build/audio")
    parser.add_argument("--speaker", type=int, default=DEFAULT_SPEAKER)
    args = parser.parse_args()

    npath = pathlib.Path(args.narration)
    if not npath.exists():
        # 原稿が無いと音声も動画の尺も決まらないため、なぜ無いのかを
        # 追えるように、探した場所を明示しておく
        print(f"[warn] ナレーション原稿が見つかりません: {npath.resolve()}")
        print("       generate_narration.py が失敗していないか確認してください")
        return

    with open(npath, "r", encoding="utf-8") as f:
        data = json.load(f)
    segments = data.get("segments", [])
    if not segments:
        print("[info] セグメントが空のためスキップします")
        return

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not engine_available():
        print(f"[warn] VOICEVOX ENGINE({VOICEVOX_URL})に接続できませんでした。"
              "音声なしで進めます(動画は無音になります)。")
        manifest = [{"index": i, "file": None, "duration": 0.0,
                     "kind": s.get("kind"), "text": s.get("text", ""),
                     "speaker": s.get("speaker", args.speaker),
                     "panel": s.get("panel"),
                     "meta": s.get("meta", {})}
                    for i, s in enumerate(segments)]
    else:
        manifest = []
        for i, seg in enumerate(segments):
            path = out_dir / f"seg_{i:03d}.wav"
            # 段が話者を指定していれば、そちらを使う。
            #
            # 対話の回は2人で喋る。台本の側に「この台詞は誰か」が
            # 入っているので、ここで拾えば1つの引数で全部を賄える。
            # 指定が無い段は、これまで通り --speaker のまま。
            speaker = seg.get("speaker")
            speaker = int(speaker) if isinstance(speaker, (int, str))                 and str(speaker).isdigit() else args.speaker
            ok = synth_one(seg.get("text", ""), speaker, path)
            dur = audio_duration(path) if ok else 0.0
            manifest.append({
                "index": i,
                "file": str(path) if ok else None,
                "duration": dur,
                "kind": seg.get("kind"),
                "text": seg.get("text", ""),
                "speaker": speaker,
                # 画面の札の鍵。長編だけが使う。
                # ここで持ち越さないと、動画側が台本と
                # 番号で突き合わせる羽目になる。段の数が
                # 1つでもずれたら、札が全部落ちる。
                "panel": seg.get("panel"),
                "meta": seg.get("meta", {}),
            })
            who = (seg.get("meta") or {}).get("who") or ""
            print(f"[info] seg_{i:03d}: {dur:.1f}秒 / {seg.get('kind')}"
                  + (f" / {who}(話者{speaker})" if who else ""))

    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump({"segments": manifest}, f, ensure_ascii=False)

    total = sum(m["duration"] for m in manifest)
    print(f"[info] 音声合成が完了しました(合計{total:.1f}秒)")


if __name__ == "__main__":
    main()
