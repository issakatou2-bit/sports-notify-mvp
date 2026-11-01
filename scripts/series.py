#!/usr/bin/env python3
"""
日本人選手ごとのシリーズ（再生リスト・題名の頭・説明欄の先頭）の下書き。

作業153・指示書 Opus-22。本番のコードは変えない。取り込むときは
scripts/ に置き、upload_youtube.py の2か所から呼ぶ（README の「変える所」）。

やること:
  1. 公開の記録（data/published_videos.json）の題から、その回の主役の
     日本人選手を決める（main_players）。
  2. 主役ごとに再生リスト「〇〇の今日」へ入れる（--sync。YouTube API を使う。
     作りは scripts/playlists.py に合わせた。この作業では実行していない）。
  3. 題名の頭を「【MLB】〇〇の今日｜…」にそろえる案（series_title）。
  4. 説明欄の先頭に「この選手の回の一覧」へのリンクを置く案（description_head）。

使い方（コレスポのリポジトリの一番上で）:
  python3 scripts/series.py --dry-run          # 振り分けを見るだけ
  python3 scripts/series.py --report out.md    # 見本の表を書く
  python3 scripts/series.py --sync             # 再生リストへ入れる（要 youtube 権限）
"""

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent

VIDEOS_PATH = "data/published_videos.json"
STORE = "data/player_playlists.json"
TITLE_MAX = 100          # YouTube の題の上限
SERIES_SUFFIX = "の今日"

# 主役を決めない区分。成績のランキングと週のまとめは、名前が3人並んでも
# 「その選手の回」ではない（上位の人を並べているだけ）。
RANKING_KINDS = {"morning", "weekly", "verdict"}
# 10/10 エマ（本人の「今日」の決定に合わせて）: 19:00 予告（daily）は「あすの試合」の回なので「〇〇の今日」と
# 言えない。18:00 報道（morning_press）は見出しに大谷翔平が入る日が多く、その人のリストが報道で埋まる
# （10/7 の写しで50本中41本）。どちらもシリーズに入れない。
NO_SERIES_KINDS = {"daily", "morning_press"}
# MLB の区分だけ扱う。サッカーの選手は名簿が別（JP_PLAYERS_SOCCER）なので次の段階。
MLB_KINDS = {"morning", "morning_local", "morning_press", "morning_player",
             "morning_voices", "morning_postseason", "daily", "longform",
             "weekly", "verdict"}
# 主役にする名前の数の上限。長編は「村上宗隆・松井裕樹の今日」のように2人まで。
MAX_MAIN = 2

# 日付に縛られない回（今日の1人＝選手の紹介）。「の今日」は付けず、元の題のまま。
# 再生リストには入れる。
EVERGREEN_KINDS = {"morning_player"}

# 題に残す語（検索に効く）。縮めるときも、これを含む区切りは最後まで残す。
KEEP_WORDS = ("地区シリーズ", "ワイルドカード", "WCS", "リーグ優勝決定シリーズ",
              "ワールドシリーズ", "ポストシーズン", "PS")

PLAYER_SLUGS_URL = "https://collespo.com/players/{slug}.html"


# ---------------------------------------------------------------- 名簿

def _find_engine():
    """notability_engine.py を探す（コレスポのリポジトリでも、この写しでも動くように）。"""
    for base in (pathlib.Path.cwd(), HERE.parent / "src", HERE.parent.parent):
        if (base / "notability_engine.py").exists():
            return base
    return None


def load_roster() -> list:
    """日本人選手（MLB）の名前の一覧。notability_engine.JP_PLAYERS_MLB から引く。"""
    base = _find_engine()
    if base is None:
        raise RuntimeError("notability_engine.py が見つかりません")
    sys.path.insert(0, str(base))
    import notability_engine as ne  # noqa: E402
    return [p["name_jp"] for p in ne.JP_PLAYERS_MLB]


