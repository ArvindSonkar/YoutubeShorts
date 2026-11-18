"""Local, configurable gaming Shorts editor. No downloads, uploads, or overwrite mode."""
from __future__ import annotations

import argparse
from bisect import bisect_right
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from progress import stage, checked_output, decode_check

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULTS = HERE / 'defaults.json'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def merge(base, updates):
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if key not in base:
            raise ValueError(f'Unknown configuration key: {key}')
        if isinstance(base[key], dict) and isinstance(value, dict):
            result[key] = merge(base[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def project_path(value):
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def writable_path(value):
    path = project_path(value)
    if not path.is_relative_to(ROOT):
        raise ValueError('Output/config/artifact paths must stay inside the YTA project')
    return path


def generated_path(value):
    """Generated media/artifacts are disposable and belong only under output/."""
    path = writable_path(value)
    if not path.is_relative_to(ROOT / 'output'):
        raise ValueError('Generated videos and artifacts must stay inside YTA/output')
    return path


def write_new_json(path, data):
    path = writable_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write('\n')


def digest(path, label='Checksum'):
    h = hashlib.sha256()
    with stage(label, Path(path).stat().st_size, 'bytes', 'Checksums') as meter, Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
            meter.update(handle.tell())
    return h.hexdigest()


def tools(config):
    folder = project_path(config['tools_directory'])
    result = {}
    for name in ('ffmpeg', 'ffprobe'):
        matches = list(folder.rglob(name + '.exe'))
        if len(matches) != 1:
            raise ValueError(f'Expected one portable {name}.exe under {folder}; found {len(matches)}. No software will be installed.')
        result[name] = str(matches[0])
    return result


def probe(path, executables):
    return json.loads(subprocess.check_output([executables['ffprobe'], '-v', 'error',
        '-show_streams', '-show_format', '-of', 'json', str(path)], encoding='utf-8'))


def seconds(value):
    parts = str(value).split(':')
    if len(parts) > 3:
        raise ValueError('Use seconds, MM:SS.mmm, or HH:MM:SS.mmm')
    result = Fraction(0)
    for part in parts:
        result = result * 60 + Fraction(part)
    if result < 0:
        raise ValueError('Times cannot be negative')
    return result


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number in [{low}, {high}]')


def validate(config):
    if config['schema_version'] != 1 or config['preferred_style'] != 'dynamic_crop':
        raise ValueError('Only schema_version 1 / dynamic_crop is supported')
    for section in ('framing', 'smoothing', 'impacts', 'background', 'hook'):
        if type(config[section]['enabled']) is not bool:
            raise ValueError(f'{section}.enabled must be true or false')
    v = config['video']
    for key in ('width', 'height', 'threads'):
        if type(v[key]) is not int or v[key] <= 0:
            raise ValueError(f'video.{key} must be a positive integer')
    if v['width'] % 2 or v['height'] % 2 or v['width'] * 16 != v['height'] * 9:
        raise ValueError('Video dimensions must be even and exactly 9:16')
    number(v['crf'], 'video.crf', 0, 40)
    if v['preset'] not in ('ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'):
        raise ValueError('Unsupported libx264 preset')
    if type(config['audio']['stream']) is not int or config['audio']['stream'] < 0:
        raise ValueError('audio.stream must be a nonnegative audio-stream ordinal')
    f = config['framing']
    number(f['min_width'], 'framing.min_width', .01, 1)
    number(f['max_width'], 'framing.max_width', f['min_width'], 1)
    number(f['max_upscale'], 'framing.max_upscale', 1, 4)
    number(f['subject_padding'], 'framing.subject_padding', 0, .25)
    previous = -1
    for key in f['keyframes']:
        if set(key) - {'time', 'center', 'width', 'protect_box'}:
            raise ValueError('Keyframes accept time, center, width, protect_box only')
        number(key['time'], 'keyframe.time', 0, 86400)
        if key['time'] <= previous:
            raise ValueError('Keyframe times must strictly increase')
        previous = key['time']
        if len(key['center']) != 2:
            raise ValueError('center must be [x,y]')
        for coordinate in key['center']:
            number(coordinate, 'center', 0, 1)
        number(key['width'], 'keyframe.width', .01, 1)
        if 'protect_box' in key:
            box = key['protect_box']
            if len(box) != 4:
                raise ValueError('protect_box must be [left,top,right,bottom]')
            for coordinate in box:
                number(coordinate, 'protect_box', 0, 1)
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError('protect_box must have positive area')
    s = config['smoothing']
    if s['interpolation'] not in ('smoothstep', 'linear'):
        raise ValueError('smoothing.interpolation must be smoothstep or linear')
    for key in ('max_pan_per_second', 'max_width_change_per_second'):
        number(s[key], key, .01, 10)
    effects = config['impacts']
    number(effects['max_strength'], 'impacts.max_strength', 0, .10)
    number(effects['strength'], 'impacts.strength', 0, effects['max_strength'])
    number(effects['sigma_seconds'], 'impacts.sigma_seconds', .04, 2)
    for time in effects['times']:
        number(time, 'impact time', 0, 86400)
    b = config['background']
    number(b['blur_sigma'], 'background.blur_sigma', 0, 30)
    number(b['brightness'], 'background.brightness', 0, 1)
    for section, key in (('background','color'), ('hook','accent'), ('hook','text_color')):
        if len(config[section][key]) != 3:
            raise ValueError(f'{section}.{key} must be RGB')
        for value in config[section][key]:
            number(value, f'{section}.{key}', 0, 255)
    h = config['hook']
    if type(h['animated']) is not bool:
        raise ValueError('hook.animated must be a boolean')
    for key in ('duration', 'fade_in', 'fade_out'):
        number(h[key], 'hook.' + key, .01, 60)
    number(h['initial_opacity'], 'hook.initial_opacity', 0, 1)
    number(h['slide_pixels'], 'hook.slide_pixels', 0, 100)
    number(h['font_size'], 'hook.font_size', 20, 200)
    number(h['panel_opacity'], 'hook.panel_opacity', 0, 255)
    if not isinstance(h['kicker'], str) or not isinstance(h['lines'], list) or any(not isinstance(x,str) for x in h['lines']):
        raise ValueError('Hook text must be strings')
    if h['enabled'] and not 1 <= len(h['lines']) <= 2:
        raise ValueError('Enabled hooks require one or two lines')
    if len(h['position']) != 2 or len(h['size']) != 2 or len(h['safe_area']) != 4:
        raise ValueError('Hook position/size need two values; safe_area needs four')
    for value in h['position'] + h['size'] + h['safe_area']:
        number(value, 'hook position/size/safe_area', 0, 1)
    if min(h['size']) <= 0:
        raise ValueError('Hook size must be positive')
    x,y = h['position']; w,height = h['size']; left,top,right,bottom = h['safe_area']
    if not (left < right and top < bottom and x >= left and y >= top and x+w <= right and y+height+h['slide_pixels']/1920 <= bottom):
        raise ValueError('Hook panel plus animation must fit the configured safe area')


class SourceContext:
    """Share one source probe/checksum across a batch; detect changes between jobs."""
    def __init__(self, source, executables):
        self.source = project_path(source)
        self.executables = executables
        self.signature = self.stat_signature()
        with stage('Source probing', category='Source preparation'):
            self.meta = probe(self.source, executables)
        self.sha256 = digest(self.source, 'Source checksum')
        self.assert_unchanged()

    def stat_signature(self):
        stat = self.source.stat()
        return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def assert_unchanged(self, full=False):
        if self.stat_signature() != self.signature or (full and digest(self.source, 'Final source integrity checksum') != self.sha256):
            raise RuntimeError('Source changed during processing; start a new run')


class Job:
    def __init__(self, config, source_context=None):
        validate(config)
        self.config = config
        self.executables = source_context.executables if source_context else tools(config)
        self.source = project_path(config['source'])
        self.target = generated_path(config['output'])
        if self.source.suffix.lower() != '.mp4' or not self.source.is_file():
            raise ValueError('source must identify an existing local MP4')
        if self.target.suffix.lower() != '.mp4' or self.source == self.target:
            raise ValueError('output must be a different .mp4 path')
        self.source_context = source_context
        if source_context is not None:
            if source_context.source != self.source:
                raise ValueError('Shared source context belongs to another file')
            source_context.assert_unchanged()
        self.meta = source_context.meta if source_context else probe(self.source, self.executables)
        self.video = next((s for s in self.meta['streams'] if s['codec_type'] == 'video'), None)
        if self.video is None:
            raise ValueError('Source has no video stream')
        if self.video.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
            raise ValueError('HDR source needs an explicit SDR conversion first; automatic tone mapping is not configured')
        if self.video.get('color_space') not in (None, 'unknown', 'bt709'):
            raise ValueError('This renderer currently supports SDR BT.709 sources only')
        audios = [s for s in self.meta['streams'] if s['codec_type'] == 'audio']
        if config['audio']['stream'] >= len(audios):
            raise ValueError('Requested original audio stream is absent; silent substitution is not allowed')
        self.audio = audios[config['audio']['stream']]
        self.sw, self.sh = self.video['width'], self.video['height']
        self.ow, self.oh = config['video']['width'], config['video']['height']
        if self.sw / self.sh < self.ow / self.oh:
            raise ValueError('Source must be at least as wide as 9:16; use landscape gameplay')
        if self.video.get('sample_aspect_ratio', '1:1') not in ('1:1','0:1','N/A'):
            raise ValueError('Non-square source pixels are unsupported; no conversion performed')
        rotation = float(self.video.get('tags', {}).get('rotate', 0))
        rotation += sum(float(s.get('rotation',0)) for s in self.video.get('side_data_list', []))
        if rotation % 360 or abs(float(self.video.get('start_time',0))) > .001:
            raise ValueError('Rotated or nonzero-start video timelines are unsupported; no source changes made')
        self.fps = Fraction(self.video['avg_frame_rate'])
        if self.fps <= 0 or abs(float(self.fps-Fraction(self.video['r_frame_rate']))) > .001:
            raise ValueError('Variable-frame-rate source detected; this workflow requires CFR gameplay')
        clip = config['clip']
        if 'start_frame' in clip or 'end_frame' in clip:
            if type(clip.get('start_frame')) is not int or type(clip.get('end_frame')) is not int:
                raise ValueError('Frame selection needs integer start_frame and end_frame')
            self.first, self.last = clip['start_frame'], clip['end_frame']
        else:
            self.first = round(seconds(clip['start']) * self.fps)
            self.last = round(seconds(clip['end']) * self.fps)
        duration = self.video.get('duration', self.meta.get('format', {}).get('duration'))
        total = int(self.video['nb_frames']) if self.video.get('nb_frames', 'N/A') != 'N/A' else round(float(duration) * float(self.fps))
        if not 0 <= self.first < self.last <= total:
            raise ValueError('Clip bounds must fall within the source; out point is exclusive')
        self.count = self.last-self.first
        self.start, self.end = float(self.first/self.fps), float(self.last/self.fps)
        self.duration = self.end-self.start
        self.source_hash = source_context.sha256 if source_context else digest(self.source)
        if config['expected_source_sha256'] and self.source_hash != config['expected_source_sha256'].lower():
            raise ValueError('Source checksum differs from the configured example')
        self.layer = make_hook(config, self.ow, self.oh) if config['hook']['enabled'] else None
        self.plan = camera_plan(config, self.sw, self.sh, self.ow, self.oh, float(self.fps), self.count)

    def check_timestamps(self):
        # Read only the selected interval (plus the preceding keyframe), then check its PTS grid.
        response = checked_output([self.executables['ffprobe'], '-v', 'error',
            '-select_streams','v:0','-read_intervals',f'{max(0,self.start-1):.9f}%{self.end+.1:.9f}',
            '-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(self.source)], 'Source frame timestamps')
        pts = [float(f['best_effort_timestamp_time']) for f in json.loads(response)['frames'] if 'best_effort_timestamp_time' in f]
        selected = sorted(t for t in pts if self.start-.00001 <= t < self.end-.00001)
        if len(selected) != self.count or any(abs(t-(self.first+i)/float(self.fps)) > .0001 for i,t in enumerate(selected)):
            raise ValueError('Source frame timestamps do not match a CFR grid; cannot guarantee audio sync')


def ease(value):
    return value*value*(3-2*value)


def target_at(config, time, key_times=None):
    keys = config['framing']['keyframes']
    if not config['framing']['enabled'] or not keys:
        return np.array([.5,.5,1.0]), None
    a,b = keys[0],keys[0]
    if time >= keys[-1]['time']:
        a=b=keys[-1]
    elif time > keys[0]['time']:
        position = bisect_right(key_times if key_times is not None else [k['time'] for k in keys], time)
        a, b = keys[position-1], keys[position]
    u = 0 if a['time']==b['time'] else (time-a['time'])/(b['time']-a['time'])
    if config['smoothing']['enabled'] and config['smoothing']['interpolation']=='smoothstep':
        u=ease(u)
    values = np.array(a['center']+[a['width']])*(1-u)+np.array(b['center']+[b['width']])*u
    box = None
    if 'protect_box' in a and 'protect_box' in b:
        box=np.array(a['protect_box'])*(1-u)+np.array(b['protect_box'])*u
    return values,box


def camera_plan(config, sw, sh, ow, oh, fps, count):
    aspect=ow/oh
    f,s,imp=config['framing'],config['smoothing'],config['impacts']
    previous=None
    result=[]
    key_times = [key['time'] for key in f['keyframes']]
    for index in range(count):
        t=index/fps
        desired,box=target_at(config,t,key_times)
        if f['enabled'] and imp['enabled']:
            punch=min(imp['max_strength'],sum(imp['strength']*math.exp(-((t-p)/imp['sigma_seconds'])**2) for p in imp['times']))
            desired[2]/=1+punch
        if s['enabled'] and previous is not None:
            limits=np.array([s['max_pan_per_second'],s['max_pan_per_second'],s['max_width_change_per_second']])/fps
            desired=previous+np.clip(desired-previous,-limits,limits)
        if f['enabled']:
            desired[2]=max(f['min_width'],min(f['max_width'],desired[2]),ow/(sw*f['max_upscale']))
        else:
            desired=np.array([.5,.5,1.0])
        cx,cy=desired[0]*sw,desired[1]*sh
        width=min(sw,desired[2]*sw)
        if box is not None:
            padding=f['subject_padding']
            left,top,right,bottom=np.clip(box+np.array([-padding,-padding,padding,padding]),0,1)
            # Widen around the smoothed center before moving it abruptly to follow a subject.
            width=min(sw,max(width,2*max(cx-left*sw,right*sw-cx),
                             2*max(cy-top*sh,bottom*sh-cy)*aspect))
        height=min(sh,width/aspect)
        x=max(0,min(sw-width,cx-width/2))
        y=max(0,min(sh-height,cy-height/2))
        # Center clipping at a source edge is safe; a full-width fallback includes the whole source.
        previous=np.array([(x+width/2)/sw,(y+height/2)/sh,width/sw])
        result.append({'frame':index,'seconds':t,'x':x,'y':y,'width':width,'height':height,
                       'upscale':ow/width,'protected_box':box.tolist() if box is not None else None})
    return result


def make_hook(config, ow, oh):
    h=config['hook']; scale=ow/1080
    width,height=round(ow*h['size'][0]),round(oh*h['size'][1])
    layer=Image.new('RGBA',(width,height),(0,0,0,0))
    d=ImageDraw.Draw(layer)
    font_path=project_path(h['font'])
    if not font_path.is_file():
        raise ValueError(f'Hook font is unavailable: {font_path}; set hook.font or disable hook')
    d.rounded_rectangle((0,0,width-1,height-1),radius=round(18*scale),fill=(7,10,19,int(h['panel_opacity'])))
    accent=tuple(int(v) for v in h['accent'])+(255,)
    d.rectangle((0,round(15*scale),max(1,round(6*scale)),height-round(15*scale)),fill=accent)
    left=round(30*scale)
    available=width-left*2
    def fitted(text, size):
        while size >= max(10,round(20*scale)):
            font=ImageFont.truetype(str(font_path),size)
            if d.textbbox((0,0),text,font=font)[2] <= available:
                return font
            size-=1
        raise ValueError('Hook text is too long for the safe panel; shorten it')
    kicker=fitted(h['kicker'],max(10,round(32*scale)))
    d.text((left,round(25*scale)),h['kicker'],font=kicker,fill=accent)
    for i,line in enumerate(h['lines']):
        font=fitted(line,round(h['font_size']*scale))
        top=round((70+i*103)*scale)
        bounds=d.textbbox((left,top),line,font=font)
        if bounds[3] > height-10*scale:
            raise ValueError('Hook lines exceed panel height; reduce font_size or increase size')
        d.text((left,top),line,font=font,fill=tuple(int(v) for v in h['text_color'])+(255,))
    return cv2.cvtColor(np.array(layer),cv2.COLOR_RGBA2BGRA)


def compose(frame, geometry, config, layer=None):
    ow,oh=config['video']['width'],config['video']['height']
    sw,sh=frame.shape[1],frame.shape[0]
    x,y,w,h=(geometry[k] for k in ('x','y','width','height'))
    fh=min(oh,max(1,round(h*ow/w)))
    transform=np.array([[w/ow,0,x],[0,h/fh,y]],dtype=np.float32)
    fg=cv2.warpAffine(frame,transform,(ow,fh),flags=cv2.INTER_LANCZOS4|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
    if fh<oh:
        b=config['background']
        if b['enabled']:
            cropw=max(1,min(sw,round(sh*ow/oh)))
            small=cv2.resize(frame[:,(sw-cropw)//2:(sw+cropw)//2],(135,240),interpolation=cv2.INTER_AREA)
            if b['blur_sigma']>0:
                small=cv2.GaussianBlur(small,(0,0),b['blur_sigma'])
            small=(small.astype(np.float32)*b['brightness']).astype(np.uint8)
            canvas=cv2.resize(small,(ow,oh),interpolation=cv2.INTER_LINEAR)
        else:
            canvas=np.full((oh,ow,3),list(reversed(b['color'])),dtype=np.uint8)
        top=(oh-fh)//2
        canvas[top:top+fh]=fg
    else:
        canvas=fg
    h=config['hook']; t=geometry['seconds']
    if layer is not None and t<h['duration']:
        enter=ease(min(1,t/h['fade_in'])) if h['animated'] else 1
        leave=ease(max(0,min(1,(h['duration']-t)/h['fade_out']))) if h['animated'] else 1
        alpha=(h['initial_opacity']+(1-h['initial_opacity'])*enter)*leave
        left=round(ow*h['position'][0])
        top=round(oh*h['position'][1]+h['slide_pixels']*(ow/1080)*(1-enter))
        roi=canvas[top:top+layer.shape[0],left:left+layer.shape[1]]
        mask=layer[:,:,3:4].astype(np.float32)/255*alpha
        roi[:]=(roi*(1-mask)+layer[:,:,:3]*mask).astype(np.uint8)
    return canvas


def artifacts(path, job):
    path=generated_path(path)
    path.mkdir(parents=True,exist_ok=False)
    write_new_json(path/'effective-config.json',job.config)
    write_new_json(path/'source-ffprobe.json',job.meta)
    write_new_json(path/'camera-plan.json',job.plan)
    return path


def capture(job, index, decoder=None):
    cap=decoder if decoder is not None else cv2.VideoCapture(str(job.source))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES,job.first+index)
        ok,frame=cap.read()
        if not ok or round(cap.get(cv2.CAP_PROP_POS_FRAMES))-1 != job.first+index:
            raise ValueError(f'Source seek failed at frame {job.first+index}')
        return frame
    finally:
        if decoder is None:
            cap.release()


def preview(job, directory, raw=False, step=1):
    directory=artifacts(directory,job)
    indices=sorted(set([0,job.count-1]+list(range(0,job.count,max(1,round(float(job.fps)*step))))))
    columns=3 if raw else 4
    per_sheet=columns*3
    decoder=cv2.VideoCapture(str(job.source))
    try:
        # Retain at most one sheet of thumbnails and reuse the open decoder.
        for start in range(0,len(indices),per_sheet):
            tiles=[]
            for index in indices[start:start+per_sheet]:
                frame=capture(job,index,decoder)
                if not raw:
                    frame=compose(frame,job.plan[index],job.config,job.layer)
                rgb=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                rgb.save(directory/f'frame-{index:06d}.jpg',quality=93)
                width=432 if raw else 216
                height=round(width*rgb.height/rgb.width)
                tile=Image.new('RGB',(width,height+24),'#11151c')
                tile.paste(rgb.resize((width,height)),(0,24))
                ImageDraw.Draw(tile).text((6,6),f'+{index/float(job.fps):.3f}s | source {job.first+index}',fill='white')
                tiles.append(tile)
            sheet=Image.new('RGB',(columns*tiles[0].width,math.ceil(len(tiles)/columns)*tiles[0].height),'#11151c')
            for i,tile in enumerate(tiles):
                sheet.paste(tile,((i%columns)*tile.width,(i//columns)*tile.height))
            sheet.save(directory/f'sheet-{start//per_sheet+1:02d}.jpg',quality=93)
    finally:
        decoder.release()
    print(f'{len(indices)} frames saved to {directory}')


def render(job, label='Rendering Short'):
    if job.target.exists():
        raise FileExistsError(f'Refusing to overwrite existing video: {job.target}')
    if job.config['framing']['enabled'] and not job.config['framing']['keyframes']:
        raise ValueError('Dynamic rendering needs reviewed crop keyframes; use inspect and edit the job JSON first')
    job.check_timestamps()
    directory=artifacts(job.target.with_suffix('.work'),job)
    job.target.parent.mkdir(parents=True,exist_ok=True)
    pending=job.target.with_name(job.target.stem+'.partial.mp4')
    if pending.exists():
        raise FileExistsError(f'Existing partial render: {pending}; choose a fresh output name')
    v,a=job.config['video'],job.config['audio']
    command=[job.executables['ffmpeg'],'-hide_banner','-nostdin','-n',
        '-f','rawvideo','-pix_fmt','bgr24','-s',f'{job.ow}x{job.oh}','-r',str(job.fps),'-i','pipe:0',
        '-ss',f'{job.start:.12f}','-i',str(job.source),'-filter_complex',
        f'[1:a:{a["stream"]}]atrim=duration={job.duration:.12f},asetpts=PTS-STARTPTS[a]',
        '-map','0:v:0','-map','[a]','-c:v','libx264','-preset',v['preset'],'-crf',str(v['crf']),
        '-threads',str(v['threads']),'-vf','scale=out_color_matrix=bt709:out_range=tv,setsar=1',
        '-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',
        '-pix_fmt','yuv420p','-fps_mode','cfr',
        '-video_track_timescale',str(job.fps.numerator),'-c:a','aac','-b:a',str(a['bitrate']),
        '-map_metadata','-1','-map_chapters','-1','-movflags','+faststart','-t',f'{job.duration:.12f}',str(pending)]
    write_new_json(directory/'command.json',command)
    cap=cv2.VideoCapture(str(job.source))
    cap.set(cv2.CAP_PROP_POS_FRAMES,job.first)
    with stage(label, job.count, 'frames', 'Rendering') as meter, (directory/'render.log').open('x',encoding='utf-8') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        try:
            for index in range(job.count):
                ok,frame=cap.read()
                if not ok or round(cap.get(cv2.CAP_PROP_POS_FRAMES))-1 != job.first+index:
                    raise ValueError('Decoder frame position changed unexpectedly')
                process.stdin.write(compose(frame,job.plan[index],job.config,job.layer).tobytes())
                meter.update(index+1)
            process.stdin.close()
            # All input frames have been submitted, but buffered encoding is not done.
            # Its remaining duration is unknown; do not display a fabricated zero ETA.
            meter.name, meter.total = label+' (finalizing encoder)', None
            meter.update(force=True)
            while process.poll() is None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    meter.update()
            if process.returncode!=0:
                raise RuntimeError(f'FFmpeg failed; inspect {directory / "render.log"}')
            meter.name, meter.total = label, job.count
        except BaseException:
            process.kill(); process.wait()
            raise
        finally:
            cap.release()
    result=probe(pending,job.executables)
    vs=next(s for s in result['streams'] if s['codec_type']=='video')
    aus=next(s for s in result['streams'] if s['codec_type']=='audio')
    if (vs['width'],vs['height'],vs['codec_name'],Fraction(vs['avg_frame_rate']),int(vs['nb_frames'])) != (job.ow,job.oh,'h264',job.fps,job.count):
        raise RuntimeError('Output video verification failed; partial retained')
    if aus['codec_name']!='aac' or aus['channels']!=job.audio['channels']:
        raise RuntimeError('Output audio verification failed; partial retained')
    if abs(float(result['format']['duration'])-job.duration)>max(.06,1/float(job.fps)):
        raise RuntimeError('Output duration verification failed; partial retained')
    decode_check(job.executables['ffmpeg'], pending, job.duration)
    if job.source_context:
        job.source_context.assert_unchanged()
    elif digest(job.source)!=job.source_hash:
        raise RuntimeError('Source changed during rendering')
    write_new_json(directory/'output-ffprobe.json',result)
    write_new_json(directory/'verification.json',{'source_sha256':job.source_hash,
        'source_unchanged':True,'duration_seconds':job.duration,'source_start_frame':job.first,
        'source_end_frame_exclusive':job.last,'frame_count':job.count,'fps':str(job.fps),
        'video':'h264','audio':'aac','channels':aus['channels'],
        'maximum_upscale':max(p['upscale'] for p in job.plan),
        'note':'Original audio retained and AAC re-encoded; no normalization, music, or sound effects.'})
    # Windows rename refuses existing destinations; never replace a completed file.
    if job.target.exists():
        raise FileExistsError('Output was created by another process; partial retained')
    pending.rename(job.target)
    print(f'Verified output: {job.target}',flush=True)


def load_job(path):
    data=read_json(path)
    defaults=read_json(DEFAULTS)
    # Frame-based selection is an explicit alternative to time-based selection.
    if 'clip' in data:
        clip=data.pop('clip')
    else:
        clip=defaults['clip']
    if set(clip) not in ({'start','end'},{'start_frame','end_frame'}):
        raise ValueError('clip needs either start/end or start_frame/end_frame, not both')
    config=merge(defaults,data)
    config['clip']=clip
    return Job(config)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('doctor',help='Check existing portable tools and local Python libraries')
    init=sub.add_parser('init',help='Write a new job template without guessing a crop path')
    for arg in ('input','output','config','start','end'):
        init.add_argument('--'+arg,required=True)
    for action in ('inspect','preview','render','check'):
        command=sub.add_parser(action)
        command.add_argument('--config',required=True)
        if action in ('inspect','preview'):
            command.add_argument('--out-dir',required=True)
            command.add_argument('--step',type=float,default=1)
    args=parser.parse_args()
    cv2.setNumThreads(2)
    if args.action=='doctor':
        config=read_json(DEFAULTS)
        executables=tools(config)
        for name,exe in executables.items():
            print(subprocess.check_output([exe,'-version'],encoding='utf-8').splitlines()[0])
        encoders=subprocess.check_output([executables['ffmpeg'],'-hide_banner','-encoders'],encoding='utf-8',stderr=subprocess.STDOUT)
        for encoder in ('libx264','aac'):
            if not any(len(line.split())>1 and line.split()[1]==encoder for line in encoders.splitlines()):
                raise ValueError(f'Required encoder unavailable: {encoder}')
        print('Required H.264/AAC encoders available.')
        print(f'Hook font available: {project_path(config["hook"]["font"]).is_file()}; free workspace disk: {shutil.disk_usage(ROOT).free / 1024**3:.1f} GiB')
        print(f'OpenCV {cv2.__version__}; NumPy {np.__version__}; Pillow available. No installation performed.')
        return
    if args.action=='init':
        config=read_json(DEFAULTS)
        config.update(source=args.input,output=args.output,clip={'start':args.start,'end':args.end})
        job=Job(config)
        job.check_timestamps()
        # Store frame-aligned boundaries explicitly; raw user timestamps may be rounded.
        config['clip']={'start_frame':job.first,'end_frame':job.last}
        config['expected_source_sha256']=job.source_hash
        write_new_json(args.config,config)
        print(f'Created {args.config}. Inspect source frames, then add normalized crop keyframes; none were invented.')
        return
    job=load_job(args.config)
    if args.action in ('inspect','preview'):
        number(args.step,'--step',.03,60)
        preview(job,args.out_dir,raw=args.action=='inspect',step=args.step)
    elif args.action=='check':
        job.check_timestamps()
        print(json.dumps({'source':str(job.source),'output':str(job.target),'fps':str(job.fps),
            'frames':job.count,'duration':job.duration,'source_dimensions':[job.sw,job.sh],
            'max_upscale':max(p['upscale'] for p in job.plan),
            'warnings':['No crop keyframes yet; inspect and add them before dynamic rendering.'] if job.config['framing']['enabled'] and not job.config['framing']['keyframes'] else []},indent=2))
    else:
        render(job)


if __name__=='__main__':
    try:
        main()
    except (ValueError,FileExistsError,FileNotFoundError,RuntimeError,KeyError,subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        sys.exit(1)
