"""Redditの声の保存試作。確認済みの短い訳だけを描画し、公開機能は持たない。"""
import argparse
import json
import os
from pathlib import Path

import topic_hub as hub
import reddit_rss as rss


def program(material, translations, context):
    if not all(t in context.get('source_title','') for t in ('Rays','Guardians')):
        raise ValueError('この試作の試合と保存スレッドの題が違います')
    rows=[]
    for translation in translations:
        original=translation['original']; quote=translation.get('quote') or original
        source=next((r for r in material['voices'] if r['original']==original),None)
        if not source or quote not in original or not translation.get('reviewed'):
            raise ValueError('保存RSSと短い引用・訳の確認が一致しません')
        rows.append(dict(kind='fan',speaker=2,text='ファンの感想です。「'+translation['ja']+'」',
                         meta=dict(source='r/'+context['board']+' / 公開RSS（評価数未確認）',heading='匿名のファンの感想',at=source['at'],url=source['url'],
                                   original=original,quote=quote,translation=translation['ja'],reviewed=True)))
    if not rows:raise ValueError('RSSに確認済みの短い声がありません')
    segments=[dict(kind='intro',speaker=2,text='レイズ対ガーディアンズの試合スレッドから、ファンの感想です。',
                   meta=dict(source='Redditの公開RSS',heading='試合スレッドの声',at=material['updated_at']))]+rows[:2]
    segments.append(dict(kind='closing',speaker=2,text=hub.FAN_NOTE,meta=dict(source='匿名の短い感想・事実の根拠ではありません',heading='短い訳と注意書き')))
    return dict(program='reddit_reaction',program_label='Redditの反応',can_make=True,label=material['updated_at'][:10],
                player=dict(name_jp='レイズ戦のRedditの声',name_en='Reddit thread',team_id='139'),direction='neutral',
                title='レイズ戦のRedditの声',description=hub.FAN_NOTE,segments=segments)


def validate(narr):
    if narr['program']!='reddit_reaction' or not narr['can_make'] or narr['segments'][-1]['text']!=hub.FAN_NOTE:
        raise ValueError('ファンの声の注意書きがありません')
    fans=[s for s in narr['segments'] if s['kind']=='fan']
    if not 1<=len(fans)<=2:raise ValueError('短い声は1〜2件')
    for seg in fans:
        meta=seg['meta'];rss.thread_link(meta['url'])
        if meta.get('author') or not meta['reviewed'] or meta['quote'] not in meta['original']:
            raise ValueError('匿名の原文引用と一致しません')
        if seg['text']!='ファンの感想です。「'+meta['translation']+'」':raise ValueError('訳を事実や断定に変えています')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--material',required=True);ap.add_argument('--translations',required=True);ap.add_argument('--context',required=True)
    ap.add_argument('--narration-out');ap.add_argument('--audio-dir');ap.add_argument('--out',default='build/reddit-reaction')
    args=ap.parse_args()
    if os.environ.get('COLLESPO_REDDIT')!='on':print('Redditの反応はonのときだけです');return
    narr=program(hub.load(args.material),json.loads(Path(args.translations).read_text(encoding='utf8')),hub.load(args.context));validate(narr)
    if args.narration_out:
        p=Path(args.narration_out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return
    import player_story_render
    player_story_render.render(narr,hub.load(Path(args.audio_dir)/'manifest.json')['segments'],args.out)


if __name__=='__main__':main()
