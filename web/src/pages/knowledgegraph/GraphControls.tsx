import { Download, Maximize2, RotateCcw, SlidersHorizontal, ZoomIn, ZoomOut } from 'lucide-react';
import { cx } from '../../lib/utils';

interface GraphControlsProps {
  /** 力导模拟是否在冷却计算中。 */
  cooling: boolean;
  minDegree: number;
  maxDegree: number;
  onMinDegreeChange: (v: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onReheat: () => void;
  onExportPng: () => void;
  exporting: boolean;
}

/** 图谱视图控制条：冷却状态、重跑布局、缩放、关系数过滤滑块、PNG 导出。 */
export default function GraphControls({
  cooling,
  minDegree,
  maxDegree,
  onMinDegreeChange,
  onZoomIn,
  onZoomOut,
  onFit,
  onReheat,
  onExportPng,
  exporting,
}: GraphControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className={cx(
          'inline-flex items-center gap-1.5 text-2xs mr-1 whitespace-nowrap',
          cooling ? 'text-accent-600 dark:text-accent-400' : 'text-ink-400 dark:text-ink-500',
        )}
      >
        <span
          aria-hidden
          className={cx('h-1.5 w-1.5 rounded-full', cooling ? 'bg-accent-500 animate-blink-soft' : 'bg-ink-300 dark:bg-ink-600')}
        />
        {cooling ? '布局计算中' : '布局已稳定'}
      </span>

      <button type="button" title="重跑力导布局" aria-label="重跑力导布局" className="btn btn-ghost btn-sm px-2" onClick={onReheat}>
        <RotateCcw size={14} />
      </button>
      <button type="button" title="放大" aria-label="放大" className="btn btn-ghost btn-sm px-2" onClick={onZoomIn}>
        <ZoomIn size={14} />
      </button>
      <button type="button" title="缩小" aria-label="缩小" className="btn btn-ghost btn-sm px-2" onClick={onZoomOut}>
        <ZoomOut size={14} />
      </button>
      <button type="button" title="适应画布" aria-label="适应画布" className="btn btn-ghost btn-sm px-2" onClick={onFit}>
        <Maximize2 size={14} />
      </button>

      <span aria-hidden className="h-5 w-px bg-ink-200 dark:bg-ink-700 mx-0.5" />

      {/* 数据支持时（存在度数 ≥2 的节点）才提供关系数过滤滑块。 */}
      {maxDegree >= 2 && (
        <label className="inline-flex items-center gap-2 text-2xs text-ink-500 dark:text-ink-400">
          <SlidersHorizontal size={13} className="text-ink-400 dark:text-ink-500" />
          <span className="whitespace-nowrap">关系数 ≥ {minDegree}</span>
          <input
            type="range"
            min={0}
            max={maxDegree}
            step={1}
            value={minDegree}
            onChange={(e) => onMinDegreeChange(Number(e.target.value))}
            className="w-24 accent-accent-500"
            aria-label="按关系数过滤节点"
          />
        </label>
      )}

      <span aria-hidden className="h-5 w-px bg-ink-200 dark:bg-ink-700 mx-0.5" />

      <button type="button" className="btn btn-secondary btn-sm" onClick={onExportPng} disabled={exporting}>
        <Download size={13} /> {exporting ? '导出中…' : '导出 PNG'}
      </button>
    </div>
  );
}
