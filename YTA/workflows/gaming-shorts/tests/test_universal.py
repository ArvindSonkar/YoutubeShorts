"""Universal selection, explicit edit timelines, safe review and offline interchange."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from test_pipeline import features
from test_visuals import config,plan
import audio_quality
import auto_shorts
import candidate_exchange as exchange
import dynamic_crop as editor
import editing
import moments
import review
import select_highlights as selection
import visuals
import verify_output
from types import SimpleNamespace


class UniversalTests(unittest.TestCase):
    def setUp(self):
        self.settings=editor.read_json(HERE/'auto_defaults.json')

    def test_sudden_activity_contrast_is_local_and_not_a_game_label(self):
        data=features(60);mask=(data['time']>=25)&(data['time']<32)
        data['motion'][mask]=.12;data['change'][mask]=.1
        c=moments.signals(data,3)
        self.assertGreater(c['contrast'][mask].max(),.3)
        self.assertGreater(c['onset'][mask].max(),.2)
        self.assertEqual(float(c['contrast'][:30].max()),0)

    def test_quiet_evolving_scene_can_be_selected(self):
        data=features(60);data['audio_db'][:]=-40
        mask=(data['time']>=18)&(data['time']<38)
        data['motion'][mask]=.018;data['change'][mask]=.06;data['audio_flux'][mask]=.2
        candidates,_=selection.candidate_windows(data,60,self.settings)
        self.assertTrue(candidates)
        self.assertTrue(any(c['reasons']['quiet_interest']>.4 for c in candidates))

    def test_static_bright_menu_with_music_still_rejected(self):
        data=features(60);data['audio_db'][:]=-1;data['audio_flux'][:]=1
        candidates,_=selection.candidate_windows(data,60,self.settings)
        self.assertFalse(candidates)

    def test_transition_flashes_do_not_create_a_highlight(self):
        data=features(60);data['change'][::3]=1;data['cut'][::3]=1
        self.assertFalse(selection.candidate_windows(data,60,self.settings)[0])

    def test_adaptive_bounds_keep_peak_and_explicit_duration_limits(self):
        data=features(70,active=True);data['motion']*=.6+.4*np.sin(data['time']/3)**2
        for lo,hi in ((6,6),(15,25),(25,40)):
            candidates,_=selection.candidate_windows(data,70,dict(self.settings,min_duration=lo,max_duration=hi))
            self.assertTrue(candidates)
            for c in candidates:
                self.assertLessEqual(c['start'],c['peak']);self.assertLess(c['peak'],c['end'])
                self.assertGreaterEqual(c['end']-c['start'],lo-1e-5)
                self.assertLessEqual(c['end']-c['start'],hi+1e-5)
                self.assertFalse(c['boundary']['semantic_payoff_verified'])

    def test_boundary_keeps_onset_context_and_never_claims_dialogue(self):
        data=features(60);t=data['time'];data['motion'][(t>=25)&(t<33)]=.2
        data['change'][(t>=25)&(t<33)]=.15
        score=selection.action_scores(data,3);peak=int(np.argmax(score))
        start,end,meta=moments.boundaries(data,score,peak,60,self.settings)
        self.assertLess(start,25);self.assertGreater(end,33)
        self.assertFalse(meta['dialogue_verified'])

    def test_uncertain_preset_is_neutral_and_funny_is_never_inferred(self):
        self.assertEqual(moments.suggest({})['preset'],'neutral')
        self.assertEqual(moments.suggest({'active_fraction':.9,'motion_score':.8})['preset'],'action')
        for motion in np.linspace(0,1,10):
            self.assertNotEqual(moments.suggest({'motion_score':motion,'quiet_interest':.5})['preset'],'funny')

    def test_manual_presets_and_explicit_title_override(self):
        v=config(1080)['visual'];v['theme']='gta6'
        for preset in ('action','funny','cinematic'):
            result,report=editing.apply(v,{},preset,[['title','style','bold']])
            self.assertEqual(report['selected'],preset);self.assertEqual(result['title']['style'],'bold')
            self.assertLessEqual(result['panel']['glow'],.1)
        self.assertEqual(v['title']['style'],'cinematic')

    def test_theme_does_not_change_detection(self):
        data=features(45,active=True)
        a,_=selection.candidate_windows(data,45,self.settings)
        other=copy.deepcopy(self.settings);other['visual']['theme']='gta6'
        b,_=selection.candidate_windows(data,45,other)
        self.assertEqual(a,b)

    def test_diversity_prefers_patterns_only_when_quality_is_comparable(self):
        def c(start,score,pattern,fp):
            return dict(start=start,end=start+10,peak=start+5,score=score,activity_pattern=pattern,fingerprints=[fp]*5)
        candidates=[c(0,.9,'burst','0000000000000000'),c(20,.89,'burst','ffffffffffffffff'),
                    c(200,.88,'subtle','aaaaaaaaaaaaaaaa'),c(300,.4,'mixed','5555555555555555')]
        picked=selection.choose(candidates,2,400,0,1)
        self.assertEqual([c['start'] for c in picked],[0,200])
        self.assertEqual([c['start'] for c in selection.choose(candidates,2,400,0,0)],[0,20])

    def test_hud_protection_applies_between_keys_and_during_punch(self):
        c=config(1080);c['framing'].update(keyframes=[{'time':0,'center':[.8,.5],'width':.4}],
            protected_regions=[[.02,.75,.3,.98]],anticipate_widening=True)
        c['effects']['punch_ins']=[dict(start=0,end=2,strength=.1)]
        for row in editor.camera_plan(c,1920,1080,1080,1920,30,90):
            self.assertLessEqual(row['x'],.02*1920)
            self.assertGreaterEqual(row['x']+row['width'],.3*1920)
            self.assertGreaterEqual(row['y']+row['height'],.98*1080)

    def test_anticipatory_widening_limits_zoom_steps(self):
        c=config();c['framing'].update(anticipate_widening=True,keyframes=[
            dict(time=0,center=[.5,.5],width=.5),dict(time=1,center=[.5,.5],width=.5),
            dict(time=1.01,center=[.5,.5],width=1.,protect_box=[0,0,1,1])])
        c['smoothing']['max_width_change_per_second']=.2
        rows=editor.camera_plan(c,1920,1080,360,640,30,90)
        self.assertLessEqual(max(abs(a['width']-b['width']) for a,b in zip(rows,rows[1:])),1920*.2/30+.001)

    def test_hooks_and_timed_reactions_stay_outside_gameplay(self):
        c=config(1080);c['visual'].update(theme='gta6',hook_text='Watch the car behind me',reaction=dict(text='So close',start=1,end=2))
        p=visuals.Presentation(c,plan(),editor.ROOT)
        self.assertIn('hook',[o['kind'] for o in p.overlays]);self.assertIn('reaction',[o['kind'] for o in p.overlays])
        for o in p.overlays:
            self.assertTrue(visuals.fits(o['rect'],p.safe,[[0,p.top,1080,p.bottom-p.top]]))
        frame=np.full((720,1280,3),60,np.uint8)
        a=p.compose(frame,dict(plan()[0],seconds=.5));b=p.compose(frame,dict(plan()[0],seconds=1.5))
        x,y,w,h=next(o['rect'] for o in p.overlays if o['kind']=='reaction')
        self.assertFalse(np.array_equal(a[y:y+h,x:x+w],b[y:y+h,x:x+w]))

    def test_bottom_title_is_safe_or_explicitly_omitted(self):
        c=config(1080);c['visual'].update(theme='gta6',title_placement='bottom')
        p=visuals.Presentation(c,plan(),editor.ROOT)
        for o in p.overlays:
            self.assertGreaterEqual(o['rect'][1],p.bottom)
            self.assertTrue(visuals.fits(o['rect'],p.safe,[]))

    def test_disabled_effects_identity_and_explicit_speed_audio(self):
        mapping,segments=editing.timeline({},180,30)
        self.assertEqual(mapping,list(range(180)));self.assertEqual(len(segments),1)
        with self.assertRaises(ValueError):
            editing.validate_effects({'slow_motion':[dict(start=1,end=2,speed=.5)]})
        with self.assertRaises(ValueError):
            editing.validate_effects({'slow_motion':[dict(start=1,end=2,speed=.5,audio='original')]})

    def test_slow_motion_and_replay_share_exact_output_timeline(self):
        effects=dict(slow_motion=[dict(start=1,end=2,speed=.5,audio='stretch')],
                     replays=[dict(start=3,end=4,speed=1,audio='original')])
        mapping,segments=editing.timeline(effects,180,30)
        self.assertEqual(len(mapping),240)
        self.assertEqual(mapping[30:34],[30,30,31,31])
        self.assertEqual(sum(s['output_duration'] for s in segments),8)
        self.assertTrue(any(s['replay'] for s in segments))
        graph=editing.audio_filter(segments,0)
        self.assertIn('atempo=0.500000000',graph);self.assertIn('concat=',graph)

    def test_effects_cannot_escape_clip_or_overlap(self):
        for effects in ({'replays':[dict(start=1,end=7,audio='original')]},
                        {'slow_motion':[dict(start=1,end=3,audio='stretch'),dict(start=2,end=4,audio='stretch')]},
                        {'punch_ins':[dict(start=1,end=2,strength=float('nan'))]}):
            with self.assertRaises(ValueError):
                editing.validate_effects(effects,6)

    def test_audio_diagnostics_find_silence_clipping_and_edge_energy(self):
        rate=1000;blocks=[np.ones((100,2),np.float32).tobytes()]*2+[np.zeros((100,2),np.float32).tobytes()]*10
        result=audio_quality.summarize(iter(blocks),rate,2)
        self.assertGreater(result['near_full_scale_fraction'],.1)
        self.assertEqual(result['silence_intervals'],[[.2,1.2]])
        self.assertEqual(len(result['warnings']),2)

    def test_audio_diagnostics_no_warning_for_clean_bounded_wave(self):
        sound=(.05*np.sin(np.arange(1000)*.2)).astype(np.float32)
        result=audio_quality.summarize(iter([sound.tobytes()]),1000,1)
        self.assertEqual(result['warnings'],[])

    def test_audio_diagnostics_check_explicit_edit_joins(self):
        a=np.full((100,1),.2,np.float32).tobytes();b=np.full((100,1),-.2,np.float32).tobytes()
        result=audio_quality.summarize(iter([a,b]),1000,1,joins=[.1])
        self.assertEqual(len(result['join_discontinuities']),1)
        self.assertAlmostEqual(result['join_discontinuities'][0]['sample_jump'],.4,places=5)

    def test_unexpected_silence_is_a_verification_failure(self):
        class Decoder:
            def set(self,*args):pass
            def read(self):return True,np.zeros((32,32,3),np.uint8)
            def release(self):pass
        job=SimpleNamespace(target=Path('out.mp4'),source=Path('source.mp4'),executables={},ow=32,oh=32,
            fps=editor.Fraction(30),count=30,first=0,duration=1.,start=0.,audio={'channels':2},
            config={'audio':{'stream':0}},plan=[{}]*30,layer=None)
        meta={'streams':[dict(codec_type='video',width=32,height=32,codec_name='h264',pix_fmt='yuv420p',avg_frame_rate='30',nb_frames='30'),
                         dict(codec_type='audio',codec_name='aac',channels=2)],'format':{'duration':'1.0'}}
        with patch.object(verify_output,'probe',return_value=meta),patch.object(verify_output.cv2,'VideoCapture',side_effect=lambda _:Decoder()), \
             patch.object(verify_output,'compose',return_value=np.zeros((32,32,3),np.uint8)), \
             patch.object(verify_output,'audio_samples',side_effect=[np.full(8000,.1,np.float32),np.zeros(8000,np.float32)]), \
             self.assertRaisesRegex(RuntimeError,'Unexpected output silence'):
            verify_output.verify(job,full_decode=False)

    def test_nonfinite_audio_and_invalid_regions_are_rejected(self):
        with self.assertRaises(RuntimeError):
            audio_quality.summarize(iter([np.full(100,np.nan,np.float32).tobytes()]),1000,1)
        for regions in ([[0,0,2,1]],[[0,0,0,1]],[[0,False,1,1]],'bad'):
            with self.assertRaises(ValueError):editing.validate_regions(regions)

    def test_review_overrides_are_validated_and_round_trip(self):
        c=config();m=dict(signature={'source':'fixture'},clips=[dict(candidate=dict(rank=1,start=0,end=6,score=.8),status='pending',config=c)])
        row=dict(rank=1,editing_preset='funny',hook_text='My hook',title_placement='top',
                 effects={'punch_ins':[dict(start=1,end=2,strength=.04)]},hud_regions=[[0,0,.2,.2]])
        document=dict(run_id=review.run_id(m),clips=[row])
        result=review.apply_decisions(m,document)
        self.assertEqual(result['clips'][0]['review']['hook_text'],'My hook')
        self.assertEqual(review.apply_decisions(result,document),result)
        row['effects']={'slow_motion':[dict(start=1,end=9,audio='mute')]}
        with self.assertRaises(ValueError):review.apply_decisions(m,document)

    def test_candidate_exchange_identity_validated_scores_and_hooks_not_applied(self):
        sig={'source_sha256':'a'*64};c=dict(start=0.,end=6.,score=.8,reasons={})
        c['candidate_id']=exchange.identify(c,sig['source_sha256'])
        p=exchange.payload(sig,[c]);self.assertEqual(p['schema_version'],1)
        document=dict(schema_version=1,run_id=p['run_id'],scores=[dict(candidate_id=c['candidate_id'],score=.4,hook_suggestion='Only a suggestion')])
        result=exchange.apply_scores(sig,[c],document)[0]
        self.assertAlmostEqual(result['score'],.7);self.assertNotIn('hook_text',result)
        for bad in (float('nan'),True,2):
            document['scores'][0]['score']=bad
            with self.assertRaises(ValueError):exchange.apply_scores(sig,[c],document)

    def test_external_scores_reject_wrong_run_duplicates_and_unknown_ids(self):
        sig={'source_sha256':'a'*64};c=dict(start=0.,end=6.,score=.8,candidate_id='known')
        good=dict(schema_version=1,run_id=exchange.identity(sig),scores=[dict(candidate_id='known',score=.5)])
        for doc in (dict(good,run_id='wrong'),dict(good,scores=good['scores']*2),
                    dict(good,scores=[dict(candidate_id='unknown',score=.5)])):
            with self.assertRaises(ValueError):exchange.apply_scores(sig,[c],doc)

    def test_legacy_cli_and_new_flags_parse_without_changing_encoder_preset(self):
        parser=auto_shorts.build_parser()
        old=parser.parse_args(['--input','videos/test.mp4','--output-dir','output/test','--count','15','--offline'])
        self.assertEqual(old.count,15);self.assertIsNone(old.editing_preset)
        new=parser.parse_args(['--input','videos/test.mp4','--output-dir','output/test','--preset','fast',
            '--editing-preset','action','--theme','gta6','--hook-text','My hook','--no-moment-aware-boundaries'])
        self.assertEqual(new.preset,'fast');self.assertEqual(new.editing_preset,'action')
        self.assertFalse(new.moment_aware_boundaries)

    def test_preset_override_signature_survives_json_resume_roundtrip(self):
        settings=dict(self.settings,_visual_overrides=[['title','style','bold']])
        self.assertEqual(settings,json.loads(json.dumps(settings)))


if __name__=='__main__':unittest.main(verbosity=2)
