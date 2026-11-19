"""Offline HTML review and validated, portable JSON decisions."""
import copy
import hashlib
import html
import json
import math
import os
from urllib.parse import quote
import visuals
import title_layout
import editing


def run_id(manifest):
    return hashlib.sha256(json.dumps(manifest['signature'], sort_keys=True).encode()).hexdigest()


def apply_decisions(manifest, review):
    if review.get('run_id') != run_id(manifest):
        raise ValueError('Review belongs to another source/settings/code run')
    decisions = review.get('clips')
    if not isinstance(decisions, list):
        raise ValueError('Review clips must be a list')
    result = copy.deepcopy(manifest)
    entries = {e['candidate']['rank']: e for e in result['clips']}
    seen = set()
    for decision in decisions:
        rank = decision.get('rank')
        if type(rank) is not int or rank not in entries or rank in seen:
            raise ValueError('Unknown or duplicate review rank')
        seen.add(rank)
        entry = entries[rank]
        original = entry.get('original_candidate', entry['candidate'])
        start, end = decision.get('start', original['start']), decision.get('end', original['end'])
        for value in (start, end):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Review timestamps must be finite seconds')
        if not original['start'] <= start < end <= original['end'] or end-start < 2:
            raise ValueError('Trim must stay inside the selected candidate and last at least two seconds')
        action, framing = decision.get('decision', 'auto'), decision.get('framing', 'safe')
        if action not in ('auto', 'approve', 'reject') or framing not in ('safe', 'wide', 'close'):
            raise ValueError('Invalid review decision/framing')
        v = entry.get('config',{}).get('visual',{})
        style = decision.get('visual_style', v.get('style','original'))
        theme = decision.get('theme', v.get('theme','generic'))
        context = decision.get('context_text', v.get('context_text',''))
        if style not in ('original','cinematic') or theme not in visuals.THEMES:
            raise ValueError('Invalid review visual style/theme')
        if not isinstance(context,str) or len(context)>90 or any(ord(c)<32 for c in context):
            raise ValueError('Context must be a single user-supplied line of at most 90 characters')
        titles=title_layout.options(v)
        title_style=decision.get('title_style',titles['style'])
        subtitle=decision.get('subtitle',titles['subtitle'])
        game_title=decision.get('game_title',v.get('game_title',''))
        if title_style not in title_layout.STYLES:
            raise ValueError('Invalid review title style')
        for text,limit in ((subtitle,90),(game_title,120)):
            if not isinstance(text,str) or len(text)>limit or any(ord(c)<32 for c in text):
                raise ValueError('Review title/subtitle is too long or contains a line break')
        preset=decision.get('editing_preset',entry.get('config',{}).get('editing_requested','auto'))
        if preset not in editing.PRESETS:
            raise ValueError('Invalid editing preset')
        hook=decision.get('hook_text',v.get('hook_text',''))
        placement=decision.get('title_placement',v.get('title_placement','auto'))
        reaction=decision.get('reaction',v.get('reaction',{'text':'','start':0.,'end':0.}))
        effects=decision.get('effects',entry.get('config',{}).get('effects',editing.EMPTY_EFFECTS))
        regions=decision.get('hud_regions',entry.get('config',{}).get('framing',{}).get('protected_regions',[]))
        if not isinstance(hook,str) or len(hook)>120 or any(ord(c)<32 for c in hook):
            raise ValueError('Hook must be one user-supplied line up to 120 characters')
        if placement not in ('auto','top','bottom'):
            raise ValueError('Invalid title placement')
        editing.validate_effects(effects,end-start)
        editing.validate_regions(regions)
        if v:
            visuals.validate(dict(v,hook_text=hook,title_placement=placement,reaction=reaction))
        elif reaction!={'text':'','start':0.,'end':0.}:
            raise ValueError('Reaction captions require a visual configuration')
        normalized = dict(rank=rank, start=start, end=end, decision=action, framing=framing,
                          visual_style=style, theme=theme, context_text=context,
                          game_title=game_title,title_style=title_style,subtitle=subtitle,
                          editing_preset=preset,hook_text=hook,title_placement=placement,reaction=reaction,
                          effects=effects,hud_regions=regions)
        if entry.get('review') == normalized:
            continue
        if entry['status'] == 'complete':
            raise ValueError('Cannot review or change an already completed video; use a new output directory')
        entry['original_candidate'] = original
        entry['candidate'] = dict(original, start=start, end=end)
        entry['review'] = normalized
        entry['status'] = 'rejected' if action == 'reject' else 'pending'
        entry.pop('preview_signature', None)
    return result


