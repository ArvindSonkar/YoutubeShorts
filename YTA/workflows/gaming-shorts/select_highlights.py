"""Explainable action ranking, boundary selection, and non-overlapping diversity."""
import numpy as np


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
    scores = np.clip(scores, 0, 1)
    radius = max(1, round(fps))
    padded = np.pad(scores, (radius, radius), mode='edge')
    return np.convolve(padded, np.ones(2*radius+1)/(2*radius+1), mode='valid')


def candidate_windows(data, duration, settings):
    fps = settings['analysis_fps']
    scores = action_scores(data, fps)
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
    for peak in peaks:
        t = float(times[peak])
        # Extend through sustained action, while limiting quiet lead-in/outro.
        left = right = peak
        low = max(.12, float(scores[peak])*.50)
        while left > 0 and t-times[left] < maximum*.4 and scores[left-1] >= low:
            left -= 1
        while right+1 < len(scores) and times[right]-t < maximum*.6 and scores[right+1] >= low:
            right += 1
        start = max(0., float(times[left])-3.)
        end = min(duration, float(times[right])+4.)
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
        cuts = times[data['cut'] > .5]
        start_cuts = cuts[(cuts >= start) & (cuts <= min(start+3, t-1)) & (end-cuts >= minimum)]
        if len(start_cuts):
            start = float(start_cuts[0])
        end_cuts = cuts[(cuts <= end) & (cuts >= max(end-3, t+1)) & (cuts-start >= minimum)]
        if len(end_cuts):
            end = float(end_cuts[-1])
        a, b = np.searchsorted(times, [start, end])
        b = max(a+1, min(len(scores), b))
        segment = scores[a:b]
        active_fraction = float(np.mean((data['motion'][a:b] > .012) | (data['camera'][a:b] > .1)))
        darkness = float(np.mean(data['brightness'][a:b] < .025))
        cut_fraction = float(np.mean(data['cut'][a:b]))
        quality = .55*float(segment.mean()) + .25*float(np.percentile(segment, 85)) + .20*active_fraction
        quality -= .30*darkness + .25*cut_fraction
        if quality < settings['min_score'] or active_fraction < .25 or darkness > .35:
            continue
        marks = np.linspace(a, b-1, 5).astype(int)
        candidates.append({'start': round(start, 6), 'end': round(end, 6), 'peak': t,
                           'score': round(float(quality), 5),
                           'fingerprints': data['fingerprint'][marks].tolist(),
                           'reasons': {'mean_action': round(float(segment.mean()), 4),
                                       'peak_action': round(float(scores[peak]), 4),
                                       'active_fraction': round(active_fraction, 4),
                                       'dark_fraction': round(darkness, 4),
                                       'cut_fraction': round(cut_fraction, 4)}})
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


def choose(candidates, count, duration, min_gap):
    remaining = list(candidates)
    selected = []
    bucket_size = max(60., duration/8)
    while remaining and len(selected) < count:
        def diversified(item):
            bucket = int(item['peak']/bucket_size)
            seen = sum(int(p['peak']/bucket_size) == bucket for p in selected)
            return item['score'] - .06*seen, -item['start']
        winner = max(remaining, key=diversified)
        remaining.remove(winner)
        if any(not (winner['end']+min_gap <= old['start'] or old['end']+min_gap <= winner['start'])
               or duplicate(winner, old) for old in selected):
            continue
        selected.append(dict(winner, rank=len(selected)+1))
    return selected
