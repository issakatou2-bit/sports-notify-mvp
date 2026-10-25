"""停止候補の行を一度だけ再点検。AIの指摘だけでは事実を確定しない。"""
import json
import re

import sanity_internal
import sanity_material as material
import sanity_sources as sources

MAX_INPUT_BYTES = 9000
MAX_OUTPUT_TOKENS = 700
MAX_COST_USD = .03


def unresolved(issue):
    return (issue.get('kind') == material.FACT and issue.get('severity') == 'high'
            and not issue.get('supported') and not issue.get('confirmed'))


def scoped(documents, issues, errors):
    """全原稿をAIへ送り直さず、指摘行とその行の材料だけにする。"""
    result = []
    indices = {int(next(v for v in m.groups() if v)) for e in errors
               for m in [re.search(r'行(\d+)|^(\d+)行目|の(\d+)番目', e)] if m}
    quotes = [i.get('where') for i in issues if unresolved(i) or i.get('confirmed')]
    for d in documents:
        selected = []
        for index, s in enumerate(d.get('segments') or [], 1):
            heads = (s.get('meta') or {}).get('source_headlines') or []
            metadata_issue = any('見出し' in e or any(h.get('title') and h['title'] in e for h in heads)
                                 for e in errors) if heads else False
            if index in indices or metadata_issue or any(q and q in (s.get('text') or '') for q in quotes):
                selected.append(dict(s, _sanity_original_line=index,
                    _sanity_context=material.claim_context(d, s.get('text') or '',
                                                           material.grounding([d]))))
        if selected:
            result.append(dict(d, _sanity_document_key=sources.key(d), segments=selected))
    return result


def short_materials(documents, materials):
    """材料は指摘人物・対戦に限定。巨大な順位表・別の原稿を再送しない。"""
    result = []
    for d in documents:
        text = '。'.join(s.get('_sanity_context') or s.get('text') or '' for s in d.get('segments') or [])
        for source in sources.for_document(d, materials):
            row = {k: source[k] for k in ('source', 'source_url', 'retrieved_at', 'date_jst') if k in source}
            for field in ('series', 'players', 'games'):
                items = source.get(field) or []
                if isinstance(items, dict):
                    items = list(items.values())
                selected = []
                for item in items:
                    names = [item.get('name'), item.get('name_jp'), item.get('home_team_name'), item.get('away_team_name')]
                    names += [t.get('name') for t in item.get('teams') or []]
                    if any(n and n in text for n in names):
                        selected.append(item)
                if selected:
                    row[field] = selected
            comps = []
            for comp in source.get('competitions') or []:
                import soccer_sanity_material as soccer
                jp = [r for r in comp.get('jp') or [] if (r.get('name') and r['name'] in text)
                      or any(n and n in text for n in soccer.aliases(r.get('club_jp') or ''))]
                if jp:
                    comps.append(dict(code=comp.get('code'), jp=jp))
            if comps:
                row['competitions'] = comps
            if any(row.get(k) for k in ('series', 'players', 'games', 'competitions')):
                result.append(row)
    return result


