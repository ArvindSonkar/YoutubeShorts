"""Action-aware local reframing. Original frames/audio stay in chronological order."""
import argparse
import hashlib
import json
import math
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from render_short import ROOT, OUT, SOURCE, START, END, EXPECTED_SOURCE_HASH, executable, probe

FPS = 29.97
COUNT = 615
FIRST = OUT / 'mourning-thunder-final.mp4'
FIRST_HASH = '66cc9038abf1120e009010a8adf1227ae1542154f40095220d2f71824b03b367'
ASSETS = OUT / 'comparison'
cv2.setNumThreads(2)

# Seconds relative to source frame 5694; centers/widths measured in source pixels.
TRACK = [
    (0,645,420),(.5,670,420),(1,650,440),(1.5,620,440),(2,635,440),
    (2.5,650,460),(3,610,500),(3.5,640,500),(4,670,460),(4.5,765,580),
    (5,675,480),(5.5,620,440),(6,660,430),(6.5,665,500),(7,670,450),
    (7.5,635,430),(8,620,460),(8.5,500,620),(9,500,620),(9.5,600,540),
    (10,650,500),(10.30,700,480),(10.36,720,480),(10.50,690,480),
    (10.67,620,480),(10.84,550,480),(11,500,480),(11.18,450,480),
    (11.30,470,480),(11.5,660,500),(12,620,540),(12.5,640,540),
    (13,620,520),(13.5,600,480),(14,640,480),(14.5,600,430),
    (15,600,460),(15.5,650,520),(16,625,560),(16.5,620,520),
    (17,630,520),(17.5,600,520),(18,590,460),(18.5,640,430),
    (19,640,460),(19.55,640,580),(20.53,640,580)]

# Wider geometry and HUD passages explicitly use the complete source frame.
HYBRID = [(0,520),(1.5,560),(2.5,720),(2.75,1280),(4.6,1280),
          (4.95,650),(7.6,650),(8,1280),(10.28,1280),
          (10.36,480),(11.30,480),(11.56,1280),(13.15,1280),
          (13.40,620),(14.55,620),(14.90,1280),(18.10,1280),
          (18.45,660),(18.75,660),(19.10,1280),(20.53,1280)]


def ease(v):
    return v*v*(3-2*v)


def interp(keys, t, column=1):
    for a,b in zip(keys,keys[1:]):
        if a[0] <= t <= b[0]:
            u=ease((t-a[0])/(b[0]-a[0]))
            return a[column]*(1-u)+b[column]*u
    return keys[0][column] if t<keys[0][0] else keys[-1][column]


def typography(mode):
    layer=Image.new('RGBA',(900,330),(0,0,0,0))
    d=ImageDraw.Draw(layer)
    accent=(193,158,255,255) if mode=='dynamic' else (240,212,158,255)
    d.rounded_rectangle((0,0,870,320),radius=18,fill=(7,10,19,190))
    d.rounded_rectangle((0,15,7,305),radius=3,fill=accent)
    font='C:/Windows/Fonts/arialbd.ttf'
    d.text((34,25),'MOURNING THUNDER',font=ImageFont.truetype(font,32),fill=accent)
    lines=['FINAL','MOMENTS'] if mode=='dynamic' else ['THE FINAL','EXCHANGE']
    for y,line in zip((70,173),lines):
        d.text((30,y),line,font=ImageFont.truetype(font,100),fill=(247,247,252,255))
    return cv2.cvtColor(np.array(layer),cv2.COLOR_RGBA2BGRA)


TITLE={name:typography(name) for name in ('dynamic','hybrid')}


def victory_title():
    layer=Image.new('RGBA',(900,210),(0,0,0,0))
    d=ImageDraw.Draw(layer)
    font='C:/Windows/Fonts/arialbd.ttf'
    d.text((28,6),'DIFFICULTY 5',font=ImageFont.truetype(font,32),fill=(240,212,158,255))
    d.text((23,54),'CLEARED',font=ImageFont.truetype(font,112),fill=(247,247,252,255),
           stroke_width=2,stroke_fill=(0,0,0,150))
    d.rectangle((28,190,160,194),fill=(240,212,158,255))
    return cv2.cvtColor(np.array(layer),cv2.COLOR_RGBA2BGRA)


