#!/usr/bin/env python3
"""Read-only PWA and bounded-memory video evidence. No pixel-based pass/fail."""
import argparse
import asyncio
import functools
import hashlib
import http.server
import io
import importlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import textwrap
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw, ImageStat

ROOT = Path(__file__).resolve().parents[1]
DEVICES = {'phone': (390, 844, 3), 'tablet': (768, 1024, 2)}
OBSERVATIONS = ['文字の欠け', '重なり', 'はみ出し', '色崩れ', '枠の大きな空き',
                '遷移の暗転・ちらつき', '出典と字幕', '札・記号と顔', 'キャラの内向き',
                '生の値の表示', '数字の幅と隣の字', '体の切れ目']


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def command(args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True,
                          encoding='utf-8', errors='replace').stdout


def sheet(items, out, columns=4, cell=(240, 370)):
    """Only thumbnails of at most 24 items are retained in memory."""
    for start in range(0, len(items), 24):
        batch = items[start:start + 24]
        canvas = Image.new('RGB', (columns * cell[0], math.ceil(len(batch) / columns) * cell[1]), '#e8edf2')
        draw = ImageDraw.Draw(canvas)
        for i, (label, source) in enumerate(batch):
            im = source() if callable(source) else Image.open(source).convert('RGB')
            im.thumbnail((cell[0] - 12, cell[1] - 38))
            x, y = (i % columns) * cell[0], (i // columns) * cell[1]
            canvas.paste(im, (x + 6, y + 32))
            caption='\n'.join(textwrap.wrap(label,width=max(12,int((cell[0]-12)/6.5)))[:2])
            draw.multiline_text((x + 6, y + 3), caption, fill='#152235',spacing=1)
            im.close()
        target = out.with_name(f'{out.stem}-{start // 24 + 1:03d}.jpg')
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target, quality=88)
        canvas.close()


def compare(current, baseline, out):
    """Side by side only: never use a numeric image difference as a verdict."""
    pairs = []
    inventory=baseline/'inventory.json'
    approvals={}
    if inventory.exists():
        approvals={Path(row['image']).with_suffix('').as_posix():row.get('approved',True) for row in
                   json.loads(inventory.read_text(encoding='utf-8')).get('images',[])}
    for path in sorted(current.rglob('*')):
        if path.suffix.lower() not in ('.png', '.jpg') or 'comparison' in path.parts:
            continue
        relative = path.relative_to(current)
        if approvals.get(relative.with_suffix('').as_posix()) is False:
            pairs.append({'image':relative.as_posix(),'baseline':'unapproved','verdict':'未確認','difference':''})
            continue
        old = baseline / relative
        if not old.exists() and path.suffix == '.png':
            old = old.with_suffix('.jpg')
        if not old.exists():
            pairs.append({'image': relative.as_posix(), 'baseline': 'missing', 'verdict': '未確認', 'difference': ''})
            continue
        with Image.open(old) as a, Image.open(path) as b:
            a.thumbnail((580, 1600)); b.thumbnail((580, 1600))
            column=max(a.width,b.width,200)+12
            result = Image.new('RGB', (column*2, max(a.height, b.height) + 32), 'white')
            result.paste(a, (0, 32)); result.paste(b, (column, 32))
            draw=ImageDraw.Draw(result)
            draw.text((8,8),'BASELINE',fill='black');draw.text((column+8,8),'CURRENT',fill='black')
            dest = out / relative.with_suffix('.jpg'); dest.parent.mkdir(parents=True, exist_ok=True)
            result.save(dest, quality=88)
        pairs.append({'image': relative.as_posix(), 'baseline': str(old), 'verdict': '未確認', 'difference': ''})
    write_json(out / 'review.json', {'checklist': OBSERVATIONS, 'images': pairs})


