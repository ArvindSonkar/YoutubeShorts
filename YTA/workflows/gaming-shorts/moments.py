"""Bounded activity context and edit suggestions; no event or dialogue recognition."""
import numpy as np


def average(values, samples):
    values=np.asarray(values,dtype=float)
    n=max(1,min(len(values),round(samples)))
    return np.convolve(np.pad(values,(n//2,n-1-n//2),mode='edge'),np.ones(n)/n,mode='valid')


def signals(data, fps):
    motion=np.clip(data['motion']/.15,0,1)
    sound=np.clip((data['audio_db']+55)/35,0,1)
    change=np.clip(data['change']/.12,0,1)
    activity=.60*motion+.20*np.clip(data['camera'],0,1)+.20*change
    fast=average(activity,fps)
    surrounding=average(activity,12*fps)
    contrast=np.clip((fast-surrounding)*2,0,1)
    onset=np.clip(fast-np.roll(fast,max(1,round(fps))),0,1)
    onset[:max(1,round(fps))]=0
    still=(data['motion']<.004)&(data['camera']<.025)&(data['change']<.01)
    static=average(still,4*fps)
    transition=average(data['cut'],2*fps)
    penalty=np.maximum(data.get('screen_penalty',np.zeros(len(activity))),
                       np.clip((static-.65)/.35,0,1)*.85)
    penalty=np.maximum(penalty,(data['brightness']<.018)*.95)
    # Quiet candidates need visible evolving detail plus changing audio; never silence alone.
    subtle=np.clip(data['motion']/.018,0,1)*np.clip(data['change']/.035,0,1)
    quiet=subtle*(1-np.clip(data['motion']/.12,0,1))*(.55+.45*np.clip(data['audio_flux']/.18,0,1))
    quiet*=np.clip((data['brightness']-.018)/.06,0,1)*(1-penalty)*(1-np.clip(transition*3,0,1))
    return dict(motion=motion,audio=sound,activity=activity,contrast=contrast,onset=onset,
                quiet=average(quiet,2*fps),screen=penalty,transition=transition)


def boundaries(data,scores,peak,duration,settings):
    """Find an activity envelope; preserve context/audio continuity when space permits."""
    times=data['time'];fps=settings['analysis_fps'];t=float(times[peak])
    lo,hi=settings['min_duration'],settings['max_duration']
    threshold=max(.10,float(scores[peak])*.40)
    left=right=peak
    while left>0 and t-times[left]<hi*.6 and scores[left-1]>=threshold and data['cut'][left]<.5:
        left-=1
    while right+1<len(times) and times[right]-t<hi*.7 and scores[right+1]>=threshold and data['cut'][right+1]<.5:
        right+=1
    envelope=float(times[right]-times[left])
    manual=settings.get('editing_preset','auto')
    target=25. if envelope>12 or manual in ('funny','cinematic') else 15.
    target=min(hi,max(lo,target))
    setup=max(settings.get('setup_seconds',1.),2. if manual=='funny' else 1.)
    tail=max(settings.get('payoff_seconds',1.5),3. if manual=='funny' else 1.5)
    start=max(0.,float(times[left])-setup)
    end=min(duration,float(times[right])+1/fps+tail)
    if end-start<target:
        missing=target-(end-start)
        start=max(0.,start-missing*.4);end=min(duration,start+target);start=max(0.,end-target)
    if end-start>hi:
        start=max(0.,min(start,t-hi*.35));end=min(duration,start+hi)
        if end<=t:
            end=min(duration,t+tail);start=max(0.,end-hi)
    # Optimize only near an existing boundary. Starting later cannot erase the detected onset.
    starts=times[(times>=max(0,start-2))&(times<=min(start+2,t-.5,float(times[left])))].tolist()+[start]
    ends=times[(times>=max(t+.5,end-2))&(times<=min(duration,end+2))].tolist()+[end]
    candidates=[]
    def edge_cost(at):
        i=min(len(times)-1,max(0,int(np.searchsorted(times,at))))
        audio=float(np.clip((data['audio_db'][i]+48)/25,0,1))
        return .55*float(scores[i])+.25*audio-.25*float(data['cut'][i])
    for a in starts:
        for b in ends:
            if lo-1e-6<=b-a<=hi+1e-6 and a<=t<b:
                opening=scores[(times>=a)&(times<min(b,a+2))]
                interest=float(opening.mean()) if len(opening) else 0
                cost=edge_cost(a)+edge_cost(b)-.3*interest+.025*(abs(a-start)+abs(b-end))
                candidates.append((cost,a,b))
    if candidates:
        _,start,end=min(candidates)
    return start,end,dict(method='activity envelope and low-activity/audio edges',
        envelope_seconds=round(envelope,3),context_target_seconds=target,
        semantic_payoff_verified=False,dialogue_verified=False)


def suggest(reasons):
    active=reasons.get('active_fraction',0);motion=reasons.get('motion_score',0)
    cuts=reasons.get('cut_fraction',0);quiet=reasons.get('quiet_interest',0)
    if active>.65 and motion>.55 and cuts<.08:
        return dict(preset='action',confidence=round(min(.85,.45+.4*motion),3),
                    reason='Sustained visible activity; event identity unknown')
    if quiet>.25 and cuts<.04:
        return dict(preset='cinematic',confidence=.55,reason='Lower activity with evolving detail; review suggested')
    return dict(preset='neutral',confidence=.25,reason='Ambiguous signals; original pacing and styling retained')


def pattern(reasons):
    if reasons.get('quiet_interest',0)>.3 and reasons.get('motion_score',0)<.4:
        return 'subtle'
    if reasons.get('activity_contrast',0)>.25:
        return 'burst'
    if reasons.get('active_fraction',0)>.7:
        return 'sustained'
    return 'mixed'
