"""Streaming local audiovisual features. No models, services, or network access."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np

VERSION = 1


def read_exact(pipe, size):
    data = bytearray()
    while len(data) < size:
        chunk = pipe.read(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


@contextmanager
def decoded_pipe(command):
    """Drain stderr to disk to avoid deadlocks; always reap interrupted decoders."""
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            yield process.stdout
            if process.wait() != 0:
                log.seek(0)
                raise RuntimeError('Analysis decode failed: ' + log.read()[-3000:].decode('utf-8', 'replace'))
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()


def fingerprint(gray):
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).reshape(-1)
    return format(int(''.join('1' if bit else '0' for bit in bits), 2), '016x')


def visual_features(previous, gray):
    """Residual motion is an action cue, not a person/vehicle detector."""
    height, width = gray.shape
    base = {'motion': 0., 'camera': 0., 'change': 0., 'cut': 0.,
            'brightness': float(gray.mean() / 255),
            'sharpness': float(cv2.Laplacian(gray, cv2.CV_32F).var()),
            'center': [.5, .5], 'box': [0., 0., 1., 1.], 'confidence': 0.,
            'fingerprint': fingerprint(gray)}
    if previous is None:
        return base
    hist_a = cv2.calcHist([previous], [0], None, [32], [0, 256])
    hist_b = cv2.calcHist([gray], [0], None, [32], [0, 256])
    cv2.normalize(hist_a, hist_a, norm_type=cv2.NORM_L1)
    cv2.normalize(hist_b, hist_b, norm_type=cv2.NORM_L1)
    change = float(np.abs(gray.astype(np.float32) - previous).mean() / 255)
    cut = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_BHATTACHARYYA) > .62 and change > .18
    base.update(change=change, cut=float(cut))
    if cut:
        return base
    # Estimate global camera translation, then measure unexplained/local changes.
    window = cv2.createHanningWindow((width, height), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(previous.astype(np.float32), gray.astype(np.float32), window)
    reliable = response > .12 and abs(dx) < width * .2 and abs(dy) < height * .2
    if not reliable:
        dx = dy = 0.
    aligned = cv2.warpAffine(previous, np.float32([[1, 0, dx], [0, 1, dy]]),
                             (width, height), borderMode=cv2.BORDER_REPLICATE)
    diff = cv2.absdiff(gray, aligned)
    mask = (diff > max(18., float(np.percentile(diff, 65)))).astype(np.uint8)
    # Ignore outer HUD and exposed borders; do not use them as a tracking target.
    mx, my = max(round(width * .10), int(abs(dx)) + 2), max(round(height * .12), int(abs(dy)) + 2)
    mask[:my] = 0; mask[-my:] = 0; mask[:, :mx] = 0; mask[:, -mx:] = 0
    base['motion'] = float(mask.mean())
    base['camera'] = float(min(1., np.hypot(dx / width, dy / height) * 8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    choices = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        fraction = area / (width * height)
        if .008 <= fraction <= .30:
            center = centers[i] / np.array([width, height])
            priority = fraction * max(.1, 1 - np.linalg.norm(center - .5))
            choices.append((priority, i))
    if choices and base['motion'] < .38:
        _, i = max(choices)
        x, y, w, h, area = stats[i]
        dominance = area / max(1, int(mask.sum()))
        confidence = min(1., dominance * 1.4) * min(1., area / (width * height * .025))
        base.update(center=(centers[i] / [width, height]).tolist(),
                    box=[x / width, y / height, (x+w) / width, (y+h) / height],
                    confidence=float(confidence))
    return base


def scan_video(source, executable, duration, fps, width, source_size):
    height = max(2, round(width * source_size[1] / source_size[0] / 2) * 2)
    command = [executable, '-v', 'error', '-nostdin', '-threads', '2', '-i', str(source),
               '-t', str(duration), '-map', '0:v:0', '-an', '-filter_threads', '1',
               '-vf', f'fps={fps},scale={width}:{height}:flags=area',
               '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1']
    rows, previous = [], None
    with decoded_pipe(command) as pipe:
        index = 0
        while True:
            raw = read_exact(pipe, width * height)
            if not raw:
                break
            if len(raw) != width * height:
                raise RuntimeError('Truncated analysis frame')
            gray = np.frombuffer(raw, np.uint8).reshape(height, width)
            row = visual_features(previous, gray)
            row['time'] = index / fps
            rows.append(row)
            previous = gray
            index += 1
            if index % max(1, round(fps * 60)) == 0:
                print(f'Analyzed video {index / fps:.0f}/{duration:.0f}s', flush=True)
    if len(rows) < 2 or len(rows) / fps < duration - max(1., 2 / fps):
        raise RuntimeError('Video analysis ended early or produced too few samples')
    return {key: np.asarray([row[key] for row in rows]) for key in rows[0]}


def scan_audio(source, executable, duration, fps, stream=0):
    rate = 16000
    block = round(rate / fps)
    command = [executable, '-v', 'error', '-nostdin', '-threads', '2', '-i', str(source),
               '-t', str(duration), '-map', f'0:a:{stream}', '-vn', '-ac', '1', '-ar', str(rate),
               '-f', 'f32le', 'pipe:1']
    rows, previous = [], None
    with decoded_pipe(command) as pipe:
        while True:
            raw = read_exact(pipe, block * 4)
            if not raw:
                break
            if len(raw) % 4:
                raise RuntimeError('Truncated analysis audio')
            samples = np.frombuffer(raw, '<f4')
            rms = float(np.sqrt(np.mean(samples * samples)))
            spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)), n=block))
            spectrum /= max(float(spectrum.sum()), 1e-9)
            flux = float(np.maximum(spectrum - previous, 0).sum()) if previous is not None else 0.
            rows.append([20 * np.log10(max(rms, 1e-6)), flux, float(np.max(np.abs(samples)))])
            previous = spectrum
    if not rows:
        raise RuntimeError('No audio samples decoded')
    return np.asarray(rows), block / rate


def scan(source_context, duration, settings):
    video = next(s for s in source_context.meta['streams'] if s['codec_type'] == 'video')
    fps = settings['analysis_fps']
    data = scan_video(source_context.source, source_context.executables['ffmpeg'], duration, fps,
                      settings['analysis_width'], (video['width'], video['height']))
    print('Analyzing audio...', flush=True)
    sound, step = scan_audio(source_context.source, source_context.executables['ffmpeg'], duration,
                              fps, settings['audio_stream'])
    times = np.arange(len(sound)) * step
    for column, name in enumerate(('audio_db', 'audio_flux', 'audio_peak')):
        data[name] = np.interp(data['time'], times, sound[:, column])
    source_context.assert_unchanged()
    return data


def save_features(path, data, signature):
    path = Path(path)
    pending = path.with_suffix('.tmp')
    with pending.open('wb') as handle:
        np.savez_compressed(handle, signature=np.asarray(json.dumps(signature, sort_keys=True)), **data)
    pending.replace(path)


def load_features(path, signature):
    with np.load(path, allow_pickle=False) as archive:
        if json.loads(str(archive['signature'])) != signature:
            raise ValueError('Analysis cache belongs to different settings/source')
        return {key: archive[key] for key in archive.files if key != 'signature'}
