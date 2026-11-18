"""Deterministic, local cinematic composition. Decoration never masks gameplay pixels."""
from functools import lru_cache
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import title_layout

THEMES = {
    'generic': {'accent': [170, 183, 201], 'title': ''},
    'dmc5': {'accent': [180, 135, 255], 'title': 'DEVIL MAY CRY 5'},
    'gta5': {'accent': [125, 205, 151], 'title': 'GRAND THEFT AUTO V'},
    'gta6': {'accent': [239, 148, 204], 'title': 'GRAND THEFT AUTO VI'},
    'custom': {'accent': [170, 183, 201], 'title': ''},
}


def validate(v):
    title_layout.validate(v)
    if v['style'] not in ('original', 'cinematic') or v['theme'] not in THEMES:
        raise ValueError('Unknown visual style/theme')
    def number(value, key, low, high):
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'visual.{key} must be finite in [{low}, {high}]')
    for key, limit in [('game_title', 120), ('context_text', 90)]:
        value = v[key]
        if not isinstance(value, str) or len(value) > limit or any(ord(c)<32 for c in value):
            raise ValueError(f'visual.{key} must be a single line of at most {limit} characters')
    b, p, z, branding, line = (v[k] for k in ('background','panel','safe_zones','branding','progress_line'))
    for key, low, high in [('blur_sigma',0,30),('brightness',.25,1),('saturation',0,1),('gradient',0,.6),('stabilization',0,1)]:
        number(b[key], 'background.'+key, low, high)
    for key, low, high in [('padding',0,48),('margin',0,80),('radius',0,40),('border',0,6),('glow',0,.5),('shadow',0,.5)]:
        number(p[key], 'panel.'+key, low, high)
    number(v['fade_in'], 'fade_in', 0, 2)
    for key in ('left','right','top','bottom'):
        number(z[key], 'safe_zones.'+key, 0, .4)
    if z['left']+z['right'] > .6 or z['top']+z['bottom'] > .6:
        raise ValueError('Safe zone margins leave too little usable area')
    for section in (p, branding, line):
        if type(section['enabled']) is not bool:
            raise ValueError('Visual enabled switches must be booleans')
    if not isinstance(branding['name'], str) or len(branding['name'])>40 or any(ord(c)<32 for c in branding['name']):
        raise ValueError('Branding name must be one line of at most 40 characters')
    for key in ('logo','name'):
        if not isinstance(branding[key], str):
            raise ValueError('Branding values must be strings')
    if not isinstance(v['font'], str) or not v['font']:
        raise ValueError('A local visual font path is required')
    number(branding['opacity'], 'branding.opacity', 0, 1)
    number(line['thickness'], 'progress_line.thickness', 1, 6)
    if line['position'] not in ('above', 'below'):
        raise ValueError('Progress position must be above or below the gameplay')
    if v['accent'] is not None:
        if not isinstance(v['accent'], list) or len(v['accent'])!=3:
            raise ValueError('Custom accent must be an RGB list')
        for c in v['accent']:
            number(c, 'accent', 0, 255)
    for key in ('font_sha256','logo_sha256','title_font_sha256'):
        value = v.get(key)
        if value is not None and (not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value)):
            raise ValueError('Visual asset hashes must be lowercase SHA-256 or null')


def asset_path(value, root):
    path = Path(value)
    return (path if path.is_absolute() else root/path).resolve()


def title(v):
    return v['game_title'] or THEMES[v['theme']]['title']


def asset_hashes(v, root):
    """Bind locally supplied assets to resume identity; never fetch assets."""
    result = {'font_sha256': None, 'logo_sha256': None, 'title_font_sha256': None}
    if v['style'] != 'cinematic':
        return result
    text = title(v) or v['context_text'] or (v['branding']['enabled'] and v['branding']['name'])
    for key, path in [('font', v['font'] if text else ''),
                      ('title_font', title_layout.options(v)['font'] if title(v) else ''),
                      ('logo', v['branding']['logo'] if v['branding']['enabled'] else '')]:
        if path:
            local = asset_path(path, root)
            if not local.is_file():
                raise ValueError(f'Local {key} asset missing: {local}')
            result[key+'_sha256'] = hashlib.sha256(local.read_bytes()).hexdigest()
    return result


