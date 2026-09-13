"""観戦の見取り図: 確認済み原稿から音声・字幕・動画を作る独立した試作枠。"""
import argparse
import array
import hashlib
import io
import json
import math
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import wave
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "content/pilot_series"
RENDER_VERSION = "2"
SCENES = {"hook": 1, "fork": 2, "points": 2, "grid": 3,
          "ladder": 3, "national": 1, "checklist": 1, "end": 0}
BASEBALL_SCENES = {"bb_photo": 3, "bb_hits": 1, "bb_inning": 6,
                   "bb_compare": 1, "bb_check": 1, "bb_end": 0}
PRESENTERS = {"metan": ("四国めたん", 2), "zundamon": ("ずんだもん", 3)}


def voice_profiles(data):
    return data.get("voices", {"metan": data.get("voice", {})})


def segment_voice(data, segment):
    key = segment.get("speaker", "metan")
    if key not in voice_profiles(data):
        raise ValueError("原稿の話者に対応する音声設定がありません")
    return voice_profiles(data)[key]


def voice_credits(data):
    names = dict.fromkeys(segment_voice(data, s)["name"] for s in data["segments"])
    return " / ".join("VOICEVOX:" + name for name in names)


def write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_episode(path, today=None):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    validate_episode(data, today)
    return data


def validate_episode(data, today=None):
    today = today or date.today()
    if data.get("schema_version") != 1 or data.get("status") != "ready":
        raise ValueError("確認済みの原稿だけを生成できます")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data.get("id", "")):
        raise ValueError("不正な企画ID")
    if not isinstance(data.get("revision"), int) or data["revision"] < 1:
        raise ValueError("原稿の版が必要です")
    if not 1 <= len(data.get("title", "")) <= 100 or any(c in data["title"] for c in "<>\n"):
        raise ValueError("題の長さ・書式を確認してください")
    reviewed, valid = date.fromisoformat(data["reviewed_on"]), date.fromisoformat(data["valid_until"])
    if not reviewed <= today <= valid or (valid - reviewed).days > 180:
        raise ValueError("出典の確認期限を過ぎています。再確認してから生成してください")
    if not data.get("sources") or not all(s.get("label") and s.get("url", "").startswith("https://")
                                          for s in data["sources"]):
        raise ValueError("公式出典が必要です")
    profiles = voice_profiles(data)
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("試作枠の音声設定が必要です")
    for key, voice in profiles.items():
        if (key not in PRESENTERS or not isinstance(voice, dict)
                or (voice.get("name"), voice.get("speaker")) != PRESENTERS[key]
                or voice.get("style") != "ノーマル"):
            raise ValueError("試作枠で確認した話者とスタイルを使ってください")
        for field, low, high, default in [("speed", .9, 1.3, 0), ("pitch", -.15, .15, 0)]:
            value = voice.get(field, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError("音声の速度・高さを確認してください")
    if not 12 <= len(data.get("segments", [])) <= 35:
        raise ValueError("原稿の区切り数を確認してください")
    baseball = data.get("visual_style") == "baseball-hits-v1"
    scenes = BASEBALL_SCENES if baseball else SCENES
    if data.get("visual_style") not in (None, "baseball-hits-v1"):
        raise ValueError("対応していない画面の方式です")
    for segment in data["segments"]:
        segment_voice(data, segment)
        if segment.get("scene") not in scenes or not isinstance(segment.get("phase"), int):
            raise ValueError("対応していない画面です")
        if not 0 <= segment["phase"] <= scenes[segment["scene"]]:
            raise ValueError("対応していない画面の段階です")
        if not 5 <= len(segment.get("text", "")) <= 78 or not segment.get("chapter"):
            raise ValueError("字幕の量・章の名前を確認してください")
        if not 5 <= len(segment.get("speech", segment["text"])) <= 160:
            raise ValueError("読み上げ原稿が長すぎます")
    facts = data.get("facts", {})
    expected = ({"a_hits": 2, "a_total_bases": 2, "a_runs": 0, "b_hits": 2, "b_total_bases": 3, "b_runs": 1}
                if baseball else {"clubs": 36, "opponents": 8, "home": 4, "away": 4, "direct": 8, "playoff_end": 24})
    if facts != expected:
        raise ValueError("大会の方式が変わっています。図と原稿を再確認してください")
    if baseball:
        import pilot_media
        assets = pilot_media.assets_for(data)
        if len(assets) != 2 or any(a["kind"] != "image" for a in assets):
            raise ValueError("第2回は確認済みの写真2枚が必要です")
        for segment in data["segments"]:
            if segment["scene"] == "bb_photo" and segment.get("media_id") not in data["media_ids"]:
                raise ValueError("画面の写真が使用素材と一致しません")


def episode_key(data):
    payload = {"episode": data, "renderer": RENDER_VERSION}
    # 既存第1回の識別子を変えず、実写を使う回だけ素材の版も含める。
    if data.get("media_ids"):
        import pilot_media
        payload["media_assets"] = pilot_media.assets_for(data)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return data["id"] + "-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def wave_info(path):
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError("16bitモノラル音声が必要です")
        frames, rate = audio.getnframes(), audio.getframerate()
        samples = array.array("h", audio.readframes(frames))
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(v) for v in samples), default=0) / 32768
    rms = math.sqrt(sum(v * v for v in samples) / max(1, len(samples))) / 32768
    if not 1 <= frames / rate <= 35 or peak < .015 or rms < .001:
        raise ValueError("音声が無音・短すぎる・長すぎるため動画化しません")
    return {"duration": frames / rate, "sample_rate": rate, "peak": peak, "rms": rms}


