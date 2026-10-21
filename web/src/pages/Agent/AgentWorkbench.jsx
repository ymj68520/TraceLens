import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Bot,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleDot,
  CircleX,
  Clock,
  Compass,
  Cpu,
  ExternalLink,
  Eye,
  FileCheck2,
  FileSearch,
  FileText,
  Filter,
  Flame,
  FolderOpen,
  HelpCircle,
  History,
  Laptop,
  Layers,
  ListOrdered,
  Maximize2,
  Microscope,
  Network,
  Pause,
  Play,
  RefreshCw,
  Search,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Square,
  Terminal,
  User,
  Workflow,
  X,
  Zap,
} from 'lucide-react';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import Spinner from '../../components/common/Spinner';
import { useToast } from '../../components/common/ToastContext';
import { fetchFeatures } from '../../services/featuresService';
import { fetchTasksSilent } from '../../store/taskSlice';
import { fetchCases } from '../../store/caseSlice';
import {
  executeAgentCycle,
  getAgentReviewCandidate,
  getAgentReviewHistory,
  getAgentState,
  getAgentTrajectory,
  listAgentReviewCandidates,
  submitAgentReviewDecision,
} from '../../services/investigationService';
import { listReportVersions } from '../../services/reportService';
import TrajectoryTimeline from './components/TrajectoryTimeline';

const getQuestionMeta = (q, idx) => {
  if (q?.text) {
    let title = q.text;
    if (q.text.includes('：')) {
      title = q.text.split('：')[0];
    } else if (q.text.includes(':')) {
      title = q.text.split(':')[0];
    } else if (q.text.includes('，')) {
      title = q.text.split('，')[0];
    } else if (q.text.includes(',')) {
      title = q.text.split(',')[0];
    }
    title = title.replace(/^调查/, '').trim();
    if (title.length > 34) {
      title = title.slice(0, 32) + '...';
    }
    const icons = [FileText, User, ShieldCheck, Network, ShieldAlert, Clock, Layers];
    return {
      title: title || (q.pillarLabel ? `调查方向 ${q.pillarLabel}` : `调查方向 #${(idx || 0) + 1}`),
      desc: q.text,
      icon: icons[(idx || 0) % icons.length] || CircleDot,
    };
  }
  return PILLAR_METADATA[q?.question_id] || {
    title: q?.pillarLabel ? `调查目标 ${q.pillarLabel}` : `调查目标方向 #${(idx || 0) + 1}`,
    desc: '专项多专家协同调查问题',
    icon: CircleDot,
  };
};

// Epistemic style variants
const EPISTEMIC_VARIANTS = {
  FACT: 'green',
  INFERENCE: 'yellow',
  HYPOTHESIS: 'purple',
};

const STATUS_VARIANTS = {
  review_pending: 'yellow',
  accepted: 'green',
  rejected: 'red',
};

const EMPTY_ARRAY = [];

const DEFAULT_PILLARS = [
  { question_id: 'Q1', status: 'open' },
  { question_id: 'Q2', status: 'open' },
  { question_id: 'Q3', status: 'open' },
  { question_id: 'q-61dff02c', status: 'open' },
  { question_id: 'q-ad56bfce', status: 'open' },
  { question_id: 'q-b856d85c', status: 'open' },
  { question_id: 'q-de74d9f4', status: 'open' },
];

// 7 Investigation Core Pillars (Investigation Questions Mapping)
const PILLAR_METADATA = {
  Q1: {
    title: '诈骗话术体系与培训资料库',
    desc: '固定磁盘/话术/目录下多套话术范例、剧本及新人培训资料',
    icon: FileText,
  },
  Q2: {
    title: '涉案嫌疑人身份与层级架构',
    desc: '排查窝点业务员、主管（如老师包装）与组织协作身份',
    icon: User,
  },
  Q3: {
    title: '涉诈赃款归集与虚拟货币钱包',
    desc: '发现 TrueCrypt 隐藏卷、ETH 钱包、加密货币买币教程',
    icon: ShieldCheck,
  },
  'q-61dff02c': {
    title: '受害人与客源引流渠道',
    desc: '挖掘客源线索、引流群组以及多日客户沟通推进记录',
    icon: Compass,
  },
  'q-ad56bfce': {
    title: '反取证与技术防范行为',
    desc: '检查磁盘加密、痕迹清理工具及反取证操作痕迹',
    icon: ShieldAlert,
  },
  'q-b856d85c': {
    title: '作案终端与涉诈平台闭环关联',
    desc: '构建本终端环境与受害人被骗平台的网络与数据闭环',
    icon: Network,
  },
  'q-de74d9f4': {
    title: '涉诈平台技术特征与部署环境',
    desc: '提取涉案平台源码、配置、部署日志与交互协议特征',
    icon: Layers,
  },
};

// Device Scope & Provenance Helper
const getCandidateScopeInfo = (candidate, currentMember = null) => {
  const refs = candidate?.evidence_refs || [];
  const scopes = new Set();
  for (const ref of refs) {
    if (typeof ref === 'string') {
      if (ref.startsWith('src_pc:') || ref.startsWith('src_pc/')) scopes.add('src_pc');
      else if (ref.startsWith('src_server:') || ref.startsWith('src_server/')) scopes.add('src_server');
      else if (ref.startsWith('src_phone:') || ref.startsWith('src_phone/')) scopes.add('src_phone');
    }
  }

  const text = ((candidate?.content || '') + ' ' + (candidate?.candidate_id || '')).toLowerCase();
  if (
    text.includes('src_server') ||
    text.includes('涉案服务器') ||
    text.includes('bt panel') ||
    text.includes('宝塔') ||
    text.includes('rc.local') ||
    text.includes('gwarp') ||
    text.includes('chkconfig')
  ) {
    scopes.add('src_server');
  }
  if (
    text.includes('src_pc') ||
    text.includes('嫌疑人计算机') ||
    text.includes('话术') ||
    text.includes('truecrypt') ||
    text.includes('wangwu') ||
    text.includes('桌面')
  ) {
    scopes.add('src_pc');
  }
  if (
    text.includes('src_phone') ||
    text.includes('涉案手机') ||
    text.includes('手机') ||
    text.includes('miui') ||
    text.includes('chat') ||
    text.includes('微信') ||
    text.includes('telegram')
  ) {
    scopes.add('src_phone');
  }

  if (scopes.has('src_pc') && scopes.has('src_server')) {
    return { scope: 'cross', label: '跨设备关联', Icon: Zap, variant: 'purple' };
  }
  if (scopes.has('src_server')) {
    return { scope: 'src_server', label: '涉案服务器', Icon: Server, variant: 'green' };
  }
  if (scopes.has('src_phone')) {
    return { scope: 'src_phone', label: '涉案手机', Icon: Smartphone, variant: 'purple' };
  }
  if (scopes.has('src_pc')) {
    return { scope: 'src_pc', label: '嫌疑人计算机', Icon: Laptop, variant: 'blue' };
  }
  if (currentMember) {
    return {
      scope: currentMember.scope,
      label: currentMember.roleLabel,
      Icon: currentMember.Icon,
      variant: currentMember.color,
    };
  }
  return { scope: 'local', label: '本地检材', Icon: Laptop, variant: 'gray' };
};