def document(directory, manifest, metrics=None):
    identifier = run_id(manifest)
    rows = []
    decisions = []
    theme_options=''.join(f'<option>{html.escape(name)}</option>' for name in visuals.THEMES)
    source = quote(os.path.relpath(manifest['signature']['source'], directory).replace('\\', '/'), safe='/.:')
    for entry in manifest.get('clips', []):
        item = entry['candidate']; rank = item['rank']
        original = entry.get('original_candidate', item)
        chosen = entry.get('review', dict(rank=rank, start=item['start'], end=item['end'], decision='auto',
                                         framing=entry.get('framing', {}).get('mode', 'safe')))
        visual = entry.get('config',{}).get('visual',{})
        chosen = dict(chosen)
        titles=title_layout.options(visual)
        for key, value in [('visual_style',visual.get('style','original')),('theme',visual.get('theme','generic')),('context_text',visual.get('context_text','')),
                           ('game_title',visual.get('game_title','')),('title_style',titles['style']),('subtitle',titles['subtitle']),
                           ('editing_preset',entry.get('config',{}).get('editing_requested','auto')),
                           ('hook_text',visual.get('hook_text','')),('title_placement',visual.get('title_placement','auto')),
                           ('reaction',visual.get('reaction',{'text':'','start':0.,'end':0.})),
                           ('effects',entry.get('config',{}).get('effects',editing.EMPTY_EFFECTS)),
                           ('hud_regions',entry.get('config',{}).get('framing',{}).get('protected_regions',[]))]:
            chosen.setdefault(key,value)
        decisions.append(chosen)
        warnings = '; '.join(item.get('warnings', [])) or 'No heuristic boundary warnings; payoff remains unverified.'
        reasons = html.escape(json.dumps(item.get('reasons', {}), indent=2))
        disabled = ' disabled' if entry['status']=='complete' else ''
        scores=item.get('reasons',{})
        score_summary=' | '.join(f'{label}: {scores.get(key,0):.3f}' for label,key in [('Motion','motion_score'),('Audio','audio_score'),('Opening','opening_score')])
        suggestion=item.get('suggested_editing',{'preset':'neutral','confidence':0,'reason':'Not classified'})
        extra_controls=''.join(f'<p><label>{label}<br><textarea class="{key}" rows="3" cols="65"{disabled}>{html.escape(json.dumps(chosen[key],indent=2))}</textarea></label></p>'
                               for key,label in [('reaction','Reaction caption: text and output start/end seconds'),('effects','Explicit effects: source-relative seconds within this clip'),('hud_regions','Protected regions: normalized source rectangles')])
        rows.append(f'''<article data-rank="{rank}"><h2>#{rank}: {html.escape(entry['status'])}</h2>
<p>Duration: {item['end']-item['start']:.2f}s source / {entry.get('output_duration',item['end']-item['start']):.2f}s output. {html.escape(score_summary)}</p>
<p>Suggested preset: {html.escape(suggestion['preset'])} ({suggestion['confidence']:.2f} heuristic confidence). {html.escape(suggestion['reason'])}</p>
<p>Applied preset: {html.escape(entry.get('config',{}).get('editing_preset','neutral'))}; theme: {html.escape(visual.get('theme','generic'))}; framing: {html.escape(entry.get('framing',{}).get('mode','safe'))}.</p>
<p>{html.escape(item.get('selection_reason',''))}</p>
<p>{html.escape('; '.join((entry.get('qa_summary') or {}).get('warnings',[])))}</p>
{f'<p><a href="clips/short-{rank:02d}.qa.json">Video/audio verification details</a></p>' if entry['status']=='complete' else ''}
<details><summary>Optional external scoring evidence</summary><pre>{html.escape(json.dumps(item.get('external_score',{}),indent=2))}</pre><p>External hook suggestions are not applied automatically.</p></details>
<p>{item['start']:.3f}–{item['end']:.3f}s · score {item['score']:.3f} · evidence confidence {item.get('confidence', 0):.2f}</p>
<p>{html.escape(warnings)}</p><details><summary>Selection reasons</summary><pre>{reasons}</pre></details>
<p>Planned composition</p><img src="clips/short-{rank:02d}.jpg" alt="Planned start, middle and end">
<details><summary>Compare original and cinematic layouts</summary>
<p>Original</p><img src="clips/short-{rank:02d}-original.jpg" alt="Original layout">
<p>Cinematic</p><img src="clips/short-{rank:02d}-cinematic.jpg" alt="Cinematic layout"></details>
<details><summary>Compare close and wide framing</summary>
<p>Safe</p><img src="clips/short-{rank:02d}-safe.jpg" alt="Safe framing">
<p>Close (still falls back when uncertain)</p><img src="clips/short-{rank:02d}-close.jpg" alt="Close alternative">
<p>Wide</p><img src="clips/short-{rank:02d}-wide.jpg" alt="Wide alternative"></details>
<details><summary>Play original interval</summary><video controls preload="none" src="{source}#t={item['start']},{item['end']}"></video></details>
<p><label>Decision <select class="decision"{disabled}><option value="auto">Automatic</option><option value="approve">Approve</option><option value="reject">Reject</option></select></label>
<label>Framing <select class="framing"{disabled}><option>safe</option><option>close</option><option>wide</option></select></label></p>
<p><label>Visual style <select class="visual_style"{disabled}><option>original</option><option>cinematic</option></select></label>
<label>Theme <select class="theme"{disabled}>{theme_options}</select></label></p>
<p><label>Title style <select class="title_style"{disabled}><option>minimal</option><option>cinematic</option><option>bold</option></select></label></p>
<p><label>Editing preset <select class="editing_preset"{disabled}><option>auto</option><option>action</option><option>funny</option><option>cinematic</option></select></label>
<label>Title placement <select class="title_placement"{disabled}><option>auto</option><option>top</option><option>bottom</option></select></label></p>
<p><label>Moment hook (your words) <input class="hook_text" maxlength="120" value="{html.escape(chosen['hook_text'],quote=True)}"{disabled}></label></p>
<details><summary>Optional timed effects and protected regions</summary>{extra_controls}</details>
<p><label>Game title (empty uses theme title) <input class="game_title" maxlength="120" value="{html.escape(chosen['game_title'],quote=True)}"{disabled}></label></p>
<p><label>Optional subtitle <input class="subtitle" maxlength="90" value="{html.escape(chosen['subtitle'],quote=True)}"{disabled}></label></p>
<p><label>Optional context (your description) <input class="context_text" maxlength="90" value="{html.escape(chosen['context_text'],quote=True)}"{disabled}></label></p>
<p><label>Source start (seconds) <input class="start" type="number" step="0.001" min="{original['start']}" max="{original['end']}" value="{item['start']}"{disabled}></label>
<label>Source end (seconds) <input class="end" type="number" step="0.001" min="{original['start']}" max="{original['end']}" value="{item['end']}"{disabled}></label></p>
{f'<p><a href="clips/short-{rank:02d}.mp4">Play finished Short</a></p>' if entry['status']=='complete' else ''}
<p>{html.escape(entry.get('error', ''))}</p></article>''')
    summary = ''
    if metrics:
        current = metrics['current_run']
        timings = ''.join(f'<tr><td>{html.escape(k)}</td><td>{v:.3f}s</td></tr>' for k,v in current['stage_seconds'].items())
        summary = f'''<section><h2>Processing measurements</h2><table><tr><th>Stage</th><th>Actual time</th></tr>{timings}</table>
<p>Current invocation wall time: {current['wall_seconds']:.3f}s. Historical + current wall time: {metrics['cumulative_wall_seconds']:.3f}s.</p>
<p>Accumulated stage time: {current['accumulated_stage_seconds']:.3f}s (nested stages can overlap).</p>
<pre>{html.escape(json.dumps(current['counts'], indent=2))}</pre>
<p>Render durations: {html.escape(json.dumps(current['render_seconds']))}</p>
<p>Cache/skips: {html.escape(', '.join(current['cache_hits']) or 'none')}</p>
<p>Python peak memory: {current['python_peak_memory_bytes']} bytes; FFmpeg/FFprobe excluded.</p>
<a href="metrics.json">Full timing history (JSON)</a></section>'''
    payload = json.dumps(dict(run_id=identifier, clips=decisions)).replace('<', '\\u003c')
    script = '''
const initial=PAYLOAD, key='yta-review-'+initial.run_id;
let saved=initial; try { const old=JSON.parse(localStorage.getItem(key)); if(old && old.run_id===initial.run_id) saved=old; } catch(e) {}
for(const article of document.querySelectorAll('article')) {
 const item=(article.querySelector('.decision').disabled ? initial : saved).clips.find(c=>c.rank===Number(article.dataset.rank)); if(!item) continue;
 for(const field of ['decision','framing','start','end','visual_style','theme','context_text','game_title','title_style','subtitle','editing_preset','hook_text','title_placement','reaction','effects','hud_regions']) {
  const input=article.querySelector('.'+field); if(item[field]!==undefined) input.value=['reaction','effects','hud_regions'].includes(field)?JSON.stringify(item[field],null,2):item[field];
 }
}
function collect(){ return {run_id:initial.run_id, clips:[...document.querySelectorAll('article')].filter(a=>!a.querySelector('.decision').disabled).map(a=>({rank:Number(a.dataset.rank),decision:a.querySelector('.decision').value,framing:a.querySelector('.framing').value,start:Number(a.querySelector('.start').value),end:Number(a.querySelector('.end').value),visual_style:a.querySelector('.visual_style').value,theme:a.querySelector('.theme').value,context_text:a.querySelector('.context_text').value,game_title:a.querySelector('.game_title').value,title_style:a.querySelector('.title_style').value,subtitle:a.querySelector('.subtitle').value,editing_preset:a.querySelector('.editing_preset').value,hook_text:a.querySelector('.hook_text').value,title_placement:a.querySelector('.title_placement').value,reaction:JSON.parse(a.querySelector('.reaction').value),effects:JSON.parse(a.querySelector('.effects').value),hud_regions:JSON.parse(a.querySelector('.hud_regions').value)}))}; }
document.addEventListener('change',()=>{try {localStorage.setItem(key,JSON.stringify(collect()));document.getElementById('status').textContent='Draft saved in this browser. Export JSON to apply it to Python.';}catch(e){document.getElementById('status').textContent='Browser storage unavailable. Export JSON to retain your decisions.';}});
document.getElementById('export').onclick=()=>{
 if(![...document.querySelectorAll('input')].every(i=>i.checkValidity())) {alert('Check trim bounds.');return;}
 let data;try{data=collect();}catch(e){alert('Check the JSON in the optional effects/protected-region fields.');return;}if(data.clips.some(c=>c.end-c.start<2)){alert('Each trim must last at least two seconds.');return;}
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
'''.replace('PAYLOAD', payload)
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local gameplay highlights</title><style>body{font:16px system-ui;background:#11151c;color:#edf0f7;max-width:950px;margin:30px auto;padding:16px}article,section{background:#202631;padding:20px;margin:20px 0}img,video{max-width:100%;width:648px;height:auto}a{color:#a9ccff}input,select,button{padding:8px;margin:5px}pre{white-space:pre-wrap}td,th{text-align:left;padding:6px}</style>
<h1>Local gameplay highlights</h1><p>Activity-based selection; confidence measures heuristic evidence, not event identity or predicted views.</p>
<p>Automatic processing needs no approval. For optional review, adjust decisions and export JSON, then resume with <code>--review-file path/to/review.json</code>. Trims apply on resume; contact sheets update afterward. Completed videos are locked.</p>
<button id="export">Export review JSON</button><p id="status">Decisions stay local. Exported JSON is the portable saved review.</p>''' + f'<p>{html.escape(manifest.get("message", ""))}</p>' + summary + ''.join(rows) + '<script>'+script+'</script></html>'
