import React, { useState, useMemo, useCallback } from 'react';
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Compass,
  FileSearch,
  Filter,
  History,
  Layers,
  ListOrdered,
  Maximize2,
  Microscope,
  Minimize2,
  Network,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
  User,
  Wrench,
} from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Spinner from '../../../components/common/Spinner';

// Pre-defined knowledge base for core questions
const QUESTION_KNOWLEDGE = {
  Q1: {
    title: '系统部署与运维执行痕迹',
    desc: '排查宝塔面板(BT Panel)、下载脚本与服务安装行为',
    icon: Terminal,
    pillar: 'P1',
  },
  Q2: {
    title: '涉案嫌疑人账号与身份凭据',
    desc: '排查 adduser/passwd 新增账号与异常提权记录',
    icon: User,
    pillar: 'P2',
  },
  Q3: {
    title: '服务自启动与开机持久化配置',
    desc: '排查 chkconfig/systemd 等异常自启服务',
    icon: Cpu,
    pillar: 'P3',
  },
  'q-61dff02c': {
    title: '远程网络连接与外部 IP 通信记录',
    desc: '确认外部控制源与数据通道',
    icon: Network,
    pillar: 'P4',
  },
  'q-ad56bfce': {
    title: '反取证与日志篡改行为',
    desc: '定位系统日志与认证日志中的异常时间跳变与删除痕迹',
    icon: ShieldAlert,
    pillar: 'P5',
  },
  'q-b856d85c': {
    title: '系统登录历史与主机重启事件',
    desc: '核查 wtmp/last 记录与终端会话对应关系',
    icon: History,
    pillar: 'P6',
  },
  'q-de74d9f4': {
    title: '受害主机系统环境与发行版特征',
    desc: '固化 /etc/redhat-release 与系统配置文件',
    icon: Compass,
    pillar: 'P7',
  },
};

/**
 * TrajectoryTimeline
 * 具有多层级收纳折叠、阶段委派分组、一键全局展开/折叠与快速筛选的高性能执行轨迹展示组件
 */
