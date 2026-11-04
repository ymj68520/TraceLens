// WhatsApp 取证（iOS）的导入弹窗与各功能面板。
// 与 WeChatPanels / QQPanels 并列，页面骨架逻辑在 IMForensics.jsx。
// 数据来自 iOS 备份的 ChatStorage.sqlite（Core Data），后端归一化为 graph.db。
import { useEffect, useState } from 'react';
import {
  BarChart3, ChevronLeft, ChevronRight, Database, FileText,
  MessageSquare, Search, User, Users, Network, Lock,
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
  createWhatsAppImport,
  getWhatsAppSessions, getWhatsAppMessages,
  getWhatsAppContacts, getWhatsAppChatrooms,
} from '../../services/whatsappForensicsService';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const fmtTime = (ts) => {
  if (!ts) return '-';
  try {
    // Timestamps are already Unix seconds (the backend converts from Apple epoch).
    return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return String(ts);
  }
};

const StatCard = ({ icon: Icon, label, value, hint }) => (
  <Card animate={false}>
    <div className="flex items-start gap-3">
      <span className="rounded-lg bg-emerald-50 p-2 text-emerald-600"><Icon size={18} /></span>
      <div className="min-w-0">
        <p className="text-xs text-slate-400">{label}</p>
        <p className="text-xl font-semibold text-slate-800">{value}</p>
        {hint && <p className="truncate text-[11px] text-slate-400">{hint}</p>}
      </div>
    </div>
  </Card>
);

// ---------------------------------------------------------------------------
// import panel
// ---------------------------------------------------------------------------

const emptyForm = { name: '', db_path: '', backup_source: '' };

