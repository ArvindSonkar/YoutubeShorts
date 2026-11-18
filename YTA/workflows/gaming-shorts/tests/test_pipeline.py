"""Deterministic tests; no network, model downloads, or long-video processing."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import analyze
import autoframe
import auto_shorts
import dynamic_crop as editor
import select_highlights as selection
import verify_output


def features(seconds=100, fps=3, active=False):
    n = round(seconds*fps)
    data = {key: np.zeros(n) for key in ('motion', 'camera', 'change', 'cut', 'confidence', 'audio_flux')}
    data.update(time=np.arange(n)/fps, brightness=np.full(n, .4), sharpness=np.full(n, 100.),
                audio_db=np.full(n, -25.), audio_peak=np.full(n, .2),
                center=np.tile([.6, .5], (n, 1)), box=np.tile([.5, .3, .7, .7], (n, 1)),
                fingerprint=np.asarray([format((i*6364136223846793005) % 2**64, '016x') for i in range(n)]))
    if active:
        data['motion'][:] = .2
        data['change'][:] = .15
        data['camera'][:] = .5
    return data


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (editor.ROOT/'output').mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.settings = editor.read_json(HERE/'auto_defaults.json')

    def test_static_screen_and_loud_audio_not_highlights(self):
        data = features()
        data['audio_db'][::2] = -1
        data['audio_flux'][::2] = .9
        candidates, _ = selection.candidate_windows(data, 100, self.settings)
        self.assertEqual(candidates, [])

    def test_action_regions_have_valid_context_bounds(self):
        data = features(active=True)
        data['motion'] *= .6+.4*np.sin(data['time']/4)**2
        candidates, scores = selection.candidate_windows(data, 100, self.settings)
        self.assertTrue(candidates)
        self.assertEqual(len(scores), len(data['time']))
        for item in candidates:
            self.assertGreaterEqual(item['start'], 0)
            self.assertLessEqual(item['end'], 100)
            self.assertGreaterEqual(item['end']-item['start'], 20-1e-5)
            self.assertLessEqual(item['end']-item['start'], 55+1e-5)
            self.assertLessEqual(item['start'], item['peak'])
            self.assertGreaterEqual(item['end'], item['peak'])

    def test_too_short_source_has_no_candidates(self):
        candidates, _ = selection.candidate_windows(features(10, active=True), 10, self.settings)
        self.assertEqual(candidates, [])

    def test_black_motion_is_rejected(self):
        data = features(active=True)
        data['brightness'][:] = 0
        candidates, _ = selection.candidate_windows(data, 100, self.settings)
        self.assertEqual(candidates, [])

    def test_no_overlap_and_no_quota_padding(self):
        def candidate(start, end, score, fp):
            return dict(start=start, end=end, peak=(start+end)/2, score=score, fingerprints=[fp]*5)
        rows = [candidate(0, 25, .9, '0000000000000000'),
                candidate(10, 35, .8, 'aaaaaaaaaaaaaaaa'),
                candidate(40, 65, .7, 'ffffffffffffffff')]
        picked = selection.choose(rows, 20, 100, 5)
        self.assertEqual(len(picked), 2)
        self.assertEqual([p['start'] for p in picked], [0, 40])

    def test_distant_duplicate_suppressed(self):
        a = dict(start=0, end=25, peak=10, score=.9, fingerprints=['0123456789abcdef']*5)
        b = dict(a, start=80, end=105, peak=90, score=.8)
        self.assertEqual(len(selection.choose([a, b], 10, 120, 0)), 1)

    def test_low_confidence_preserves_full_frame(self):
        keys, report = autoframe.keyframes(features(), 20, 40, self.settings, 30)
        self.assertEqual(keys[0]['time'], 0)
        self.assertEqual(report['fallback_fraction'], 1.)
        self.assertTrue(all(k['width']==1 and k['protect_box']==[0, 0, 1, 1] for k in keys))

    def test_persistent_motion_can_crop(self):
        data = features()
        data['confidence'][:] = .9
        keys, report = autoframe.keyframes(data, 20, 40, self.settings, 30)
        self.assertTrue(any(k['width'] < 1 for k in keys))
        self.assertLess(report['fallback_fraction'], .1)

    def test_scene_cut_resets_framing(self):
        data = features()
        data['confidence'][:] = .9
        data['cut'][75] = 1
        keys, _ = autoframe.keyframes(data, 20, 40, self.settings, 30)
        at_cut = next(k for k in keys if abs(k['time']-5)<1e-8)
        self.assertEqual(at_cut['width'], 1.)
        self.assertTrue(all(a['time'] < b['time'] for a, b in zip(keys, keys[1:])))

    def test_visual_static_has_no_motion(self):
        gray = np.random.default_rng(5).integers(0, 255, (180, 320), dtype=np.uint8)
        result = analyze.visual_features(gray, gray)
        self.assertLess(result['motion'], .01)
        self.assertEqual(result['confidence'], 0)

    def test_frame_read_handles_short_pipe_reads(self):
        class ShortPipe(io.BytesIO):
            def read(self, count):
                return super().read(min(count, 3))
        self.assertEqual(analyze.read_exact(ShortPipe(b'abcdefgh'), 8), b'abcdefgh')

    def test_invalid_settings_rejected(self):
        for key, bad in [('count', 0), ('analysis_fps', float('nan')), ('analysis_width', 321),
                         ('min_duration', 100), ('threads', 0)]:
            settings = dict(self.settings, **{key: bad})
            with self.subTest(key=key), self.assertRaises(ValueError):
                auto_shorts.validate_settings(settings)

    def test_timestamp_formats_and_fractional_fps(self):
        self.assertEqual(editor.seconds('01:02:03.5'), editor.Fraction(7447, 2))
        self.assertEqual(round(editor.seconds('03:09.990')*editor.Fraction(2997, 100)), 5694)
        with self.assertRaises(ValueError):
            editor.seconds('-1')

    def test_shared_source_detects_changes(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            path = Path(folder)/'source.mp4'
            path.write_bytes(b'original')
            with patch.object(editor, 'probe', return_value={'streams': []}):
                context = editor.SourceContext(path, {})
            context.assert_unchanged(full=True)
            path.write_bytes(b'changed source')
            with self.assertRaises(RuntimeError):
                context.assert_unchanged()

    def test_analysis_cache_signature_is_enforced(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            path = Path(folder)/'features.npz'
            analyze.save_features(path, features(2), {'source': 'one'})
            loaded = analyze.load_features(path, {'source': 'one'})
            self.assertEqual(len(loaded['time']), 6)
            with self.assertRaises(ValueError):
                analyze.load_features(path, {'source': 'two'})

    def test_retry_preserves_incomplete_artifacts(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            root = Path(folder)
            target = root/'short.mp4'
            target.with_suffix('.work').mkdir()
            (target.with_suffix('.work')/'render.log').write_text('failure')
            target.with_name('short.partial.mp4').write_bytes(b'partial')
            auto_shorts.archive_incomplete(target, root, 2)
            self.assertFalse(target.with_suffix('.work').exists())
            self.assertEqual(len(list((root/'attempts').iterdir())), 2)

    def test_output_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):
            editor.writable_path(editor.ROOT.parent/'outside.mp4')

    def test_generated_media_cannot_be_written_among_source_files(self):
        for location in ('workflows/clip.mp4', 'videos/clip.mp4', 'clip.mp4', 'output/../clip.mp4'):
            with self.subTest(location=location), self.assertRaises(ValueError):
                editor.generated_path(location)
        self.assertEqual(editor.generated_path('output/run/clip.mp4'), editor.ROOT/'output/run/clip.mp4')

    def test_artifact_folder_recreated_when_output_is_missing(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            temporary_root = Path(folder)
            job = SimpleNamespace(config={}, meta={}, plan=[])
            with patch.object(editor, 'ROOT', temporary_root):
                self.assertFalse((temporary_root/'output').exists())
                result = editor.artifacts('output/new-run/clip.work', job)
                self.assertTrue((result/'effective-config.json').is_file())

    def test_generated_job_uses_source_frame_rate(self):
        class Context:
            sha256 = 'test'
            meta = {'streams': [{'codec_type': 'video', 'avg_frame_rate': '60000/1001'}]}
        candidate = {'start': 10.123, 'end': 30.456}
        config, _ = auto_shorts.make_config(editor.read_json(editor.DEFAULTS), Path('source.mp4'),
                                            Path('out.mp4'), candidate, features(), self.settings, Context())
        self.assertEqual(config['clip']['start_frame'], round(10.123*editor.Fraction(60000, 1001)))
        self.assertFalse(config['impacts']['enabled'])

    def test_verification_rejects_wrong_frame_count(self):
        job = SimpleNamespace(target=Path('out.mp4'), executables={}, ow=1080, oh=1920,
                              fps=editor.Fraction(30), count=600)
        metadata = {'streams': [dict(codec_type='video', width=1080, height=1920,
                                    codec_name='h264', pix_fmt='yuv420p', avg_frame_rate='30', nb_frames='599'),
                                dict(codec_type='audio', codec_name='aac', channels=2)]}
        with patch.object(verify_output, 'probe', return_value=metadata), self.assertRaises(RuntimeError):
            verify_output.verify(job, full_decode=False)

    def test_verification_rejects_misaligned_audio(self):
        class Decoder:
            def set(self, *args):
                pass
            def read(self):
                return True, np.zeros((32, 32, 3), np.uint8)
            def release(self):
                pass
        job = SimpleNamespace(target=Path('out.mp4'), source=Path('source.mp4'), executables={},
                              ow=32, oh=32, fps=editor.Fraction(30), count=30, first=0, duration=1.,
                              start=0., audio={'channels': 2}, config={'audio': {'stream': 0}},
                              plan=[{}]*30, layer=None)
        metadata = {'streams': [dict(codec_type='video', width=32, height=32, codec_name='h264',
                                    pix_fmt='yuv420p', avg_frame_rate='30', nb_frames='30'),
                                dict(codec_type='audio', codec_name='aac', channels=2)],
                    'format': {'duration': '1.0'}}
        original = np.random.default_rng(3).normal(0, .1, 8000).astype(np.float32)
        with patch.object(verify_output, 'probe', return_value=metadata), \
             patch.object(verify_output.cv2, 'VideoCapture', side_effect=lambda _: Decoder()), \
             patch.object(verify_output, 'compose', return_value=np.zeros((32, 32, 3), np.uint8)), \
             patch.object(verify_output, 'audio_samples', side_effect=[original, np.roll(original, 200)]), \
             self.assertRaisesRegex(RuntimeError, 'Audio alignment'):
            verify_output.verify(job, full_decode=False)

    def test_archive_rejects_outside_run(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            root = Path(folder)
            run = root/'run'
            run.mkdir()
            external = root/'other.mp4'
            external.with_suffix('.work').mkdir()
            with self.assertRaises(ValueError):
                auto_shorts.archive_incomplete(external, run, 1)
            self.assertTrue(external.with_suffix('.work').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
