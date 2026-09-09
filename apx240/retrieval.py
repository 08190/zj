"""Exact alarms plus versioned, metadata-filtered semantic document retrieval."""
import functools
import hashlib
import math
import os
import re
from .providers import configuration, configuration_status, post_json, ProviderError
from .diagnostics import safe_error

REPAIR_ALARMS={'WO-240-031':'A101','WO-240-042':'A203','WO-240-051':'A310','WO-240-063':'A401','WO-240-077':'A520'}

def vectors(texts):
    cfg=configuration('embedding')
    if not all(cfg.values()): raise ProviderError('not_configured')
    result=post_json(cfg,{'model':cfg['model'],'input':texts,'encoding_format':'float'})
    try:
        items=result['data']
        if not isinstance(items,list) or len(items)!=len(texts): raise ValueError()
        if any(type(x['index']) is not int for x in items) or {x['index'] for x in items}!=set(range(len(texts))): raise ValueError()
        out=[x['embedding'] for x in sorted(items,key=lambda x:x['index'])]
        if not out or not isinstance(out[0],list) or not out[0]: raise ValueError()
        for v in out:
            if not isinstance(v,list) or len(v)!=len(out[0]) or any(type(n) not in [int,float] or not math.isfinite(n) for n in v): raise ValueError()
            if not math.isfinite(math.hypot(*v)) or math.hypot(*v)==0: raise ValueError()
        return out
    except (KeyError,TypeError,ValueError): raise ProviderError('invalid_embedding_response') from None

@functools.lru_cache(maxsize=8)
def document_vectors(version,endpoint,model,key_fingerprint,texts):
    # Cache holds documents only, never现场输入 or raw credentials.
    return vectors(list(texts))

def cosine(a,b):
    if len(a)!=len(b): raise ProviderError('embedding_dimension_changed')
    na=math.hypot(*a);nb=math.hypot(*b)
    if not na or not nb: raise ProviderError('zero_vector')
    return sum((x/na)*(y/nb) for x,y in zip(a,b))

def corpus(kb):
    docs=[]
    groups=[(list(kb.alarms.values()),'alarm_manual',4),(kb.history,'history_case',5),(kb.repairs,'maintenance_record',6)]
    for rows,kind,page in groups:
        content=kb.pages[page-1]
        for item in rows:
            sid=item['id']; start=content.index(sid)
            ends=[content.find(other['id'],start+len(sid)) for other in rows if other['id']!=sid]
            end=min([x for x in ends if x>=0] or [len(content)])
            if kind=='maintenance_record':
                dates=list(re.finditer(r'\d{4}-\d{2}-\d{2}',content))
                start=max([d.start() for d in dates if d.start()<start] or [start])
                end=min([d.start() for d in dates if d.start()>start] or [len(content)])
            snippet=content[start:end].strip()
            alarm=sid if kind=='alarm_manual' else item['alarm'] if kind=='history_case' else REPAIR_ALARMS[sid]
            e=kb.evidence(sid,kind,page,item['section'],snippet,kind!='alarm_manual')
            docs.append({**e.__dict__,'alarm':alarm,'association':'manual_alarm' if kind!='maintenance_record' else 'application_module_mapping'})
    return docs

def semantic_documents(text,kb,selected):
    docs=[d for d in corpus(kb) if not selected or d['alarm'] in selected]
    mode='lexical_fallback';error=None
    if configuration_status('embedding')=='configured':
        try:
            cfg=configuration('embedding')
            threshold=float(os.getenv('APX_EMBEDDING_MIN_SCORE','0.35'))
            if not math.isfinite(threshold) or not -1<=threshold<=1: raise ProviderError('invalid_threshold')
            vs=document_vectors(kb.manifest['version_id'],cfg['url'],cfg['model'],hashlib.sha256(cfg['key'].encode()).hexdigest(),tuple(d['snippet'] for d in docs))
            query=vectors([text])[0]
            ranked=[{**d,'score':round(cosine(query,v),6)} for d,v in zip(docs,vs)]
            ranked=[d for d in ranked if d['score']>=threshold]
            return sorted(ranked,key=lambda d:-d['score'])[:6], 'embedding', None
        except (ProviderError,ValueError,TypeError,KeyError) as exc: error=safe_error(exc)
    elif configuration_status('embedding')=='partial': error=safe_error(ProviderError('not_configured'))
    scored=[]
    for d in docs:
        score=sum(k in text for k in kb.alarms[d['alarm']]['keywords'])
        if selected or score: scored.append({**d,'score':score})
    return sorted(scored,key=lambda d:-d['score'])[:6],mode,error

def retrieve(text,kb,codes,allow_remote=True):
    exact=[c for c in codes if c in kb.alarms]
    unknown=[c for c in codes if c not in kb.alarms]
    if not allow_remote or unknown:
        return exact,{'channel':'exact' if codes else 'safety_only','unknown_codes':unknown,'candidates':[],
                      'documents':[],'semantic_channel':'skipped_safety_gate'}
    docs,mode,error=semantic_documents(text,kb,exact)
    candidates=[]
    if not codes:
        scores={}
        for d in docs: scores[d['alarm']]=max(scores.get(d['alarm'],-1),d['score'])
        candidates=[{'code':c,'score':score} for c,score in sorted(scores.items(),key=lambda p:-p[1])[:3]]
    return exact,{'channel':'exact' if codes else mode,'semantic_channel':mode,'unknown_codes':unknown,
                  'candidates':candidates,'documents':docs,
                  'error':error,
                  'notice':error['hint'] if error else ('向量召回仅为候选；不据此认定报警或根因。' if mode=='embedding' else '离线关键词候选检索；不是向量语义 RAG。')}
