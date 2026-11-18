"""Bounded, matched presentation benchmark using an existing single-clip configuration."""
import argparse
import json
from pathlib import Path
import sys

import cv2

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import auto_shorts
import dynamic_crop as editor
import progress
from verify_output import verify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--subtitle')
    parser.add_argument('--preview-only',action='store_true')
    parser.add_argument('--current-panel-defaults',action='store_true',help='Compare the updated panel defaults against the old saved job')
    args=parser.parse_args()
    directory=editor.generated_path(args.output_dir)
    directory.mkdir(parents=True,exist_ok=False)
    raw=editor.read_json(args.config)
    clip=raw.pop('clip')
    config=editor.merge(editor.read_json(editor.DEFAULTS),raw)
    config.update(clip=clip,output=str(directory/'short.mp4'))
    if args.subtitle is not None:
        config['visual']['title']['subtitle']=args.subtitle
    if args.current_panel_defaults:
        config['visual']['panel']=editor.read_json(editor.DEFAULTS)['visual']['panel']
    recorder=progress.Session(directory)
    cv2.setNumThreads(2)
    with progress.session(recorder):
        context=editor.SourceContext(config['source'],editor.tools(config))
        job=editor.Job(config,context)
        if not 2 <= job.duration <= 12:
            raise ValueError('Benchmark requires an existing 2–12 second clip; no long renders allowed')
        auto_shorts.atomic_json(directory/'config.json',config)
        with progress.stage('Benchmark preview',category='Previews'):
            auto_shorts.thumbnail(job,directory/'contact.jpg')
            frame=editor.capture(job,job.count//2)
            image=editor.compose(frame,job.plan[job.count//2],job.config,job.layer,job.presentation)
            cv2.imwrite(str(directory/'frame.png'),image)
            auto_shorts.atomic_json(directory/'layout.json',job.presentation.report())
        if not args.preview_only:
            editor.render(job)
            auto_shorts.atomic_json(directory/'qa.json',verify(job,full_decode=False))
        context.assert_unchanged(full=True)
        recorder.counts.update(successful=0 if args.preview_only else 1,
                               rendered_this_invocation=0 if args.preview_only else 1,
                               generated_video_seconds=0 if args.preview_only else job.duration)
        recorder.ended=recorder.clock()
        recorder.summary('planned' if args.preview_only else 'complete')


if __name__=='__main__':
    main()
