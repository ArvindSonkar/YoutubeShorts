"""Presentation presets and a bounded, explicitly timed edit decision list."""
import copy
import math
import moments

PRESETS=('auto','action','funny','cinematic')
EMPTY_EFFECTS={'punch_ins':[], 'slow_motion':[], 'replays':[]}


def finite(value, low, high, name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f'{name} must be a finite number in [{low}, {high}]')


def validate_regions(regions):
    if not isinstance(regions,list) or len(regions)>32:
        raise ValueError('Protected regions must be a list of at most 32 rectangles')
    for box in regions:
        if not isinstance(box,list) or len(box)!=4:
            raise ValueError('Protected rectangles need left, top, right, bottom')
        for value in box:
            finite(value,0,1,'protected coordinate')
        if box[0]>=box[2] or box[1]>=box[3]:
            raise ValueError('Protected rectangles need positive area')


def validate_effects(effects, duration=None):
    if not isinstance(effects,dict) or set(effects)-set(EMPTY_EFFECTS):
        raise ValueError('effects accepts punch_ins, slow_motion and replays lists')
    for name in EMPTY_EFFECTS:
        rows=effects.get(name,[])
        if not isinstance(rows,list) or len(rows)>4:
            raise ValueError(f'effects.{name} requires at most four explicitly timed entries')
        for row in rows:
            if not isinstance(row,dict):
                raise ValueError('Effect entries must be objects')
            finite(row.get('start'),0,duration or 180,'effect start')
        previous=-1
        for row in sorted(rows,key=lambda r:r.get('start',0) if isinstance(r,dict) else 0):
            keys={'start','end','strength'} if name=='punch_ins' else {'start','end','speed','audio'}
            if not isinstance(row,dict) or set(row)-keys or not {'start','end'}<=set(row):
                raise ValueError(f'Invalid {name} entry')
            finite(row['start'],0,duration or 180,'effect start')
            finite(row['end'],0,duration or 180,'effect end')
            if row['end']<=row['start'] or row['start']<previous:
                raise ValueError('Effects of the same type must have positive non-overlapping intervals')
            previous=row['end']
            if row['end']-row['start']>8:
                raise ValueError('Emphasis segments must last at most eight source seconds')
            if name=='punch_ins':
                finite(row.get('strength',.04),0,.1,'punch strength')
            else:
                finite(row.get('speed',.5 if name=='slow_motion' else 1.),.5,1.,'effect speed')
                audio=row.get('audio')
                if audio not in ('stretch','mute','original'):
                    raise ValueError('Timed speed/replay effects require explicit audio: stretch, mute or original')
                if row.get('speed',.5 if name=='slow_motion' else 1.)!=1 and audio=='original':
                    raise ValueError('Slow motion requires pitch-preserving stretch or explicit mute')


def apply(visual, candidate, requested='auto', overrides=None):
    suggestion=candidate.get('suggested_editing') or moments.suggest(candidate.get('reasons',{}))
    selected=suggestion['preset'] if requested=='auto' else requested
    if selected not in ('neutral','action','funny','cinematic'):
        raise ValueError('Unknown editing preset')
    v=copy.deepcopy(visual)
    if selected=='action':
        v['title']['style']='minimal';v['panel'].update(margin=6,padding=6)
    elif selected=='funny':
        v['title']['style']='minimal'
    elif selected=='cinematic':
        v['title']['style']='cinematic';v['panel']['glow']=min(.10,v['panel']['glow'])
    if v['theme']=='gta6':
        v['panel']['glow']=min(.10,v['panel']['glow'])
    # Explicit settings/CLI/review overrides win over presentation presets.
    for section,key,value in overrides or []:
        v[section][key]=value
    return v,dict(requested=requested,selected=selected,suggestion=suggestion,
                  note='Funny is manual only; activity cannot establish humor. No automatic internal jump cuts.')


def timeline(effects,count,fps):
    """Source-frame-relative spans, bounded output map, and matching audio segments."""
    validate_effects(effects,count/fps)
    speeds=[];replays=[]
    for name,store in [('slow_motion',speeds),('replays',replays)]:
        for row in effects.get(name,[]):
            a,b=round(row['start']*fps),round(row['end']*fps)
            if b<=a:
                raise ValueError('Effect interval is shorter than one source frame')
            store.append(dict(start=a,end=b,speed=row.get('speed',.5 if name=='slow_motion' else 1.),audio=row['audio']))
    points=sorted({0,count}|{v[k] for v in speeds+replays for k in ('start','end')})
    segments=[];mapping=[]
    def add(a,b,speed,audio,replay=False):
        n=round((b-a)/speed)
        out=len(mapping)
        if out+n>round(180*fps):
            raise ValueError('Edited output exceeds the 180-second safety limit')
        mapping.extend(min(b-1,a+int(i*speed)) for i in range(n))
        segments.append(dict(start=a/fps,end=b/fps,speed=speed,audio=audio,replay=replay,
                             output_start=out/fps,output_duration=n/fps))
    for a,b in zip(points,points[1:]):
        speed=next((v for v in speeds if v['start']<=a and b<=v['end']),None)
        add(a,b,speed['speed'] if speed else 1.,speed['audio'] if speed else 'original')
        for replay in replays:
            if replay['end']==b:
                add(replay['start'],replay['end'],replay['speed'],replay['audio'],True)
    return mapping,segments


def audio_filter(segments, stream, source_start=0., input_index=1, label='a'):
    """Use the same trim/tempo graph for rendering and independent audio verification."""
    parts=[]
    for i,s in enumerate(segments):
        chain=f'[{input_index}:a:{stream}]atrim=start={source_start+s["start"]:.12f}:end={source_start+s["end"]:.12f},asetpts=PTS-STARTPTS'
        if s['speed']!=1:
            chain+=f',atempo={s["speed"]:.9f}'
        if s['audio']=='mute':
            chain+=',volume=0'
        chain+=f',apad,atrim=duration={s["output_duration"]:.12f}[s{i}]'
        parts.append(chain)
    inputs=''.join(f'[s{i}]' for i in range(len(segments)))
    parts.append(inputs+f'concat=n={len(segments)}:v=0:a=1[{label}]')
    return ';'.join(parts)


def punch(time,effects):
    value=0.
    for row in effects.get('punch_ins',[]):
        if row['start']<=time<=row['end']:
            u=(time-row['start'])/(row['end']-row['start'])
            value+=row.get('strength',.04)*math.sin(math.pi*u)**2
    return min(.10,value)
