"""Verify codecs, source/audio preservation and rendered compositions for both variants."""
import json
import subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw
from render_variants import OUT, ASSETS, FPS, SOURCE, compose, assert_originals, executable, probe
from verify_short import audio


def main():
    if not all((OUT/f'mourning-thunder-{mode}.mp4').is_file() for mode in ('dynamic','hybrid')):
        raise SystemExit('No rendered variants to verify. Run workflows/legacy/render_variants.py --render both first.')
    ASSETS.mkdir(parents=True, exist_ok=True)
    reference=audio(SOURCE,True)
    indices=[0,6,45,74,75,90,135,165,225,255,285,310,320,330,345,375,
             405,450,495,540,570,591,598,608,614]
    source=cv2.VideoCapture(str(SOURCE))
    summary={}
    for mode in ('dynamic','hybrid'):
        target=OUT/f'mourning-thunder-{mode}.mp4'
        meta=probe(target)
        video=next(s for s in meta['streams'] if s['codec_type']=='video')
        sound=next(s for s in meta['streams'] if s['codec_type']=='audio')
        encoded_audio=audio(target)
        n=min(len(reference),len(encoded_audio))
        correlation=float(np.corrcoef(reference[:n],encoded_audio[:n])[0,1])
        assert correlation>.95
        cap=cv2.VideoCapture(str(target))
        tiles,errors=[],[]
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,frame=cap.read()
            assert ok
            source.set(cv2.CAP_PROP_POS_FRAMES,5694+index)
            ok,original=source.read()
            assert ok
            expected=compose(original,index,mode)
            error=float(np.abs(expected.astype(float)-frame.astype(float)).mean())
            assert error<6, f'{mode} frame {index} composition error {error}'
            errors.append({'frame':index,'mean_absolute_pixel_error':error})
            cv2.imwrite(str(ASSETS/f'{mode}-rendered-{index:03d}.jpg'),frame,[cv2.IMWRITE_JPEG_QUALITY,94])
            im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).resize((270,480))
            tile=Image.new('RGB',(270,504),'#101218')
            tile.paste(im,(0,24))
            ImageDraw.Draw(tile).text((8,6),f'{index/FPS:.3f}s | {mode}',fill='white')
            tiles.append(tile)
        for offset in range(0,len(tiles),8):
            subset=tiles[offset:offset+8]
            sheet=Image.new('RGB',(1080,1008),'#101218')
            for j,tile in enumerate(subset):
                sheet.paste(tile,((j%4)*270,(j//4)*504))
            sheet.save(ASSETS/f'{mode}-rendered-sheet-{offset//8+1}.jpg',quality=94)
        cap.release()
        summary[mode]={'file':target.name,'duration_seconds':float(meta['format']['duration']),
                       'dimensions':[video['width'],video['height']],'fps':video['avg_frame_rate'],
                       'frame_count':int(video['nb_frames']),'video_codec':video['codec_name'],
                       'audio_codec':sound['codec_name'],'audio_channels':sound['channels'],
                       'audio_sample_rate':sound['sample_rate'],'audio_correlation':correlation,
                       'output_audio_samples_8khz':len(encoded_audio),
                       'source_audio_samples_8khz':len(reference),'frame_comparisons':errors}
        print(f'{mode}: {len(indices)} rendered frames checked; audio correlation {correlation:.6f}',flush=True)
    source.release()
    assert_originals()
    summary['original_source_unchanged']=True
    (ASSETS/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
