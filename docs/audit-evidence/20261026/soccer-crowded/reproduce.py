import sys,json,os,math
from pathlib import Path
sys.path[:0]=['scripts','.']
os.environ.update(COLLESPO_SOCCER_LOOK='v6',COLLESPO_SHORT_LOOK='v4',COLLESPO_HOST_SPLIT='half',COLLESPO_SOLO_HOST='ui')
import soccer_result_story as story,soccer_results_render as render,soccer_readable as layout,review_render_v3 as r3
from PIL import Image
from unittest.mock import patch
out=Path('docs/audit-evidence/20261026/soccer-crowded');out.mkdir(parents=True,exist_ok=True)
data=json.loads(Path('scripts/fixtures/soccer-results/run-40249272204.json').read_text(encoding='utf8'))
with patch('soccer_publications.load',return_value={}):narr=story.narration(data)
segments=[s for s in narr['segments'] if s['kind'] not in ('team-stats','outro','followup-next','followup-change')]
for stage in (1,2):segments=story.shorten_required(segments,data,stage)
rosters=[s for s in segments if s['kind']=='roster']
segments=story.shorten_required(segments,data,3)
clubs=render.resolve_clubs(data);images=[];problems=[];times=[];records=[]
for i,seg in enumerate(segments+rosters):
    seconds=math.ceil(max(len(seg['text'])/6,layout.minimum_seconds(seg,data),2)*30)/30
    if i<len(segments):times.append(seconds)
    r3.set_caption(seg['text'],seconds,60,speaker=2,caption_units=seg.get('caption_units'))
    goals=seg['meta'].get('goals',[])
    samples=[seconds*(p+.5)/len(goals) for p in range(len(goals))] if len(goals)>1 else [1.4]
    for page,t in enumerate(samples):
        im=render.frame(t,seg,data,clubs);errors=render.validate_frame(im,data,clubs);problems.extend(errors)
        name=f'{i:02d}-{seg["kind"]}-{page}.png';im.save(out/name);images.append(im.resize((360,640)))
        records.append(dict(file=name,kind=seg['kind'],text=seg['text'],meta=seg['meta'],errors=errors))
report=dict(run_id=40249272204,base_commit='4edb08f3',audio='6 narration characters per second; not actual speech',seconds=sum(times),stages=[1,2,3],roster_samples='stage 2; stage 3 omits duplicate roster',errors=problems,frames=records,segments=segments)
(out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
for start in range(0,len(images),6):
    batch=images[start:start+6];contact=Image.new('RGB',(360*3,640*math.ceil(len(batch)/3)),(18,29,26))
    for i,im in enumerate(batch):contact.paste(im,((i%3)*360,(i//3)*640))
    contact.save(out/f'sheet-{start//6+1}.png')
print('seconds',sum(times),'frames',len(images),'errors',len(problems))
if problems:print(problems);raise SystemExit(1)
