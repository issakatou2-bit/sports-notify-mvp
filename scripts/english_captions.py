"""任意の英語字幕。共有API枠が不明なら送らない。秘密・原稿は台帳に残さない。"""
import json
import math
import os
import pathlib
import re
import unicodedata
from collections import Counter
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

import backstage_guard
import caption_names
import captions
import llm_models
import token_log

COST_LIST = 50
COST_INSERT = 400
SNAPSHOT_TTL = 300


def quota_date(now):
    """YouTube resets at Pacific midnight; US DST rules since 2007, without host tzdata.

    Second Sunday of March at 10:00 UTC through first Sunday of November at 09:00 UTC.
    """
    march = datetime(now.year, 3, 1, 10, tzinfo=timezone.utc)
    start = march + timedelta(days=(6-march.weekday()) % 7 + 7)
    november = datetime(now.year, 11, 1, 9, tzinfo=timezone.utc)
    end = november + timedelta(days=(6-november.weekday()) % 7)
    offset = -7 if start <= now < end else -8
    return now.astimezone(timezone(timedelta(hours=offset))).date().isoformat()


def utcnow():
    return datetime.now(timezone.utc)


def load_state(path):
    p = pathlib.Path(path)
    if not p.exists():
        return {'events': []}
    state = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(state.get('events'), list):
        raise ValueError('invalid state')
    return state


def save_event(path, state, video, status, *, units=0, now=None):
    now = now or utcnow()
    event = dict(at=now.isoformat(), day=now.astimezone(timezone(timedelta(hours=9))).date().isoformat(),
                 video_id=video, status=status, units=units)
    state['events'].append(event)
    # Keep enough history to reconcile a fresh snapshot and daily attempts.
    state['events'] = state['events'][-2000:]
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tmp.replace(p)
    message = f'[info] 英語字幕: {status} ({video or "動画未取得"})'
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(message+'\n')


def quota_snapshot(env):
    """Read a fresh shared quota observation at each attempt, not only job startup."""
    url = env.get('YOUTUBE_SHARED_QUOTA_URL') or ''
    if not url:
        return json.loads(env.get('YOUTUBE_SHARED_QUOTA_SNAPSHOT') or '{}')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('invalid quota URL')
    import requests
    token = env.get('YOUTUBE_SHARED_QUOTA_TOKEN') or ''
    headers = {'Authorization': 'Bearer '+token} if token else {}
    response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
    response.raise_for_status()
    return response.json()


def budget_reason(state, video, env=None, now=None):
    env = os.environ if env is None else env
    now = now or utcnow()
    day = now.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    try:
        cap = int(env.get('COLLESPO_EN_CAPTIONS_DAILY_MAX') or '1')
        reserve = int(env.get('COLLESPO_EN_CAPTIONS_RESERVE') or '1000')
        if cap < 0 or reserve < 0:
            raise ValueError()
    except ValueError:
        return 'invalid_limits'
    attempts = [e for e in state['events'] if e['day'] == day and e['status'] == 'insert_reserved']
    if any(e['video_id'] == video for e in attempts):
        return 'already_attempted'
    if len(attempts) >= cap:
        return 'daily_limit'
    if not (env.get('YOUTUBE_SHARED_QUOTA_URL') or env.get('YOUTUBE_SHARED_QUOTA_SNAPSHOT')):
        # 共有の残りを知る窓口が無いときは、1日の上限本数（既定1本＝400ユニット、1日1万の4%）の
        # 範囲でだけ付ける。窓口が無いだけで毎回見送ると、オンにしても1本も付かない（10/14 本人の確認）。
        # 枠切れの 403 は投稿の失敗として記録され、次の日まで付けない。
        return ''
    try:
        snap = quota_snapshot(env)
        seen = datetime.fromisoformat(snap['observed_at'].replace('Z', '+00:00'))
        remaining = snap['remaining_units']
        if seen.tzinfo is None or isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
            raise ValueError()
        if not math.isfinite(remaining) or not 0 <= remaining <= 10000:
            raise ValueError()
        age = (now - seen).total_seconds()
        if not 0 <= age <= SNAPSHOT_TTL:
            return 'quota_snapshot_stale'
        if snap['quota_date'] != quota_date(now):
            return 'quota_day_mismatch'
        used = sum(e['units'] for e in state['events'] if datetime.fromisoformat(e['at']) >= seen)
        if remaining - used < COST_LIST + COST_INSERT + reserve:
            return 'quota_insufficient'
    except Exception:
        return 'quota_unknown'
    return ''


