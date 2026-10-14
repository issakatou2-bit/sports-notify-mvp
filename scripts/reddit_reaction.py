"""Redditの声の保存試作。確認済みの短い訳だけを描画し、公開機能は持たない。"""
import argparse
import json
import os
from pathlib import Path

import topic_hub as hub
import reddit_rss as rss

MAX_COMMENTS=3
MAX_JA=26


def short_translation(original, translated):
    # 全文の訳だけ。切り出しや要約では長いコメントを通さない。
    return bool(original and translated and len(translated)<=MAX_JA and
                '\n' not in translated and not any(x in original+translated for x in ('@','/u/','u/')))


def count(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None


def platform_url(url, platform):
    from urllib.parse import urlsplit, parse_qs
    if platform=='Reddit':return rss.thread_link(url)
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname not in ('www.youtube.com','youtube.com') or u.path!='/watch' or not parse_qs(u.query).get('v'):
        raise ValueError('公式ハイライトの元動画URLが必要です')
    return url


def youtube_rows(material, translations):
    if material.get('source')!='MLB公式ハイライトのコメント':raise ValueError('公式ハイライトの保存材料だけを使います')
    out=[]
    for row in material.get('voices') or []:
        original=row.get('title') or ''
        tr=next((t for t in translations if t['original']==original and t.get('reviewed')),None)
        if not tr or tr.get('quote',original)!=original or not short_translation(original,tr['ja']):continue
        if not all(team in row.get('matchup','').upper() for team in ('GUARDIANS','RAYS')):
            raise ValueError('この試作の試合と公式ハイライトの保存材料が違います')
        out.append(dict(kind='fan',speaker=2,text='「'+tr['ja']+'」',meta=dict(
            platform='YouTube',source='YouTube / MLB公式ハイライト',heading='匿名のファンの感想',
            at=row.get('at') or material['updated_at'],url=platform_url(row['url'],'YouTube'),
            original=original,quote=original,translation=tr['ja'],reviewed=True,
            likes=count(row.get('like_count',row.get('likes'))),replies=count(row.get('reply_count',row.get('replies'))),
            reply_candidates=row.get('reply_ja') or [],reply_details=row.get('reply_details') or [])))
    return out


def select_reply(rows):
    for row in rows:
        meta=row['meta']; eligible=[]
        for reply in meta.get('reply_candidates') or []:
            if not short_translation(reply.get('original',''),reply.get('ja','')):continue
            details=next((d for d in meta.get('reply_details') or [] if d['original']==reply['original']),{})
            eligible.append((count(details.get('like_count')),reply))
        if not eligible:continue
        verified=[r for r in eligible if r[0] is not None]
        likes,reply=max(verified,key=lambda x:x[0]) if verified else eligible[0]
        details=next((d for d in meta.get('reply_details') or [] if d['original']==reply['original']),{})
        return dict(kind='fan_reply',speaker=2,text='「'+reply['ja']+'」',meta=dict(
            platform=meta['platform'],source=meta['source'],heading='評価数取得済みの短い返信で最多' if verified else '保存された返信の1件（順位不明）',
            at=details.get('at'),display_time='' if details.get('at') else '返信時刻は保存なし',
            url=meta['url'],original=reply['original'],quote=reply['original'],
            translation=reply['ja'],reviewed=True,likes=likes,parent_original=meta['original'],parent_translation=meta['translation']))
    return None

def program(material, translations, context, youtube=None, youtube_translations=None):
    if not all(t in context.get('source_title','') for t in ('Rays','Guardians')):
        raise ValueError('この試作の試合と保存スレッドの題が違います')
    rows=[]
    for translation in translations:
        original=translation['original']; quote=translation.get('quote') or original
        source=next((r for r in material['voices'] if r['original']==original),None)
        if not source or quote not in original or not translation.get('reviewed'):
            raise ValueError('保存RSSと短い引用・訳の確認が一致しません')
        if quote!=original or not short_translation(original,translation['ja']):continue
        rows.append(dict(kind='fan',speaker=2,text='「'+translation['ja']+'」',
                         meta=dict(source='r/'+context['board']+' / 公開RSS（評価数未確認）',heading='匿名のファンの感想',at=source['at'],url=source['url'],
                                   platform='Reddit',likes=count(source.get('score')) if source.get('score_verified') else None,
                                   original=original,quote=quote,translation=translation['ja'],reviewed=True)))
    if youtube:rows+=youtube_rows(youtube,youtube_translations or [])
    # 数字のあるものを高評価→返信順。不明なRSS同士は保存順で、順位とは呼ばない。
    rows.sort(key=lambda s:(s['meta'].get('likes') is not None,s['meta'].get('likes') or 0,s['meta'].get('replies') or 0),reverse=True)
    rows=rows[:MAX_COMMENTS]
    if not rows:raise ValueError('RSSに確認済みの短い声がありません')
    segments=[dict(kind='intro',speaker=2,text='レイズ対ガーディアンズ戦のファンの感想です。',
                   meta=dict(source='保存材料の短い訳',heading='公式ハイライトと試合スレッド',at=material['updated_at']))]+rows
    reply=select_reply(rows)
    for row in rows:
        row['meta'].pop('reply_candidates',None);row['meta'].pop('reply_details',None)
    if reply:segments.append(reply)
    segments.append(dict(kind='closing',speaker=2,text=hub.FAN_NOTE,meta=dict(source='匿名の短い感想・事実の根拠ではありません',heading='短い訳と注意書き')))
    return dict(program='reddit_reaction',program_label='ファンの反応',can_make=True,label=material['updated_at'][:10],
                player=dict(name_jp='レイズ戦のファンの声',name_en='Fan reactions',team_id='139'),direction='neutral',
                title='レイズ戦のファンの声',description=hub.FAN_NOTE,segments=segments)


def validate(narr):
    if narr['program']!='reddit_reaction' or not narr['can_make'] or narr['segments'][-1]['text']!=hub.FAN_NOTE:
        raise ValueError('ファンの声の注意書きがありません')
    fans=[s for s in narr['segments'] if s['kind']=='fan']
    if not 1<=len(fans)<=MAX_COMMENTS:raise ValueError('短いコメントは3件まで')
    replies=[s for s in narr['segments'] if s['kind']=='fan_reply']
    if len(replies)>1:raise ValueError('返信は1件まで')
    for seg in fans+replies:
        meta=seg['meta'];platform_url(meta['url'],meta['platform'])
        if meta.get('author') or not meta['reviewed'] or meta['quote']!=meta['original'] or not short_translation(meta['original'],meta['translation']):
            raise ValueError('匿名の原文引用と一致しません')
        if seg['text']!='「'+meta['translation']+'」':raise ValueError('訳を事実や断定に変えています')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--material',required=True);ap.add_argument('--translations',required=True);ap.add_argument('--context',required=True)
    ap.add_argument('--youtube');ap.add_argument('--youtube-translations')
    ap.add_argument('--narration-out');ap.add_argument('--audio-dir');ap.add_argument('--out',default='build/reddit-reaction')
    args=ap.parse_args()
    if os.environ.get('COLLESPO_REDDIT')!='on':print('Redditの反応はonのときだけです');return
    narr=program(hub.load(args.material),json.loads(Path(args.translations).read_text(encoding='utf8')),hub.load(args.context),
                 hub.load(args.youtube) if args.youtube else None,
                 json.loads(Path(args.youtube_translations).read_text(encoding='utf8')) if args.youtube_translations else None);validate(narr)
    if args.narration_out:
        p=Path(args.narration_out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(narr,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return
    import player_story_render
    player_story_render.render(narr,hub.load(Path(args.audio_dir)/'manifest.json')['segments'],args.out)


if __name__=='__main__':main()
