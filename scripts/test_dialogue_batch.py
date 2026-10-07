#!/usr/bin/env python3
"""台本の Batch 化（dialogue_batch.py・dialogue_batch.patch・estimate.py）の検査。

**通信しない・APIキーは要らない。**
  - Anthropic の client は偽物（FakeClient）。Batch の返事は fixtures/ の
    **手で作った見本**（形は公式の説明と anthropic 1.11.0 の型に合わせた）。
  - 時計も偽物（FakeClock）。眠らずに 15:10〜17:30 を進める。
  - patch の検査は、collespo/src の写しを一時フォルダへ写し、そこに patch を当てて動かす
    （src/ そのものは書き換えない）。

動かし方（リポジトリの一番上で）:
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider collespo/batch/test_dialogue_batch.py
"""
import contextlib
import copy
import io
import json
import pathlib
import shutil
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures/dialogue_batch"
sys.path.insert(0, str(HERE))

import dialogue_batch as db  # noqa: E402

JST = timezone(timedelta(hours=9))
START = datetime(2026, 10, 7, 15, 10, tzinfo=JST)
# 本番と同じ「GitHub Actions の、時刻で動いた回」
GHA = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "schedule"}
KW = {"max_tokens": 16000, "messages": [{"role": "user", "content": "材料と頼み方"}]}


# ---------------------------------------------------------------------------
# 偽物
# ---------------------------------------------------------------------------
def ns(o):
    """JSON を、SDK の返事と同じく属性で読める形にする。"""
    if isinstance(o, dict):
        return types.SimpleNamespace(**{k: ns(v) for k, v in o.items()})
    if isinstance(o, list):
        return [ns(v) for v in o]
    return o


def fixture_rows(name, cid):
    """fixtures の結果（JSONL）を読み、見本の custom_id を、出した依頼のものに差し替える。"""
    rows = []
    for line in (FIX / name).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["custom_id"].startswith("dlg-draft-"):
            r["custom_id"] = cid
        rows.append(ns(r))
    return rows


def message(name):
    """fixtures の succeeded の返事（Message の形）を1つ。"""
    for line in (FIX / name).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["custom_id"].startswith("dlg-draft-"):
            return ns(r["result"]["message"])
    raise KeyError(name)


class FakeClock:
    def __init__(self, t=START):
        self.t = t
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        assert s > 0
        self.slept.append(s)
        self.t += timedelta(seconds=s)


class FakeBatches:
    """plans: 出すたびに1つ使う。{"minutes": 返るまでの分, "result": fixture 名,
    "on_cancel": 取り消したときの fixture 名（None なら取り消し後も終わらない）}"""

    def __init__(self, clock, plans, fail_create=False, fail_retrieve=0, existing=None):
        self.clock, self.plans = clock, list(plans)
        self.created, self.canceled, self.retrieved = [], [], 0
        self.fail_create, self.fail_retrieve = fail_create, fail_retrieve
        self.batches = dict(existing or {})

    def create(self, requests):
        if self.fail_create:
            raise RuntimeError("偽物: 出せない")
        reqs = list(requests)
        assert len(reqs) == 1
        self.created.append(copy.deepcopy(reqs))
        plan = self.plans.pop(0)
        bid = f"msgbatch_fake_{len(self.created)}"
        self.batches[bid] = {"cid": reqs[0]["custom_id"], "ready": self.clock.now()
                             + timedelta(minutes=plan["minutes"]), **plan}
        return ns({"id": bid, "type": "message_batch", "processing_status": "in_progress"})

    def _status(self, b):
        if b.get("canceled_at") is not None:
            return "ended" if b.get("on_cancel") else "canceling"
        return "ended" if self.clock.now() >= b["ready"] else "in_progress"

    def retrieve(self, bid):
        self.retrieved += 1
        if self.fail_retrieve:
            self.fail_retrieve -= 1
            raise RuntimeError("偽物: 様子が見られない")
        return ns({"id": bid, "processing_status": self._status(self.batches[bid])})

    def results(self, bid):
        b = self.batches[bid]
        assert self._status(b) == "ended", "終わる前に結果を読んだ"
        name = b["on_cancel"] if b.get("canceled_at") is not None else b["result"]
        return iter(fixture_rows(name, b["cid"]))

    def cancel(self, bid):
        self.canceled.append(bid)
        self.batches[bid]["canceled_at"] = self.clock.now()
        return ns({"id": bid, "processing_status": "canceling"})


