#!/usr/bin/env python3
"""RSSが取れない日に、材料が空にならないか。

なぜ要るのか:
  9/19から毎日、GitHubの実行環境だけYouTubeのRSSが404を返している
  （同じURLが手元からは200）。「現地の声」「現地の報道」の材料を集める
  5〜6チャンネルが毎回すべて落ちていた。RSSが落ちたときだけ、API の
  アップロード一覧（1回1ユニット）で取り直す。

通信は作り物に差し替える。本物のYouTubeには触らない。
"""

import pathlib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import channel_feeds as cf  # noqa: E402
from checks_report import check, section, done  # noqa: E402

NOW = datetime.now(timezone.utc)
FRESH = (NOW - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
OLD = (NOW - timedelta(days=5)).isoformat().replace("+00:00", "Z")
calls = []


class Resp:
    def __init__(self, body):
        self._b = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._b


def fake_get(url, params=None, timeout=None):
    calls.append(params)
    return Resp({"items": [
        {"snippet": {"title": "Game Highlights: MIL vs BAL",
                     "resourceId": {"videoId": "NEW1"}, "publishedAt": FRESH},
         "contentDetails": {"videoId": "NEW1", "videoPublishedAt": FRESH}},
        {"snippet": {"title": "old one",
                     "resourceId": {"videoId": "OLD1"}, "publishedAt": OLD},
         "contentDetails": {"videoId": "OLD1", "videoPublishedAt": OLD}},
    ]})


def rss_404(*a, **k):
    raise urllib.error.HTTPError("u", 404, "Not Found", None, None)


cf.requests.get = fake_get
urllib.request.urlopen = rss_404

section("RSSが404の日")
check("鍵が無ければ取り直さない", cf.fetch_feed("UCabc", 24), [])
check("鍵が無ければAPIを呼ばない", calls, [])
got = cf.fetch_feed("UCabc", 24, "KEY")
check("鍵があればアップロード一覧で取り直す", [v["video_id"] for v in got], ["NEW1"])
check("アップロード一覧はUCをUUに替えたID", calls[-1]["playlistId"], "UUabc")
check("RSSと同じ形で返す", sorted(got[0]), ["published_at", "title", "video_id"])
check("見る時間の外は捨てる", "OLD1" in [v["video_id"] for v in got], False)

section("取り直せない形")
check("UCで始まらないIDは引かない", cf.fetch_uploads("KEY", "xyz", 24), [])


def broken_get(*a, **k):
    raise RuntimeError("quota")


cf.requests.get = broken_get
check("APIも落ちたら空で返す（止めない）", cf.fetch_feed("UCabc", 24, "KEY"), [])

sys.exit(done())
