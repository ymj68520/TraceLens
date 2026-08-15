import { describe, expect, test } from 'vitest';
import { NODE_COLORS } from '../knowledge-graph/graphConstants';
import {
    BASE_NODE_COLOR_FALLBACK,
    INVESTIGATION_NODE_COLORS,
    colorKeyForNode,
    getNodeColor,
    getLinkColor,
    isUnconfirmed,
    linkTooltip,
    nodeTooltip,
    parseNodeId,
} from './investigationGraphConstants';

describe('investigationGraphConstants namespace colors', () => {
    test('every investigation namespace color is distinct and avoids the Base KG palette', () => {
        const values = Object.values(INVESTIGATION_NODE_COLORS);
        expect(new Set(values).size).toBe(values.length);
        const baseValues = Object.values(NODE_COLORS);
        for (const color of values) {
            expect(baseValues).not.toContain(color);
        }
    });

    test('a Base KG Event and an Investigation Event never share a color', () => {
        const baseEvent = getNodeColor({ source: 'base_kg', label: 'Event' });
        const investigationEvent = getNodeColor({ source: 'investigation', label: 'InvestigationEvent' });
        expect(baseEvent).toBe(NODE_COLORS.Event);
        expect(investigationEvent).toBe(INVESTIGATION_NODE_COLORS['investigation:InvestigationEvent']);
        expect(baseEvent).not.toBe(investigationEvent);
    });

    test('base nodes reuse the KnowledgeGraph palette and fall back to slate', () => {
        expect(getNodeColor({ source: 'base_kg', label: 'File' })).toBe(NODE_COLORS.File);
        expect(getNodeColor({ source: 'base_kg', label: 'Whatever' })).toBe(BASE_NODE_COLOR_FALLBACK);
        expect(getNodeColor(null)).toBe(BASE_NODE_COLOR_FALLBACK);
    });

    test('color keys are composed from source and label', () => {
        expect(colorKeyForNode({ source: 'investigation', label: 'Claim' })).toBe('investigation:Claim');
        expect(colorKeyForNode({ source: 'base_kg', label: 'Event' })).toBe('base_kg:Event');
    });

    test('overlay link kinds get their own colors and base relations keep the slate default', () => {
        expect(getLinkColor({ kind: 'claim_evidence' })).not.toBe(getLinkColor({ kind: 'base_relation' }));
        expect(getLinkColor({})).toBe(getLinkColor({ kind: 'base_relation' }));
    });
});

describe('isUnconfirmed review-state semantics', () => {
    test('only Analysis and Claim can be unconfirmed', () => {
        expect(isUnconfirmed({ source: 'investigation', label: 'Analysis', confirmed: false })).toBe(true);
        expect(isUnconfirmed({ source: 'investigation', label: 'Claim', confirmed: false })).toBe(true);
        // Evidence/Event never inherit an analysis review state.
        expect(isUnconfirmed({ source: 'investigation', label: 'Evidence', confirmed: false })).toBe(false);
        expect(isUnconfirmed({ source: 'investigation', label: 'InvestigationEvent', confirmed: false })).toBe(false);
        expect(isUnconfirmed({ source: 'investigation', label: 'Analysis', confirmed: true })).toBe(false);
        expect(isUnconfirmed({ source: 'investigation', label: 'Analysis' })).toBe(false);
        expect(isUnconfirmed({ source: 'base_kg', label: 'Analysis', confirmed: false })).toBe(false);
    });
});

describe('parseNodeId exact deterministic IDs', () => {
    test('splits at the first colon so colon-bearing evidence keys stay intact', () => {
        expect(parseNodeId('evidence:file:\\case-1')).toEqual({
            namespace: 'evidence',
            value: 'file:\\case-1',
        });
        expect(parseNodeId('event:e-123')).toEqual({ namespace: 'event', value: 'e-123' });
        expect(parseNodeId('analysis:a-9')).toEqual({ namespace: 'analysis', value: 'a-9' });
        expect(parseNodeId('claim:c-7')).toEqual({ namespace: 'claim', value: 'c-7' });
    });

    test('Graphiti uuids without an overlay namespace stay base_kg', () => {
        expect(parseNodeId('0f4c2a1b-1111-2222-3333-444455556666')).toEqual({
            namespace: 'base_kg',
            value: '0f4c2a1b-1111-2222-3333-444455556666',
        });
        // unknown prefix cannot be an overlay node
        expect(parseNodeId('something:else')).toEqual({ namespace: 'base_kg', value: 'something:else' });
        expect(parseNodeId('')).toEqual({ namespace: 'base_kg', value: '' });
    });
});

describe('tooltip builders escape untrusted text', () => {
    test('claim tooltips escape HTML and surface grounding metadata', () => {
        const html = nodeTooltip({
            id: 'claim:c-1',
            name: '<script>alert(1)</script>',
            label: 'Claim',
            source: 'investigation',
            confirmed: false,
            provenance: { claim_id: 'c-1', claim_type: 'FACT', grounding_status: 'grounded' },
        });
        expect(html).not.toContain('<script>');
        expect(html).toContain('&lt;script&gt;');
        expect(html).toContain('FACT');
        expect(html).toContain('grounded');
        expect(html).toContain('<b>Unconfirmed</b>');
    });

    test('event tooltips show the current version; analysis tooltips show review state', () => {
        expect(
            nodeTooltip({
                id: 'event:e1',
                name: 'USB insertion',
                label: 'InvestigationEvent',
                source: 'investigation',
                provenance: { event_id: 'e1', version: 3 },
            }),
        ).toContain('v3');
        expect(
            nodeTooltip({
                id: 'analysis:a1',
                name: 'Analysis v2 - file:/x',
                label: 'Analysis',
                source: 'investigation',
                confirmed: true,
                provenance: { analysis_id: 'a1', review_state: 'accepted', version: 2, evidence_key: 'file:/x' },
            }),
        ).toContain('accepted');
    });

    test('base tooltips show name/label/summary and link tooltips escape labels', () => {
        expect(
            nodeTooltip({ id: 'u1', name: 'Bob', label: 'User', source: 'base_kg', summary: 'account <b>bob</b>' }),
        ).toContain('account &lt;b&gt;bob&lt;/b&gt;');
        expect(linkTooltip({ label: 'REFERENCES_EVIDENCE' })).toBe('REFERENCES_EVIDENCE');
        expect(linkTooltip({ label: '<img src=x>' })).not.toContain('<img');
    });
});
