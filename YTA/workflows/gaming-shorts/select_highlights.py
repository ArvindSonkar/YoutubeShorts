"""Explainable action ranking, boundary selection, and non-overlapping diversity."""
import numpy as np
from progress import stage
import moments


def local_scale(values, fps, floor):
    values = np.asarray(values, dtype=float)
    result = np.zeros_like(values)
    # Rolling reference windows avoid hard score jumps at fixed block boundaries.
    step = max(1, round(30 * fps))
    anchors = list(range(0, len(values), step))
    if anchors[-1] != len(values)-1:
        anchors.append(len(values)-1)
    lows, highs = [], []
    radius = round(60 * fps)
    for index in anchors:
        window = values[max(0, index-radius):index+radius+1]
        lo, hi = np.percentile(window, [20, 90])
        lows.append(lo); highs.append(max(hi, lo+floor))
    lo = np.interp(np.arange(len(values)), anchors, lows)
    hi = np.interp(np.arange(len(values)), anchors, highs)
    result[:] = np.clip((values-lo)/(hi-lo), 0, 1)
    return result


def action_scores(data, fps):
    motion = .55 * local_scale(data['motion'], fps, .025) + .45 * np.clip(data['motion']/.15, 0, 1)
    camera = np.clip(data['camera'], 0, 1)
    sound = local_scale(data['audio_db'], fps, 12) * np.clip((data['audio_db']+55)/25, 0, 1)
    transient = local_scale(data['audio_flux'], fps, .15)
    change = np.clip(data['change']/.15, 0, 1)
    scores = .38*motion + .18*camera + .18*sound + .12*transient + .14*change
    scores -= .28*data['cut'] + .35*(data['brightness'] < .025)
    # Loud music over a still screen must not become a visual action highlight.
    active = (data['motion'] > .012) | (data['camera'] > .10)
    scores *= np.where(active, 1., .20)
    # Sustained residual movement is stronger evidence than camera sweeps alone.
    width = max(1, round(2*fps))
    sustained = np.convolve(np.pad((data['motion'] > .012).astype(float),
                                   (width//2, width-1-width//2), mode='edge'),
                            np.ones(width)/width, mode='valid')
    scores *= .55+.45*sustained
    scores *= 1-np.clip(data.get('screen_penalty', np.zeros_like(scores)), 0, 1)
    cues=moments.signals(data,fps)
    scores=np.maximum(scores+.10*cues['contrast']+.08*cues['onset'],.42*cues['quiet'])
    scores *= 1-cues['screen']
    scores = np.clip(scores, 0, 1)
    radius = max(1, round(fps))
    padded = np.pad(scores, (radius, radius), mode='edge')
    return np.convolve(padded, np.ones(2*radius+1)/(2*radius+1), mode='valid')


def candidate_windows(data, duration, settings):
    with stage('Highlight scoring and candidate selection', len(data['time']), 'samples', 'Selection') as meter:
        return _candidate_windows(data, duration, settings, meter)


def _candidate_windows(data, duration, settings, meter):
    fps = settings['analysis_fps']
    scores = action_scores(data, fps)
    cues=moments.signals(data,fps)
    minimum, maximum = settings['min_duration'], settings['max_duration']
    if duration < minimum:
        return [], scores
    times = data['time']
    # One peak per three-second neighborhood; rank later after measuring context.
    radius = max(1, round(fps*1.5))
    peaks = [i for i in range(len(scores))
             if scores[i] >= settings['min_score'] and
             i == max(0, i-radius) + int(np.argmax(scores[max(0, i-radius):i+radius+1]))]
    candidates = []
    cuts = times[data['cut'] > .5]
    screen_penalties = data.get('screen_penalty', np.zeros(len(times)))
    for peak in peaks:
        meter.update(peak)
        t = float(times[peak])
        # Extend through sustained action, while limiting quiet lead-in/outro.
        left = right = peak
        low = max(.12, float(scores[peak])*.50)
        while left > 0 and t-times[left] < maximum*.4 and scores[left-1] >= low:
            left -= 1
        while right+1 < len(scores) and times[right]-t < maximum*.6 and scores[right+1] >= low:
            right += 1
        start = max(0., float(times[left])-settings.get('setup_seconds', 1.))
        end = min(duration, float(times[right])+settings.get('payoff_seconds', 1.5))
        if end-start < minimum:
            missing = minimum-(end-start)
            start = max(0., start-missing*.4)
            end = min(duration, start+minimum)
            start = max(0., end-minimum)
        if end-start > maximum:
            start = max(0., t-maximum*.35)
            end = min(duration, start+maximum)
            start = max(0., end-maximum)
        # Prefer a nearby actual cut when it preserves both length and the peak.
        start_cuts = cuts[(cuts >= start) & (cuts <= min(start+3, t-1)) & (end-cuts >= minimum)]
        if len(start_cuts):
            start = float(start_cuts[0])
        end_cuts = cuts[(cuts <= end) & (cuts >= max(end-3, t+1)) & (cuts-start >= minimum)]
        if len(end_cuts):
            end = float(end_cuts[-1])
        # Search nearby openings while retaining the peak and configured bounds.
        options = times[(times >= start) & (times <= min(start+4., t-.5, end-minimum))]
        if len(options):
            def opening_value(s):
                a0, b0 = np.searchsorted(times, [s, min(end, s+settings.get('opening_seconds', 2.))])
                return float(scores[a0:max(a0+1,b0)].mean())-.015*(s-start)
            start = float(max(options, key=opening_value))
        boundary={'method':'legacy activity boundaries','semantic_payoff_verified':False,'dialogue_verified':False}
        if settings.get('moment_aware_boundaries',True):
            start,end,boundary=moments.boundaries(data,scores,peak,duration,settings)
        a, b = np.searchsorted(times, [start, end])
        b = max(a+1, min(len(scores), b))
        segment = scores[a:b]
        active_fraction = float(np.mean((data['motion'][a:b] > .012) | (data['camera'][a:b] > .1)))
        darkness = float(np.mean(data['brightness'][a:b] < .025))
        cut_fraction = float(np.mean(data['cut'][a:b]))
        opening_end = min(b, a+max(1, round(settings.get('opening_seconds', 2.)*fps)))
        opening = float(scores[a:opening_end].mean())
        ending = float(scores[max(a,b-round(2*fps)):b].mean())
        screen_fraction = float(np.mean(np.maximum(screen_penalties[a:b],cues['screen'][a:b])))
        local_active = data['motion'][a:b] > .012
        sustained_fraction = float(np.mean(local_active))
        quality = .55*float(segment.mean()) + .25*float(np.percentile(segment, 85)) + .20*active_fraction
        quality = .8*quality+.2*opening
        quality -= .30*darkness + .25*cut_fraction + .5*screen_fraction
        quality -= .12*(1-sustained_fraction)
        quiet=float(cues['quiet'][a:b].mean())
        contrast=float(cues['contrast'][a:b].max())
        quality=max(quality,.48*quiet+.20*opening+.12*contrast-.5*screen_fraction-.3*darkness)
        if quality < settings['min_score'] or (active_fraction < .25 and quiet < .45) or darkness > .35:
            continue
        marks = np.linspace(a, b-1, 5).astype(int)
        warnings = []
        if opening < max(.20, float(scores[peak])*.45):
            warnings.append('Weak opening: little activity in the first two seconds')
        if ending > .75*float(scores[peak]):
            warnings.append('Action continues at the ending; payoff is unverified')
        if cut_fraction > .08:
            warnings.append('Frequent scene changes; may be a cutscene or montage')
        confidence = float(np.clip(.5*active_fraction+.3*sustained_fraction+.2*(1-darkness)-.3*cut_fraction-.5*screen_fraction, 0, 1))
        candidates.append({'start': round(start, 6), 'end': round(end, 6), 'peak': t,
                           'score': round(float(quality), 5),
                           'confidence': round(confidence, 4), 'warnings': warnings,
                           'confidence_note': 'Heuristic evidence strength, not a calibrated event probability',
                           'metadata_version':1,'boundary':boundary,
                           'fingerprints': data['fingerprint'][marks].tolist(),
                           'reasons': {'mean_action': round(float(segment.mean()), 4),
                                       'peak_action': round(float(scores[peak]), 4),
                                       'active_fraction': round(active_fraction, 4),
                                       'opening_score': round(opening, 4),
                                       'ending_activity': round(ending, 4),
                                       'sustained_local_motion': round(sustained_fraction, 4),
                                       'screen_penalty': round(screen_fraction, 4),
                                       'dark_fraction': round(darkness, 4),
                                       'cut_fraction': round(cut_fraction, 4)}})
        item=candidates[-1]
        item['reasons'].update(motion_score=round(float(cues['motion'][a:b].mean()),4),
            audio_score=round(float(cues['audio'][a:b].mean()),4),quiet_interest=round(quiet,4),
            activity_contrast=round(contrast,4),sudden_change=round(float(cues['onset'][a:b].max()),4))
        item['suggested_editing']=moments.suggest(item['reasons'])
        item['activity_pattern']=moments.pattern(item['reasons'])
        if boundary['method']!='legacy activity boundaries':
            warnings.append('Activity boundaries cannot verify dialogue completion or semantic payoff')
    # Multiple peaks can refine to the exact same interval.
    unique = {}
    for item in candidates:
        key = (round(item['start'], 1), round(item['end'], 1))
        if key not in unique or item['score'] > unique[key]['score']:
            unique[key] = item
    return sorted(unique.values(), key=lambda c: (-c['score'], c['start'])), scores


def duplicate(a, b):
    pairs = zip(a['fingerprints'], b['fingerprints'])
    distances = [(int(x, 16) ^ int(y, 16)).bit_count() for x, y in pairs]
    return bool(distances) and sum(d < 6 for d in distances) >= 4


def choose(candidates, count, duration, min_gap, diversity=.5):
    remaining = list(candidates)
    selected = []
    bucket_size = max(60., duration/8)
    while remaining and len(selected) < count:
        def diversified(item):
            bucket = int(item['peak']/bucket_size)
            seen = sum(int(p['peak']/bucket_size) == bucket for p in selected)
            similar=sum(p.get('activity_pattern')==item.get('activity_pattern') for p in selected) if item.get('activity_pattern') else 0
            return item['score'] - diversity*(.08*seen+.04*similar), -item['start']
        # Diversity only breaks ties among comparable-quality candidates (within .08).
        best=max(item['score'] for item in remaining)
        winner = max((item for item in remaining if item['score']>=best-.08*diversity), key=diversified)
        remaining.remove(winner)
        if any(not (winner['end']+min_gap <= old['start'] or old['end']+min_gap <= winner['start'])
               or duplicate(winner, old) for old in selected):
            continue
        selected.append(dict(winner, rank=len(selected)+1,selection_reason='Quality first; non-overlap and fingerprint deduplication; temporal/pattern diversity among comparable scores',
                             diversity_adjusted_score=round(diversified(winner)[0],5)))
    return selected