class TranslationRejected(ValueError):
    """診断用の応答は属性に保持。通常ログ・例外文字列には本文を含めない。"""
    def __init__(self, code, original, english):
        super().__init__(code)
        self.original, self.english = original, english


def translate(cues, ai):
    source = [text for _, _, text in cues]
    if any(backstage_guard.violations(text) for text in source):
        raise ValueError('backstage_source')
    prompt = ('Translate each Japanese caption to English. Return ONLY a JSON array of strings, '
              'one per input cue in exactly the same order. Do not merge or split cues. '
              'Keep facts, numbers, speakers, and quotation attribution; add no claims or explanations. '
              'Preserve every count, ordinal and calendar day explicitly, preferably with digits: '
              'In baseball headlines, 1号 means the first home run (not merely a solo homer), '
              '1安打 means one hit and 1回 means the first inning. 第1戦 means Game 1. '
              '一発 means one homer/a homer; 1番 as a batting-order position means leadoff/top of the order. '
              '21日 means the 21st: never replace a calendar day with a month, weekday or relative date, '
              'and never infer a month absent from the source. Do not shorten away numeric details. '
              'Use the full official spellings in this canonical name table wherever those names occur. '
              'Other player names must use MLB official English spellings. No markdown.\n'
              + json.dumps({ja: name for text in source for ja, name in caption_names.required(text).items()}, ensure_ascii=False) + '\nINPUT:\n'
              + json.dumps(source, ensure_ascii=False))
    if not token_log.allowed('translate'):
        raise ValueError('translation_budget')
    response = backstage_guard.create(ai, label='english_captions.py', category='translate', mode='whole',
                                     **llm_models.params('translate', max(1600, len(source)*180)),
                                     messages=[{'role': 'user', 'content': prompt}])
    token_log.record('translate', llm_models.model('translate'), response)
    if response.stop_reason == 'max_tokens':
        raise ValueError('translation_truncated')
    result = json.loads(backstage_guard.response_text(response))
    if not isinstance(result, list) or len(result) != len(cues):
        raise ValueError('translation_count')
    for original, english in zip(source, result):
        if isinstance(english, str) and not english.strip():
            raise TranslationRejected('translation_empty',original,english)
        if isinstance(english, str) and backstage_guard.violations(english):
            raise TranslationRejected('translation_backstage',original,english)
        if (not isinstance(english, str) or not english.strip() or len(english) > 1000
                or re.search(r'[\u3040-\u30ff\u3400-\u9fff]', english)
                or backstage_guard.violations(english)):
            raise TranslationRejected('translation_invalid',original,english)
        if any(name not in english for name in caption_names.required(original).values()):
            raise TranslationRejected('translation_names',original,english)
        missing, extra = number_mismatches(original, english)
        if missing or extra:
            # 原稿やモデルの応答を出さず、照合で余った数字だけを残す。
            print(f'[warn] 英語字幕: translation_numbers Japanese={missing} English={extra}')
            raise TranslationRejected('translation_numbers',original,english)
    return [(start, end, text.strip()) for (start, end, _), text in zip(cues, result)]



_MONTHS = {
    name: str(number)
    for number, names in enumerate(('january jan', 'february feb', 'march mar', 'april apr',
                                   'may', 'june jun', 'july jul', 'august aug',
                                   'september sep sept', 'october oct', 'november nov',
                                   'december dec'), 1)
    for name in names.split()
}
_CARDINALS = ('zero one two three four five six seven eight nine ten eleven twelve thirteen '
              'fourteen fifteen sixteen seventeen eighteen nineteen').split()
