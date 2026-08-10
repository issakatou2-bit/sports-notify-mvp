"""
YouTubeのカスタムサムネイル(1280×720)を作る。

なぜ必要か:
  指定しないとYouTubeが動画中のコマを自動で選ぶ。ショートでも
  検索結果・関連動画・チャンネルページではサムネイルが出るため、
  そこが自動選択のままだと「たまたま切り取られた1コマ」で
  クリックされるかどうかが決まってしまう。

設計:
  ・動画の1枚目と同じフックを使う。サムネで見た話とタイトル・中身が
    一致しないと、開いた瞬間に閉じられる
  ・スマホの検索結果では横幅が小さいので、文字は極端に大きく、
    要素は3つまで(フック / 対戦カード / 日付)に絞る
  ・写真素材は使わない。著作権上の懸念が無く、毎日同じ品質で出せる

使い方:
  # 日次(ナレーション原稿のフックを使う)
  python3 scripts/generate_thumbnail.py --kind daily \
      --games notable_games.json --narration public/narration.json \
      --out build/video/thumb.png
  # 資産動画
  python3 scripts/generate_thumbnail.py --kind asset --asset-topic mlb_abbr \
      --out build/asset/thumb.png
"""

import argparse
import json
import os
import pathlib
import subprocess

from PIL import Image, ImageDraw, ImageFont

# YouTube推奨サイズ。2MB以内に収める必要がある(PNGでも十分収まる)
W, H = 1280, 720

BG = (11, 14, 20)
SURF = (18, 22, 31)
TEXT = (242, 240, 230)
DIM = (136, 145, 163)
ACCENT = (255, 176, 32)
JP = (73, 197, 182)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]
_FONT_FILE = None

# 資産動画のサムネ文言。動画の中身と一致させる。
ASSET_THUMB = {
    "mlb_abbr": ("LAD って どこ？", "MLB30球団の略称", "地区ごとに覚える"),
    "mlb_venue": ("点が入る球場", "入らない球場", "MLBの球場の癖"),
    "mlb_rivalry": ("なぜ因縁の対決？", "MLB 伝統の一戦", "由来から知る"),
    "mlb_stats": ("OPS って何？", "この数字だけ分かればいい", "防御率・WHIPも"),
    "mlb_terms": ("順位表、こう読む", "ゲーム差・ワイルドカード", "試合の重みが分かる"),
    "mlb_league": ("30球団の分かれ方", "2リーグ 6地区", "まずここから"),
    "mlb_position": ("SS ってどこ？", "守備位置の略号", "スタメン表が読める"),
    "collespo_guide": ("毎日19時に届く", "今日の注目試合を理由つきで", "登録は無料"),
    # 1球場ずつの深掘り。サムネでは「なぜそうなるのか」を問いの形で出す
    "venue_coors": ("なぜ点が入る？", "クアーズ・フィールド", "標高1600mの球場"),
    "venue_fenway": ("この壁、高さ11m", "フェンウェイ・パーク", "MLB現役最古"),
    "venue_wrigley": ("風で試合が変わる", "リグレー・フィールド", "ツタの生えた球場"),
    "venue_oracle": ("打球が海に落ちる", "オラクル・パーク", "MLB屈指の投手有利"),
    "venue_yankee": ("左打者天国の理由", "ヤンキー・スタジアム", "右翼が浅い"),
    "jp_players": ("今、何人いる？", "MLBの日本人選手", "2026年シーズン"),
    "mlb_watch": ("どこで見られる？", "日本でMLBを見る", "中継・時間帯"),
    "mlb_postseason": ("どう決まる？", "MLBのポストシーズン", "ワイルドカードとは"),
}


def _resolve_font() -> str:
    global _FONT_FILE
    if _FONT_FILE:
        return _FONT_FILE
    env = os.environ.get("COLLESPO_FONT")
    if env and pathlib.Path(env).exists():
        _FONT_FILE = env
        return _FONT_FILE
    for p in FONT_CANDIDATES:
        if pathlib.Path(p).exists():
            _FONT_FILE = p
            return p
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                           capture_output=True, text=True, check=True)
        if r.stdout.strip():
            _FONT_FILE = r.stdout.strip()
            return _FONT_FILE
    except Exception:
        pass
    raise RuntimeError("日本語フォントが見つかりません")


def font(size: int):
    path = _resolve_font()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        for i in (1, 2, 3):
            try:
                return ImageFont.truetype(path, size, index=i)
            except OSError:
                continue
        raise


def fit(d, text: str, max_w: int, sizes) -> int:
    """1行に収まる最大のフォントサイズを実測で選ぶ"""
    for s in sizes:
        if d.textlength(text, font=font(s)) <= max_w:
            return s
    return sizes[-1]


def base():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for i in range(-1, 7):
        x = i * 250
        d.polygon([(x, H), (x + 105, H), (x + 290, 0), (x + 185, 0)],
                  fill=(14, 18, 26))
    d.rectangle([0, H - 14, W, H], fill=ACCENT)
    return im, d


