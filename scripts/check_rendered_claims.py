"""Check the meanings of text drawn by production ranking cards, before upload.

No model/API calls. This checks renderer output against the supplied snapshot;
it is not OCR of the encoded movie or independent verification of every source.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from unittest.mock import patch


def drawn_rows(video, row_name, render):
    rows, text, active = [], [], []
    original_row = getattr(video, row_name)
    original_text = video.ImageDraw.ImageDraw.text

    def row(draw, y, item, *args, **kwargs):
        record = {'source': item, 'drawn': []}
        rows.append(record)
        active.append(record)
        try:
            return original_row(draw, y, item, *args, **kwargs)
        finally:
            active.pop()

    def draw_text(draw, xy, value, *args, **kwargs):
        text.append(str(value))
        if active:
            active[-1]['drawn'].append(str(value))
        return original_text(draw, xy, value, *args, **kwargs)

    with patch.object(video, row_name, row), patch.object(video.ImageDraw.ImageDraw, 'text', draw_text):
        render()
    return rows, text


def check_ps(data, expected_date, video=None):
    import generate_morning_short
    video = video or generate_morning_short
    errors, cards, scope = [], [], []
    if data.get('date') != expected_date:
        errors.append('PS資料の日付が公開対象日と不一致')
    phase = data.get('phase', 'regular')
    if phase == 'postseason' and data.get('series'):
        return errors, cards, ['シリーズの勝敗・勝ち上がり表示は別検査。今回の地区順位検査の対象外']
    if phase != 'regular':
        errors.append('PSの段階が不明、またはシリーズ資料が空')
    leagues = data.get('leagues') or {}
    if not leagues:
        errors.append('PS順位資料が空')
    champs = {}
    for lid, league in leagues.items():
        rows, words = drawn_rows(video, 'ps_row', lambda: video.render_ps_league(1, league, lid))
        cards.append({'league': lid, 'rows': rows, 'drawn': words})
        if not rows:
            errors.append(lid + ': 表示球団が空')
        for record in rows:
            team, drawn = record['source'], record['drawn']
            name = str(team.get('name') or team.get('id'))
            champion = team.get('div_champ') is True
            berth = champion or team.get('clinched') is True or team.get('wc_clinched') is True
            if '地区優勝' in drawn and not champion:
                errors.append(name + ': 地区優勝の根拠がないのに地区優勝と描画')
            if '決定' in drawn and not berth:
                errors.append(name + ': 進出未確定なのに決定と描画')
            if champion and '地区優勝' not in drawn:
                errors.append(name + ': 地区優勝が表示されていない')
            if berth and not champion and ('PS進出' not in drawn or '決定' not in drawn):
                errors.append(name + ': 進出確定と地区優勝が区別されていない')
            if team.get('div_rank') == 1 and 'ワイルドカード最後の枠' in drawn:
                errors.append(name + ': 地区首位を最後のWC枠と描画')
            if 'E' in drawn:
                errors.append(name + ': 敗退記号Eがゲーム差として露出')
            if (team.get('eliminated') or team.get('wc_gb') == 'E') and berth:
                errors.append(name + ': 敗退と進出確定の元データが矛盾')
            if champion and team.get('division'):
                key = (lid, str(team['division']))
                if key in champs and champs[key] != team.get('id'):
                    errors.append(name + ': 同一地区の優勝が複数')
                champs[key] = team.get('id')
            w, lost = team.get('w'), team.get('l')
            if not isinstance(w, int) or not isinstance(lost, int):
                errors.append(name + ': 勝敗不明をゼロ扱いできない')
            elif f'{w}勝{lost}敗' not in drawn:
                errors.append(name + ': 描画の勝敗と資料が不一致')
    scope.append('地区順位カードのみ。音声・翻訳・シリーズ表・公式API再照合は別検査')
    return errors, cards, scope


def check_soccer(data, expected_date, video=None):
    import generate_morning_short
    video = video or generate_morning_short
    errors, cards = [], []
    if data.get('date_jst') != expected_date:
        errors.append('サッカー資料の日付が公開対象日と不一致')
    picked = data.get('picked') or []
    comps = {c['code']: c for c in data.get('competitions', [])}
    if not picked:
        errors.append('対象大会が空')
    # Ranking data cannot prove a title/berth/relegation, or a player's goal.
    forbidden = re.compile(r'(?:優勝|出場|進出|降格|残留)(?:が)?(?:決定|確定)(?!ではありません|ではない|ではなく)')
    for code in picked:
        comp = comps.get(code)
        if not comp or comp.get('ready') is not True:
            errors.append(code + ': 大会資料が欠落または準備未完了')
            continue
        lines = (comp.get('lines') or [])[:video.LINES_PER_COMP]
        if not lines:
            errors.append(code + ': 順位の境界資料が空')
        for line in lines:
            rows, words = drawn_rows(video, 'race_row', lambda: video.render_race_line(1, comp, line))
            cards.append({'competition': code, 'rows': rows, 'drawn': words})
            if any(forbidden.search(s) for s in words):
                errors.append(code + ': 順位資料だけで優勝・出場等を確定扱い')
            inside, outside, boundary = line.get('inside') or [], line.get('outside') or [], line.get('at')
            if not isinstance(boundary, int) or boundary < 1:
                errors.append(code + ': 境界順位が不明')
            else:
                for side, items in [('inside', inside), ('outside', outside)]:
                    for item in items:
                        pos = item.get('position')
                        if not isinstance(pos, int) or ((pos <= boundary) != (side == 'inside')):
                            errors.append(code + ': 添字でなく公式positionで圏内外を判定する必要あり')
            if inside and outside:
                a, b = inside[-1].get('points'), outside[0].get('points')
                if not isinstance(a, int) or not isinstance(b, int) or line.get('diff') != a - b:
                    errors.append(code + ': 勝点差と境界のクラブの勝点が不一致')
            for record in rows:
                item, drawn = record['source'], record['drawn']
                if any(not isinstance(item.get(k), int) for k in ['position', 'points', 'gf', 'ga', 'played']):
                    errors.append(code + ': 不明な成績を0扱いできない')
                    continue
                required = [str(item['position']), str(item['points']), item.get('team', ''),
                            '得失点 %+d  %d試合' % (item['gf'] - item['ga'], item['played'])]
                if any(value not in drawn for value in required):
                    errors.append(code + ': 描画の順位・勝点・得失点・試合数が資料と不一致')
    _, intro = drawn_rows(video, 'race_row', lambda: video.render_race_intro(1, data, expected_date))
    _, japanese = drawn_rows(video, 'race_row', lambda: video.render_race_japanese(1, data))
    cards.append({'intro': intro, 'japanese': japanese})
    if '日本人選手のいるクラブ' not in japanese:
        errors.append('クラブ順位と選手個人成績の区別がない')
    if any(forbidden.search(s) for s in intro + japanese):
        errors.append('冒頭/日本人紹介で未確認の確定情報を表示')
    lead = video.race_lead(data)
    if lead and lead[0].get('out'):
        errors.append('欠場情報のある選手を冒頭の主役に選択')
    return errors, cards, ['順位カードと冒頭のみ。選手の出場/ゴール・正確な欧州出場枠・音声は別検査']


def audit(kind, path, expected_date, out):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    errors, cards, scope = {'postseason': check_ps, 'soccer_race': check_soccer}[kind](data, expected_date)
    report = {'kind': kind, 'expected_date': expected_date,
              'input_sha256': hashlib.sha256(raw).hexdigest(), 'errors': errors,
              'scope_limits': scope, 'cards': cards}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    message = f'{kind}: 描画の意味検査 エラー{len(errors)}件\n' + '\n'.join(errors)
    print(message)
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('\n### 公開前の描画検査\n' + message + '\n対象外: ' + ' / '.join(scope) + '\n')
    if errors:
        raise ValueError('描画の意味検査に失敗。公開を停止')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', required=True, choices=['postseason', 'soccer_race'])
    parser.add_argument('--input', required=True)
    parser.add_argument('--expected-date', default=datetime.now(timezone(timedelta(hours=9))).date().isoformat())
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    audit(args.kind, args.input, args.expected_date, args.out)
