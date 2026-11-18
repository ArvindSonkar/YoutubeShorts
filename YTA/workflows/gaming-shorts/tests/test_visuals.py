"""Visual contracts: gameplay preservation, safe layout, themes and reproducible QA."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import dynamic_crop as editor
import auto_shorts
import review
import visuals


def config(width=360):
    c=editor.read_json(editor.DEFAULTS)
    c['video'].update(width=width,height=width*16//9)
    c['visual']['style']='cinematic'
    c['visual']['fade_in']=0
    return c


def plan(width=1280,height=720):
    return [dict(frame=i,seconds=i,x=0.,y=0.,width=float(width),height=float(height),protected_box=None) for i in range(3)]


class VisualTests(unittest.TestCase):
    def test_legacy_original_is_pixel_identical(self):
        c=config(); c['visual']['style']='original'
        legacy=copy.deepcopy(c); legacy.pop('visual')
        frame=np.random.default_rng(10).integers(0,256,(180,320,3),np.uint8)
        geometry=plan(320,180)[0]
        np.testing.assert_array_equal(editor.compose(frame,geometry,c),editor.compose(frame,geometry,legacy))

    def test_cinematic_preserves_entire_sharp_crop_at_1080(self):
        c=config(1080); p=plan(); presentation=visuals.Presentation(c,p,editor.ROOT)
        frame=np.full((720,1280,3),[50,90,140],np.uint8)
        frame[:25]=[0,255,0]; frame[-25:]=[255,0,0]
        frame[:,:25]=[0,0,255]; frame[:,-25:]=[0,255,255]
        image=presentation.compose(frame,p[1])
        self.assertEqual(image.shape,(1920,1080,3))
        x,y,w,h=visuals.panel_layout(p[1],1080,1920,c['visual'])['gameplay']
        np.testing.assert_array_equal(image[y+2,x+2],[0,0,255])
        np.testing.assert_array_equal(image[y+h-3,x+w-3],[0,255,255])
        np.testing.assert_array_equal(image[y+2,x+w//2],[0,255,0])
        np.testing.assert_array_equal(image[y+h-3,x+w//2],[255,0,0])
        np.testing.assert_array_equal(image[y+h//2,x+w//2],[50,90,140])

    def test_no_text_or_branding_is_invented(self):
        c=config(); p=visuals.Presentation(c,plan(),editor.ROOT)
        self.assertEqual(p.overlays,[])
        self.assertIsNone(p.line)
        self.assertEqual(c['visual']['context_text'],'')
        self.assertFalse(c['visual']['branding']['enabled'])

    def test_badge_context_branding_and_progress_respect_safe_zones(self):
        c=config(1080); v=c['visual']
        v.update(theme='dmc5',context_text='User-provided context')
        v['branding'].update(enabled=True,name='Test creator')
        v['progress_line']['enabled']=True
        presentation=visuals.Presentation(c,plan(),editor.ROOT)
        self.assertEqual({o['kind'] for o in presentation.overlays},{'title','context','branding'})
        self.assertIsNotNone(presentation.line)
        blocked=[[0,presentation.top,presentation.ow,presentation.bottom-presentation.top]]
        for overlay in presentation.overlays:
            self.assertTrue(visuals.fits(overlay['rect'],presentation.safe,blocked))
            blocked.append(overlay['rect'])
        self.assertTrue(visuals.fits(presentation.line,presentation.safe,blocked))

    def test_near_full_frame_hides_optional_decorations_without_shrinking(self):
        c=config(); c['visual'].update(theme='dmc5',context_text='Context')
        c['visual']['progress_line']['enabled']=True
        p=plan(405,720)
        presentation=visuals.Presentation(c,p,editor.ROOT)
        self.assertTrue(presentation.compact)
        self.assertEqual(presentation.overlays,[])
        self.assertIsNone(presentation.line)
        layout=visuals.panel_layout(p[0],360,640,c['visual'],presentation.compact)
        self.assertEqual(layout['gameplay'],[0,0,360,640])
        self.assertIsNone(layout['outer'])

    def test_mixed_crop_uses_stable_empty_space(self):
        c=config(); c['visual']['theme']='gta5'
        p=plan(); p[1]['width']=405
        presentation=visuals.Presentation(c,p,editor.ROOT)
        self.assertTrue(presentation.compact)
        self.assertEqual(presentation.overlays,[])

    def test_theme_and_custom_accent(self):
        c=config()
        for theme in ('generic','dmc5','gta5'):
            c['visual']['theme']=theme
            self.assertEqual(visuals.Presentation(c,plan(),editor.ROOT).accent,tuple(visuals.THEMES[theme]['accent']))
        c['visual']['accent']=[10,80,200]
        self.assertEqual(visuals.Presentation(c,plan(),editor.ROOT).accent,(10,80,200))

    def test_background_global_flash_is_attenuated_and_foreground_unmodified(self):
        c=config(); c['visual']['background']['gradient']=0
        presentation=visuals.Presentation(c,plan(),editor.ROOT)
        means=[]
        for value in (40,220):
            image=presentation.compose(np.full((720,1280,3),value,np.uint8),plan()[1])
            means.append(float(image[:40].mean()))
            self.assertEqual(image[320,180,0],value)
        self.assertLess(abs(means[1]-means[0]),(220-40)*.48*.5)

    def test_random_access_preview_matches_sequential_composition(self):
        c=config(); c['visual'].update(theme='dmc5',fade_in=.35)
        c['visual']['progress_line']['enabled']=True
        p=plan(); frame=np.full((720,1280,3),90,np.uint8)
        sequential=visuals.Presentation(c,p,editor.ROOT)
        sequential.compose(frame*2,p[0]); expected=sequential.compose(frame,p[1])
        isolated=visuals.Presentation(c,p,editor.ROOT).compose(frame,p[1])
        np.testing.assert_array_equal(expected,isolated)

    def test_progress_line_starts_empty_and_ends_filled(self):
        c=config(); c['visual']['progress_line']['enabled']=True
        p=plan(); presentation=visuals.Presentation(c,p,editor.ROOT)
        frame=np.full((720,1280,3),90,np.uint8)
        x,y,w,h=presentation.line
        first=presentation.compose(frame,p[0]); last=presentation.compose(frame,p[-1])
        np.testing.assert_array_equal(first[y,x],[75,68,66])
        np.testing.assert_array_equal(last[y,x+w-1],presentation.accent[::-1])

    def test_padding_does_not_clip_rounded_panel_corners(self):
        c=config(1080); v=c['visual']
        v['panel'].update(radius=40,padding=0,border=6)
        layout=visuals.panel_layout(plan()[0],1080,1920,v)
        x,y,w,h=layout['outer']; gx,gy,gw,gh=layout['gameplay']
        inset=gx-x
        self.assertGreaterEqual(inset,40*(1-1/2**.5)+6)
        self.assertLessEqual(gx+gw,x+w)
        self.assertLessEqual(gy+gh,y+h)

    def test_visual_config_validation(self):
        original=config()['visual']
        changes=[('style','unknown'),('theme','unknown'),('context_text','x'*91),('context_text','line\nbreak'),
                 ('accent',[999,0,0]),('fade_in',float('nan'))]
        for key,value in changes:
            v=copy.deepcopy(original);v[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                visuals.validate(v)
        for section,key,value in [('background','brightness',3),('panel','glow',1),('safe_zones','right',.8),('progress_line','position','overlay')]:
            v=copy.deepcopy(original);v[section][key]=value
            with self.assertRaises(ValueError):
                visuals.validate(v)

    def test_logo_is_local_and_bound_to_resume_hash(self):
        with tempfile.TemporaryDirectory(dir=editor.ROOT/'output') as folder:
            path=Path(folder)/'logo.png';Image.new('RGBA',(40,40),(200,40,80,128)).save(path)
            c=config();c['visual']['branding'].update(enabled=True,logo=str(path))
            c['visual'].update(visuals.asset_hashes(c['visual'],editor.ROOT))
            presentation=visuals.Presentation(c,plan(),editor.ROOT)
            self.assertEqual(presentation.overlays[0]['kind'],'branding')
            Image.new('RGBA',(40,40),(0,255,0,255)).save(path)
            with self.assertRaisesRegex(ValueError,'asset changed'):
                visuals.Presentation(c,plan(),editor.ROOT)

    def test_mask_cache_is_bounded(self):
        for i in range(60):
            visuals.decoration_masks((24,600+i,1032,600),22,1080,1920)
        self.assertLessEqual(visuals.decoration_masks.cache_info().currsize,24)

    def test_review_visual_choices_and_context_persist(self):
        m=dict(signature={'source':'fixture'},clips=[dict(candidate=dict(rank=1,start=0.,end=6.,score=.8),
                                                       status='pending',config=config())])
        decision={'run_id':review.run_id(m),'clips':[dict(rank=1,visual_style='original',theme='gta5',context_text='My supplied context')]}
        result=review.apply_decisions(m,decision)
        self.assertEqual(result['clips'][0]['review']['context_text'],'My supplied context')
        self.assertEqual(result['clips'][0]['review']['visual_style'],'original')
        self.assertEqual(m['clips'][0]['config']['visual']['context_text'],'')
        decision['clips'][0]['context_text']='x'*91
        with self.assertRaises(ValueError):
            review.apply_decisions(m,decision)

    def test_html_escapes_context_and_has_style_controls(self):
        c=config();c['visual']['context_text']='</script><script>alert(1)</script>'
        m=dict(signature={'source':str(editor.ROOT/'videos/DMC5.mp4')},clips=[dict(candidate=dict(rank=1,start=0.,end=6.,score=.8),
                status='pending',config=c,framing={})])
        page=review.document(editor.ROOT/'output',m)
        self.assertNotIn('</script><script>alert(1)',page)
        self.assertIn('class="visual_style"',page)
        self.assertIn('short-01-original.jpg',page)
        self.assertIn('short-01-cinematic.jpg',page)


if __name__=='__main__':
    unittest.main(verbosity=2)
