#!/usr/bin/env python3
"""自チャンネルの公開トップレベルコメントから動画の種を定型ルールで抽出する。

YOUTUBE_API_KEYは既存のearly_views.get経由。OAuth/AIは使わない。
コメント本文・著者情報・コメントIDは保存せず、許可語だけの短い要約を出す。
"""
import argparse
import json
import os
import pathlib
import re
import sys
import unicodedata
from urllib.error import HTTPError
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from early_views import get as youtube_get  # 既存の環境変数による鍵の取り方

OUT = "data/comment_seeds.json"
# backfill_records.CHANNEL_ID と同じ既存の自チャンネル。試験で一致を確認。
CHANNEL_ID = "UCpZ_j8X8uOex5VvKwwTJj3Q"
RULES = (
    ("first", r"初|史上|first|record", "初・歴代記録の確認"),
    ("years", r"何年ぶり|年ぶり|以来|last time", "前回からの年数の確認"),
    ("streak", r"連続|連勝|連敗|streak|consecutive", "連続記録の確認"),
    ("compare", r"どっち|どちら|比較|対戦成績|which|better", "成績・対戦の比較"),
    ("why", r"なぜ|何故|どうして|why", "理由についての疑問"),
    ("correction", r"違[うい]|誤り|訂正|正しく|ではなく|じゃなく|incorrect|actually", "事実関係の指摘"),
    ("question", r"[?？]|ですか|ますか|だろう|なのか|何本|何回|何人|いつ|how many|when", "事実についての疑問"),
)
MATERIALS = (
    ("本塁打", r"本塁打|ホームラン|home runs?|homer", "MLB Stats API /people/{id}/stats (gameLog, hitting)", "安打・本塁打を試合順に集計"),
    ("打点", r"打点|rbi", "MLB Stats API /people/{id}/stats (gameLog, hitting)", "打点を対象期間で合算"),
    ("打率", r"打率|batting average", "MLB Stats API /people/{id}/stats (gameLog, hitting)", "打数・安打から計算し打席の下限も確認"),
    ("安打", r"安打|ヒット|hits?", "MLB Stats API /people/{id}/stats (gameLog, hitting)", "安打を試合順に集計"),
    ("奪三振", r"奪三振|strikeouts?", "MLB Stats API /people/{id}/stats (gameLog, pitching)", "奪三振を対象期間で合算"),
    ("防御率", r"防御率|\bera\b", "MLB Stats API /people/{id}/stats (gameLog, pitching)", "自責点とアウト数から計算し投球回の下限も確認"),
    ("勝敗・優勝", r"優勝|勝利|勝敗|連勝|連敗|何勝|対戦|勝った|負け|champion|wins?", "MLB Stats API /schedule (season, gameType)・/standings", "確定した勝敗・シリーズ結果を集計"),
    ("日程・本拠地", r"日程|本拠地|球場|何時|いつ|schedule|home field", "MLB Stats API /schedule・/venues", "開始日時・ホーム側・球場を確認"),
)


def normalize(text):
    return unicodedata.normalize("NFKC", str(text)).lower()


def entities(text):
    """競技の既知の固有名だけ。自由文・ハンドル・任意の数値は出力に渡さない。"""
    import notability_engine as ne
    allowed = {name: name for name in ne.MLB_TEAM_NAME_JP.values()}
    allowed.update({name: name for name in ne.SOCCER_CLUB_NAME_JP.values()})
    for word, label in ne.MLB_NAME_READINGS.items():
        allowed[word] = label.replace("、", "・")
        allowed[label.replace("、", "・")] = label.replace("、", "・")
    for p in ne.JP_PLAYERS_MLB:
        allowed[p["name_en"]] = p["name_jp"]
        allowed[p["name_jp"]] = p["name_jp"]
    return sorted({label for word, label in allowed.items()
                   if len(word) > 1 and normalize(word) in text})[:4]


