"""保存材料で得点速報・週末まとめの既存v5見本を作る。既定は静止画。"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', choices=('goal', 'week', 'all'), default='all')
    ap.add_argument('--video', action='store_true', help='起動済みの音声エンジンで声つき動画も作る')
    ap.add_argument('--out', type=Path, default=ROOT/'build/soccer-expansion-preview')
    args = ap.parse_args()
    os.environ['COLLESPO_SOCCER_LOOK'] = 'v5'
    os.environ['COLLESPO_SHORT_LOOK'] = 'v4'
    import soccer_goal_short as goal
    import soccer_results_render as render
    import soccer_result_story as story
    import soccer_slots_v4 as slots
    from preview_unified_v3 import sheet

    for mode in (('goal', 'week') if args.mode == 'all' else (args.mode,)):
        out = args.out.resolve()/mode
        out.mkdir(parents=True, exist_ok=True)
        if mode == 'goal':
            boards = json.loads((ROOT/'scripts/fixtures/soccer-results/scoreboards.json').read_text(encoding='utf8'))
            summaries = json.loads((ROOT/'scripts/fixtures/soccer-results/summaries.json').read_text(encoding='utf8'))
            items, _ = goal.build(boards, summaries, goal.now.results.utc('2026-09-20T17:15:00Z'))
            data = items[0]
            data['sample_fictional'] = True
            narr = render.production_narration(data, goal_short=True)
            clubs = story.clubs_for(data)
            draw = lambda seg: render.frame(1.8, seg, data, clubs)
            check = lambda im: render.validate_frame(im, data, clubs)
        else:
            data = json.loads((ROOT/'scripts/fixtures/soccer-slots/week.json').read_text(encoding='utf8'))
            plan = slots.program('week', data)
            narr = plan['narration']
            draw = lambda seg: slots.frame(1.8, seg, plan)
            check = lambda im: slots.check_frame(im, plan)
        for name, content in (('material', data), ('narration', narr)):
            (out/(name+'.json')).write_text(json.dumps(content, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
        images = []
        for i, seg in enumerate(narr['segments']):
            render.r3.set_program_clock(0)
            render.r3.set_caption(seg['text'], 20, 60, speaker=seg['speaker'],
                                  hide_caption=seg['kind']=='outro', caption_units=seg.get('caption_units'))
            render.r3.set_program_clock(1.8)
            im = draw(seg)
            errors = check(im)
            if errors: raise ValueError(f'{mode}画面{i+1}: {errors}')
            im.save(out/f'{i+1:02d}.png')
            images.append(im)
        render.r3.set_program_clock(None)
        sheet(images, [s['kind'] for s in narr['segments']], out/'all-screens.png', columns=4)
        if args.video:
            if mode == 'goal':
                goal.save(data, out)
            else:
                from preview_soccer_v5 import audio_for
                slots.render_video(plan, audio_for(narr, out), out)
        print(out/'all-screens.png')


if __name__ == '__main__':
    main()
