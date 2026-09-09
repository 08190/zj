"""Local persistent multi-turn diagnostics with revisions, retries and safety latches."""
import copy
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .engine import diagnose
from .knowledge import Knowledge, ROOT
from .observations import normalize,parse_observations,single_value

class SessionConflict(Exception):
    pass

class SessionNotFound(Exception):
    pass

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def validate_text(text):
    if not isinstance(text,str) or not 1<=len(text.strip())<=8000:
        raise ValueError('请输入 1–8000 字的故障描述')

def merge_turn(effective,message,mode):
    validate_text(message)
    if mode not in ['append','correct_measurements']:
        raise ValueError('未知补充方式')
    message=normalize(message)
    replaced=[]
    if mode=='correct_measurements':
        new=parse_observations(message)
        old=parse_observations(effective)
        if not new['measurements'] or new['excluded_historical_clauses']:
            raise ValueError('更正读数需写出字段、数值和单位，例如“实际温度140°C”')
        for field in new['measurements']:
            if single_value(new,field) is None:
                raise ValueError('一次更正只能为每个字段提供一个明确读数')
            prior=old['measurements'].get(field,[])
            for reading in prior:
                effective=effective.replace(reading['quote'],'（读数已更正）')
            replaced.append({'field':field,'previous':prior,'replacement':new['measurements'][field]})
    combined=(effective+'\n'+message).strip()
    if len(combined)>8000:
        raise ValueError('本会话有效描述达到 8000 字上限；请导出会话后交由人工整理')
    return combined,replaced

def summarize_changes(previous,report):
    if not previous:return []
    changes=[]
    old_measurements=previous.get('current_observations',{}).get('measurements',{})
    new_measurements=report.current_observations.get('measurements',{})
    labels={'set_temperature':'设定温度','actual_temperature':'实际温度','heater_current':'加热电流',
            'upstream_pressure':'上游压力','device_pressure':'设备端压力'}
    for field,items in new_measurements.items():
        before={(x['value'],x['unit']) for x in old_measurements.get(field,[])}
        after={(x['value'],x['unit']) for x in items}
        if after!=before:
            values='、'.join(f"{v:g}{u}" for v,u in sorted(after))
            changes.append('新增或更新'+labels.get(field,field)+'：'+values)
    if previous.get('status')!=report.status:
        changes.append('诊断状态由 '+previous.get('status','未知')+' 变为 '+report.status)
    old_causes={c['cause_id']:c for c in previous.get('possible_causes',[])}
    new_causes={c['cause_id']:c for c in report.possible_causes}
    label=lambda cid,items:items[cid].get('description',cid).removeprefix('可能：')
    tier_label={'PRIORITY':'优先核查','RETAINED':'保留候选','CURRENTLY_UNSUPPORTED':'当前证据不支持'}
    for cid in sorted(old_causes.keys()&new_causes.keys()):
        before=old_causes[cid].get('assessment')
        after=new_causes[cid].get('assessment')
        if before!=after:
            changes.append(f"{label(cid,new_causes)}：{tier_label.get(before,before)} → {tier_label.get(after,after)}")
    resolved=[q for q in previous.get('missing_information',[]) if q not in report.missing_information]
    if resolved:changes.append('已补齐信息：'+'；'.join(resolved[:3]))
    return changes or ['已记录补充信息；当前诊断结论未发生实质变化']