def ai_review(documents, issues, materials, api_key):
    """SDK/内容の自動再試行も行わず、短いリクエストを最大1回。"""
    import llm_models
    import token_log
    import backstage_guard
    payload = dict(lines=[dict(document_key=sources.key(d),
                        lines=[dict(line=s.get('_sanity_original_line'), text=s.get('text'))
                               for s in d.get('segments') or []]) for d in documents],
                   findings=[{k: i.get(k) for k in ('where', 'why')} for i in issues],
                   materials=short_materials(documents, materials),
                   headlines=material.headline_grounding(documents))
    prompt = ('次の指摘行だけ再点検してください。材料が現在の事実です。学習知識で所属・順位・'
              '成績を否定しない。材料のない事実は未確認です。計算は式を示してください。'
              '新しい行を指摘しない。JSON配列だけ: '
              '[{"kind":"事実の誤り|説明不足・文脈","severity":"high|low",'
              '"where":"引用","why":"根拠"}]\n' + json.dumps(payload, ensure_ascii=False))
    params = llm_models.params('translate', MAX_OUTPUT_TOKENS)
    params['max_tokens'] = MAX_OUTPUT_TOKENS
    model = params['model']
    # UTF-8の各byteを1tokenとした保守的な上限。未知単価も勝手に通さない。
    prepared = backstage_guard.with_instruction(dict(messages=[dict(role='user', content=prompt)]))
    input_bytes = sum(len(m['content'].encode('utf-8')) for m in prepared['messages'])
    bound = token_log.cost(model, input_bytes, MAX_OUTPUT_TOKENS)
    info = dict(model=model, max_input_bytes=MAX_INPUT_BYTES, max_output_tokens=MAX_OUTPUT_TOKENS,
                estimated_upper_usd=bound, actual_usd=0, calls=0)
    if not api_key or not token_log.allowed('sanity_recheck'):
        return [], dict(info, status='キーなし・日次上限')
    if (input_bytes > MAX_INPUT_BYTES or model not in token_log.PRICES
            or bound > MAX_COST_USD):
        return [], dict(info, status='短い入力・費用上限を超えるため機械照合のみ')
    try:
        import anthropic
        info.update(calls=1, actual_usd=None)
        response = backstage_guard.create_once(anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=20),
            label='sanity_recheck',
            **params, messages=[dict(role='user', content=prompt)])
        token_log.record('sanity_recheck', model, response)
        info.update(calls=1)
        usage = getattr(response, 'usage', None)
        info['actual_usd'] = token_log.cost(model, getattr(usage, 'input_tokens', 0) or 0,
                                           getattr(usage, 'output_tokens', 0) or 0)
        txt = ''.join(b.text for b in response.content if b.type == 'text')
        match = re.search(r'\[.*\]', txt, re.S)
        rows = json.loads(match[0]) if match else None
        if not isinstance(rows, list) or any(not isinstance(i, dict) or
                i.get('kind') not in (material.FACT, material.CONTEXT) for i in rows):
            raise ValueError('再点検の応答形式が不正')
        quotes = [i.get('where') or '' for i in issues]
        rows = [i for i in rows if i.get('where') and any(
            i['where'] in q or q in i['where'] for q in quotes if q)]
        return rows, dict(info, status='完了')
    except Exception as error:
        rejected = getattr(error, 'response', None)
        if rejected is not None and getattr(rejected, 'usage', None) is not None:
            token_log.record('sanity_recheck', model, rejected)
            info['actual_usd'] = token_log.cost(model, rejected.usage.input_tokens,
                                               rejected.usage.output_tokens)
        # 認証・料金・通信エラーを再試行しない。秘密を含みうる本文は保存しない。
        return [], dict(info, calls=1, status='取得失敗', error_type=type(error).__name__)


def run(documents, issues, materials, impossible, contradictions, api_key=''):
    """初回の全検査と、必要な場合の限定再検査の履歴を返す。"""
    import sanity_refresh
    first = dict(attempt=1, odd=issues, impossible=impossible, contradictions=contradictions,
                 materials=materials)
    attempts = [first]
    candidates = [i for i in issues if unresolved(i) or i.get('confirmed')]
    if not (candidates or impossible or contradictions):
        return issues, contradictions, materials, attempts
    targets = scoped(documents, issues, contradictions + impossible)
    refreshed, refresh_log = sanity_refresh.refresh(targets, materials)
    # 再取得後も指摘された行だけを照合する。行を特定できない入力不備は維持する。
    reviewed, errors = material.assess(issues, targets, refreshed)
    if not targets or refreshed == materials:
        # 行をまたぐ検算は、同じ材料で切り出し方を変えただけでは撤回しない。
        errors = list(dict.fromkeys(contradictions + errors))
    pending = [i for i in reviewed if unresolved(i)]
    ai, ai_info = (ai_review(targets, pending, refreshed, api_key) if pending and targets else
                   ([], dict(status='機械照合で決着', calls=0, actual_usd=0)))
    # 再点検のhighも同じ機械照合へ。初回の引用・severityは監査用に保持する。
    additions, _ = material.assess(ai, targets, refreshed)
    for issue in reviewed:
        issue['rechecked'] = True
        issue['recheck_findings'] = [a for a in additions if a.get('where') and
            (a['where'] in (issue.get('where') or '') or (issue.get('where') or '') in a['where'])]
        if unresolved(issue):
            issue['verification'] = ('材料不足・再点検後も未確認（材料が空・公開を止めない）'
                                     if issue.get('material_missing') else
                                     '再点検後も材料で未確認（当季情報・学習知識を根拠に止めない）'
                                     if re.search(r'今季|所属|移籍|順位|勝点|勝ち点|勝敗|成績|シーズン',
                                                  (issue.get('where') or '')+(issue.get('why') or ''))
                                     else '再点検後も未確認（材料・原稿内で誤りを確定できず）')
    internal = sanity_internal.check(documents)
    errors = list(dict.fromkeys(errors + internal))
    attempts.append(dict(attempt=2, lines=[dict(document_key=sources.key(d),
        lines=[s.get('_sanity_original_line') for s in d.get('segments') or []]) for d in targets],
        odd=reviewed, impossible=impossible, contradictions=errors,
        materials=refreshed, refresh=refresh_log, ai=ai_info))
    return reviewed, errors, refreshed, attempts
