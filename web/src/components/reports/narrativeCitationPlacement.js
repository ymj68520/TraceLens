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
        const filename = evidenceKey.slice(5).split(/[\\/]/).pop() || '';
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
