import { stripFileKeyPrefix } from '../../utils/evidenceKey';
/**
 * Locate a frozen citation beside a literal evidence filename in report prose.
 * Identity always comes from the persisted manifest. If the filename (or its
 * extension-less form) is absent, repeated, or ambiguous, keep the citation
 * in the section-level list instead of guessing which claim it supports.
 */
export function placeNarrativeCitations(content, citationIds, citationsById) {
    const text = typeof content === 'string' ? content : '';
    const placements = [];
    const unresolved = [];

    for (const citationId of citationIds || []) {
        const citation = citationsById.get(citationId);
        const evidenceKey = citation?.evidence_key || '';
        if (!evidenceKey.startsWith('file:')) {
            unresolved.push(citationId);
            continue;
        }
        const filename = (stripFileKeyPrefix(evidenceKey) || "").split(/[\\/]/).pop() || '';
        const stem = filename.replace(/\.[^.]+$/, '');
        const candidates = [...new Set([filename, stem])]
            .filter((candidate) => candidate.length >= 4)
            .sort((left, right) => right.length - left.length);
        const match = candidates.map((candidate) => {
            const start = text.indexOf(candidate);
            if (start < 0 || text.indexOf(candidate, start + candidate.length) >= 0) return null;
            return { start, end: start + candidate.length, citationId };
        }).find(Boolean);
        if (!match || placements.some((item) => match.start < item.end && item.start < match.end)) {
            unresolved.push(citationId);
            continue;
        }
        placements.push(match);
    }

    placements.sort((left, right) => left.start - right.start);
    return { placements, unresolved };
}

// New globally planned reports carry explicit paragraph markers. Never infer
// these positions from filenames, including same-name files across sources.
export function explicitNarrativeParts(content, citationIds, citationsById) {
    const allowed = new Set(citationIds || []), parts = [];
    const text = String(content || '');
    let cursor = 0;
    for (const match of text.matchAll(/\[\[([^\]]+)\]\]/g)) {
        parts.push({ text: text.slice(cursor, match.index) });
        parts.push(allowed.has(match[1]) && citationsById.has(match[1])
            ? { citationId: match[1] } : { text: '〔引用待核对〕' });
        cursor = match.index + match[0].length;
    }
    parts.push({ text: text.slice(cursor) });
    return parts;
}