def classify(text):
    value = normalize(text)
    triggers = [key for key, pattern, _ in RULES if re.search(pattern, value, re.I)]
    if not triggers:
        return None
    subjects = entities(value)
    matches = [row for row in MATERIALS if re.search(row[1], value, re.I)]
    import notability_engine as ne
    soccer = bool(re.search(r"サッカー|ゴール|勝ち点|プレミア|ラ・?リーガ|soccer|football", value)) or any(
        name in subjects for name in ne.SOCCER_CLUB_NAME_JP.values())
    baseball = bool(re.search(r"野球|mlb|ワールドシリーズ|ポストシーズン|\bws\b|三振", value)) or any(
        name in subjects for name in ne.MLB_TEAM_NAME_JP.values()) or any(
        re.search(row[1], value, re.I) for row in MATERIALS[:6]) or any(
        p["name_jp"] in subjects for p in ne.JP_PLAYERS_MLB)
    sport = "soccer" if soccer and not baseball else "mlb" if baseball and not soccer else "needs_identification"
    labels = [row[0] for row in matches]
    aspects = [label for key, _, label in RULES if key in triggers and key != "question"]
    if not aspects:
        aspects = ["事実についての疑問"]
    summary = "／".join(subjects + labels) or "競技の話題（対象の特定が必要）"
    summary = summary[:70] + "：" + "・".join(aspects[:2])
    sources = [dict(material=row[0], api=row[2], method=row[3]) for row in matches]
    if not sources:
        sources = [dict(material="対象の選手・球団・期間", api="MLB Stats API /people/search・/teams・/schedule",
                        method="動画と照合して対象を特定し、公式成績で検証できる問いにする")]
    if sport == "soccer":
        sources = [dict(material="大会の試合結果・順位", api="football-data.org v4 /competitions/{code}/matches・standings",
                        method="対象大会・期間を特定し、公式試合結果と順位表を確認。個人・歴代記録は大会公式記録も照合")]
    elif sport == "needs_identification":
        sources = [dict(material="競技・対象・期間の特定", api="対象特定後に公式API・大会公式記録を選定",
                        method="元動画と照合して競技を特定し、裏付けに使える一次資料を選ぶ")]
    caveats = ["未検証の候補。対象・期間と元動画の内容を人が照合する"]
    if "first" in triggers or "years" in triggers:
        caveats.append("初・何年ぶりの断定には過去全期間の網羅確認が必要")
    if "streak" in triggers:
        caveats.append("連続の定義、出場しない試合、四球のみの試合の扱いを確認")
    if "why" in triggers:
        caveats.append("成績だけでは原因を断定できない。公式発表・規則・会見などの一次資料が必要")
    return dict(summary=summary, triggers=triggers, subjects=subjects, sport=sport,
                verification=dict(outlook="要一次資料" if "why" in triggers else
                                  "公式データで集計可能な見込み" if matches and sport == "mlb" else
                                  "大会・記録範囲の確認が必要" if sport == "soccer" else "対象特定が必要",
                                  materials=sources, caveats=caveats))


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


API_REASONS = frozenset(("commentsDisabled", "forbidden", "quotaExceeded",
    "dailyLimitExceeded", "invalidParameter", "badRequest", "operationNotSupported",
    "notFound", "videoNotFound", "processingFailure", "accessNotConfigured",
    "keyInvalid", "ipRefererBlocked", "insufficientPermissions", "unsupportedOperation"))
FALLBACK_REASONS = frozenset(("forbidden", "invalidParameter", "badRequest",
    "operationNotSupported", "unsupportedOperation", "insufficientPermissions"))


class FetchError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(json.dumps(reason, ensure_ascii=False))


