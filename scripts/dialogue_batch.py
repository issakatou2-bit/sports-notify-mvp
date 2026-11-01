#!/usr/bin/env python3
"""長編の台本の呼び出しを、Message Batches API（料金が半分）で出す。

なぜ要るのか:
  API代の半分強が長編の台本（generate_dialogue.py、Sonnet 5.5）。
  台本の中身（プロンプト・モデル・effort・検査）を変えずに安くできるのは
  Batch だけ。Batch は料金が半分になる代わりに、返事が来るまで
  最長24時間かかる（たいていは1時間以内）。
  長編は 15:10 ごろに作り始めて 21:00 に予約公開なので、待てる時間はある。

  ただし**公開に間に合わないのは困る。**だから締め切り（既定 17:30 JST）を
  置き、それまでに返らなければ Batch を取り消して、いまの呼び方
  （generate_dialogue._create）で作る。

ここがすること（run）:
  1. 使うかどうかを決める（環境変数・手で動かした回・締め切りまでの残り時間・
     その日に出した回数）。使わないなら、いまの呼び方へ。
  2. 同じ中身の依頼をもう出していないかを、状態ファイルで見る（二重に出さない）。
     出していて、まだ使っていなければ、その Batch の返事を待つ。
  3. 出す。出したらすぐ状態ファイルに書く（そのあと落ちても、次の回が拾える）。
  4. 間をのばしながら様子を見る（30秒→45秒→…→最大5分）。
  5. 返事を custom_id で拾う。
       succeeded            → そのまま返す（refusal なら、いまと同じく止める）
       errored（依頼の誤り） → いまの呼び方へ（_create がモデル名の誤りなら Sonnet 5 で1度やり直す）
       errored（向こうの不調）・expired → 時間が残っていれば1度だけ出し直す。無ければいまの呼び方へ
       canceled・見つからない → いまの呼び方へ
  6. 締め切りに来たら取り消す。取り消しの間に返事が出来ていたら、それを使う
     （もう払っているので、二重に払わない）。出来ていなければ、いまの呼び方へ。

  費用の記録（token_log.record）は、払った返事1つにつき1回だけ。Batch の返事は
  batch=True（半額）で残す。

API キーはここでは扱わない。client は呼ぶ側が作って渡す（検査では偽物を渡す）。
"""

import copy
import hashlib
import json
import os
import pathlib
import re
import time
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 状態ファイル。同じ依頼を二重に出さないための控え。
# 本番では data/ に置き、出した直後にコミットすると、ジョブをやり直しても
# 続きから待てる（COLLESPO_BATCH_COMMIT=1。README の「決めてほしいこと」）。
STATE_PATH = os.environ.get("COLLESPO_BATCH_STATE") or "data/dialogue_batch.json"

# 締め切り（日本時間）。これを過ぎたら、取り消していまの呼び方で作る。
DEADLINE = os.environ.get("COLLESPO_BATCH_DEADLINE") or "17:30"

# 締め切りまでこれより短いなら、Batch は出さない（待っても返らない見込みが高い）。
MIN_LEFT = timedelta(minutes=20)

# 様子を見る間隔（秒）。最初は短く、だんだん長く。締め切りを越えては眠らない。
POLL_FIRST = 30
POLL_GROW = 1.5
POLL_MAX = 300

# 取り消したあと、取り消しが終わるのを待つ長さ（秒）。
# 取り消す前に出来上がっていた返事は、もう払っているので拾いたい。
CANCEL_GRACE = 120

# 向こうの不調（api_error・overloaded_error）や期限切れのとき、出し直す回数。
RESUBMIT = 1

# 1日に Batch を出してよい回数。作り直しが続く日に、待ちが積み重ならないように。
MAX_SUBMITS = 4

# 様子見の問い合わせが続けて失敗したら、あきらめる回数。
MAX_POLL_ERRORS = 5

# custom_id の決まり（公式: 1〜64文字、英数字・-・_ だけ）。
CUSTOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class Fallback(Exception):
    """Batch をあきらめて、いまの呼び方で作るときの合図（理由つき）。"""


def _g(o, name, default=None):
    """SDK の型（属性）でも、JSON（辞書）でも同じように読む。"""
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


def _now() -> datetime:
    return datetime.now(JST)


def mode(env=None) -> str:
    """COLLESPO_DIALOGUE_BATCH: on / off / auto（既定）。"""
    env = os.environ if env is None else env
    v = (env.get("COLLESPO_DIALOGUE_BATCH") or "auto").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return "on"
    if v in ("0", "off", "false", "no"):
        return "off"
    return "auto"


