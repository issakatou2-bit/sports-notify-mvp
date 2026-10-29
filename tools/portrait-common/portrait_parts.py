"""キャラ共通の部品指定。素材・既定値・組・制約は parts.json を正本にする。"""
import copy
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIASES = dict(eye='目', brow='眉', mouth='口', arm_back='右腕', arm_front='左腕')
LEGACY = {
    'neutral': ('開', '基本', '閉', '基本', '基本'),
    'smile': ('笑', '基本', '笑', '基本', '基本'),
    'surprise': ('見開', '上げ', '大', '基本', '基本'),
    'jito': ('ジト', '基本', '閉', '基本', '基本'),
    'komari': ('開', '困り', '閉', '基本', '基本'),
    'think': ('ジト', '基本', '閉', '考え', '基本'),
    'hirameki': ('見開', '上げ', '笑', '上げ', '基本'),
    'doya': ('笑', '上げ', '笑', '基本', '基本'),
    'akire': ('ジト', '困り', '閉', '基本', '基本'),
    'point': ('開', '基本', '閉', '指', '基本'),
}
NEW_REACTIONS = frozenset('heart kirakira konran pinch gaan tere aseri zannen chui gutsu yobikake setsumei udegumi jishin mic kasa'.split())
MIN_HOLD = 1.2  # 秒。口パク・既存の瞬きは表情の切替に数えない。


def directory(who, data=None):
    if who in ('zunda', 'zundamon', 'metan'):
        return ROOT / 'assets/portraits' / ('四国めたん' if who == 'metan' else 'ずんだもん')
    import guest_config
    spec = guest_config.guests_of(data or {}).get(who) or guest_config.LOCAL_CHARACTERS.get(who)
    if not spec or spec.get('portrait') != 'parts':
        raise ValueError(f'部品式のキャラではありません: {who}')
    return ROOT / spec['dir']


def normalize(raw, who=''):
    """既存21部品のマニフェストも読める。元ファイルは書き換えない。"""
    m = copy.deepcopy(raw)
    m.setdefault('parts', {k: raw.get(k, raw.get(j, {})) for k, j in ALIASES.items()})
    for k in ('cheek', 'fx', 'head', 'outfit'):
        if k in raw:
            m['parts'].setdefault(k, raw[k])
    m.setdefault('base', raw.get('体'))
    m.setdefault('order', ['base', 'arm_back', 'arm_front', 'cheek', 'brow', 'eye', 'mouth', 'fx', 'head', 'outfit'])
    m.setdefault('defaults', dict(eye='開', brow='基本', mouth=['閉', '開', '大'], arm_back='基本', arm_front='基本', fx=[]))
    m.setdefault('presets', {})
    if not all(j in raw for j in ALIASES.values()):
        # 新しい共通形式だけの素材では、古い日本語の部品名を作り足さない。
        m['presets'].setdefault('neutral', {})
        m.setdefault('rules', [])
        return m
    for name, values in LEGACY.items():
        face = dict(zip(('eye', 'brow', 'mouth', 'arm_back', 'arm_front'), values))
        face['mouth'] = [values[2], '開', '大']
        arms = raw.get('expression_arms', {}).get(name)
        if arms:
            face['arm_back'], face['arm_front'] = arms
        elif name == 'think' and who == 'metan':
            face.update(arm_back='基本', arm_front='考え')
        m['presets'].setdefault(name, face)
    m.setdefault('rules', [])
    return m


@lru_cache(maxsize=24)
def load(folder, who=''):
    folder = Path(folder).resolve()
    return normalize(json.loads((folder / 'parts.json').read_text(encoding='utf-8')), who)


def values(value):
    return value if isinstance(value, list) else [] if value is None else [value]


def matches(face, condition):
    return all(bool(set(values(face.get(k))) & set(values(v))) for k, v in condition.items())


