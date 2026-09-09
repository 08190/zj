"""Runtime report invariants independent of the model/provider."""
import math

def validate_report(data):
    if data['status'] not in ['SAFE_BLOCKED','INFO_REQUIRED','EXPERT_REQUIRED','REPORT_READY']:
        raise ValueError('Invalid report status')
    if type(data['expert_required']) is not bool: raise ValueError('Invalid expert flag')
    if data['status'] in ['SAFE_BLOCKED','EXPERT_REQUIRED'] and not data['expert_required']:
        raise ValueError('Blocked report must escalate')
    ids=set()
    for e in data['evidence']:
        if e['source_id'] in ids: raise ValueError('Duplicate evidence')
        ids.add(e['source_id'])
        if e['source_type'] not in ['alarm_manual','safety_rule','manual','history_case','maintenance_record']:
            raise ValueError('External references cannot be diagnostic evidence')
        if type(e['page']) is not int or not 1<=e['page']<=7: raise ValueError('Invalid source page')
        if e['version_id']!=data['knowledge_version'] or not e['snippet']: raise ValueError('Invalid source version')
        if e['source_type'] in ['history_case','maintenance_record','external_reference_case'] and e['historical_only'] is not True:
            raise ValueError('History cannot be current fact')
        if e.get('authority') not in ['设备说明书','安全规则','历史候选'] or not e.get('usage'):
            raise ValueError('Evidence classification missing')
    for item in data['possible_causes']+data['troubleshooting_order']:
        if not item['evidence_ids'] or not set(item['evidence_ids'])<=ids: raise ValueError('Unsupported report item')
    if any(c['confirmed'] is not False for c in data['possible_causes']): raise ValueError('Unverified root cause')
    if any(c.get('evidence_level') not in ['说明书直接支持','历史候选'] or c.get('verification_status')!='待现场验证' for c in data['possible_causes']):
        raise ValueError('Cause evidence status missing')
    if any(c.get('assessment') not in ['PRIORITY','RETAINED','CURRENTLY_UNSUPPORTED'] or not c.get('assessment_reason') for c in data['possible_causes']):
        raise ValueError('Cause assessment missing')
    next_question=data.get('next_best_question',{})
    if next_question and (next_question.get('question') not in data['missing_information'] or not next_question.get('reason')):
        raise ValueError('Invalid next best question')
    if data['status']=='SAFE_BLOCKED' and next_question:raise ValueError('Blocked report cannot ask a next action question')
    for field,readings in data['current_observations'].get('measurements',{}).items():
        for reading in readings:
            if type(reading['value']) not in [int,float] or not math.isfinite(reading['value']): raise ValueError('Invalid measurement')
            if reading['unit'] not in ['°C','A','MPa'] or not reading['quote']: raise ValueError('Invalid measurement source')
    order=data['work_order']
    if order['confirmed_root_cause'] is not None or order['restart_approved'] is not False:
        raise ValueError('Draft cannot confirm repair or restart')
    if order['report_id']!=data['report_id'] or order['risk_status']!=data['status'] or order['expert_required']!=data['expert_required']:
        raise ValueError('Work order report mismatch')
    if order['proposed_steps']!=data['troubleshooting_order']: raise ValueError('Work order steps mismatch')
    policy=data['stop_policy']
    if type(policy.get('immediate_stop')) is not bool or policy['immediate_stop']!=(data['status']=='SAFE_BLOCKED'):
        raise ValueError('Immediate stop policy mismatch')
    if type(policy.get('stop_further_operations')) is not bool or policy['stop_further_operations']!=(data['status'] in ['SAFE_BLOCKED','EXPERT_REQUIRED']):
        raise ValueError('Stop operations policy mismatch')
    if policy.get('restart_authorized') is not False or policy.get('isolation_before_intrusive_work') is not True:
        raise ValueError('Unsafe execution policy')
    if order.get('stop_policy')!=policy: raise ValueError('Work order stop policy mismatch')
    if order['knowledge_version']!=data['knowledge_version'] or set(order['evidence_ids'])!=ids:
        raise ValueError('Work order provenance mismatch')
    if order['missing_information']!=data['missing_information']: raise ValueError('Work order questions mismatch')
    if order.get('status')!='DRAFT' or not order.get('status_history') or order.get('assigned_role') not in ['现场工程师','设备专家']:
        raise ValueError('Invalid work order lifecycle')
    meta=data.get('execution_metadata',{})
    if meta.get('trace_id')!=data['report_id'] or type(meta.get('duration_ms')) not in [int,float]:
        raise ValueError('Invalid execution metadata')
    return data