def rounded(mask, rectangle, radius, color):
    x,y,w,h = map(int, rectangle)
    if min(w,h)<=0:
        return
    r = max(0, min(int(radius), w//2, h//2))
    cv2.rectangle(mask,(x+r,y),(x+w-r-1,y+h-1),color,-1,cv2.LINE_AA)
    cv2.rectangle(mask,(x,y+r),(x+w-1,y+h-r-1),color,-1,cv2.LINE_AA)
    for cx,cy in ((x+r,y+r),(x+w-r-1,y+r),(x+r,y+h-r-1),(x+w-r-1,y+h-r-1)):
        cv2.circle(mask,(cx,cy),r,color,-1,cv2.LINE_AA)


def panel_layout(geometry, ow, oh, v, compact=False):
    """Fit the existing crop inside a decorated frame without cropping any more pixels."""
    scale = ow/1080
    natural_height = min(oh, max(1, round(geometry['height']*ow/geometry['width'])))
    decorated = v['panel']['enabled'] and not compact and natural_height/oh < .80
    if not decorated:
        return {'gameplay': [0,(oh-natural_height)//2,ow,natural_height], 'outer': None, 'radius': 0}
    p = v['panel']
    radius = round(p['radius']*scale)
    border = round(p['border']*scale)
    # A rectangle inside rounded corners is safe only with sufficient inset.
    inset = max(round(p['padding']*scale), math.ceil(radius*(1-1/math.sqrt(2)))+border+1)
    margin = max(round(p['margin']*scale), border+1)
    width = max(2, ow-2*(margin+inset))
    height = min(oh-2*inset, max(1, round(geometry['height']*width/geometry['width'])))
    x, y = (ow-width)//2, (oh-height)//2
    return {'gameplay':[x,y,width,height], 'outer':[x-inset,y-inset,width+2*inset,height+2*inset], 'radius':radius}


def safe_rectangle(v, ow, oh):
    z = v['safe_zones']
    return [math.ceil(z['left']*ow), math.ceil(z['top']*oh),
            math.floor((1-z['right'])*ow), math.floor((1-z['bottom'])*oh)]


def fits(rect, safe, blocked):
    x,y,w,h = rect
    if not (safe[0]<=x and safe[1]<=y and x+w<=safe[2] and y+h<=safe[3]):
        return False
    return not any(x < bx+bw and x+w > bx and y < by+bh and y+h > by for bx,by,bw,bh in blocked)


@lru_cache(maxsize=24)
def decoration_masks(rect, radius, ow, oh):
    """Bounded, small masks; no full-frame float glow/shadow allocation."""
    shape = (240,135)
    mask = np.zeros(shape, np.uint8)
    x,y,w,h = rect
    scaled = [round(x*135/ow),round(y*240/oh),round(w*135/ow),round(h*240/oh)]
    rounded(mask, scaled, max(1,round(radius*135/ow)), 255)
    glow = cv2.GaussianBlur(mask,(0,0),2.4).astype(np.float32)/255
    shifted = np.roll(mask, 2, axis=0)
    shadow = cv2.GaussianBlur(shifted,(0,0),2.).astype(np.float32)/255
    return glow,shadow


class Presentation:
    def __init__(self, config, plan, root):
        self.v = config['visual']
        self.ow, self.oh = config['video']['width'], config['video']['height']
        self.scale = self.ow/1080
        self.accent = tuple(int(c) for c in (self.v['accent'] or THEMES[self.v['theme']]['accent']))
        actual = asset_hashes(self.v, root)
        for key,value in actual.items():
            if self.v.get(key) is not None and self.v[key] != value:
                raise ValueError('Visual asset changed; use a new run or restore the original asset')
        self.assets = actual
        self.compact = any(g['height']*self.ow/g['width'] >= self.oh*.80 for g in plan)
        layouts = [panel_layout(g, self.ow, self.oh, self.v, self.compact) for g in plan]
        self.safe = safe_rectangle(self.v,self.ow,self.oh)
        self.overlays = []
        self.line = None
        self.last_frame = max(1,len(plan)-1)
        self.font_path = str(asset_path(self.v['font'],root))
        self.title_font_path = str(asset_path(title_layout.options(self.v)['font'],root))
        self.title_metadata = {'omitted':True,'reason':'No supplied game title or insufficient space'}
        # Use common empty bands across the WHOLE clip to avoid layout popping.
        self.top = min((p['outer'] or p['gameplay'])[1] for p in layouts)
        self.bottom = max((p['outer'] or p['gameplay'])[1]+(p['outer'] or p['gameplay'])[3] for p in layouts)
        gap = round(28*self.scale)
        sx,sy,sr,sb = self.safe
        width = sr-sx
        if not self.compact:
            pieces = []
            center=self.ow/2
            title_width=max(1,math.floor(2*min(center-sx,sr-center)))
            context = self.text_image(self.v['context_text'],32,title_width,wrap=True) if self.v['context_text'] else None
            title_height=max(0,self.top-gap-sy-(context.height+gap if context else 0))
            if title(self.v):
                title_image,self.title_metadata=title_layout.build(title(self.v),self.v,title_width,title_height,
                    self.scale,self.title_font_path,self.accent)
                if title_image is None and context:
                    context=None
                    title_image,self.title_metadata=title_layout.build(title(self.v),self.v,title_width,max(0,self.top-gap-sy),
                        self.scale,self.title_font_path,self.accent)
                pieces.append(('title',title_image))
            if self.v['context_text']:
                pieces.append(('context',context))
            pieces = [(kind,img) for kind,img in pieces if img is not None]
            while pieces and sum(img.height for _,img in pieces)+gap*max(0,len(pieces)-1) > self.top-gap-sy:
                pieces.pop()  # Omit optional context first; never overlap gameplay.
            height = sum(img.height for _,img in pieces)+gap*max(0,len(pieces)-1)
            y = sy+max(0, round((self.top-gap-sy-height)*.62))
            for kind,img in pieces:
                self.add(kind,img,(self.ow-img.width)//2,y,1.)
                y += img.height+gap
            branding = self.v['branding']
            if branding['enabled'] and (branding['name'] or branding['logo']):
                brand = self.brand_image(branding,root,width)
                if brand:
                    self.add('branding',brand,sx,self.bottom+gap,branding['opacity'])
            line = self.v['progress_line']
            if line['enabled']:
                h = max(1, round(line['thickness']*self.scale))
                y = self.top-round(14*self.scale) if line['position']=='above' else self.bottom+round(16*self.scale)
                rect = [sx,y,width,h]
                if fits(rect,self.safe,[[0,self.top,self.ow,self.bottom-self.top]]+[o['rect'] for o in self.overlays]):
                    self.line=rect
        self.gradient = (1-self.v['background']['gradient']*np.abs(np.linspace(-1,1,240))**1.5).astype(np.float32)[:,None,None]

    def text_image(self, text, size, width, badge=False, wrap=False):
        size = max(12,round(size*self.scale))
        pad = max(6,round(18*self.scale))
        minimum = max(10,round(24*self.scale))
        while size >= minimum:
            font = ImageFont.truetype(self.font_path,size)
            lines = [text]
            if wrap:
                lines=['']
                for word in text.split():
                    candidate=(lines[-1]+' '+word).strip()
                    if font.getlength(candidate) <= width-2*pad:
                        lines[-1]=candidate
                    else:
                        lines.append(word)
            if len(lines)<=2 and all(font.getlength(s)<=width-2*pad for s in lines):
                break
            size-=1
        else:
            return None
        w = min(width, math.ceil(max(font.getlength(s) for s in lines))+2*pad)
        line_height=math.ceil(size*1.35)
        h = line_height*len(lines)+2*pad
        image=Image.new('RGBA',(w,h),(0,0,0,0))
        d=ImageDraw.Draw(image)
        if badge:
            d.rounded_rectangle((0,0,w-1,h-1),radius=round(12*self.scale),fill=(16,18,28,190),outline=self.accent+(130,),width=max(1,round(self.scale)))
            d.rounded_rectangle((0,pad,max(2,round(3*self.scale)),h-pad),radius=1,fill=self.accent+(255,))
        for i,line in enumerate(lines):
            d.text((pad,pad+i*line_height),line,font=font,fill=(240,240,246,255),anchor='lt',stroke_width=0)
        return image

    def brand_image(self, branding, root, width):
        parts=[]
        if branding['logo']:
            with Image.open(asset_path(branding['logo'],root)) as source:
                logo=source.convert('RGBA')
                logo.thumbnail((round(52*self.scale),round(52*self.scale)),Image.Resampling.LANCZOS)
                parts.append(logo.copy())
        if branding['name']:
            text=self.text_image(branding['name'],26,width-sum(p.width for p in parts)-12)
            if text is not None:
                parts.append(text)
        if not parts:
            return None
        image=Image.new('RGBA',(sum(p.width for p in parts)+12*(len(parts)-1),max(p.height for p in parts)),(0,0,0,0))
        x=0
        for part in parts:
            image.paste(part,(x,(image.height-part.height)//2))
            x+=part.width+12
        return image

    def add(self, kind, image, x, y, opacity):
        rect=[x,y,image.width,image.height]
        blocked=[[0,self.top,self.ow,self.bottom-self.top]]+[o['rect'] for o in self.overlays]
        if fits(rect,self.safe,blocked):
            rgba=np.asarray(image)
            self.overlays.append(dict(kind=kind,rect=rect,rgb=rgba[:,:,:3][:,:,::-1].copy(),alpha=rgba[:,:,3:4].astype(np.float32)/255*opacity))

    def report(self):
        return dict(style='cinematic', theme=self.v['theme'], compact=self.compact, safe_rectangle=self.safe,
                    title=self.title_metadata,
                    overlays=[{'kind':o['kind'],'rect':o['rect']} for o in self.overlays], progress_line=self.line,
                    common_gameplay_band=[0,self.top,self.ow,self.bottom-self.top], asset_hashes=self.assets,
                    note='Safe margins are configurable estimates; platform UI varies. All decorative text is outside gameplay.')

    def background(self, frame, layout):
        sw,sh=frame.shape[1],frame.shape[0]
        cropw=max(1,min(sw,round(sh*self.ow/self.oh)))
        small=cv2.resize(frame[:,(sw-cropw)//2:(sw+cropw)//2],(135,240),interpolation=cv2.INTER_AREA)
        b=self.v['background']
        if b['blur_sigma']:
            small=cv2.GaussianBlur(small,(0,0),b['blur_sigma'])
        values=small.astype(np.float32)
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY).astype(np.float32)[:,:,None]
        values=gray+(values-gray)*b['saturation']
        # Stateless luminance compression preserves exact random-access QA and source motion.
        # No frame blending/lag; it attenuates global flashes only in the decorative background.
        exposure=float(np.clip(105/max(float(gray.mean()),1.),.35,2.5))
        values*=((1-b['stabilization'])+b['stabilization']*exposure)*b['brightness']
        values*=self.gradient
        if layout['outer']:
            glow,shadow=decoration_masks(tuple(layout['outer']),layout['radius'],self.ow,self.oh)
            values*=1-shadow[:,:,None]*self.v['panel']['shadow']
            alpha=glow[:,:,None]*self.v['panel']['glow']
            values=values*(1-alpha)+np.asarray(self.accent[::-1],np.float32)*alpha
        return cv2.resize(np.clip(values,0,255).astype(np.uint8),(self.ow,self.oh),interpolation=cv2.INTER_LINEAR)

    def compose(self, frame, geometry):
        layout=panel_layout(geometry,self.ow,self.oh,self.v,self.compact)
        left,top,width,height=layout['gameplay']
        canvas=self.background(frame,layout) if height < self.oh or width < self.ow else np.empty((self.oh,self.ow,3),np.uint8)
        outer=layout['outer']
        if outer:
            p=self.v['panel']; border=round(p['border']*self.scale)
            rounded(canvas,outer,layout['radius'],self.accent[::-1] if border else (21,20,25))
            if border:
                x,y,w,h=outer
                rounded(canvas,(x+border,y+border,w-2*border,h-2*border),max(0,layout['radius']-border),(21,20,25))
        x,y,w,h=(geometry[k] for k in ('x','y','width','height'))
        transform=np.array([[w/width,0,x],[0,h/height,y]],np.float32)
        # Every pixel in the original selected crop is represented; corners apply to its outer frame.
        canvas[top:top+height,left:left+width]=cv2.warpAffine(frame,transform,(width,height),flags=cv2.INTER_LANCZOS4|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
        fade=min(1.,max(0.,geometry['seconds']/self.v['fade_in'])) if self.v['fade_in'] else 1.
        fade=fade*fade*(3-2*fade)
        for overlay in self.overlays:
            ox,oy,ow,oh=overlay['rect']
            roi=canvas[oy:oy+oh,ox:ox+ow]
            alpha=overlay['alpha']*fade
            roi[:]=(roi*(1-alpha)+overlay['rgb']*alpha).astype(np.uint8)
        if self.line:
            x,y,w,h=self.line
            cv2.rectangle(canvas,(x,y),(x+w-1,y+h-1),(75,68,66),-1)
            filled=round(w*min(1.,max(0.,geometry['frame']/self.last_frame)))
            if filled:
                cv2.rectangle(canvas,(x,y),(x+filled-1,y+h-1),self.accent[::-1],-1)
        return canvas
