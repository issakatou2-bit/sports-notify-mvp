#!/usr/bin/env python3
"""新しい見た目（COLLESPO_STYLE=v2）の全種類の見本を1枚に並べる。"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]


def _workflow_path(workflow_file: str | Path) -> Path:
    path = Path(workflow_file)
    if not path.is_absolute():
        if path.parts[:2] == (".github", "workflows"):
            path = ROOT / path
        else:
            path = ROOT / ".github" / "workflows" / path
    if path.suffix != ".yml":
        path = path.with_suffix(".yml")
    return path


def _resolve_env_value(value, repo_vars: dict[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = re.fullmatch(
        r"\$\{\{\s*vars\.([A-Za-z_][A-Za-z0-9_]*)\s*\|\|\s*(['\"])(.*?)\2\s*\}\}",
        text,
    )
    if m:
        return repo_vars.get(m.group(1), m.group(3))
    m = re.fullmatch(r"\$\{\{\s*vars\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", text)
    if m:
        return repo_vars.get(m.group(1), "")
    if text.startswith("${{"):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _workflow_env_pairs_from_yaml(path: Path) -> list[tuple[str, object]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pairs: list[tuple[str, object]] = []
    top_env = data.get("env")
    if isinstance(top_env, dict):
        pairs.extend(top_env.items())
    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            env = job.get("env")
            if isinstance(env, dict):
                pairs.extend(env.items())
            steps = job.get("steps")
            if isinstance(steps, list):
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    env = step.get("env")
                    if isinstance(env, dict):
                        pairs.extend(env.items())
    return pairs


def _workflow_env_pairs_from_lines(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "env:" or stripped.startswith("env:"):
            indent = len(line) - len(line.lstrip())
            i += 1
            while i < len(lines):
                raw = lines[i]
                if not raw.strip() or raw.lstrip().startswith("#"):
                    i += 1
                    continue
                raw_indent = len(raw) - len(raw.lstrip())
                if raw_indent <= indent:
                    break
                m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", raw)
                if m:
                    pairs.append((m.group(1), m.group(2).strip()))
                i += 1
            continue
        i += 1
    return pairs


def workflow_env(workflow_file: str | Path, repo_vars: dict[str, str]) -> dict[str, str]:
    path = _workflow_path(workflow_file)
    # PyYAML は on/off を真偽に変えて落とすので、GitHub と同じく文字のまま行で読む。
    pairs = _workflow_env_pairs_from_lines(path)
    env: dict[str, str] = {}
    for key, value in pairs:
        if not key.startswith("COLLESPO_") or key == "COLLESPO_SAMPLE_ONLY":
            continue
        resolved = _resolve_env_value(value, repo_vars)
        if resolved is not None:
            env[key] = resolved
    return env


def _run_code(body: str, env: dict | None = None) -> Image:
    """一時プロセスで body を実行し、保存した画像を開いて返す。"""
    merged = {**os.environ}
    merged.update(env or {})
    merged.setdefault("PYTHONUTF8", "1")

    fd, script = tempfile.mkstemp(suffix=".py")
    out_dir = Path(tempfile.mkdtemp())
    out = out_dir / "frame.png"
    try:
        code = f"""import os, sys
from pathlib import Path
ROOT = Path({str(ROOT)!r})
OUT_PATH = {str(out)!r}
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
os.environ.update({merged!r})
{body}
im.save(OUT_PATH)
"""
        os.write(fd, code.encode("utf-8"))
        os.close(fd)
        result = subprocess.run(
            [sys.executable, script],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=merged,
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "").splitlines()[-1]
            msg = msg or f"exit {result.returncode}"
            raise RuntimeError(msg)
        return Image.open(out)
    finally:
        Path(script).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 各種類の描画。材料は既存の試験・preview・fixtureを流用する。
# ---------------------------------------------------------------------------

def render_asset_video() -> Image:
    body = """
