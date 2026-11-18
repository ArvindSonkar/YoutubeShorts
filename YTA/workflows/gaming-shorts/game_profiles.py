"""Optional, narrowly calibrated visual rules. No event recognition or models."""
import json
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np


def title_patch(gray):
    height, width = gray.shape
    return cv2.resize(gray[round(height*.2):round(height*.8), round(width*.15):round(width*.85)],
                      (32, 16), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=1)
def calibration():
    return json.loads((Path(__file__).with_name('dmc5_title_calibration.json')).read_text(encoding='utf-8'))


def screen_penalty(gray, profile='generic'):
    if profile == 'generic':
        return 0.
    if profile != 'dmc5':
        raise ValueError('Unknown game profile')
    config = calibration()
    reference = np.frombuffer(bytes.fromhex(config['patch_hex']), np.uint8).reshape(16, 32)
    difference = float(np.abs(title_patch(gray).astype(float)-reference).mean()/255)
    return 1. if difference <= config['maximum_mean_error'] else 0.