def load_hook(narration_path: str) -> dict:
    try:
        data = json.loads(pathlib.Path(narration_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    for s in data.get("segments", []):
        if s.get("kind") == "intro":
            return (s.get("meta") or {}).get("hook") or {}
    return {}


def draw_daily(d, hook: dict, games: list, date_label: str):
    sub = (hook.get("sub") or "").strip()
    big = (hook.get("big") or "今日の注目試合").strip()

    y = 90
    if sub:
        s = fit(d, sub, W - 140, (76, 64, 56, 48))
        d.text((70, y), sub, font=font(s), fill=JP)
        y += s + 24

    # フックは可能な限り大きく。スマホの一覧でも読めることが最優先
    s = fit(d, big, W - 140, (150, 132, 116, 100, 88, 76))
    d.text((70, y), big, font=font(s), fill=ACCENT)
    y += s + 40

    # 対戦カードは2試合まで。3つ並べると字が小さくなり読めない
    for g in games[:2]:
        line = f"{g.get('home_team_name')} vs {g.get('away_team_name')}"
        ls = fit(d, line, W - 200, (54, 48, 42, 38))
        d.rounded_rectangle([70, y, W - 70, y + ls + 26], 12, fill=SURF)
        d.text((96, y + 12), line, font=font(ls), fill=TEXT)
        y += ls + 40

    d.text((70, H - 78), f"{date_label}  コレスポ", font=font(38), fill=DIM)


def draw_weekly(d, label: str):
    d.text((70, 110), "今週の", font=font(80), fill=TEXT)
    d.text((70, 210), "答え合わせ", font=font(140), fill=ACCENT)
    d.text((70, 400), "注目した試合は、実際どうだったか", font=font(52), fill=TEXT)
    d.text((70, H - 130), label, font=font(56), fill=JP)
    d.text((70, H - 66), "コレスポ 週間まとめ", font=font(36), fill=DIM)


def draw_morning(d, day: str, players: list):
    d.text((70, 90), day, font=font(56), fill=DIM)
    d.text((70, 170), "日本人選手の成績", font=font(112), fill=ACCENT)

    # 名前と成績を2人ぶんだけ。サムネで読ませられるのはこのくらい
    y = 340
    for p in players[:2]:
        line = f"{p.get('name', '')}　{p.get('headline', '')}"
        s = fit(d, line, W - 200, (58, 52, 46, 40))
        d.rounded_rectangle([70, y, W - 70, y + s + 34], 14, fill=SURF)
        d.text((100, y + 14), line, font=font(s), fill=TEXT)
        y += s + 56

    d.text((70, H - 78), f"出場 {len(players)}人　コレスポ", font=font(38), fill=JP)


def draw_verdict(d, label: str):
    d.text((70, 110), "注目した試合", font=font(76), fill=TEXT)
    d.text((70, 210), "どうなった？", font=font(140), fill=ACCENT)
    d.text((70, 400), "連勝は続いたのか、止まったのか", font=font(52), fill=TEXT)
    d.text((70, H - 130), label, font=font(56), fill=JP)
    d.text((70, H - 66), "コレスポ 先週の答え合わせ", font=font(36), fill=DIM)


def draw_asset(d, topic: str):
    big, mid, small = ASSET_THUMB.get(
        topic, ("コレスポ", "MLB入門", "collespo.com"))
    s = fit(d, big, W - 140, (150, 132, 116, 100))
    d.text((70, 120), big, font=font(s), fill=ACCENT)
    s2 = fit(d, mid, W - 140, (84, 72, 64, 56))
    d.text((70, 320), mid, font=font(s2), fill=TEXT)
    d.text((70, 440), small, font=font(52), fill=JP)
    d.text((70, H - 78), "コレスポ  collespo.com", font=font(38), fill=DIM)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", default="daily",
                        choices=["daily", "weekly", "asset", "verdict", "morning"])
    parser.add_argument("--recap", default="data/morning_recap.json")
    parser.add_argument("--games", default="notable_games.json")
    parser.add_argument("--narration", default="public/narration.json")
    parser.add_argument("--asset-topic", default="mlb_abbr")
    parser.add_argument("--label", default="")
    parser.add_argument("--archive-dir", default="archive",
                        help="週次で --label を省いたときの期間の算出元")
    parser.add_argument("--out", default="build/thumb.png")
    args = parser.parse_args()

    im, d = base()

    if args.kind == "morning":
        try:
            rec = json.loads(pathlib.Path(args.recap).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("[info] 成績データが読めないため、サムネイルは作りません")
            return
        players = rec.get("players") or []
        if not players:
            print("[info] 出場選手がいないため、サムネイルは作りません")
            return
        day = rec.get("date", "")
        try:
            from datetime import datetime as _dt
            _p = _dt.strptime(day, "%Y-%m-%d")
            day = f"{_p.month}月{_p.day}日"
        except ValueError:
            pass
        draw_morning(d, day, players)
    elif args.kind == "asset":
        draw_asset(d, args.asset_topic)
    elif args.kind in ("weekly", "verdict"):
        label = args.label
        if not label:
            # 動画・タイトルと同じ条件で週の範囲を求める。
            # ここだけ別に計算すると、サムネの日付だけずれる
            try:
                import sys

                sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
                import weekly_stats as ws

                week = ws.load_week(pathlib.Path(args.archive_dir))
                if week:
                    label = (f"{week[0][0][5:].replace('-', '/')}〜"
                             f"{week[-1][0][5:].replace('-', '/')}")
            except Exception as e:
                print(f"[warn] 週の範囲を求められませんでした: {e}")
        if args.kind == "verdict":
            draw_verdict(d, label)
        else:
            draw_weekly(d, label)
    else:
        try:
            data = json.loads(pathlib.Path(args.games).read_text(encoding="utf-8"))
            games = [g for g in data.get("games", []) if g.get("is_notable")]
        except (json.JSONDecodeError, OSError):
            games = []
        if not games:
            print("[info] 注目試合が無いため、サムネイルは作りません")
            return
        date_label = args.label or (games[0].get("start_time_jst") or "").split(" ")[0]
        draw_daily(d, load_hook(args.narration), games, date_label)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)
    kb = out.stat().st_size / 1024
    print(f"[info] サムネイルを生成しました: {out} ({W}×{H}, {kb:.0f}KB)")
    if kb > 2048:
        print("::warning title=サムネイルが大きすぎる::"
              "YouTubeの上限は2MBです")


if __name__ == "__main__":
    main()