import json
from unittest.mock import patch
import generate_asset_video as asset
import review_render_v3 as r3
asset.VOICE_CREDIT = "音声: VOICEVOX:四国めたん"
saved = json.loads((ROOT / "scripts/fixtures/v3-rules/game-v4.json").read_text(encoding="utf-8"))
spec = saved["topics"][0]
key = spec["key"]
with patch.dict(asset.LIST_TOPICS, {key: spec}):
    nar = asset.build_narration(key)
seg = nar["segments"][0]
r3.set_program_clock(0)
r3.set_caption(seg["text"], 40, 40 * len(nar["segments"]))
with patch.dict(asset.LIST_TOPICS, {key: spec}):
    im = asset.render_v3(3, seg["kind"], seg["meta"], spec, key, seg=seg, dur=40)
r3.set_program_clock(None)
r3.set_caption("", 0, 0)

"""
    return _run_code(body)


def render_daily_video() -> Image:
    body = """
import bubble_styles as bs
import generate_video as daily
seg = {"text": "山本由伸は6回を投げて8奪三振。3打数1安打でした。", "speaker": 2}
im = bs.narration_frame(daily.render_intro(1, "10月14日"), seg, 2, 20)

"""
    return _run_code(body)


def render_ps_preview() -> Image:
    body = """
from datetime import datetime, timezone
import ps_editorial as policy
import generate_ps_preview as preview
snapshot = {"date": "2026-09-28", "phase": "regular", "teams": {}}
games = []
for i in range(4):
    lid = 103 if i < 2 else 104
    a, h, b = 100 + 3 * i, 101 + 3 * i, 102 + 3 * i
    for tid in (a, h, b):
        snapshot["teams"][str(tid)] = {"name": f"球団{tid}", "clinched": True}
    def team(tid):
        return {"id": tid, "name": f"球団{tid}", "abbreviation": f"T{tid}", "league": {"id": lid}}
    games.append({
        "gamePk": 1000 + i, "gameType": "F", "seriesGameNumber": 1,
        "officialDate": "2026-09-29", "gameDate": "2026-09-30T00:00:00Z",
        "status": {"abstractGameState": "Preview", "startTimeTBD": False},
        "teams": {"away": {"team": team(a)}, "home": {"team": team(h)}},
    })
    games.append({
        "gamePk": 2000 + i, "gameType": "D", "seriesGameNumber": 1,
        "officialDate": "2026-10-03", "gameDate": "2026-10-03T07:33:00Z",
        "status": {"abstractGameState": "Preview", "startTimeTBD": True},
        "teams": {"away": {"team": {"id": 9999, "name": f"T{a}/T{h}"}}, "home": {"team": team(b)}},
    })
schedule = {"dates": [{"games": games}]}
ctx = policy.editorial(snapshot, schedule, datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc), "https://statsapi.mlb.com/example")
seg = preview.cards(ctx)[0]
im = preview.render(ctx, seg)

"""
    return _run_code(body)


def render_ps_program() -> Image:
    body = """
from datetime import datetime
import ps_program as p
saved = p.read(ROOT / "scripts/fixtures/ps-design/2026-10-07.json")
now = datetime.fromisoformat(saved["evidence"]["retrieved_at"])
program = p.prepare(saved["snapshot"], saved["evidence"], "situation", now, saved["ledger"])
if not program:
    raise ValueError("試作材料に対応するPS枠がありません")
program["rehearsal"] = True
program["rehearsal_real_retrieved_at"] = now.isoformat()
p.check_program(program)
im, _ = p.render_segment(program["segments"][0])

"""
    return _run_code(body)


def render_longform() -> Image:
    body = """
from test_soccer_national_numbers import fixture_sheet, AS_OF
import soccer_national_long as long
import render_soccer_national_long as rl
import longform_render_v3 as v3
doc = long.dialogue(long.material("brazil", AS_OF, fixture_sheet()))
rl.prepare(doc)
key = next(iter(doc["panels"]))
seg = next(s for s in doc["segments"] if s["panel"] == key)
page = v3.paginate([seg])[0]
im = v3.render_line(8, page, topic=doc["top"], panel=doc["panels"][key], panel_t=8, chapters=doc["chapters"], dur=10)

