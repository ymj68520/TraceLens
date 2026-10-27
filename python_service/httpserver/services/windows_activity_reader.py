"""Read exact immutable Windows records from the existing task events store."""
import hashlib,json,re,sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from .evidence.exceptions import EvidenceNotFoundError,EvidenceStoreError

KINDS=frozenset({'event_logs','prefetch_files','browser_history','browser_downloads','browser_logins',
                'windows_services','scheduled_tasks','usb_devices','recycle_bin','amcache_entries'})
KEY=re.compile(r'^windows_artifact:v1:([A-Za-z0-9_-]{1,128}):([0-9a-f]{64}):([a-z_]+):([1-9][0-9]{0,18})$')
def parse_key(key):
    match=KEY.fullmatch(key)
    if not match or match[3] not in KINDS or int(match[4])>2**63-1:raise ValueError('Windows记录身份无效')
    return match[1],match[2],match[3],int(match[4])
def key(task,result,kind,record):return f'windows_artifact:v1:{task}:{result}:{kind}:{record}'
def connect(database):
    if not database or not Path(database).is_file():raise EvidenceStoreError('Windows活动来源库不存在')
    con=sqlite3.connect('file:'+quote(str(database),safe='/')+'?mode=ro',uri=True,timeout=10);con.row_factory=sqlite3.Row;return con
def detail(database,task,result,kind,record_id):
    # A rebuilt timeline keeps the historical databases in the same task root.
    # Result identity is exact; never substitute a row from the current version.
    row=None
    paths=[Path(database),*sorted((Path(database).parent/'windows_history').glob('*.db'))]
    for candidate in paths:
        if not candidate.is_file():continue
        with closing(connect(candidate)) as conn:
            try:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='windows_activity_records'").fetchone():continue
                row=conn.execute('SELECT r.*,s.task_id,s.source_revision,s.import_version,s.coverage_json FROM windows_activity_records r '
                    'JOIN windows_activity_sets s ON s.result_set_id=r.result_set_id WHERE r.record_id=? AND r.result_set_id=? AND r.source_table=? AND s.task_id=?',
                    (record_id,result,kind,task)).fetchone()
            except sqlite3.Error as exc:raise EvidenceStoreError('Windows活动来源结构不可用') from exc
        if row is not None:break
    if row is None:raise EvidenceNotFoundError('指定版本的Windows记录不存在')
    value=dict(row)
    if hashlib.sha256(value['record_json'].encode()).hexdigest()!=value['record_hash']:raise EvidenceStoreError('Windows来源记录摘要不一致')
    value['record']=json.loads(value['record_json']);value['coverage']=json.loads(value['coverage_json'])
    return value

def render(payload):
    row=payload.record_fields
    if row.get('parser_status') not in ('ok','partial'):return ''
    return json.dumps({'观察':row.get('observation'),'原始字段':row.get('fields'),
        '时间记录':row.get('times'),'时间依据':row.get('time_basis'),'来源':row.get('source'),
        '回收记录':row.get('is_recovered'),'限制':list(payload.warnings)},ensure_ascii=False,sort_keys=True)
