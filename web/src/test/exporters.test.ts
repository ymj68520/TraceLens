import { describe, expect, it } from 'vitest';
import {
  buildClusterText,
  buildFileText,
  buildTaskText,
  relevantFileCount,
  shortTaskId,
  snapshotLabel,
} from '../pages/analysis/exporters';
import type { LlmDescriptionRow, TaskResultSnapshot } from '../pages/analysis/types';

const snap = (over: Partial<TaskResultSnapshot> = {}): TaskResultSnapshot => ({
  taskId: 'abcdef1234567890',
  descriptions: [],
  clusters: [],
  finishedAt: 0,
  ...over,
});

describe('shortTaskId / snapshotLabel', () => {
  it('cuts the task id to its first 8 characters', () => {
    expect(shortTaskId('abcdef1234567890')).toBe('abcdef12');
    expect(shortTaskId('abc')).toBe('abc');
  });

  it('labels snapshots with the image file name plus short id', () => {
    expect(snapshotLabel(snap({ imagePath: '/data/evidence.img' }))).toBe('evidence.img（abcdef12）');
    expect(snapshotLabel(snap({ imagePath: 'C:\\cases\\disk.E01' }))).toBe('disk.E01（abcdef12）');
  });

  it('falls back to the short id when there is no image path', () => {
    expect(snapshotLabel(snap())).toBe('abcdef12');
  });
});

describe('relevantFileCount', () => {
  it('counts only 1/true rows', () => {
    const rows: LlmDescriptionRow[] = [
      { file_path: '/a', is_relevant: 1 },
      { file_path: '/b', is_relevant: true },
      { file_path: '/c', is_relevant: 0 },
      { file_path: '/d', is_relevant: false },
      { file_path: '/e' },
    ];
    expect(relevantFileCount(rows)).toBe(2);
    expect(relevantFileCount([])).toBe(0);
  });
});

describe('buildFileText', () => {
  it('renders all known fields including the optional description', () => {
    const text = buildFileText({
      file_path: '/evidence/chat.db',
      is_relevant: 1,
      size: 2048,
      keywords: ['微信', '转账'],
      summary: '  聊天记录  ',
      description: '包含转账讨论',
    });
    expect(text).toBe(
      [
        '文件：/evidence/chat.db',
        '相关性：相关',
        '大小：2048 字节',
        '关键词：微信、转账',
        '摘要：聊天记录',
        '描述：包含转账讨论',
      ].join('\n'),
    );
  });

  it('uses placeholders for missing values and drops empty descriptions', () => {
    const text = buildFileText({ is_relevant: false });
    expect(text).toBe(['文件：—', '相关性：不相关', '大小：—', '关键词：—', '摘要：—'].join('\n'));
    expect(text).not.toContain('描述：');
  });
});

describe('buildClusterText', () => {
  it('renders the cluster header and summary', () => {
    const text = buildClusterText({
      event_type: 'file_create',
      parent_directory: '/data',
      timestamp: 1700000000,
      llm_is_relevant: true,
      llm_summary: '创建文件',
    });
    expect(text).toBe(
      ['事件簇：file_create @ /data', '时间戳：1700000000', '相关性：相关', '摘要：创建文件'].join('\n'),
    );
  });

  it('falls back to / for a missing directory', () => {
    const text = buildClusterText({ event_type: 'delete' });
    expect(text.split('\n')[0]).toBe('事件簇：delete @ /');
  });
});

describe('buildTaskText', () => {
  it('includes the header, file evidence and a cluster section', () => {
    const text = buildTaskText(
      snap({
        taskId: 'task-12345678',
        imagePath: '/img/x.raw',
        descriptions: [
          { file_path: '/a', is_relevant: 1 },
          { file_path: '/b', is_relevant: 0 },
        ],
        clusters: [{ event_type: 'create', parent_directory: '/d' }],
      }),
    );
    expect(text).toContain('任务：task-12345678');
    expect(text).toContain('镜像：/img/x.raw');
    expect(text).toContain('文件证据 2 项（相关 1 项），事件簇 1 项');
    expect(text).toContain('—— 事件簇 ——');
    expect(text).toContain('事件簇：create @ /d');
    expect(text).toContain('文件：/a');
  });

  it('omits the cluster section when there are no clusters', () => {
    const text = buildTaskText(snap({ descriptions: [{ file_path: '/a' }] }));
    expect(text).not.toContain('—— 事件簇 ——');
    expect(text).toContain('事件簇 0 项');
  });
});
