"""Conservative motion-region framing; low confidence preserves the full image."""
import numpy as np


def keyframes(data, start, end, settings, source_fps):
    indices = np.flatnonzero((data['time'] >= start) & (data['time'] < end))
    keys, confidences, history = [], [], []
    fallback = 0
    for index in indices:
        time = max(0., float(data['time'][index])-start)
        confidence = float(data['confidence'][index])
        mode = settings.get('framing_mode', 'safe')
        good = confidence >= settings['crop_confidence'] and data['cut'][index] < .5 and mode != 'wide'
        if history and good:
            last = history[-1]
            displacement = float(np.linalg.norm(data['center'][index]-data['center'][last]))
            old = data['box'][last]; new = data['box'][index]
            old_area = max(.001, (old[2]-old[0])*(old[3]-old[1]))
            new_area = max(.001, (new[2]-new[0])*(new[3]-new[1]))
            if displacement > .12 or max(old_area/new_area, new_area/old_area) > 2.5:
                good = False  # Flash/target jump: do not chase it.
        if not good:
            history.clear()
        else:
            history.append(index)
            history = history[-4:]
        # Require persistence; a single flash is not a subject to follow.
        if len(history) >= 3:
            boxes = data['box'][history]
            box = [float(boxes[:, 0].min()), float(boxes[:, 1].min()),
                   float(boxes[:, 2].max()), float(boxes[:, 3].max())]
            center = np.median(data['center'][history], axis=0)
            # Explicit HUD rectangles join the protected motion box.
            for hud in settings.get('hud_regions', []):
                box = [min(box[0], hud[0]), min(box[1], hud[1]), max(box[2], hud[2]), max(box[3], hud[3])]
            minimum = settings['crop_min_width'] if mode == 'close' else max(.70, settings['crop_min_width'])
            width = max(minimum, box[2]-box[0]+.18)
            keys.append({'time': time, 'center': [float(center[0]), .5],
                         'width': min(1., width), 'protect_box': box})
        else:
            fallback += 1
            keys.append({'time': time, 'center': [.5, .5], 'width': 1., 'protect_box': [0., 0., 1., 1.]})
        confidences.append(confidence)
    if not keys:
        keys = [{'time': 0., 'center': [.5, .5], 'width': 1., 'protect_box': [0., 0., 1., 1.]}]
        fallback = 1
    if keys[0]['time'] > 0:
        keys.insert(0, dict(keys[0], time=0.))
    # At a scene cut, force full width one output frame before the transition.
    for index in indices:
        if data['cut'][index] > .5:
            t = max(0., float(data['time'][index])-start-1/source_fps)
            keys.append({'time': t, 'center': [.5, .5], 'width': 1., 'protect_box': [0., 0., 1., 1.]})
    unique = {round(k['time'], 8): k for k in keys}
    keys = [unique[t] for t in sorted(unique)]
    return keys, {'method': 'persistent residual-motion regions; no object identity',
                  'mode': settings.get('framing_mode', 'safe'),
                  'hud_regions': settings.get('hud_regions', []),
                  'mean_confidence': float(np.mean(confidences)) if confidences else 0.,
                  'fallback_fraction': fallback / max(1, len(indices)),
                  'keyframe_count': len(keys)}
