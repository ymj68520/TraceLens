import { useEffect, useState } from 'react';

/**
 * ResizeObserver 容器尺寸追踪 —— 图谱画布需要随容器缩放，
 * 而首帧时 ref.current 还没有布局尺寸，必须由 observer 驱动。
 */
export function useElementSize<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!node) return;
    const measure = () => {
      const w = node.clientWidth;
      const h = node.clientHeight;
      setSize((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);

  return { ref: setNode, size } as const;
}