_ORDINALS = ('zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh '
             'twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth').split()
_TENS = 'twenty thirty forty fifty sixty seventy eighty ninety'.split()
_TENTHS = 'twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth'.split()
_WORD_VALUES = {word: n for words in (_CARDINALS, _ORDINALS) for n, word in enumerate(words)}
_WORD_VALUES.update({word: n * 10 for words in (_TENS, _TENTHS)
                     for n, word in enumerate(words, 2)})
_UNIT_WORDS = '|'.join(_CARDINALS[1:10] + _ORDINALS[1:10])
_UNDER_HUNDRED = ('(?:' + '|'.join(_TENS) + r')(?:[\s-]+(?:' + _UNIT_WORDS + '))?'
                  + '|' + '|'.join(_WORD_VALUES))
_WORD_NUMBERS = re.compile(r'\b(?:'
    + '(?:' + '|'.join(_CARDINALS[1:10]) + r')[\s-]+hundred(?:[\s-]+(?:and[\s-]+)?(?:'
    + _UNDER_HUNDRED + '))?|' + _UNDER_HUNDRED + r')\b', re.IGNORECASE)
_COUNT_NOUN = r'(?:home runs?|runs?|hits?|singles?|walks?|strikeouts?|wins?|loss(?:es)?|outs?|homers?|innings?|goals?)'
_FRACTION_WORD = r'(?:third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)'


def _word_number(match):
    words = re.split(r'[\s-]+', match.group().lower())
    if 'hundred' in words:
        return str(_WORD_VALUES[words[0]] * 100
                   + sum(_WORD_VALUES[w] for w in words[2:] if w != 'and'))
    return str(sum(_WORD_VALUES[w] for w in words))


def _japanese_number_text(text):
    # 人名（一平・十亀）や熟語（一方・統一・二刀流）の文字を数にしない。
    digits={word:str(n) for n,word in enumerate('〇一二三四五六七八九')}
    def convert(match):
        word=match.group()
        if word.count('十')>1:return word
        if '十' in word:
            tens,ones=word.split('十')
            if len(tens)>1 or len(ones)>1:return word
            return str(int(digits.get(tens,'1'))*10+int(digits.get(ones,'0')))
        return ''.join(digits[c] for c in word)
    numeral=r'[〇一二三四五六七八九十]+'
    units=r'(?:打席|打数|打点|安打|本塁打|四球|奪三振|盗塁|得点|失点|アシスト|連勝|連敗|連発|試合|発|本|点|戦|回|人|番|勝|敗|塁|死|日|月|年|分|秒|度|号|対)'
    return re.sub(r'(?<![〇零一二三四五六七八九十百千万億\d])'+numeral+r'(?='+units+r')'
                  + r'|(?<![一-龯\w])'+numeral+r'(?![一-龯\w])',convert,text)


