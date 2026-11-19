"""Versioned local interchange for optional external rerankers; never uploads or loads models."""
import copy
import hashlib
import json
import cv2
import editing

VERSION=1


def identity(signature):
    return hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()


def identify(candidate,source_hash):
    key=f'{source_hash}:{candidate["start"]:.6f}:{candidate["end"]:.6f}'
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def payload(signature,candidates):
    for c in candidates[:40]:
        if c.get('candidate_id')!=identify(c,signature['source_sha256']):
            raise ValueError('Candidate identity does not match its source interval')
    return dict(schema_version=VERSION,run_id=identity(signature),source_sha256=signature['source_sha256'],
        note='Local exchange only. Scores are heuristic by default. Hooks from external tools are suggestions requiring review.',
        candidates=[dict(candidate_id=c['candidate_id'],start=c['start'],end=c['end'],duration=c['end']-c['start'],
            rule_score=c.get('rule_score',c['score']),features=c.get('reasons',{}),
            activity_pattern=c.get('activity_pattern','mixed'),suggested_editing=c.get('suggested_editing'),
            warnings=c.get('warnings',[]),boundary=c.get('boundary',{})) for c in candidates[:40]])


def apply_scores(signature,candidates,document):
    if not isinstance(document,dict) or document.get('schema_version')!=VERSION or document.get('run_id')!=identity(signature):
        raise ValueError('Reranker scores belong to a different run or unsupported schema')
    if set(document)-{'schema_version','run_id','scores','provider','weight'}:
        raise ValueError('Unknown reranker document fields')
    provider=document.get('provider','external')
    if not isinstance(provider,str) or len(provider)>80 or any(ord(c)<32 for c in provider):
        raise ValueError('Reranker provider must be a short text label')
    weight=document.get('weight',.25);editing.finite(weight,0,.5,'reranker weight')
    rows=document.get('scores')
    if not isinstance(rows,list) or not rows or len(rows)>40:
        raise ValueError('Scores must contain 1-40 candidate entries')
    result=copy.deepcopy(candidates);lookup={c['candidate_id']:c for c in result[:40]};seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'candidate_id','score','reason','hook_suggestion'}:
            raise ValueError('Invalid external score row')
        key=row.get('candidate_id')
        if not isinstance(key,str) or key not in lookup or key in seen:
            raise ValueError('Unknown or duplicate candidate score')
        seen.add(key);editing.finite(row.get('score'),0,1,'external score')
        for field,limit in [('reason',300),('hook_suggestion',120)]:
            value=row.get(field,'')
            if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 for c in value):
                raise ValueError('External reason/hook must be bounded single-line text')
        c=lookup[key];rule=c.get('rule_score',c['score']);c['rule_score']=rule
        c['external_score']=dict(row,provider=provider,weight=weight)
        c['score']=round((1-weight)*rule+weight*row['score'],5)
    return sorted(result,key=lambda c:(-c['score'],c['start']))


def export(directory,source,signature,candidates,frames=False):
    target=directory/'exchange';target.mkdir(exist_ok=True)
    if not target.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Candidate export directory escapes the run directory')
    document=payload(signature,candidates)
    if frames:
        # At most 20 candidates, three small frames each; one decoder, no video copies/uploads.
        cap=cv2.VideoCapture(str(source))
        try:
            for c in document['candidates'][:20]:
                paths=[]
                for i,t in enumerate((c['start'],(c['start']+c['end'])/2,max(c['start'],c['end']-.1))):
                    path=target/f'{c["candidate_id"]}-{i}.jpg'
                    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,image=cap.read()
                    if not ok:
                        raise RuntimeError('Candidate frame export failed to decode')
                    image=cv2.resize(image,(480,max(1,round(image.shape[0]*480/image.shape[1]))))
                    if not cv2.imwrite(str(path),image):
                        raise RuntimeError('Candidate frame export failed to write')
                    paths.append(dict(path=path.name,source_seconds=round(cap.get(cv2.CAP_PROP_POS_MSEC)/1000,6)))
                c['sampled_frames']=paths
        finally:
            cap.release()
    pending=target/'candidates.json.tmp'
    pending.write_text(json.dumps(document,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    pending.replace(target/'candidates.json')
    return document