def layout_issues(layout):
    """Explicit renderer/DOM geometry, independent of visual approval."""
    problems = []
    if layout.get('preference') in ('light','dark') and layout.get('theme') != layout['preference']:
        problems.append({'kind':'theme-preference-not-applied'})
    width, height = layout['width'], layout['height']
    boxes = layout.get('boxes', [])
    for box in boxes:
        x, y, w, h = box['rect']
        if x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1:
            problems.append({'kind': 'overflow', 'id': box['id']})
        if box.get('role') == 'number' and w < box.get('max_number_width', w):
            problems.append({'kind': 'number-width', 'id': box['id']})
        if box.get('role') == 'character':
            cx = x + w / 2
            if (cx < width / 2 and box.get('facing') == 'left') or (cx > width / 2 and box.get('facing') == 'right'):
                problems.append({'kind': 'outward', 'id': box['id']})
            if box.get('body_cut_y', height) < height - 1:
                problems.append({'kind': 'body-cut', 'id': box['id']})
        if box.get('text') and re.search(r'\[object Object\]|\b(?:undefined|NaN)\b', box['text']):
            problems.append({'kind': 'raw-value', 'id': box['id']})
        if box.get('content_rect'):
            area = box['content_rect'][2] * box['content_rect'][3]
            if w * h and area / (w * h) < box.get('min_fill', .12):
                problems.append({'kind': 'empty', 'id': box['id']})
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            # Only declared incompatible layers. Containers/text naturally overlap.
            if b['id'] not in a.get('avoid', []) and a['id'] not in b.get('avoid', []):
                continue
            x, y, w, h = a['rect']; xx, yy, ww, hh = b['rect']
            if min(x + w, xx + ww) > max(x, xx) and min(y + h, yy + hh) > max(y, yy):
                problems.append({'kind': 'overlap', 'ids': [a['id'], b['id']]})
    return problems


def renderer_layout(frame, width=1080, height=1920):
    """Adapt the existing v3 renderer evidence without guessing face positions."""
    boxes = []
    # characters.place_bustsが実際に描いた矩形。締めの下端を推測せず検査する。
    for i, portrait in enumerate(frame.get('duo_portraits', [])):
        x, y, right, bottom = portrait['box']
        if frame.get('v3_outro') and not frame.get('duo_caption'):
            boxes.append({'id': f'character-{i}', 'role': 'character',
                          'rect': [x, y, right-x, min(height, bottom)-y],
                          'body_cut_y': bottom})
    for i, entry in enumerate(frame.get('v3_layout', [])):
        x, y, right, bottom = entry['box']
        boxes.append({'id': str(i), 'role': entry['role'], 'rect': [x,y,right-x,bottom-y],
                      'text': entry.get('text', '')})
    for box in boxes:
        if box['role'] == 'caption':
            box['avoid'] = [b['id'] for b in boxes if b['role'] in ('text','number','source','face','badge')]
        if box['role'] == 'card':
            x,y,w,h=box['rect']
            contained=[b['rect'] for b in boxes if b['role'] in ('text','number') and
                       x <= b['rect'][0] <= x+w and y <= b['rect'][1] <= y+h]
            if contained:
                left=min(r[0] for r in contained); top=min(r[1] for r in contained)
                box['content_rect']=[left,top,max(r[0]+r[2] for r in contained)-left,
                                     max(r[1]+r[3] for r in contained)-top]
    return {'width':width,'height':height,'boxes':boxes}