def load_slugs() -> dict:
    """選手ページの URL の名前（scripts/generate_player_pages.py の PLAYER_SLUGS）。"""
    base = _find_engine()
    if base is None:
        return {}
    path = base / "scripts" / "generate_player_pages.py"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    m = re.search(r"PLAYER_SLUGS = \{(.*?)\n\}", text, re.S)
    if not m:
        return {}
    return dict(re.findall(r'"([^"]+)": "([^"]+)"', m.group(1)))


# ---------------------------------------------------------------- 主役を決める

_BADGE = re.compile(r"^【[^】]*】")


def head_of(title: str) -> str:
    """題の頭（先頭の【…】を除き、最初の「｜」より前）。"""
    t = _BADGE.sub("", title.strip())
    return t.split("｜", 1)[0]


def names_in(text: str, roster: list) -> list:
    """text に出てくる選手名を、出てくる順に返す。"""
    found = []
    for name in roster:
        i = text.find(name)
        if i >= 0:
            found.append((i, name))
    return [n for _, n in sorted(found)]


def main_players(title: str, kind: str, roster: list) -> list:
    """その回の主役の日本人選手（0〜2人）。

    決まり:
      - MLB の区分だけ。ランキング（17:00 成績）と週のまとめは主役なし。
      - 題の頭（最初の「｜」より前）に出てくる名前だけを数える。
        後ろの区切りにだけ出る名前は「ついでに出た人」とみなす。
      - 頭に3人以上いる回は、だれの回でもないので主役なし。
    """
    if kind not in MLB_KINDS or kind in RANKING_KINDS or kind in NO_SERIES_KINDS:
        return []
    names = names_in(head_of(title), roster)
    return names if 0 < len(names) <= MAX_MAIN else []


def assign(videos: dict, roster: list) -> dict:
    """{選手名: [{video_id, title, kind, day, published_at}, ...]}（古い順）。"""
    out = {}
    for kind, entries in videos.items():
        if not isinstance(entries, dict):
            continue
        for day, e in entries.items():
            if not isinstance(e, dict) or not e.get("video_id"):
                continue
            for name in main_players(e.get("title", ""), kind, roster):
                out.setdefault(name, []).append({
                    "video_id": e["video_id"], "title": e.get("title", ""),
                    "kind": kind, "day": day,
                    "published_at": e.get("published_at", "")})
    for items in out.values():
        items.sort(key=lambda x: (x["published_at"] or x["day"]))
    return out


# ---------------------------------------------------------------- 題名の頭

_UPDATED = re.compile(r"^【(\d{1,2}/\d{1,2})更新】")
# 名前のすぐ後ろの、つなぎの言葉。頭から名前を抜いたあとに残さない。
_JOINERS = ("が所属する", "の", "、", " ", "")


def _strip_names(head: str, names: list) -> str:
    """頭から主役の名前と、そのつなぎを抜く。引用（「…」）の中は触らない。"""
    if "「" in head:
        return head
    out = head
    for n in names:
        for j in _JOINERS:
            out = out.replace(n + j, "")
    out = re.sub(r"\s+、", "、", out).strip("・、 　")
    # 長編はもともと「〇〇の今日｜…」。名前を抜くと「今日」だけ残る。
    return "" if out in ("きょう", "今日", "のきょう", SERIES_SUFFIX) else out


def _fit(segments: list, tail: str, limit: int) -> str:
    """区切りをつないで limit 字以内にする。検索に効く語の無い区切りから縮める。"""
    def join(segs):
        return "｜".join(s for s in segs if s) + tail
    segs = list(segments)
    # 先頭（シリーズの頭）は縮めない。後ろから、KEEP_WORDS を含まない区切りを削る。
    for i in range(len(segs) - 1, 0, -1):
        if len(join(segs)) <= limit:
            break
        if not any(w in segs[i] for w in KEEP_WORDS):
            segs[i] = ""
    t = join(segs)
    if len(t) > limit:
        # それでも長いときは、いちばん長い区切りの末尾を「…」で切る。
        k = max(range(1, len(segs)), key=lambda i: len(segs[i]), default=0)
        over = len(t) - limit
        if k and len(segs[k]) > over + 1:
            segs[k] = segs[k][:len(segs[k]) - over - 1] + "…"
        t = join(segs)[:limit]
    return t


