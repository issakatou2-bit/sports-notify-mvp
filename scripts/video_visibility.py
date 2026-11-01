"""台帳の公開状態を読む。予約の経過時刻と非公開保留を混ぜない。"""
import json
import pathlib
from datetime import datetime, timezone


def publish_time(entry):
    value=entry.get('publish_at')
    if not value:
        return None
    try:
        when=datetime.fromisoformat(value.replace('Z','+00:00'))
        if when.tzinfo is None:
            return False
        return when
    except (ValueError,AttributeError,TypeError):
        return False


def is_scheduled(entry, now=None):
    when=publish_time(entry)
    return bool(when and when > (now or datetime.now(timezone.utc)))


def exclusion_reason(entry, now=None):
    if not isinstance(entry,dict) or not entry.get('video_id'):
        return '動画IDなし'
    if entry.get('held') or entry.get('hold') or entry.get('status') in ('held','hold','private','unlisted','deleted','failed'):
        return '保留/非公開/削除/失敗の記録'
    privacy=entry.get('privacy') or entry.get('privacyStatus')
    if privacy and privacy not in ('private','public'):
        return '公開対象でない公開設定'
    when=publish_time(entry)
    if when is False:
        return '予約日時の記録が不正'
    if when and when > (now or datetime.now(timezone.utc)):
        return '予約時刻前'
    if privacy=='private' and not when:
        return '非公開保留'
    # 過去のprivacy無しの台帳を維持。正当な予約は従来どおり時刻経過で表示。
    # 予約の実公開や、台帳に残らない過去の手動変更は別の照合が必要。
    return None


def is_public(entry, now=None):
    return exclusion_reason(entry,now) is None


def record_status(path, video_id, saved):
    """YouTubeから確認した状態だけを同じIDの全記録へ。別のID/本文は維持。"""
    privacy=saved.get('privacyStatus')
    if privacy not in ('private','unlisted','public'):
        raise ValueError('確認した公開状態が不明です')
    at=saved.get('publishAt')
    if at and publish_time({'publish_at':at}) is False:
        raise ValueError('確認した予約日時が不正です')
    path=pathlib.Path(path)
    data=json.loads(path.read_text(encoding='utf-8'))
    matching=[entry for rows in data.values() if isinstance(rows,dict)
              for entry in rows.values() if isinstance(entry,dict) and entry.get('video_id')==video_id]
    for entry in matching:
        entry['privacy']=privacy
        entry['held']=privacy=='private' and not at
        entry.pop('hold',None)
        if entry.get('status') in ('held','hold','private','unlisted'):
            entry.pop('status',None)
        if at:
            entry['publish_at']=at
        else:
            entry.pop('publish_at',None)
    if matching:
        temp=path.with_suffix(path.suffix+'.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)
        from publication_writer import mirror_documents, root_for
        selected = {kind: {key: row for key, row in rows.items()
                              if isinstance(row, dict) and row.get('video_id') == video_id}
                    for kind, rows in data.items() if isinstance(rows, dict)}
        name = 'published_assets' if path.stem == 'published_assets' else 'published_videos'
        mirror_documents({name: selected}, root=root_for(path), verified=True)
    return len(matching)
