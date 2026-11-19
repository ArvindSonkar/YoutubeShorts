"""One-command offline gameplay highlights. No API keys, models, or downloads."""
from contextlib import contextmanager
from fractions import Fraction
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

import analyze
import autoframe
import select_highlights
import progress
import review
import visuals
import editing
import candidate_exchange
from dynamic_crop import (HERE, DEFAULTS, Job, SourceContext, capture, compose, digest,
                          merge, number, project_path, read_json, render, tools, writable_path, generated_path)
from verify_output import verify


def atomic_json(path, value):
    path = writable_path(path)
    pending = path.with_suffix(path.suffix+'.tmp')
    pending.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    pending.replace(path)


@contextmanager
def run_lock(directory):
    # An OS lock is released after a crash; no stale-PID guessing or forced unlock.
    with (directory/'.run.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another process is using this output directory') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def validate_settings(settings):
    if settings.get('editing_preset','auto') not in editing.PRESETS:
        raise ValueError('editing_preset must be auto, action, funny or cinematic')
    number(settings.get('highlight_diversity',.5),'highlight_diversity',0,1)
    if type(settings.get('moment_aware_boundaries',True)) is not bool:
        raise ValueError('moment_aware_boundaries must be a boolean')
    editing.validate_effects(settings.get('effects',{}))
    editing.validate_regions(settings.get('hud_regions',[]))
    if 'visual' in settings:
        visuals.validate(settings['visual'])
    for key, low, high in [('analysis_fps', 1, 10), ('min_duration', 2, 180),
                           ('max_duration', 2, 180), ('min_score', .05, 1),
                           ('min_gap', 0, 60), ('crop_confidence', .1, 1),
                           ('crop_min_width', .35, 1), ('crf', 0, 30)]:
        number(settings[key], key, low, high)
    for key, low, high in [('count', 1, 100), ('analysis_width', 160, 640),
                           ('audio_stream', 0, 32), ('threads', 1, 64)]:
        if type(settings[key]) is not int or not low <= settings[key] <= high:
            raise ValueError(f'{key} must be an integer in [{low}, {high}]')
    if settings['analysis_width'] % 2:
        raise ValueError('analysis_width must be even')
    if settings['max_duration'] < settings['min_duration']:
        raise ValueError('max_duration must be at least min_duration')
    if settings['preset'] not in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'):
        raise ValueError('Unsupported encoding preset')
    for key, low, high in [('opening_seconds', 1, 2), ('setup_seconds', 0, 5), ('payoff_seconds', 0, 5)]:
        number(settings.get(key, 2 if key=='opening_seconds' else 1), key, low, high)
    if settings.get('framing_mode', 'safe') not in ('safe', 'close', 'wide'):
        raise ValueError('framing_mode must be safe, close or wide')
    if settings.get('game_profile', 'generic') not in ('generic', 'dmc5'):
        raise ValueError('game_profile must be generic or dmc5')


def code_signature():
    names = ['auto_shorts.py', 'analyze.py', 'select_highlights.py', 'autoframe.py',
             'dynamic_crop.py', 'verify_output.py', 'defaults.json', 'auto_defaults.json',
             'progress.py', 'review.py', 'game_profiles.py', 'dmc5_title_calibration.json', 'visuals.py', 'title_layout.py',
             'moments.py','editing.py','candidate_exchange.py','audio_quality.py']
    return hashlib.sha256(b''.join((HERE/name).read_bytes() for name in names)).hexdigest()


def archive_incomplete(target, run_dir, attempt):
    # Only move this job's incomplete artifacts, always inside the resolved run directory.
    root = run_dir.resolve()
    for path in (target.with_suffix('.work'), target.with_name(target.stem+'.partial.mp4')):
        if not path.exists():
            continue
        destination = root/'attempts'/f'{target.stem}-{attempt}-{path.name}'
        if not path.resolve().is_relative_to(root) or not destination.resolve().is_relative_to(root):
            raise ValueError('Refusing artifact move outside the run directory')
        destination.parent.mkdir(exist_ok=True)
        path.rename(destination)