def failure_reason(exc, call="collect", page=1):
    """例外文字列・URLは使わず、HTTP本文から許可した理由識別子だけを拾う。"""
    if isinstance(exc, FetchError):
        return exc.reason
    kind = type(exc).__name__
    result = dict(call=call, page=page,
                  exception_type=kind if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", kind) else "Exception")
    if isinstance(exc, HTTPError):
        result["http_status"] = exc.code
        reason = "unknown"
        try:
            body = json.loads(exc.read(65536))
            value = body["error"]["errors"][0]["reason"]
            if isinstance(value, str) and value in API_REASONS:
                reason = value
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            pass
        finally:
            exc.close()
        result["api_reason"] = reason
    return result


def recent_video_ids(now, *, paths=None):
    """両台帳の公開日時で直近7日を選ぶ。予定・非公開・日付不明は除外。"""
    paths = paths if paths is not None else [HERE.parent / "data" / name for name in
            ("published_videos.json", "published_assets.json")]
    found = {}

    def visit(node):
        if isinstance(node, dict):
            vid = node.get("video_id")
            published = timestamp(node.get("published_at"))
            if (isinstance(vid, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid)
                    and published and now - timedelta(days=7) <= published <= now
                    and node.get("privacy", "public") == "public"):
                found[vid] = max(found.get(vid, published), published)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    for path in paths:
        visit(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))
    return sorted(found, key=lambda vid: (found[vid], vid), reverse=True)


def public_videos(ids, get, *, details=False):
    """公開状態と自チャンネル所有をvideos.listで二重確認。"""
    valid = {} if details else set()
    ids = sorted(ids)
    for offset in range(0, len(ids), 50):
        page = get("videos", part="snippet,status", id=",".join(ids[offset:offset + 50]), maxResults=50)
        if details and not isinstance(page.get("items"), list):
            raise ValueError("videosの公開確認が欠測")
        for row in page.get("items") or []:
            if ((row.get("snippet") or {}).get("channelId") == CHANNEL_ID
                    and (row.get("status") or {}).get("privacyStatus") == "public"):
                if details:
                    valid[row["id"]] = (row.get("snippet") or {}).get("title", "（題の取得なし）")
                else:
                    valid.add(row["id"])
    return valid


