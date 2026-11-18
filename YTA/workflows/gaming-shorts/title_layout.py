"""Responsive local title typesetting, independent of game names and themes."""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULTS = {
    'style': 'cinematic', 'subtitle': '', 'font': 'C:/Windows/Fonts/segoeuib.ttf',
    'font_size': 96, 'min_font_size': 44, 'max_lines': 3, 'subtitle_size': 28,
    'letter_spacing': 1.5, 'shadow_opacity': .55, 'shadow_blur': 3,
    'underline': True, 'uppercase': True,
}
STYLES = {
    'minimal': {'size': .65, 'spacing': .6, 'line_height': 1.10, 'underline_width': .20},
    'cinematic': {'size': 1., 'spacing': 1., 'line_height': 1.10, 'underline_width': .32},
    'bold': {'size': 1.18, 'spacing': 1.15, 'line_height': 1.04, 'underline_width': .46},
}


def options(visual):
    return dict(DEFAULTS, **visual.get('title', {}))


def validate(visual):
    values=options(visual)
    if set(values)-set(DEFAULTS) or values['style'] not in STYLES:
        raise ValueError('Unknown title option/style; use minimal, cinematic or bold')
    for key,low,high in [('font_size',32,180),('min_font_size',20,96),('subtitle_size',18,48),
                         ('letter_spacing',0,6),('shadow_opacity',0,1),('shadow_blur',0,8)]:
        value=values[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'title.{key} must be finite in [{low}, {high}]')
    if values['min_font_size']>values['font_size']:
        raise ValueError('Title minimum size cannot exceed font_size')
    if type(values['max_lines']) is not int or not 1<=values['max_lines']<=3:
        raise ValueError('title.max_lines must be 1, 2 or 3')
    if not isinstance(values['font'],str) or not values['font']:
        raise ValueError('title.font must name a local font')
    if not isinstance(values['subtitle'],str) or len(values['subtitle'])>90 or any(ord(c)<32 for c in values['subtitle']):
        raise ValueError('Title subtitle must be a single line of at most 90 characters')
    if any(type(values[k]) is not bool for k in ('underline','uppercase')):
        raise ValueError('Title underline/uppercase options must be booleans')


def measured(text,font,spacing):
    if not hasattr(font,'_yta_advances'):
        font._yta_advances={}
    for c in text:
        if c not in font._yta_advances:
            font._yta_advances[c]=font.getlength(c)
    return sum(font._yta_advances[c] for c in text)+max(0,len(text)-1)*spacing


def wrap(text,font,spacing,width):
    """Wrap at words, splitting a long token only when necessary; never discard text."""
    tokens=[]
    for word in text.split():
        part=''
        for char in word:
            if part and measured(part+char,font,spacing)>width:
                tokens.append(part); part=char
            else:
                part+=char
        if part:
            tokens.append(part)
    lines=[]
    current=[]
    for token in tokens:
        if current and measured(' '.join(current+[token]),font,spacing)>width:
            lines.append(current);current=[]
        current.append(token)
    if current:
        lines.append(current)
    # Balance adjacent lines while keeping words in reading order.
    changed=True
    while changed:
        changed=False
        for i in range(len(lines)-1):
            a,b=lines[i],lines[i+1]
            if len(a)<=1:
                continue
            old=abs(measured(' '.join(a),font,spacing)-measured(' '.join(b),font,spacing))
            newa,newb=a[:-1],[a[-1]]+b
            wa,wb=measured(' '.join(newa),font,spacing),measured(' '.join(newb),font,spacing)
            if wb<=width and abs(wa-wb)+.01<old*.9:
                lines[i],lines[i+1]=newa,newb;changed=True
    return [' '.join(line) for line in lines]


def draw_centered(draw,text,font,spacing,width,y,fill):
    x=(width-measured(text,font,spacing))/2
    baseline=y-font.getbbox(text,anchor='ls')[1]
    for char in text:
        draw.text((round(x),baseline),char,font=font,fill=fill,anchor='ls')
        x+=font.getlength(char)+spacing


