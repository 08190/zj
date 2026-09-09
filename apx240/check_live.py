"""Run explicitly after setting project-specific credentials: python -m apx240.check_live."""
import json
import sys
import argparse
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from .engine import diagnose
from .providers import configuration_status
from .knowledge import ROOT
from .diagnostics import safe_error
from .sessions import SessionStore

def check_sessions():
    """Four turns, two eligible remote calls; use a temporary local database."""
    with tempfile.TemporaryDirectory() as directory:
        store=SessionStore(Path(directory)/'checks.db')
        first=store.create('A203，实际128°C，没有烟雾和焦味。','live-first')
        second=store.append(first['session_id'],'设定165°C，加热电流0A','append',1,'live-second')
        danger=store.create('A520，有金属摩擦声','live-danger')
        later=store.append(danger['session_id'],'现在没有异常，想继续运行','append',1,'live-later')
        remote=[s['latest_report'] for s in [first,second]]
        blocked=[s['latest_report'] for s in [danger,later]]
        checks={
          'remote_applied':all(r['model_review']['status']=='applied' and r['retrieval']['semantic_channel']=='embedding' for r in remote),
          'readings_retained':second['latest_report']['current_observations']['measurements'].get('actual_temperature',[{}])[0].get('value')==128,
          'work_order_stable':first['latest_report']['work_order']['work_order_id']==second['latest_report']['work_order']['work_order_id'],
          'refresh_retained':SessionStore(store.path).get(second['session_id'])['revision']==2,
          'safety_retained':all(r['status']=='SAFE_BLOCKED' and r['model_review']['status']=='skipped_safety_gate' and r['retrieval']['semantic_channel']=='skipped_safety_gate' for r in blocked)}
        return {'status':'passed' if all(checks.values()) else 'failed','checks':checks}

DIAGNOSTIC_PATH=ROOT/'last-live-check.json'

def emit(result):
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    rendered=json.dumps(result,ensure_ascii=False,indent=2)
    print(rendered)
    try:
        DIAGNOSTIC_PATH.write_text(rendered,encoding='utf-8')
        print('诊断文件：'+str(DIAGNOSTIC_PATH))
    except OSError:
        print('诊断文件未能保存；可复制上面的检查结果。')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sessions',action='store_true',help='追加两轮普通会话及两轮安全会话')
    args=parser.parse_args(argv)
    states={kind:configuration_status(kind) for kind in ['llm','embedding']}
    if any(value!='configured' for value in states.values()):
        emit({'status':'not_ready','configuration':states,
              'next':'配置 APX_LLM_* 和 APX_EMBEDDING_* 后重试；不输出或记录密钥。'})
        return 2
    cases=['A203，设定165°C，实际128°C，电流0A，没有烟雾和焦味。',
           'A310，上游0.64MPa，设备端0.41MPa，有持续漏气声',
           'A520，有金属摩擦声']
    results=[]
    for index,text in enumerate(cases,1):
        print(f'正在检查样例 {index}/3……',flush=True)
        try:
            r=diagnose(text)
            result={'case_id':index,'status':r.status,'model_status':r.model_review['status'],
                    'model_error':r.model_review.get('error'),
                    'retrieval':r.retrieval.get('semantic_channel'),'retrieval_error':r.retrieval.get('error'),
                    'schema_valid':bool(r.to_dict())}
        except Exception as exc:
            results.append({'case_id':index,'status':'error','error':safe_error(exc)})
            break
        results.append(result)
        if index<3 and (result['model_status']!='applied' or result['retrieval']!='embedding'):
            break  # Preserve the first failure; do not spend on another equivalent request.
    passed=len(results)==3 and all(r.get('model_status')=='applied' and r.get('retrieval')=='embedding' for r in results[:2]) and results[2]['status']=='SAFE_BLOCKED' and results[2]['model_status']=='skipped_safety_gate' and results[2]['retrieval']=='skipped_safety_gate'
    session_result={'status':'not_requested' if not args.sessions else 'skipped_baseline_failed'}
    if args.sessions and passed:
        print('正在验证多轮读数、工单版本和安全锁定……',flush=True)
        try:session_result=check_sessions()
        except Exception as exc:session_result={'status':'failed','error':safe_error(exc)}
        passed=session_result['status']=='passed'
    emit({'status':'passed' if passed else 'failed','cases':results,'multiturn':session_result})
    return 0 if passed else 1

if __name__=='__main__': sys.exit(main())