def voice_request(base, endpoint, params=None, body=None):
    url = base.rstrip("/") + endpoint
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="POST" if params or body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def synthesize(data, out, base="http://127.0.0.1:50021"):
    out = pathlib.Path(out)
    directory = out / "audio"
    directory.mkdir(parents=True, exist_ok=True)
    version = json.loads(voice_request(base, "/version"))
    speakers = json.loads(voice_request(base, "/speakers"))
    for voice in voice_profiles(data).values():
        if not any(s["name"] == voice["name"] and any(st["id"] == voice["speaker"] and st["name"] == voice["style"]
                                                     for st in s["styles"]) for s in speakers):
            raise ValueError("音声エンジンの話者が想定と違います")
    entries, start, rate = [], 0., None
    chunks = []
    for i, segment in enumerate(data["segments"]):
        voice = segment_voice(data, segment)
        speech = segment.get("speech", segment["text"])
        query = json.loads(voice_request(base, "/audio_query", {"text": speech, "speaker": voice["speaker"]}))
        query.update(speedScale=voice["speed"], pitchScale=voice.get("pitch", 0), intonationScale=1.05,
                     prePhonemeLength=.06, postPhonemeLength=.15, outputStereo=False)
        if "pauseLengthScale" in query:
            query["pauseLengthScale"] = .95
        raw = voice_request(base, "/synthesis", {"speaker": voice["speaker"]}, query)
        path = directory / f"{i:02d}.wav"
        path.write_bytes(raw)
        info = wave_info(path)
        if rate is not None and rate != info["sample_rate"]:
            raise ValueError("音声のサンプルレートが一致しません")
        rate = info["sample_rate"]
        with wave.open(io.BytesIO(raw), "rb") as audio:
            chunks.append(audio.readframes(audio.getnframes()))
        entries.append({**segment, "speaker_name": voice["name"], "speaker_id": voice["speaker"],
                        "start": start, **info, "kana": query.get("kana", ""), "file": f"audio/{i:02d}.wav"})
        start += info["duration"]
        print(f"音声 {i + 1}/{len(data['segments'])}: {info['duration']:.1f}秒", flush=True)
    if not 100 <= start <= 240:
        raise ValueError(f"総尺{start:.1f}秒が試作枠の100〜240秒を外れています")
    with wave.open(str(out / "narration.wav"), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for chunk in chunks:
            audio.writeframes(chunk)
    manifest = {"episode_key": episode_key(data), "voicevox_version": version,
                "duration": start, "segments": entries}
    write_json(out / "timeline.json", manifest)
    write_subtitles(entries, out / "captions.srt")
    return manifest


def write_subtitles(entries, path):
    def timestamp(seconds):
        ms = round(seconds * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    blocks = [f"{i + 1}\n{timestamp(s['start'])} --> {timestamp(s['start'] + s['duration'])}\n{s['text']}\n"
              for i, s in enumerate(entries)]
    pathlib.Path(path).write_text("\n".join(blocks), encoding="utf-8")


def verify_video(out):
    out = pathlib.Path(out)
    manifest = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                             str(out / "episode.mp4")], check=True, capture_output=True, text=True)
    meta = json.loads(result.stdout)
    videos = [s for s in meta["streams"] if s["codec_type"] == "video"]
    audios = [s for s in meta["streams"] if s["codec_type"] == "audio"]
    if len(videos) != 1 or len(audios) != 1 or (videos[0]["width"], videos[0]["height"]) != (1920, 1080):
        raise ValueError("映像と音声の形式が不正です")
    duration = float(meta["format"]["duration"])
    if abs(duration - manifest["duration"]) > .15:
        raise ValueError("映像と音声の尺が一致しません")
    levels = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out / "episode.mp4"),
                              "-af", "volumedetect", "-vn", "-f", "null", "-"],
                             capture_output=True, text=True, check=True).stderr
    peak = re.search(r"max_volume: ([-\d.]+) dB", levels)
    mean = re.search(r"mean_volume: ([-\d.]+) dB", levels)
    if not peak or not mean or not -15 <= float(peak[1]) <= -.1 or not -30 <= float(mean[1]) <= -10:
        raise ValueError("動画音声の音量を確認してください")
    checks = {"episode_key": manifest["episode_key"], "passed": True,
              "duration": duration, "width": 1920, "height": 1080,
              "audio_peak_db": float(peak[1]), "audio_mean_db": float(mean[1]),
              "video_sha256": hashlib.sha256((out / "episode.mp4").read_bytes()).hexdigest()}
    write_json(out / "quality.json", checks)
    print(json.dumps(checks, ensure_ascii=False))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "preview", "synthesize", "render", "verify"])
    parser.add_argument("--episode", default="football-two-tables")
    parser.add_argument("--out", default="build/pilot")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+", args.episode):
        parser.error("企画IDが不正です")
    data = load_episode(CATALOG / (args.episode + ".json"))
    out = pathlib.Path(args.out)
    if args.command == "validate":
        print("原稿・出典・確認期限を検査しました:", episode_key(data))
    elif args.command == "synthesize":
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "episode.json", data)
        synthesize(data, out)
    elif args.command == "verify":
        verify_video(out)
    else:
        import pilot_render
        if args.command == "preview":
            pilot_render.preview(data, out)
        else:
            pilot_render.render(data, out)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
