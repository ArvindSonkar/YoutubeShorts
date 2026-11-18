"""Inspect the rendered Short's frame alignment and retained gameplay audio."""
import json
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw

from render_short import SOURCE, TARGET, OUT, START, END, executable


def audio(path, source=False):
    cmd = [executable('ffmpeg'), '-v', 'error', '-i', str(path), '-map', '0:a:0']
    if source:
        cmd += ['-af', f'atrim=start={START:.12f}:end={END:.12f},asetpts=PTS-STARTPTS']
    cmd += ['-ac', '1', '-ar', '8000', '-f', 'f32le', '-']
    return np.frombuffer(subprocess.check_output(cmd), dtype='<f4')


def main():
    if not TARGET.is_file():
        raise SystemExit('No rendered Short to verify. Run workflows/legacy/render_short.py first.')
    src, dst = cv2.VideoCapture(str(SOURCE)), cv2.VideoCapture(str(TARGET))
    frame_indexes = [0, 59, 60, 150, 330, 608]
    tiles, comparisons = [], []
    for index in frame_indexes:
        dst.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = dst.read()
        assert ok
        src.set(cv2.CAP_PROP_POS_FRAMES, 5694 + index)
        ok, original = src.read()
        assert ok
        foreground = frame[659:1261, 0:1080]
        reference = cv2.resize(original, (1080, 602), interpolation=cv2.INTER_LANCZOS4)
        error = float(np.abs(foreground.astype(float) - reference.astype(float)).mean())
        comparisons.append({'output_frame': index, 'source_frame': index + 5694,
                            'foreground_mean_absolute_pixel_error': error})
        assert error < 8, f'Unexpected source-frame mismatch: {error}'
        im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        im.save(OUT / f'preview-frame-{index:03d}.jpg', quality=94)
        tile = Image.new('RGB', (360, 666), '#111111')
        tile.paste(im.resize((360, 640)), (0, 26))
        ImageDraw.Draw(tile).text((8, 7), f'{index / 29.97:.3f}s | frame {index}', fill='white')
        tiles.append(tile)
    src.release()
    dst.release()
    sheet = Image.new('RGB', (1080, 1332))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 3) * 360, (i // 3) * 666))
    sheet.save(OUT / 'preview-contact-sheet.jpg', quality=94)
    original_audio, encoded_audio = audio(SOURCE, True), audio(TARGET)
    length = min(len(original_audio), len(encoded_audio))
    correlation = float(np.corrcoef(original_audio[:length], encoded_audio[:length])[0, 1])
    assert correlation > 0.95, f'Audio correspondence needs investigation: {correlation}'
    results = {'frame_comparisons': comparisons,
               'audio_correlation_mono_8khz': correlation,
               'reference_audio_samples_8khz': len(original_audio),
               'output_audio_samples_8khz': len(encoded_audio),
               'note': 'Original gameplay audio retained; AAC re-encoding is lossy, not bit-identical.'}
    (OUT / 'content-validation.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
