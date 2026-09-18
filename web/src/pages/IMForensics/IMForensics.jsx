// 即时通讯取证（IMForensics）—— 2026-09-15 由 微信取证 / QQ 取证 / 微信关系分析
// 三页合并而来。平台（微信/QQ）切换 + 六个 Tab（概览/会话/消息/联系人/群聊/关系分析）。
// platform / tab / import_id / task_id（图谱数据源覆盖）都落在 URL 上，旧路由
// （/wechat-forensics、/qq-forensics、/wechat-graph）经 IMForensicsRedirect 映射进来。
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Database, FileText, MessageSquare, Plus, RefreshCw, Trash2, User, Users, Network,
} from 'lucide-react';
import Card from '../../components/common/Card';
import Spinner from '../../components/common/Spinner';
import { useToast } from '../../components/common/useToast';
import {
  listWeChatImports, deleteWeChatImport, getWeChatForensicsOverview,
} from '../../services/wechatForensicsService';
import {
  listQQImports, deleteQQImport, getQQForensicsOverview,
} from '../../services/qqForensicsService';
import {
  WeChatImportModal, WeChatOverviewTab, WeChatSessionsTab,
  WeChatMessagesTab, WeChatContactsTab, WeChatChatroomsTab,
} from './WeChatPanels';
import {
  QQImportModal, QQOverviewTab, QQSessionsTab,
  QQMessagesTab, QQContactsTab, QQChatroomsTab,
} from './QQPanels';
import GraphTab from './GraphTab';

// ---------------------------------------------------------------------------

const TABS = [
  { id: 'overview', label: '取证概览', icon: FileText },
  { id: 'sessions', label: '会话列表', icon: MessageSquare },
  { id: 'messages', label: '聊天记录', icon: FileText },
  { id: 'contacts', label: '联系人', icon: User },
  { id: 'chatrooms', label: '群聊', icon: Users },
  { id: 'graph', label: '关系分析', icon: Network },
];

const TAB_IDS = new Set(TABS.map((t) => t.id));

const PLATFORMS = {
  wechat: {
    key: 'wechat',
    label: '微信',
    taskPrefix: 'wx_',
    listImports: listWeChatImports,
    deleteImport: deleteWeChatImport,
    getOverview: getWeChatForensicsOverview,
    panels: {
      ImportModal: WeChatImportModal,
      OverviewTab: WeChatOverviewTab,
      SessionsTab: WeChatSessionsTab,
      MessagesTab: WeChatMessagesTab,
      ContactsTab: WeChatContactsTab,
      ChatroomsTab: WeChatChatroomsTab,
    },
    emptyHint: '点击「导入数据库」，填写 EnMicroMsg.db 路径（支持加密原件，自动页面级检测与解密）以及 UIN / IMEI / wxid 等密钥材料，即可开始微信取证分析。',
  },
  qq: {
    key: 'qq',
    label: 'QQ',
    taskPrefix: 'qq_',
    listImports: listQQImports,
    deleteImport: deleteQQImport,
    getOverview: getQQForensicsOverview,
    panels: {
      ImportModal: QQImportModal,
      OverviewTab: QQOverviewTab,
      SessionsTab: QQSessionsTab,
      MessagesTab: QQMessagesTab,
      ContactsTab: QQContactsTab,
      ChatroomsTab: QQChatroomsTab,
    },
    emptyHint: '点击「导入数据库」，填写 nt_msg.db 路径（支持 SQLCipher 加密原件，自动离线推导密钥并解密）以及 nt_uid / QQ 号，即可开始 QQ 取证分析。',
  },
};

// ---------------------------------------------------------------------------

