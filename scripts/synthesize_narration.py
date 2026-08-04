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

VOICEVOX_URL = "http://127.0.0.1:50021"
# 話者ID。VOICEVOXのspeakersエンドポイントで確認できる。
# 3 = ずんだもん(ノーマル)が一般的だが、環境により異なる場合がある。
DEFAULT_SPEAKER = 3
# 少しゆっくりめの方が聞き取りやすい
SPEED_SCALE = 1.05


def engine_available() -> bool:
    try:
        r = requests.get(f"{VOICEVOX_URL}/version", timeout=5)
        return r.ok
    except Exception:
        return False


def synth_one(text: str, speaker: int, out_path: pathlib.Path) -> bool:
    """1セグメント分の音声を合成する。成功したらTrue。"""
    try:
        q = requests.post(
            f"{VOICEVOX_URL}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=30,
        )
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = SPEED_SCALE

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
        print("[info] ナレーション原稿が無いため、音声合成をスキップします")
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
        print("[warn] VOICEVOX ENGINEに接続できませんでした。"
              "音声なしで進めます(動画は無音になります)。")
        manifest = [{"index": i, "file": None, "duration": 0.0,
                     "kind": s.get("kind"), "text": s.get("text", ""),
                     "meta": s.get("meta", {})}
                    for i, s in enumerate(segments)]
    else:
        manifest = []
        for i, seg in enumerate(segments):
            path = out_dir / f"seg_{i:03d}.wav"
            ok = synth_one(seg.get("text", ""), args.speaker, path)
            dur = audio_duration(path) if ok else 0.0
            manifest.append({
                "index": i,
                "file": str(path) if ok else None,
                "duration": dur,
                "kind": seg.get("kind"),
                "text": seg.get("text", ""),
                "meta": seg.get("meta", {}),
            })
            print(f"[info] seg_{i:03d}: {dur:.1f}秒 / {seg.get('kind')}")

    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump({"segments": manifest}, f, ensure_ascii=False)

    total = sum(m["duration"] for m in manifest)
    print(f"[info] 音声合成が完了しました(合計{total:.1f}秒)")


if __name__ == "__main__":
    main()