def resolve(m, expr='neutral', face=None, pose=None):
    if face is not None and not isinstance(face, dict):
        raise ValueError('face は部品名をキーにした辞書です')
    if expr not in m['presets']:
        raise ValueError(f'知らない表情名: {expr}')
    result = copy.deepcopy(m['defaults'])
    result.update(copy.deepcopy(m['presets'][expr]))
    if pose:
        if pose not in m['presets']:
            raise ValueError(f'知らないポーズ名: {pose}')
        result.update({k: v for k, v in m['presets'][pose].items() if k.startswith('arm_')})
    result.update(copy.deepcopy(face or {}))
    unknown = set(result) - set(m['parts'])
    # fx=[] は旧マニフェストでも共通の既定値。
    unknown -= {k for k in unknown if result[k] == []}
    if unknown:
        raise ValueError(f'知らない部品の種類: {sorted(unknown)}')
    for k, v in result.items():
        seq = values(v)
        if not all(isinstance(x, str) for x in seq):
            raise ValueError(f'{k}: 部品名は文字列です')
        if k == 'mouth' and isinstance(v, list) and len(v) != 3:
            raise ValueError('mouth は閉/開/大の3部品です')
        if k.startswith('arm_') and len(seq) > 1:
            raise ValueError(f'{k}: 同じ腕の重複です')
        if k in ('brow', 'head', 'outfit') and len(seq) > 1 or k == 'eye' and not m.get('white_variants') and len(seq)>1:
            raise ValueError(f'{k}: 組めない部品です')
        if k != 'mouth' and len(seq) != len(set(seq)):
            raise ValueError(f'{k}: 部品の重複です')
        for x in seq:
            if x not in m['parts'].get(k, {}):
                raise ValueError(f'存在しない部品: {k}={x}')
    for rule in m['rules']:
        if not isinstance(rule, dict) or set(rule) - {'when', 'hide', 'requires', 'exclusive', 'default', 'message', 'reject'}:
            raise ValueError('未対応の parts.json rules（黙って無視しません）')
        if rule.get('when') and not matches(result, rule['when']):
            continue
        if rule.get('reject') is True:
            raise ValueError(rule.get('message', '組めない部品です'))
        for k, groups in rule.get('exclusive', {}).items():
            for group in groups:
                if len(set(values(result.get(k))) & set(group)) > 1:
                    raise ValueError(rule.get('message', f'{k}: 組めない部品です'))
        for k, choices in rule.get('requires', {}).items():
            if not set(values(result.get(k))) & set(values(choices)):
                raise ValueError(rule.get('message', f'{k}: 組み合わせに必要な部品がありません'))
        for k, v in rule.get('default', {}).items():
            # 目の黒目だけを選んだとき、白目基本を補う。
            if not any(x in values(result.get(k)) for x in m.get('white_variants', [])):
                result[k] = values(v) + values(result.get(k))
        for k in rule.get('hide', []):
            result[k] = []
    return result


def files(m, resolved, mouth=0, blink=False):
    for part in m['order']:
        if part == 'base':
            if m.get('base'):
                yield m['base']
            continue
        selected = resolved.get(part, [])
        if part == 'mouth':
            selected = values(selected)
            selected = selected[min(mouth, len(selected)-1):min(mouth, len(selected)-1)+1]
        elif part == 'eye' and blink:
            selected = m.get('blink', '閉')
        for name in values(selected):
            item = m['parts'][part][name]
            for filename in values(item):
                yield filename


class Composer:
    def __init__(self, folder, who=''):
        self.folder = Path(folder).resolve()
        self.manifest = load(str(self.folder), who)
        self.cache = {}

    def image(self, expr='neutral', face=None, pose=None, mouth=0, blink=False):
        from PIL import Image
        m = self.manifest
        selected = resolve(m, expr, face, pose)
        canvas = Image.new('RGBA', tuple(m['size']))
        for filename in files(m, selected, mouth, blink):
            path = (self.folder / filename).resolve()
            if not path.is_relative_to(self.folder):
                raise ValueError('部品のパスが素材フォルダーの外です')
            if filename not in self.cache:
                with Image.open(path) as art:
                    if list(art.size) != list(m['size']):
                        raise ValueError(f'部品のキャンバスサイズ不一致: {filename}')
                    self.cache[filename] = art.convert('RGBA')
            canvas.alpha_composite(self.cache[filename])
        return canvas


def line_selection(m, line, me=True, active=True):
    pose = line.get('pose' if me else 'listen_pose') if me or active else None
    if isinstance(pose, str) and pose.startswith('pose_'):
        pose = None
    return resolve(m, (line.get('expr' if me else 'listen') if me or active else None) or 'neutral',
                   line.get('face' if me else 'listen_face') if me or active else None,
                   pose)


