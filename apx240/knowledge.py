from pathlib import Path
import hashlib, json, re
from .models import Evidence

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / 'knowledge_mounts/apx240-v1'

def compact(s):
    return re.sub(r'\s+', '', s)

class Knowledge:
    def __init__(self, path=KB):
        self.path = Path(path)
        self.manifest = json.loads((self.path/'manifest.json').read_text(encoding='utf-8'))
        required={'alarms.json','history_cases.json','maintenance_records.json','manual.md','manual.pdf','pages.json','safety_rules.json'}
        if set(self.manifest.get('files',{}))!=required:
            raise ValueError('知识清单文件不完整，停止诊断')
        for name, expected in self.manifest['files'].items():
            p = self.path/name
            if p.parent != self.path or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
                raise ValueError('知识快照校验失败，停止诊断：'+name)
        if self.manifest.get('version_id')!='sha256:'+self.manifest['files']['manual.pdf'][:16]:
            raise ValueError('知识版本与原文摘要不一致')
        self.snapshot_digest=hashlib.sha256(json.dumps(self.manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        def read(name):
            return json.loads((self.path/name).read_text(encoding='utf-8'))
        self.alarms = read('alarms.json')
        self.history = read('history_cases.json')
        self.repairs = read('maintenance_records.json')
        self.rules = read('safety_rules.json')
        self.pages = read('pages.json')

    def evidence(self, source_id, source_type, page, section, snippet, historical=False):
        if source_id in self.rules:
            expected=('safety_rule',3,False);source=self.rules[source_id]
        elif source_id=='PARAMETERS':
            expected=('manual',2,False);source=self.pages[1]
        else:
            rows=None
            for group,kind,number in [(list(self.alarms.values()),'alarm_manual',4),(self.history,'history_case',5),(self.repairs,'maintenance_record',6)]:
                if any(row['id']==source_id for row in group):
                    rows=group;expected=(kind,number,number!=4);break
            if rows is None:raise ValueError('未知引用编号：'+source_id)
            content=self.pages[expected[1]-1];start=content.index(source_id)
            ends=[content.find(row['id'],start+len(source_id)) for row in rows if row['id']!=source_id]
            end=min([x for x in ends if x>=0] or [len(content)])
            if expected[0]=='maintenance_record':
                dates=list(re.finditer(r'\d{4}-\d{2}-\d{2}',content))
                start=max([d.start() for d in dates if d.start()<start] or [start])
                end=min([d.start() for d in dates if d.start()>start] or [len(content)])
            source=content[start:end]
        if (source_type,page,historical)!=expected or not compact(snippet) or compact(snippet) not in compact(source):
            raise ValueError('引用未通过原文校验：'+source_id)
        return Evidence(source_id,source_type,self.manifest['source_filename'],page,section,
                        f'p{page}-{source_id}',self.manifest['version_id'],snippet,historical)