def number_mismatches(original, english):
    """数の表記と語順をそろえ、日本語側・英語側に余る数字だけを返す。

    序数（first / 3rd）・点数（two-run / 6-2）・分数（one third / 1/3）も
    数字として数える。同じ数字の出現回数も一致させ、増減・脱落を見逃さない。
    """
    original = _japanese_number_text(unicodedata.normalize('NFKC', original))
    english = unicodedata.normalize('NFKC', english).lower()
    # 打順だけの同義語。first inningや単なるtopには足さない。
    if re.search(r'(?<!\d)1番',original):
        english = re.sub(r'\blead[ -]?off\b|\btop of (?:the )?(?:batting )?order\b', '1', english)
    if re.search(r'初|(?<!\d)1(?:回|戦)',original):
        # opening inning / series opener も「初回」「第1戦」と同じ1。
        english = re.sub(r'\bopening(?=\s+(?:inning|game|pitch|round|day)\b)', 'first', english)
        english = re.sub(r'\bopener\b', 'first game', english)
    japanese_firsts = len(re.findall(r'初めて|最初|(?<![当最])初(?![期心級旬頭夏秋冬春])', original))
    matched_firsts = min(japanese_firsts, len(re.findall(r'\b(?:first|1st)\b', english)))
    # 「44年ぶり」は "first ... in 44 years" とも訳す。ここでのfirstは
    # 日本語に独立した1がなくても同じ意味（年数自体は通常どおり照合する）。
    first_after_gap = len(re.findall(r'\b(?:first|1st)\b[^.!?;]{0,120}?\b(?:in|for)\s+'
                                    r'(?:\d+|'+_UNDER_HUNDRED+r')\s+(?:years?|days?|games?|matches?|plate appearances?)\b', english))
    # a goal / a hitは1。ただし分数の単位（of an inning）は別の1ではない。
    counted_articles = len(re.findall(r'\b(?:a|an)\s+(?:(?:earned|unearned)\s+)?'
                                     + _COUNT_NOUN + r'\b', english))
    counted_articles -= len(re.findall(r'\b(?:' + _FRACTION_WORD + r's?|\d+/\d+)\s+of\s+an\s+inning\b', english))
    # a third の分子とno/scorelessの0は、明示された数の不足だけを補う。
    implicit = {
        '1': len(re.findall(r'\ba\s+' + _FRACTION_WORD + r'\b', english)),
        '0': len(re.findall(r'\bno\s+(?:earned\s+)?' + _COUNT_NOUN
                            + r'\b|\bscoreless\b', english)),
    }
    english = re.sub(r'\b(one|two|three|four|five|six|seven|eight|nine|\d+)[\s-]+('
                     + _FRACTION_WORD + r')s\b', r'\1 \2', english)
    if re.search(r'\d{1,2}[月日]', original):
        def month_number(match):
            word=match.group()
            if (word in ('may','march') and not re.search(r'\d{1,2}月',original)
                    and not re.match(r'\s+\d',english[match.end():])
                    and not re.search(r'\b(?:in|of|on)\s*$',english[:match.start()])):
                return word  # 助動詞may・動詞marchを月として足さない。
            return _MONTHS[word]
        english = re.sub(r'\b(?:' + '|'.join(_MONTHS) + r')\b',
                         month_number, english)
    english = _WORD_NUMBERS.sub(_word_number, english)
    pattern = r'\d+(?:[.,]\d+)?'
    want = Counter(re.findall(pattern, original))
    have = Counter(re.findall(pattern, english))
    # 「最初」をa hitの冠詞で埋めないよう、対応するfirstは先に取り出す。
    want['first'] = japanese_firsts
    have['first'] = matched_firsts
    have['1'] += counted_articles - matched_firsts
    # 無失点・無安打のようなゼロも、英訳が明示的にzeroと書いた分だけ照合する。
    want['0'] += min(max(0, have['0'] - want['0']),
                     len(re.findall(r'無(?:失点|安打|四球|得点|本塁打)', original)))
    # 「64日ぶり」「26試合ぶり」もfirst ... inと同義。数字自体は通常照合。
    want['1'] += min(max(0, have['1'] - want['1']), first_after_gap,
                     len(re.findall(r'\d+(?:年|日|試合|戦|打席)ぶり', original)))
    # 「開幕2連勝」のfirst 2 matchesは、独立した第1戦の追加ではない。
    opening_wins=re.findall(r'開幕(\d+)連勝',original)
    for count in opening_wins:
        if re.search(r'\b1\s+'+re.escape(count)+r'\b(?:\s+[a-z]+){0,3}\s+(?:games?|matches?)\b',english):
            want['1'] += min(max(0,have['1']-want['1']),1)
    for number, count in implicit.items():
        have[number] += min(max(0, want[number] - have[number]), count)
    return tuple(sorted('1' if n == 'first' else n for n in difference.elements())
                 for difference in (want - have, have - want))


def numbers_survive(original, english):
    """英語の数字・数詞・序数を、日本語の数字と出現回数まで照合する。"""
    return not any(number_mismatches(original, english))

