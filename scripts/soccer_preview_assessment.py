"""健康診断と再実行の軽い共通判定。描画/LLMの依存を持たない。"""
from datetime import datetime,timedelta,timezone
JST=timezone(timedelta(hours=9))
def timestamp(text):
    try:
        value=datetime.fromisoformat(str(text).replace('Z','+00:00'))
        return value if value.tzinfo else None
    except ValueError:return None

def assessment(data,day):
    at=timestamp(data.get('generated_at'))
    if not at or at.astimezone(JST).date().isoformat()!=day or not isinstance(data.get('games'),list):return 'unknown',0,'当日の試合材料を確認できません'
    selected=data.get('preview_selection')
    if not selected or selected.get('day')!=day:return 'unknown',0,'当日の点数選定記録がありません'
    count=len([g for g in data['games'] if str(g.get('game_id')) in selected.get('selected_ids',[])])
    if count!=selected.get('count'):return 'unknown',0,'選定記録と試合IDが一致しません'
    if count:return 'required',count,'点数基準を満たした注目試合'
    if selected.get('source_errors') or selected.get('rejected'):return 'unknown',0,selected.get('reason')
    return 'skip',0,selected.get('reason') or '注目度がしきい値以上の試合なし'