export const WhatsAppImportModal = ({ isOpen, onClose, onCreated }) => {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const { show } = useToast();

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));

  const submit = async () => {
    if (!form.db_path.trim()) {
      show('请填写 ChatStorage.sqlite 路径或其所在目录', 'error');
      return;
    }
    setBusy(true);
    try {
      const res = await createWhatsAppImport({
        name: form.name.trim(),
        db_path: form.db_path.trim(),
        backup_source: form.backup_source.trim(),
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

  const Field = ({ label, k, ph, hint }) => (
    <label className="block">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <input
        value={form[k]}
        onChange={set(k)}
        placeholder={ph}
        className="mt-1 w-full rounded-lg border-0 bg-white/70 px-3 py-2 font-mono text-xs ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500"
      />
      {hint && <span className="mt-0.5 block text-[11px] text-slate-400">{hint}</span>}
    </label>
  );

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="导入 WhatsApp 数据库" width="max-w-xl">
      <div className="space-y-3">
        <Field label="导入名称" k="name" ph="例：李佩妍 WhatsApp" />
        <Field
          label="数据库路径 *"
          k="db_path"
          ph="/path/to/.../AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
          hint="填写 ChatStorage.sqlite 路径，或包含它的目录；同目录的 ContactsV2.sqlite / CallHistory.sqlite 会自动一并导入。iOS 备份中的文件是 SHA-1 分片，需先按 Manifest.db 还原文件名。"
        />
        <Field label="来源说明" k="backup_source" ph="例：iOS 备份 李佩妍的手機鏡像" />
        <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
          <p className="flex items-center gap-1 font-medium text-slate-600"><Database size={12} /> 只读解析</p>
          <p className="mt-1">源数据库以只读方式打开，不会修改检材；归一化结果写入独立的 graph.db。</p>
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100">取消</button>
        <button
          onClick={submit}
          disabled={busy}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? '导入中…' : '开始导入'}
        </button>
      </div>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// overview tab
// ---------------------------------------------------------------------------

export const WhatsAppOverviewTab = ({ overview }) => {
  if (!overview) return null;
  const {
    owner = {}, stats = {}, type_stats = [], day_stats = [], top_sessions = [],
  } = overview;

  const kv = (label, value) => (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="shrink-0 text-xs text-slate-400">{label}</span>
      <span className="truncate font-mono text-xs text-slate-800" title={String(value ?? '')}>{value || '-'}</span>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <StatCard icon={MessageSquare} label="消息总数" value={stats.total_messages ?? 0}
          hint={`私聊 ${stats.c2c_messages ?? 0} / 群聊 ${stats.group_messages ?? 0}`} />
        <StatCard icon={User} label="联系人" value={stats.contacts ?? 0} />
        <StatCard icon={Users} label="群聊" value={stats.groups ?? 0} />
        <StatCard icon={BarChart3} label="活跃天数" value={day_stats.length} />
        <StatCard icon={Network} label="通话事件" value={stats.calls ?? 0} />
        <StatCard icon={Lock} label="媒体消息" value={stats.media_messages ?? 0} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="👤 账号归属" animate={false}>
          <div className="space-y-0.5">
            {kv('昵称', owner.nickname)}
            {kv('平台', 'iOS WhatsApp')}
            {kv('数据来源', 'ChatStorage.sqlite')}
          </div>
        </Card>

        <Card title="📊 消息类型分布" animate={false}>
          <div className="space-y-1">
            {type_stats.slice(0, 8).map((t) => (
              <div key={t.base_type} className="flex items-center justify-between text-sm">
                <span className="text-slate-600">{t.label}</span>
                <span className="font-mono text-xs text-slate-500">{t.count}</span>
              </div>
            ))}
            {!type_stats.length && <p className="py-4 text-center text-sm text-slate-400">无数据</p>}
          </div>
        </Card>

        <Card title="🔥 活跃会话 Top 8" animate={false}>
          <div className="space-y-1">
            {top_sessions.map((s) => (
              <div key={s.talker} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-slate-600" title={s.display_name}>{s.display_name}</span>
                <span className="shrink-0 font-mono text-xs text-slate-500">{s.msg_count}</span>
              </div>
            ))}
            {!top_sessions.length && <p className="py-4 text-center text-sm text-slate-400">无数据</p>}
          </div>
        </Card>
      </div>

      <Card title="📅 每日活跃" animate={false}>
        {day_stats.length ? (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={day_stats}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#10b981" name="消息数" />
            </BarChart>
          </ResponsiveContainer>
        ) : <p className="py-8 text-center text-sm text-slate-400">无数据</p>}
      </Card>
    </div>
  );
};

// ---------------------------------------------------------------------------
// sessions tab
// ---------------------------------------------------------------------------

export const WhatsAppSessionsTab = ({ importId, onOpenMessages }) => {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getWhatsAppSessions(importId)
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
            <th className="py-2 pr-4">号码 / 群 ID</th>
            <th className="py-2 pr-4">消息数</th>
            <th className="py-2 pr-4">最后活跃</th>
            <th className="py-2">最后消息预览</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sessions.map((s) => (
            <tr
              key={s.talker}
              className="cursor-pointer hover:bg-slate-50"
              onClick={() => onOpenMessages(s.talker)}
            >
              <td className="py-2 pr-4">
                <Badge variant={s.is_group ? 'purple' : 'blue'} size="sm">
                  <span className="mr-1 inline-flex align-[-2px]">
                    {s.is_group ? <Users size={11} /> : <User size={11} />}
                  </span>
                  {s.is_group ? '群聊' : '私聊'}
                </Badge>
              </td>
              <td className="py-2 pr-4 font-medium text-slate-800">{s.display_name}</td>
              <td className="py-2 pr-4 font-mono text-xs text-slate-400">{s.talker}</td>
              <td className="py-2 pr-4">{s.msg_count}</td>
              <td className="py-2 pr-4 text-slate-500">{fmtTime(s.last_timestamp)}</td>
              <td className="max-w-[280px] truncate py-2 text-slate-500">{s.last_message}</td>
            </tr>
          ))}
          {!sessions.length && (
            <tr><td colSpan={6} className="py-8 text-center text-sm text-slate-400">无会话</td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// messages tab
// ---------------------------------------------------------------------------

const PAGE_SIZE = 100;

export const WhatsAppMessagesTab = ({ importId, initialTalker }) => {
  const [talker, setTalker] = useState(initialTalker || '');
  const [keyword, setKeyword] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ total: 0, records: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => { setTalker(initialTalker || ''); setPage(1); }, [initialTalker]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getWhatsAppMessages(importId, {
      talker: talker || undefined,
      keyword: appliedKeyword || undefined,
      page,
      page_size: PAGE_SIZE,
    })
      .then((res) => alive && setData({ total: res.total || 0, records: res.records || [] }))
      .catch(() => alive && setData({ total: 0, records: [] }))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId, talker, appliedKeyword, page]);

  const totalPages = Math.max(Math.ceil(data.total / PAGE_SIZE), 1);

  return (
    <div className="space-y-3">
      <Card animate={false}>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); setAppliedKeyword(keyword); } }}
              placeholder="搜索消息内容，回车确认"
              className="w-full rounded-lg border-0 bg-white/70 py-2 pl-9 pr-3 text-sm ring-1 ring-slate-200 focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <button
            onClick={() => { setPage(1); setAppliedKeyword(keyword); }}
            className="rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white"
          >搜索</button>
          {talker && (
            <Badge variant="blue" size="sm">
              会话筛选：{talker}
              <button onClick={() => setTalker('')} className="ml-2 text-slate-500 hover:text-slate-800">×</button>
            </Badge>
          )}
          <span className="ml-auto text-xs text-slate-400">共 {data.total} 条</span>
        </div>
      </Card>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : (
        <Card animate={false}>
          <div className="divide-y divide-slate-100">
            {data.records.map((m) => (
              <div key={m.id} className="flex gap-3 py-2">
                <div className="w-40 shrink-0">
                  <p className={`truncate text-xs font-medium ${m.is_send ? 'text-emerald-600' : 'text-slate-700'}`}>
                    {m.is_send ? '我' : m.sender}
                  </p>
                  <p className="text-[10px] text-slate-400">{fmtTime(m.timestamp)}</p>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="whitespace-pre-wrap break-words text-sm text-slate-700">{m.content}</p>
                  {m.media_type && <Badge variant="gray" size="sm"><span className="mr-1"><FileText size={10} /></span>{m.media_type}</Badge>}
                </div>
                <span className="shrink-0 text-[10px] text-slate-400">{m.msg_type_label}</span>
              </div>
            ))}
            {!data.records.length && (
              <p className="py-8 text-center text-sm text-slate-400">无消息</p>
            )}
          </div>
        </Card>
      )}

      <div className="flex items-center justify-center gap-2">
        <button
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(p - 1, 1))}
          className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100 disabled:opacity-40"
        ><ChevronLeft size={16} /></button>
        <span className="text-xs text-slate-500">{page} / {totalPages}</span>
        <button
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
          className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100 disabled:opacity-40"
        ><ChevronRight size={16} /></button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// contacts tab
