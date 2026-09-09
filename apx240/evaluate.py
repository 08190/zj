"""Explicit manual-derived behavior checks; offline by default, not diagnostic accuracy."""
import argparse
import json
import os
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from .engine import diagnose
from .knowledge import Knowledge,ROOT,compact
from .validation import validate_report
from .diagnostics import safe_error
from .providers import configuration_status

@contextmanager
def offline_environment():
    keys=[f'APX_{kind}_{part}' for kind in ['LLM','EMBEDDING'] for part in ['URL','MODEL','KEY']]
    saved={key:os.environ.get(key) for key in keys}
    try:
        for key in keys:os.environ[key]=''
        yield
    finally:
        for key,value in saved.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value

def assess(case,report,kb):
    failures=[]
    def check(condition,label):
        if not condition:failures.append(label)
    try:validate_report(report)
    except (ValueError,KeyError,TypeError):failures.append('报告结构或工单不变量')
    expected=case['expected'];policy=report['stop_policy']
    check(report['status'] in expected['allowed_statuses'],'诊断状态')
    for flag in ['immediate_stop','stop_further_operations']:
        check(policy[flag] is expected[flag],flag)
    check(report['expert_required'] is expected['expert_required'],'专家升级')
    evidence={e['source_id']:e for e in report['evidence']}
    check(set(expected['required_evidence'])<=set(evidence),'必要证据缺失')
    for e in evidence.values():
        check(compact(e['snippet']) in compact(kb.pages[e['page']-1]),'引用片段不在原文')
        if e['source_type']=='alarm_manual':check(e['source_id'] in kb.alarms and e['page']==4,'报警来源错配')
        if e['historical_only']:check(e['source_type'] in ['history_case','maintenance_record'],'历史来源错配')
    questions='；'.join(report['missing_information'])
    for group in expected['question_groups']:
        check(any(word in questions for word in group['any_of']),'追问缺失：'+group['topic'])
    causes=report['possible_causes'];allowed=set(expected['allowed_cause_ids'])
    check(all(c['cause_id'] in allowed for c in causes),'超出允许原因范围')
    if allowed:check(bool(causes),'原因候选为空')
    for c in causes:
        alarm,number=c['cause_id'].split('-C')
        check(c['description']=='可能：'+kb.alarms[alarm]['causes'][int(number)-1],'原因内容与手册错配')
        check(alarm in c['evidence_ids'],'原因缺少对应手册支持')
        check(c['confirmed'] is False,'历史候选被确认为根因')
    if policy['stop_further_operations']:
        check(report['model_review']['status']=='skipped_safety_gate' or report['model_review']['status']=='applied','风险流程状态')
    return list(dict.fromkeys(failures))

def run_suite(cases,live=False):
    kb=Knowledge();results=[]
    for case in cases:
        try:
            report=diagnose(case['description'],kb).to_dict()
            failures=assess(case,report,kb)
            remote={'model':report['model_review']['status'],'retrieval':report['retrieval'].get('semantic_channel')}
            if live and not report['stop_policy']['stop_further_operations'] and report['possible_causes']:
                if remote!={'model':'applied','retrieval':'embedding'}:failures.append('真实模型或向量未应用')
            if case['expected']['immediate_stop'] and remote!={'model':'skipped_safety_gate','retrieval':'skipped_safety_gate'}:
                failures.append('明确停机风险未跳过远程调用')
            results.append({'id':case['id'],'passed':not failures,'failures':failures,'actual_status':report['status'],**remote})
        except Exception as exc:
            results.append({'id':case['id'],'passed':False,'failures':['执行或评测异常'],'error':safe_error(exc)})
    return {'mode':'live' if live else 'offline','status':'passed' if all(r['passed'] for r in results) else 'failed',
            'passed':sum(r['passed'] for r in results),'total':len(results),'cases':results,
            'knowledge_version':kb.manifest['version_id'],'snapshot_digest':kb.snapshot_digest,
            'checked_at':datetime.now(timezone.utc).isoformat(),
            'interpretation':'手册派生的工程行为验收；非真实故障准确率，未由维修专家签署。追问仅检查主题关键词，不证明完整语义。'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='明确发起外部模型调用，使用本机项目配置')
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/acceptance-result.json')
    args=parser.parse_args(argv)
    cases=json.loads((ROOT/'tests/acceptance_cases_v3.json').read_text(encoding='utf-8'))
    if args.live:
        if any(configuration_status(k)!='configured' for k in ['llm','embedding']):
            print('未配置完整项目接口；未发送请求。');return 2
        result=run_suite(cases,live=True)
    else:
        with offline_environment():result=run_suite(cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{result['mode']}: {result['passed']}/{result['total']}，{result['status']}")
    for case in result['cases']:
        if not case['passed']:print(case['id']+'：'+'；'.join(case['failures']))
    print('结果文件：'+str(args.output))
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
