import { Link } from 'react-router-dom';

function Preview({ preview }) {
  if (!preview?.available) {
    return <p className="text-xs text-amber-700 dark:text-amber-300">{preview?.reason || '当前无法读取提取副本。'}</p>;
  }
  return <div className="space-y-2 text-xs">
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-slate-500">
      <span>提取副本 · {preview.file_size?.toLocaleString()} 字节</span>
      {preview.copy_sha256 && <span className="break-all">副本 SHA-256：{preview.copy_sha256}</span>}
      {preview.recorded_md5_matches_copy === true && <span className="text-emerald-700">与记录 MD5 一致</span>}
      {preview.recorded_md5_matches_copy === false && <span className="text-rose-700">与记录 MD5 不一致</span>}
    </div>
    <p className="text-amber-700 dark:text-amber-300">{preview.integrity_note}</p>
    {preview.kind === 'text' ? <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 p-3 text-slate-100" data-testid="graph-original-preview">{preview.text}</pre> : <>
      <p className="text-slate-500">二进制文件：下方为真实字节的十六进制预览和可打印字符串，不代表已解析文件格式。</p>
      <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-900 p-3 font-mono text-slate-100" data-testid="graph-original-preview">{preview.hex}</pre>
      {!!preview.printable_strings?.length && <ul className="max-h-28 space-y-1 overflow-auto rounded-lg bg-slate-50 p-2 font-mono text-slate-700 dark:bg-slate-900 dark:text-slate-300">
        {preview.printable_strings.map((value, index) => <li key={`${index}:${value}`} className="break-all">{value}</li>)}
      </ul>}
    </>}
    {preview.preview_truncated && <p className="text-slate-500">仅展示文件前 16 KiB。</p>}
  </div>;
}

export default function RelationshipTracePanel({ taskId, trace, loading, error, onClose }) {
  const relationship = trace?.relationship;
  return <div className="h-full overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800" data-testid="graph-relationship-panel">
    <div className="mb-3 flex items-center justify-between gap-2">
      <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">机器提取 · 待人工核验</span>
      <button type="button" aria-label="关闭关系详情" onClick={onClose} className="text-lg text-slate-400 hover:text-slate-700">×</button>
    </div>
    {loading && <p role="status" className="text-sm text-slate-500">正在读取关系来源…</p>}
    {error && <p role="alert" className="text-sm text-rose-600">关系来源读取失败：{error}</p>}
    {relationship && <div className="space-y-4">
      <div>
        <h3 className="break-words text-sm font-semibold text-slate-900 dark:text-white">{relationship.source.name} <span className="text-primary-600">— {relationship.label} →</span> {relationship.target.name}</h3>
        <p className="mt-1 break-all font-mono text-[10px] text-slate-400">关系 ID：{relationship.id}</p>
      </div>
      <section className="rounded-xl bg-amber-50 p-3 dark:bg-amber-950/20">
        <h4 className="text-xs font-semibold text-amber-900 dark:text-amber-200">机器抽取的关系表述（不是原始证据）</h4>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700 dark:text-slate-200">{relationship.fact || '该关系没有保存文字表述。'}</p>
      </section>
      <section>
        <h4 className="text-sm font-semibold text-slate-900 dark:text-white">来源记录 · {relationship.episode_count}</h4>
        <p className="mt-1 text-xs text-slate-500">以下是建图时送入模型的记录。分析文字与原始文件字节分开展示。</p>
        {!relationship.episodes.length && <p className="mt-2 text-xs text-amber-700">没有可读取的同任务来源记录，不能核验此关系。</p>}
        <div className="mt-3 space-y-4">
          {relationship.episodes.map((episode) => <article key={episode.id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700" data-testid={`graph-source-${episode.id}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700 dark:bg-slate-700 dark:text-slate-200">{episode.source_kind === 'llm_analysis' ? '文件分析记录' : '其他来源记录'}</span>
              <span className="break-all font-mono text-[10px] text-slate-400">{episode.id}</span>
            </div>
            <p className="mt-2 break-all text-xs text-slate-600 dark:text-slate-300">{episode.file_path || episode.name}</p>
            {episode.evidence_key && <Link
              className="mt-2 inline-block text-xs font-semibold text-primary-600 hover:underline"
              to={`/graph-source-file?task_id=${encodeURIComponent(taskId)}&evidence_key=${encodeURIComponent(episode.evidence_key)}&relationship_id=${encodeURIComponent(relationship.id)}&episode_id=${encodeURIComponent(episode.id)}`}
            >打开任务文件证据与提取副本 →</Link>}
            <details className="mt-3" open={relationship.episodes.length === 1}>
              <summary className="cursor-pointer text-xs font-medium text-slate-700 dark:text-slate-200">查看建图输入文字</summary>
              <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700 dark:bg-slate-900 dark:text-slate-300" data-testid="graph-source-episode-content">{episode.content || '该来源记录没有保存正文。'}</pre>
              {episode.content_truncated && <p className="mt-1 text-xs text-slate-500">这里只显示前 12,000 字符。</p>}
            </details>
            <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700">
              <h5 className="mb-2 text-xs font-semibold text-slate-800 dark:text-slate-200">任务文件的实际提取副本</h5>
              <Preview preview={episode.original_preview} />
            </div>
          </article>)}
        </div>
      </section>
      <p className="text-xs text-slate-500">关系的机器抽取结果仅供研判；核验时应结合原镜像、提取记录和实际文件内容。</p>
    </div>}
  </div>;
}
