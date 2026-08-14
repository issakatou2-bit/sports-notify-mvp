"""
TikTok投稿の組み立てを、通信を差し替えて検証する。
実アカウントが無くても、分割の計算・公開範囲の選び方・
下書きと直接投稿の切り替えは確かめられる。
"""
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")
import post_tiktok as pt

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'NG '} {label}: {got}" + ("" if ok else f" (期待 {want})"))


# --- 分割の計算 -------------------------------------------------------------
print("--- chunks ---")
check("1MB(ショート想定)", pt.chunks(1_000_000), (1_000_000, 1))
check("4.9MB(境界の下)", pt.chunks(5 * 1024 * 1024 - 1), (5 * 1024 * 1024 - 1, 1))
c, n = pt.chunks(5 * 1024 * 1024)
print(f"ok  5MBちょうど: chunk={c:,} count={n}")
assert n >= 1 and c <= pt.MAX_CHUNK
c, n = pt.chunks(200 * 1024 * 1024)
print(f"ok  200MB: chunk={c:,} count={n}")
assert c <= pt.MAX_CHUNK, "1塊が上限を超えている"
assert c >= pt.MIN_CHUNK, "1塊が下限を下回っている"
# 分割しても全部のバイトが送られるか(最後が端数を飲む前提)
size = 200 * 1024 * 1024
covered = 0
for i in range(n):
    start = i * c
    end = size - 1 if i == n - 1 else start + c - 1
    covered += end - start + 1
check("200MBを過不足なく送れる", covered, size)

# --- 公開範囲の選択 ---------------------------------------------------------
print("\n--- pick_privacy ---")
check("審査前(SELF_ONLYのみ)",
      pt.pick_privacy({"privacy_level_options": ["SELF_ONLY"]}, None), "SELF_ONLY")
check("審査後(全部使える)",
      pt.pick_privacy({"privacy_level_options":
                       ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}, None),
      "PUBLIC_TO_EVERYONE")
check("指定が使える場合はそれを使う",
      pt.pick_privacy({"privacy_level_options":
                       ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}, "SELF_ONLY"),
      "SELF_ONLY")
check("指定が使えない場合は勝手に公開しない",
      pt.pick_privacy({"privacy_level_options": ["SELF_ONLY"]},
                      "PUBLIC_TO_EVERYONE"),
      "SELF_ONLY")
check("情報が取れないときは最も安全側",
      pt.pick_privacy({}, "PUBLIC_TO_EVERYONE"), "SELF_ONLY")

# --- init の組み立て --------------------------------------------------------
print("\n--- init_upload の中身 ---")
sent = {}


def fake_post(url, token, payload):
    sent["url"] = url
    sent["payload"] = payload
    return {"publish_id": "p1", "upload_url": "https://upload.example/x"}


pt._post = fake_post
tmp = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".") / "dummy.mp4"
tmp.write_bytes(b"0" * 1_000_000)

pt.init_upload("tok", tmp, "テスト投稿", "SELF_ONLY", direct=False, info={})
check("下書きは inbox へ", sent["url"].endswith("/inbox/video/init/"), True)
check("下書きに post_info を送らない", "post_info" in sent["payload"], False)

pt.init_upload("tok", tmp, "テスト投稿", "PUBLIC_TO_EVERYONE", direct=True,
               info={"comment_disabled": True})
check("直接投稿は video/init へ", sent["url"].endswith("/post/publish/video/init/"), True)
pi = sent["payload"]["post_info"]
check("公開範囲が入る", pi["privacy_level"], "PUBLIC_TO_EVERYONE")
check("コメント不可の設定を尊重", pi["disable_comment"], True)
check("タイアップ表示は立てない",
      (pi["brand_content_toggle"], pi["brand_organic_toggle"]), (False, False))
si = sent["payload"]["source_info"]
check("サイズが実ファイルと一致", si["video_size"], 1_000_000)
check("FILE_UPLOAD を指定", si["source"], "FILE_UPLOAD")

# タイトルの上限
long_title = "あ" * 3000
pt.init_upload("tok", tmp, long_title, "SELF_ONLY", direct=True, info={})
check("タイトルは2200で切る",
      len(sent["payload"]["post_info"]["title"]), 2200)