class SessionStore:
    def __init__(self,path=None,diagnoser=diagnose):
        self.path=Path(path) if path else ROOT/'runtime/sessions.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.diagnoser=diagnoser
        # Local MVP serializes updates so retries cannot duplicate model calls.
        self.lock=threading.RLock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self,write=False):
        db=sqlite3.connect(str(self.path),timeout=90)
        try:
            with db:
                # Reserve the database before checking idempotency/revisions. An
                # in-memory lock alone does not protect a second local process.
                if write: db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def _fingerprint(self,payload):
        return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    def _retry(self,db,request_id,fingerprint):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',request_id):
            raise ValueError('缺少有效请求编号')
        row=db.execute('SELECT fingerprint,response FROM requests WHERE id=?',(request_id,)).fetchone()
        if row:
            if row[0]!=fingerprint: raise SessionConflict('请求编号已用于不同内容，请刷新会话后再提交')
            return json.loads(row[1])

    def get(self,session_id):
        with self.lock,self.connect() as db:
            row=db.execute('SELECT state FROM sessions WHERE id=?',(session_id,)).fetchone()
            if not row: raise SessionNotFound('会话不存在；请确认会话编号')
            return json.loads(row[0])

    def create(self,message,request_id):
        validate_text(message)
        fingerprint=self._fingerprint({'operation':'create','message':message})
        with self.lock,self.connect(write=True) as db:
            cached=self._retry(db,request_id,fingerprint)
            if cached: return cached
            session_id=str(uuid.uuid4())
            state={'session_id':session_id,'revision':0,'created_at':timestamp(),'updated_at':timestamp(),
                   'turns':[],'reports':[],'effective_description':'','safety_latch':None,'latch_events':[]}
            state=self._advance(state,message,'append')
            rendered=json.dumps(state,ensure_ascii=False)
            db.execute('INSERT INTO sessions VALUES(?,?)',(session_id,rendered))
            db.execute('INSERT INTO requests VALUES(?,?,?)',(request_id,fingerprint,rendered))
            return state

    def append(self,session_id,message,mode,expected_revision,request_id):
        validate_text(message)
        if type(expected_revision) is not int or expected_revision<1:
            raise ValueError('需提供当前会话版本')
        fingerprint=self._fingerprint({'operation':'append','session_id':session_id,'message':message,'mode':mode,'revision':expected_revision})
        with self.lock,self.connect(write=True) as db:
            cached=self._retry(db,request_id,fingerprint)
            if cached: return cached
            row=db.execute('SELECT state FROM sessions WHERE id=?',(session_id,)).fetchone()
            if not row: raise SessionNotFound('会话不存在')
            state=json.loads(row[0])
            if state['revision']!=expected_revision:
                raise SessionConflict('会话已更新，请先载入最新内容；本次未调用模型')
            if len(state['turns'])>=30 or sum(len(t['message']) for t in state['turns'])+len(message)>32000:
                raise ValueError('已达到单会话容量上限；请导出并交由人工整理')
            kb=Knowledge()
            if not state.get('knowledge_snapshot_digest'):
                raise SessionConflict('旧会话缺少完整知识快照标识，需人工核对后新建会话；历史和安全要求保留')
            if state['knowledge_snapshot_digest']!=kb.snapshot_digest:
                raise SessionConflict('知识快照已变化，需人工核对后新建会话；本会话历史和安全要求保留')
            state=self._advance(state,message,mode,kb)
            rendered=json.dumps(state,ensure_ascii=False)
            db.execute('UPDATE sessions SET state=? WHERE id=?',(rendered,session_id))
            db.execute('INSERT INTO requests VALUES(?,?,?)',(request_id,fingerprint,rendered))
            return state

    def _advance(self,state,message,mode,kb=None):
        kb=kb or Knowledge()
        state.setdefault('knowledge_snapshot_digest',kb.snapshot_digest)
        combined,replaced=merge_turn(state['effective_description'],message,mode)
        previous=state.get('latest_report')
        report=self.diagnoser(combined,kb=kb,safety_floor=state['safety_latch'])
        report.change_summary=summarize_changes(previous,report)
        revision=state['revision']+1
        if report.status=='SAFE_BLOCKED' and state['safety_latch']!='SAFE_BLOCKED':
            state['safety_latch']='SAFE_BLOCKED'
            state['latch_events'].append({'revision':revision,'status':report.status,'reason':report.escalation_reason})
        elif report.status=='EXPERT_REQUIRED' and not state['safety_latch']:
            state['safety_latch']='EXPERT_REQUIRED'
            state['latch_events'].append({'revision':revision,'status':report.status,'reason':report.escalation_reason})
        report.session={'session_id':state['session_id'],'revision':revision,'safety_latch':state['safety_latch'],
                        'latch_events':copy.deepcopy(state['latch_events'])}
        report.work_order.update({'work_order_id':'DRAFT-'+state['session_id'],'session_id':state['session_id'],'revision':revision})
        data=report.to_dict()
        state.update(revision=revision,updated_at=timestamp(),effective_description=combined,latest_report=data)
        state['turns'].append({'revision':revision,'message':message,'mode':mode,'replaced_measurements':replaced,'at':timestamp()})
        state['reports'].append(copy.deepcopy(data))
        return state
