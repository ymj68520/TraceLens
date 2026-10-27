"""Durable job state for the existing event-cluster run route."""
import json,re,sqlite3,time,uuid,os
from contextlib import closing
from pathlib import Path
from .cluster_revision import canonical

def process_key(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError,IndexError):return None
OWNER=f'{os.getpid()}:{process_key(os.getpid()) or "unknown"}:{uuid.uuid4().hex}'
def owner_alive(owner,updated_at):
    if owner==OWNER:return True
    pid,started,_=owner.split(':',2)
    if Path('/proc').is_dir():return process_key(int(pid))==started
    return time.time()-updated_at<300
def schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS cluster_run_jobs(job_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,owner TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,updated_at INTEGER NOT NULL)')
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS cluster_one_active_run ON cluster_run_jobs(task_id) WHERE status='running'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS cluster_one_active_run_v2 ON cluster_run_jobs(task_id) WHERE status IN ('running','cancel_requested')")

def create(database,task_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',task_id):raise ValueError('任务标识无效')
    with closing(sqlite3.connect(database,timeout=10)) as conn, conn:
        schema(conn);conn.execute('BEGIN IMMEDIATE')
        for job_id,owner,updated in conn.execute("SELECT job_id,owner,updated_at FROM cluster_run_jobs WHERE task_id=? AND status IN ('running','cancel_requested')",(task_id,)).fetchall():
            if not owner_alive(owner,updated):conn.execute("UPDATE cluster_run_jobs SET status='interrupted' WHERE job_id=?",(job_id,))
        previous=conn.execute("SELECT payload FROM cluster_run_jobs WHERE task_id=? AND status IN ('running','cancel_requested')",(task_id,)).fetchone()
        if previous:return json.loads(previous[0]),False
        job={'job_id':task_id+'.'+uuid.uuid4().hex,'task_id':task_id,'status':'running',
             'detail':'正在选择聚簇窗口并启动分析…','summary':None,'error':None,'started_at':int(time.time()),'finished_at':None}
        conn.execute('INSERT INTO cluster_run_jobs VALUES(?,?,?,?,?,?)',(job['job_id'],task_id,OWNER,'running',canonical(job),int(time.time())))
        return job,True

def task_from_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}\.[0-9a-f]{32}',job_id):raise ValueError('事件分析运行标识无效')
    return job_id.rsplit('.',1)[0]

def read(database,job_id):
    with closing(sqlite3.connect(database,timeout=10)) as conn, conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='cluster_run_jobs'").fetchone():return None
        row=conn.execute('SELECT status,payload,owner,updated_at FROM cluster_run_jobs WHERE job_id=?',(job_id,)).fetchone()
    if not row:return None
    value=json.loads(row[1]);value['status']=row[0]
    if value['status'] in ('running','cancel_requested') and not owner_alive(row[2],row[3]):
        value.update(status='interrupted',detail='服务已重启；已完成分析保留，可继续运行')
    return value

def update(database,job_id,**values):
    with closing(sqlite3.connect(database,timeout=10)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT payload,status FROM cluster_run_jobs WHERE job_id=? AND owner=?',(job_id,OWNER)).fetchone()
        if not row:raise ValueError('事件分析运行所有者已改变')
        payload=json.loads(row[0]);payload['status']=row[1];payload.update(values)
        conn.execute('UPDATE cluster_run_jobs SET status=?,payload=?,updated_at=? WHERE job_id=?',
                     (payload['status'],canonical(payload),int(time.time()),job_id))
    return payload

def request_cancel(database,job_id):
    with closing(sqlite3.connect(database,timeout=10)) as conn, conn:
        conn.execute("UPDATE cluster_run_jobs SET status='cancel_requested' WHERE job_id=? AND status='running'",(job_id,))
