// QQ 取证（NTQQ）的导入弹窗与各功能面板。
// 自 QQForensics.jsx 平移（2026-09-15 三页合并进 IMForensics），页面骨架逻辑在 IMForensics.jsx。
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3, ChevronLeft, ChevronRight, Database, FileText,
  KeyRound, MessageSquare, Plus, Search, Trash2,
  User, Users, Network, Lock,
} from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid
} from 'recharts';
import Card from '../../components/common/Card';
import Badge from '../../components/common/Badge';
import Spinner from '../../components/common/Spinner';
import Modal from '../../components/common/Modal';
import { useToast } from '../../components/common/useToast';
import {
  createQQImport,
  getQQSessions, getQQMessages,
  getQQContacts, getQQChatrooms,
} from '../../services/qqForensicsService';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const fmtTime = (ts) => {
  if (!ts) return '-';
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return String(ts);
  }
};

const KIND_BADGE = {
  group: { label: '群聊', variant: 'purple' },
  private: { label: '私聊', variant: 'blue' },
};

const MSG_TYPE_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 2, label: '文本' },
  { value: 9, label: '卡片/红包' },
  { value: 10, label: '灰条通知' },
];

const dateToMs = (dateStr, endOfDay = false) => {
  if (!dateStr) return null;
  const t = new Date(`${dateStr}T${endOfDay ? '23:59:59' : '00:00:00'}`).getTime();
  return Number.isNaN(t) ? null : t;
};

// ---------------------------------------------------------------------------
// import panel
// ---------------------------------------------------------------------------

const emptyForm = {
  name: '',
  db_path: '',
  password: '',
  nt_uid: '',
  uin: '',
  backup_source: '',
};