def wanted(env=None) -> tuple:
    """Batch を使うか。(使う?, 理由)。

    auto のとき、**人が手で動かした回（workflow_dispatch）と、GitHub Actions の
    外（手元のPC）では使わない。**作り直しや試しを頼んだ人は、いま結果を見たい。
    1時間待たせるより、倍の値段（1本あたり数円）で今すぐ返すほうがよい。
    on にすれば、どこでも使う。
    """
    env = os.environ if env is None else env
    m = mode(env)
    if m == "off":
        return False, "COLLESPO_DIALOGUE_BATCH=off"
    if m == "auto":
        if env.get("GITHUB_ACTIONS") != "true":
            return False, "GitHub Actions の外なので、すぐ作ります"
        if env.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
            return False, "手で動かした回なので、すぐ作ります"
    return True, ""


def deadline_at(now: datetime, hhmm: str = None) -> datetime:
    """その日の締め切り（日本時間）。"""
    hhmm = hhmm or DEADLINE
    h, m = (int(x) for x in hhmm.split(":"))
    return now.astimezone(JST).replace(hour=h, minute=m, second=0, microsecond=0)


def params_of(kw: dict, model: str, effort: str) -> dict:
    """Batch に載せる params。_create と**同じもの**を作る。

    _create は model=MODEL を足し、output_config が無ければ effort を足す。
    ここで食い違うと、Batch と今の呼び方で別の台本になる。
    """
    p = copy.deepcopy(kw)
    p.setdefault("output_config", {"effort": effort})
    return {"model": model, **p}


def key_of(params: dict) -> str:
    """依頼の中身の指紋。同じ中身なら同じ値。"""
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def custom_id(stage: str, key: str, n: int) -> str:
    cid = f"dlg-{stage}-{key[:16]}-{n}"
    if not CUSTOM_ID_RE.match(cid):
        raise ValueError(f"custom_id の形が違います: {cid}")
    return cid


# ---------------------------------------------------------------------------
# 状態ファイル
# ---------------------------------------------------------------------------
def load_state(path: str, today: str) -> dict:
    """その日の控え。日が変わっていたら空から。"""
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {}
    if not isinstance(d, dict) or d.get("date") != today:
        d = {"date": today, "submits": 0, "stages": {}}
    d.setdefault("submits", 0)
    d.setdefault("stages", {})
    return d


def save_state(path: str, state: dict) -> None:
    """途中で落ちても壊れないよう、別名で書いてから置き換える。"""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------
