"""LLM の受信境界で制作側の言葉を止める。通信は呼び出し側に任せる。"""
import copy
import functools
import json
import pathlib
import re
import sys


class BackstageError(ValueError):
    """削ると形や意味が壊れる原稿は既存の失敗経路へ戻す。"""


@functools.lru_cache(maxsize=1)
def rules():
    path = pathlib.Path(__file__).resolve().parent.parent / 'data/backstage_phrases.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    return data['instruction'], [(r['id'], re.compile(r['regex'], re.I), r.get('scope', 'all'))
                                 for r in data['patterns']]


def violations(text, *, scope="all"):
    # 文字間の空白・改行で禁止語をすり抜けさせない。材料費等は一致しない。
    compact = re.sub(r'\s+', '', text or '')
    return [name for name, pat, target in rules()[1]
            if target in ('all', scope) and (pat.search(text or '') or pat.search(compact))]


def response_text(resp):
    return ''.join(b.text for b in resp.content if b.type == 'text')


def with_instruction(kw):
    kw = copy.deepcopy(kw)
    kw['messages'] = list(kw.get('messages', [])) + [
        {'role': 'user', 'content': rules()[0]}]
    return kw


def _filtered(resp, mode, label, *, already_recorded=False, diagnostics=None):
    text = response_text(resp)
    if mode == 'lines':
        # 管理された行形式のみ。JSONや一続きの原稿を行ごとに削らない。
        kept = []
        for i, line in enumerate(text.splitlines(), 1):
            bad = violations(line)
            if bad:
                if diagnostics is not None:
                    diagnostics['filtered'] = True
                print(f'[warn] {label}: 楽屋の言葉の行を除外 {i}行目 ({",".join(bad)})', file=sys.stderr)
            else:
                kept.append(line)
        clean = '\n'.join(kept).strip()
        if clean and not violations(clean):
            result = copy.deepcopy(resp)
            blocks = [b for b in result.content if b.type == 'text']
            blocks[0].text = clean
            for b in blocks[1:]:
                b.text = ''
            if already_recorded and getattr(result, 'usage', None) is not None:
                # 予算で訂正を止めた場合、初回費用はすでに記録済み。
                result.usage.input_tokens = result.usage.output_tokens = 0
            return result
    print(f'[warn] {label}: 楽屋の言葉が残ったため生成結果を失敗扱い', file=sys.stderr)
    raise BackstageError(f'{label}: 楽屋の言葉を含む原稿は使用しません')


def guard_response(first, retry, *, label, mode='whole', rejected=None, allowed=None, diagnostics=None):
    """初回応答・訂正1回。費用記録済みのBatchにも同じ検査を掛ける。"""
    resp = first()
    bad = violations(response_text(resp))
    if not bad:
        return resp
    if rejected:
        rejected(resp)
    print(f'[warn] {label}: 楽屋の言葉を検出 ({",".join(bad)})。1回作り直し', file=sys.stderr)
    if allowed is not None and not allowed():
        return _filtered(resp, mode, label, already_recorded=rejected is not None, diagnostics=diagnostics)
    # 再生成が通信エラーなら既存の呼び出し側の失敗経路へ。初回の危険な文へ戻さない。
    resp = retry()
    if not violations(response_text(resp)):
        return resp
    try:
        return _filtered(resp, mode, label, diagnostics=diagnostics)
    except BackstageError:
        if rejected:
            rejected(resp)
        raise


def create(client, *, label, mode='whole', category=None, **kw):
    """Messages API。採用された応答の費用記録は従来どおり呼び出し側。"""
    import token_log
    prepared = with_instruction(kw)
    return guard_response(lambda: client.messages.create(**prepared),
                          lambda: client.messages.create(**prepared),
                          label=label, mode=mode,
                          rejected=lambda r: token_log.record(category or label, kw['model'], r),
                          allowed=lambda: token_log.allowed(category or label))