export const QQImportModal = ({ isOpen, onClose, onCreated }) => {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const { show } = useToast();

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async () => {
    if (!form.db_path.trim()) {
      show('请填写数据库文件路径 (nt_msg.db)', 'error');
      return;
    }
    setBusy(true);
    try {
      const res = await createQQImport({
        name: form.name.trim(),
        db_path: form.db_path.trim(),
        password: form.password.trim(),
        backup_source: form.backup_source.trim(),
        key_material: {
          nt_uid: form.nt_uid.trim(),
          uin: form.uin.trim(),
        },
      });
      const item = res.import || {};
      if (item.status === 'ready') {
        show(`导入成功：${item.stats?.total_messages ?? 0} 条消息`, 'success');
        onCreated(item.import_id);
        setForm(emptyForm);
      } else {
        show(`导入失败：${item.error || '未知错误'}`, 'error');
      }
    } catch (e) {
      show(`导入失败：${e.data?.detail || e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const Field = (props) => {
    const { label, hint, k, ph, mono = true } = props;
    return (
      <label className="block">
        <span className="text-xs font-medium text-slate-500">{label}</span>
        <input
          value={form[k]}
          onChange={set(k)}
          placeholder={ph}
          className={`mt-1 w-full rounded-lg border-0 bg-white/70 px-3 py-2 text-sm ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500 ${mono ? 'font-mono text-xs' : ''}`}
        />
        {hint && <span className="mt-0.5 block text-[11px] text-slate-400">{hint}</span>}
      </label>
    );
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="导入 QQ 账号数据库 (NTQQ)" size="lg">
      <div className="space-y-4">
        <div className="rounded-xl bg-primary-50 p-3 text-xs leading-relaxed text-primary-800 ring-1 ring-primary-100">
          支持直接导入 <b>SQLCipher 加密的 nt_msg.db</b>（QQ 9.x NT 架构）。
          提供 <b>nt_uid</b>（形如 u_xxx）即可自动推导密钥：
          key = md5(md5(nt_uid) + 库头 rand)；也可直接粘贴已知的 32 位密钥。
          同目录的 profile_info.db / group_info.db 会自动一并解密用于还原昵称与群名。
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="导入名称" k="name" ph="例：MIUI备份 QQ 2874289874" mono={false} />
          <Field label="备份来源说明" k="backup_source" ph="例：MIUI 整机备份 QQ.bak" mono={false} />
        </div>
        <Field label="数据库路径 (nt_msg.db) *" k="db_path" ph="/path/to/nt_db/nt_qq_xxx/nt_msg.db" />
        <div className="border-t border-slate-100 pt-3">
          <p className="mb-2 flex items-center gap-1 text-sm font-medium text-slate-700">
            <KeyRound size={14} /> 密钥材料（用于自动推导密钥与取证记录）
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="nt_uid（f/uid/&lt;QQ号&gt;###u_xxx 中的 u_xxx）" k="nt_uid" ph="u_UJEcIMaQtYqv4WxT5Bl30Q" />
            <Field label="QQ 号 (uin)" k="uin" ph="2874289874" />
          </div>
        </div>
        <Field label="数据库密钥（可选；留空时由 nt_uid + 库头 rand 自动推导）" k="password" ph="32 位 hex，如 55a19994…" />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">取消</button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {busy ? <Spinner size="sm" /> : <Plus size={16} />} 开始导入
          </button>
        </div>
      </div>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// overview tab
// ---------------------------------------------------------------------------

const StatCard = ({ icon: Icon, label, value, hint }) => (
  <div className="rounded-xl bg-white/70 p-4 ring-1 ring-slate-200/60">
    <div className="flex items-center gap-2 text-slate-500">
      <Icon size={15} />
      <span className="text-xs font-medium">{label}</span>
    </div>
    <p className="mt-1 text-xl font-semibold text-slate-900">{value}</p>
    {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
  </div>
);

export const QQOverviewTab = ({ overview }) => {
  if (!overview) return null;
  const { owner = {}, key_material: km = {}, decryption = {}, stats = {}, type_stats = [], day_stats = [], top_sessions = [] } = overview;

  const kv = (label, value, mono = true) => (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="shrink-0 text-xs text-slate-400">{label}</span>
      <span className={`truncate text-sm text-slate-800 ${mono ? 'font-mono text-xs' : ''}`} title={String(value ?? '')}>{value || '-'}</span>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <StatCard icon={MessageSquare} label="消息总数" value={stats.total_messages ?? 0} hint={`私聊 ${stats.c2c_messages ?? 0} / 群聊 ${stats.group_messages ?? 0}`} />
        <StatCard icon={User} label="好友" value={stats.contacts ?? 0} />
        <StatCard icon={Users} label="群聊" value={stats.groups ?? 0} />
        <StatCard icon={BarChart3} label="活跃天数" value={day_stats.length} />
        <StatCard icon={Lock} label="完整性" value={decryption.integrity === 'ok' ? 'OK' : (decryption.integrity || '-')} />
        <StatCard icon={Network} label="密钥推导" value={decryption.formula ? '离线' : (decryption.scheme || '-')} hint={decryption.scheme || ''} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="👤 账号归属" animate={false}>
          {kv('QQ 号', owner.username)}
          {kv('昵称', owner.nickname, false)}
          {kv('nt_uid', owner.nt_uid)}
        </Card>
        <Card title="🔑 密钥材料来源" animate={false}>
          {kv('nt_uid', km.nt_uid)}
          {kv('QQ 号 (uin)', km.uin)}
          {kv('库头 rand', km.rand)}
          {kv('数据库密钥', km.key)}
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
            目录哈希 = md5(md5(nt_uid) + &quot;nt_kernel&quot;)，
            密钥 = md5(md5(nt_uid) + rand)，全部离线推导。
          </p>
        </Card>
        <Card title="🔓 解密参数" animate={false}>
          {kv('方案', decryption.scheme)}
          {kv('页大小', decryption.params?.cipher_page_size)}
          {kv('KDF', decryption.params ? `${decryption.params.cipher_kdf_algorithm} × ${decryption.params.kdf_iter}` : '')}
          {kv('HMAC', decryption.params?.cipher_hmac_algorithm)}
          {kv('WAL', decryption.wal?.present ? '已回放' : '无')}
          {kv('时间范围', stats.first_ts_ms ? `${fmtTime(stats.first_ts_ms)} ~ ${fmtTime(stats.last_ts_ms)}` : '')}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="消息类型分布" className="lg:col-span-1" animate={false}>
          <ul className="space-y-1.5">
            {type_stats.map((t) => (
              <li key={`${t.base_type}`} className="flex items-center justify-between text-sm">
                <span className="text-slate-600">{t.label} <span className="text-xs text-slate-400">(40011={t.base_type})</span></span>
                <Badge variant="blue">{t.count}</Badge>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="每日消息量" className="lg:col-span-2" animate={false}>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={day_stats} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                <Tooltip formatter={(v) => [`${v} 条`, '消息']} />
                <Bar dataKey="count" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="最活跃会话" animate={false}>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400">
                <th className="py-1.5 pr-4">会话</th>
                <th className="py-1.5 pr-4">消息数</th>
                <th className="py-1.5 pr-4">首条时间</th>
                <th className="py-1.5">最后活跃</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {top_sessions.map((s) => (
                <tr key={s.talker}>
                  <td className="py-1.5 pr-4 text-slate-800">{s.display_name}</td>
                  <td className="py-1.5 pr-4">{s.msg_count}</td>
                  <td className="py-1.5 pr-4 text-slate-500">{fmtTime(s.first_ts)}</td>
                  <td className="py-1.5 text-slate-500">{fmtTime(s.last_ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};

// ---------------------------------------------------------------------------
// sessions tab
// ---------------------------------------------------------------------------

export const QQSessionsTab = ({ importId, onOpenMessages }) => {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getQQSessions(importId)
      .then((res) => alive && setSessions(res.sessions || []))
      .catch(() => alive && setSessions([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId]);

  if (loading) return <div className="flex justify-center py-12"><Spinner /></div>;

  return (
    <Card animate={false}>
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400">
            <th className="py-2 pr-4">类型</th>
            <th className="py-2 pr-4">会话</th>
            <th className="py-2 pr-4">QQ 号 / 群号</th>
            <th className="py-2 pr-4">消息数</th>
            <th className="py-2 pr-4">最后活跃</th>
            <th className="py-2">最后消息预览</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sessions.map((s) => {
            const Icon = s.kind === 'group' ? Users : User;
            const badge = KIND_BADGE[s.kind] || KIND_BADGE.private;
            return (
              <tr key={`${s.kind}-${s.talker}`} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpenMessages(s.talker)}>
                <td className="py-2 pr-4"><Badge variant={badge.variant} size="sm"><span className="mr-1 inline-flex align-[-2px]"><Icon size={11} /></span>{badge.label}</Badge></td>
                <td className="py-2 pr-4 font-medium text-slate-800">{s.display_name}</td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-400">{s.talker}</td>
                <td className="py-2 pr-4">{s.msg_count}</td>
                <td className="py-2 pr-4 text-slate-500">{fmtTime(s.last_ts)}</td>
                <td className="max-w-[280px] truncate py-2 text-slate-500">{s.last_preview}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// messages tab
// ---------------------------------------------------------------------------

const PAGE_SIZE = 100;

export const QQMessagesTab = ({ importId, initialTalker }) => {
  const [talker, setTalker] = useState(initialTalker || '');
  const [msgType, setMsgType] = useState('');
  const [keyword, setKeyword] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ messages: [], total: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => { setTalker(initialTalker || ''); setPage(1); }, [initialTalker]);

  const load = useCallback(() => {
    let alive = true;
    setLoading(true);
    const params = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
    if (talker) params.talker = talker;
    if (msgType !== '') params.msg_type = Number(msgType);
    if (keyword.trim()) params.keyword = keyword.trim();
    const s = dateToMs(startDate); if (s) params.start_ts = s;
    const e = dateToMs(endDate, true); if (e) params.end_ts = e;
    getQQMessages(importId, params)
      .then((res) => alive && setData({ messages: res.messages || [], total: res.total || 0 }))
      .catch(() => alive && setData({ messages: [], total: 0 }))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId, talker, msgType, keyword, startDate, endDate, page]);

  useEffect(() => load(), [load]);

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const inputCls = 'rounded-lg border-0 bg-white/70 px-3 py-2 text-sm ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500';

  return (
    <Card animate={false}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input value={talker} onChange={(e) => { setTalker(e.target.value); setPage(1); }} placeholder="按 QQ 号 / 群号过滤" className={`${inputCls} w-52 font-mono text-xs`} />
        <select value={msgType} onChange={(e) => { setMsgType(e.target.value); setPage(1); }} className={inputCls}>
          {MSG_TYPE_OPTIONS.map((o) => <option key={String(o.value)} value={o.value}>{o.label}</option>)}
        </select>
        <div className="flex items-center gap-1">
          <input type="date" value={startDate} onChange={(e) => { setStartDate(e.target.value); setPage(1); }} className={inputCls} />
          <span className="text-slate-400">~</span>
          <input type="date" value={endDate} onChange={(e) => { setEndDate(e.target.value); setPage(1); }} className={inputCls} />
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
          <input value={keyword} onChange={(e) => { setKeyword(e.target.value); setPage(1); }} placeholder="关键词搜索内容" className={`${inputCls} w-48 pl-8`} />
        </div>
        <span className="ml-auto text-xs text-slate-400">共 {data.total} 条</span>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : data.messages.length === 0 ? (
        <p className="py-12 text-center text-slate-400">没有符合条件的消息</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400">
                  <th className="py-2 pr-3">时间</th>
                  <th className="py-2 pr-3">方向</th>
                  <th className="py-2 pr-3">发送者</th>
                  <th className="py-2 pr-3">会话</th>
                  <th className="py-2 pr-3">类型</th>
                  <th className="py-2">内容</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.messages.map((m) => (
                  <tr key={m.id} className="align-top hover:bg-slate-50">
                    <td className="whitespace-nowrap py-2 pr-3 text-xs text-slate-500">{m.time_display}</td>
                    <td className="py-2 pr-3">
                      <Badge variant={m.direction === 'send' ? 'green' : 'blue'} size="sm">{m.direction === 'send' ? '发出' : '接收'}</Badge>
                    </td>
                    <td className="max-w-[130px] truncate py-2 pr-3 text-slate-700" title={m.sender}>{m.sender_name}</td>
                    <td className="max-w-[150px] truncate py-2 pr-3 text-slate-500" title={m.talker}>{m.session_name}</td>
                    <td className="py-2 pr-3"><Badge variant="gray" size="sm">{m.type_label}</Badge></td>
                    <td className="max-w-[480px] py-2">
                      <p className="whitespace-pre-wrap break-words text-slate-800">{m.content_display}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-sm">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-40">
              <ChevronLeft size={14} /> 上一页
            </button>
            <span className="text-xs text-slate-400">第 {page} / {totalPages} 页</span>
            <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-40">
              下一页 <ChevronRight size={14} />
            </button>
          </div>
        </>
      )}
    </Card>
  );
};

// ---------------------------------------------------------------------------
// contacts tab
// ---------------------------------------------------------------------------

export const QQContactsTab = ({ importId }) => {
  const [contacts, setContacts] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    getQQContacts(importId)
      .then((res) => alive && setContacts(res.contacts || []))
      .catch(() => alive && setContacts([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId]);

  const filtered = useMemo(() => contacts.filter((c) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [c.nickname, c.username].some((v) => (v || '').toLowerCase().includes(q));
  }), [contacts, query]);

  if (loading) return <div className="flex justify-center py-12"><Spinner /></div>;

  return (
    <Card animate={false}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索昵称 / QQ 号" className="w-64 rounded-lg border-0 bg-white/70 py-2 pl-8 pr-3 text-sm ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500" />
        </div>
        <span className="ml-auto text-xs text-slate-400">显示 {filtered.length} / {contacts.length} 条</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              <th className="py-2 pr-4">昵称</th>
              <th className="py-2 pr-4">QQ 号</th>
              <th className="py-2 pr-4">类型</th>
              <th className="py-2">相关消息</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((c) => (
              <tr key={c.username} className="hover:bg-slate-50">
                <td className="py-2 pr-4 font-medium text-slate-800">{c.nickname || c.username}</td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-500">{c.username}</td>
                <td className="py-2 pr-4"><Badge variant="blue" size="sm">好友</Badge></td>
                <td className="py-2">{c.msg_count || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// chatrooms tab
// ---------------------------------------------------------------------------

export const QQChatroomsTab = ({ importId }) => {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    getQQChatrooms(importId)
      .then((res) => alive && setRooms(res.chatrooms || []))
      .catch(() => alive && setRooms([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId]);

  if (loading) return <div className="flex justify-center py-12"><Spinner /></div>;
  if (rooms.length === 0) return <Card animate={false}><p className="py-8 text-center text-slate-400">没有群聊记录</p></Card>;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {rooms.map((r) => (
        <Card key={r.chatroom_name} animate={false}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <h4 className="font-medium text-slate-900">{r.display_name}</h4>
              <p className="font-mono text-xs text-slate-400">群号 {r.chatroom_name}</p>
            </div>
            <Badge variant="purple" size="sm">{r.msg_count} 条消息</Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
            <p>最后活跃：<span className="text-slate-700">{fmtTime(r.last_ts)}</span></p>
          </div>
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-slate-500">活跃成员（按发言解析）</p>
            <div className="flex flex-wrap gap-1.5">
              {(r.members_preview || []).map((m) => (
                <span key={m} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700">
                  {m}
                </span>
              ))}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
};