"""
    return _run_code(body)


def render_player_story() -> Image:
    body = """
import test_player_story as player
import player_story_render as pr
pd = player.StoryTests().fixture()
ps = next(s for s in pd["segments"] if s["kind"] not in ("intro", "outro"))
im = pr.frame(0.1, ps, pd)

"""
    return _run_code(body)


def render_japan_reacts() -> Image:
    body = """
import japan_reacts as jr
jd = jr.read(ROOT / "scripts/fixtures/japan-reacts/sponichi-saved.json")
js = jd["segments"][1]
im = jr.frame(jd, 1.8, js)

"""
    return _run_code(body)


def render_soccer_now() -> Image:
    body = """
import soccer_now as now
import test_soccer_results as results
boards, summaries = results.fixture()
nd, errors = now.build(boards, summaries, now.results.utc("2026-09-20T17:15:00Z"), goal_short=None)
if errors:
    raise ValueError(errors)
ns = next(s for s in now.narration(nd[0])["segments"] if s["kind"] not in ("cover", "intro", "outro"))
im = now.frame(nd[0], 1.5, ns)

"""
    return _run_code(body)


def render_soccer_goal_short() -> Image:
    body = """
import soccer_goal_short as gs
import soccer_results_render as rr
import test_soccer_results as results
boards, summaries = results.fixture()
items, _ = gs.build(boards, summaries, gs.now.results.utc("2026-09-20T17:15:00Z"))
if not items:
    raise ValueError("goal short 用の材料がありません")
data = items[0]
nar = rr.production_narration(data, goal_short=True)
seg = next(s for s in nar["segments"] if s["kind"] not in ("intro", "outro"))
im = rr.frame(1.5, seg, data)

"""
    return _run_code(body)


def render_soccer_race() -> Image:
    body = """
import json
import soccer_slots_v4 as soccer
data = json.loads((ROOT / "scripts/fixtures/soccer-slots/race.json").read_text(encoding="utf-8"))
plan = soccer.program("race", data)
seg = next(s for s in plan["narration"]["segments"] if s["kind"] not in ("cover", "intro", "outro"))
im = soccer.frame(1.5, seg, plan)

"""
    return _run_code(body)


def render_soccer_week() -> Image:
    body = """
import json
import soccer_slots_v4 as soccer
data = json.loads((ROOT / "scripts/fixtures/soccer-slots/week.json").read_text(encoding="utf-8"))
plan = soccer.program("week", data)
seg = next(s for s in plan["narration"]["segments"] if s["kind"] not in ("cover", "intro", "outro"))
im = soccer.frame(1.5, seg, plan)

"""
    return _run_code(body)


def render_soccer_results() -> Image:
    body = """
import test_soccer_results as results
import soccer_results_render as rr
data = results.fixed()
seg = next(s for s in rr.narration(data)["segments"] if s["kind"] not in ("intro", "outro"))
im = rr.frame(1.5, seg, data)

"""
    return _run_code(body)


def render_soccer_voices() -> Image:
    body = """
import test_soccer_voices as voices
import soccer_voices as sv
import soccer_voices_render as vr
vd = voices.sample()
vs = next(s for s in sv.narration(vd)["segments"] if s["kind"] not in ("intro", "outro"))
im = vr.frame(1.5, vs, vd, vr.clubs_for(vd), 20)

"""
    return _run_code(body)


def render_soccer_national() -> Image:
    env = {
        "COLLESPO_SOCCER_LOOK": "v6",
        "COLLESPO_SOCCER_FOCUS": "on",
        "COLLESPO_SHORT_LOOK": "v4",
        "COLLESPO_SOLO_HOST": "metan",
    }
    body = """
