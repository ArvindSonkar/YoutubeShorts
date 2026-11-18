"""Read-only local MP4 inspection using existing OpenCV and Pillow installs."""
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

import cv2
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def atoms(data, start=0, end=None):
    end = len(data) if end is None else end
    while start + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, start)
        header = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, start + 8)[0]
            header = 16
        elif size == 0:
            size = end - start
        if size < header or start + size > end:
            break
        yield kind.decode('ascii', errors='replace'), data[start + header:start + size]
        start += size


def child(data, name):
    return next((body for kind, body in atoms(data) if kind == name), None)


def metadata(path, cap):
    data = path.read_bytes()
    moov = child(data, 'moov')
    mvhd = child(moov, 'mvhd')
    movie_offset = 20 if mvhd[0] == 1 else 12
    movie_scale = struct.unpack_from('>I', mvhd, movie_offset)[0]
    movie_duration = struct.unpack_from('>Q' if mvhd[0] == 1 else '>I', mvhd, movie_offset + 4)[0]
    tracks = []
    for kind, body in atoms(moov):
        if kind != 'trak':
            continue
        mdia = child(body, 'mdia')
        mdhd, hdlr = child(mdia, 'mdhd'), child(mdia, 'hdlr')
        offset = 20 if mdhd[0] == 1 else 12
        scale = struct.unpack_from('>I', mdhd, offset)[0]
        duration = struct.unpack_from('>Q' if mdhd[0] == 1 else '>I', mdhd, offset + 4)[0]
        stbl = child(child(mdia, 'minf'), 'stbl')
        stsd = child(stbl, 'stsd')
        entries = []
        for codec, entry in atoms(stsd, 8):
            info = {'codec_tag': codec}
            handler = hdlr[8:12].decode('ascii')
            if handler == 'soun':
                info.update(channels_sample_entry=struct.unpack_from('>H', entry, 16)[0],
                            sample_size_bits=struct.unpack_from('>H', entry, 18)[0],
                            sample_rate_hz=struct.unpack_from('>I', entry, 24)[0] / 65536)
            if handler == 'vide':
                info.update(width=struct.unpack_from('>H', entry, 24)[0],
                            height=struct.unpack_from('>H', entry, 26)[0])
            entries.append(info)
        track = {'handler': hdlr[8:12].decode('ascii'), 'timescale': scale,
                 'duration_seconds': duration / scale, 'sample_entries': entries}
        stts = child(stbl, 'stts')
        if stts:
            count = struct.unpack_from('>I', stts, 4)[0]
            runs = [struct.unpack_from('>II', stts, 8 + i * 8) for i in range(count)]
            track['sample_count'] = sum(n for n, delta in runs)
            track['sample_duration_ticks'] = sorted(set(delta for n, delta in runs))
            if track['handler'] == 'vide':
                deltas = [delta for n, delta in runs for _ in range(n)]
                ctts = child(stbl, 'ctts')
                offsets = [0] * len(deltas)
                if ctts:
                    ct_count = struct.unpack_from('>I', ctts, 4)[0]
                    ct_runs = [struct.unpack_from('>Ii' if ctts[0] else '>II', ctts, 8 + i * 8)
                               for i in range(ct_count)]
                    offsets = [value for n, value in ct_runs for _ in range(n)]
                edts = child(body, 'edts')
                elst = child(edts, 'elst') if edts else None
                media_start = 0
                if elst:
                    if elst[0] != 0 or struct.unpack_from('>I', elst, 4)[0] != 1:
                        raise ValueError('Unsupported edit-list structure')
                    media_start = struct.unpack_from('>i', elst, 12)[0]
                dts, pts = 0, []
                for delta, composition_offset in zip(deltas, offsets):
                    pts.append(dts + composition_offset - media_start)
                    dts += delta
                pts.sort()
                track['presentation_start_seconds'] = pts[0] / scale
                track['presentation_frame_grid_verified'] = all(t == i * deltas[0] for i, t in enumerate(pts))
                if not track['presentation_frame_grid_verified']:
                    raise ValueError('Presentation timestamps do not match the assumed frame grid')
        tracks.append(track)
    return {'file': str(path.resolve()), 'bytes': len(data),
            'movie_duration_seconds': movie_duration / movie_scale,
            'sha256': hashlib.sha256(data).hexdigest(), 'tracks': tracks,
            'opencv': {'version': cv2.__version__, 'backend': cap.getBackendName(),
                       'width': cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                       'height': cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
                       'fps': cap.get(cv2.CAP_PROP_FPS),
                       'frame_count': cap.get(cv2.CAP_PROP_FRAME_COUNT)}}


def timestamp(t):
    return f'{int(t // 60):02}:{t % 60:06.3f}'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--end', type=float)
    p.add_argument('--step', type=float, default=5)
    p.add_argument('--width', type=int, default=384)
    p.add_argument('--columns', type=int, default=3)
    p.add_argument('--label', default='overview')
    args = p.parse_args()
    candidates = list((ROOT / 'videos').glob('*.mp4'))
    if len(candidates) != 1:
        raise SystemExit(f'Expected one MP4; found {len(candidates)}')
    path = candidates[0]
    out = ROOT / 'output' / 'frames'
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit('OpenCV could not open the video')
    info = metadata(path, cap)
    (ROOT / 'output' / 'video-metadata.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    print(json.dumps(info, indent=2))
    fps = info['opencv']['fps']
    frames = int(info['opencv']['frame_count'])
    end = min(args.end if args.end is not None else frames / fps, (frames - 1) / fps)
    records, tiles = [], []
    t = args.start
    while t <= end + 1e-7:
        index = round(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f'Decode failed at frame {index}')
        actual_index = round(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if actual_index != index:
            raise RuntimeError(f'Seek mismatch: wanted {index}, got {actual_index}')
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        filename = f'{args.label}_{index:06d}.jpg'
        image.save(out / filename, quality=92)
        height = round(args.width * image.height / image.width)
        tile = Image.new('RGB', (args.width, height + 28), '#111111')
        tile.paste(image.resize((args.width, height)), (0, 28))
        ImageDraw.Draw(tile).text((8, 7), f'{timestamp(index / fps)} | frame {index}', fill='white')
        tiles.append(tile)
        records.append({'file': filename, 'frame_index': index, 'seconds': index / fps})
        t += args.step
    for offset in range(0, len(tiles), 18):
        subset = tiles[offset:offset + 18]
        sheet = Image.new('RGB', (args.columns * subset[0].width,
                                  math.ceil(len(subset) / args.columns) * subset[0].height), '#222222')
        for i, tile in enumerate(subset):
            sheet.paste(tile, ((i % args.columns) * tile.width, (i // args.columns) * tile.height))
        sheet_path = out / f'{args.label}_sheet_{offset // 18 + 1:02d}.jpg'
        sheet.save(sheet_path, quality=92)
        print(f'SHEET {sheet_path}')
    (out / f'{args.label}_index.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    cap.release()


if __name__ == '__main__':
    main()