def run(client, stage: str, kw: dict, *, model: str, effort: str, direct, record,
        now=_now, sleep=time.sleep, state_path: str = None, deadline: str = None,
        env=None, after_submit=None, log=print):
    """台本の呼び出しを1つ。Batch で返るならそれを、だめならいまの呼び方で。

    client  : anthropic.Anthropic()（検査では偽物）
    stage   : "draft"（1回目）/ "more"（書き足し）。custom_id と状態ファイルの見出し
    kw      : _create に渡すのと同じ引数（max_tokens・messages。model は含めない）
    direct  : いまの呼び方。引数なしで呼ぶと返事を返す（lambda: _create(client, **kw)）
    record  : record(resp, batch) で費用を1回残す
    after_submit : 出した直後に呼ぶ（状態ファイルのコミットなど。任意）
    返り値   : Messages API の返事（Message と同じ形）
    """
    state_path = state_path or STATE_PATH
    t0 = now()
    ok, why = wanted(env)
    if not ok:
        return _direct(direct, record, why, log, env)

    # Batchの通信だけ短い上限にする。通常呼び出しの設定・思考設定は不変。
    if callable(getattr(client, "with_options", None)):
        client = client.with_options(timeout=15.0, max_retries=0)
    params = params_of(kw, model, effort)
    key = key_of(params)
    today = t0.astimezone(JST).strftime("%Y-%m-%d")
    state = load_state(state_path, today)
    entry = state["stages"].get(stage)
    limit = deadline_at(t0, deadline)

    # 前の回の控え。同じ中身で、まだ使っていない Batch があれば、それを待つ。
    if entry and entry.get("key") == key and entry.get("status") == "submitted":
        log(f"[info] 台本({stage}): 前の回に出した Batch {entry['batch_id']} の返事を待ちます")
    else:
        if entry and entry.get("status") == "submitted":
            # 材料が変わった（作り直し）。古いほうは要らないので取り消す。
            # 取り消しの前に処理が済んでいた分は払うことになるが、まだなら払わない。
            _cancel(client, entry["batch_id"], log, "材料が変わったため")
            entry["status"] = "superseded"
            save_state(state_path, state)
        n = (entry.get("n", 0) + 1) if entry else 1
        entry = None
        if now() >= limit - MIN_LEFT:
            return _direct(direct, record,
                           f"締め切り {limit:%H:%M} まで{int(MIN_LEFT.total_seconds() // 60)}分を切っています",
                           log, env)
        if state["submits"] >= MAX_SUBMITS:
            return _direct(direct, record, f"きょうは Batch を{MAX_SUBMITS}回出しました", log, env)
        try:
            entry = _submit(client, stage, params, key, n, state, state_path, now, log)
        except Fallback as e:
            return _direct(direct, record, str(e), log, env)
        if after_submit:
            try:
                after_submit(state_path)
            except Exception as e:                       # noqa: BLE001
                log(f"[warn] 状態ファイルを残せませんでした（続けます）: {e}")

    while True:
        try:
            resp = _wait_and_take(client, entry, limit, now, sleep, log)
        except _Resubmit as e:
            if entry.get("tries", 1) <= RESUBMIT and now() < limit - MIN_LEFT \
                    and state["submits"] < MAX_SUBMITS:
                log(f"[info] 台本({stage}): {e}。Batch をもう1度出します")
                tries = entry.get("tries", 1) + 1
                try:
                    entry = _submit(client, stage, params, key, entry.get("n", 1) + 1,
                                    state, state_path, now, log, tries=tries)
                    if after_submit:
                        try:
                            after_submit(state_path)
                        except Exception as persist_error:  # noqa: BLE001
                            log(f"[warn] 再依頼の状態を残せません: {persist_error}")
                except Fallback as e2:
                    return _finish_direct(direct, record, str(e2), log, state, state_path, entry, env)
                continue
            return _finish_direct(direct, record, str(e), log, state, state_path, entry, env)
        except Fallback as e:
            return _finish_direct(direct, record, str(e), log, state, state_path, entry, env)
        break

    # 払った返事。費用は1回だけ残す（前の回で残していれば残さない）。
    entry["status"] = "used"
    waited = (now() - t0).total_seconds() / 60
    if not entry.get("recorded"):
        record(resp, True)
        entry["recorded"] = True
    save_state(state_path, state)
    log(f"[info] 台本({stage}): Batch（半額）で受け取りました（待ち {waited:.0f}分）")
    _summary(f"台本({stage}): Batch（半額）で作成。待ち {waited:.0f}分", env)
    _stop_if_refused(resp)
    return resp


class _Resubmit(Exception):
    """向こうの都合で返事が出来なかった。出し直してよい。"""


def _submit(client, stage, params, key, n, state, state_path, now, log, tries=1) -> dict:
    cid = custom_id(stage, key, n)
    try:
        batch = client.messages.batches.create(
            requests=[{"custom_id": cid, "params": params}])
    except Exception as e:                               # noqa: BLE001
        raise Fallback(f"Batch を出せませんでした（{type(e).__name__}: {e}）")
    entry = {"key": key, "n": n, "custom_id": cid, "batch_id": _g(batch, "id"),
             "status": "submitted", "tries": tries, "recorded": False,
             "submitted_at": now().isoformat(timespec="seconds"),
             "model": params.get("model")}
    state["stages"][stage] = entry
    state["submits"] = int(state.get("submits", 0)) + 1
    save_state(state_path, state)
    log(f"[info] 台本({stage}): Batch {entry['batch_id']} を出しました（{cid}）")
    return entry


def _wait_and_take(client, entry, limit, now, sleep, log):
    """終わるまで待って、自分の返事を取り出す。"""
    bid, cid = entry["batch_id"], entry["custom_id"]
    interval, errors = POLL_FIRST, 0
    while True:
        if now() >= limit:
            return _at_deadline(client, entry, limit, now, sleep, log)
        try:
            b = client.messages.batches.retrieve(bid)
            errors = 0
        except Exception as e:                           # noqa: BLE001
            errors += 1
            log(f"[warn] Batch の様子を見られませんでした（{errors}回目）: {e}")
            if errors >= MAX_POLL_ERRORS:
                _cancel(client, bid, log, "様子が分からないため")
                raise Fallback("Batch の様子が分からなくなりました")
            b = None
        if b is not None and _g(b, "processing_status") == "ended" and now() < limit:
            return _take(client, bid, cid, log)
        # 取り消し待ちの2分も17:30までの予算に含める。期限後に待たない。
        left = (limit - timedelta(seconds=CANCEL_GRACE) - now()).total_seconds()
        if left <= 0:
            return _at_deadline(client, entry, limit, now, sleep, log)
        sleep(min(interval, left))
        interval = min(interval * POLL_GROW, POLL_MAX)


