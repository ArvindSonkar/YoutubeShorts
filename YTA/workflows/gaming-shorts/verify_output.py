"""Reusable checks for batch outputs, including sampled image and audio alignment."""
from fractions import Fraction
import subprocess

import cv2
import numpy as np

from dynamic_crop import compose, probe


def audio_samples(job, path, start, duration, ordinal=0):
    command = [job.executables['ffmpeg'], '-v', 'error', '-nostdin', '-ss', f'{start:.12f}',
               '-i', str(path), '-t', f'{duration:.12f}', '-map', f'0:a:{ordinal}',
               '-ac', '1', '-ar', '8000', '-f', 'f32le', 'pipe:1']
    return np.frombuffer(subprocess.check_output(command, stderr=subprocess.PIPE), '<f4')


def verify(job, full_decode=True):
    meta = probe(job.target, job.executables)
    video = next(s for s in meta['streams'] if s['codec_type'] == 'video')
    sound = next(s for s in meta['streams'] if s['codec_type'] == 'audio')
    if (video['width'], video['height'], video['codec_name'], video['pix_fmt'],
        Fraction(video['avg_frame_rate']), int(video['nb_frames'])) != (
            job.ow, job.oh, 'h264', 'yuv420p', job.fps, job.count):
        raise RuntimeError('Output dimensions/codec/frame count do not match the job')
    if sound['codec_name'] != 'aac' or sound['channels'] != job.audio['channels']:
        raise RuntimeError('Output audio stream does not match the job')
    if abs(float(meta['format']['duration'])-job.duration) > max(.06, 1/float(job.fps)):
        raise RuntimeError('Output duration does not match the job')
    if full_decode:
        subprocess.run([job.executables['ffmpeg'], '-v', 'error', '-xerror', '-nostdin',
                        '-i', str(job.target), '-f', 'null', '-'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    source = cv2.VideoCapture(str(job.source))
    output = cv2.VideoCapture(str(job.target))
    errors = []
    try:
        for index in sorted(set([0, job.count//2, job.count-1])):
            source.set(cv2.CAP_PROP_POS_FRAMES, job.first+index)
            output.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok1, original = source.read(); ok2, encoded = output.read()
            if not ok1 or not ok2:
                raise RuntimeError('Verification could not decode sampled frames')
            expected = compose(original, job.plan[index], job.config, job.layer)
            error = float(np.abs(expected.astype(np.float32)-encoded).mean())
            if error > 15:
                raise RuntimeError(f'Output/source composition mismatch at frame {index}: {error:.2f}')
            errors.append({'frame': index, 'mean_absolute_error': error})
    finally:
        source.release(); output.release()
    audio_checks = []
    # Bounded windows near both ends catch a trim offset and accumulated drift.
    for offset in sorted(set([0., max(0., job.duration-2.)])):
        duration = min(2., job.duration-offset)
        original = audio_samples(job, job.source, job.start+offset, duration, job.config['audio']['stream'])
        encoded = audio_samples(job, job.target, offset, duration)
        size = min(len(original), len(encoded))
        if size < 1 or abs(len(original)-len(encoded)) > 512:
            raise RuntimeError('Audio verification sample lengths differ')
        original, encoded = original[:size], encoded[:size]
        rms = float(np.sqrt(np.mean(original**2)))
        encoded_rms = float(np.sqrt(np.mean(encoded**2)))
        correlation = None
        if rms > .0001 and np.std(original) > .0001:
            correlation = float(np.corrcoef(original, encoded)[0, 1])
            if not np.isfinite(correlation) or correlation < .85:
                raise RuntimeError(f'Audio alignment check failed at +{offset:.3f}s: {correlation}')
        elif encoded_rms > .002:
            raise RuntimeError('Silent source window acquired unexpected output audio')
        audio_checks.append({'offset': offset, 'correlation': correlation,
                             'source_rms': rms, 'output_rms': encoded_rms,
                             'note': 'Silent/constant windows have no meaningful correlation' if correlation is None else 'Aligned'})
    return {'frames': job.count, 'dimensions': [job.ow, job.oh], 'duration': job.duration,
            'fps': str(job.fps), 'frame_checks': errors, 'audio_checks': audio_checks,
            'full_decode_passed': True, 'note': 'Technical checks do not measure entertainment value.'}