export default function TrajectoryTimeline({
  events = [],
  loading = false,
  onRefresh,
  latestTrajectoryRef = '',
  questions = [],
  isExecuting = false,
}) {
  // View mode: 'grouped' (阶段与委派收纳) | 'flat' (平铺时间线)
  const [viewMode, setViewMode] = useState('grouped');

  // Filter: 'all' | 'tools' | 'delegations' | 'integrations' | 'alerts'
  const [filterType, setFilterType] = useState('all');

  // Set of group IDs currently expanded
  const [expandedGroups, setExpandedGroups] = useState(() => new Set());
  const [userInteractedWithGroups, setUserInteractedWithGroups] = useState(false);

  // Set of event keys (seq) whose payload drawer is expanded
  const [expandedEventDetails, setExpandedEventDetails] = useState(() => new Set());

  // Build question metadata resolver
  const questionMap = useMemo(() => {
    const map = new Map();
    // Default from QUESTION_KNOWLEDGE
    Object.entries(QUESTION_KNOWLEDGE).forEach(([k, v]) => map.set(k, v));
    // Dynamic from questions prop
    if (Array.isArray(questions)) {
      questions.forEach((q, idx) => {
        if (!q?.question_id) return;
        const existing = map.get(q.question_id);
        map.set(q.question_id, {
          title: q.title || existing?.title || q.text?.slice(0, 24) || `调查方向 ${q.question_id}`,
          desc: q.desc || existing?.desc || q.text || '',
          icon: existing?.icon || Microscope,
          pillar: existing?.pillar || `P${idx + 1}`,
        });
      });
    }
    return map;
  }, [questions]);

  // Build delegation ID -> Question Ref mapping
  const delToQuestionMap = useMemo(() => {
    const map = new Map();
    events.forEach((evt) => {
      const p = evt.payload || {};
      const delId = evt.delegation_id || p.delegation_id;
      const qref = p.question_ref || p.question_id;
      if (delId && qref) {
        map.set(delId, qref);
      }
    });
    return map;
  }, [events]);

  // Group events hierarchically
  const groups = useMemo(() => {
    if (!events || events.length === 0) return [];

    const rawGroups = [];
    let current = null;

    events.forEach((evt) => {
      const etype = evt.event_type || '';
      const p = evt.payload || {};
      const delId = evt.delegation_id || p.delegation_id;

      let gtype = 'standalone';
      let gid = `item_${evt.seq}`;
      let gtitle = evt.title;
      let qref = null;

      if (
        [
          'investigation_created',
          'attention_compiled',
          'run_admitted',
          'run_started',
          'supervisor_plan_decided',
          'delegation_admitted',
        ].includes(etype)
      ) {
        gtype = 'planning';
        gid = `planning_${evt.run_id || 'main'}`;
        gtitle = '🎯 目标规划与任务准入';
      } else if (
        delId ||
        [
          'delegation_started',
          'tool_observation_recorded',
          'tool_executed',
          'delegation_completed',
          'delegation_failed',
          'delegation_succeeded',
        ].includes(etype)
      ) {
        gtype = 'delegation';
        gid = delId ? `del_${delId}` : `del_seq_${evt.seq}`;
        qref = delId ? delToQuestionMap.get(delId) : null;
        const qmeta = qref ? questionMap.get(qref) : null;
        if (qmeta) {
          gtitle = `🔬 专家专项取证: ${qmeta.pillar} ${qmeta.title}`;
        } else if (qref) {
          gtitle = `🔬 专家专项取证 [${qref}]`;
        } else {
          gtitle = `🔬 专家专项取证 (委派 ID: ${delId ? delId.slice(0, 10) : evt.seq})`;
        }
      } else if (
        [
          'supervisor_integration_committed',
          'working_state_committed',
          'working_state_integrated',
          'run_completed',
          'investigation_completed',
        ].includes(etype)
      ) {
        gtype = 'integration';
        const rev = p.result_revision || p.state_revision || p.revision || '';
        gid = `integ_${evt.run_id || 'main'}_${rev}`;
        gtitle = rev ? `⚖️ 成果整合与状态固化 (Rev ${rev})` : '⚖️ 成果整合与状态固化';
      } else if (etype.includes('review')) {
        gtype = 'review';
        gid = `review_${evt.seq}`;
        gtitle = evt.title || '🛡️ 研判审核复核记录';
      }

      if (!current || current.id !== gid) {
        if (current) rawGroups.push(current);
        current = {
          id: gid,
          type: gtype,
          title: gtitle,
          delId,
          qref,
          events: [evt],
        };
      } else {
        current.events.push(evt);
      }
    });

    if (current) rawGroups.push(current);

    // Merge consecutive planning groups if any
    const merged = [];
    rawGroups.forEach((g) => {
      const prev = merged[merged.length - 1];
      if (prev && prev.type === 'planning' && g.type === 'planning') {
        prev.events.push(...g.events);
      } else {
        merged.push({ ...g });
      }
    });

    return merged;
  }, [events, delToQuestionMap, questionMap]);

  // Set default expanded group to the latest group when events load
  React.useEffect(() => {
    if (!userInteractedWithGroups && groups.length > 0) {
      // Expand the latest 1 or 2 groups by default
      const lastGroup = groups[groups.length - 1];
      const nextSet = new Set();
      if (lastGroup) nextSet.add(lastGroup.id);
      // If the last is integration, also expand the last delegation
      if (lastGroup?.type === 'integration' && groups.length > 1) {
        nextSet.add(groups[groups.length - 2].id);
      }
      setExpandedGroups(nextSet);
    }
  }, [groups, userInteractedWithGroups]);

  // Toggle single group expand/collapse
  const toggleGroup = useCallback((groupId) => {
    setUserInteractedWithGroups(true);
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }, []);

  // Toggle single event details expand/collapse
  const toggleEventDetail = useCallback((eventKey) => {
    setExpandedEventDetails((prev) => {
      const next = new Set(prev);
      if (next.has(eventKey)) {
        next.delete(eventKey);
      } else {
        next.add(eventKey);
      }
      return next;
    });
  }, []);

  // Check if any group is currently expanded
  const isAnyGroupExpanded = expandedGroups.size > 0;

  // Global toggle all groups: if any open -> close all; if none open -> open all
  const toggleAllGroups = useCallback(() => {
    setUserInteractedWithGroups(true);
    if (expandedGroups.size > 0) {
      setExpandedGroups(new Set());
    } else {
      const allIds = new Set(groups.map((g) => g.id));
      setExpandedGroups(allIds);
    }
  }, [expandedGroups.size, groups]);

  // Category counters
  const categoryCounts = useMemo(() => {
    let tools = 0;
    let delegations = 0;
    let integrations = 0;
    let alerts = 0;

    events.forEach((e) => {
      const et = e.event_type || '';
      if (et.includes('tool')) tools++;
      if (et.includes('delegation')) delegations++;
      if (et.includes('committed') || et.includes('integrated')) integrations++;
      if (et.includes('rejected') || et.includes('failed') || (e.payload?.warnings && e.payload.warnings.length > 0)) {
        alerts++;
      }
    });

    return { total: events.length, tools, delegations, integrations, alerts };
  }, [events]);

  // Filtered events for Flat view
  const filteredFlatEvents = useMemo(() => {
    if (filterType === 'all') return events;
    return events.filter((e) => {
      const et = e.event_type || '';
      if (filterType === 'tools') return et.includes('tool');
      if (filterType === 'delegations') return et.includes('delegation');
      if (filterType === 'integrations') return et.includes('committed') || et.includes('integrated');
      if (filterType === 'alerts') {
        return (
          et.includes('rejected') ||
          et.includes('failed') ||
          (e.payload?.warnings && e.payload.warnings.length > 0)
        );
      }
      return true;
    });
  }, [events, filterType]);

  // Filtered groups for Grouped view
  const filteredGroups = useMemo(() => {
    if (filterType === 'all') return groups;
    return groups
      .map((g) => {
        const matchingEvents = g.events.filter((e) => {
          const et = e.event_type || '';
          if (filterType === 'tools') return et.includes('tool');
          if (filterType === 'delegations') return et.includes('delegation');
          if (filterType === 'integrations') return et.includes('committed') || et.includes('integrated');
          if (filterType === 'alerts') {
            return (
              et.includes('rejected') ||
              et.includes('failed') ||
              (e.payload?.warnings && e.payload.warnings.length > 0)
            );
          }
          return true;
        });
        return { ...g, events: matchingEvents };
      })
      .filter((g) => g.events.length > 0);
  }, [groups, filterType]);

  // Helper for badge variant and dot color
  const getEventStyle = (evt) => {
    const et = evt.event_type || '';
    const isRejected = et.includes('rejected') || et.includes('failed');
    const isReview = et.includes('review');
    const isCommit = et.includes('committed') || et.includes('integrated');
    const isCompile = et.includes('compiled') || et.includes('admitted') || et.includes('plan');
    const isTool = et.includes('tool');

    return {
      badgeVariant: isRejected
        ? 'red'
        : isReview
        ? 'green'
        : isCommit
        ? 'purple'
        : isCompile
        ? 'blue'
        : isTool
        ? 'indigo'
        : 'slate',
      dotColor: isRejected
        ? 'bg-rose-500'
        : isReview
        ? 'bg-emerald-500'
        : isCommit
        ? 'bg-purple-500'
        : isCompile
        ? 'bg-blue-500'
        : isTool
        ? 'bg-indigo-500'
        : 'bg-slate-500',
    };
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden text-xs">
      {/* ── Top Control & Summary Toolbar ─────────────────────────────────── */}
      <div className="pb-3 border-b border-slate-100 dark:border-slate-800 space-y-2">
        {/* Row 1: Counts, Global Expand/Collapse & Refresh */}
        <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 font-mono text-[11px] text-slate-500">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-700 dark:text-slate-200">
              轨迹事件: {events.length} 条
            </span>
            <span
              className="text-slate-400 truncate max-w-[120px] hidden sm:inline"
              title={latestTrajectoryRef}
            >
              ({latestTrajectoryRef || 'init'})
            </span>
          </div>

          <div className="flex items-center gap-1.5 font-sans">
            {/* View Mode Toggle */}
            <div className="flex items-center bg-slate-200/70 dark:bg-slate-800 p-0.5 rounded-lg text-[10px]">
              <button
                type="button"
                onClick={() => setViewMode('grouped')}
                className={`px-2 py-0.5 rounded transition-all font-medium ${
                  viewMode === 'grouped'
                    ? 'bg-white dark:bg-slate-700 text-purple-700 dark:text-purple-300 shadow-xs'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
                title="按阶段与专家委派折叠收纳"
              >
                阶段收纳
              </button>
              <button
                type="button"
                onClick={() => setViewMode('flat')}
                className={`px-2 py-0.5 rounded transition-all font-medium ${
                  viewMode === 'flat'
                    ? 'bg-white dark:bg-slate-700 text-purple-700 dark:text-purple-300 shadow-xs'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
                title="按时序平铺全部事件"
              >
                平铺流
              </button>
            </div>

            {/* Toggle All Expand / Collapse */}
            {viewMode === 'grouped' && (
              <button
                type="button"
                onClick={toggleAllGroups}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-all border border-slate-200/80 dark:border-slate-700/60"
                title={isAnyGroupExpanded ? '全部折叠收纳' : '全部展开查看'}
              >
                {isAnyGroupExpanded ? (
                  <>
                    <Minimize2 className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                    <span>全部收起</span>
                  </>
                ) : (
                  <>
                    <Maximize2 className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                    <span>全部展开</span>
                  </>
                )}
              </button>
            )}

            {/* Refresh Button */}
            <button
              type="button"
              onClick={onRefresh}
              className="text-purple-600 hover:text-purple-700 dark:text-purple-400 p-1 rounded hover:bg-purple-50 dark:hover:bg-purple-950/40 transition-colors"
              title="刷新轨迹事件"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Row 2: Category Filter Chips */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 text-[11px] scrollbar-none">
          <button
            type="button"
            onClick={() => setFilterType('all')}
            className={`px-2 py-0.5 rounded-full border transition-all shrink-0 ${
              filterType === 'all'
                ? 'bg-purple-600 text-white border-purple-600 font-semibold shadow-xs'
                : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
            }`}
          >
            全部 ({categoryCounts.total})
          </button>
          <button
            type="button"
            onClick={() => setFilterType('tools')}
            className={`px-2 py-0.5 rounded-full border transition-all shrink-0 ${
              filterType === 'tools'
                ? 'bg-indigo-600 text-white border-indigo-600 font-semibold shadow-xs'
                : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
            }`}
          >
            🛠️ 工具 ({categoryCounts.tools})
          </button>
          <button
            type="button"
            onClick={() => setFilterType('delegations')}
            className={`px-2 py-0.5 rounded-full border transition-all shrink-0 ${
              filterType === 'delegations'
                ? 'bg-blue-600 text-white border-blue-600 font-semibold shadow-xs'
                : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
            }`}
          >
            🔬 委派 ({categoryCounts.delegations})
          </button>
          <button
            type="button"
            onClick={() => setFilterType('integrations')}
            className={`px-2 py-0.5 rounded-full border transition-all shrink-0 ${
              filterType === 'integrations'
                ? 'bg-purple-600 text-white border-purple-600 font-semibold shadow-xs'
                : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
            }`}
          >
            ⚖️ 整合 ({categoryCounts.integrations})
          </button>
          {categoryCounts.alerts > 0 && (
            <button
              type="button"
              onClick={() => setFilterType('alerts')}
              className={`px-2 py-0.5 rounded-full border transition-all shrink-0 ${
                filterType === 'alerts'
                  ? 'bg-rose-600 text-white border-rose-600 font-semibold shadow-xs'
                  : 'border-rose-200 dark:border-rose-900 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40'
              }`}
            >
              ⚠️ 拦截 ({categoryCounts.alerts})
            </button>
          )}
        </div>
      </div>

      {/* ── Trajectory Content Scroll Area ─────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto space-y-3 pt-3 pr-1 text-xs">
        {loading && events.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2 text-slate-400">
            <Spinner size="sm" />
            <span>读取审计轨迹中...</span>
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-12 text-slate-400 text-xs">
            暂无执行轨迹记录，点击右上角启动自主研判循环
          </div>
        ) : viewMode === 'grouped' ? (
          /* ═════════════════════════════════════════════════════════════════
             GROUPED VIEW: Hierarchical Accordion by Stage & Delegation
             ═════════════════════════════════════════════════════════════════ */
          <div className="space-y-3">
            {filteredGroups.map((group, gIdx) => {
              const isExpanded = expandedGroups.has(group.id);
              const isDelegation = group.type === 'delegation';
              const isIntegration = group.type === 'integration';
              const isPlanning = group.type === 'planning';

              // Delegation metadata
              const qmeta = group.qref ? questionMap.get(group.qref) : null;
              const toolCount = group.events.filter((e) => (e.event_type || '').includes('tool')).length;
              const hasFailure = group.events.some((e) => (e.event_type || '').includes('failed'));
              const isLastGroup = gIdx === filteredGroups.length - 1;
              const isActiveExecuting = isLastGroup && isExecuting;

              // Group Header Styling
              let borderClass = 'border-slate-200 dark:border-slate-800';
              let bgHeaderClass = 'bg-slate-50/80 dark:bg-slate-900/60 hover:bg-slate-100/80 dark:hover:bg-slate-800/80';
              let iconElement = <BrainCircuit className="w-4 h-4 text-purple-600 dark:text-purple-400" />;

              if (isDelegation) {
                borderClass = isExpanded
                  ? 'border-indigo-200 dark:border-indigo-800/80'
                  : 'border-slate-200 dark:border-slate-800';
                bgHeaderClass = hasFailure
                  ? 'bg-slate-50 dark:bg-slate-900/60'
                  : 'bg-indigo-50/50 dark:bg-indigo-950/20 hover:bg-indigo-50/80 dark:hover:bg-indigo-950/40';
                const IconComponent = qmeta?.icon || Microscope;
                iconElement = (
                  <div
                    className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 ${
                      isActiveExecuting
                        ? 'bg-indigo-600 text-white animate-pulse'
                        : 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300'
                    }`}
                  >
                    <IconComponent className="w-3.5 h-3.5" />
                  </div>
                );
              } else if (isIntegration) {
                borderClass = 'border-purple-200 dark:border-purple-800/80';
                bgHeaderClass = 'bg-purple-50/50 dark:bg-purple-950/20 hover:bg-purple-50/80 dark:hover:bg-purple-950/40';
                iconElement = (
                  <div className="w-6 h-6 rounded-md bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 flex items-center justify-center shrink-0">
                    <ShieldCheck className="w-3.5 h-3.5" />
                  </div>
                );
              } else if (isPlanning) {
                borderClass = 'border-slate-200 dark:border-slate-800';
                bgHeaderClass = 'bg-slate-50 dark:bg-slate-900/40 hover:bg-slate-100/60 dark:hover:bg-slate-800/50';
                iconElement = (
                  <div className="w-6 h-6 rounded-md bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 flex items-center justify-center shrink-0">
                    <BrainCircuit className="w-3.5 h-3.5" />
                  </div>
                );
              }

              return (
                <div
                  key={group.id}
                  className={`rounded-xl border transition-all overflow-hidden shadow-2xs ${borderClass}`}
                >
                  {/* Group Header Bar (Click to fold/unfold) */}
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.id)}
                    className={`w-full text-left p-3 flex items-center justify-between gap-2.5 transition-colors cursor-pointer ${bgHeaderClass}`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      {iconElement}
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 truncate">
                            {group.title}
                          </span>
                          {qmeta?.pillar && (
                            <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300">
                              {qmeta.pillar}
                            </span>
                          )}
                        </div>

                        {/* Subtitle / summary info */}
                        <div className="flex items-center gap-2 text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">
                          {isDelegation && (
                            <span>
                              {toolCount > 0 ? `${toolCount} 次底层工具调用` : `${group.events.length} 项取证动作`}
                            </span>
                          )}
                          {isPlanning && <span>{group.events.length} 项规划与准入调度</span>}
                          {isIntegration && (
                            <span className="text-purple-600 dark:text-purple-400 font-medium">
                              多路分析成果汇聚固化
                            </span>
                          )}
                          <span>·</span>
                          <span className="font-mono">
                            {group.events[0]?.created_at
                              ? new Date(group.events[0].created_at).toLocaleTimeString()
                              : ''}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {isDelegation && (
                        <Badge
                          size="xs"
                          variant={isActiveExecuting ? 'yellow' : hasFailure ? 'slate' : 'green'}
                        >
                          {isActiveExecuting ? '执行中' : hasFailure ? '链路结束' : '完成'}
                        </Badge>
                      )}
                      {isIntegration && (
                        <Badge size="xs" variant="purple">
                          版本固化
                        </Badge>
                      )}
                      {isPlanning && (
                        <Badge size="xs" variant="blue">
                          已规划
                        </Badge>
                      )}

                      {/* Expand / Collapse Chevron */}
                      <div
                        className={`w-5 h-5 rounded flex items-center justify-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-transform duration-200 ${
                          isExpanded ? 'rotate-180' : ''
                        }`}
                      >
                        <ChevronDown className="w-3.5 h-3.5" />
                      </div>
                    </div>
                  </button>

                  {/* Group Collapsible Content */}
                  {isExpanded && (
                    <div className="p-3 bg-white dark:bg-slate-950/60 border-t border-slate-100 dark:border-slate-800/80 space-y-2.5">
                      <div className="relative pl-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200 dark:before:bg-slate-800 space-y-2.5">
                        {group.events.map((evt) => {
                          const { badgeVariant, dotColor } = getEventStyle(evt);
                          const isDetailExpanded = expandedEventDetails.has(evt.seq);
                          const hasPayload = evt.payload && Object.keys(evt.payload).length > 0;

                          return (
                            <div key={evt.event_id || evt.seq} className="relative">
                              {/* Sequence Dot */}
                              <div
                                className={`absolute -left-6 top-0.5 w-3.5 h-3.5 rounded-full ${dotColor} text-white flex items-center justify-center text-[9px] font-bold shadow-xs`}
                              >
                                {evt.seq}
                              </div>

                              <div className="p-2 rounded-lg bg-slate-50/70 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800/60">
                                <div className="flex items-center justify-between gap-1 flex-wrap">
                                  <div className="flex items-center gap-1.5 font-medium text-slate-800 dark:text-slate-200">
                                    <span>{evt.title}</span>
                                    {evt.event_type?.includes('tool') && (
                                      <Wrench className="w-2.5 h-2.5 text-indigo-500 shrink-0" />
                                    )}
                                  </div>
                                  <div className="flex items-center gap-1.5">
                                    <Badge size="xs" variant={badgeVariant}>
                                      {evt.event_type.replace(/_/g, ' ')}
                                    </Badge>
                                    <span className="text-[10px] text-slate-400 font-mono">
                                      {evt.created_at
                                        ? new Date(evt.created_at).toLocaleTimeString()
                                        : ''}
                                    </span>
                                  </div>
                                </div>

                                <p className="text-slate-600 dark:text-slate-400 text-[11px] mt-1 leading-relaxed">
                                  {evt.description}
                                </p>

                                {/* Per-event Collapsible Payload Drawer */}
                                {hasPayload && (
                                  <div className="mt-1.5 pt-1.5 border-t border-slate-200/50 dark:border-slate-800/50">
                                    <button
                                      type="button"
                                      onClick={() => toggleEventDetail(evt.seq)}
                                      className="inline-flex items-center gap-1 text-[10px] font-mono text-purple-600 dark:text-purple-400 hover:underline"
                                    >
                                      <span>
                                        {isDetailExpanded ? '收起观测明细' : '查看参数与观测明细'}
                                      </span>
                                      <ChevronRight
                                        className={`w-3 h-3 transition-transform ${
                                          isDetailExpanded ? 'rotate-90' : ''
                                        }`}
                                      />
                                    </button>

                                    {isDetailExpanded && (
                                      <div className="mt-1.5 p-2 rounded bg-slate-900 text-slate-200 dark:bg-slate-950 font-mono text-[10px] space-y-1 overflow-x-auto max-h-48 border border-slate-800">
                                        {evt.payload.finding_id && (
                                          <div>
                                            <span className="text-slate-400">对象:</span>{' '}
                                            {typeof evt.payload.finding_id === 'object'
                                              ? JSON.stringify(evt.payload.finding_id)
                                              : String(evt.payload.finding_id)}
                                          </div>
                                        )}
                                        {evt.payload.decision && (
                                          <div>
                                            <span className="text-slate-400">审查决定:</span>{' '}
                                            {typeof evt.payload.decision === 'string'
                                              ? evt.payload.decision
                                              : evt.payload.decision?.integration_summary ||
                                                evt.payload.decision?.action ||
                                                '已生成研判决策'}
                                            {evt.payload.reviewer ? ` (${evt.payload.reviewer})` : ''}
                                          </div>
                                        )}
                                        {evt.payload.violation_codes &&
                                          evt.payload.violation_codes.length > 0 && (
                                            <div className="text-rose-400">
                                              <span className="text-slate-400">拦截约束:</span>{' '}
                                              {evt.payload.violation_codes.join(', ')}
                                            </div>
                                          )}
                                        {evt.payload.item_count != null && (
                                          <div>
                                            <span className="text-slate-400">注意域项数:</span>{' '}
                                            {evt.payload.item_count} (Rev {evt.payload.state_revision})
                                          </div>
                                        )}
                                        {evt.payload.stop_reason && (
                                          <div>
                                            <span className="text-slate-400">收敛原因:</span>{' '}
                                            {typeof evt.payload.stop_reason === 'object'
                                              ? JSON.stringify(evt.payload.stop_reason)
                                              : String(evt.payload.stop_reason)}
                                          </div>
                                        )}
                                        {/* Pretty JSON fallback for full payload */}
                                        <details className="mt-1 pt-1 border-t border-slate-800 text-[9px] text-slate-400">
                                          <summary className="cursor-pointer hover:text-slate-200">
                                            完整 JSON 载荷
                                          </summary>
                                          <pre className="mt-1 whitespace-pre-wrap">
                                            {JSON.stringify(evt.payload, null, 2)}
                                          </pre>
                                        </details>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          /* ═════════════════════════════════════════════════════════════════
             FLAT VIEW: Chronological Stream with Individual Folders
             ═════════════════════════════════════════════════════════════════ */
          <div className="space-y-3 relative before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200 dark:before:bg-slate-800">
            {filteredFlatEvents.map((evt) => {
              const { badgeVariant, dotColor } = getEventStyle(evt);
              const isDetailExpanded = expandedEventDetails.has(evt.seq);
              const hasPayload = evt.payload && Object.keys(evt.payload).length > 0;

              return (
                <div key={evt.event_id || evt.seq} className="relative pl-7">
                  <div
                    className={`absolute left-1.5 top-1 w-3.5 h-3.5 rounded-full ${dotColor} text-white flex items-center justify-center text-[9px] font-bold shadow-xs`}
                  >
                    {evt.seq}
                  </div>
                  <div className="flex items-center justify-between gap-1 flex-wrap">
                    <span className="font-semibold text-slate-800 dark:text-slate-200">
                      {evt.title}
                    </span>
                    <Badge size="xs" variant={badgeVariant}>
                      {evt.event_type.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                  <p className="text-slate-500 dark:text-slate-400 text-[11px] mt-0.5 leading-relaxed">
                    {evt.description}
                  </p>

                  {hasPayload && (
                    <div className="mt-1">
                      <button
                        type="button"
                        onClick={() => toggleEventDetail(evt.seq)}
                        className="inline-flex items-center gap-1 text-[10px] font-mono text-purple-600 dark:text-purple-400 hover:underline"
                      >
                        <span>{isDetailExpanded ? '收起明细' : '展开载荷明细'}</span>
                        <ChevronRight
                          className={`w-3 h-3 transition-transform ${isDetailExpanded ? 'rotate-90' : ''}`}
                        />
                      </button>

                      {isDetailExpanded && (
                        <div className="mt-1 p-2 rounded bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 text-[10px] font-mono text-slate-600 dark:text-slate-400 space-y-0.5">
                          {evt.payload.finding_id && (
                            <div>
                              <span className="text-slate-400">对象:</span>{' '}
                              {typeof evt.payload.finding_id === 'object'
                                ? JSON.stringify(evt.payload.finding_id)
                                : String(evt.payload.finding_id)}
                            </div>
                          )}
                          {evt.payload.decision && (
                            <div>
                              <span className="text-slate-400">审查决定:</span>{' '}
                              {typeof evt.payload.decision === 'string'
                                ? evt.payload.decision
                                : evt.payload.decision?.integration_summary ||
                                  evt.payload.decision?.action ||
                                  '已生成研判决策'}
                              {evt.payload.reviewer ? ` (${evt.payload.reviewer})` : ''}
                            </div>
                          )}
                          {evt.payload.violation_codes && evt.payload.violation_codes.length > 0 && (
                            <div className="text-rose-600 dark:text-rose-400">
                              <span className="text-slate-400">拦截约束:</span>{' '}
                              {evt.payload.violation_codes.join(', ')}
                            </div>
                          )}
                          {evt.payload.item_count != null && (
                            <div>
                              <span className="text-slate-400">注意域项数:</span>{' '}
                              {evt.payload.item_count} (Rev {evt.payload.state_revision})
                            </div>
                          )}
                          {evt.payload.stop_reason && (
                            <div>
                              <span className="text-slate-400">收敛原因:</span>{' '}
                              {typeof evt.payload.stop_reason === 'object'
                                ? JSON.stringify(evt.payload.stop_reason)
                                : String(evt.payload.stop_reason)}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="text-[10px] text-slate-400 mt-0.5 flex items-center gap-1 font-mono">
                    <Clock className="w-2.5 h-2.5" />
                    {evt.created_at ? new Date(evt.created_at).toLocaleTimeString() : ''}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