export default function IMForensics() {
  const [searchParams, setSearchParams] = useSearchParams();

  const platformKey = searchParams.get('platform') === 'qq' ? 'qq' : 'wechat';
  const platform = PLATFORMS[platformKey];
  const rawTab = searchParams.get('tab');
  const activeTab = TAB_IDS.has(rawTab) ? rawTab : 'overview';
  const urlImportId = searchParams.get('import_id') || '';
  // 原始扫描任务 ID（来自全局任务上下文或旧 /wechat-graph 链接）：存在时图谱 Tab 优先用它
  const graphTaskOverride = searchParams.get('task_id') || '';

  const [imports, setImports] = useState([]);
  const [overview, setOverview] = useState(null);
  const [msgTalker, setMsgTalker] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const { show } = useToast();

  // 用户主动的导航（切 Tab / 切平台 / 换导入 / 跳聊天记录）默认 push 历史条目，
  // 浏览器"返回"才能回到上一个功能页；自动纠偏类调用显式传 { replace: true }，
  // 避免参数自动修正塞满历史记录。（之前统一 replace 导致页内切换后无法返回）
  const updateParams = useCallback((mutate, options = {}) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      mutate(next);
      return next;
    }, { replace: false, ...options });
  }, [setSearchParams]);

  // setSearchParams 每次 search 变化都会换新引用；经 ref 取用，避免加载列表的
  // effect 因 URL 变化反复重跑
  const updateParamsRef = useRef(updateParams);
  useEffect(() => { updateParamsRef.current = updateParams; });

  const refreshImports = useCallback(async (selectId) => {
    try {
      const res = await platform.listImports();
      setImports(res.imports || []);
      if (selectId) {
        updateParamsRef.current((p) => { p.set('import_id', selectId); p.delete('task_id'); }, { replace: true });
      }
    } catch (e) {
      show(`加载导入列表失败：${e.data?.detail || e.message}`, 'error');
    } finally {
      setLoadingList(false);
    }
  }, [platform, show]);

  // 切平台立即丢弃上一平台的列表，避免加载间隙误选到别的平台的导入
  useEffect(() => {
    setImports([]);
    setLoadingList(true);
    setOverview(null);
  }, [platformKey]);

  useEffect(() => { refreshImports(); }, [refreshImports]);

  // URL 里的 import_id 失效（跨平台残留/被删除/未指定）时回退到首条可用导入
  useEffect(() => {
    if (loadingList) return;
    const items = imports;
    const exists = urlImportId && items.some((i) => i.import_id === urlImportId);
    if (exists) return;
    const ready = items.filter((i) => i.status === 'ready');
    const target = (ready[0] || items[0] || {}).import_id || '';
    if (target !== urlImportId) {
      // 注意：不清理 task_id 覆盖 —— 旧 /wechat-graph 链接可能只带原始任务 ID，
      // 自动选中导入不应吞掉它；只有用户主动切换平台/导入时才清除
      updateParams((p) => p.set('import_id', target), { replace: true });
    }
  }, [imports, loadingList, urlImportId, updateParams]);

  useEffect(() => {
    if (!urlImportId) { setOverview(null); return; }
    let alive = true;
    platform.getOverview(urlImportId)
      .then((res) => alive && setOverview(res))
      .catch(() => alive && setOverview(null));
    return () => { alive = false; };
  }, [urlImportId, platform]);

  const current = imports.find((i) => i.import_id === urlImportId);

  const removeImport = async () => {
    if (!urlImportId) return;
    if (!window.confirm(`确定删除导入「${current?.name || urlImportId}」及其解密数据？`)) return;
    try {
      await platform.deleteImport(urlImportId);
      show('已删除', 'success');
      refreshImports();
    } catch (e) {
      show(`删除失败：${e.data?.detail || e.message}`, 'error');
    }
  };

  const selectPlatform = (key) => {
    if (key === platformKey) return;
    setMsgTalker('');
    updateParams((p) => { p.set('platform', key); p.delete('import_id'); p.delete('task_id'); });
  };

  const openMessagesForTalker = (talker) => {
    setMsgTalker(talker);
    updateParams((p) => p.set('tab', 'messages'));
  };

  const graphTaskId = graphTaskOverride
    || (urlImportId ? `${platform.taskPrefix}${urlImportId}` : null);

  if (loadingList) return <div className="flex items-center justify-center h-full"><Spinner /></div>;

  const graphOnly = activeTab === 'graph' && !!graphTaskOverride;
  const P = platform.panels;

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-900">即时通讯取证</h2>
        <div className="flex rounded-xl bg-white/60 p-1 ring-1 ring-slate-200">
          {Object.values(PLATFORMS).map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => selectPlatform(p.key)}
              className={`rounded-lg px-3.5 py-1.5 text-sm transition-colors ${
                platformKey === p.key ? 'bg-primary-600 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <select
          value={urlImportId}
          onChange={(e) => updateParams((p) => { p.set('import_id', e.target.value); p.delete('task_id'); })}
          className="rounded-lg border-0 bg-white/70 px-3 py-2 text-sm ring-1 ring-slate-200"
        >
          {imports.length === 0 && <option value="">（暂无导入）</option>}
          {imports.map((i) => (
            <option key={i.import_id} value={i.import_id}>
              {i.name || i.import_id} — {i.message_count ?? i.stats?.total_messages ?? 0} 条消息 {i.status !== 'ready' ? '(失败)' : ''}
            </option>
          ))}
        </select>
        <button onClick={() => setShowImport(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700">
          <Plus size={15} /> 导入数据库
        </button>
        <button onClick={() => refreshImports()} className="inline-flex items-center gap-1.5 rounded-lg bg-white/70 px-3 py-2 text-sm text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50">
          <RefreshCw size={14} /> 刷新
        </button>
        {urlImportId && current?.status === 'ready' && (
          <button onClick={removeImport} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-rose-600 hover:bg-rose-50">
            <Trash2 size={14} /> 删除
          </button>
        )}
      </div>

      {!urlImportId && !graphOnly ? (
        <Card>
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <Database size={36} className="text-slate-300" />
            <p className="text-slate-500">尚未导入{platform.label}账号数据库</p>
            <p className="max-w-xl text-sm text-slate-400">{platform.emptyHint}</p>
            <button onClick={() => setShowImport(true)} className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700">
              <Plus size={15} /> 导入数据库
            </button>
          </div>
        </Card>
      ) : urlImportId && current && current.status !== 'ready' && !graphOnly ? (
        <Card>
          <div className="py-8 text-center">
            <p className="text-rose-500">导入失败</p>
            <p className="mt-2 text-sm text-slate-500">{current.error || '未知错误'}</p>
          </div>
        </Card>
      ) : (
        <>
          <div className="flex gap-1 overflow-x-auto rounded-xl bg-white/60 p-1 ring-1 ring-slate-200">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => updateParams((p) => p.set('tab', t.id))}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm transition-colors ${
                  activeTab === t.id ? 'bg-primary-600 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <t.icon size={14} /> {t.label}
              </button>
            ))}
          </div>

          {activeTab === 'overview' && (overview ? <P.OverviewTab overview={overview} /> : <div className="flex justify-center py-12"><Spinner /></div>)}
          {activeTab === 'sessions' && urlImportId && <P.SessionsTab importId={urlImportId} onOpenMessages={openMessagesForTalker} />}
          {activeTab === 'messages' && urlImportId && <P.MessagesTab importId={urlImportId} initialTalker={msgTalker} />}
          {activeTab === 'contacts' && urlImportId && <P.ContactsTab importId={urlImportId} />}
          {activeTab === 'chatrooms' && urlImportId && <P.ChatroomsTab importId={urlImportId} />}
          {activeTab === 'graph' && (
            <GraphTab
              taskId={graphTaskId}
              overrideTaskId={graphTaskOverride || null}
              onClearOverride={() => updateParams((p) => p.delete('task_id'))}
            />
          )}
        </>
      )}

      <P.ImportModal isOpen={showImport} onClose={() => setShowImport(false)} onCreated={(id) => { setShowImport(false); refreshImports(id); }} />
    </div>
  );
}
