import { describe, expect, test } from 'vitest';
import {
    normalizeWeChatGraph,
    normalizeWeChatTimeline,
} from './useWeChatGraph';

describe('WeChat graph response compatibility', () => {
    test('normalizes API edges and community member details for graph consumers', () => {
        const graph = normalizeWeChatGraph({
            nodes: [{ id: 'alice' }, { id: 'bob', community: 1 }],
            edges: [{ source: 'alice', target: 'bob', weight: 2 }],
            communities: [
                {
                    community_id: 0,
                    members: [{ username: 'alice', label: 'Alice' }],
                },
            ],
        });

        expect(graph.links).toEqual(graph.edges);
        expect(graph.nodes[0]).toMatchObject({ cluster: 0, community: 0 });
        expect(graph.nodes[1]).toMatchObject({ cluster: 1, community: 1 });
        expect(graph.communities[0]).toMatchObject({
            cluster: 0,
            label: '社区 1',
        });
    });

    test('accepts legacy links and timeline payloads', () => {
        expect(normalizeWeChatGraph({
            nodes: [],
            links: [{ source: 'a', target: 'b' }],
        }).edges).toHaveLength(1);
        expect(normalizeWeChatTimeline({
            intervals: [{ period: '2024-01', total_messages: 3 }],
        })).toEqual([{ period: '2024-01', total_messages: 3 }]);
        expect(normalizeWeChatTimeline({
            timeline: [{ period: '2024-02', total_messages: 4 }],
        })).toEqual([{ period: '2024-02', total_messages: 4 }]);
    });
});