def build(text,visual,width,height,scale,font_path,accent):
    """Prepare one RGBA title layer. Rendering and random-access QA reuse it unchanged."""
    o=options(visual);style=STYLES[o['style']]
    text=' '.join(text.split())
    if o['uppercase']:
        text=text.upper()
    metadata={'style':o['style'],'text':text,'lines':[],'subtitle_lines':[], 'font_size':None,
              'subtitle_omitted':False,'omitted':False,'alignment':'canvas center within symmetric safe bounds'}
    if not text:
        metadata['omitted']=True
        return None,metadata
    pad=max(4,math.ceil((o['shadow_blur']*3+5)*scale))
    available=width-2*pad
    spacing=o['letter_spacing']*style['spacing']*scale
    minimum=max(8,round(o['min_font_size']*scale))
    maximum=max(minimum,round(o['font_size']*style['size']*scale))
    subtitle=o['subtitle'].upper() if o['uppercase'] else o['subtitle']
    # Try the requested subtitle first; discard it before sacrificing primary legibility.
    for secondary in ([subtitle,''] if subtitle else ['']):
        subfont=ImageFont.truetype(font_path,max(8,round(o['subtitle_size']*scale)))
        subspace=max(.2,2*scale)
        sublines=wrap(secondary,subfont,subspace,available) if secondary else []
        if len(sublines)>2 or any(measured(s,subfont,subspace)>available for s in sublines):
            continue
        for size in range(maximum,minimum-1,-1):
            font=ImageFont.truetype(font_path,size)
            lines=wrap(text,font,spacing,available)
            if len(lines)>o['max_lines'] or any(measured(s,font,spacing)>available for s in lines):
                continue
            step=math.ceil(size*style['line_height'])
            line_heights=[font.getbbox(s,anchor='lt')[3] for s in lines]
            primary_height=step*(len(lines)-1)+line_heights[-1]
            gap=max(4,round(20*scale))
            line_thickness=max(1,round((2 if o['style']=='minimal' else 3)*scale))
            underline_height=(gap+line_thickness) if o['underline'] else 0
            substep=math.ceil(subfont.size*1.4)
            secondary_height=(gap+substep*len(sublines)) if sublines else 0
            total=2*pad+primary_height+underline_height+secondary_height
            if total>height:
                continue
            ink=Image.new('RGBA',(width,total),(0,0,0,0));d=ImageDraw.Draw(ink)
            boxes=[]
            for i,line in enumerate(lines):
                y=pad+i*step
                draw_centered(d,line,font,spacing,width,y,(247,246,252,255))
                line_width=measured(line,font,spacing)
                boxes.append([(width-line_width)/2,y,line_width,line_heights[i]])
            y=pad+primary_height
            if o['underline']:
                y+=gap
                length=max(1,round(available*style['underline_width']))
                x=(width-length)//2
                d.rounded_rectangle((x,y,x+length-1,y+line_thickness-1),radius=line_thickness//2,fill=tuple(accent)+(235,))
                y+=line_thickness
            if sublines:
                y+=gap
                for line in sublines:
                    draw_centered(d,line,subfont,subspace,width,y,tuple(round(.45*c+.55*240) for c in accent)+(255,))
                    y+=substep
            shadow=Image.new('RGBA',ink.size,(0,0,0,0))
            mask=ink.getchannel('A').filter(ImageFilter.GaussianBlur(o['shadow_blur']*scale))
            mask=mask.point(lambda a:round(a*o['shadow_opacity']))
            shadow.putalpha(mask)
            result=Image.alpha_composite(shadow,ink)
            metadata.update(lines=lines,subtitle_lines=sublines,font_size=size,subtitle_size=subfont.size if sublines else None,
                            subtitle_omitted=bool(subtitle and not sublines),line_boxes=boxes,layer_size=[width,total],letter_spacing=spacing)
            return result,metadata
    metadata.update(omitted=True,reason='Not enough safe space at the minimum readable title size')
    return None,metadata