// ---------------------------------------------------------------------------

export const WhatsAppContactsTab = ({ importId }) => {
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getWhatsAppContacts(importId)
      .then((res) => alive && setContacts(res.contacts || []))
      .catch(() => alive && setContacts([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId]);

  if (loading) return <div className="flex justify-center py-12"><Spinner /></div>;

  return (
    <Card animate={false}>
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400">
            <th className="py-2 pr-4">昵称</th>
            <th className="py-2 pr-4">号码</th>
            <th className="py-2">备注</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {contacts.map((c) => (
            <tr key={c.username}>
              <td className="py-2 pr-4 font-medium text-slate-800">{c.nickname}</td>
              <td className="py-2 pr-4 font-mono text-xs text-slate-500">{c.mobile || c.username}</td>
              <td className="py-2 text-slate-500">{c.remark || '-'}</td>
            </tr>
          ))}
          {!contacts.length && (
            <tr><td colSpan={3} className="py-8 text-center text-sm text-slate-400">无联系人</td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// chatrooms tab
// ---------------------------------------------------------------------------

export const WhatsAppChatroomsTab = ({ importId }) => {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getWhatsAppChatrooms(importId)
      .then((res) => alive && setRooms(res.chatrooms || []))
      .catch(() => alive && setRooms([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [importId]);

  if (loading) return <div className="flex justify-center py-12"><Spinner /></div>;

  return (
    <Card animate={false}>
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400">
            <th className="py-2 pr-4">群名称</th>
            <th className="py-2 pr-4">群 ID</th>
            <th className="py-2">消息数</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rooms.map((r) => (
            <tr key={r.chatroom_name}>
              <td className="py-2 pr-4 font-medium text-slate-800">{r.chatroom_name}</td>
              <td className="py-2 pr-4 font-mono text-xs text-slate-400">{r.owner || '-'}</td>
              <td className="py-2">{r.msg_count}</td>
            </tr>
          ))}
          {!rooms.length && (
            <tr><td colSpan={3} className="py-8 text-center text-sm text-slate-400">无群聊</td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
};