VICTORY=victory_title()


def geometry(t,mode):
    center=interp(TRACK,t)
    width=interp(TRACK,t,2) if mode=='dynamic' else interp(HYBRID,t)
    # Small, eased punches only on observed impacts; never add flashes or shake.
    pulse=sum(0.028*math.exp(-((t-p)/.16)**2) for p in (1.0,11.65,13.55))
    if mode=='hybrid' and width>1000:
        pulse=0  # retain full-width geometry on wide effects
    width/=1+pulse
    height=min(714,width*16/9)
    center_y=357
    if width>=1279:
        center=640
    # Blend center toward the middle when the frame widens to avoid edge clamp jumps.
    if mode=='hybrid' and width>760:
        u=(width-760)/(1280-760)
        center=center*(1-u)+640*u
    x=max(0,min(1280-width,center-width/2))
    y=max(0,min(714-height,center_y-height/2))
    return x,y,width,height


def compose(frame,index,mode):
    t=index/FPS
    x,y,w,h=geometry(t,mode)
    fh=min(1920,round(h*1080/w))
    # Subpixel affine mapping makes camera movement smooth rather than integer-step crops.
    matrix=np.array([[w/1080,0,x],[0,h/fh,y]],dtype=np.float32)
    foreground=cv2.warpAffine(frame,matrix,(1080,fh),flags=cv2.INTER_LANCZOS4|cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REPLICATE)
    if fh<1920:
        bg=cv2.resize(frame[:,439:841],(135,240),interpolation=cv2.INTER_AREA)
        bg=cv2.GaussianBlur(bg,(0,0),9)
        bg=(bg.astype(np.float32)*.48).astype(np.uint8)
        canvas=cv2.resize(bg,(1080,1920),interpolation=cv2.INTER_LINEAR)
        top=(1920-fh)//2
        canvas[top:top+fh]=foreground
    else:
        canvas=foreground
    if t<2.50:
        enter=ease(min(1,t/.24))
        leave=ease(max(0,min(1,(2.50-t)/.28)))
        # Visible from first frame; small lift/fade settles within seven frames.
        opacity=(.45+.55*enter)*leave
        title=TITLE[mode]
        top=180+round(24*(1-enter))
        left=84
        roi=canvas[top:top+title.shape[0],left:left+title.shape[1]]
        alpha=title[:,:,3:4].astype(np.float32)/255*opacity
        roi[:]=(roi*(1-alpha)+title[:,:,:3]*alpha).astype(np.uint8)
    if mode=='hybrid' and index>=592:
        # Appears only after the original completion banner is visible in the source.
        opacity=ease(min(1,(index-592)/5))
        top=382+round(12*(1-opacity))
        roi=canvas[top:top+VICTORY.shape[0],100:100+VICTORY.shape[1]]
        alpha=VICTORY[:,:,3:4].astype(np.float32)/255*opacity
        roi[:]=(roi*(1-alpha)+VICTORY[:,:,:3]*alpha).astype(np.uint8)
    return canvas


def assert_originals():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==EXPECTED_SOURCE_HASH
    if FIRST.exists():
        assert hashlib.sha256(FIRST.read_bytes()).hexdigest()==FIRST_HASH