def collect(*, get=youtube_get, now=None, days=7, max_pages=10,
            classifier=None, include_comments=False, max_videos=50, video_pages=2,
            ledger_paths=None):
    """取得と公開確認を共用。本文の保持は訂正通知が明示した場合だけ。"""
    if min(days, max_pages, max_videos, video_pages) < 1:
        raise ValueError("取得上限は正数が必要です")
    classifier = classifier or classify
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    payload = dict(updated_at=now.isoformat(), source="YouTube Data API commentThreads・videos",
                   status="ok", scope=dict(days=days, since=cutoff.isoformat(), until=now.isoformat(),
                   comments="公開動画の公開トップレベルコメント（返信は対象外）", max_pages=max_pages,
                   max_videos=max_videos, video_pages=video_pages, mode="channel", fallback_video_days=7),
                   coverage=dict(pages=0, scanned=0, complete=True), seeds=[])
    candidates, seen = [], set()
    raw_get = get
    calls = {}
    def get(method, **params):
        calls[method] = calls.get(method, 0) + 1
        try:
            response = raw_get(method, **params)
            if not isinstance(response, dict) or not isinstance(response.get("items"), list):
                raise ValueError("一覧が欠測")
            return response
        except Exception as exc:
            raise FetchError(failure_reason(exc, method, calls[method])) from None

    def pages(video_id=None):
        token, tokens = None, set()
        limit = video_pages if video_id else max_pages
        for page_number in range(1, limit + 1):
            params = dict(part="snippet", textFormat="plainText", order="time", maxResults=100)
            if video_id:
                params["videoId"] = video_id
            else:
                params["allThreadsRelatedToChannelId"] = CHANNEL_ID
            if token:
                params["pageToken"] = token
            try:
                page = get("commentThreads", **params)
                if not isinstance(page.get("items"), list):
                    raise ValueError("一覧が欠測")
            except Exception as exc:
                reason = dict(failure_reason(exc, "commentThreads", page_number), page=page_number)
                if video_id:
                    reason["video_id"] = video_id
                raise FetchError(reason) from None
            payload["coverage"]["pages"] += 1
            yield page
            token = page.get("nextPageToken")
            if not token:
                return
            if token in tokens:
                payload["coverage"]["complete"] = False
                return
            tokens.add(token)
        if token:
            payload["coverage"]["complete"] = False

    def scan(video_id=None):
        for page in pages(video_id):
            older = False
            for thread in page.get("items") or []:
                sn = thread.get("snippet") or {}
                top = sn.get("topLevelComment") or {}
                item = top.get("snippet") or {}
                payload["coverage"]["scanned"] += 1
                published = timestamp(item.get("publishedAt"))
                if not published:
                    payload["coverage"]["complete"] = False
                    continue
                if published < cutoff:
                    older = True
                    continue
                if published > now or sn.get("isPublic") is not True or sn.get("channelId") != CHANNEL_ID:
                    continue
                vid, cid = sn.get("videoId"), top.get("id")
                if video_id and vid != video_id:
                    continue
                if not vid or not cid or cid in seen or item.get("channelId") != CHANNEL_ID:
                    continue
                seen.add(cid)
                seed = classifier(item.get("textOriginal") or item.get("textDisplay") or "")
                if seed:
                    candidates.append((vid, seed))
            if older:
                break

    try:
        scan()
    except FetchError as exc:
        reason = exc.reason
        if (reason.get("http_status") not in (400, 403, 410)
                or reason.get("api_reason") not in FALLBACK_REASONS):
            raise
        payload["reason"] = reason
        candidates.clear()
        seen.clear()
        payload["scope"]["mode"] = "videoId"
        payload["coverage"]["complete"] = False  # 古い動画への新着コメントは代替対象外
        ids = recent_video_ids(now, paths=ledger_paths)
        payload["coverage"].update(videos_available=len(ids), videos_selected=min(len(ids), max_videos),
                                  skipped=[])
        valid_ids = public_videos(ids[:max_videos], get)
        for vid in ids[:max_videos]:
            if vid not in valid_ids:
                continue
            try:
                scan(vid)
            except FetchError as video_exc:
                if video_exc.reason.get("api_reason") != "commentsDisabled":
                    raise
                payload["coverage"]["skipped"].append(video_exc.reason)
    payload["coverage"]["api_calls"] = calls
    valid = public_videos({vid for vid, _ in candidates}, get, details=include_comments)
    if include_comments:
        payload["seeds"] = [dict(seed, source_video_id=vid, source_video_title=valid[vid])
                            for vid, seed in candidates if vid in valid]
        return payload
    # 同じ定型要約はまとめて件数化。個々のコメントへの逆引き情報を出さない。
    groups = {}
    for vid, seed in candidates:
        if vid not in valid:
            continue
        key = (vid, json.dumps(seed, ensure_ascii=False, sort_keys=True))
        if key not in groups:
            groups[key] = dict(seed, source_video_id=vid,
                               source_url=f"https://www.youtube.com/watch?v={vid}", comment_count=0)
        groups[key]["comment_count"] += 1
    payload["seeds"] = sorted(groups.values(), key=lambda s: (-s["comment_count"], s["summary"]))
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/comment_seeds.json")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--max-videos", type=int, default=50)
    ap.add_argument("--video-pages", type=int, default=2)
    args = ap.parse_args()
    if min(args.days, args.max_pages, args.max_videos, args.video_pages) < 1:
        ap.error("取得日数・動画数・ページ数は正数が必要です")
    # 引数処理が先なので --help は鍵の参照も通信もしない。
    if os.environ.get("COLLESPO_COMMENT_SEEDS", "off") != "on":
        print("[info] コメント候補は既定オフです")
        return 0
    now = datetime.now(timezone.utc)
    if not os.environ.get("YOUTUBE_API_KEY"):
        payload = dict(updated_at=now.isoformat(), status="missing_key", seeds=[])
        code = 1
    else:
        try:
            payload = collect(now=now, days=args.days, max_pages=args.max_pages,
                              max_videos=args.max_videos, video_pages=args.video_pages)
            code = 0
        except Exception as exc:
            payload = dict(updated_at=now.isoformat(), status="fetch_failed", seeds=[],
                           reason=failure_reason(exc))
            code = 1
    dest = pathlib.Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[info] コメント候補 {payload['status']}: {len(payload['seeds'])}件")
    if "reason" in payload:
        print("[info] reason: " + json.dumps(payload["reason"], ensure_ascii=False))
    for skipped in payload.get("coverage", {}).get("skipped", []):
        print("[info] skipped: " + json.dumps(skipped, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