def _at_deadline(client, entry, limit, now, sleep, log):
    """締め切り。取り消して、取り消しの間に出来ていた返事があれば使う。"""
    bid, cid = entry["batch_id"], entry["custom_id"]
    _cancel(client, bid, log, f"締め切り {limit:%H:%M} に備えて")
    end = limit
    while now() < end:
        try:
            b = client.messages.batches.retrieve(bid)
        except Exception:                                # noqa: BLE001
            b = None
        if b is not None and _g(b, "processing_status") == "ended" and now() < limit:
            try:
                return _take(client, bid, cid, log)
            except _Resubmit as e:
                raise Fallback(f"締め切りまでに返りませんでした（{e}）")
        sleep(min(15, max(0, (end - now()).total_seconds())))
    raise Fallback(f"締め切り {limit:%H:%M} までに返りませんでした")


def _take(client, bid, cid, log):
    """終わった Batch から、custom_id の返事を拾う（並び順は当てにしない）。"""
    try:
        found = None
        for r in client.messages.batches.results(bid):
            if _g(r, "custom_id") == cid:
                found = _g(r, "result")
                break
    except Exception as e:                               # noqa: BLE001
        raise Fallback(f"Batch の返事を読めませんでした（{type(e).__name__}: {e}）")
    if found is None:
        raise Fallback(f"Batch {bid} に {cid} の返事がありません")
    kind = _g(found, "type")
    if kind == "succeeded":
        return _g(found, "message")
    if kind == "errored":
        err = _g(_g(found, "error"), "error")
        etype = _g(err, "type") or "?"
        msg = _g(err, "message") or ""
        if etype == "invalid_request_error":
            # 依頼の形かモデル名の誤り。出し直しても同じなので、いまの呼び方へ
            # （_create はモデル名が通らなければ Sonnet 5 で1度やり直す）。
            raise Fallback(f"Batch が依頼を受け付けませんでした（{etype}: {msg}）")
        raise _Resubmit(f"Batch で向こうの不調（{etype}: {msg}）")
    if kind == "expired":
        raise _Resubmit("Batch が24時間の期限で切れました")
    if kind == "canceled":
        raise Fallback("Batch が取り消されていました")
    raise Fallback(f"Batch の返事の種類が分かりません（{kind}）")


def _cancel(client, bid, log, why):
    try:
        client.messages.batches.cancel(bid)
        log(f"[info] Batch {bid} を取り消しました（{why}）")
    except Exception as e:                               # noqa: BLE001
        # もう終わっている Batch は取り消せない。困らないので続ける。
        log(f"[warn] Batch {bid} を取り消せませんでした（{why}）: {e}")


def _stop_if_refused(resp):
    """断られた返事は空。いまの _create と同じく、理由を出して止める。"""
    if _g(resp, "stop_reason") == "refusal":
        det = _g(resp, "stop_details")
        cat = _g(det, "category") if det else None
        raise SystemExit(f"[error] 台本の生成を断られました（{cat}）")


def _direct(direct, record, why, log, env=None):
    log(f"[info] 台本: いまの呼び方で作ります（{why}）")
    resp = direct()
    record(resp, False)
    _summary(f"台本: 通常の呼び方で作成（{why}）", env)
    return resp


def _finish_direct(direct, record, why, log, state, state_path, entry, env=None):
    log(f"::warning::台本: Batch をあきらめ、いまの呼び方で作ります（{why}）")
    if entry is not None:
        entry["status"] = "fallback"
        entry["fallback_reason"] = why
        save_state(state_path, state)
    resp = direct()
    record(resp, False)
    _summary(f"台本: Batch をあきらめて通常の呼び方で作成（{why}）", env)
    return resp


def _summary(line: str, env=None) -> None:
    env = os.environ if env is None else env
    s = env.get("GITHUB_STEP_SUMMARY")
    if not s:
        return
    try:
        with open(s, "a", encoding="utf-8") as f:
            f.write(line + "\n\n")
    except OSError:
        pass