# --- エラー応答の扱い -------------------------------------------------------
print("\n--- エラー応答 ---")


class R:
    def __init__(self, code, body):
        self.status_code = code
        self._b = body
        self.text = json.dumps(body)

    def json(self):
        return self._b


try:
    pt._check(R(200, {"error": {"code": "ok"}, "data": {"x": 1}}), "u")
    print("ok  code=ok は成功として扱う")
except RuntimeError as e:
    fails += 1
    print(f"NG  code=ok を失敗にしている: {e}")

try:
    pt._check(R(200, {"error": {"code": "spam_risk_too_many_posts",
                                "message": "too many"}}), "u")
    fails += 1
    print("NG  HTTP200のエラーを見逃した")
except RuntimeError as e:
    print(f"ok  HTTP200でもエラーを拾う: {e}")

# --- 題材の判定 -------------------------------------------------------------
# MLBのタイトルには「ア・リーグ」「ナ・リーグ」「インターリーグ」が出る。
# 「リーグ」で部分一致させると、これらがサッカー扱いになる。
print("\n--- caption の題材判定 ---")
TOPIC_CASES = [
    ("ア・リーグ東地区の首位攻防｜ヤンキース vs レッドソックス ほか #Shorts", False),
    ("ナ・リーグ西地区 ドジャースが首位をキープ #Shorts", False),
    ("インターリーグ対決｜08/12の注目試合【MLB】#Shorts", False),
    ("大谷翔平が2試合連続本塁打 #Shorts", False),
    ("千賀滉大・松井裕樹 ほか｜8月10日 MLB日本人選手の成績まとめ #Shorts", False),
    ("【サッカー】欧州5大リーグ、何が違う？｜プレミア・ラリーガ・セリエA #Shorts", True),
    ("【サッカー】欧州でプレーする日本人選手まとめ｜所属クラブ一覧 #Shorts", True),
    ("【サッカー】xG って何の数字？｜期待ゴール・ポゼッションの見方 #Shorts", True),
    ("プレミアリーグ開幕｜リバプール対アーセナル", True),
    ("リーグ・アンの注目カード", True),
]
for title, want_soccer in TOPIC_CASES:
    c = pt.caption(title)
    got = "#サッカー" in c
    check(("サッカー" if want_soccer else "MLB   ") + " " + title[:34], got, want_soccer)
    if "#Shorts" in c:
        fails += 1
        print("NG  #Shorts が残っている")

# --- creator_info を呼ぶ条件 ------------------------------------------------
# creator_info は直接投稿のためのAPIで video.publish が要る。
# 下書きしか許されていない審査前に呼ぶと scope_not_authorized で落ち、
# その間の自動投稿が毎日すべて失敗する。実際にそうなった。
print("\n--- creator_info を呼ぶ条件 ---")
called = []
pt.creator_info = lambda token: (called.append(token),
                                 {"privacy_level_options": ["SELF_ONLY"],
                                  "creator_nickname": "テスト"})[1]
pt.upload_file = lambda url, video: None
pt.wait_status = lambda token, pid, tries=12: {"status": "SEND_TO_USER_INBOX"}
pt._post = fake_post

rec = tmp.parent / "rec.json"
argv = sys.argv

# 通信は差し替えてあるので中身は使われない。存在確認だけを満たす。
for name in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"):
    os.environ[name] = "test"


def run_main(scope):
    pt.refresh_token = lambda k, s, r: {"access_token": "t", "scope": scope}
    called.clear()
    sys.argv = ["post_tiktok.py", "--video", str(tmp), "--title", "確認",
                "--record", str(rec)]
    try:
        return pt.main()
    finally:
        sys.argv = argv


tmp.write_bytes(b"0" * 1000)
check("下書きのみ: 正常終了する", run_main("user.info.basic,video.upload"), 0)
check("下書きのみ: creator_info を呼ばない", called, [])
check("審査後: creator_info を呼ぶ",
      (run_main("user.info.basic,video.upload,video.publish"), called) == (0, ["t"]),
      True)

saved = json.loads(rec.read_text(encoding="utf-8"))["daily"]
check("記録に投稿方法が残る",
      [v["direct"] for v in saved.values()], [True])
rec.unlink()

tmp.unlink()
print("\nALL OK" if not fails else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
