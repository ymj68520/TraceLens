// markdownRenderer.js
// Renders the case-report markdown produced by the LLM, with interactive
// badges for [[file:...]] and [[event:...]] reference tokens.
//
// Extracted from CaseIntelligence.jsx as a pure helper. It takes the callbacks
// it needs (scrollToFile, navigate) plus the active context id as arguments.

// Render a single reference token into an interactive badge, or null.
const renderRef = (token, keyPrefix, { scrollToFile, activeContextId, navigate }) => {
    const fileMatch = token.match(/^\[\[file:(.+)\]\]$/);
    if (fileMatch) {
        const fPath = fileMatch[1];
        return <button key={`${keyPrefix}-f`} onClick={() => scrollToFile(fPath)} className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-md text-[13px] font-mono hover:bg-purple-100 border border-purple-200 font-bold">📄 {fPath.split('/').pop()}</button>;
    }
    const eventMatch = token.match(/^\[\[event:([A-Za-z_]+)@(\d+)\/([^\]]*)\]\]$/);
    if (eventMatch) {
        const eType = eventMatch[1];
        const eWindow = eventMatch[2];
        const eDir = eventMatch[3];
        const label = `${eType}@${eWindow}/${eDir.split('/').filter(Boolean).pop() || eDir}`;
        const shortLabel = label.length > 32 ? label.slice(0, 32) + '…' : label;
        const params = new URLSearchParams({
            task_id: activeContextId || '',
            cluster: 'true',
            type: eType,
        });
        return (
            <button
                key={`${keyPrefix}-e`}
                onClick={() => navigate(`/timeline?${params.toString()}`)}
                title={`事件簇: ${eType}@${eWindow}/${eDir}`}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-md text-[13px] font-mono hover:bg-blue-100 dark:hover:bg-blue-800/40 border border-blue-200 dark:border-blue-700 font-bold"
            >
                ⏱ {shortLabel}
            </button>
        );
    }
    return null;
};

// Split a chunk on reference tokens; refs become badges, rest is text.
const renderRefParts = (chunk, keyPrefix, ctx) => {
    const parts = chunk.split(/(\[\[(?:file|event):[^\]]+\]\])/g);
    return parts.map((part, j) => {
        const ref = renderRef(part, `${keyPrefix}-${j}`, ctx);
        if (ref) return ref;
        return <span key={`${keyPrefix}-${j}-t`}>{part}</span>;
    });
};

// IMPORTANT: split bold first, then resolve refs inside each chunk.
// The LLM often wraps a whole reference in bold, so the reference token
// is surrounded by double-asterisks. If we split references first and
// match with start/end anchors, the surrounding asterisks break the
// match and the whole reference renders as bold literal text instead of
// a badge. Splitting bold first lets refs render even inside bold spans.
const renderInline = (t, lineKey, ctx) => {
    const boldParts = t.split(/(\*\*[^*]+\*\*)/g);
    return boldParts.flatMap((bp, bi) => {
        const boldMatch = bp.match(/^\*\*(.+)\*\*$/);
        if (boldMatch) {
            return [<strong key={`${lineKey}-b-${bi}`} className="font-bold text-slate-900 dark:text-slate-100">{renderRefParts(boldMatch[1], `${lineKey}-b-${bi}`, ctx)}</strong>];
        }
        return renderRefParts(bp, `${lineKey}-${bi}`, ctx);
    });
};

/**
 * Render case-report markdown text with interactive file/event reference badges.
 * @param {string} text - the markdown text
 * @param {object} ctx - { scrollToFile, activeContextId, navigate }
 */
export const renderCaseMarkdown = (text, ctx) => {
    if (!text) return null;
    return <div className="prose prose-slate max-w-none dark:prose-invert">
        {text.split('\n').map((line, i) => {
            if (line.startsWith('# ')) return <h1 key={i} className="text-2xl font-bold mt-6 mb-3">{renderInline(line.slice(2), `l${i}`, ctx)}</h1>;
            if (line.startsWith('## ')) return <h2 key={i} className="text-xl font-semibold mt-5 mb-2">{renderInline(line.slice(3), `l${i}`, ctx)}</h2>;
            if (line.startsWith('### ')) return <h3 key={i} className="text-lg font-semibold mt-4 mb-2">{renderInline(line.slice(4), `l${i}`, ctx)}</h3>;
            if (line.startsWith('- ') || line.startsWith('* ')) return <li key={i} className="text-sm mb-1 ml-4 list-disc text-slate-700 dark:text-slate-300">{renderInline(line.slice(2), `l${i}`, ctx)}</li>;
            if (line.match(/^\d+\.\s/)) return <li key={i} className="text-sm mb-1 ml-4 list-decimal text-slate-700 dark:text-slate-300">{renderInline(line.replace(/^\d+\.\s/, ''), `l${i}`, ctx)}</li>;
            if (line.trim() === '') return null;
            return <p key={i} className="text-sm mb-2 leading-relaxed text-slate-700 dark:text-slate-300">{renderInline(line, `l${i}`, ctx)}</p>;
        })}
    </div>;
};
