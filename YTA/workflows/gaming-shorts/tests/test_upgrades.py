"""Deterministic upgrade regressions; real media QA is exercised by the smoke run."""
import argparse
import ast
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from test_pipeline import features
import analyze
import auto_shorts
import autoframe
import dynamic_crop as editor
import game_profiles
import progress
import review
import select_highlights as selection


class Clock:
    def __init__(self):
        self.now = 0.
    def __call__(self):
        return self.now


class ProgressTests(unittest.TestCase):
    def test_percentage_speed_eta_and_throttle(self):
        clock, emit = Clock(), Mock()
        meter = progress.Stage('test', 100, clock=clock, emit=emit)
        meter.__enter__()
        self.assertIsNone(meter.snapshot()['eta_seconds'])
        clock.now = 4
        meter.update(25)
        value = meter.snapshot()
        self.assertEqual(value['percent'], 25)
        self.assertEqual(value['speed_per_second'], 6.25)
        self.assertEqual(value['eta_seconds'], 12)
        calls = emit.call_count
        clock.now = 4.1
        meter.update(26)
        self.assertEqual(emit.call_count, calls)
        meter.update(200, force=True)
        self.assertEqual(meter.snapshot()['percent'], 100)
        meter.update(-20)
        self.assertEqual(meter.done, 100)

    def test_unknown_total_and_zero_work_do_not_invent_eta(self):
        clock = Clock()
        for total in (None, 0, 100):
            meter = progress.Stage('test', total, clock=clock, emit=Mock())
            clock.now += 10
            self.assertIsNone(meter.snapshot()['eta_seconds'])

    def test_interruption_does_not_report_100_percent(self):
        clock, recorder = Clock(), Mock(stages=[])
        meter = progress.Stage('test', 100, clock=clock, emit=Mock(), recorder=recorder)
        with self.assertRaises(KeyboardInterrupt), meter:
            clock.now = 3
            meter.update(30)
            raise KeyboardInterrupt()
        self.assertEqual(recorder.stages[0]['status'], 'interrupted')
        self.assertEqual(recorder.stages[0]['percent'], 30)
        self.assertEqual(recorder.stages[0]['elapsed_seconds'], 3)

    def test_resume_history_distinct_from_wall_and_stage_time(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            clock = Clock()
            first = progress.Session(folder, clock=clock)
            first.stages.append(dict(category='Rendering', elapsed_seconds=3, status='complete'))
            clock.now = 5
            first.save('interrupted')
            second = progress.Session(folder, True, clock=clock)
            clock.now = 9
            result = second.save('complete')
            self.assertEqual(len(result['runs']), 2)
            self.assertEqual(result['current_run']['wall_seconds'], 4)
            self.assertEqual(result['cumulative_wall_seconds'], 9)
            self.assertEqual(result['runs'][0]['accumulated_stage_seconds'], 3)
            second.save('complete')
            self.assertEqual(len(json.loads((Path(folder)/'metrics.json').read_text())['runs']), 2)


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.settings = editor.read_json(HERE/'auto_defaults.json')

    def test_short_clips_and_explainable_boundaries(self):
        data = features(50, active=True)
        data['motion'] *= .6+.4*np.sin(data['time']/3)**2
        candidates, _ = selection.candidate_windows(data, 50, dict(self.settings, min_duration=6, max_duration=12))
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertGreaterEqual(candidate['end']-candidate['start'], 6-1e-5)
            self.assertLessEqual(candidate['end']-candidate['start'], 12+1e-5)
            self.assertIn('opening_score', candidate['reasons'])
            self.assertIn('ending_activity', candidate['reasons'])
            self.assertTrue(0 <= candidate['confidence'] <= 1)
            self.assertIsInstance(candidate['warnings'], list)

    def test_menu_profile_suppresses_even_loud_moving_title(self):
        data = features(active=True)
        data['screen_penalty'] = np.ones(len(data['time']))
        self.assertEqual(selection.candidate_windows(data, 100, self.settings)[0], [])

    def test_camera_sweep_is_weaker_than_residual_action(self):
        action = features(active=True)
        sweep = copy.deepcopy(action)
        sweep['motion'][:] = 0
        self.assertLess(selection.action_scores(sweep, 3).mean(), selection.action_scores(action, 3).mean())

    def test_boundary_search_improves_weak_leadin(self):
        data = features(40, active=True)
        data['motion'][:12] = 0
        data['camera'][:12] = 0
        data['change'][:12] = 0
        candidates, scores = selection.candidate_windows(data, 40, dict(self.settings, min_duration=6, max_duration=12))
        self.assertTrue(candidates)
        self.assertGreater(candidates[0]['reasons']['opening_score'], float(scores[:6].mean()))

    def test_particle_jump_does_not_become_tracking_target(self):
        data = features(30)
        data['confidence'][:] = .99
        data['center'][::2] = [.1, .5]
        data['center'][1::2] = [.9, .5]
        keys, result = autoframe.keyframes(data, 0, 30, self.settings, 30)
        self.assertTrue(all(key['width']==1 for key in keys))
        self.assertEqual(result['fallback_fraction'], 1)

    def test_wide_always_preserves_image_and_hud_union(self):
        data = features(30)
        data['confidence'][:] = .9
        wide, _ = autoframe.keyframes(data, 0, 30, dict(self.settings, framing_mode='wide'), 30)
        self.assertTrue(all(key['width']==1 for key in wide))
        hud = [.02, .03, .3, .15]
        close, _ = autoframe.keyframes(data, 0, 30, dict(self.settings, framing_mode='close', hud_regions=[hud]), 30)
        for key in close:
            self.assertLessEqual(key['protect_box'][0], hud[0])
            self.assertLessEqual(key['protect_box'][1], hud[1])
            self.assertGreaterEqual(key['protect_box'][2], hud[2])
            self.assertGreaterEqual(key['protect_box'][3], hud[3])

    def test_camera_plan_smoothing_and_bisect_interpolation(self):
        config = editor.read_json(editor.DEFAULTS)
        config['framing']['keyframes'] = [dict(time=0, center=[.4,.5], width=.7), dict(time=2, center=[.6,.5], width=.8)]
        config['smoothing'].update(max_pan_per_second=.18, max_width_change_per_second=.2)
        config['impacts']['enabled'] = False
        plan = editor.camera_plan(config, 1280, 720, 1080, 1920, 30, 90)
        centers = [(p['x']+p['width']/2)/1280 for p in plan]
        widths = [p['width']/1280 for p in plan]
        self.assertLessEqual(max(abs(np.diff(centers))), .18/30+1e-6)
        self.assertLessEqual(max(abs(np.diff(widths))), .2/30+1e-6)
        self.assertAlmostEqual(editor.target_at(config, 1, [0,2])[0][0], .5)

    def test_calibrated_title_evidence_and_generic_isolation(self):
        config = game_profiles.calibration()
        for second in config['validation_title_seconds']:
            self.assertLess(config['sample_mean_errors'][str(second)], config['maximum_mean_error'])
        for second in config['validation_other_seconds']:
            self.assertGreater(config['sample_mean_errors'][str(second)], config['maximum_mean_error'])
        with patch.object(game_profiles, 'calibration', side_effect=AssertionError('Generic must not read DMC calibration')):
            self.assertEqual(game_profiles.screen_penalty(np.zeros((180,320), np.uint8)), 0)

    def test_actual_title_template_filter(self):
        config = game_profiles.calibration()
        gray = np.zeros((100,100), np.uint8)
        patch_image = np.frombuffer(bytes.fromhex(config['patch_hex']), np.uint8).reshape(16,32)
        with patch.object(game_profiles, 'title_patch', return_value=patch_image):
            self.assertEqual(game_profiles.screen_penalty(gray, 'dmc5'), 1)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.manifest = dict(signature={'source': 'test'}, clips=[dict(candidate=dict(rank=1, start=10., end=30., score=.8), status='pending')])
    def decision(self, **changes):
        return dict(run_id=review.run_id(self.manifest), clips=[dict(rank=1, start=12., end=25., decision='approve', framing='wide', **changes)])
    def test_review_trims_without_mutating_original(self):
        result = review.apply_decisions(self.manifest, self.decision())
        self.assertEqual(result['clips'][0]['candidate']['start'], 12)
        self.assertEqual(self.manifest['clips'][0]['candidate']['start'], 10)
        self.assertEqual(review.apply_decisions(result, self.decision()), result)
    def test_invalid_reviews_and_completed_edits_rejected(self):
        for field, value in [('start', 9), ('end', 31), ('start', float('nan')), ('decision', 'publish'), ('framing','bad'), ('rank',2)]:
            item = self.decision(); item['clips'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                review.apply_decisions(self.manifest, item)
        wrong = self.decision(); wrong['run_id'] = 'other'
        with self.assertRaises(ValueError):
            review.apply_decisions(self.manifest, wrong)
        self.manifest['clips'][0]['status'] = 'complete'
        with self.assertRaises(ValueError):
            review.apply_decisions(self.manifest, self.decision())
    def test_rejection_and_duplicate_rank(self):
        item = self.decision(); item['clips'][0]['decision'] = 'reject'
        self.assertEqual(review.apply_decisions(self.manifest, item)['clips'][0]['status'], 'rejected')
        item['clips'] *= 2
        with self.assertRaises(ValueError):
            review.apply_decisions(self.manifest, item)


class ResumeTests(unittest.TestCase):
    def test_renderer_kills_and_reaps_encoder_on_interrupt(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            root = Path(folder)
            work = root/'work'; work.mkdir()
            target = root/'short.mp4'
            config = editor.read_json(editor.DEFAULTS)
            config['framing']['keyframes'] = [dict(time=0, center=[.5,.5], width=1.)]
            job = SimpleNamespace(target=target, source=root/'source.mp4', config=config, check_timestamps=Mock(),
                                  executables={'ffmpeg':'fake'}, ow=1080, oh=1920, count=3, first=0,
                                  fps=editor.Fraction(30), start=0., duration=.1, plan=[{}]*3, layer=None)
            process = Mock()
            process.stdin.write.side_effect = KeyboardInterrupt()
            decoder = Mock()
            decoder.read.return_value = (True, np.zeros((2,2,3),np.uint8))
            decoder.get.return_value = 1
            partial = root/'short.partial.mp4'
            def start(*args, **kwargs):
                partial.write_bytes(b'partial')
                return process
            with patch.object(editor, 'artifacts', return_value=work), patch.object(editor.cv2,'VideoCapture',return_value=decoder), \
                 patch.object(editor, 'compose', return_value=np.zeros((2,2,3),np.uint8)), \
                 patch.object(editor.subprocess, 'Popen', side_effect=start), self.assertRaises(KeyboardInterrupt):
                editor.render(job)
            process.kill.assert_called_once()
            process.wait.assert_called_once()
            decoder.release.assert_called_once()
            self.assertTrue(partial.exists())
            self.assertFalse(target.exists())

    def test_complete_resume_cache_and_interruption_recovery(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            root = Path(folder); source = root/'input.mp4'; source.write_bytes(b'fixture')
            output = root/'run'
            meta = dict(streams=[dict(codec_type='video', width=1280, height=720, avg_frame_rate='30/1', r_frame_rate='30/1',
                                     duration='30', nb_frames='900'), dict(codec_type='audio', channels=2)], format={'duration':'30'})
            args = argparse.Namespace(input=str(source), output_dir=str(output), count=1, settings=None,
                                      max_seconds=30, analysis_only=False, resume=False, offline=True, review_file=None)
            candidate = dict(rank=1, start=5., end=25., peak=15., score=.8, fingerprints=['0']*5)
            def thumbnail(job, path, frames=None):
                path.write_bytes(b'preview')
            def interrupted(job, label):
                job.target.with_name(job.target.stem+'.partial.mp4').write_bytes(b'partial')
                job.target.with_suffix('.work').mkdir()
                raise KeyboardInterrupt()
            def rendered(job, label):
                job.target.write_bytes(b'finished')
            with patch.object(editor, 'probe', return_value=meta), patch.object(analyze, 'scan', return_value=features(30, active=True)) as scan, \
                 patch.object(selection, 'candidate_windows', return_value=([candidate], np.ones(90))) as choose, \
                 patch.object(auto_shorts, 'thumbnail', side_effect=thumbnail), patch.object(auto_shorts, 'capture', return_value=np.zeros((2,2,3), np.uint8)), \
                 patch.object(auto_shorts.cv2, 'VideoCapture'), patch.object(auto_shorts, 'verify', return_value={'ok':True}), \
                 patch.object(socket, 'socket', side_effect=AssertionError('Network forbidden')):
                with patch.object(auto_shorts, 'render', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                    auto_shorts.execute(args)
                self.assertEqual(editor.read_json(output/'manifest.json')['clips'][0]['status'], 'interrupted')
                args.resume = True
                with patch.object(auto_shorts, 'render', side_effect=rendered) as rendering:
                    self.assertEqual(auto_shorts.execute(args), 0)
                    self.assertEqual(rendering.call_count, 1)
                    self.assertEqual(auto_shorts.execute(args), 0)
                    self.assertEqual(rendering.call_count, 1)
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(choose.call_count, 1)
                self.assertEqual(len(list((output/'attempts').iterdir())), 2)
                metrics = editor.read_json(output/'metrics.json')
                self.assertEqual(len(metrics['runs']), 3)
                self.assertEqual(metrics['runs'][0]['status'], 'interrupted')
                self.assertTrue(any('completed Short' in item for item in metrics['current_run']['cache_hits']))
                self.assertEqual(metrics['current_run']['counts']['generated_video_seconds'], 20)
                # Same-code resume succeeds; changed code identity is rejected without altering the manifest.
                original = (output/'manifest.json').read_bytes()
                with patch.object(auto_shorts, 'code_signature', return_value='changed'), self.assertRaisesRegex(ValueError, 'code changed'):
                    auto_shorts.execute(args)
                self.assertEqual((output/'manifest.json').read_bytes(), original)

    def test_pipeline_has_no_network_or_model_dependencies(self):
        forbidden = {'requests','urllib','http','socket','torch','transformers','openai'}
        for name in ('auto_shorts.py','analyze.py','autoframe.py','dynamic_crop.py','verify_output.py','progress.py','game_profiles.py'):
            tree = ast.parse((HERE/name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(forbidden.intersection(alias.name.split('.')[0] for alias in node.names))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[0], forbidden)


if __name__ == '__main__':
    (editor.ROOT/'output').mkdir(exist_ok=True)
    unittest.main(verbosity=2)