import soccer_national as n
import soccer_national_render as render
import review_render_v3 as r3
data = n.squad(n.read(ROOT / "scripts/fixtures/national-pitch/soccer_national_squad.json"), {}, "2026-11-09T10:15:00+09:00", 4)
doc = n.narration(data)
clubs = render.clubs_for(data)
seg = doc["segments"][1]
r3.set_program_clock(0)
r3.set_caption(seg["text"], 3.2, 20, speaker=2)
im = render.frame(0, seg, data, clubs)
r3.set_program_clock(None)
r3.set_caption("", 0, 0)

"""
    return _run_code(body, env)


def render_soccer_national_topics() -> Image:
    env = {
        "COLLESPO_SOCCER_LOOK": "v6",
        "COLLESPO_SOCCER_FOCUS": "on",
        "COLLESPO_SHORT_LOOK": "v4",
        "COLLESPO_SOLO_HOST": "metan",
    }
    body = """
import soccer_national as n
import soccer_national_topics as topics
import soccer_national_topics_render as render
import review_render_v3 as r3
doc = topics.narration(n.read(ROOT / "scripts/fixtures/soccer_national_topics.json"), "team-numbers", meetings=[])
clubs = render.clubs_for(doc)
seg = doc["segments"][5]
r3.set_program_clock(0)
r3.set_caption(seg["text"], 3.2, 20, speaker=seg["speaker"])
im = render.frame(1.0, seg, doc, clubs)
r3.set_program_clock(None)
r3.set_caption("", 0, 0)

"""
    return _run_code(body, env)


def render_soccer_national_long() -> Image:
    body = """
from test_soccer_national_numbers import fixture_sheet, AS_OF
import soccer_national_long as long
import render_soccer_national_long as rl
import longform_render_v3 as v3
doc = long.dialogue(long.material("brazil", AS_OF, fixture_sheet()))
rl.prepare(doc)
key = next(iter(doc["panels"]))
seg = next(s for s in doc["segments"] if s["panel"] == key)
page = v3.paginate([seg])[0]
im = v3.render_line(8, page, topic=doc["top"], panel=doc["panels"][key], panel_t=8, chapters=doc["chapters"], dur=10)

"""
    return _run_code(body)


def render_soccer_weekly_long() -> Image:
    body = """
import json
import soccer_weekly_long as w
import longform_render_v3 as v3
nights = json.loads((ROOT / "scripts/fixtures/soccer_weekly_long.json").read_text(encoding="utf8"))
data = w.aggregate(nights, "2026-11-02")
doc = w.dialogue(data)
key = next(iter(doc["panels"]))
seg = next(s for s in doc["segments"] if s["panel"] == key)
page = v3.paginate([seg])[0]
im = v3.render_line(8, page, topic=doc["top"], panel=doc["panels"][key], panel_t=8, chapters=doc["chapters"], dur=10)

"""
    return _run_code(body)


def render_morning_design_preview() -> Image:
    body = """
import json
import bignumber_render as bn
import generate_morning_short as gms
bn._no_network()
path = ROOT / "scripts/fixtures/bignumber/recap_history/2026-09-25.json"
data = json.loads(path.read_text(encoding="utf-8"))
players = gms.sort_players(data.get("players") or [])
data = dict(data, players=players)
narration = gms.build_narration(data, "players")
scenes = bn.scenes_from_morning(data, narration)
plan = bn.timeline(scenes, bn.estimate_durations(narration))
im = bn.frame(3.0, plan)

"""
    return _run_code(body)


def render_weekly_summary() -> Image:
    body = """
import bubble_styles as bs
import generate_weekly as weekly
seg = {"text": "山本由伸は6回を投げて8奪三振。3打数1安打でした。", "speaker": 2}
im = bs.narration_frame(weekly.render_intro(1, "保存材料の週次まとめ"), seg, 2, 20)

"""
    return _run_code(body)


def render_weekly_verdict() -> Image:
    body = """
import generate_verdict_short as verdict
im = verdict.render_outro(1)

