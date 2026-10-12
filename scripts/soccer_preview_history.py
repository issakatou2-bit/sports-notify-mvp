"""実際に出した予告を、読み上げ原稿と公開台帳から保存する。"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import soccer_slots_v4 as slots
import name_reading_guard as readings
ROOT=Path(__file__).resolve().parents[1]


def binding(data,narration):
    def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest()
    return dict(material_sha256=digest(data),narration_sha256=digest(narration))


def snapshot(data,narration,published):
    day=slots.datetime.fromisoformat(data['generated_at'].replace('Z','+00:00')).astimezone(slots.JST).date().isoformat()
    entry=(published.get('daily_soccer') or {}).get(day) or {}
    if not entry.get('video_id'):raise ValueError('当日の公開/予約済み予告の記録がありません')
    actual=entry.get('preview_binding') or {}
    if any(actual.get(k)!=v for k,v in binding(data,narration).items()):raise ValueError('公開予告の材料/原稿hashが一致しません')
    segments=[s for s in narration.get('segments',[]) if s.get('kind') in ('preview','game')]
    selected=(data.get('preview_selection') or {}).get('selected_ids')
    games=[g for g in data['games'] if g.get('is_notable')]
    rows=[]
    for seg in segments:
        meta=seg.get('meta') or {};ident=meta.get('game_id')
        if ident is None and type(meta.get('game_index')) is int and 0<=meta['game_index']<len(games):ident=games[meta['game_index']]['game_id']
        matches=[g for g in games if str(g['game_id'])==str(ident)]
        if len(matches)!=1:raise ValueError('読んだ試合と材料のIDが一致しません')
        game=matches[0];facts=meta.get('interest') or {}
        player=facts.get('player')
        if player:
            if player['name'] not in seg['text']:raise ValueError('期待選手が読み上げ原稿にありません')
            readings.assert_known(player['name'])
            player=copy.deepcopy(player)
            known=next((p for p in __import__('notability_engine').JP_PLAYERS_SOCCER if p['name_jp']==player['name']),None)
            aliases=readings.player_data().get('reading_aliases',{})
            english=[k for k,v in aliases.items() if v==player['name'] and any(c.isascii() and c.isalpha() for c in k)]
            player['name_en']=known['name_en'] if known else english[0] if len(english)==1 else None
        code=game.get('competition_code') or next((c for c,n in __import__('notability_engine').SOCCER_COMPETITIONS.items() if game['league'] in (c,n)),None)
        rows.append(dict(game_id=str(game['game_id']),espn_event_id=game.get('espn_event_id'),league=game['league'],competition_code=code,
                         home=game['home_team_name'],away=game['away_team_name'],start_utc=slots.kickoff(game,data['generated_at']).isoformat(),
                         reasons=copy.deepcopy(facts.get('reasons',[])),expectation=player,spoken=seg['text'],
                         standings={s:dict(game.get(s+'_standing') or {},as_of=data['generated_at'],competition=code,season=game.get('season')) for s in ('home','away')}))
    if selected is not None and [r['game_id'] for r in rows]!=selected:raise ValueError('公開予告と選定順が一致しません')
    if not rows:raise ValueError('予告原稿に試合の区間がありません')
    return dict(day=day,video_id=entry['video_id'],title=entry.get('title'),published_at=entry.get('published_at'),binding=actual,games=rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--games',type=Path,default=ROOT/'data/soccer_games.json');ap.add_argument('--narration',type=Path,default=ROOT/'build/soccer_narration.json');ap.add_argument('--published',type=Path,default=ROOT/'data/published_videos.json');ap.add_argument('--out',type=Path,default=ROOT/'data/soccer_preview_history.json')
    args=ap.parse_args();read=lambda p:json.loads(p.read_text(encoding='utf8'))
    record=snapshot(read(args.games),read(args.narration),read(args.published))
    history=read(args.out) if args.out.exists() else {}
    if (history.get(record['day']) or {}).get('video_id')==record['video_id']:
        print('公開予告は保存済み:',record['day']);return
    import soccer_result_context
    record=soccer_result_context.capture_before(record)
    history[record['day']]=record
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(history,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('保存した公開予告:',record['day'],len(record['games']),'試合')
if __name__=='__main__':main()