class FakeClient:
    def __init__(self, clock, plans=(), **kw):
        self.messages = types.SimpleNamespace(batches=FakeBatches(clock, plans, **kw))


class Calls:
    """direct（いまの呼び方）と record（費用の記録）の呼ばれ方を控える。"""

    def __init__(self, direct_msg="result_succeeded_long.jsonl"):
        self.direct_n, self.records, self.direct_msg = 0, [], direct_msg

    def direct(self):
        self.direct_n += 1
        return message(self.direct_msg)

    def record(self, resp, batch):
        self.records.append((resp.id, batch))


def go(tmp_path, client, clock, calls=None, stage="draft", kw=KW, env=None, **extra):
    calls = calls or Calls()
    resp = db.run(client, stage, kw, model="claude-sonnet-5-5", effort="medium",
                  direct=calls.direct, record=calls.record, now=clock.now, sleep=clock.sleep,
                  state_path=str(tmp_path / "state.json"), deadline="17:30",
                  env=env if env is not None else dict(GHA), log=lambda *a: None, **extra)
    return resp, calls


def state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 依頼の形
# ---------------------------------------------------------------------------
def test_params_are_the_same_as_create():
    p = db.params_of(KW, "claude-sonnet-5-5", "medium")
    assert p == {"model": "claude-sonnet-5-5", "max_tokens": 16000,
                 "messages": KW["messages"], "output_config": {"effort": "medium"}}
    # 公式: batch に入れられない引数（stream・speed・max_tokens 0）を入れない
    assert "stream" not in p and "speed" not in p and p["max_tokens"] >= 1
    # 渡した kw は書き換えない
    assert "output_config" not in KW
    # 呼ぶ側が output_config を決めていれば、そのまま（_create の setdefault と同じ）
    own = db.params_of(dict(KW, output_config={"effort": "high"}), "m", "medium")
    assert own["output_config"] == {"effort": "high"}


def test_custom_id_follows_official_rule():
    key = db.key_of(db.params_of(KW, "claude-sonnet-5-5", "medium"))
    for stage in ("draft", "more"):
        cid = db.custom_id(stage, key, 12)
        assert db.CUSTOM_ID_RE.match(cid) and len(cid) <= 64
    with pytest.raises(ValueError):
        db.custom_id("書き足し", key, 1)


def test_key_changes_with_content_only():
    a = db.key_of(db.params_of(KW, "m", "medium"))
    assert a == db.key_of(db.params_of(copy.deepcopy(KW), "m", "medium"))
    assert a != db.key_of(db.params_of(dict(KW, max_tokens=8000), "m", "medium"))
    assert a != db.key_of(db.params_of(KW, "m", "high"))


# ---------------------------------------------------------------------------
# うまくいく場合
# ---------------------------------------------------------------------------
def test_success_returns_batch_result_and_records_half_price(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 40, "result": "result_succeeded_short.jsonl"}])
    resp, calls = go(tmp_path, client, clock)
    assert resp.id == "msg_fixture_01"            # 別の依頼の返事（先頭行）ではない
    assert calls.direct_n == 0
    assert calls.records == [("msg_fixture_01", True)]
    req = client.messages.batches.created[0][0]
    assert req["params"] == db.params_of(KW, "claude-sonnet-5-5", "medium")
    st = state(tmp_path)
    assert st["date"] == "2026-10-07" and st["submits"] == 1
    assert st["stages"]["draft"]["status"] == "used" and st["stages"]["draft"]["recorded"]
    # 間はのびていく（30秒→45秒→…）。最大5分
    assert clock.slept[:3] == [30, 45, 67.5]
    assert max(clock.slept) <= db.POLL_MAX
    assert clock.now() - START < timedelta(minutes=50)