def thumbnail(job, path, frames=None):
    # One contact strip per clip, using the same source composition as rendering.
    sheet = Image.new('RGB', (648, 408), '#11151c')
    draw = ImageDraw.Draw(sheet)
    decoder = cv2.VideoCapture(str(job.source)) if frames is None else None
    try:
        for column, index in enumerate((0, job.count//2, job.count-1)):
            original = capture(job, index, decoder) if frames is None else frames[index]
            frame = compose(original, job.plan[index], job.config, job.layer, job.presentation)
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((216, 384))
            sheet.paste(image, (column*216, 24))
            draw.text((column*216+5, 5), f'+{index/float(job.fps):.2f}s', fill='white')
    finally:
        if decoder is not None:
            decoder.release()
    sheet.save(path, quality=88)


def report(directory, manifest, metrics=None):
    (directory/'index.html').write_text(review.document(directory, manifest, metrics), encoding='utf-8')


def make_config(defaults, source, target, candidate, data, settings, context):
    config = copy.deepcopy(defaults)
    fps = Fraction(next(s for s in context.meta['streams'] if s['codec_type']=='video')['avg_frame_rate'])
    first, last = round(candidate['start']*fps), round(candidate['end']*fps)
    config.update(source=str(source), output=str(target), expected_source_sha256=context.sha256,
                  clip={'start_frame': first, 'end_frame': last})
    config['audio']['stream'] = settings['audio_stream']
    config['video'].update(preset=settings['preset'], crf=settings['crf'], threads=settings['threads'])
    if 'visual' in settings:
        config['visual'],edit_report=editing.apply(settings['visual'],candidate,settings.get('editing_preset','auto'),settings.get('_visual_overrides'))
        config['visual'].update(visuals.asset_hashes(config['visual'],HERE.parents[1]))
        config['editing_preset']=edit_report['selected']
        config['editing_requested']=settings.get('editing_preset','auto')
    else:
        edit_report={'selected':'neutral','requested':'auto'}
    config['framing']['keyframes'], framing = autoframe.keyframes(
        data, float(first/fps), float(last/fps), settings, float(fps))
    # Automatic pulses are omitted: motion peaks do not prove that an impact happened.
    config['impacts']['enabled'] = False
    config['effects']=copy.deepcopy(settings.get('effects',editing.EMPTY_EFFECTS))
    config['framing']['protected_regions']=copy.deepcopy(settings.get('hud_regions',[]))
    config['framing']['anticipate_widening']=True
    config['smoothing'].update(max_pan_per_second=.18, max_width_change_per_second=.20)
    framing['editing']=edit_report
    return config, framing


def execute(args):
    settings = read_json(HERE/'auto_defaults.json')
    supplied={}
    if args.settings:
        supplied=read_json(args.settings)
        settings = merge(settings, supplied)
    settings['_visual_overrides']=[[section,key,value] for section,keys in supplied.get('visual',{}).items()
        if section in ('panel','title') for key,value in keys.items()]
    for key in settings:
        value = getattr(args, key, None)
        if value is not None:
            settings[key] = value
    v = settings['visual']
    for arg, key in [('visual_style','style'),('theme','theme'),('game_title','game_title'),('context_text','context_text'),
                     ('hook_text','hook_text'),('title_placement','title_placement')]:
        if getattr(args,arg,None) is not None:
            v[key] = getattr(args,arg)
    for arg,key in [('title_style','style'),('subtitle','subtitle')]:
        if getattr(args,arg,None) is not None:
            v['title'][key]=getattr(args,arg)
            settings['_visual_overrides'].append(['title',key,getattr(args,arg)])
    if getattr(args,'hud_safe_config',None):
        hud=read_json(project_path(args.hud_safe_config))
        if not isinstance(hud,dict) or set(hud)!={'regions'}:
            raise ValueError('HUD file must contain exactly a regions list of normalized rectangles')
        settings['hud_regions']=hud['regions']
    for arg,key in [('creator_name','name'),('creator_logo','logo')]:
        if getattr(args,arg,None) is not None:
            v['branding'][key] = getattr(args,arg)
            v['branding']['enabled'] = True
    if getattr(args,'branding',None) is not None:
        v['branding']['enabled'] = args.branding
    if getattr(args,'progress_line',None) is not None:
        v['progress_line']['enabled'] = args.progress_line
    if getattr(args,'blur_intensity',None) is not None:
        v['background']['blur_sigma'] = args.blur_intensity
    if getattr(args,'glow_intensity',None) is not None:
        v['panel']['glow'] = args.glow_intensity
        settings['_visual_overrides'].append(['panel','glow',args.glow_intensity])
    validate_settings(settings)
    v.update(visuals.asset_hashes(v, HERE.parents[1]))
    if args.max_seconds is not None:
        number(args.max_seconds, 'max_seconds', settings['min_duration'], 86400)
    source = project_path(args.input)
    if not source.is_file() or source.suffix.lower() != '.mp4':
        raise ValueError('Input must be an existing local MP4')
    directory = generated_path(args.output_dir)
    if directory.exists() and not args.resume:
        raise FileExistsError('Output directory already exists; choose a new name or use --resume')
    if args.resume and not (directory/'manifest.json').is_file():
        raise ValueError('--resume requires an existing run manifest')
    directory.mkdir(parents=True, exist_ok=True)
    with run_lock(directory):
        recorder = progress.Session(directory, args.resume)
        outcome = 'failed'
        with progress.session(recorder):
            try:
                result = run(args, settings, source, directory)
                outcome = ('planned' if args.analysis_only else 'complete') if result == 0 else ('no_candidates' if result == 2 else 'partial')
                return result
            except KeyboardInterrupt:
                outcome = 'interrupted'
                raise
            finally:
                path = directory/'manifest.json'
                if path.exists() and getattr(recorder, 'manifest_ready', False):
                    manifest = read_json(path)
                    entries = manifest.get('clips', [])
                    recorder.counts.update(selected=len(entries),
                        successful=sum(e['status']=='complete' for e in entries),
                        failed=sum(e['status']=='failed' for e in entries),
                        rejected=sum(e['status']=='rejected' for e in entries),
                        generated_video_seconds=sum(e.get('output_duration',(e['config']['clip']['end_frame']-e['config']['clip']['start_frame'])/
                            float(Fraction(e.get('source_fps', '30')))) for e in entries if e['status']=='complete'))
                    manifest['last_invocation_status'] = outcome
                    atomic_json(path, manifest)
                    with progress.stage('HTML report generation', 1, 'report', 'HTML report') as meter:
                        report(directory, manifest, recorder.document(outcome))
                        meter.update(1)
                    recorder.ended = recorder.clock()
                    recorder.summary(outcome)
                    # Refresh the embedded snapshot after measuring report generation.
                    report(directory, manifest, recorder.document(outcome))
                else:
                    recorder.summary(outcome)


def run(args, settings, source, directory):
    defaults = read_json(DEFAULTS)
    executables = tools(defaults)
    print('Probing and fingerprinting source once for this run...', flush=True)
    context = SourceContext(source, executables)
    # One-frame metadata validation reuses the renderer's actual compatibility rules.
    preflight = copy.deepcopy(defaults)
    preflight.update(source=str(source), output=str(directory/'preflight.mp4'),
                     clip={'start_frame': 0, 'end_frame': 1})
    preflight['audio']['stream'] = settings['audio_stream']
    check = Job(preflight, context)
    video = check.video
    source_duration = float(video.get('duration', context.meta['format']['duration']))
    duration = min(source_duration, args.max_seconds) if args.max_seconds else source_duration
    if duration < settings['min_duration']:
        raise ValueError('Source/analysis interval is shorter than the minimum clip length')
    if shutil.disk_usage(directory).free < 512*1024**2:
        raise RuntimeError('Less than 512 MiB free; choose a drive with more space')
    signature = {'source_sha256': context.sha256, 'source': str(source), 'duration': duration,
                 'settings': settings, 'code_sha256': code_signature(), 'analysis_version': analyze.VERSION}
    manifest_path = directory/'manifest.json'
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest['signature'] != signature:
            raise ValueError('Source, settings, or code changed; use a new output directory')
    else:
        manifest = {'schema_version': 1, 'signature': signature, 'status': 'analyzing', 'clips': [],
                    'message': 'Analysis pending', 'source_unchanged': False}
        atomic_json(manifest_path, manifest)
    progress.CURRENT.manifest_ready = True
    manifest['source_unchanged'] = False
    atomic_json(manifest_path, manifest)
    cache = directory/'features.npz'
    if cache.exists():
        print('Reusing cached audiovisual features.', flush=True)
        with progress.stage('Loading cached analysis', category='Cache'):
            data = analyze.load_features(cache, signature)
        progress.CURRENT.cache_hits.append('audiovisual features; video/audio scans skipped')
    else:
        data = analyze.scan(context, duration, settings)
        with progress.stage('Saving analysis cache', category='Cache'):
            analyze.save_features(cache, data, signature)
    rerank_document=read_json(project_path(args.rerank_file)) if getattr(args,'rerank_file',None) else None
    rerank_changed=rerank_document is not None and rerank_document!=manifest.get('rerank_document')
    if rerank_changed and any(e['status']=='complete' or e.get('review') or project_path(e['config']['output']).exists() for e in manifest['clips']):
        raise ValueError('Rerank before manual review/rendering, or use a fresh output directory')
    if not manifest.get('selection_done') or rerank_changed:
        candidates, scores = select_highlights.candidate_windows(data, duration, settings)
        for c in candidates:
            c['candidate_id']=candidate_exchange.identify(c,context.sha256)
        if rerank_document:
            candidates=candidate_exchange.apply_scores(signature,candidates,rerank_document)
            manifest['rerank_document']=rerank_document
        with progress.stage('Candidate diversity and overlap removal', category='Selection'):
            selected = select_highlights.choose(candidates, settings['count'], duration, settings['min_gap'],settings.get('highlight_diversity',.5))
        progress.CURRENT.counts['candidates'] = len(candidates)
        atomic_json(directory/'candidates.json', {'candidates': candidates, 'selected': selected,
                    'note': 'Heuristic activity scores, not event recognition or predicted views.'})
        np.savez_compressed(directory/'scores.npz', time=data['time'], score=scores)
        (directory/'clips').mkdir(exist_ok=True)
        manifest['clips']=[]
        with progress.stage('Automatic framing', len(selected), 'clips', 'Framing') as meter:
            for candidate in selected:
                rank = candidate['rank']
                target = directory/'clips'/f'short-{rank:02d}.mp4'
                config, framing = make_config(defaults, source, target, candidate, data, settings, context)
                entry = {'candidate': candidate, 'config': config, 'framing': framing, 'status': 'pending', 'attempts': 0,
                         'source_fps': str(check.fps)}
                manifest['clips'].append(entry)
                atomic_json(target.with_suffix('.json'), config)
                meter.update(rank)
        manifest['selection_done'] = True
        manifest['message'] = f'Selected {len(selected)} of requested {settings["count"]} clips. '
        if len(selected) < settings['count']:
            manifest['message'] += 'Fewer non-overlapping candidates met the quality threshold.'
        atomic_json(manifest_path, manifest)
    else:
        progress.CURRENT.cache_hits.append('candidate selection and framing plan')
        progress.CURRENT.counts['candidates'] = len(read_json(directory/'candidates.json')['candidates'])
    if getattr(args,'export_candidates',False):
        with progress.stage('Candidate metadata and sampled frame export',category='Previews'):
            candidate_exchange.export(directory,source,signature,read_json(directory/'candidates.json')['candidates'],frames=True)
    if getattr(args, 'review_file', None):
        decisions = read_json(project_path(args.review_file))
        revised = review.apply_decisions(manifest, decisions)
        # Validate every affected job before committing any review changes.
        for old, entry in zip(manifest['clips'], revised['clips']):
            if old.get('review') != entry.get('review'):
                target = project_path(entry['config']['output'])
                if target.exists():
                    raise ValueError('Review cannot replace an existing video; use a new run')
                visual = copy.deepcopy(settings['visual'])
                visual.update(style=entry['review']['visual_style'], theme=entry['review']['theme'], context_text=entry['review']['context_text'])
                visual['game_title']=entry['review']['game_title']
                visual['title'].update(style=entry['review']['title_style'],subtitle=entry['review']['subtitle'])
                visual.update(hook_text=entry['review']['hook_text'],title_placement=entry['review']['title_placement'],reaction=entry['review']['reaction'])
                visual.update(visuals.asset_hashes(visual, HERE.parents[1]))
                reviewed_settings = dict(settings, framing_mode=entry['review']['framing'], visual=visual,
                    editing_preset=entry['review']['editing_preset'],effects=entry['review']['effects'],hud_regions=entry['review']['hud_regions'],
                    _visual_overrides=settings['_visual_overrides']+[['title','style',entry['review']['title_style']],['title','subtitle',entry['review']['subtitle']]])
                entry['config'], entry['framing'] = make_config(defaults, source, target, entry['candidate'], data, reviewed_settings, context)
                Job(entry['config'], context)
        manifest = revised
        atomic_json(manifest_path, manifest)
        atomic_json(directory/'review-applied.json', decisions)
        for entry in manifest['clips']:
            atomic_json(project_path(entry['config']['output']).with_suffix('.json'), entry['config'])
    print(manifest['message'], flush=True)
    # Prepare all alternatives and the review page before any expensive encoding.
    variants = [(None,None), ('original',None), ('cinematic',None), (None,'safe'), (None,'close'), (None,'wide')]
    with progress.stage('Preview generation', len(manifest['clips'])*len(variants), 'contact sheets', 'Previews') as meter:
        for position, entry in enumerate(manifest['clips']):
            if entry['status'] == 'rejected':
                meter.update((position+1)*len(variants))
                continue
            signature = hashlib.sha256(json.dumps(entry['config'], sort_keys=True).encode()).hexdigest()
            target = project_path(entry['config']['output'])
            paths = [target.with_suffix('.jpg')]+[target.with_name(target.stem+f'-{style or mode}.jpg') for style,mode in variants[1:]]
            if entry.get('preview_signature') == signature and all(p.exists() for p in paths):
                progress.CURRENT.cache_hits.append(f'previews Short {entry["candidate"]["rank"]}')
                meter.update((position+1)*len(variants))
                continue
            try:
                preview_job = Job(entry['config'], context)
                entry['output_duration']=preview_job.duration
                decoder = cv2.VideoCapture(str(source))
                try:
                    frames = {index: capture(preview_job, index, decoder) for index in (0, preview_job.count//2, preview_job.count-1)}
                finally:
                    decoder.release()
                for offset, (style, mode) in enumerate(variants):
                    config = copy.deepcopy(entry['config']) if mode is None else make_config(defaults, source, target,
                        entry['candidate'], data, dict(settings, framing_mode=mode, visual=entry['config']['visual'],
                        effects=entry['config'].get('effects',{}),editing_preset=entry['config'].get('editing_requested','auto'),
                        hud_regions=entry['config']['framing'].get('protected_regions',[])), context)[0]
                    if style:
                        config['visual']['style'] = style
                        config['visual'].update(visuals.asset_hashes(config['visual'], HERE.parents[1]))
                    thumbnail(preview_job if offset==0 else Job(config, context), paths[offset], frames)
                    meter.update(position*len(variants)+offset+1)
                entry['preview_signature'] = signature
                if entry.get('error', '').startswith('Preview failed:'):
                    entry.pop('error', None)
                    entry['status'] = 'pending'
            except Exception as exc:
                entry.update(status='failed', error='Preview failed: '+str(exc))
            atomic_json(manifest_path, manifest)
    with progress.stage('HTML report generation', 1, 'report', 'HTML report'):
        report(directory, manifest, progress.CURRENT.document())
    failures = 0
    for entry in manifest['clips']:
        if entry['status'] == 'rejected':
            continue
        if entry.get('error', '').startswith('Preview failed:'):
            failures += 1
            continue
        if args.analysis_only:
            continue
        rank = entry['candidate']['rank']
        try:
            job = Job(entry['config'], context)
            if job.target.exists():
                if entry['status'] == 'complete' and entry.get('output_sha256') == digest(job.target):
                    print(f'[{rank}] Verified completed output checksum; skipping.', flush=True)
                    progress.CURRENT.cache_hits.append(f'completed Short {rank}; checksum verified')
                    continue
                # Recover a process that finished rendering before saving its manifest.
                effective = job.target.with_suffix('.work')/'effective-config.json'
                if not effective.exists() or read_json(effective) != job.config:
                    raise RuntimeError('Existing video lacks matching provenance; refusing to replace it')
                result = verify(job)
            else:
                entry['attempts'] += 1
                entry['status'] = 'rendering'
                entry.pop('error', None)
                atomic_json(manifest_path, manifest)
                archive_incomplete(job.target, directory, entry['attempts'])
                print(f'[{rank}/{len(manifest["clips"])}] Rendering {job.duration:.2f}s...', flush=True)
                render(job, f'Rendering Short {rank}/{len(manifest["clips"])}')
                progress.CURRENT.counts['rendered_this_invocation'] = progress.CURRENT.counts.get('rendered_this_invocation', 0)+1
                result = verify(job, full_decode=False)  # render already did a complete decode.
            atomic_json(job.target.with_suffix('.qa.json'), result)
            entry['qa_summary']=result.get('audio_quality')
            entry.update(status='complete', output_sha256=digest(job.target),output_duration=job.duration)
            entry.pop('error', None)
        except KeyboardInterrupt:
            entry.update(status='interrupted', error='Interrupted; partial artifacts retained for resume')
            atomic_json(manifest_path, manifest)
            raise
        except Exception as exc:
            entry.update(status='failed', error=str(exc))
            failures += 1
            print(f'[{rank}] FAILED: {exc}', file=sys.stderr, flush=True)
        atomic_json(manifest_path, manifest)
        progress.CURRENT.save()
        with progress.stage('HTML report generation', 1, 'report', 'HTML report'):
            report(directory, manifest, progress.CURRENT.document())
    context.assert_unchanged(full=True)
    manifest['source_unchanged'] = True
    manifest['status'] = ('no_candidates' if not manifest['clips'] else
                          ('partial' if failures else ('planned' if args.analysis_only else 'complete')))
    manifest['completed'] = sum(c['status']=='complete' for c in manifest['clips'])
    atomic_json(manifest_path, manifest)
    print(f'{manifest["status"]}: {manifest["completed"]} verified videos. Report: {directory / "index.html"}', flush=True)
    return 1 if failures else (2 if not manifest['clips'] else 0)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True, help='Must be inside YTA/output')
    parser.add_argument('--settings', help='Optional JSON overrides for auto_defaults.json')
    parser.add_argument('--count', type=int)
    parser.add_argument('--min-duration', type=float)
    parser.add_argument('--max-duration', type=float)
    parser.add_argument('--min-score', type=float)
    parser.add_argument('--analysis-fps', type=float)
    parser.add_argument('--analysis-width', type=int)
    parser.add_argument('--audio-stream', type=int)
    parser.add_argument('--preset')
    parser.add_argument('--crf', type=int)
    parser.add_argument('--threads', type=int)
    parser.add_argument('--max-seconds', type=float, help='Limit analysis to the first N seconds for a smoke test')
    parser.add_argument('--analysis-only', action='store_true', help='Create plan and previews, without encoding videos')
    parser.add_argument('--resume', action='store_true', help='Reuse the same source/settings/code and continue the run')
    parser.add_argument('--offline', action='store_true', help='Explicit offline mode; all executions are offline')
    parser.add_argument('--review-file', help='Apply exported local review JSON; completed videos cannot be changed')
    parser.add_argument('--framing-mode', choices=('safe', 'close', 'wide'), help='Default composition; low confidence still falls back to wide')
    parser.add_argument('--game-profile', choices=('generic', 'dmc5'), help='Optional calibrated DMC5 title-screen suppression; no event recognition')
    parser.add_argument('--editing-preset',choices=editing.PRESETS,help='Automatic activity suggestion or manual editing preset; uncertain clips remain neutral')
    parser.add_argument('--hook-text',help='User-provided moment hook; no events are inferred')
    parser.add_argument('--title-placement',choices=('auto','top','bottom'),help='Safe text band; auto prefers above gameplay')
    parser.add_argument('--hud-safe-config',help='Local JSON with regions: [[left,top,right,bottom], ...], normalized source coordinates')
    parser.add_argument('--highlight-diversity',type=float,help='0 to 1; diversity preference among comparable-quality clips (default .5)')
    parser.add_argument('--moment-aware-boundaries',action=argparse.BooleanOptionalAction,default=None,help='Activity/context boundary refinement; enabled by default')
    parser.add_argument('--export-candidates',action='store_true',help='Export local candidate metadata and at most 60 sampled frames; never uploads')
    parser.add_argument('--rerank-file',help='Import validated version-1 external scores before review/render; optional, no model execution')
    parser.add_argument('--visual-style', choices=('original','cinematic'), help='Presentation only; automatic default is cinematic')
    parser.add_argument('--theme', choices=tuple(visuals.THEMES), help='Visual accent/title preset; use custom plus --game-title for other games')
    parser.add_argument('--game-title', help='User-supplied title, up to 120 characters; generic/custom themes have no invented title')
    parser.add_argument('--title-style', choices=('minimal','cinematic','bold'), help='Responsive typography preset; default cinematic')
    parser.add_argument('--subtitle', help='Optional user-supplied secondary title line, up to 90 characters')
    parser.add_argument('--context-text', help='Optional user-supplied context, at most 90 characters; never inferred from motion')
    parser.add_argument('--creator-name', help='User-supplied channel name; enables branding unless --no-branding')
    parser.add_argument('--creator-logo', help='Existing local image; enables branding unless --no-branding')
    parser.add_argument('--branding', action=argparse.BooleanOptionalAction, default=None, help='Enable/disable supplied branding')
    parser.add_argument('--progress-line', action=argparse.BooleanOptionalAction, default=None, help='Optional playback progress line; off by default')
    parser.add_argument('--blur-intensity', type=float, help='Cinematic background Gaussian sigma, 0–30 at 135x240 working resolution')
    parser.add_argument('--glow-intensity', type=float, help='Cinematic panel glow opacity, 0–0.5')
    return parser


def main():
    args = build_parser().parse_args()
    cv2.setNumThreads(2)
    try:
        return execute(args)
    except KeyboardInterrupt:
        print('Interrupted. Reuse this command with --resume to continue.', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
