"""Streaming diagnostics for rendered gameplay audio; warnings do not alter the sound."""
import numpy as np
from analyze import decoded_pipe, read_exact


def summarize(blocks,rate,channels,joins=()):
    count=clipped=0;peak=0.;silence=[];quiet_start=None;first=last=None
    join_samples={round(t*rate):t for t in joins};jumps=[];previous=None
    for raw in blocks:
        if len(raw)%(4*channels):
            raise RuntimeError('Truncated audio diagnostic block')
        samples=np.frombuffer(raw,'<f4').reshape(-1,channels)
        if not np.all(np.isfinite(samples)):
            raise RuntimeError('Non-finite rendered audio samples')
        if not len(samples):
            continue
        if first is None:
            first=samples[:max(1,rate//1000)].copy()
        for index,time in join_samples.items():
            local=index-count
            if 0<=local<len(samples) and (local or previous is not None):
                before=samples[local-1] if local else previous
                jump=float(np.abs(samples[local]-before).max())
                if jump>.15:
                    jumps.append(dict(seconds=time,sample_jump=jump))
        last=samples[-max(1,rate//1000):].copy()
        peak=max(peak,float(np.abs(samples).max()))
        clipped+=int((np.abs(samples)>=.999).sum())
        quiet=float(np.sqrt(np.mean(samples**2)))<.0001
        if quiet and quiet_start is None:
            quiet_start=count/rate
        if not quiet and quiet_start is not None:
            if count/rate-quiet_start>=.5:
                silence.append([quiet_start,count/rate])
            quiet_start=None
        count+=len(samples)
        previous=samples[-1].copy()
    if quiet_start is not None and count/rate-quiet_start>=.5:
        silence.append([quiet_start,count/rate])
    if not count:
        raise RuntimeError('No audio decoded for diagnostics')
    fraction=clipped/(count*channels)
    warnings=[]
    if fraction>.001:
        warnings.append('Near-full-scale samples detected; possible clipping (may already be present in the source)')
    edge=max(float(np.abs(first).mean()),float(np.abs(last).mean()))
    if edge>.08:
        warnings.append('Audible energy reaches a clip boundary; possible abrupt cut, review by ear')
    if jumps:
        warnings.append('Sample discontinuity at an explicit edit join; possible click, review by ear')
    return dict(sample_rate=rate,channels=channels,peak=peak,near_full_scale_fraction=fraction,
                duration=count/rate,silence_intervals=silence,edge_mean_absolute=edge,join_discontinuities=jumps,warnings=warnings,
                note='Sample-peak and boundary-energy heuristics, not true-peak mastering or dialogue detection')


def inspect(job):
    rate=int(job.audio.get('sample_rate',48000));channels=job.audio['channels']
    command=[job.executables['ffmpeg'],'-v','error','-nostdin','-threads','2','-i',str(job.target),
             '-t',f'{job.duration:.12f}','-map','0:a:0','-ar',str(rate),'-ac',str(channels),'-f','f32le','pipe:1']
    with decoded_pipe(command) as pipe:
        def blocks():
            while True:
                raw=read_exact(pipe,max(1,rate//10)*channels*4)
                if not raw:
                    break
                yield raw
        return summarize(blocks(),rate,channels,[s['output_start'] for s in getattr(job,'audio_segments',None) or [] if s['output_start']>0])