def previews():
    ASSETS.mkdir(parents=True, exist_ok=True)
    indices=[6,45,135,165,255,285,330,375,405,450,495,540,570,600,610]
    cap=cv2.VideoCapture(str(SOURCE))
    for mode in ('dynamic','hybrid'):
        tiles=[]
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES,5694+index)
            ok,frame=cap.read()
            assert ok
            result=compose(frame,index,mode)
            cv2.imwrite(str(ASSETS/f'{mode}-planned-{index:03d}.jpg'),result,[cv2.IMWRITE_JPEG_QUALITY,92])
            im=Image.fromarray(cv2.cvtColor(result,cv2.COLOR_BGR2RGB)).resize((270,480))
            tile=Image.new('RGB',(270,504),'#101218')
            tile.paste(im,(0,24))
            ImageDraw.Draw(tile).text((8,6),f'{tstamp(index)} | {mode}',fill='white')
            tiles.append(tile)
        for offset in range(0,len(tiles),8):
            subset=tiles[offset:offset+8]
            sheet=Image.new('RGB',(1080,1008),'#101218')
            for j,tile in enumerate(subset):
                sheet.paste(tile,((j%4)*270,(j//4)*504))
            sheet.save(ASSETS/f'{mode}-planned-sheet-{offset//8+1}.jpg',quality=93)
    cap.release()


def tstamp(index):
    return f'{index/FPS:.2f}s'


def render(mode):
    ASSETS.mkdir(parents=True, exist_ok=True)
    target=OUT/f'mourning-thunder-{mode}.mp4'
    if target.exists():
        raise RuntimeError(f'Refusing to overwrite {target}')
    command=[executable('ffmpeg'),'-hide_banner','-nostdin','-n',
             '-f','rawvideo','-pix_fmt','bgr24','-s','1080x1920','-r','2997/100','-i','pipe:0',
             '-i',str(SOURCE),'-filter_complex',
             f'[1:a:0]atrim=start={START:.12f}:end={END:.12f},asetpts=PTS-STARTPTS[a]',
             '-map','0:v:0','-map','[a]','-c:v','libx264','-preset','medium','-crf','18',
             '-threads','4','-pix_fmt','yuv420p','-fps_mode','cfr','-video_track_timescale','11988',
             '-c:a','aac','-b:a','192k','-map_metadata','-1','-map_chapters','-1',
             '-movflags','+faststart','-t',f'{END-START:.12f}',str(target)]
    (ASSETS/f'{mode}-command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
    cap=cv2.VideoCapture(str(SOURCE))
    cap.set(cv2.CAP_PROP_POS_FRAMES,5694)
    with (ASSETS/f'{mode}-render.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        try:
            for index in range(COUNT):
                ok,frame=cap.read()
                assert ok
                proc.stdin.write(compose(frame,index,mode).tobytes())
                if index%150==0:
                    print(f'{mode}: {index}/{COUNT} frames',flush=True)
            proc.stdin.close()
            if proc.wait()!=0:
                raise RuntimeError(f'FFmpeg failed; see {mode}-render.log')
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        finally:
            cap.release()
    result=probe(target)
    (ASSETS/f'{mode}-ffprobe.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    v=next(s for s in result['streams'] if s['codec_type']=='video')
    a=next(s for s in result['streams'] if s['codec_type']=='audio')
    assert (v['width'],v['height'],v['codec_name'],v['avg_frame_rate'],int(v['nb_frames']))==(1080,1920,'h264','2997/100',615)
    assert a['codec_name']=='aac' and a['channels']==2
    assert abs(float(result['format']['duration'])-(END-START))<.06
    subprocess.run([executable('ffmpeg'),'-v','error','-i',str(target),'-f','null','-'],check=True)
    assert_originals()
    print(f'VERIFIED {target.name}: {result["format"]["duration"]} s, 1080x1920, 29.97 fps, H.264/AAC',flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--preview',action='store_true')
    p.add_argument('--render',choices=['dynamic','hybrid','both'])
    args=p.parse_args()
    assert_originals()
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS/'framing-plan.json').write_text(json.dumps({'source_start_frame':5694,
        'source_out_frame_exclusive':6309,'track_columns':['relative_seconds','source_center_x','dynamic_source_width'],
        'dynamic_track':TRACK,'hybrid_width_keyframes':HYBRID},indent=2),encoding='utf-8')
    if args.preview:
        previews()
    if args.render:
        for mode in (['dynamic','hybrid'] if args.render=='both' else [args.render]):
            render(mode)


if __name__=='__main__':
    main()
