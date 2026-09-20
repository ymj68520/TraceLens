// DocxPreview.jsx
// Full-fidelity DOCX rendering in the browser via docx-preview: fetches the
// materialized file bytes and renders the real document (layout, images,
// tables, styles). Falls back to the extracted Markdown text on failure.

import { useEffect, useRef, useState } from 'react';
import { renderAsync } from 'docx-preview';
import Spinner from '../common/Spinner';
import { fetchOfficeFile } from '../../services/officeService';

const DocxPreview = ({ taskId, filePath, fallbackText }) => {
  const containerRef = useRef(null);
  const [status, setStatus] = useState('loading'); // loading | ok | error

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');

    fetchOfficeFile(taskId, filePath)
      .then(async (blob) => {
        const buffer = await blob.arrayBuffer();
        if (cancelled || !containerRef.current) return;
        const container = containerRef.current;
        container.innerHTML = '';
        await renderAsync(buffer, container, undefined, {
          className: 'docx',
          inWrapper: true,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
        });
        if (!cancelled) setStatus('ok');
      })
      .catch((err) => {
        console.warn('docx full render failed, falling back to text:', err);
        if (!cancelled) setStatus('error');
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, filePath]);

  return (
    <div>
      {status === 'loading' && (
        <div className="flex items-center justify-center gap-2 py-8 text-slate-400 text-sm">
          <Spinner size="sm" /> 正在渲染文档...
        </div>
      )}
      {status === 'error' && (
        <div>
          <p className="text-xs text-amber-600 dark:text-amber-400 mb-2">
            文档排版渲染失败，以下为提取的文本内容：
          </p>
          <pre className="text-sm text-slate-800 dark:text-slate-200 bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap">
            {fallbackText}
          </pre>
        </div>
      )}
      {/* The render target stays mounted (hidden) even while loading so the
          effect can render into it as soon as the bytes arrive. */}
      <div
        ref={containerRef}
        className="overflow-auto max-h-[36rem] rounded border border-slate-200 dark:border-slate-700 bg-white"
        style={{ display: status === 'ok' ? 'block' : 'none' }}
      />
    </div>
  );
};

export default DocxPreview;