"""
    return _run_code(body)


def render_thumbnail() -> Image:
    body = """
import generate_thumbnail as gt
im, d = gt.base()
gt.draw_asset(d, "mlb_abbr")

"""
    return _run_code(body)


def render_cover() -> Image:
    body = """
import render_shorts_cover as cover
meta = dict(subject="大谷翔平", fact="4打数3安打", matchup="ドジャース 対 パドレス", time="明日 8:00", team="ドジャース")
im = cover.render_cover(meta)

"""
    return _run_code(body)


# ---------------------------------------------------------------------------
# 種類の定義。workflows は .github/workflows/*.yml のうち COLLESPO_STYLE を渡す物。
# ---------------------------------------------------------------------------
KINDS = {
    "asset_video": {
        "workflows": [
            "asset_video",
            "correct_video",
            "design_preview",
            "offseason_news",
            "ps_game_now",
            "season_review",
        ],
        "render": render_asset_video,
        "why": "",
    },
    "daily_video": {
        "workflows": ["soccer_daily", "repair_daily_20260912"],
        "render": render_daily_video,
        "why": "",
    },
    "ps_preview": {
        "workflows": ["ps_preview", "morning_recap"],
        "render": render_ps_preview,
        "why": "",
    },
    "ps_program": {
        "workflows": ["ps_program_preview", "daily_notify"],
        "render": render_ps_program,
        "why": "",
    },
    "longform": {
        "workflows": ["longform"],
        "render": render_longform,
        "why": "",
    },
    "player_story": {
        "workflows": ["player_story"],
        "render": render_player_story,
        "why": "",
    },
    "japan_reacts": {
        "workflows": ["japan_reacts"],
        "render": render_japan_reacts,
        "why": "",
    },
    "soccer_now": {
        "workflows": ["soccer_now"],
        "render": render_soccer_now,
        "why": "",
    },
    "soccer_goal_short": {
        "workflows": ["soccer_goal_short"],
        "render": render_soccer_goal_short,
        "why": "",
    },
    "soccer_race": {
        "workflows": ["soccer_race"],
        "render": render_soccer_race,
        "why": "",
    },
    "soccer_week": {
        "workflows": ["soccer_week"],
        "render": render_soccer_week,
        "why": "",
    },
    "soccer_results": {
        "workflows": ["soccer_results"],
        "render": render_soccer_results,
        "why": "",
    },
    "soccer_voices": {
        "workflows": ["soccer_voices"],
        "render": render_soccer_voices,
        "why": "",
    },
    "soccer_national": {
        "workflows": ["soccer_national"],
        "render": render_soccer_national,
        "why": "",
    },
    "soccer_national_topics": {
        "workflows": ["soccer_national_topics"],
        "render": render_soccer_national_topics,
        "why": "",
    },
    "soccer_national_long": {
        "workflows": ["soccer_national_long"],
        "render": render_soccer_national_long,
        "why": "",
    },
    "soccer_weekly_long": {
        "workflows": ["soccer_weekly_long"],
        "render": render_soccer_weekly_long,
        "why": "",
    },
    "morning_design_preview": {
        "workflows": ["morning_design_preview"],
        "render": render_morning_design_preview,
        "why": "",
    },
    "weekly_summary": {
        "workflows": ["weekly_summary"],
        "render": render_weekly_summary,
        "why": "",
    },
    "weekly_verdict": {
        "workflows": ["weekly_summary"],
        "render": render_weekly_verdict,
        "why": "",
    },
    "thumbnail": {
        "workflows": [],
        "render": render_thumbnail,
        "why": "",
    },
    "cover": {
        "workflows": [],
        "render": render_cover,
        "why": "",
    },
    "ui_voice_stock": {
        "workflows": ["ui_voice_stock"],
        "render": None,
        "why": "描画を行わず在庫注文だけのため、代表する1コマが無い",
    },
}


def _fit_size(im: Image.Image) -> tuple[int, int]:
    """縦長なら 270x480、横長なら 480x270 に縮める。"""
    if im.width >= im.height:
        return (480, 270)
    return (270, 480)


def main() -> None:
    ap = argparse.ArgumentParser(description="新しい見た目の全種類の見本を1枚に並べる")
    ap.add_argument("--out", type=Path, required=True, help="出力PNG")
    ap.add_argument("--only", default="", help="描く種類をカンマ区切りで限定")
    ap.add_argument("--vars", type=Path, help="本番の切替（KEY=値 の行。gh variable list で取る）。見本を本番と同じ旗で描く")
    args = ap.parse_args()
    # 見本は本番と同じ旗で描く（11/12 代表の回が見本から漏れ、本番で旧い見た目が出た）。
    repo_vars: dict[str, str] = {}
    if args.vars:
        for line in args.vars.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.startswith("COLLESPO_"):
                repo_vars[key] = value
                os.environ[key] = value
    # 試験の材料で描くので、本番の材料として扱わない印を付ける。
    os.environ["COLLESPO_SAMPLE_ONLY"] = "true"

    only = {x.strip() for x in args.only.split(",") if x.strip()}

    results: list[tuple[str, str, object]] = []
    for name, info in KINDS.items():
        if only and name not in only:
            continue
        fn = info.get("render")
        if fn is None:
            results.append((name, "unsupported", info.get("why", "")))
            continue
        kind_env = {}
        if info.get("workflows"):
            kind_env = workflow_env(info["workflows"][0], repo_vars)
        saved = {key: os.environ.get(key) for key in kind_env}
        os.environ.update(kind_env)
        try:
            im = fn()
        except Exception as exc:
            results.append((name, "error", (str(exc).splitlines() or [type(exc).__name__])[0]))
        else:
            results.append((name, "ok", im))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    cell_w, cell_h = 500, 550
    cols = 3
    rows = (len(results) + cols - 1) // cols
    canvas = Image.new("RGB", (cell_w * cols, cell_h * rows), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)

    font_path = ROOT / "assets/fonts/soccer-v5/NotoSansJP-VF.ttf"
    try:
        label_font = ImageFont.truetype(str(font_path), 24)
    except Exception:
        label_font = ImageFont.load_default()

    try:
        lanczos = Image.Resampling.LANCZOS
    except AttributeError:
        lanczos = Image.LANCZOS

    for i, (name, status, payload) in enumerate(results):
        x = (i % cols) * cell_w
        y = (i // cols) * cell_h
        if status == "ok":
            im = payload.resize(_fit_size(payload), lanczos)
            cx = x + cell_w // 2
            cy = y + cell_h // 2 - 20
            canvas.paste(im, (cx - im.width // 2, cy - im.height // 2))
        elif status == "unsupported":
            draw.rectangle(
                (x + 20, y + 20, x + cell_w - 20, y + cell_h - 60),
                fill=(80, 80, 80),
                outline=(120, 120, 120),
                width=2,
            )
            text = f"未対応：{payload}" if payload else "未対応"
            draw.text((x + 30, y + 30), text, fill=(220, 220, 220), font=label_font)
        else:
            draw.rectangle(
                (x + 20, y + 20, x + cell_w - 20, y + cell_h - 60),
                fill=(120, 50, 50),
                outline=(200, 100, 100),
                width=2,
            )
            draw.text(
                (x + 30, y + 30),
                f"失敗：{payload}",
                fill=(255, 220, 220),
                font=label_font,
            )
        draw.text((x + 20, y + cell_h - 45), name, fill=(230, 230, 230), font=label_font)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out)

    ok = sum(1 for _, s, _ in results if s == "ok")
    unsupported = sum(1 for _, s, _ in results if s == "unsupported")
    err = sum(1 for _, s, _ in results if s == "error")
    print(f"描けた数：{ok}／未対応の数：{unsupported}／失敗の数：{err}")


if __name__ == "__main__":
    main()
