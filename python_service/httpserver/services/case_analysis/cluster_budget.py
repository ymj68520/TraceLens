"""Persistent request ceilings for one content/version-bound cluster plan."""
import sqlite3
from contextlib import closing
from contextvars import ContextVar
from contextlib import contextmanager
from ..model_budget import ModelBudgetError
_scope=ContextVar('cluster_run_budget',default=None)

def create(database,plan,calls,tokens):
    with closing(sqlite3.connect(database,timeout=10)) as db, db:
        db.executescript('CREATE TABLE IF NOT EXISTS cluster_model_budget(plan_id TEXT PRIMARY KEY,max_calls INTEGER,max_tokens INTEGER,used_calls INTEGER NOT NULL DEFAULT 0,reserved_tokens INTEGER NOT NULL DEFAULT 0);'
            'CREATE TABLE IF NOT EXISTS cluster_model_ledger(id INTEGER PRIMARY KEY,plan_id TEXT,source_key TEXT,input_bound INTEGER,output_limit INTEGER,created_at INTEGER);')
        db.execute('INSERT OR IGNORE INTO cluster_model_budget(plan_id,max_calls,max_tokens) VALUES(?,?,?)',(plan,calls,tokens))

@contextmanager
def bind(database,plan,source):
    token=_scope.set((database,plan,source))
    try:yield
    finally:_scope.reset(token)

def reserve(input_bound,output_limit):
    context=_scope.get()
    if not context:return
    database,plan,source=context;amount=int(input_bound)+int(output_limit)
    with closing(sqlite3.connect(database,timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('UPDATE cluster_model_budget SET used_calls=used_calls+1,reserved_tokens=reserved_tokens+? WHERE plan_id=? AND used_calls<max_calls AND reserved_tokens+?<=max_tokens',(amount,plan,amount))
        if row.rowcount!=1:raise ModelBudgetError('本轮事件分析调用或令牌预算已用尽，未派发请求')
        db.execute("INSERT INTO cluster_model_ledger(plan_id,source_key,input_bound,output_limit,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(plan,source,input_bound,output_limit))