def test_polls_never_sleep_past_deadline(tmp_path):
    clock = FakeClock(datetime(2026, 10, 7, 17, 0, tzinfo=JST))
    client = FakeClient(clock, [{"minutes": 600, "result": "result_succeeded_short.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1 and calls.records == [("msg_fixture_02", False)]
    deadline = datetime(2026, 10, 7, 17, 30, tzinfo=JST)
    # 締め切りちょうどまで眠り、取り消しの後は最大 CANCEL_GRACE 秒だけ待つ
    assert client.messages.batches.canceled == ["msgbatch_fake_1"]
    assert clock.now() <= deadline
    assert state(tmp_path)["stages"]["draft"]["status"] == "fallback"


def test_deadline_but_finished_during_cancel_uses_it(tmp_path):
    """取り消しの間に出来ていた返事は、もう払っているので使う（二重に払わない）。"""
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 600, "result": "result_succeeded_short.jsonl",
                                 "on_cancel": "result_succeeded_short.jsonl"}])
    resp, calls = go(tmp_path, client, clock)
    assert resp.id == "msg_fixture_01" and calls.direct_n == 0
    assert calls.records == [("msg_fixture_01", True)]


def test_deadline_cancel_ends_as_canceled_goes_direct(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 600, "result": "result_succeeded_short.jsonl",
                                 "on_cancel": "result_canceled.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1 and calls.records == [("msg_fixture_02", False)]


# ---------------------------------------------------------------------------
# Batch を使わない場合
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("when", ["17:11", "17:30", "19:00"])
def test_too_close_or_past_deadline_goes_direct_without_submitting(tmp_path, when):
    h, m = map(int, when.split(":"))
    clock = FakeClock(datetime(2026, 10, 7, h, m, tzinfo=JST))
    client = FakeClient(clock, [])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1 and client.messages.batches.created == []


@pytest.mark.parametrize("env,batch", [
    (GHA, True),
    ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_run"}, True),
    ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"}, False),
    ({}, False),                                           # 手元のPC
    ({"COLLESPO_DIALOGUE_BATCH": "on"}, True),
    ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
      "COLLESPO_DIALOGUE_BATCH": "on"}, True),
    (dict(GHA, COLLESPO_DIALOGUE_BATCH="off"), False),
    (dict(GHA, COLLESPO_DIALOGUE_BATCH="0"), False),
])
def test_switches(tmp_path, env, batch):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    _, calls = go(tmp_path, client, clock, env=env)
    assert (len(client.messages.batches.created) == 1) is batch
    assert calls.direct_n == (0 if batch else 1)


def test_create_failure_goes_direct(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [], fail_create=True)
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1 and calls.records == [("msg_fixture_02", False)]


def test_retrieve_keeps_failing_cancels_and_goes_direct(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}],
                        fail_retrieve=db.MAX_POLL_ERRORS)
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1 and client.messages.batches.canceled == ["msgbatch_fake_1"]


def test_a_few_retrieve_errors_are_tolerated(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}],
                        fail_retrieve=db.MAX_POLL_ERRORS - 1)
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 0 and calls.records == [("msg_fixture_01", True)]


# ---------------------------------------------------------------------------
# 失敗した返事
# ---------------------------------------------------------------------------
def test_invalid_request_goes_direct_without_resubmitting(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 3, "result": "result_errored_invalid.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert len(client.messages.batches.created) == 1
    assert calls.direct_n == 1 and calls.records == [("msg_fixture_02", False)]
    st = state(tmp_path)["stages"]["draft"]
    assert st["status"] == "fallback" and "invalid_request_error" in st["fallback_reason"]


@pytest.mark.parametrize("bad", ["result_errored_overloaded.jsonl", "result_expired.jsonl"])
def test_server_error_or_expired_resubmits_once(tmp_path, bad):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 3, "result": bad},
                                {"minutes": 10, "result": "result_succeeded_short.jsonl"}])
    resp, calls = go(tmp_path, client, clock)
    created = client.messages.batches.created
    assert len(created) == 2 and calls.direct_n == 0
    assert created[0][0]["custom_id"] != created[1][0]["custom_id"]   # 出し直しは別の id
    assert created[0][0]["params"] == created[1][0]["params"]         # 中身は同じ
    assert calls.records == [("msg_fixture_01", True)]
    assert state(tmp_path)["stages"]["draft"]["tries"] == 2


