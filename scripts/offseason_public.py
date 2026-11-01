"""予定・賞・移籍だけの投稿文。ほかの資産動画の型は変更しない。"""
import re

KINDS = {'schedule', 'awards', 'transactions'}


def caption_phrases(text):
    import caption_breaks
    # 既存モデルが1文節にする長い複合語は、語境界の中黒だけで分ける。
    return tuple(part for atom in caption_breaks.phrases(text)
                 for part in re.split(r'(?<=クオリファイング・)(?=オファー)', atom) if part)


def applies(spec):
    return isinstance(spec.get('offseason'), dict) and spec['offseason'].get('kind') in KINDS


def social_kind(kind):
    return bool(re.fullmatch(r'asset_offseason_(?:schedule|awards|transactions)_\d{4}_[a-f0-9]+', kind))


def metadata(spec):
    label = spec.get('heading') or spec['label']
    lead = [label + 'を、MLB公式の記録から紹介します。', '']
    if spec.get('intro'):
        lead += [spec['intro'], '']
    lead += [f'・{head}　{body}' for head, body in spec.get('items', [])]
    lead += ['', '出典: ' + spec.get('source', 'MLB公式')]
    if spec.get('source_url'):
        lead.append(spec['source_url'])
    # 連載は見出しが「第N回」だけなので、題は選手名と動きが入った label を使う。
    series = spec['offseason'].get('series_number')
    return dict(title=f'【MLB】{spec["label"] if series else label} #Shorts', lead=lead,
                tags=['MLB', 'メジャーリーグ', '野球', 'コレスポ'])


def voice_credit(narration):
    """保存音声の解決結果・実話者を優先し、無関係な話者を足さない。"""
    from ui_voice_queue import UI_CREDIT
    resolution = narration.get('voice_resolution') or {}
    if resolution.get('audio_available') is False or resolution.get('host') not in (None, 'metan', 'ui'):
        raise ValueError('保存音声の実話者を確認できません')
    if resolution.get('host') == 'ui':
        return UI_CREDIT
    segments = narration.get('segments') or []
    credits = []
    for segment in segments:
        host = resolution.get('host') or segment.get('voice_host')
        if host == 'ui':
            name = UI_CREDIT
        else:
            speaker = int(segment.get('speaker', 2))
            name = {2: 'VOICEVOX:四国めたん', 3: 'VOICEVOX:ずんだもん',
                    108: 'VOICEVOX:東北きりたん'}[speaker]
        if name not in credits:
            credits.append(name)
    if not credits:
        raise ValueError('オフ話題の音声表記には保存原稿の話者が必要です')
    return ' / '.join(credits)


def saved_voice(narration, receipt, video_digest):
    if not receipt.get('voice_resolution'):
        return narration
    if not video_digest or receipt.get('video_sha256') != video_digest:
        raise ValueError('音声の受領記録と動画が一致しません')
    return dict(narration, voice_resolution=receipt['voice_resolution'])


def description_voice(description):
    from ui_voice_queue import UI_CREDIT
    for line in description.splitlines():
        if line.strip() == UI_CREDIT:
            return UI_CREDIT
        if line.startswith(('音声: ', '音声：')):
            return line.removeprefix('音声: ').removeprefix('音声：').strip()
    raise ValueError('オフ話題の説明欄に音声表記がありません')
