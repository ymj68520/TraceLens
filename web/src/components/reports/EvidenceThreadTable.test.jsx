import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import EvidenceThreadTable from './EvidenceThreadTable';

const TABLE = {
    title: '案情线索与研判方向',
    rows: [
        {
            name: 'Quasar 远控驻留',
            contribution: '客户端配置指向 192.168.10.30:4782 并写入注册表启动项，'
                + '服务端配置同端口监听，两端互证；是否实际外联仍缺网络日志。',
            key_facts: ['192.168.10.30:4782', 'HideFile=True', 'Quasar Client Startup'],
            direction_count: 3,
            material_count: 4,
            reference_count: 9,
            chapter_count: 2,
            chapter_numbers: [3, 5],
            citation_ids: ['c002', 'c017'],
        },
        {
            name: '日志解析缺口',
            contribution: '大量 evtx 通道为空，本轮结论仅在可读片段范围内成立。',
            key_facts: [],
            direction_count: 12,
            material_count: 30,
            reference_count: 40,
            chapter_count: 1,
            chapter_numbers: [4],
            citation_ids: [],
        },
    ],
    covered_directions: 15,
    total_directions: 15,
    total_materials: 34,
    notes: ['全部 15 项调查方向已归入 2 条线索，未出现遗漏或重复。'],
};

describe('EvidenceThreadTable', () => {
    test('renders one human-readable row per thread with anchored key facts', () => {
        render(<EvidenceThreadTable table={TABLE} />);
        expect(screen.getByTestId('evidence-thread-table')).toHaveTextContent('案情线索与研判方向');
        expect(screen.getAllByTestId('thread-row')).toHaveLength(2);
        expect(screen.getAllByTestId('thread-contribution')[0]).toHaveTextContent('两端互证');
        for (const fact of TABLE.rows[0].key_facts) {
            expect(screen.getByText(fact)).toBeInTheDocument();
        }
        // Exhaustive coverage is stated, not implied.
        expect(screen.getByTestId('evidence-thread-table'))
            .toHaveTextContent('研判方向 15 项 · 已归入线索 15 项（100%）');
        expect(screen.getByTestId('evidence-thread-table'))
            .toHaveTextContent('未出现遗漏或重复');
    });

    test('chapter numbers jump to the corresponding chapter card', () => {
        const onJumpToChapter = vi.fn();
        render(<EvidenceThreadTable table={TABLE} onJumpToChapter={onJumpToChapter} />);
        fireEvent.click(screen.getByTestId('thread-chapter-3'));
        expect(onJumpToChapter).toHaveBeenCalledWith(3);
        fireEvent.click(screen.getByTestId('thread-chapter-5'));
        expect(onJumpToChapter).toHaveBeenCalledWith(5);
    });

    test('renders nothing without a table and a notice without rows', () => {
        const { container } = render(<EvidenceThreadTable table={null} />);
        expect(container).toBeEmptyDOMElement();
        render(<EvidenceThreadTable table={{ ...TABLE, rows: [] }} />);
        expect(screen.getByText('本轮没有可归入线索的调查方向。')).toBeInTheDocument();
    });
});
