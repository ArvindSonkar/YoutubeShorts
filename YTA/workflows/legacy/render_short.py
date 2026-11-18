"""Render the approved Short with project-local FFmpeg; never overwrite source/output."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output' / 'shorts'
SOURCE = ROOT / 'videos' / 'Wuthering Waves Mourning Thunder Difficulty_ 5 Defeated l PS5.mp4'
TARGET = OUT / 'mourning-thunder-final.mp4'
EXPECTED_SOURCE_HASH = '7b171b7d822d660ef46d2e926bccf9ffd5f79ff71ac8f458a11ac019884c9819'
START, END = 5694 / 29.97, 6309 / 29.97


def executable(name):
    found = list((ROOT / 'tools' / 'ffmpeg').rglob(name + '.exe'))
    if len(found) != 1:
        raise RuntimeError(f'Expected exactly one local {name}.exe, found {len(found)}')
    return str(found[0])


def probe(path):
    return json.loads(subprocess.check_output([
        executable('ffprobe'), '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', str(path)], text=True, encoding='utf-8'))


def main():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != EXPECTED_SOURCE_HASH:
        raise RuntimeError('Source differs from the inspected file')
    if TARGET.exists():
        raise RuntimeError('Output already exists; refusing to overwrite it')
    OUT.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in ('ffmpeg', 'ffprobe'):
        versions[name] = subprocess.check_output([executable(name), '-version'], text=True)
    (OUT / 'tool-versions.txt').write_text('\n'.join(versions.values()), encoding='utf-8')
    (OUT / 'source-ffprobe.json').write_text(json.dumps(probe(SOURCE), indent=2), encoding='utf-8')
    (OUT / 'hook-line-1.txt').write_text('MOURNING THUNDER \u2014', encoding='utf-8')
    (OUT / 'hook-line-2.txt').write_text('FINAL MOMENTS!', encoding='utf-8')
    font = "fontfile='C\\:/Windows/Fonts/arialbd.ttf'"
    hook = "enable='lt(t,2)'"
    graph = (
        '[0:v:0]trim=start_frame=5694:end_frame=6309,setpts=PTS-STARTPTS,split=2[bg0][fg0];'
        '[bg0]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,'
        'gblur=sigma=12,eq=brightness=-0.13:saturation=0.65,scale=1080:1920[bg];'
        '[fg0]scale=1080:602:flags=lanczos,setsar=1[fg];'
        '[bg][fg]overlay=x=0:y=659:shortest=1,'
        f'drawbox=x=60:y=458:w=960:h=170:color=black@0.65:t=fill:{hook},'
        f'drawtext={font}:textfile=output/shorts/hook-line-1.txt:fontsize=60:'
        f'fontcolor=white:x=(w-text_w)/2:y=480:borderw=2:bordercolor=black:{hook},'
        f'drawtext={font}:textfile=output/shorts/hook-line-2.txt:fontsize=64:'
        f'fontcolor=white:x=(w-text_w)/2:y=556:borderw=2:bordercolor=black:{hook},'
        'setsar=1,format=yuv420p[v];'
        f'[0:a:0]atrim=start={START:.12f}:end={END:.12f},asetpts=PTS-STARTPTS[a]'
    )
    (OUT / 'render-filter.txt').write_text(graph, encoding='utf-8')
    command = [executable('ffmpeg'), '-hide_banner', '-nostdin', '-n', '-threads', '4',
               '-i', str(SOURCE), '-filter_complex_threads', '2', '-filter_complex', graph,
               '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium',
               '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
               '-r', '2997/100', '-fps_mode', 'cfr', '-video_track_timescale', '11988',
               '-c:a', 'aac', '-b:a', '192k', '-map_metadata', '-1', '-map_chapters', '-1',
               '-movflags', '+faststart', '-t', f'{END-START:.12f}', str(TARGET)]
    (OUT / 'render-command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
    print('Rendering 615 frames, duration', END-START, flush=True)
    with (OUT / 'render.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = probe(TARGET)
    (OUT / 'mourning-thunder-final.ffprobe.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    video = next(s for s in result['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in result['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height'], video['codec_name']) == (1080, 1920, 'h264')
    assert video['avg_frame_rate'] == '2997/100'
    assert int(video['nb_frames']) == 615
    assert audio['codec_name'] == 'aac'
    assert abs(float(result['format']['duration']) - (END-START)) < 0.06
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED_SOURCE_HASH
    subprocess.run([executable('ffmpeg'), '-v', 'error', '-nostdin', '-i', str(TARGET),
                    '-f', 'null', '-'], check=True)
    print(json.dumps({'output': str(TARGET), 'duration': result['format']['duration'],
                      'resolution': [video['width'], video['height']],
                      'fps': video['avg_frame_rate'], 'frames': video['nb_frames'],
                      'video_codec': video['codec_name'], 'audio_codec': audio['codec_name'],
                      'audio_channels': audio['channels'], 'audio_sample_rate': audio['sample_rate'],
                      'source_unchanged': True}, indent=2), flush=True)


if __name__ == '__main__':
    main()