def test_server_error_twice_goes_direct(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 3, "result": "result_errored_overloaded.jsonl"},
                                {"minutes": 3, "result": "result_errored_overloaded.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert len(client.messages.batches.created) == 2 and calls.direct_n == 1


def test_server_error_near_deadline_goes_direct_instead_of_resubmitting(tmp_path):
    clock = FakeClock(datetime(2026, 10, 7, 16, 55, tzinfo=JST))
    client = FakeClient(clock, [{"minutes": 25, "result": "result_errored_overloaded.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert len(client.messages.batches.created) == 1 and calls.direct_n == 1


def test_canceled_by_someone_goes_direct(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 3, "result": "result_canceled.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1


def test_missing_result_goes_direct(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 3, "result": "result_succeeded_short.jsonl"}])
    real = client.messages.batches.results
    client.messages.batches.results = lambda bid: iter(
        [r for r in real(bid) if r.custom_id.startswith("dlg-other")])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 1


def test_refusal_stops_like_create_and_still_records(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 3, "result": "result_refusal.jsonl"}])
    calls = Calls()
    with pytest.raises(SystemExit) as e:
        go(tmp_path, client, clock, calls=calls)
    assert "general_harms" in str(e.value)
    assert calls.direct_n == 0 and calls.records == [("msg_fixture_01", True)]


# ---------------------------------------------------------------------------
# 二重に出さない・作り直しの日
# ---------------------------------------------------------------------------
def test_rerun_waits_for_the_batch_already_submitted(tmp_path):
    """出した後で落ちた回の続き。同じ中身なら、もう1つ出さずに前の Batch を待つ。"""
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 60, "result": "result_succeeded_short.jsonl"}])
    # 1回目: 出した直後に落ちた（様子見の最初で例外）
    client.messages.batches.retrieve, keep = (
        lambda bid: (_ for _ in ()).throw(KeyboardInterrupt())), client.messages.batches.retrieve
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, client, clock)
    assert state(tmp_path)["stages"]["draft"]["status"] == "submitted"
    # 2回目（同じ日・同じ中身）
    client.messages.batches.retrieve = keep
    resp, calls = go(tmp_path, client, clock)
    assert len(client.messages.batches.created) == 1
    assert resp.id == "msg_fixture_01" and calls.records == [("msg_fixture_01", True)]


def test_remake_after_used_submits_a_new_one(tmp_path):
    """使い終わった依頼と同じ中身でも、作り直しなら新しく出す（同じ台本を返さない）。"""
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"},
                                {"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    go(tmp_path, client, clock)
    go(tmp_path, client, clock)
    c = client.messages.batches.created
    assert len(c) == 2 and c[0][0]["custom_id"].endswith("-1") and c[1][0]["custom_id"].endswith("-2")
    assert state(tmp_path)["submits"] == 2


def test_changed_material_cancels_the_old_batch(tmp_path):
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 60, "result": "result_succeeded_short.jsonl"},
                                {"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    client.messages.batches.retrieve, keep = (
        lambda bid: (_ for _ in ()).throw(KeyboardInterrupt())), client.messages.batches.retrieve
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, client, clock)
    client.messages.batches.retrieve = keep
    new_kw = {"max_tokens": 16000, "messages": [{"role": "user", "content": "新しい材料"}]}
    _, calls = go(tmp_path, client, clock, kw=new_kw)
    assert client.messages.batches.canceled == ["msgbatch_fake_1"]
    assert len(client.messages.batches.created) == 2 and calls.direct_n == 0


def test_daily_submit_limit(tmp_path):
    clock = FakeClock()
    plans = [{"minutes": 1, "result": "result_succeeded_short.jsonl"}] * (db.MAX_SUBMITS + 1)
    client = FakeClient(clock, plans)
    calls = Calls()
    for _ in range(db.MAX_SUBMITS + 1):
        go(tmp_path, client, clock, calls=calls)
    assert len(client.messages.batches.created) == db.MAX_SUBMITS
    assert calls.direct_n == 1


def test_state_resets_on_a_new_day(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "date": "2026-10-06", "submits": 99,
        "stages": {"draft": {"status": "submitted", "batch_id": "old", "key": "x"}}}),
        encoding="utf-8")
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 0 and client.messages.batches.canceled == []
    assert state(tmp_path)["submits"] == 1


def test_broken_state_file_is_not_fatal(tmp_path):
    (tmp_path / "state.json").write_text("{壊れた", encoding="utf-8")
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    _, calls = go(tmp_path, client, clock)
    assert calls.direct_n == 0


