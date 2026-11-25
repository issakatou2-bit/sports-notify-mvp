def video_snapshots(store):
    """動画別データが取れた保存日を返す。"""
    return {day: snapshot for day, snapshot in (store.get("days") or {}).items()
            if "videos" in snapshot}
