import {
  LayoutDashboard,
  ListTodo,
  Clock,
  FolderOpen,
  FileText,
  ScanSearch,
  Network,
  FileSearch,
  Smartphone,
  Cpu,
  MessageCircle,
  Cloud,
  Search,
  BarChart3,
  Server,
  Share2,
  Settings,
  Briefcase,
  Wrench,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  key: string;
  href: string;
  icon: LucideIcon;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

/** Pages that keep the current task context in the URL across navigation. */
export const TASK_CONTEXT_PAGES = new Set([
  '/timeline',
  '/files',
  '/case-intelligence',
  '/analysis-center',
  '/knowledge-graph',
  '/investigation-graph',
  '/investigation',
  '/android',
  '/memory',
  '/wechat-graph',
  '/oss',
  '/search',
  '/statistics',
]);

/**
 * Sidebar + command palette source of truth. Four grouped sections instead of
 * one long list — group labels are rendered as micro-caps.
 */
export function buildNavSections(showTerminal: boolean): NavSection[] {
  const sections: NavSection[] = [
    {
      label: 'overview',
      items: [
        { key: 'nav.dashboard', href: '/dashboard', icon: LayoutDashboard },
        { key: 'nav.tasks', href: '/tasks', icon: ListTodo },
        { key: 'nav.cases', href: '/cases', icon: Briefcase },
      ],
    },
    {
      label: 'forensics',
      items: [
        { key: 'nav.timeline', href: '/timeline', icon: Clock },
        { key: 'nav.files', href: '/files', icon: FolderOpen },
        { key: 'nav.case_intelligence', href: '/case-intelligence', icon: FileText },
        { key: 'nav.case_center', href: '/analysis-center', icon: ScanSearch },
        { key: 'nav.android', href: '/android', icon: Smartphone },
        { key: 'nav.memory', href: '/memory', icon: Cpu },
      ],
    },
    {
      label: 'intelligence',
      items: [
        { key: 'nav.knowledge_graph', href: '/knowledge-graph', icon: Network },
        { key: 'nav.investigation_workbench', href: '/investigation', icon: FileSearch },
        { key: 'nav.wechat_graph', href: '/wechat-graph', icon: MessageCircle },
        { key: 'nav.oss_analysis', href: '/oss', icon: Cloud },
        { key: 'nav.search', href: '/search', icon: Search },
        { key: 'nav.statistics', href: '/statistics', icon: BarChart3 },
      ],
    },
    {
      label: 'system',
      items: [
        { key: 'nav.distributed', href: '/distributed', icon: Server },
        { key: 'nav.tools', href: '/tools', icon: Wrench },
        ...(showTerminal ? [{ key: 'nav.terminal', href: '/terminal', icon: Share2 } as NavItem] : []),
        { key: 'nav.settings', href: '/settings', icon: Settings },
      ],
    },
  ];
  return sections;
}

export const NAV_GROUP_LABELS: Record<string, string> = {
  overview: '概览',
  forensics: '取证分析',
  intelligence: '情报与图谱',
  system: '系统',
};