def test_after_submit_hook_gets_state_path_and_its_failure_is_ignored(tmp_path):
    seen = []

    def hook(path):
        seen.append(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))
        raise RuntimeError("押せない")

    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    _, calls = go(tmp_path, client, clock, after_submit=hook)
    assert seen and seen[0]["stages"]["draft"]["status"] == "submitted"
    assert calls.direct_n == 0


def test_step_summary_line(tmp_path):
    s = tmp_path / "summary.md"
    clock = FakeClock()
    client = FakeClient(clock, [{"minutes": 5, "result": "result_succeeded_short.jsonl"}])
    go(tmp_path, client, clock, env=dict(GHA, GITHUB_STEP_SUMMARY=str(s)))
    assert "Batch（半額）" in s.read_text(encoding="utf-8")


def test_fixtures_are_labeled_handmade():
    for p in FIX.iterdir():
        text = p.read_text(encoding="utf-8")
        assert "手で作った見本" in text, p.name


# ---------------------------------------------------------------------------
def test_fixtures_match_sdk_types_when_sdk_is_installed():
    """anthropic が入っている所では、見本が SDK の型として読めることも確かめる。"""
    anthropic = pytest.importorskip("anthropic")
    if not hasattr(anthropic, "__version__"):
        pytest.skip("偽の anthropic")
    from anthropic.types.messages import MessageBatch, MessageBatchIndividualResponse
    for p in sorted(FIX.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = MessageBatchIndividualResponse.model_validate(json.loads(line))
            assert r.result.type in ("succeeded", "errored", "canceled", "expired"), p.name
            if r.result.type == "errored":
                assert r.result.error.error.type in ("invalid_request_error", "overloaded_error")
    states = json.loads((FIX / "batch_states.json").read_text(encoding="utf-8"))
    for k in ("in_progress", "canceling", "ended"):
        assert MessageBatch.model_validate(states[k]).processing_status == k


def test_real_sdk_request_shape_with_mock_http(tmp_path):
    """anthropic が入っている所では、本物の SDK を通信なし（偽の HTTP）で動かし、
    POST /v1/messages/batches に載る中身と、結果（JSONL）の読み方を確かめる。"""
    anthropic = pytest.importorskip("anthropic")
    if not hasattr(anthropic, "__version__"):
        pytest.skip("偽の anthropic")
    httpx = pytest.importorskip("httpx2")
    states = json.loads((FIX / "batch_states.json").read_text(encoding="utf-8"))
    sent, polls = {}, {"n": 0}

    def handler(request):
        path = request.url.path
        if request.method == "POST" and path == "/v1/messages/batches":
            sent.update(json.loads(request.content))
            return httpx.Response(200, json=states["in_progress"])
        if request.method == "GET" and path == "/v1/messages/batches/msgbatch_fixture_01":
            polls["n"] += 1
            return httpx.Response(200, json=states["ended" if polls["n"] > 1 else "in_progress"])
        if request.method == "GET" and path.endswith("/results"):
            cid = sent["requests"][0]["custom_id"]
            body = "".join(json.dumps(json.loads(line) | (
                {"custom_id": cid} if json.loads(line)["custom_id"].startswith("dlg-draft-") else {}),
                ensure_ascii=False) + "\n"
                for line in (FIX / "result_succeeded_short.jsonl").read_text(
                    encoding="utf-8").splitlines())
            return httpx.Response(200, content=body.encode("utf-8"),
                                  headers={"content-type": "application/binary"})
        return httpx.Response(404, json={"type": "error", "error": {
            "type": "not_found_error", "message": path}})

    client = anthropic.Anthropic(api_key="dummy-not-a-key", base_url="http://fake.invalid",
                                 max_retries=0,
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    clock = FakeClock()
    resp, calls = go(tmp_path, client, clock)
    assert sent["requests"][0]["params"] == db.params_of(KW, "claude-sonnet-5-5", "medium")
    assert db.CUSTOM_ID_RE.match(sent["requests"][0]["custom_id"])
    assert resp.id == "msg_fixture_01" and resp.usage.input_tokens == 5210
    assert [b.type for b in resp.content] == ["thinking", "text"]
    assert calls.direct_n == 0 and calls.records == [("msg_fixture_01", True)]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "--tb=short", "--basetemp",
                                 str(HERE.parent / "build/batch-test-20261007")]))