def catalog(data):
    import guest_config
    actors = set(data.get('cast') or ('metan', 'zundamon')) | {l.get('who') for l in data.get('lines', [])}
    return {who: load(str(directory(who, data)), who) for who in actors if who and
            (who in ('metan', 'zundamon') or guest_config.guests_of(data).get(who, {}).get('portrait') == 'parts')}


def custom_enabled(data):
    if any('face' in l or 'listen_face' in l for l in data.get('lines', [])):
        return True
    try:
        new = set().union(*(set(m['presets'])-set(LEGACY) for m in catalog(data).values()))
    except (ValueError, OSError):
        new = NEW_REACTIONS
    return any(isinstance(l.get(k), str) and l[k] in new for l in data.get('lines', []) for k in ('expr','listen','pose','listen_pose'))


def inspect(data, times=None):
    """描画前の部品検査。新指定は旗offでも無視せず検査する。"""
    issues = []
    try:
        manifests = catalog(data)
    except (ValueError, OSError) as e:
        return [dict(code='face_parts', line=1, message=str(e))]
    last, changed = {}, {}
    custom = custom_enabled(data)
    for i, line in enumerate(data.get('lines', [])):
        if not line.get('who'):
            continue
        for who, m in manifests.items():
            me = who == line['who']
            # 旧台本は既存検査を維持。新顔・直接指定を使用した動画は全状態を検査。
            if not custom:
                continue
            try:
                selected = line_selection(m, line, me)
                # 実ファイルの存在・パスも描画前に確認。
                folder = directory(who, data).resolve()
                all_files = {name for mouth in range(3) for blink in (False, True) for name in files(m, selected, mouth, blink)}
                for name in all_files:
                    p = (folder / name).resolve()
                    if not p.is_relative_to(folder) or not p.is_file():
                        raise ValueError(f'部品ファイルがありません: {name}')
                loud = set(m.get('emphatic_eyes', [])) & set(values(selected.get('eye')))
                scene = (data.get('scenes') or {}).get(line.get('scene'), {})
                factual = line.get('study_fact') is True or line.get('fact') is True or line.get('section') in ('answer', 'choices', 'news') or scene.get('type') in ('quiz', 'flow', 'compare')
                unusual = set(m.get('eye_moods', {}).get('非平時', [])) & set(values(selected.get('eye')))
                if unusual and (factual or not me or line.get('eye_context') not in ('異変', '不穏', '呆然', '夢うつつ', '催眠・洗脳', '事件簿の不気味な場面')):
                    raise ValueError('非平時の目は事実・聞き手・普段の行に使えません。該当する場面を eye_context に明記してください')
                if loud and (factual or not me):
                    raise ValueError('勉強の事実の行・聞き手には目立つ目を使いません')
                if not me:
                    for part, allowed in m.get('listener_quiet', {}).items():
                        if set(values(selected.get(part))) - set(allowed):
                            raise ValueError('聞き手の変化が大きすぎます: '+part)
                signature = json.dumps(selected, ensure_ascii=False, sort_keys=True)
                at = times[i] if times else line.get('start')
                if signature != last.get(who):
                    if at is not None and who in changed and at-changed[who] < m.get('min_hold_seconds', MIN_HOLD)-1e-6:
                        raise ValueError('表情の保持が1.2秒未満です（速い切替）')
                    if at is not None:
                        changed[who] = at
                last[who] = signature
            except (ValueError, KeyError, TypeError) as e:
                issues.append(dict(code='face_parts', line=i+1, who=who, message=str(e)))
    return issues


def usage(data):
    """行の選択回数。口の3段階は指定回数、実コマ数とは区別する。"""
    from collections import Counter
    result = {}
    for who, m in catalog(data).items():
        counts = Counter()
        for line in data.get('lines', []):
            if line.get('who'):
                for k, v in line_selection(m, line, line['who'] == who).items():
                    counts.update(f'{k}:{x}' for x in set(values(v)))
        result[who] = dict(sorted(counts.items()))
    return result


def record_usage(data, destination):
    from datetime import datetime, timezone
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = dict(id=data.get('id'), publish_at=data.get('publish_at'), recorded_at=datetime.now(timezone.utc).isoformat(), unit='行ごとの選択回数（口3段階は指定回数）', parts=usage(data))
    record['available_parts'] = {who: {k: list(v) for k,v in m.get('coverage', m['parts']).items()}
                                 for who,m in catalog(data).items()}
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return record
