"""Content-bound cluster derivations; legacy analyses remain append-only."""
import hashlib,json,sqlite3

VERSION='cluster-derivation:v2'
FIELDS=('id','timestamp','event_type','file_path','inode','description','file_size','file_type',
        'system_context','priority','severity','event_source','event_category','normalized_type','source_id')

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def source_row(row):return {key:dict(row).get(key) for key in FIELDS}

def ensure_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS cluster_derivations(analysis_id INTEGER PRIMARY KEY,version TEXT NOT NULL,context_hash TEXT NOT NULL,members_hash TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS event_cluster_members(analysis_id INTEGER NOT NULL,event_id INTEGER NOT NULL,event_json TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(analysis_id,event_id))')
    for table in ('cluster_derivations','event_cluster_members'):
        for operation in ('UPDATE','DELETE'):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable cluster derivation'); END")

def read_members(conn,ids):
    ids=sorted(set(map(int,ids)))
    rows=[]
    for start in range(0,len(ids),500):
        part=ids[start:start+500]
        rows.extend(source_row(row) for row in conn.execute('SELECT * FROM events WHERE id IN ('+','.join('?' for _ in part)+') ORDER BY id',part))
    if len(rows)!=len(ids):raise sqlite3.DatabaseError('事件成员已改变或缺失，未持久化旧分析')
    return rows

def fingerprint(rows):
    rows=sorted(rows,key=lambda row:int(row['id']))
    if not rows:raise ValueError('事件簇没有来源成员')
    return {'member_count':len(rows),'member_min_id':rows[0]['id'],'member_max_id':rows[-1]['id'],
            'members_hash':hash_rows(rows)}

def hash_rows(rows):
    hasher=hashlib.sha256(VERSION.encode())
    for row in sorted(rows,key=lambda item:int(item['id'])):
        hasher.update(f"{row['id']}:{digest(source_row(row))}\n".encode())
    return hasher.hexdigest()

class MemberDigest:
    def __init__(self):self.values=[]
    def step(self,raw):
        row=json.loads(raw);self.values.append((row['id'],digest(source_row(row))))
    def finalize(self):
        hasher=hashlib.sha256(VERSION.encode())
        for key,value in sorted(self.values):hasher.update(f'{key}:{value}\n'.encode())
        return hasher.hexdigest()

def hash_expression(conn):
    columns={row[1] for row in conn.execute('PRAGMA table_info(events)')}
    conn.create_aggregate('activity_members_hash',1,MemberDigest)
    conn.create_function('activity_safe_text',1,lambda raw:raw.decode('utf-8','replace') if isinstance(raw,bytes) else raw)
    def column(key):
        if key not in columns:return 'NULL'
        quoted='"'+key+'"'
        return f"CASE WHEN typeof({quoted})='text' THEN activity_safe_text(CAST({quoted} AS BLOB)) ELSE {quoted} END"
    fields=','.join("'"+key+"',"+column(key) for key in FIELDS)
    return 'activity_members_hash(json_object('+fields+'))'

def context_hash(settings,case_description):
    return digest({'version':VERSION,'case':case_description,'model':getattr(settings,'llm_text_model',''),
                   'base_url':getattr(settings,'llm_text_base_url',''),'endpoint':getattr(settings,'llm_endpoint',''),
                   'temperature':getattr(settings,'llm_text_temperature',None),
                   'thinking':getattr(settings,'llm_thinking_body',{}),
                   'reserved':getattr(settings,'llm_reserved_tokens',512),
                   'context':getattr(settings,'llm_context_length',4096),
                   'output':getattr(settings,'llm_text_max_tokens',2048),
                   'chunk_size':getattr(settings,'cluster_analysis_chunk_size',200)})

def fresh(conn,latest,cluster,context):
    if not latest or latest.get('members_hash')!=cluster['members_hash']:return False
    row=conn.execute('SELECT version,context_hash,members_hash FROM cluster_derivations WHERE analysis_id=?',(latest['id'],)).fetchone()
    return row is not None and tuple(row)==(VERSION,context,cluster['members_hash'])

def save_members(conn,analysis_id,rows,context):
    value=fingerprint(rows)
    conn.execute('INSERT INTO cluster_derivations VALUES(?,?,?,?)',(analysis_id,VERSION,context,value['members_hash']))
    conn.executemany('INSERT INTO event_cluster_members VALUES(?,?,?,?)',
                     [(analysis_id,row['id'],canonical(row),digest(row)) for row in rows])

def data_revision(database):
    from .cluster_analyzer import _connect_events
    hasher=hashlib.sha256(VERSION.encode())
    with _connect_events(database) as conn:
        for row in conn.execute('SELECT * FROM events ORDER BY id'):
            hasher.update(canonical(source_row(row)).encode());hasher.update(b'\n')
    return hasher.hexdigest()

def filter_current_analyses(conn,records):
    """Only current content-bound records may enter a new ingestion batch.

    Pre-upgrade databases keep their historical accessor. Once derivations exist,
    unverified legacy caches are retained for browsing, not newly ingested.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='cluster_derivations'").fetchone():return [dict(r) for r in records]
    result=[]
    for raw in records:
        row=dict(raw)
        full=conn.execute('SELECT * FROM event_cluster_analyses WHERE id=?',(row['id'],)).fetchone()
        if not full:continue
        full=dict(full)
        coordinate=tuple(full[name] for name in ('task_id','bucket_epoch_offset','bucket_seconds','bucket_index','event_type','parent_directory'))
        newest=conn.execute('SELECT MAX(id) FROM event_cluster_analyses WHERE task_id=? AND bucket_epoch_offset=? AND bucket_seconds=? AND bucket_index=? AND event_type=? AND parent_directory=?',coordinate).fetchone()[0]
        if newest!=row['id']:continue
        meta=conn.execute('SELECT members_hash,version FROM cluster_derivations WHERE analysis_id=?',(row['id'],)).fetchone()
        if not meta:continue
        if meta[1]!=VERSION or full['members_hash']!=meta[0]:continue
        ids=[item[0] for item in conn.execute('SELECT event_id FROM event_cluster_members WHERE analysis_id=? ORDER BY event_id',(row['id'],))]
        if not ids:continue
        try:observed=fingerprint(read_members(conn,ids))['members_hash']
        except sqlite3.DatabaseError:continue
        if observed==meta[0]:result.append(row)
    # Keep the newest current analysis for one coordinate.
    latest={}
    for row in result:
        key=tuple(row.get(name) for name in ('task_id','bucket_epoch_offset','bucket_seconds','bucket_index','event_type','parent_directory'))
        if key not in latest or row['id']>latest[key]['id']:latest[key]=row
    return sorted(latest.values(),key=lambda row:row['id'])
