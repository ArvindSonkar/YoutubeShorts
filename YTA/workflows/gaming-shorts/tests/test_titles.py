"""Responsive title contracts, independent of a particular game or clip."""
import copy
from pathlib import Path
import sys
import unittest

from PIL import ImageFont

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import dynamic_crop as editor
import review
import title_layout as titles
import visuals
from test_visuals import config, plan


class TitleTests(unittest.TestCase):
    def build(self, text='DEVIL MAY CRY 5', width=734, height=470, scale=1, **options):
        v=config()['visual']
        v['title'].update(options)
        image, meta=titles.build(text,v,width,height,scale,v['title']['font'],(180,135,255))
        return image,meta

    def assert_fits(self, image, meta, width, height):
        self.assertIsNotNone(image)
        self.assertLessEqual(image.height,height)
        self.assertEqual(image.width,width)
        for x,y,w,h in meta['line_boxes']:
            self.assertGreaterEqual(x,0)
            self.assertGreaterEqual(y,0)
            self.assertLessEqual(x+w,width)
            self.assertLessEqual(y+h,image.height)
            self.assertAlmostEqual(x+w/2,width/2)

    def test_large_centered_title_and_secondary_hierarchy(self):
        image,m=self.build(subtitle='CINEMATIC GAMEPLAY')
        self.assert_fits(image,m,734,470)
        self.assertEqual(' '.join(m['lines']),'DEVIL MAY CRY 5')
        self.assertEqual(m['subtitle_lines'],['CINEMATIC GAMEPLAY'])
        self.assertGreater(m['font_size'],m['subtitle_size']*2)
        self.assertGreater(m['font_size'],30)

    def test_long_title_wraps_without_losing_words(self):
        name='THE LEGEND OF THE FORGOTTEN KINGDOM COMPLETE EDITION'
        image,m=self.build(name)
        self.assert_fits(image,m,734,470)
        self.assertEqual(' '.join(m['lines']),name)
        self.assertLessEqual(len(m['lines']),3)
        self.assertGreaterEqual(m['font_size'],44)
        self.assertLess(m['font_size'],96)

    def test_unbroken_long_name_is_split_without_lost_characters(self):
        name='ABCDEFGHIJKLMNOPQRSTUVWXYZ'*2
        image,m=self.build(name)
        self.assert_fits(image,m,734,470)
        self.assertEqual(''.join(m['lines']).replace(' ',''),name)

    def test_narrow_width_reduces_font_when_line_count_is_bounded(self):
        wide,a=self.build('RACING LEGENDS',max_lines=1)
        narrow,b=self.build('RACING LEGENDS',width=480,max_lines=1)
        self.assert_fits(narrow,b,480,470)
        self.assertLess(b['font_size'],a['font_size'])

    def test_responsive_resolution_scales_font_and_stays_inside_bounds(self):
        for scale in (1,.5,1/3):
            width=round(734*scale);height=round(470*scale)
            image,m=self.build(width=width,height=height,scale=scale)
            self.assert_fits(image,m,width,height)
            self.assertLessEqual(m['font_size'],round(96*scale))
            self.assertGreaterEqual(m['font_size'],round(44*scale))

    def test_styles_produce_distinct_hierarchy_without_game_specific_rules(self):
        sizes=[]
        for style in ('minimal','cinematic','bold'):
            image,m=self.build('HALO',style=style)
            self.assert_fits(image,m,734,470)
            sizes.append(m['font_size'])
        self.assertLess(sizes[0],sizes[1])
        self.assertLess(sizes[1],sizes[2])

    def test_subtitle_is_optional_and_yields_to_primary_in_tight_space(self):
        _,plain=self.build('HALO')
        self.assertEqual(plain['subtitle_lines'],[])
        image,m=self.build('HALO',height=85,subtitle='CINEMATIC GAMEPLAY')
        self.assert_fits(image,m,734,85)
        self.assertTrue(m['subtitle_omitted'])
        self.assertEqual(m['lines'],['HALO'])

    def test_insufficient_space_omits_instead_of_overlapping_or_truncating(self):
        image,m=self.build(height=10)
        self.assertIsNone(image)
        self.assertTrue(m['omitted'])
        image,m=self.build('W'*120,width=100)
        self.assertIsNone(image)
        self.assertTrue(m['omitted'])

    def test_centered_title_respects_asymmetric_safe_area_and_changing_panel(self):
        for geometry in (plan(1280,720),plan(900,720),plan(700,720)):
            c=config(1080);c['visual']['theme']='dmc5'
            p=visuals.Presentation(c,geometry,editor.ROOT)
            title=next(o for o in p.overlays if o['kind']=='title')
            x,y,w,h=title['rect']
            self.assertAlmostEqual(x+w/2,540,delta=.5)
            self.assertTrue(visuals.fits(title['rect'],p.safe,[[0,p.top,1080,p.bottom-p.top]]))
            self.assertLessEqual(y+h,p.top-28)

    def test_theme_and_custom_title_share_typesetting_and_accept_accent(self):
        for theme in ('dmc5','gta5','gta6','custom'):
            c=config(1080);v=c['visual'];v['theme']=theme
            if theme=='custom':
                v.update(game_title='FUTURE GAME',accent=[20,120,180])
            visuals.validate(v)
            p=visuals.Presentation(c,plan(),editor.ROOT)
            self.assertFalse(p.title_metadata['omitted'])
            self.assertEqual(p.title_metadata['style'],'cinematic')
            self.assertEqual(p.title_metadata['text'],visuals.title(v))

    def test_new_panel_defaults_increase_area_and_retain_aspect(self):
        v=config(1080)['visual'];old=copy.deepcopy(v)
        old['panel'].update(margin=24,padding=12)
        a=visuals.panel_layout(plan()[0],1080,1920,old)['gameplay']
        b=visuals.panel_layout(plan()[0],1080,1920,v)['gameplay']
        self.assertGreater(b[2]*b[3],a[2]*a[3])
        self.assertAlmostEqual(b[3],b[2]*720/1280,delta=.5)

    def test_old_visual_config_gains_title_defaults_and_font_hash_is_enforced(self):
        c=config(1080);v=c['visual'];v['theme']='dmc5'
        v.pop('title');v.pop('title_font_sha256')
        visuals.validate(v)
        self.assertEqual(visuals.Presentation(c,plan(),editor.ROOT).title_metadata['style'],'cinematic')
        v['title_font_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'asset changed'):
            visuals.Presentation(c,plan(),editor.ROOT)

    def test_invalid_options_fail_before_render(self):
        for key,value in [('style','neon'),('font_size',float('nan')),('min_font_size',97),
                          ('max_lines',4),('letter_spacing',-1),('subtitle','x'*91),
                          ('subtitle','line\nbreak'),('underline','yes'),('unknown',1)]:
            v=config()['visual'];v['title'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                titles.validate(v)

    def test_review_round_trip_keeps_custom_title_subtitle_and_style(self):
        m=dict(signature={'source':'fixture'},clips=[dict(candidate=dict(rank=1,start=0.,end=6.,score=.8),
                status='pending',config=config())])
        decision=dict(run_id=review.run_id(m),clips=[dict(rank=1,theme='custom',game_title='MY GAME',
                title_style='bold',subtitle='CUSTOM GAMEPLAY')])
        result=review.apply_decisions(m,decision)['clips'][0]['review']
        for key in ('game_title','title_style','subtitle'):
            self.assertEqual(result[key],decision['clips'][0][key])
        page=review.document(editor.ROOT/'output',m)
        for field in ('game_title','title_style','subtitle'):
            self.assertIn(f'class="{field}"',page)


if __name__=='__main__':
    unittest.main(verbosity=2)