def series_title(title: str, names: list, kind: str = "",
                 badge: str = "【MLB】", limit: int = TITLE_MAX) -> str:
    """題名の頭を「【MLB】〇〇の今日｜…」にそろえる。

    - 主役がいない回と、日付に縛られない回（EVERGREEN_KINDS）は、元の題のまま返す。
    - 「【10/5更新】」は後ろへ回す（「10/5更新」）。日付は説明欄にもある。
    - 「#Shorts」は最後に残す。
    - 検索に効く語（地区シリーズ・PS など）とチーム名は残す。チーム名は
      頭の残り（例「ホワイトソックス対ガーディアンズの地区シリーズ第2戦」）に入っている。
    """
    if not names or kind in EVERGREEN_KINDS:
        return title
    t = title.strip()
    updated = ""
    m = _UPDATED.match(t)
    if m:
        updated = f"{m.group(1)}更新"
        t = t[m.end():]
    t = _BADGE.sub("", t)
    tail = ""
    if t.endswith("#Shorts"):
        tail = " #Shorts"
        t = t[: -len("#Shorts")].rstrip()
    parts = t.split("｜")
    rest_head = _strip_names(parts[0], names)
    rest = [rest_head] + parts[1:]
    # 古い回の「…｜9/26の注目試合【MLB】」のような後ろの札は、頭へ移したので消す。
    rest = [r.replace(badge, "").strip() for r in rest]
    rest = [r for r in rest if r]
    if updated:
        rest.append(updated)
    head = badge + "・".join(names) + SERIES_SUFFIX
    return _fit([head] + rest, tail, limit)


# ---------------------------------------------------------------- 説明欄の先頭

def playlist_url(pid: str) -> str:
    return f"https://www.youtube.com/playlist?list={pid}"


def description_head(names: list, store: dict, slugs: dict) -> list:
    """説明欄の先頭に置く行。再生リストが無ければ、選手ページへのリンク。"""
    lines = []
    for n in names:
        pid = (store.get(n) or {}).get("id")
        if pid:
            lines.append(f"▶ {n}の回の一覧：{playlist_url(pid)}")
        elif n in slugs:
            lines.append(f"▶ {n}のページ：{PLAYER_SLUGS_URL.format(slug=slugs[n])}")
    return lines + [""] if lines else []


# ---------------------------------------------------------------- 再生リスト（YouTube API）

def playlist_meta(name: str) -> tuple:
    title = f"{name}{SERIES_SUFFIX}｜MLB"
    desc = (f"{name}が主役の回だけを集めた再生リストです。"
            "その日の成績・ポストシーズン・現地の報道とファンの声を、"
            "公開した順に追加しています。試合情報：https://collespo.com/")
    return title, desc


def load_store(path: str = STORE) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_store(data: dict, path: str = STORE) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_playlist(yt, store: dict, name: str) -> str:
    """その選手の再生リストID。無ければ作る（playlists.ensure_playlist と同じ形）。"""
    if store.get(name, {}).get("id"):
        return store[name]["id"]
    title, desc = playlist_meta(name)
    res = yt.playlists().insert(
        part="snippet,status",
        body={"snippet": {"title": title, "description": desc,
                          "defaultLanguage": "ja"},
              "status": {"privacyStatus": "public"}}).execute()
    store[name] = {"id": res["id"], "title": title, "videos": []}
    print(f"[info] 再生リストを作りました: {title} ({res['id']})")
    return res["id"]


def add_video(yt, store: dict, name: str, video_id: str) -> bool:
    from googleapiclient.errors import HttpError
    pid = ensure_playlist(yt, store, name)
    if video_id in store[name].get("videos", []):
        return False
    try:
        yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": pid,
                              "resourceId": {"kind": "youtube#video",
                                             "videoId": video_id}}}).execute()
    except HttpError as e:
        print(f"[warn] {video_id} を追加できませんでした: {e}")
        return False
    store[name].setdefault("videos", []).append(video_id)
    return True


