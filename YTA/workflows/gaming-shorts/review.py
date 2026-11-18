"""Offline HTML review and validated, portable JSON decisions."""
import copy
import hashlib
import html
import json
import math
import os
from urllib.parse import quote


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
        normalized = dict(rank=rank, start=start, end=end, decision=action, framing=framing)
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
    source = quote(os.path.relpath(manifest['signature']['source'], directory).replace('\\', '/'), safe='/.:')
    for entry in manifest.get('clips', []):
        item = entry['candidate']; rank = item['rank']
        original = entry.get('original_candidate', item)
        chosen = entry.get('review', dict(rank=rank, start=item['start'], end=item['end'], decision='auto',
                                         framing=entry.get('framing', {}).get('mode', 'safe')))
        decisions.append(chosen)
        warnings = '; '.join(item.get('warnings', [])) or 'No heuristic boundary warnings; payoff remains unverified.'
        reasons = html.escape(json.dumps(item.get('reasons', {}), indent=2))
        disabled = ' disabled' if entry['status']=='complete' else ''
        rows.append(f'''<article data-rank="{rank}"><h2>#{rank}: {html.escape(entry['status'])}</h2>
<p>{item['start']:.3f}–{item['end']:.3f}s · score {item['score']:.3f} · evidence confidence {item.get('confidence', 0):.2f}</p>
<p>{html.escape(warnings)}</p><details><summary>Selection reasons</summary><pre>{reasons}</pre></details>
<p>Planned composition</p><img src="clips/short-{rank:02d}.jpg" alt="Planned start, middle and end">
<details><summary>Compare close and wide framing</summary>
<p>Close (still falls back when uncertain)</p><img src="clips/short-{rank:02d}-close.jpg" alt="Close alternative">
<p>Wide</p><img src="clips/short-{rank:02d}-wide.jpg" alt="Wide alternative"></details>
<details><summary>Play original interval</summary><video controls preload="none" src="{source}#t={item['start']},{item['end']}"></video></details>
<p><label>Decision <select class="decision"{disabled}><option value="auto">Automatic</option><option value="approve">Approve</option><option value="reject">Reject</option></select></label>
<label>Framing <select class="framing"{disabled}><option>safe</option><option>close</option><option>wide</option></select></label></p>
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
 const item=saved.clips.find(c=>c.rank===Number(article.dataset.rank)); if(!item) continue;
 for(const field of ['decision','framing','start','end']) {
  const input=article.querySelector('.'+field); if(!input.disabled) input.value=item[field];
 }
}
function collect(){ return {run_id:initial.run_id, clips:[...document.querySelectorAll('article')].filter(a=>!a.querySelector('.decision').disabled).map(a=>({rank:Number(a.dataset.rank),decision:a.querySelector('.decision').value,framing:a.querySelector('.framing').value,start:Number(a.querySelector('.start').value),end:Number(a.querySelector('.end').value)}))}; }
document.addEventListener('change',()=>{try {localStorage.setItem(key,JSON.stringify(collect()));document.getElementById('status').textContent='Draft saved in this browser. Export JSON to apply it to Python.';}catch(e){document.getElementById('status').textContent='Browser storage unavailable. Export JSON to retain your decisions.';}});
document.getElementById('export').onclick=()=>{
 if(![...document.querySelectorAll('input')].every(i=>i.checkValidity())) {alert('Check trim bounds.');return;}
 const data=collect();if(data.clips.some(c=>c.end-c.start<2)){alert('Each trim must last at least two seconds.');return;}
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
'''.replace('PAYLOAD', payload)
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local gameplay highlights</title><style>body{font:16px system-ui;background:#11151c;color:#edf0f7;max-width:950px;margin:30px auto;padding:16px}article,section{background:#202631;padding:20px;margin:20px 0}img,video{max-width:100%;width:648px;height:auto}a{color:#a9ccff}input,select,button{padding:8px;margin:5px}pre{white-space:pre-wrap}td,th{text-align:left;padding:6px}</style>
<h1>Local gameplay highlights</h1><p>Activity-based selection; confidence measures heuristic evidence, not event identity or predicted views.</p>
<p>Automatic processing needs no approval. For optional review, adjust decisions and export JSON, then resume with <code>--review-file path/to/review.json</code>. Trims apply on resume; contact sheets update afterward. Completed videos are locked.</p>
<button id="export">Export review JSON</button><p id="status">Decisions stay local. Exported JSON is the portable saved review.</p>''' + f'<p>{html.escape(manifest.get("message", ""))}</p>' + summary + ''.join(rows) + '<script>'+script+'</script></html>'