DOM = """() => {
 const visible = e => {const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
 const findings=[];
 for(const e of document.querySelectorAll('body *')) {
  if(!visible(e))continue; const r=e.getBoundingClientRect(),s=getComputedStyle(e);
  const label=e.tagName+'.'+e.className;
  if((r.left < -1 || r.right > innerWidth+1) && !e.closest('[style*="overflow"],.std-scroll') && !['auto','scroll'].includes(s.overflowX))
   findings.push({kind:'overflow-candidate',element:label,text:e.textContent.trim().slice(0,80),rect:[r.x,r.y,r.width,r.height]});
  if(e.children.length===0&&/\\[object Object\\]|\\bundefined\\b|\\bNaN\\b/.test(e.textContent))findings.push({kind:'raw-value',element:label});
  if(s.overflow==='hidden'&&e.scrollHeight>e.clientHeight+3&&e.textContent.trim())findings.push({kind:'clipping-candidate',element:label});
 }
 const preference=localStorage.getItem('collespo.theme');
 const expected=['light','dark'].includes(preference)?preference:(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 if(document.documentElement.dataset.theme!==expected)
  findings.push({kind:'theme-preference-not-applied',preference,actual:document.documentElement.dataset.theme||null});
 return {width:innerWidth,height:document.documentElement.scrollHeight,preference,theme:document.documentElement.dataset.theme,
         expected,background:getComputedStyle(document.body).backgroundColor,findings};
}"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def capture_pwa(args):
    site = args.site.resolve()
    if not site.is_dir(): raise ValueError(f'Site directory does not exist: {site}')
    available = sorted(p.relative_to(site).as_posix() for p in site.rglob('*.html'))
    pages = [name for name in available if Path(name).match(args.include)]
    if not pages: raise ValueError('No HTML pages matched; capture was not performed')
    # Optional PWA dependency: video CI must not need a browser installation.
    async_playwright = importlib.import_module('playwright.async_api').async_playwright
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/'
    records = []
    started = time.monotonic()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=args.browser or None, headless=True)
            for device, (w, h, dpr) in DEVICES.items():
                context = await browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=dpr,
                                                   is_mobile=True, has_touch=True, service_workers='block', locale='ja-JP')
                async def safe_route(route):
                    request = route.request
                    if request.method not in ('GET', 'HEAD') or not request.url.startswith(base):
                        await route.abort()
                    else:
                        await route.continue_()
                await context.route('**/*', safe_route)
                page = await context.new_page()
                transition_families = set()
                if args.states_only:
                    records.extend(await capture_states(page, context, args.out, base, device, w, h, dpr,args.state_groups))
                for name in pages:
                    if args.states_only: break
                    row = {'page': name, 'device': device, 'visual': '未確認', 'static': '未実施', 'transitions': []}
                    try:
                        response = await page.goto(base + name, wait_until='networkidle', timeout=15000)
                        row['http'] = response.status if response else None
                        await page.evaluate('document.fonts.ready')
                        await page.wait_for_timeout(150)
                        dest = args.out / 'pwa' / device / (name + '.png')
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        await capture_page(page, dest, w, h, dpr)
                        row['image'] = dest.relative_to(args.out).as_posix()
                        geometry = await page.evaluate(DOM)
                        row['static'] = '候補あり' if geometry['findings'] else 'PASS'
                        row['geometry'] = geometry
                        # One real safe link and history back per page. Never buttons/forms/auth.
                        links = await page.locator('a[href]').evaluate_all("es=>es.map(e=>({href:e.getAttribute('href'),text:e.textContent}))")
                        family = re.sub(r'archive/[^/]+\.html', 'archive/day', name) if name != 'archive/index.html' else name
                        if name.startswith('players/') and name != 'players/index.html': family = 'players/detail'
                        for link_index, link in enumerate(links):
                            if family in transition_families: break
                            href = link['href'] or ''
                            target = urljoin(base + name, href)
                            route_path = urlparse(target).path.lstrip('/') or 'index.html'
                            if route_path.endswith('/'): route_path += 'index.html'
                            if (not target.startswith(base) or route_path not in available or route_path == name or
                                re.search(r'callback|tiktok|threads|subscribe|publish|notify|post', href, re.I) or
                                re.search(r'購読|投稿|公開|通知|購入|ログイン|連携', link['text'])):
                                continue
                            locator = page.locator('a[href]').nth(link_index)
                            if not await locator.is_visible(): continue
                            await locator.scroll_into_view_if_needed()
                            prefix = dest.with_suffix('')
                            await page.screenshot(path=str(prefix) + '-link-before.png')
                            await locator.click(no_wait_after=True, timeout=3000)
                            for n, delay in enumerate((0, 60, 180)):
                                await page.wait_for_timeout(delay)
                                await page.screenshot(path=str(prefix) + f'-link-{n}.png')
                            await page.wait_for_load_state('networkidle')
                            row['transitions'].append({'action': 'link', 'href': href, 'arrived': page.url})
                            await page.go_back(wait_until='commit')
                            for n, delay in enumerate((0, 60, 180)):
                                await page.wait_for_timeout(delay)
                                await page.screenshot(path=str(prefix) + f'-back-{n}.png')
                            row['transitions'].append({'action': 'back', 'arrived': page.url})
                            transition_families.add(family)
                            break
                    except Exception as error:
                        row['error'] = str(error)
                    records.append(row)
                    write_json(args.out / 'pwa-manifest.json', {'seconds': round(time.monotonic()-started, 2), 'records': records})
                await context.close()
            await browser.close()
    finally:
        server.shutdown(); server.server_close()
    write_json(args.out / 'pwa-manifest.json', {'seconds': round(time.monotonic()-started,2), 'records':records})
    images = [(f"{r['device']} {r['page']}", args.out / r['image']) for r in records if r.get('image')]
    sheet(images, args.out / 'pwa-contact.jpg')
    write_json(args.out / 'review.json', {'checklist': OBSERVATIONS, 'visual': '未確認', 'differences': '', 'records': records})
    print(f'PWA {len(records)} captures, {time.monotonic()-started:.1f}s')
    return int(any(r.get('error') or r.get('http') != 200 for r in records))


async def capture_states(page, context, out, base, device, w, h, dpr, groups):
    """Explicit allowlist of local controls. Share/notification/auth are excluded."""
    rows=[]
    await context.add_init_script('Math.random=()=>0.42')
    async def save(name, action=None):
        dest=out/'pwa-states'/device/(name+'.png'); dest.parent.mkdir(parents=True,exist_ok=True)
        if action:
            await page.screenshot(path=str(dest.with_name(name+'-before.png')))
            await action()
            for n,delay in enumerate((0,60,180)):
                await page.wait_for_timeout(delay)
                await page.screenshot(path=str(dest.with_name(name+f'-during-{n}.png')))
        await capture_page(page,dest,w,h,dpr)
        geometry=await page.evaluate(DOM)
        rows.append({'page':name,'device':device,'http':200,'image':dest.relative_to(out).as_posix(),
                     'static':'候補あり' if geometry['findings'] else 'PASS','geometry':geometry,
                     'visual':'未確認','material':'saved data; lineup success uses explicit synthetic fixture'})
        write_json(out/'states-progress.json', {'records':rows})
    tasks=groups
    for task in tasks:
        try:
            if task=='home':
                await page.goto(base+'index.html',wait_until='networkidle')
                await save('home-menu',lambda:page.locator('#menuBtn').click())
                await page.keyboard.press('Escape')
                await save('home-soccer',lambda:page.locator('#tab-soccer').click())
                await save('home-mlb',lambda:page.locator('#tab-mlb').click())
                await save('home-dark',lambda:page.locator('#themeChoice').select_option('dark'))
                await save('home-light',lambda:page.locator('#themeChoice').select_option('light'))
                await save('home-system',lambda:page.locator('#themeChoice').select_option('system'))
                async def missing(route): await route.abort()
                await context.route('**/games.json*',missing)
                await page.reload(wait_until='networkidle')
                await save('home-fetch-failed')
                await context.unroute('**/games.json*',missing)
                await page.reload(wait_until='networkidle')
                await save('home-fetch-recovered')
            elif task=='archive':
                await page.goto(base+'archive/index.html',wait_until='networkidle')
                await save('archive-found',lambda:page.locator('#archive-query').fill('MLB'))
                await save('archive-empty',lambda:page.locator('#archive-query').fill('VISUAL-NO-SUCH-ENTRY'))
                await save('archive-cleared',lambda:page.locator('#archive-query').fill(''))
            elif task=='quiz':
                await page.goto(base+'quiz.html',wait_until='networkidle')
                await save('quiz-question')
                wrong=await page.evaluate('questions[current].choices.find(c=>c!==questions[current].answer)')
                await save('quiz-wrong',lambda:page.get_by_role('button',name=wrong,exact=True).click())
                await save('quiz-next',lambda:page.locator('#nextBtn').click())
                correct=await page.evaluate('questions[current].answer')
                await save('quiz-correct',lambda:page.get_by_role('button',name=correct,exact=True).click())
                await page.locator('#nextBtn').click()
                for _ in range(6):
                    await page.locator('#choices button').first.click()
                    await page.locator('#nextBtn').click()
                await save('quiz-result')
                await save('quiz-retry',lambda:page.locator('#retryBtn').click())
            elif task=='lineup':
                await page.goto(base+'lineup.html',wait_until='networkidle')
                await save('lineup-missing-data')
                fixture=ROOT/'scripts/fixtures/visual/lineup-data.json'
                async def sample(route): await route.fulfill(path=str(fixture),content_type='application/json')
                await context.route('**/player_stats.json*',sample)
                await page.reload(wait_until='networkidle')
                await save('lineup-picker',lambda:page.locator('.slot').first.click())
                await save('lineup-selected',lambda:page.locator('#picker .opt').first.click())
                await save('lineup-random',lambda:page.locator('#randomBtn').click())
                await save('lineup-cleared',lambda:page.locator('#clearBtn').click())
                await context.unroute('**/player_stats.json*',sample)
            elif task=='theme-nav':
                for label, choice, media in (('light','light','dark'), ('dark','dark','light'),
                                              ('system-light','system','light'), ('system-dark','system','dark')):
                    await page.emulate_media(color_scheme=media)
                    await page.goto(base+'index.html',wait_until='networkidle')
                    await page.locator('#themeChoice').select_option(choice)
                    await save(f'theme-{label}-source')
                    await save(f'theme-{label}-to-players',lambda:page.locator('a[href="players/"]:visible').first.click())
                    await save(f'theme-{label}-to-player',lambda:page.locator('.playerlist a[href]').first.click())
                    await save(f'theme-{label}-back',lambda:page.go_back(wait_until='networkidle'))
                    for target in ('archive/index.html', 'score.html', 'soccer.html', 'standings.html'):
                        await save(f'theme-{label}-to-'+target.replace('/','-').replace('.html',''),
                                   lambda target=target:page.goto(base+target,wait_until='networkidle'))
                    day=await page.evaluate("fetch('/visual-build.json').then(r=>r.json()).then(d=>d.games_source.split('/').pop().replace('.json','.html'))")
                    await save(f'theme-{label}-to-archive-day',lambda:page.goto(base+'archive/'+day,wait_until='networkidle'))
        except Exception as error:
            rows.append({'page':task,'device':device,'error':str(error),'visual':'未確認'})
    return rows


async def capture_page(page, dest, width, viewport_height, dpr, tall_threshold=16000):
    """Stitch real viewports: Chrome fullPage can repeat pixels above 16K at DPR3."""
    height = await page.evaluate('Math.max(document.body.scrollHeight,document.documentElement.scrollHeight)')
    if height * dpr <= tall_threshold:
        await page.screenshot(path=str(dest), full_page=True, timeout=30000)
        return
    canvas = Image.new('RGB', (width * dpr, height * dpr), 'white')
    for requested in range(0, height, viewport_height):
        await page.evaluate('(y)=>scrollTo(0,y)', requested)
        await page.wait_for_timeout(60)
        actual = await page.evaluate('scrollY')
        raw = await page.screenshot(full_page=False)
        with Image.open(io.BytesIO(raw)) as tile:
            offset = max(0, requested - actual)
            length = min(viewport_height, height - requested)
            crop = tile.crop((0, round(offset*dpr), width*dpr, round((offset+length)*dpr)))
            canvas.paste(crop, (0, requested*dpr))
    canvas.save(dest)
    canvas.close()
    await page.evaluate('scrollTo(0,0)')


def probe(video):
    data = json.loads(command(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', video]))
    stream = next(s for s in data['streams'] if s['codec_type'] == 'video')
    num, den = map(float, stream.get('avg_frame_rate', '30/1').split('/'))
    return float(data['format']['duration']), num / den


def safe_video_frame(video, t, fps):
    """最終PTSより丸めで僅かに先をseekした場合だけ、2〜3フレーム戻す。"""
    for at in (t, max(0, t-max(.1, 2/fps))):
        data = subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-ss', str(at), '-i', str(video),
                               '-frames:v', '1', '-vf', 'scale=320:-2', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                              check=True, capture_output=True).stdout
        if data:
            return Image.open(io.BytesIO(data)).convert('RGB'), at
    raise ValueError(f'完成動画から時刻{t:.3f}秒の画像を取得できません')


def video_capture(args):
    duration, fps = probe(args.video)
    # Low-resolution streaming scene detection: no extracted full-size frame files.
    result = subprocess.run(['ffmpeg', '-hide_banner', '-threads', '1', '-i', str(args.video), '-an',
                             '-vf', f'scale=192:-2,select=gt(scene\\,{getattr(args,"scene_threshold",.015)}),showinfo', '-fps_mode', 'vfr',
                             '-f', 'null', '-'], capture_output=True, encoding='utf-8', errors='replace', check=True)
    detected = sorted({float(t) for t in re.findall(r'pts_time:([\d.]+)', result.stderr)})
    groups=[]
    for t in detected:
        if groups and t-groups[-1][-1] <= .35: groups[-1].append(t)
        else: groups.append([t])
    cuts = sorted({0.0, duration, *((g[0]+g[-1])/2 for g in groups)})
    timeline = json.loads(args.timeline.read_text(encoding='utf-8')) if args.timeline else {}
    cuts = sorted(set(cuts + [float(s['start']) for s in timeline.get('scenes', [])] +
                      [float(s['end']) for s in timeline.get('scenes', [])]))
    cuts = [t for t in cuts if 0 <= t <= duration]
    # Gradual dissolves may evade scene detection: also retain 10-second intervals.
    cuts = sorted(set(cuts + [float(t) for t in range(10, math.ceil(duration), 10)
                             if all(abs(t-cut)>.6 for cut in cuts)]))
    samples = {}
    def add(t, reason):
        t = round(max(0, min(duration - 1 / fps, t)), 3)
        samples.setdefault(t, []).append(reason)
    for start, end in zip(cuts, cuts[1:]):
        for t, reason in ((start, 'head'), ((start+end)/2, 'middle'), (end-1/fps, 'tail')):
            add(t, reason)
    for cut in cuts[1:-1]:
        for delta in (-.15, 0, .15): add(cut + delta, 'transition')
    for group in groups:
        add(group[0]-.15,'transition-before-dissolve')
        add(group[-1]+.15,'transition-after-dissolve')
    for t in timeline.get('proximity_times', []): add(float(t), 'caption-near-table-or-face:declared')
    # Every second, rank edge density in the subtitle/table/face boundary band.
    # This is a candidate heuristic, never semantic proof or approval.
    process = subprocess.Popen(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(args.video), '-an',
                                '-vf', 'fps=1,scale=96:160', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], stdout=subprocess.PIPE)
    risks = []
    from PIL import ImageFilter
    try:
        second = 0
        while True:
            raw = process.stdout.read(96*160)
            if not raw: break
            if len(raw) != 96*160: raise ValueError('short proximity frame')
            im = Image.frombytes('L', (96, 160), raw)
            band = im.crop((0, 88, 96, 148)).filter(ImageFilter.FIND_EDGES)
            risks.append((ImageStat.Stat(band).mean[0], second)); second += 1
    finally:
        process.stdout.close()
        if process.wait(): raise RuntimeError('proximity decoding failed')
    # One strongest candidate per detected/guard interval, not only global top N.
    for start, end in zip(cuts, cuts[1:]):
        candidates = [(score, t) for score, t in risks if start <= t < end]
        if candidates: add(max(candidates)[1], 'caption-near-table-or-face:candidate')
    stem = args.video.stem
    seek_fallbacks = []
    def frame(t):
        result, actual = safe_video_frame(args.video, t, fps)
        if actual != t:
            seek_fallbacks.append(dict(requested=t, actual=actual, reason='末尾PTSの丸めによる空画像'))
        return result
    items = [(f'{t:.3f}s {"/".join(reasons)}', functools.partial(frame, t)) for t, reasons in sorted(samples.items())]
    sheet(items, args.out / 'video' / f'{stem}-contact.jpg', cell=(320, 590))
    with args.video.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    static = {'status': '未実施', 'reason': '完成mp4だけでは意味付き矩形を復元できない'}
    verification = args.video.parent / 'verification.json'
    if verification.exists():
        frames = json.loads(verification.read_text(encoding='utf-8')).get('frames', [])
        geometries = [renderer_layout(frame) for frame in frames if frame.get('v3_layout')]
        if geometries:
            issues = [{'frame':i,'issues':layout_issues(g)} for i,g in enumerate(geometries)]
            static = {'status':'候補あり' if any(r['issues'] for r in issues) else 'PASS',
                      'source':'verification.json/v3_layout', 'frames':issues,
                      'limits':'記録済み領域だけ。顔・向き・数字の予約幅など未記録の意味は未検査'}
    write_json(args.out / 'video' / f'{stem}-static.json', static)
    write_json(args.out / 'video' / f'{stem}-manifest.json', {
        'source': args.video.name, 'sha256': digest,
        'duration': duration, 'fps': fps, 'cuts': cuts, 'detected_transition_ranges':groups, 'samples': samples,
        'seek_fallbacks': seek_fallbacks,
        'proximity': 'heuristic candidates; declare exact times with --timeline for authored layouts',
        'static': static['status'], 'visual': '未確認', 'difference': '',
        'checklist': OBSERVATIONS, 'extracted_files': 0})
    print(f'video {len(items)} frames; only contact sheets saved; static={static["status"]}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='mode', required=True)
    default = ROOT / 'build' / 'visual' / datetime.now().strftime('%Y%m%d')
    pwa = sub.add_parser('pwa'); pwa.add_argument('--site', type=Path, default=ROOT / 'public')
    pwa.add_argument('--out', type=Path, default=default); pwa.add_argument('--browser', default=os.getenv('VISUAL_BROWSER'))
    pwa.add_argument('--include', default='*.html', help='Optional subset; default recursively includes every HTML file')
    pwa.add_argument('--states-only', action='store_true', help='Capture allowlisted menus/tabs/themes/quiz/picker states')
    pwa.add_argument('--state-groups',nargs='+',choices=['home','archive','quiz','lineup','theme-nav'],
                     default=['home','archive','quiz','lineup','theme-nav'])
    video = sub.add_parser('video'); video.add_argument('--video', required=True, type=Path)
    video.add_argument('--timeline', type=Path); video.add_argument('--out', type=Path, default=default)
    video.add_argument('--scene-threshold',type=float,default=.015)
    comp = sub.add_parser('compare'); comp.add_argument('--current', type=Path, required=True)
    comp.add_argument('--baseline', type=Path, default=ROOT / 'build/visual-baseline')
    comp.add_argument('--out', type=Path, default=default / 'comparison')
    layout = sub.add_parser('layout'); layout.add_argument('--input', type=Path, required=True)
    layout.add_argument('--out', type=Path, default=default / 'static.json')
    args = ap.parse_args()
    if args.mode == 'pwa': return asyncio.run(capture_pwa(args))
    if args.mode == 'video': video_capture(args)
    if args.mode == 'compare': compare(args.current, args.baseline, args.out)
    if args.mode == 'layout':
        layout=json.loads(args.input.read_text(encoding='utf-8'))
        issues = layout_issues(layout)
        status='FAIL' if issues else 'PASS' if layout.get('boxes') else '未実施（矩形なし）'
        write_json(args.out, {'static':status, 'issues':issues, 'visual':'未確認'})
        return bool(issues)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