def sync(assigned: dict, store: dict) -> int:
    """振り分けた回を再生リストへ入れる。認証は scripts/playlists.py の client() を使う。"""
    scripts = (_find_engine() or pathlib.Path.cwd()) / "scripts"
    sys.path.insert(0, str(scripts))
    import playlists  # noqa: E402  google のライブラリが無ければここで終わる
    yt = playlists.client()
    if yt is None:
        return 0
    added = 0
    for name, items in assigned.items():
        for it in items:
            if add_video(yt, store, name, it["video_id"]):
                added += 1
                print(f"  {name} {it['day']} -> {it['video_id']}")
    print(f"[info] {added}本を追加しました")
    return added


# ---------------------------------------------------------------- 見本の表

def report(assigned: dict, videos: dict, roster: list) -> str:
    total = sum(len(e) for k, e in videos.items()
                if isinstance(e, dict) and k in MLB_KINDS)
    used = {it["video_id"] for items in assigned.values() for it in items}
    out = ["# 選手ごとの振り分けの見本", "",
           f"MLB の区分の回 {total}本のうち、主役が決まった回 {len(used)}本。", "",
           "| 選手 | 本数 | 区分の内訳 | いちばん新しい回 |", "|---|---|---|---|"]
    for name in roster:
        items = assigned.get(name) or []
        if not items:
            continue
        kinds = {}
        for it in items:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        k = "・".join(f"{a} {b}" for a, b in sorted(kinds.items(), key=lambda x: -x[1]))
        out.append(f"| {name} | {len(items)} | {k} | {items[-1]['day']} |")
    none = [n for n in roster if n not in assigned]
    if none:
        out += ["", "主役の回が無い選手：" + "・".join(none)]
    out += ["", "## 題名の頭をそろえた例（各選手の新しい回から）", "",
            "| いまの題 | 案 | 字数 |", "|---|---|---|"]
    seen = set()
    for name in roster:
        for it in reversed(assigned.get(name) or []):
            if it["video_id"] in seen:
                continue
            seen.add(it["video_id"])
            names = main_players(it["title"], it["kind"], roster)
            new = series_title(it["title"], names, it["kind"])
            out.append(f"| {it['title']} | {new} | {len(new)} |")
            break
    # 区分ごとにも1本ずつ（上で出ていない区分）
    shown = {it["kind"] for items in assigned.values() for it in items
             if it["video_id"] in seen}
    for name in roster:
        for it in reversed(assigned.get(name) or []):
            if it["kind"] in shown:
                continue
            shown.add(it["kind"])
            new = series_title(it["title"], main_players(it["title"], it["kind"], roster),
                               it["kind"])
            out.append(f"| {it['title']} | {new} | {len(new)} |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="data フォルダ")
    ap.add_argument("--dry-run", action="store_true", help="振り分けを出すだけ")
    ap.add_argument("--report", help="見本の表を Markdown で書く")
    ap.add_argument("--sync", action="store_true", help="再生リストへ入れる")
    args = ap.parse_args()

    roster = load_roster()
    videos = json.loads((pathlib.Path(args.data) / "published_videos.json")
                        .read_text(encoding="utf-8"))
    assigned = assign(videos, roster)
    if args.report:
        pathlib.Path(args.report).write_text(report(assigned, videos, roster),
                                             encoding="utf-8")
        print(f"[info] {args.report} を書きました")
    if args.dry_run or not (args.sync or args.report):
        for name in roster:
            for it in assigned.get(name) or []:
                print(f"  {name:<8} {it['kind']:<18} {it['day']} {it['title'][:50]}")
    if args.sync:
        store_path = str(pathlib.Path(args.data) / "player_playlists.json")
        store = load_store(store_path)
        sync(assigned, store)
        save_store(store, store_path)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