def find_video(args):
    if args.kind == 'daily':
        # upload_youtube records this key in UTC, even though the daily slot is JST.
        return captions.video_id_for('daily', args.date or utcnow().date().isoformat(), args.record)
    if args.kind == 'asset' and args.asset_topic.startswith('season_game_'):
        record = json.loads(pathlib.Path(args.record).read_text(encoding='utf-8'))
        row = (record.get('assets') or {}).get(args.asset_topic) or {}
        return row.get('video_id') or ''
    return ''


def main(args):
    if os.environ.get('COLLESPO_EN_CAPTIONS') != 'on':
        print('[info] 英語字幕はoffです')
        return 0
    state = None
    video = ''
    try:
        state = load_state(args.state)
        if args.kind != 'daily' and not (args.kind == 'asset' and args.asset_topic.startswith('season_game_')):
            save_event(args.state, state, video, 'unsupported_kind')
            return 0
        video = find_video(args)
        if not video and not args.out:
            save_event(args.state, state, video, 'video_missing')
            return 0
        if any(e['video_id'] == video and e['status'] in ('inserted', 'already_present') for e in state['events']) and not args.out:
            save_event(args.state, state, video, 'already_recorded')
            return 0
        reason = budget_reason(state, video)
        if reason and not args.out:
            save_event(args.state, state, video, reason)
            return 0
        narration = json.loads(pathlib.Path(args.narration).read_text(encoding='utf-8'))
        manifest = json.loads((pathlib.Path(args.audio_dir)/'manifest.json').read_text(encoding='utf-8'))['segments']
        cues = captions.build_cues(narration, manifest)
        if not cues:
            save_event(args.state, state, video, 'empty_script')
            return 0
        yt = None
        if not args.out:
            yt = captions.client()
            if yt is None:
                save_event(args.state, state, video, 'oauth_missing')
                return 0
            # Reserve even failed requests; do not spend units on retries.
            save_event(args.state, state, video, 'list_reserved', units=COST_LIST)
            have = yt.captions().list(part='snippet', videoId=video).execute()
            if any(i.get('snippet', {}).get('language') == 'en' and i['snippet'].get('name') == 'Collespo' for i in have.get('items', [])):
                save_event(args.state, state, video, 'already_present')
                return 0
        import anthropic
        srt = captions.render_srt(translate(cues, anthropic.Anthropic()), english=True)
        if args.out:
            p = pathlib.Path(args.out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(srt, encoding='utf-8')
            print(f'[info] 英語SRTを書き出しました: {p}')
            return 0
        # Recheck freshness/budget after translation; list units have already been reserved.
        reason = budget_reason(state, video)
        if reason:
            save_event(args.state, state, video, reason)
            return 0
        from googleapiclient.http import MediaFileUpload
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)/'en.srt'
            p.write_text(srt, encoding='utf-8')
            save_event(args.state, state, video, 'insert_reserved', units=COST_INSERT)
            media = MediaFileUpload(str(p), mimetype='application/octet-stream')
            try:
                yt.captions().insert(part='snippet', body={'snippet': {'videoId': video, 'language': 'en',
                    'name': 'Collespo', 'isDraft': False}}, media_body=media).execute()
            finally:
                media.stream().close()
        save_event(args.state, state, video, 'inserted')
    except Exception as exc:
        # Never dump OAuth/HTTP objects or model responses into public records.
        known = {'backstage_source', 'translation_budget', 'translation_truncated', 'translation_count',
                 'translation_invalid', 'translation_names', 'translation_numbers',
                 'translation_empty', 'translation_backstage'}
        status = str(exc) if isinstance(exc, ValueError) and str(exc) in known else 'failed_' + type(exc).__name__
        if getattr(getattr(exc, 'resp', None), 'status', None) == 403:
            status = 'forbidden_check_scope_or_quota'
        if state is not None:
            save_event(args.state, state, video, status)
        else:
            print('[warn] 英語字幕: state_unreadable（送信なし）')
    return 0