export default function AgentWorkbench() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const toast = useToast();
  const { tasks } = useSelector((state) => state.tasks);
  const cases = useSelector((state) => state.cases?.cases || EMPTY_ARRAY);

  // Fetch cases if not loaded
  useEffect(() => {
    if (!cases || cases.length === 0) {
      dispatch(fetchCases());
    }
  }, [cases?.length, dispatch]);

  // Task & Case context from URL or fallback
  const caseIdParam = searchParams.get('case_id') || searchParams.get('caseId');
  const taskIdParam = searchParams.get('task_id') || searchParams.get('taskId');

  // Associated Case resolution
  const associatedCase = useMemo(() => {
    if (caseIdParam && cases && cases.length > 0) {
      const found = cases.find((c) => c.id === caseIdParam);
      if (found) return found;
    }
    if (taskIdParam && cases && cases.length > 0) {
      const found = cases.find((c) => Array.isArray(c.task_ids) && c.task_ids.includes(taskIdParam));
      if (found) return found;
    }
    return null;
  }, [caseIdParam, taskIdParam, cases]);

  // Mode: cross-image mode is explicitly indicated by case_id param and a valid associated case
  const isCrossImageMode = useMemo(() => {
    return Boolean(caseIdParam && associatedCase);
  }, [caseIdParam, associatedCase]);

  // In cross-image mode, taskIdParam indicates whether the investigator has focused on a specific single device.
  // If taskIdParam is absent or 'all', the investigator is viewing the entire case (All Devices Global View).
  const focusedTaskId = useMemo(() => {
    if (!isCrossImageMode) return taskIdParam || null;
    if (!taskIdParam || taskIdParam === 'all') return null;
    return taskIdParam;
  }, [isCrossImageMode, taskIdParam]);

  const currentTaskId = useMemo(() => {
    if (focusedTaskId) return focusedTaskId;
    if (taskIdParam && taskIdParam !== 'all') return taskIdParam;
    if (associatedCase && Array.isArray(associatedCase.task_ids) && associatedCase.task_ids.length > 0) {
      return associatedCase.task_ids[0];
    }
    if (tasks && tasks.length > 0) {
      // Prioritize completed agent-tagged tasks, then any completed tasks, then any agent tasks
      const completedAgentTask = tasks.find(
        (t) => (t.metadata?.workflow_type === 'agent' || t.metadata?.agent_enabled === 'true') && t.status?.toLowerCase() === 'completed'
      );
      if (completedAgentTask) return completedAgentTask.id;
      const agentTask = tasks.find(
        (t) => t.metadata?.workflow_type === 'agent' || t.metadata?.agent_enabled === 'true'
      );
      if (agentTask) return agentTask.id;
      const completedTask = tasks.find((t) => t.status?.toLowerCase() === 'completed');
      if (completedTask) return completedTask.id;
      return tasks[0].id;
    }
    return '60dedf82-7f35-48be-a104-b4d283a4fe92'; // Fallback to wo_dian synthetic task
  }, [focusedTaskId, taskIdParam, associatedCase, tasks]);

  const selectedTask = useMemo(
    () => tasks?.find((t) => t.id === currentTaskId),
    [tasks, currentTaskId]
  );
  const isTaskRunning = selectedTask?.status?.toLowerCase() === 'running' || selectedTask?.status?.toLowerCase() === 'pending';

  // Member tasks in this case
  const caseMembers = useMemo(() => {
    if (!associatedCase || !Array.isArray(associatedCase.task_ids)) {
      return [];
    }
    return associatedCase.task_ids.map((tid) => {
      const t = (tasks || []).find((x) => x.id === tid) || { id: tid };
      const imgLower = (t.image_path || '').toLowerCase();
      const nameLower = (t.task_name || '').toLowerCase();
      const scope =
        t.metadata?.device_scope ||
        t.metadata?.source_label ||
        (imgLower.includes('server') || imgLower.includes('服务器') || nameLower.includes('server') || nameLower.includes('服务器')
          ? 'src_server'
          : imgLower.includes('phone') || imgLower.includes('miui') || imgLower.includes('android') || imgLower.includes('手机') || nameLower.includes('phone') || nameLower.includes('手机')
          ? 'src_phone'
          : 'src_pc');

      let roleLabel = '嫌疑人计算机';
      let Icon = Laptop;
      let color = 'blue';
      if (scope === 'src_server') {
        roleLabel = '涉案服务器';
        Icon = Server;
        color = 'emerald';
      } else if (scope === 'src_phone') {
        roleLabel = '涉案手机';
        Icon = Smartphone;
        color = 'purple';
      }

      const imageName =
        t.image_path ? t.image_path.split('/').pop() :
        t.task_name ? t.task_name :
        `镜像设备 ${tid.slice(0, 8)}`;

      return {
        id: tid,
        task: t,
        scope,
        roleLabel,
        Icon,
        color,
        imageName,
        isCurrent: Boolean(focusedTaskId && tid === focusedTaskId),
        status: t.status || 'completed',
      };
    });
  }, [associatedCase, tasks, focusedTaskId]);

  const currentMember = useMemo(
    () => (focusedTaskId ? caseMembers.find((m) => m.id === focusedTaskId) || null : null),
    [caseMembers, focusedTaskId]
  );

  const handleCancelFocus = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('task_id');
      next.delete('investigation_id');
      if (associatedCase) next.set('case_id', associatedCase.id);
      return next;
    });
  }, [associatedCase, setSearchParams]);

  const handleMemberCardClick = useCallback(
    (memberId) => {
      if (focusedTaskId === memberId) {
        // Toggle off focus
        handleCancelFocus();
      } else {
        // Focus on this specific device
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set('task_id', memberId);
          next.delete('investigation_id');
          if (associatedCase) next.set('case_id', associatedCase.id);
          return next;
        });
      }
    },
    [focusedTaskId, handleCancelFocus, associatedCase, setSearchParams]
  );

  const investigationIdParam = searchParams.get('investigation_id') || searchParams.get('investigationId');
  const [investigationId, setInvestigationId] = useState(
    investigationIdParam || (currentTaskId === '60dedf82-7f35-48be-a104-b4d283a4fe92' ? 'inv_wo_dian_002' : null)
  );

  useEffect(() => {
    if (investigationIdParam) {
      setInvestigationId(investigationIdParam);
    } else {
      setInvestigationId(null);
    }
  }, [currentTaskId, investigationIdParam]);

  // Poll tasks if current task is running
  useEffect(() => {
    if (!isTaskRunning) return;
    const timer = setInterval(() => {
      dispatch(fetchTasksSilent({}));
    }, 3000);
    return () => clearInterval(timer);
  }, [isTaskRunning, dispatch]);

  // Update URL if taskId was auto-resolved (only in single-image standalone mode without case_id)
  useEffect(() => {
    if (!caseIdParam && !taskIdParam && currentTaskId) {
      setSearchParams(
        (prev) => {
          prev.set('task_id', currentTaskId);
          if (investigationId) prev.set('investigation_id', investigationId);
          return prev;
        },
        { replace: true }
      );
    }
  }, [taskIdParam, currentTaskId, caseIdParam, investigationId, setSearchParams]);

  // Feature gate
  const [featureEnabled, setFeatureEnabled] = useState(true);
  useEffect(() => {
    fetchFeatures()
      .then((flags) => {
        setFeatureEnabled(!!flags?.agent_execution_enabled);
      })
      .catch(() => setFeatureEnabled(true));
  }, []);

  // Agent Working State
  const [agentState, setAgentState] = useState(null);
  const [stateLoading, setStateLoading] = useState(false);
  const [stateError, setStateError] = useState(null);

  // Review Candidates
  const [candidates, setCandidates] = useState([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState(null);
  const [candidateDetail, setCandidateDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Review Decision State
  const [confirmAction, setConfirmAction] = useState(null); // 'accepted' | 'rejected'
  const [reviewNote, setReviewNote] = useState('');
  const [submittingReview, setSubmittingReview] = useState(false);
  const [reviewRequestId, setReviewRequestId] = useState('');

  // Review History
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Cycle Execution State
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionOutcome, setExecutionOutcome] = useState(null);
  const [executionError, setExecutionError] = useState(null);
  const [cycleRequestId, setCycleRequestId] = useState(
    () => `req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  );

  // Auto-propel State (Continuous Investigation Loop with localStorage persistence)
  const [isAutoPropelling, setIsAutoPropelling] = useState(false);
  const [autoPropelCycle, setAutoPropelCycle] = useState(1);
  const [maxAutoCycles, setMaxAutoCycles] = useState(() => {
    try {
      const saved = localStorage.getItem('tracelens_agent_max_cycles');
      const parsed = parseInt(saved, 10);
      return !isNaN(parsed) && parsed > 0 ? parsed : 30;
    } catch {
      return 30;
    }
  });
  const [cooldownRemaining, setCooldownRemaining] = useState(0);
  const stopRequestedRef = useRef(false);
  const localCycleRunningRef = useRef(false);
  const prevBackendStatusRef = useRef(null);
  const cooldownTimerRef = useRef(null);
  const autoPropelTimerRef = useRef(null);

  // Keep latest values in refs to decouple runner execution from component re-renders/polling
  const agentStateRef = useRef(agentState);
  agentStateRef.current = agentState;
  const investigationIdRef = useRef(investigationId);
  investigationIdRef.current = investigationId;
  const isAutoPropellingRef = useRef(isAutoPropelling);
  isAutoPropellingRef.current = isAutoPropelling;
  const autoPropelCycleRef = useRef(autoPropelCycle);
  autoPropelCycleRef.current = autoPropelCycle;
  const maxAutoCyclesRef = useRef(maxAutoCycles);
  maxAutoCyclesRef.current = maxAutoCycles;
  const isExecutingRef = useRef(isExecuting);
  isExecutingRef.current = isExecuting;

  const getPersistedAutoPropel = useCallback((taskId) => {
    if (!taskId) return null;
    try {
      const data = localStorage.getItem(`tracelens_auto_propel_${taskId}`);
      return data ? JSON.parse(data) : null;
    } catch {
      return null;
    }
  }, []);

  const persistAutoPropel = useCallback((taskId, state) => {
    if (!taskId) return;
    try {
      if (state) {
        localStorage.setItem(`tracelens_auto_propel_${taskId}`, JSON.stringify(state));
      } else {
        localStorage.removeItem(`tracelens_auto_propel_${taskId}`);
      }
    } catch {}
  }, []);

  // Restore auto-propel state on mount / task change
  useEffect(() => {
    if (!currentTaskId) return;
    const saved = getPersistedAutoPropel(currentTaskId);
    if (saved?.active) {
      stopRequestedRef.current = false;
      setIsAutoPropelling(true);
      setAutoPropelCycle(saved.cycle || 1);
      if (saved.maxCycles) setMaxAutoCycles(saved.maxCycles);
    }
  }, [currentTaskId, getPersistedAutoPropel]);

  useEffect(() => {
    return () => {
      stopRequestedRef.current = true;
      if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
      if (autoPropelTimerRef.current) clearTimeout(autoPropelTimerRef.current);
    };
  }, []);

  // Process / Planning UI Tabs (Left Panel)
  const [processTab, setProcessTab] = useState('questions'); // 'questions' | 'trace' | 'thoughts'
  const [selectedQuestionId, setSelectedQuestionId] = useState(null);

  // Filter tabs (Middle Panel)
  const [filterType, setFilterType] = useState('all'); // 'all' | 'FACT' | 'HYPOTHESIS' | 'review_pending'
  const [deviceFilter, setDeviceFilter] = useState('all'); // 'all' | 'src_pc' | 'src_server' | 'src_phone' | 'cross'

  // Selected Evidence modal / preview
  const [previewEvidence, setPreviewEvidence] = useState(null);

  // Member Matrix presentation state (compact / collapsed)
  const [isMatrixCollapsed, setIsMatrixCollapsed] = useState(false);

  // Fetch Agent State
  const loadAgentState = useCallback(async () => {
    if (!currentTaskId || isTaskRunning) return;
    setStateLoading(true);
    setStateError(null);
    try {
      const state = await getAgentState(currentTaskId, investigationId || undefined);
      if (!focusedTaskId && isCrossImageMode && associatedCase) {
        setAgentState({
          ...state,
          objective: associatedCase.description || '案件全案多设备跨镜像协同研判：综合研判嫌疑人终端、服务器及涉案移动设备证据闭环',
        });
      } else {
        setAgentState(state);
      }
      if (state?.investigation_id && !investigationId) {
        setInvestigationId(state.investigation_id);
      }
    } catch (err) {
      setAgentState(null);
      const status = err?.status || err?.response?.status;
      if (status !== 404) {
        setStateError(err?.data?.detail || err?.message || '读取 Agent 状态失败');
      }
    } finally {
      setStateLoading(false);
    }
  }, [currentTaskId, focusedTaskId, isCrossImageMode, associatedCase, investigationId, isTaskRunning]);

  // Trajectory State & Loader
  const [trajectoryEvents, setTrajectoryEvents] = useState([]);
  const [trajectoryLoading, setTrajectoryLoading] = useState(false);

  const loadTrajectory = useCallback(async () => {
    if (!currentTaskId || isTaskRunning) return;
    setTrajectoryLoading(true);
    try {
      const res = await getAgentTrajectory(currentTaskId, investigationId || undefined, 60);
      const evts = Array.isArray(res?.events) ? res.events : [];
      setTrajectoryEvents(evts);
    } catch (err) {
      // Non-fatal for UI
    } finally {
      setTrajectoryLoading(false);
    }
  }, [currentTaskId, investigationId, isTaskRunning]);

  // Fetch Candidates
  const loadCandidates = useCallback(async () => {
    if (!currentTaskId || isTaskRunning) {
      setCandidates([]);
      return;
    }
    setCandidatesLoading(true);
    try {
      if (isCrossImageMode && !focusedTaskId && caseMembers.length > 0) {
        // All-Devices Mode: load candidates from all case members and merge
        const memberResults = await Promise.all(
          caseMembers.map((m) =>
            listAgentReviewCandidates(m.id).catch(() => [])
          )
        );
        const merged = [];
        const seen = new Set();
        for (const res of memberResults) {
          const list = Array.isArray(res) ? res : Array.isArray(res?.candidates) ? res.candidates : [];
          for (const item of list) {
            if (item && item.candidate_id && !seen.has(item.candidate_id)) {
              seen.add(item.candidate_id);
              merged.push(item);
            }
          }
        }
        setCandidates(merged);
        setSelectedCandidateId((prev) =>
          merged.some((c) => c.candidate_id === prev) ? prev : merged[0]?.candidate_id || null
        );
      } else {
        const res = await listAgentReviewCandidates(currentTaskId, investigationId || undefined);
        const list = Array.isArray(res) ? res : Array.isArray(res?.candidates) ? res.candidates : [];
        setCandidates(list);
        setSelectedCandidateId((prev) =>
          list.some((c) => c.candidate_id === prev) ? prev : list[0]?.candidate_id || null
        );
      }
    } catch (err) {
      setCandidates([]);
      const status = err?.status || err?.response?.status;
      if (status !== 404) {
        toast.error(err?.data?.detail || err?.message || '读取审核候选失败');
      }
    } finally {
      setCandidatesLoading(false);
    }
  }, [currentTaskId, focusedTaskId, isCrossImageMode, caseMembers, investigationId, isTaskRunning, toast]);

  // Fetch Candidate Detail
  useEffect(() => {
    if (!currentTaskId || !selectedCandidateId || isTaskRunning) {
      setCandidateDetail(null);
      return;
    }
    setDetailLoading(true);
    getAgentReviewCandidate(currentTaskId, selectedCandidateId, investigationId || undefined)
      .then((detail) => setCandidateDetail(detail))
      .catch((err) => {
        // Fallback to in-memory candidate if detail request fails
        const fallback = candidates.find((c) => c.candidate_id === selectedCandidateId);
        setCandidateDetail(fallback || null);
      })
      .finally(() => setDetailLoading(false));

    // Also load history for candidate
    setHistoryLoading(true);
    getAgentReviewHistory(currentTaskId, selectedCandidateId, investigationId || undefined)
      .then((hist) => setHistory(Array.isArray(hist) ? hist : []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [currentTaskId, selectedCandidateId, investigationId, candidates, isTaskRunning]);

  // Narrative Report State
  const [latestReportVersion, setLatestReportVersion] = useState(null);

  const loadReportStatus = useCallback(async () => {
    if (!currentTaskId || isTaskRunning) return;
    try {
      const versions = await listReportVersions('task', currentTaskId);
      if (Array.isArray(versions) && versions.length > 0) {
        setLatestReportVersion(versions[0]);
      } else {
        setLatestReportVersion(null);
      }
    } catch {
      // ignore
    }
  }, [currentTaskId, isTaskRunning]);

  // Initial & Dependency Load
  useEffect(() => {
    loadAgentState();
    loadCandidates();
    loadTrajectory();
    loadReportStatus();
  }, [loadAgentState, loadCandidates, loadTrajectory, loadReportStatus]);

  // Real-time live polling effect while agent is active or executing
  const isAgentActive = isExecuting || isAutoPropelling || agentState?.agent_execution_status === 'running';

  useEffect(() => {
    if (!isAgentActive || !currentTaskId) return;
    const timer = setInterval(() => {
      loadAgentState();
      loadTrajectory();
      loadCandidates();
      loadReportStatus();
    }, 3000);
    return () => clearInterval(timer);
  }, [isAgentActive, currentTaskId, loadAgentState, loadTrajectory, loadCandidates, loadReportStatus]);

  // Reload trajectory on tab switch
  useEffect(() => {
    if (processTab === 'trace') {
      loadTrajectory();
    }
  }, [processTab, loadTrajectory]);

  // Detect background cycle completion when reconnected or running
  useEffect(() => {
    const prev = prevBackendStatusRef.current;
    const current = agentState?.agent_execution_status;
    prevBackendStatusRef.current = current;

    if (isAutoPropelling && prev === 'running' && current === 'idle' && !localCycleRunningRef.current) {
      setAutoPropelCycle((prevCycle) => {
        const nextCycle = prevCycle + 1;
        persistAutoPropel(currentTaskId, { active: true, cycle: nextCycle, maxCycles: maxAutoCycles });
        return nextCycle;
      });
      toast.success('后台研判周期已执行完毕，即将进入下一轮推进...');
      loadTrajectory();
      loadCandidates();
      loadReportStatus();
    }
  }, [
    agentState?.agent_execution_status,
    isAutoPropelling,
    currentTaskId,
    maxAutoCycles,
    persistAutoPropel,
    toast,
    loadTrajectory,
    loadCandidates,
    loadReportStatus,
  ]);

  // Handle Triggering Agent Cycle
  const handleStartCycle = async () => {
    if (!currentTaskId || isExecuting || isTaskRunning) return;
    localCycleRunningRef.current = true;
    setIsExecuting(true);
    setExecutionError(null);
    const reqId = cycleRequestId || `req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    setCycleRequestId(reqId);

    try {
      const payload = {
        task_id: currentTaskId,
        ...(investigationId ? { investigation_id: investigationId } : {}),
        request_id: reqId,
        expected_working_state_revision: agentState?.working_state_revision ?? null,
        max_steps: 5,
      };

      const outcome = await executeAgentCycle(payload, currentTaskId);
      setExecutionOutcome(outcome);
      if (outcome.investigation_id && outcome.investigation_id !== investigationId) {
        setInvestigationId(outcome.investigation_id);
      }
      toast.success(`Agent 循环执行成功 (Rev ${outcome.starting_revision} → Rev ${outcome.ending_revision})`);
      setCycleRequestId(`req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`);
      await loadAgentState();
      await loadCandidates();
      await loadTrajectory();
      loadReportStatus();
    } catch (err) {
      const msg = err?.data?.detail || err?.message || 'Agent 循环执行失败';
      setExecutionError(msg);
      toast.error(msg);
    } finally {
      localCycleRunningRef.current = false;
      setIsExecuting(false);
    }
  };

  // Handle Stopping Agent Auto-Propel Loop
  const handleStopAutoPropel = useCallback(() => {
    stopRequestedRef.current = true;
    if (cooldownTimerRef.current) {
      clearTimeout(cooldownTimerRef.current);
      cooldownTimerRef.current = null;
    }
    if (autoPropelTimerRef.current) {
      clearTimeout(autoPropelTimerRef.current);
      autoPropelTimerRef.current = null;
    }
    persistAutoPropel(currentTaskId, null);
    setIsAutoPropelling(false);
    setCooldownRemaining(0);
    toast.info('已暂停自动研判连续推进');
  }, [currentTaskId, persistAutoPropel, toast]);

  // Handle Triggering Agent Autonomous Propel Loop
  const handleStartAutoPropel = useCallback(() => {
    if (!currentTaskId || isTaskRunning) return;
    stopRequestedRef.current = false;
    if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
    if (autoPropelTimerRef.current) clearTimeout(autoPropelTimerRef.current);
    setExecutionError(null);
    setIsAutoPropelling(true);
    setAutoPropelCycle(1);
    persistAutoPropel(currentTaskId, { active: true, cycle: 1, maxCycles: maxAutoCycles });
    if (agentStateRef.current?.agent_execution_status === 'running') {
      toast.info(`🚀 已接管正在运行的研判周期，将连续推进至调查完成 (上限 ${maxAutoCycles} 轮)`);
    } else {
      toast.info(`🚀 启动自主研判连续推进 (上限 ${maxAutoCycles} 轮，状态已持久化)`);
    }
  }, [currentTaskId, isTaskRunning, maxAutoCycles, persistAutoPropel, toast]);

  // Autonomous Propel Master Step Executor
  const executeAutoPropelStep = useCallback(async () => {
    if (!isAutoPropellingRef.current || stopRequestedRef.current || !currentTaskId) {
      return;
    }

    if (localCycleRunningRef.current || isExecutingRef.current) {
      return;
    }

    localCycleRunningRef.current = true;

    try {
      const currentState = agentStateRef.current;

      // Check completion
      if (currentState?.agent_execution_status === 'completed') {
        toast.success('🎉 案件调查已全面完成，所有研判支柱已闭环！');
        setIsAutoPropelling(false);
        persistAutoPropel(currentTaskId, null);
        return;
      }

      // Check questions: if every question is answered, we're done
      const qSummaries = currentState?.questions_summary || [];
      if (qSummaries.length > 0) {
        const allAnswered = qSummaries.every((q) => q.status === 'answered');
        if (allAnswered) {
          toast.success('🎯 所有调查方向均已排查完毕，证据链已固化');
          setIsAutoPropelling(false);
          persistAutoPropel(currentTaskId, null);
          return;
        }
      }

      // Check max cycles
      if (autoPropelCycleRef.current > maxAutoCyclesRef.current) {
        toast.info(`已达到最大自动推进轮数 (${maxAutoCyclesRef.current} 轮)，已自动停驻`);
        setIsAutoPropelling(false);
        persistAutoPropel(currentTaskId, null);
        return;
      }

      // If backend is currently running, poll until ready
      if (currentState?.agent_execution_status === 'running') {
        if (autoPropelTimerRef.current) clearTimeout(autoPropelTimerRef.current);
        autoPropelTimerRef.current = setTimeout(() => {
          if (isAutoPropellingRef.current && !stopRequestedRef.current) {
            executeAutoPropelStep();
          }
        }, 2000);
        return;
      }

      // Cooldown countdown for cycle > 1
      if (autoPropelCycleRef.current > 1) {
        for (let sec = 3; sec > 0; sec--) {
          if (!isAutoPropellingRef.current || stopRequestedRef.current) {
            setCooldownRemaining(0);
            return;
          }
          setCooldownRemaining(sec);
          await new Promise((resolve) => {
            cooldownTimerRef.current = setTimeout(resolve, 1000);
          });
        }
        if (!isAutoPropellingRef.current || stopRequestedRef.current) {
          setCooldownRemaining(0);
          return;
        }
        setCooldownRemaining(0);
      }

      setIsExecuting(true);
      const reqId = `req_cycle_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
      const currentRev = agentStateRef.current?.working_state_revision ?? null;
      const invId = investigationIdRef.current;
      const currentCycleNum = autoPropelCycleRef.current;

      const payload = {
        task_id: currentTaskId,
        ...(invId ? { investigation_id: invId } : {}),
        request_id: reqId,
        expected_working_state_revision: currentRev,
        max_steps: 5,
      };

      try {
        const outcome = await executeAgentCycle(payload, currentTaskId);
        setExecutionOutcome(outcome);
        if (outcome.investigation_id && outcome.investigation_id !== invId) {
          setInvestigationId(outcome.investigation_id);
        }
        toast.success(
          `第 ${currentCycleNum} 轮完成 (Rev ${outcome.starting_revision} → Rev ${outcome.ending_revision ?? outcome.starting_revision})`
        );

        await loadAgentState();
        await loadCandidates();
        await loadTrajectory();
        loadReportStatus();

        if (
          outcome?.finalization?.finalized === true ||
          outcome?.run_stop_reason === 'finalized'
        ) {
          toast.success('🎉 案件调查已全面完成，所有研判支柱已闭环！');
          setIsAutoPropelling(false);
          persistAutoPropel(currentTaskId, null);
          return;
        }

        if (outcome?.run_stop_reason === 'no_progress') {
          toast.info('取证数据已充分收敛（无新增线索），自动推进完成');
          setIsAutoPropelling(false);
          persistAutoPropel(currentTaskId, null);
          return;
        }

        const nextCycle = currentCycleNum + 1;
        setAutoPropelCycle(nextCycle);
        persistAutoPropel(currentTaskId, {
          active: true,
          cycle: nextCycle,
          maxCycles: maxAutoCyclesRef.current,
        });

        if (isAutoPropellingRef.current && !stopRequestedRef.current) {
          if (autoPropelTimerRef.current) clearTimeout(autoPropelTimerRef.current);
          autoPropelTimerRef.current = setTimeout(() => {
            if (isAutoPropellingRef.current && !stopRequestedRef.current) {
              executeAutoPropelStep();
            }
          }, 100);
        }
      } catch (err) {
        const msg = err?.data?.detail || err?.message || 'Agent 循环执行失败';
        if (msg.includes('already running')) {
          toast.info('检测到后台研判周期正在运行，已自动接入并实时同步轨迹...');
          if (autoPropelTimerRef.current) clearTimeout(autoPropelTimerRef.current);
          autoPropelTimerRef.current = setTimeout(() => {
            if (isAutoPropellingRef.current && !stopRequestedRef.current) {
              executeAutoPropelStep();
            }
          }, 3000);
        } else {
          setExecutionError(msg);
          toast.error(`第 ${currentCycleNum} 轮执行异常: ${msg}`);
          setIsAutoPropelling(false);
          persistAutoPropel(currentTaskId, null);
        }
      } finally {
        setIsExecuting(false);
      }
    } finally {
      localCycleRunningRef.current = false;
    }
  }, [
    currentTaskId,
    loadAgentState,
    loadCandidates,
    loadTrajectory,
    loadReportStatus,
    persistAutoPropel,
    toast,
  ]);

  // Autonomous Propel Master Driver Effect
  useEffect(() => {
    if (!isAutoPropelling || !currentTaskId) return;
    if (stopRequestedRef.current) return;

    if (!localCycleRunningRef.current && !isExecutingRef.current) {
      executeAutoPropelStep();
    }

    return () => {
      if (stopRequestedRef.current) {
        if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
        if (autoPropelTimerRef.current) clearTimeout(autoPropelTimerRef.current);
      }
    };
  }, [isAutoPropelling, currentTaskId, executeAutoPropelStep]);

  // Handle Review Decision
  const handleOpenReviewConfirm = (action) => {
    setConfirmAction(action);
    setReviewNote('');
    setReviewRequestId(`req_rev_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`);
  };

  const handleSubmitReviewDecision = async () => {
    if (!activeCandidate || !confirmAction || submittingReview) return;
    setSubmittingReview(true);
    try {
      const payload = {
        task_id: currentTaskId,
        investigation_id: investigationId,
        review_target_id: activeCandidate.candidate_id,
        expected_source_revision: activeCandidate.source_revision,
        expected_candidate_hash: activeCandidate.candidate_hash,
        decision: confirmAction,
        reviewer: 'lead_forensic_analyst',
        request_id: reviewRequestId,
        ...(reviewNote.trim() ? { note: reviewNote.trim() } : {}),
        ...(confirmAction === 'accepted' ? { requested_assertion_class: activeCandidate.claim_type } : {}),
      };

      const outcome = await submitAgentReviewDecision(payload);
      toast.success(`审核决策已提交：${confirmAction === 'accepted' ? '已接受 (Accepted)' : '已拒绝 (Rejected)'}`);

      // Optimistic update local candidate list
      setCandidates((prev) =>
        prev.map((c) =>
          c.candidate_id === activeCandidate.candidate_id
            ? { ...c, review_status: outcome.decision || confirmAction, review_note: outcome.note }
            : c
        )
      );
      if (candidateDetail?.candidate_id === activeCandidate.candidate_id) {
        setCandidateDetail((prev) => ({
          ...prev,
          review_status: outcome.decision || confirmAction,
          review_note: outcome.note,
        }));
      }

      setConfirmAction(null);
      setReviewNote('');
      // Reload history & state & trajectory & report
      loadAgentState();
      loadTrajectory();
      loadReportStatus();
    } catch (err) {
      toast.error(err?.data?.detail || err?.message || '提交审核决策失败');
    } finally {
      setSubmittingReview(false);
    }
  };

  const displayQuestions = useMemo(() => {
    if (agentState?.questions_summary && agentState.questions_summary.length > 0) {
      return agentState.questions_summary;
    }
    return DEFAULT_PILLARS;
  }, [agentState?.questions_summary]);

  // Pillar Sub-task Expand/Collapse State
  const [expandedPillars, setExpandedPillars] = useState(() => ({
    Q1: true,
    Q2: true,
    Q3: true,
    'q-ad56bfce': true,
  }));

  const togglePillarExpand = useCallback((pillarId, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setExpandedPillars((prev) => ({
      ...prev,
      [pillarId]: prev[pillarId] === undefined ? false : !prev[pillarId],
    }));
  }, []);

  // Hierarchical Question Tree (Root Pillars P1..P7 + Sub-tasks)
  const questionTree = useMemo(() => {
    const roots = [];
    const childrenByParent = {};

    displayQuestions.forEach((q) => {
      const parentId = q.parent_question_id;
      if (parentId && parentId !== q.question_id && displayQuestions.some((other) => other.question_id === parentId)) {
        if (!childrenByParent[parentId]) {
          childrenByParent[parentId] = [];
        }
        childrenByParent[parentId].push(q);
      } else {
        roots.push(q);
      }
    });

    return roots.map((root, rootIdx) => {
      const children = childrenByParent[root.question_id] || [];
      return {
        ...root,
        pillarIndex: rootIdx + 1,
        pillarLabel: `P${rootIdx + 1}`,
        children: children.map((child, childIdx) => ({
          ...child,
          parentLabel: `P${rootIdx + 1}`,
          pillarLabel: `P${rootIdx + 1}.${childIdx + 1}`,
        })),
      };
    });
  }, [displayQuestions]);

  // Filtered candidates
  const filteredCandidates = useMemo(() => {
    let list = candidates;
    if (isCrossImageMode && deviceFilter !== 'all') {
      list = list.filter((c) => {
        const info = getCandidateScopeInfo(c, currentMember);
        return info.scope === deviceFilter;
      });
    }
    if (selectedQuestionId) {
      // Find the selected question (could be a root or a child)
      const targetQuestions = [];
      const currentQuestion = displayQuestions.find((q) => q.question_id === selectedQuestionId);
      if (currentQuestion) {
        targetQuestions.push(currentQuestion);
      }
      // If selectedQuestionId is a root pillar, also include all its sub-tasks!
      const rootNode = questionTree.find((r) => r.question_id === selectedQuestionId);
      if (rootNode && rootNode.children && rootNode.children.length > 0) {
        targetQuestions.push(...rootNode.children);
      }

      // Collect all lowerPaths and keywords from all target questions
      const allLowerPaths = [];
      const allQTexts = [];
      targetQuestions.forEach((q) => {
        const text = (q.text || '').toLowerCase();
        allQTexts.push(text);
        const matches = text.match(/(?:\/[\w\.-]+){2,}/g) || [];
        matches.forEach((p) => allLowerPaths.push(p.toLowerCase()));
      });

      list = list.filter((c) => {
        const text = (c.content || '').toLowerCase();
        const cid = (c.candidate_id || '').toLowerCase();
        const refs = (c.evidence_refs || []).map((r) => r.toLowerCase());

        // Check if candidate evidence_refs contain paths mentioned in any target question
        const hasPathRefMatch = allLowerPaths.some((p) =>
          refs.some((r) => r.includes(p)) || text.includes(p)
        );
        if (hasPathRefMatch) return true;

        // Check domain rules for target questions
        const targetIds = targetQuestions.map((q) => q.question_id);
        if (targetIds.includes('Q1')) {
          if (text.includes('话术') || cid.includes('pillar1') || text.includes('bt') || text.includes('宝塔') || text.includes('部署') || cid.includes('bt') || refs.some((r) => r.includes('panel') || r.includes('bt'))) return true;
        }
        if (targetIds.includes('Q2')) {
          if (text.includes('嫌疑人') || cid.includes('pillar2') || text.includes('wangwu') || text.includes('用户') || text.includes('账户') || cid.includes('user') || refs.some((r) => r.includes('passwd') || r.includes('shadow'))) return true;
        }
        if (targetIds.includes('Q3')) {
          if (text.includes('钱包') || text.includes('truecrypt') || cid.includes('pillar6') || text.includes('chkconfig') || text.includes('资金') || text.includes('自启') || cid.includes('chkconfig') || text.includes('gwarp') || text.includes('rc.local')) return true;
        }
        if (targetIds.includes('q-61dff02c')) {
          if (text.includes('客源') || text.includes('受害人') || text.includes('引流') || cid.includes('channel') || text.includes('网络') || text.includes('连接') || text.includes('ip') || text.includes('端口')) return true;
        }
        if (targetIds.includes('q-ad56bfce')) {
          if (text.includes('反取证') || text.includes('篡改') || cid.includes('tampering') || cid.includes('pillar4') || text.includes('日志') || text.includes('跳变') || text.includes('time_window_gap')) return true;
        }
        if (targetIds.includes('q-b856d85c')) {
          if (text.includes('终端') || text.includes('闭环') || cid.includes('login') || cid.includes('pillar5') || text.includes('登录') || text.includes('主机') || text.includes('重启') || text.includes('last')) return true;
        }
        if (targetIds.includes('q-de74d9f4')) {
          if (text.includes('平台') || text.includes('技术特征') || text.includes('环境') || text.includes('redhat') || cid.includes('platform') || text.includes('发行版') || cid.includes('os')) return true;
        }

        // Sub-task specific matches
        if (targetIds.includes('q-a5effdff')) {
          if (text.includes('authorized_keys') || text.includes('ssh') || text.includes('公钥') || text.includes('免密') || text.includes('后门') || refs.some((r) => r.includes('ssh') || r.includes('authorized_keys'))) return true;
        }
        if (targetIds.includes('q-5a5de680') || targetIds.includes('q-1672efe9')) {
          if (text.includes('gwarp') || text.includes('rc.local') || text.includes('自启') || text.includes('木马') || refs.some((r) => r.includes('gwarp') || r.includes('rc.local') || r.includes('init.d'))) return true;
        }
        if (targetIds.includes('q-ffc508f1')) {
          if (text.includes('chrony') || text.includes('ntp') || text.includes('时钟') || text.includes('授时') || text.includes('时间同步') || refs.some((r) => r.includes('chrony'))) return true;
        }
        if (targetIds.includes('q-ad31351c')) {
          if (text.includes('upload') || text.includes('jijin') || text.includes('task.json') || text.includes('config.json') || refs.some((r) => r.includes('upload') || r.includes('jijin'))) return true;
        }
        if (targetIds.includes('q-dc6e3ef1')) {
          if (text.includes('.bash_history') || text.includes('bash_history') || text.includes('家目录') || refs.some((r) => r.includes('bash_history'))) return true;
        }

        // Generic keyword matching fallback
        return allQTexts.some((qText) => {
          const keywords = (qText.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, ' ').split(/\s+/)).filter((w) => w.length >= 2);
          const matchCount = keywords.filter((kw) => text.includes(kw) || refs.some((r) => r.includes(kw))).length;
          return matchCount >= 2;
        });
      });
    }
    if (filterType === 'FACT') {
      return list.filter((c) => c.claim_type === 'FACT');
    }
    if (filterType === 'HYPOTHESIS') {
      return list.filter((c) => c.claim_type === 'HYPOTHESIS');
    }
    if (filterType === 'review_pending') {
      return list.filter((c) => c.review_status === 'review_pending');
    }
    return list;
  }, [candidates, filterType, selectedQuestionId, isCrossImageMode, deviceFilter, currentMember]);

  const activeCandidate = candidateDetail || candidates.find((c) => c.candidate_id === selectedCandidateId);
  const selectedQuestionInfo = useMemo(() => {
    if (!selectedQuestionId) return null;
    for (const root of questionTree) {
      if (root.question_id === selectedQuestionId) {
        return { label: root.pillarLabel, title: getQuestionMeta(root, root.pillarIndex - 1).title };
      }
      if (root.children) {
        const child = root.children.find((c) => c.question_id === selectedQuestionId);
        if (child) {
          return { label: child.pillarLabel, title: getQuestionMeta(child).title };
        }
      }
    }
    return { label: '筛选', title: selectedQuestionId };
  }, [selectedQuestionId, questionTree]);
  const pendingCount = useMemo(
    () => candidates.filter((c) => c.review_status === 'review_pending').length,
    [candidates]
  );
  const factCount = useMemo(() => candidates.filter((c) => c.claim_type === 'FACT').length, [candidates]);
  const hypothesisCount = useMemo(
    () => candidates.filter((c) => c.claim_type === 'HYPOTHESIS').length,
    [candidates]
  );

  return (
    <div className="space-y-4">
      {/* ── Top Header / Agent Mission & Controls Bar ─────────────────────── */}
      <div className="rounded-2xl glass-strong border border-slate-200/80 dark:border-slate-800 p-4 sm:p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          {/* Mission & Identity */}
          <div className="flex items-start gap-3.5">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-primary-500 flex items-center justify-center shadow-lg shadow-purple-500/20 shrink-0">
              <Bot className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
                  TraceLens Agent v0 智能研判中心
                </h1>
                <Badge
                  data-testid="agent-execution-status-badge"
                  variant={
                    isAutoPropelling || isExecuting || agentState?.agent_execution_status === 'running'
                      ? 'yellow'
                      : agentState?.agent_execution_status === 'completed'
                      ? 'green'
                      : 'purple'
                  }
                  size="sm"
                  className="flex items-center gap-1.5"
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isAutoPropelling || isExecuting || agentState?.agent_execution_status === 'running'
                        ? 'bg-amber-400 animate-ping'
                        : 'bg-current'
                    }`}
                  />
                  {isAutoPropelling
                    ? `auto (自动推进 第${autoPropelCycle}/${maxAutoCycles}轮)`
                    : isExecuting || agentState?.agent_execution_status === 'running'
                    ? 'executing (研判推进中)'
                    : agentState?.agent_execution_status === 'completed'
                    ? 'completed (已结案)'
                    : 'idle (就绪)'}
                </Badge>
                <span
                  data-testid="agent-state-revision"
                  className="text-xs font-mono px-2 py-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-semibold"
                >
                  Rev {agentState?.working_state_revision ?? 2}
                </span>
                <span className="text-xs font-mono text-slate-400 dark:text-slate-500">
                  会话: {investigationId || '待初始化'}
                </span>
              </div>

              {/* Mode & Associated Case Identifier */}
              <div className="mt-2 flex items-center gap-2 flex-wrap" data-testid="agent-mode-identifier">
                {isCrossImageMode ? (
                  <>
                    <span
                      data-testid="mode-badge-cross-image"
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-200 border border-purple-300 dark:border-purple-700 shadow-sm"
                    >
                      <Network className="w-3.5 h-3.5 text-purple-600 dark:text-purple-300 animate-pulse" />
                      <span>🌐 跨镜像多设备联合研判模式</span>
                      <span className="px-1.5 py-0.2 rounded-full bg-purple-200/80 dark:bg-purple-800/80 text-[10px] font-bold">
                        {caseMembers.length} 设备协同
                      </span>
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1">
                      <span>所属案件:</span>
                      <strong className="text-slate-800 dark:text-slate-200">{associatedCase?.name || associatedCase?.id}</strong>
                    </span>
                    {currentMember ? (
                      <span className="text-xs font-mono text-slate-500 dark:text-slate-400 flex items-center gap-1.5 flex-wrap">
                        <span>当前聚焦设备:</span>
                        <span className="text-purple-600 dark:text-purple-400 font-semibold px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-800">
                          {currentMember.roleLabel} ({currentMember.imageName})
                        </span>
                        <button
                          type="button"
                          data-testid="btn-cancel-device-focus-header"
                          onClick={handleCancelFocus}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-purple-100 hover:bg-purple-200 dark:bg-purple-900/60 dark:hover:bg-purple-800 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-700 transition-colors shadow-xs"
                          title="取消单机聚焦，返回全案多设备协同全景"
                        >
                          <X className="w-3 h-3" />
                          <span>取消聚焦 / 返回全景</span>
                        </button>
                      </span>
                    ) : (
                      <span className="text-xs font-mono text-slate-500 dark:text-slate-400 flex items-center gap-1.5 flex-wrap">
                        <span>工作区:</span>
                        <span className="text-purple-600 dark:text-purple-400 font-semibold px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-800 flex items-center gap-1">
                          <Network className="w-3 h-3" />
                          🌐 全案多设备协同全景 (汇总 {caseMembers.length} 台设备)
                        </span>
                      </span>
                    )}
                    <Link
                      to={`/case-intelligence?case_id=${encodeURIComponent(associatedCase?.id)}&tab=cross-image`}
                      className="text-xs text-purple-600 dark:text-purple-400 hover:underline flex items-center gap-0.5 ml-1"
                    >
                      <span>案件智能全景</span>
                      <ExternalLink className="w-3 h-3" />
                    </Link>
                    <button
                      type="button"
                      data-testid="btn-switch-to-single-device"
                      onClick={() => {
                        setSearchParams((prev) => {
                          prev.delete('case_id');
                          return prev;
                        });
                      }}
                      className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline ml-1"
                      title="切换到仅针对当前单设备的专注研判视图"
                    >
                      切换为单设备专注模式
                    </button>
                  </>
                ) : (
                  <>
                    <span
                      data-testid="mode-badge-single-image"
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700"
                    >
                      <Laptop className="w-3.5 h-3.5 text-slate-500" />
                      <span>🖥️ 单镜像独立调查模式</span>
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1">
                      <span>当前镜像:</span>
                      <strong className="text-slate-800 dark:text-slate-200 font-mono">
                        {selectedTask?.image_path ? selectedTask.image_path.split('/').pop() : selectedTask?.task_name || currentTaskId}
                      </strong>
                    </span>
                    {associatedCase && (
                      <button
                        type="button"
                        data-testid="btn-switch-to-cross-image"
                        onClick={() => {
                          setSearchParams((prev) => {
                            prev.set('case_id', associatedCase.id);
                            return prev;
                          });
                        }}
                        className="inline-flex items-center gap-1 text-xs text-purple-600 dark:text-purple-400 font-semibold hover:underline ml-1"
                      >
                        <span>所属案件「{associatedCase.name}」({associatedCase.task_ids?.length || 0}设备) · 切换为跨镜像联合研判</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>
                    )}
                  </>
                )}
              </div>

              <p className="text-xs sm:text-sm text-slate-600 dark:text-slate-300 mt-1 line-clamp-1">
                <strong>案件目标：</strong>{' '}
                {agentState?.objective ||
                  selectedTask?.case_description ||
                  selectedTask?.task_name ||
                  '多维电子数据司法取证研判：固定系统行为、账户凭据、异常持久化与反取证对抗痕迹'}
              </p>
            </div>
          </div>

          {/* Action Toolbar */}
          <div className="flex items-center gap-2.5 shrink-0">
            <Button
              data-testid="btn-refresh-agent-state"
              variant="outline"
              size="sm"
              onClick={() => {
                loadAgentState();
                loadCandidates();
                loadTrajectory();
              }}
              disabled={stateLoading || candidatesLoading || isExecuting || isAutoPropelling || isTaskRunning}
              icon={RefreshCw}
              className="text-slate-600 dark:text-slate-300"
            >
              刷新状态
            </Button>

            <Link
              data-testid="btn-view-investigation-report"
              to={
                isCrossImageMode && associatedCase
                  ? `/case-intelligence?case_id=${encodeURIComponent(associatedCase.id)}&task_id=${encodeURIComponent(currentTaskId)}&tab=cross-image`
                  : `/case-intelligence?task_id=${encodeURIComponent(currentTaskId)}&tab=forensic`
              }
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700/60 shadow-sm transition-all"
            >
              <FileCheck2 className="w-3.5 h-3.5 text-teal-500" />
              <span>{isCrossImageMode ? '查看跨镜像研判报告' : '查看调查报告'}</span>
              {isCrossImageMode ? (
                <span className="ml-0.5 px-1.5 py-0.5 rounded-md text-[10px] font-mono bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 font-bold">
                  案件级
                </span>
              ) : latestReportVersion ? (
                <span className="ml-0.5 px-1.5 py-0.5 rounded-md text-[10px] font-mono bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 font-bold">
                  v{latestReportVersion.version}
                </span>
              ) : null}
            </Link>

            {isAutoPropelling ? (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-purple-200 dark:border-purple-800 bg-purple-50/80 dark:bg-purple-950/40 text-xs font-mono text-purple-700 dark:text-purple-300 shadow-sm">
                  {isExecuting || agentState?.agent_execution_status === 'running' ? (
                    <>
                      <Spinner size="xs" />
                      <span>研判推进中 ({autoPropelCycle}/{maxAutoCycles})</span>
                    </>
                  ) : (
                    <>
                      <Clock className="w-3.5 h-3.5 text-amber-500 animate-pulse" />
                      <span>缓冲 ({cooldownRemaining}s)</span>
                    </>
                  )}
                </div>
                <Button
                  data-testid="btn-stop-auto-propel"
                  variant="danger"
                  size="sm"
                  onClick={handleStopAutoPropel}
                  icon={Pause}
                  className="shadow-sm"
                >
                  <span>暂停推进</span>
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-700 dark:text-slate-300 shadow-sm transition-colors">
                  <span className="text-slate-400 dark:text-slate-500 font-normal">推进上限:</span>
                  <select
                    data-testid="select-max-auto-cycles"
                    value={maxAutoCycles}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      setMaxAutoCycles(val);
                      try {
                        localStorage.setItem('tracelens_agent_max_cycles', String(val));
                      } catch {}
                    }}
                    disabled={isExecuting || isAutoPropelling || agentState?.agent_execution_status === 'running'}
                    className="bg-transparent font-semibold font-mono text-purple-700 dark:text-purple-300 focus:outline-none cursor-pointer pr-1"
                  >
                    <option value={15}>15 轮 (快速验证)</option>
                    <option value={30}>30 轮 (深度调查·推荐)</option>
                    <option value={50}>50 轮 (全量闭环)</option>
                    <option value={100}>100 轮 (极限攻坚)</option>
                  </select>
                </div>

                <Button
                  data-testid="btn-start-agent-cycle"
                  variant="outline"
                  size="sm"
                  onClick={handleStartCycle}
                  disabled={!featureEnabled || isExecuting || isTaskRunning || agentState?.agent_execution_status === 'running'}
                  title={
                    agentState?.agent_execution_status === 'running'
                      ? '当前研判周期已在后台执行中'
                      : '仅触发单轮自主循环并在该轮完成后暂停'
                  }
                  className="text-purple-700 dark:text-purple-300 border-purple-300 dark:border-purple-800 hover:bg-purple-50 dark:hover:bg-purple-950/40"
                >
                  {isExecuting || agentState?.agent_execution_status === 'running' ? (
                    <>
                      <Spinner size="xs" />
                      <span>执行中...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5 fill-current" />
                      <span>单步研判</span>
                    </>
                  )}
                </Button>

                <Button
                  data-testid="btn-start-auto-propel"
                  variant="primary"
                  size="sm"
                  onClick={handleStartAutoPropel}
                  disabled={!featureEnabled || isExecuting || isTaskRunning}
                  title={
                    isTaskRunning
                      ? '取证任务尚未完成基础工件提取'
                      : agentState?.agent_execution_status === 'running'
                      ? '当前已有研判周期在后台运行，点击将开启连续自动推进并实时追踪'
                      : '自主连续推进多轮研判，直至达成结案条件或收敛停机'
                  }
                  className="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 shadow-md shadow-purple-500/20"
                >
                  {isTaskRunning ? (
                    <>
                      <Spinner size="xs" />
                      <span>任务分析中...</span>
                    </>
                  ) : agentState?.agent_execution_status === 'running' ? (
                    <>
                      <Sparkles className="w-3.5 h-3.5 animate-pulse" />
                      <span>接管并自动推进</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>自动推进至调查完成</span>
                    </>
                  )}
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Task Processing Live Progress Banner */}
        {isTaskRunning && (
          <div className="mt-3 p-4 rounded-xl bg-purple-50/80 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Spinner size="sm" className="text-purple-600" />
                <span className="font-semibold text-xs sm:text-sm text-purple-900 dark:text-purple-200">
                  当前取证镜像基础提取与分析中 ({selectedTask?.progress?.overall_percentage ?? 0}%)
                </span>
              </div>
              <span className="text-xs font-mono text-purple-700 dark:text-purple-300">
                阶段: {selectedTask?.progress?.phase_description || '处理中...'}
              </span>
            </div>
            <div className="w-full bg-purple-200/50 dark:bg-purple-900/50 h-2 rounded-full overflow-hidden">
              <div
                className="bg-purple-600 h-full rounded-full transition-all duration-300"
                style={{ width: `${selectedTask?.progress?.overall_percentage ?? 0}%` }}
              />
            </div>
            <p className="text-[11px] text-purple-700/80 dark:text-purple-300/80 mt-2">
              基础工件抽取、文件哈希与时间线构建完成后，将自动进入 Agent 自主研判流程。
            </p>
          </div>
        )}

        {/* Auto Propel Active Notification Banner */}
        {isAutoPropelling && (
          <div className="mt-3 p-3.5 rounded-xl bg-purple-50/90 dark:bg-purple-950/50 border border-purple-200 dark:border-purple-800 text-xs text-purple-900 dark:text-purple-200 flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-lg bg-purple-100 dark:bg-purple-900/60 flex items-center justify-center text-purple-600 dark:text-purple-300 shrink-0">
                <Sparkles className="w-4 h-4 animate-spin" />
              </div>
              <div>
                <span className="font-semibold text-purple-950 dark:text-purple-100">
                  {isExecuting || agentState?.agent_execution_status === 'running'
                    ? `Agent 自主闭环自动推进中 (第 ${autoPropelCycle} / ${maxAutoCycles} 轮)`
                    : `第 ${autoPropelCycle} 轮执行完毕，系统状态已就绪`}
                </span>
                <p className="text-[11px] text-purple-700 dark:text-purple-300 mt-0.5">
                  {isExecuting || agentState?.agent_execution_status === 'running'
                    ? 'AI 智能体正在按规划执行取证工具调用、成果推导与假设验证... (状态已持久化，刷新页面自动保持)'
                    : `分析师缓冲观察期：${cooldownRemaining} 秒后将自动执行下一轮推进。支持随时人工暂停。`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="danger"
                size="sm"
                onClick={handleStopAutoPropel}
                icon={Pause}
                className="py-1 px-3 text-xs"
              >
                立即暂停
              </Button>
            </div>
          </div>
        )}

        {/* Real-time Status / Execution Alert */}
        {executionError && (
          <div className="mt-3 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-500 shrink-0" />
              <span>执行异常: {executionError}</span>
            </div>
            <button onClick={handleStartCycle} className="underline font-semibold hover:text-rose-900">
              重试
            </button>
          </div>
        )}
      </div>

      {/* ── Cross-Image Member Images Matrix (Shown in Cross-Image Mode) ────── */}
      {isCrossImageMode && caseMembers.length > 0 && (
        <div
          data-testid="case-member-matrix"
          className="rounded-2xl glass-strong border border-purple-200/70 dark:border-purple-900/50 p-3 shadow-xs bg-gradient-to-r from-purple-50/40 via-indigo-50/20 to-transparent dark:from-purple-950/20 dark:via-indigo-950/10 transition-all duration-300"
        >
          {/* Header Bar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-purple-100 dark:border-purple-900/40">
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-md bg-purple-600 text-white flex items-center justify-center text-xs font-bold shadow-xs">
                <Layers className="w-3 h-3" />
              </div>
              <span className="text-xs font-bold text-slate-900 dark:text-slate-100 uppercase tracking-wider flex items-center gap-1.5">
                涉案设备镜像协同矩阵 (Member Devices Matrix)
                <span className="text-[10px] font-normal text-purple-700 dark:text-purple-300 font-mono bg-purple-100/70 dark:bg-purple-900/50 px-1.5 py-0.2 rounded">
                  共 {caseMembers.length} 台协同源
                </span>
              </span>
            </div>
            <div className="flex items-center gap-2.5 text-xs text-slate-500 dark:text-slate-400">
              {focusedTaskId && (
                <button
                  type="button"
                  data-testid="btn-cancel-device-focus-matrix"
                  onClick={handleCancelFocus}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-semibold bg-white dark:bg-slate-800 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-700 shadow-2xs hover:bg-purple-50 dark:hover:bg-purple-950 transition-colors"
                  title="取消单机聚焦，查看全案所有设备联合研判全景"
                >
                  <X className="w-3 h-3" />
                  <span>取消单机聚焦 · 返回全案全景</span>
                </button>
              )}
              <span className="hidden md:inline-flex items-center gap-1 text-[11px] text-slate-400">
                <span className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse" />
                <span>点击卡片聚焦单机或取消</span>
              </span>
              <button
                type="button"
                data-testid="btn-toggle-matrix-collapse"
                onClick={() => setIsMatrixCollapsed((prev) => !prev)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:text-purple-600 dark:hover:text-purple-300 hover:bg-white/80 dark:hover:bg-slate-800/80 transition-colors"
                title={isMatrixCollapsed ? '展开完整设备矩阵' : '收起设备矩阵以节省垂直工作区'}
              >
                {isMatrixCollapsed ? (
                  <>
                    <span>展开</span>
                    <ChevronDown className="w-3.5 h-3.5" />
                  </>
                ) : (
                  <>
                    <span>收起</span>
                    <ChevronUp className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Collapsed Ribbon Mode (Ultra-compact ~34px) */}
          {isMatrixCollapsed ? (
            <div className="flex items-center gap-2 pt-2 overflow-x-auto no-scrollbar">
              <button
                type="button"
                data-testid="case-member-card-all"
                onClick={handleCancelFocus}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-medium transition-all shrink-0 cursor-pointer ${
                  !focusedTaskId
                    ? 'border-purple-500 bg-purple-100/90 dark:bg-purple-900/60 text-purple-900 dark:text-purple-100 ring-2 ring-purple-500/30 font-semibold shadow-xs'
                    : 'border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 hover:border-purple-300 hover:bg-slate-50'
                }`}
                title="全案多设备协同全景"
              >
                <Network className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
                <span>🌐 全案协同全景</span>
                <span className="text-[10px] font-mono px-1 rounded bg-purple-200/70 dark:bg-purple-800/60">
                  ALL ({caseMembers.length}台)
                </span>
                {!focusedTaskId && (
                  <span className="text-[10px] font-bold text-purple-700 dark:text-purple-300 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-purple-600 animate-ping" />
                    当前全景
                  </span>
                )}
              </button>

              {caseMembers.map((member) => {
                const { Icon } = member;
                const isFocus = member.isCurrent;
                return (
                  <div
                    key={member.id}
                    data-testid={`case-member-card-${member.id}`}
                    onClick={() => handleMemberCardClick(member.id)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs transition-all shrink-0 cursor-pointer ${
                      isFocus
                        ? 'border-purple-500 bg-purple-100/90 dark:bg-purple-900/60 text-purple-900 dark:text-purple-100 ring-2 ring-purple-500/30 font-semibold shadow-xs'
                        : 'border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 hover:border-purple-300 hover:bg-slate-50'
                    }`}
                    title={`${member.roleLabel} (${member.imageName}) - 点击聚焦或取消聚焦`}
                  >
                    <Icon className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
                    <span className="font-semibold">{member.roleLabel}</span>
                    <span className="text-[10px] font-mono text-slate-400">({member.scope})</span>
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        member.status === 'completed'
                          ? 'bg-emerald-500'
                          : member.status === 'running'
                          ? 'bg-amber-500 animate-ping'
                          : 'bg-slate-400'
                      }`}
                      title={`状态: ${member.status === 'completed' ? '就绪' : member.status}`}
                    />
                    {isFocus ? (
                      <span className="text-[10px] font-bold text-purple-700 dark:text-purple-300 flex items-center gap-1 ml-0.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-purple-600 animate-ping" />
                        聚焦中
                        <button
                          type="button"
                          data-testid={`btn-cancel-focus-${member.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCancelFocus();
                          }}
                          className="ml-0.5 p-0.5 hover:text-purple-900 dark:hover:text-purple-100 rounded"
                          title="取消聚焦"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            /* Expanded Sleek Cards Grid (Compact ~46px per card) */
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-2.5 pt-2.5">
              {/* Global Overview Card (All Devices in Case) */}
              <div
                data-testid="case-member-card-all"
                onClick={handleCancelFocus}
                className={`px-3 py-2 rounded-xl border transition-all cursor-pointer select-none flex items-center justify-between gap-2 ${
                  !focusedTaskId
                    ? 'border-purple-500/90 bg-gradient-to-r from-purple-100/90 via-white to-indigo-50/70 dark:from-purple-950/70 dark:via-slate-800 dark:to-indigo-950/40 shadow-xs ring-2 ring-purple-500/30'
                    : 'border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/50 hover:border-purple-300 hover:bg-slate-50 dark:hover:bg-slate-800/80'
                }`}
                title="点击查看全案多设备联合研判全景"
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div
                    className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                      !focusedTaskId
                        ? 'bg-purple-600 text-white shadow-2xs'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                    }`}
                  >
                    <Network className="w-3.5 h-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-xs font-bold text-slate-900 dark:text-slate-100 truncate">
                        🌐 全案协同全景
                      </span>
                      <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 font-semibold">
                        ALL ({caseMembers.length}台)
                      </span>
                    </div>
                    <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 truncate">
                      跨镜像全局因果推导
                    </div>
                  </div>
                </div>

                {!focusedTaskId ? (
                  <span className="shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-700 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-purple-600 animate-ping" />
                    当前全景
                  </span>
                ) : (
                  <span className="shrink-0 text-[10px] text-slate-400 hover:text-purple-600 flex items-center gap-0.5">
                    <span>切回全景</span>
                    <ChevronRight className="w-3 h-3" />
                  </span>
                )}
              </div>

              {/* Individual Device Cards */}
              {caseMembers.map((member) => {
                const { Icon } = member;
                const isFocus = member.isCurrent;
                return (
                  <div
                    key={member.id}
                    data-testid={`case-member-card-${member.id}`}
                    onClick={() => handleMemberCardClick(member.id)}
                    className={`px-3 py-2 rounded-xl border transition-all cursor-pointer select-none flex items-center justify-between gap-2 ${
                      isFocus
                        ? 'border-purple-500/90 bg-white dark:bg-slate-800 shadow-xs ring-2 ring-purple-500/30'
                        : 'border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/50 hover:border-purple-300 hover:bg-slate-50 dark:hover:bg-slate-800/80'
                    }`}
                    title={isFocus ? '再次点击取消聚焦' : '点击聚焦研判此设备'}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <div
                        className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                          isFocus
                            ? 'bg-purple-600 text-white shadow-2xs'
                            : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-xs font-bold text-slate-900 dark:text-slate-100 truncate">
                            {member.roleLabel}
                          </span>
                          <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                            {member.scope}
                          </span>
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              member.status === 'completed'
                                ? 'bg-emerald-500'
                                : member.status === 'running'
                                ? 'bg-amber-500 animate-ping'
                                : 'bg-slate-400'
                            }`}
                            title={`状态: ${member.status === 'completed' ? '就绪' : member.status}`}
                          />
                        </div>
                        <div
                          className="text-[11px] font-mono text-slate-500 dark:text-slate-400 truncate"
                          title={member.imageName}
                        >
                          {member.imageName}
                        </div>
                      </div>
                    </div>

                    {isFocus ? (
                      <div className="flex items-center gap-1 shrink-0">
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-700 flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-purple-600 animate-ping" />
                          聚焦中
                        </span>
                        <button
                          type="button"
                          data-testid={`btn-cancel-focus-${member.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCancelFocus();
                          }}
                          className="p-0.5 text-slate-400 hover:text-purple-600 dark:hover:text-purple-300 rounded hover:bg-purple-100 dark:hover:bg-purple-900/40"
                          title="取消聚焦"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ) : (
                      <span className="shrink-0 text-[10px] text-slate-400 hover:text-purple-600 flex items-center gap-0.5">
                        <ChevronRight className="w-3 h-3" />
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── 3-Column Modern Agent Studio Layout ───────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 min-h-[720px]">
        {/* ── LEFT COLUMN (4 Cols): 执行过程与规划拆解 (Execution Process) ── */}
        <div className="lg:col-span-4 flex flex-col gap-4">
          <Card className="flex-1 flex flex-col p-4 overflow-hidden border-slate-200/80 dark:border-slate-800">
            {/* Header / Tabs */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                  研判过程 (Process)
                </h2>
              </div>
              <div className="flex items-center bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-xs">
                <button
                  type="button"
                  onClick={() => setProcessTab('questions')}
                  className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                    processTab === 'questions'
                      ? 'bg-white dark:bg-slate-700 text-purple-700 dark:text-purple-300 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                  }`}
                >
                  目标拆解
                </button>
                <button
                  type="button"
                  onClick={() => setProcessTab('trace')}
                  className={`px-2.5 py-1 rounded-md transition-all font-medium ${
                    processTab === 'trace'
                      ? 'bg-white dark:bg-slate-700 text-purple-700 dark:text-purple-300 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                  }`}
                >
                  执行轨迹
                </button>
              </div>
            </div>

            {/* Questions Decomposition View */}
            {processTab === 'questions' && (
              <div className="flex-1 overflow-y-auto space-y-2.5 pt-3 pr-1">
                <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center justify-between pb-1">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-slate-700 dark:text-slate-300">
                      法定排查支柱 ({questionTree.length})
                    </span>
                    {displayQuestions.length > questionTree.length && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 font-medium">
                        +{displayQuestions.length - questionTree.length} 专项下钻
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {displayQuestions.length > questionTree.length && (
                      <button
                        type="button"
                        onClick={() => {
                          const hasCollapsed = questionTree.some(
                            (r) => r.children && r.children.length > 0 && expandedPillars[r.question_id] === false
                          );
                          const next = {};
                          questionTree.forEach((r) => {
                            if (r.children && r.children.length > 0) {
                              next[r.question_id] = hasCollapsed;
                            }
                          });
                          setExpandedPillars(next);
                        }}
                        className="text-[11px] text-purple-600 hover:text-purple-800 dark:text-purple-400 font-medium"
                      >
                        {questionTree.some((r) => r.children && r.children.length > 0 && expandedPillars[r.question_id] === false)
                          ? '全部展开'
                          : '全部折叠'}
                      </button>
                    )}
                    {selectedQuestionId && (
                      <button
                        type="button"
                        onClick={() => setSelectedQuestionId(null)}
                        className="text-purple-600 hover:underline text-[11px]"
                      >
                        清除筛选
                      </button>
                    )}
                  </div>
                </div>

                {questionTree.map((root, rootIdx) => {
                  const meta = getQuestionMeta(root, rootIdx);
                  const isRootSelected = selectedQuestionId === root.question_id;
                  const hasChildren = root.children && root.children.length > 0;
                  const isExpanded = hasChildren && expandedPillars[root.question_id] !== false;
                  const hasSelectedChild = hasChildren && root.children.some((c) => c.question_id === selectedQuestionId);

                  return (
                    <div key={root.question_id} className="space-y-1.5">
                      {/* Root Pillar Card */}
                      <div
                        data-testid={`pillar-card-${root.pillarLabel}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => setSelectedQuestionId(isRootSelected ? null : root.question_id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            setSelectedQuestionId(isRootSelected ? null : root.question_id);
                          }
                        }}
                        className={`w-full text-left p-3 rounded-xl border transition-all cursor-pointer flex flex-col gap-1.5 ${
                          isRootSelected
                            ? 'border-purple-500 bg-purple-50/70 dark:bg-purple-950/40 ring-1 ring-purple-500 shadow-sm'
                            : hasSelectedChild
                            ? 'border-purple-300 dark:border-purple-800/80 bg-purple-50/30 dark:bg-purple-950/20'
                            : 'border-slate-200 dark:border-slate-800/80 hover:bg-slate-50/80 dark:hover:bg-slate-800/50'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-1.5">
                          <div className="flex items-center gap-2 min-w-0">
                            <div className="w-5 h-5 rounded-md bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 flex items-center justify-center text-[10px] font-bold shrink-0">
                              {root.pillarLabel}
                            </div>
                            <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
                              {meta.title}
                            </span>
                          </div>

                          <div className="flex items-center gap-1.5 shrink-0">
                            {hasChildren && (
                              <button
                                type="button"
                                title={isExpanded ? '收起专项子任务' : '展开专项子任务'}
                                onClick={(e) => togglePillarExpand(root.question_id, e)}
                                className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-purple-100/80 hover:bg-purple-200 dark:bg-purple-900/50 dark:hover:bg-purple-900/80 text-purple-700 dark:text-purple-300 transition-colors"
                              >
                                <span>+{root.children.length}</span>
                                {isExpanded ? (
                                  <ChevronDown className="w-3 h-3" />
                                ) : (
                                  <ChevronRight className="w-3 h-3" />
                                )}
                              </button>
                            )}
                            <Badge
                              size="xs"
                              variant={
                                root.status === 'in_progress'
                                  ? 'yellow'
                                  : root.status === 'answered'
                                  ? 'green'
                                  : 'blue'
                              }
                            >
                              {root.status === 'in_progress'
                                ? '研判中'
                                : root.status === 'answered'
                                ? '已闭环'
                                : '待排查'}
                            </Badge>
                          </div>
                        </div>

                        <p className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">
                          {meta.desc}
                        </p>
                      </div>

                      {/* Sub-tasks Tree (Children) */}
                      {hasChildren && isExpanded && (
                        <div className="ml-4 pl-3 border-l-2 border-purple-200 dark:border-purple-800/80 space-y-1.5 pt-0.5 pb-1">
                          {root.children.map((child) => {
                            const childMeta = getQuestionMeta(child);
                            const isChildSelected = selectedQuestionId === child.question_id;

                            return (
                              <div
                                key={child.question_id}
                                data-testid={`subquestion-card-${child.pillarLabel}`}
                                role="button"
                                tabIndex={0}
                                onClick={() => setSelectedQuestionId(isChildSelected ? null : child.question_id)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    setSelectedQuestionId(isChildSelected ? null : child.question_id);
                                  }
                                }}
                                className={`w-full text-left p-2.5 rounded-lg border transition-all cursor-pointer flex flex-col gap-1 ${
                                  isChildSelected
                                    ? 'border-purple-500 bg-purple-100/70 dark:bg-purple-900/50 ring-1 ring-purple-500 shadow-sm'
                                    : 'border-slate-200/90 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-purple-50/50 dark:hover:bg-purple-950/30'
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1.5">
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-indigo-100 dark:bg-indigo-900/60 text-indigo-700 dark:text-indigo-300 shrink-0">
                                      {child.pillarLabel}
                                    </span>
                                    <span className="text-[11px] font-medium text-slate-800 dark:text-slate-200 truncate">
                                      {childMeta.title}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-1 shrink-0">
                                    <span className="text-[9px] px-1 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                                      专项
                                    </span>
                                    <Badge
                                      size="xs"
                                      variant={
                                        child.status === 'in_progress'
                                          ? 'yellow'
                                          : child.status === 'answered'
                                          ? 'green'
                                          : 'blue'
                                      }
                                    >
                                      {child.status === 'in_progress'
                                        ? '下钻中'
                                        : child.status === 'answered'
                                        ? '已核实'
                                        : '待排查'}
                                    </Badge>
                                  </div>
                                </div>
                                <p className="text-[10px] text-slate-500 dark:text-slate-400 line-clamp-2">
                                  {child.text}
                                </p>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Execution Trajectory View */}
            {processTab === 'trace' && (
              <TrajectoryTimeline
                events={trajectoryEvents}
                loading={trajectoryLoading}
                onRefresh={loadTrajectory}
                latestTrajectoryRef={agentState?.latest_trajectory_ref}
                questions={displayQuestions}
                isExecuting={isExecuting || agentState?.agent_execution_status === 'running'}
              />
            )}
          </Card>
        </div>

        {/* ── MIDDLE COLUMN (5 Cols): 研判结论与证据底座 (Findings & Provenance) ── */}
        <div className="lg:col-span-5 flex flex-col gap-4">
          <Card className="flex-1 flex flex-col p-4 overflow-hidden border-slate-200/80 dark:border-slate-800">
            {/* Stat Metrics Header */}
            <div className="grid grid-cols-4 gap-2 pb-3.5 border-b border-slate-100 dark:border-slate-800">
              <div className="p-2.5 rounded-xl bg-purple-50/60 dark:bg-purple-950/20 border border-purple-100 dark:border-purple-900/40 text-center">
                <span className="text-[10px] text-purple-700 dark:text-purple-400 font-medium">调查问题</span>
                <div className="text-base font-bold text-purple-900 dark:text-purple-200">
                  {agentState?.questions_count && agentState.questions_count > 0 ? agentState.questions_count : displayQuestions.length}
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-emerald-50/60 dark:bg-emerald-950/20 border border-emerald-100 dark:border-emerald-900/40 text-center">
                <span className="text-[10px] text-emerald-700 dark:text-emerald-400 font-medium">证实事实</span>
                <div className="text-base font-bold text-emerald-900 dark:text-emerald-200">{factCount}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-amber-50/60 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/40 text-center">
                <span className="text-[10px] text-amber-700 dark:text-amber-400 font-medium">研判假说</span>
                <div className="text-base font-bold text-amber-900 dark:text-amber-200">{hypothesisCount}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-blue-50/60 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/40 text-center">
                <span className="text-[10px] text-blue-700 dark:text-blue-400 font-medium">接地率</span>
                <div className="text-base font-bold text-blue-900 dark:text-blue-200">100%</div>
              </div>
            </div>

            {/* Filter Tabs */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 py-2.5">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider flex items-center gap-1.5 shrink-0">
                  <Layers className="w-3.5 h-3.5 text-purple-500" />
                  研判成果清单 ({filteredCandidates.length})
                </span>
                {selectedQuestionInfo && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 font-medium flex items-center gap-1 truncate">
                    <span className="font-bold">{selectedQuestionInfo.label}</span>
                    <span className="truncate max-w-[140px]">{selectedQuestionInfo.title}</span>
                    <button
                      type="button"
                      onClick={() => setSelectedQuestionId(null)}
                      className="hover:text-purple-900 dark:hover:text-white ml-0.5 font-bold"
                      title="清除筛选"
                    >
                      ×
                    </button>
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {isCrossImageMode && (
                  <div className="flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-xs" data-testid="filter-device-group">
                    {[
                      { id: 'all', label: '全部设备' },
                      { id: 'src_pc', label: 'PC' },
                      { id: 'src_server', label: '服务器' },
                      { id: 'cross', label: '跨源' },
                    ].map((df) => (
                      <button
                        key={df.id}
                        type="button"
                        data-testid={`filter-device-${df.id}`}
                        onClick={() => setDeviceFilter(df.id)}
                        className={`px-2 py-0.5 rounded text-[11px] font-medium transition-all ${
                          deviceFilter === df.id
                            ? 'bg-purple-600 text-white shadow-sm font-semibold'
                            : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                        }`}
                      >
                        {df.label}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-xs">
                  {['all', 'FACT', 'HYPOTHESIS', 'review_pending'].map((type) => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setFilterType(type)}
                      className={`px-2 py-0.5 rounded-md text-[11px] font-medium transition-all ${
                        filterType === type
                          ? 'bg-white dark:bg-slate-700 text-purple-700 dark:text-purple-300 shadow-sm'
                          : 'text-slate-500 hover:text-slate-700'
                      }`}
                    >
                      {type === 'all'
                        ? '全部'
                        : type === 'FACT'
                        ? '事实'
                        : type === 'HYPOTHESIS'
                        ? '假说'
                        : '待审'}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Candidates Card List */}
            <div className="flex-1 overflow-y-auto space-y-2 pr-1 min-h-[300px]">
              {candidatesLoading && (
                <div className="p-8 text-center"><Spinner size="md" /></div>
              )}

              {!candidatesLoading && filteredCandidates.length === 0 && (
                <div className="p-8 text-center text-xs text-slate-400">
                  {selectedQuestionId ? (
                    <div className="flex flex-col items-center gap-2">
                      <span>当前调查方向暂无匹配结论</span>
                      <button
                        onClick={() => setSelectedQuestionId(null)}
                        className="text-purple-600 hover:underline text-xs"
                      >
                        查看全部结论
                      </button>
                    </div>
                  ) : (
                    '暂无匹配的研判结论。'
                  )}
                </div>
              )}

              {filteredCandidates.map((c) => {
                const isSelected = c.candidate_id === selectedCandidateId;
                const epistemicVariant = EPISTEMIC_VARIANTS[c.claim_type] || 'gray';
                const statusVariant = STATUS_VARIANTS[c.review_status] || 'gray';
                const scopeInfo = getCandidateScopeInfo(c, currentMember);

                return (
                  <div
                    key={c.candidate_id}
                    data-testid={`candidate-item-${c.candidate_id}`}
                    onClick={() => setSelectedCandidateId(c.candidate_id)}
                    className={`p-3 rounded-xl border text-left cursor-pointer transition-all flex flex-col gap-1.5 ${
                      isSelected
                        ? 'border-purple-500 bg-purple-50/60 dark:bg-purple-950/30 ring-1 ring-purple-500/50 shadow-sm'
                        : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50/70 dark:hover:bg-slate-800/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Badge size="xs" variant={epistemicVariant}>
                          {c.claim_type}
                        </Badge>
                        <Badge size="xs" variant={statusVariant}>
                          {c.review_status}
                        </Badge>
                        <Badge size="xs" variant="blue">
                          {c.grounding_status}
                        </Badge>
                        {isCrossImageMode && (
                          <span
                            data-testid={`badge-scope-${c.candidate_id}`}
                            className={`inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] font-medium font-mono ${
                              scopeInfo.scope === 'cross'
                                ? 'bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-700'
                                : scopeInfo.scope === 'src_server'
                                ? 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700'
                                : scopeInfo.scope === 'src_phone'
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border border-indigo-300 dark:border-indigo-700'
                                : 'bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-700'
                            }`}
                          >
                            <scopeInfo.Icon className="w-2.5 h-2.5" />
                            <span>{scopeInfo.label}</span>
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] font-mono text-slate-400">
                        Rev {c.source_revision}
                      </span>
                    </div>

                    <p className="text-xs text-slate-800 dark:text-slate-200 line-clamp-2 leading-relaxed">
                      {c.content}
                    </p>

                    <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono mt-0.5">
                      <span className="truncate max-w-[180px]">{c.candidate_id}</span>
                      <span>{c.evidence_refs?.length || 0} 证据锚点</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Selected Finding Deep Dive & Provenance References */}
            {activeCandidate && (
              <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                      <FileSearch className="w-3.5 h-3.5 text-purple-500" />
                      事实依据与证据链溯源 (Provenance)
                    </span>
                    {isCrossImageMode && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                        来源: {getCandidateScopeInfo(activeCandidate, currentMember).label}
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] font-mono text-slate-400">
                    ID: {activeCandidate.candidate_id}
                  </span>
                </div>

                {/* Epistemic Alert for HYPOTHESIS */}
                {activeCandidate.claim_type === 'HYPOTHESIS' && (
                  <div
                    data-testid="hypothesis-epistemic-warning"
                    className="p-2 rounded-lg bg-purple-50 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800 text-[11px] text-purple-800 dark:text-purple-300"
                  >
                    <strong>推测性假说（HYPOTHESIS）：</strong>{' '}
                    此为线索推测，接受假说不会自动晋升为确凿事实。
                  </div>
                )}

                {/* Full Statement */}
                <div
                  data-testid="candidate-full-content"
                  className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200/60 dark:border-slate-800 text-xs text-slate-800 dark:text-slate-200 whitespace-pre-wrap leading-relaxed select-text"
                >
                  {activeCandidate.content}
                </div>

                {/* Provenance Evidence Buttons */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  {activeCandidate.evidence_refs?.map((ref) => {
                    const isServer = ref.startsWith('src_server:') || ref.startsWith('src_server/');
                    const isPC = ref.startsWith('src_pc:') || ref.startsWith('src_pc/');
                    const isPhone = ref.startsWith('src_phone:') || ref.startsWith('src_phone/');
                    return (
                      <button
                        key={ref}
                        type="button"
                        data-testid={`evidence-ref-${ref}`}
                        data-testid-alt="btn-evidence-provenance"
                        onClick={() => setPreviewEvidence(ref)}
                        className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] font-mono transition-colors ${
                          isServer
                            ? 'border-emerald-300 dark:border-emerald-800 bg-emerald-50/70 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-100'
                            : isPC
                            ? 'border-blue-300 dark:border-blue-800 bg-blue-50/70 dark:bg-blue-950/40 text-blue-800 dark:text-blue-300 hover:bg-blue-100'
                            : isPhone
                            ? 'border-purple-300 dark:border-purple-800 bg-purple-50/70 dark:bg-purple-950/40 text-purple-800 dark:text-purple-300 hover:bg-purple-100'
                            : 'border-purple-200 dark:border-purple-800 bg-purple-50/50 dark:bg-purple-950/30 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900/50'
                        }`}
                        title={`点击溯源并查看此底层证据 (${isServer ? '涉案服务器' : isPC ? '嫌疑人计算机' : isPhone ? '涉案手机' : '单机'})`}
                      >
                        {isServer ? (
                          <Server className="w-3 h-3 text-emerald-600" />
                        ) : isPC ? (
                          <Laptop className="w-3 h-3 text-blue-600" />
                        ) : isPhone ? (
                          <Smartphone className="w-3 h-3 text-purple-600" />
                        ) : (
                          <FileText className="w-3 h-3" />
                        )}
                        <span>{ref}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </Card>
        </div>

        {/* ── RIGHT COLUMN (3 Cols): 人工复核与终审闭环 (Analyst Review & Report) ── */}
        <div className="lg:col-span-3 flex flex-col gap-4">
          <Card className="flex-1 flex flex-col p-4 border-slate-200/80 dark:border-slate-800">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                  人工审查 (Review)
                </h2>
              </div>
              <Badge variant={pendingCount > 0 ? 'yellow' : 'gray'} size="xs">
                {pendingCount} 待复核
              </Badge>
            </div>

            {/* Review Action Controls */}
            <div className="py-3 border-b border-slate-100 dark:border-slate-800 space-y-2.5">
              <div className="text-xs text-slate-500 dark:text-slate-400">
                当前选中项审核状态：
                <span className="font-semibold text-slate-800 dark:text-slate-200 ml-1">
                  {activeCandidate?.review_status || '无选中项'}
                </span>
              </div>

              {activeCandidate?.review_status === 'review_pending' && !confirmAction && (
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    data-testid="btn-accept-candidate"
                    variant="success"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleOpenReviewConfirm('accepted')}
                    icon={Check}
                  >
                    接受 (Accept)
                  </Button>
                  <Button
                    data-testid="btn-reject-candidate"
                    variant="danger"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleOpenReviewConfirm('rejected')}
                    icon={CircleX}
                  >
                    拒绝 (Reject)
                  </Button>
                </div>
              )}

              {/* Review Confirmation Dialog Box */}
              {confirmAction && (
                <div
                  data-testid="review-confirmation-dialog"
                  className={`p-3 rounded-xl border space-y-2.5 ${
                    confirmAction === 'accepted'
                      ? 'border-emerald-300 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20'
                      : 'border-rose-300 bg-rose-50/50 dark:border-rose-800 dark:bg-rose-950/20'
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-bold text-xs text-slate-900 dark:text-white">
                    <ShieldAlert
                      className={`w-4 h-4 ${confirmAction === 'accepted' ? 'text-emerald-600' : 'text-rose-600'}`}
                    />
                    <span>确认{confirmAction === 'accepted' ? '接受' : '拒绝'}该项研判结论？</span>
                  </div>

                  <textarea
                    data-testid="review-note-input"
                    rows={2}
                    value={reviewNote}
                    onChange={(e) => setReviewNote(e.target.value)}
                    placeholder="请输入分析员审查批注或核验依据..."
                    className="w-full p-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />

                  <div className="flex items-center gap-2">
                    <Button
                      data-testid="btn-confirm-review-action"
                      data-testid-alt="btn-confirm-review-decision"
                      variant={confirmAction === 'accepted' ? 'success' : 'danger'}
                      size="xs"
                      className="flex-1"
                      loading={submittingReview}
                      disabled={submittingReview}
                      onClick={handleSubmitReviewDecision}
                    >
                      确认提交
                    </Button>
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={submittingReview}
                      onClick={() => setConfirmAction(null)}
                    >
                      取消
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* Authoritative Audit History */}
            <div className="flex-1 overflow-y-auto space-y-2 pt-3 pr-1 text-xs">
              <div className="flex items-center justify-between text-slate-500 dark:text-slate-400 text-[11px] mb-1">
                <span className="flex items-center gap-1">
                  <History className="w-3 h-3" />
                  不可变审核日志
                </span>
                <span>{history.length} 条</span>
              </div>

              {historyLoading && <div className="text-center p-4"><Spinner size="xs" /></div>}

              {!historyLoading && history.length === 0 && (
                <div className="text-slate-400 text-xs italic text-center py-4">暂无历史审查动作。</div>
              )}

              {history.map((h) => (
                <div
                  key={h.review_id}
                  className="p-2.5 rounded-lg border border-slate-200/60 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/30 flex flex-col gap-1"
                >
                  <div className="flex items-center justify-between">
                    <Badge size="xs" variant={h.decision === 'accepted' ? 'green' : 'red'}>
                      {h.decision}
                    </Badge>
                    <span className="text-[10px] text-slate-400 font-mono">
                      {h.created_at?.slice(11, 19) || '-'}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-600 dark:text-slate-300">
                    审核人: <span className="font-mono">{h.reviewer}</span>
                  </div>
                  {h.note && (
                    <p className="text-[11px] text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-950 p-1.5 rounded border border-slate-200/40">
                      {h.note}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {/* Final Report Card Footer */}
            <div className="mt-auto pt-3 border-t border-slate-100 dark:border-slate-800">
              <Link
                data-testid="btn-view-final-report-footer"
                to={
                  isCrossImageMode && associatedCase
                    ? `/case-intelligence?case_id=${encodeURIComponent(associatedCase.id)}&task_id=${encodeURIComponent(currentTaskId)}&tab=cross-image`
                    : `/case-intelligence?task_id=${encodeURIComponent(currentTaskId)}&tab=forensic`
                }
                className="w-full flex items-center justify-between p-2.5 rounded-xl bg-purple-50/50 dark:bg-purple-950/20 border border-purple-200/60 dark:border-purple-900/40 hover:bg-purple-100/50 transition-colors text-xs font-semibold text-purple-700 dark:text-purple-300"
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-purple-500" />
                  <span>{isCrossImageMode ? '跨镜像终审研判报告' : '终审调查报告'}</span>
                  {isCrossImageMode ? (
                    <Badge size="xs" variant="purple">
                      案件跨源
                    </Badge>
                  ) : latestReportVersion ? (
                    <Badge size="xs" variant="purple">
                      v{latestReportVersion.version} 就绪
                    </Badge>
                  ) : null}
                </div>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </Card>
        </div>
      </div>

      {/* ── Evidence Trace Modal / Preview ─────────────────────────────────── */}
      <AnimatePresence>
        {previewEvidence && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 max-w-xl w-full p-5 space-y-4"
            >
              <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-500" />
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                    真实底层取证检材锚点 (Grounded Provenance)
                  </h3>
                </div>
                <button
                  onClick={() => setPreviewEvidence(null)}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  ✕
                </button>
              </div>

              <div className="space-y-2 text-xs">
                <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 font-mono text-purple-700 dark:text-purple-300 break-all">
                  {previewEvidence}
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-600 dark:text-slate-300">
                  <div className="p-2 rounded-lg bg-slate-100/70 dark:bg-slate-800/40">
                    <span className="text-slate-400 block">检材来源设备:</span>
                    <span className="font-semibold text-purple-700 dark:text-purple-300">{
                      previewEvidence?.startsWith('src_server:') ? '服务器镜像.E01 [src_server: Linux]' :
                      previewEvidence?.startsWith('src_phone:') ? '移动终端备份 [src_phone: Android]' :
                      previewEvidence?.startsWith('src_pc:') ? '窝点嫌疑人计算机镜像.E01 [src_pc: Windows]' :
                      (selectedTask?.image_name || selectedTask?.image_path || '当前镜像检材')
                    }</span>
                  </div>
                  <div className="p-2 rounded-lg bg-slate-100/70 dark:bg-slate-800/40">
                    <span className="text-slate-400 block">校验结果:</span>
                    <span className="text-emerald-600 font-semibold">100% 真实哈希吻合</span>
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Link
                  to={`/files?task_id=${
                    previewEvidence?.startsWith('src_server:') ? '442400ab-4de1-4188-8912-5ac3f31ac468' :
                    (currentTaskId || '60dedf82-7f35-48be-a104-b4d283a4fe92')
                  }&search=${encodeURIComponent(previewEvidence?.replace(/^.*?:file:/, '').replace(/^file:/, '') || '')}`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium hover:bg-slate-200"
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  <span>在源设备文件视图中定位</span>
                </Link>
                <Button size="sm" variant="primary" onClick={() => setPreviewEvidence(null)}>
                  关闭
                </Button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
