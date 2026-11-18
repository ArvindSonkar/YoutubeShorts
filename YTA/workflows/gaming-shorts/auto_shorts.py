"""One-command offline gameplay highlights. No API keys, models, or downloads."""
from contextlib import contextmanager
from fractions import Fraction
import argparse
import copy
import hashlib
import html
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


def code_signature():
    names = ['auto_shorts.py', 'analyze.py', 'select_highlights.py', 'autoframe.py',
             'dynamic_crop.py', 'verify_output.py', 'defaults.json']
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


def thumbnail(job, path):
    # One contact strip per clip, using the same source composition as rendering.
    sheet = Image.new('RGB', (648, 408), '#11151c')
    draw = ImageDraw.Draw(sheet)
    for column, index in enumerate((0, job.count//2, job.count-1)):
        frame = compose(capture(job, index), job.plan[index], job.config, job.layer)
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((216, 384))
        sheet.paste(image, (column*216, 24))
        draw.text((column*216+5, 5), f'+{index/float(job.fps):.2f}s', fill='white')
    sheet.save(path, quality=88)


def report(directory, manifest):
    rows = []
    for entry in manifest.get('clips', []):
        rank = entry['candidate']['rank']
        item = entry['candidate']
        image = f'clips/short-{rank:02d}.jpg'
        video = f'clips/short-{rank:02d}.mp4'
        rows.append(f'<article><h2>#{rank}: {html.escape(entry["status"])}</h2>'
                    f'<p>{item["start"]:.2f}–{item["end"]:.2f}s · action score {item["score"]:.3f}</p>'
                    f'<p>Full-width fallback: {entry["framing"]["fallback_fraction"]:.0%}</p>'
                    f'<img src="{image}" width="648" alt="Planned start, middle and ending frames">'
                    + (f'<p><a href="{video}">Play Short</a></p>' if entry['status']=='complete' else '')
                    + f'<p>{html.escape(entry.get("error", ""))}</p></article>')
    message = manifest.get('message', '')
    document = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Local gameplay highlights</title>'
                '<style>body{font:16px system-ui;background:#11151c;color:#edf0f7;max-width:900px;margin:40px auto;padding:16px}'
                'article{background:#202631;padding:20px;margin:20px 0}img{max-width:100%;height:auto}a{color:#a9ccff}</style>'
                '<h1>Local gameplay highlights</h1><p>Heuristic action scores; no event labels or object identity.</p>'
                f'<p>{html.escape(message)}</p>' + ''.join(rows) + '</html>')
    (directory/'index.html').write_text(document, encoding='utf-8')


def make_config(defaults, source, target, candidate, data, settings, context):
    config = copy.deepcopy(defaults)
    fps = Fraction(next(s for s in context.meta['streams'] if s['codec_type']=='video')['avg_frame_rate'])
    first, last = round(candidate['start']*fps), round(candidate['end']*fps)
    config.update(source=str(source), output=str(target), expected_source_sha256=context.sha256,
                  clip={'start_frame': first, 'end_frame': last})
    config['audio']['stream'] = settings['audio_stream']
    config['video'].update(preset=settings['preset'], crf=settings['crf'], threads=settings['threads'])
    config['framing']['keyframes'], framing = autoframe.keyframes(
        data, float(first/fps), float(last/fps), settings, float(fps))
    # Automatic pulses are omitted: motion peaks do not prove that an impact happened.
    config['impacts']['enabled'] = False
    config['smoothing'].update(max_pan_per_second=.30, max_width_change_per_second=.35)
    return config, framing


def execute(args):
    settings = read_json(HERE/'auto_defaults.json')
    if args.settings:
        settings = merge(settings, read_json(args.settings))
    for key in settings:
        value = getattr(args, key, None)
        if value is not None:
            settings[key] = value
    validate_settings(settings)
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
        return run(args, settings, source, directory)


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
    cache = directory/'features.npz'
    if cache.exists():
        print('Reusing cached audiovisual features.', flush=True)
        data = analyze.load_features(cache, signature)
    else:
        data = analyze.scan(context, duration, settings)
        analyze.save_features(cache, data, signature)
    if not manifest.get('selection_done'):
        candidates, scores = select_highlights.candidate_windows(data, duration, settings)
        selected = select_highlights.choose(candidates, settings['count'], duration, settings['min_gap'])
        atomic_json(directory/'candidates.json', {'candidates': candidates, 'selected': selected,
                    'note': 'Heuristic activity scores, not event recognition or predicted views.'})
        np.savez_compressed(directory/'scores.npz', time=data['time'], score=scores)
        (directory/'clips').mkdir(exist_ok=True)
        for candidate in selected:
            rank = candidate['rank']
            target = directory/'clips'/f'short-{rank:02d}.mp4'
            config, framing = make_config(defaults, source, target, candidate, data, settings, context)
            entry = {'candidate': candidate, 'config': config, 'framing': framing, 'status': 'pending', 'attempts': 0}
            manifest['clips'].append(entry)
            atomic_json(target.with_suffix('.json'), config)
        manifest['selection_done'] = True
        manifest['message'] = f'Selected {len(selected)} of requested {settings["count"]} clips. '
        if len(selected) < settings['count']:
            manifest['message'] += 'Fewer non-overlapping candidates met the quality threshold.'
        atomic_json(manifest_path, manifest)
    print(manifest['message'], flush=True)
    failures = 0
    for entry in manifest['clips']:
        job = Job(entry['config'], context)
        image = job.target.with_suffix('.jpg')
        if not image.exists():
            thumbnail(job, image)
        if args.analysis_only:
            continue
        rank = entry['candidate']['rank']
        try:
            if job.target.exists():
                if entry['status'] == 'complete' and entry.get('output_sha256') == digest(job.target):
                    print(f'[{rank}] Verified completed output checksum; skipping.', flush=True)
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
                render(job)
                result = verify(job, full_decode=False)  # render already did a complete decode.
            atomic_json(job.target.with_suffix('.qa.json'), result)
            entry.update(status='complete', output_sha256=digest(job.target))
            entry.pop('error', None)
        except Exception as exc:
            entry.update(status='failed', error=str(exc))
            failures += 1
            print(f'[{rank}] FAILED: {exc}', file=sys.stderr, flush=True)
        atomic_json(manifest_path, manifest)
        report(directory, manifest)
    context.assert_unchanged(full=True)
    manifest['source_unchanged'] = True
    manifest['status'] = ('no_candidates' if not manifest['clips'] else
                          ('planned' if args.analysis_only else ('partial' if failures else 'complete')))
    manifest['completed'] = sum(c['status']=='complete' for c in manifest['clips'])
    atomic_json(manifest_path, manifest)
    report(directory, manifest)
    print(f'{manifest["status"]}: {manifest["completed"]} verified videos. Report: {directory / "index.html"}', flush=True)
    return 1 if failures else (2 if not manifest['clips'] else 0)


def main():
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
    args = parser.parse_args()
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
