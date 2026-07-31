import { screen } from '@testing-library/react';
import { renderWithRouter } from '../../../test/renderWithRouter';
import GenericTableRenderer from './GenericTableRenderer';

test('shows full sensitive text and uniform forensic badges', () => {
  renderWithRouter(<GenericTableRenderer records={[{
    record_id: 'rec_1', title: 'WiFi', data_state: 'deleted', severity: 'high',
    is_relevant: true, source_path: '/data/misc/wifi/WifiConfigStore.xml',
    source_table: 'wifi_networks', source_record_id: '7',
    fields: { pre_shared_key: 'CorrectHorseBatteryStaple' },
    hashes: {}, attachments: [], analysis_references: [{ chapter: '证据分析' }],
  }]} />);

  expect(screen.getByText('CorrectHorseBatteryStaple')).toBeInTheDocument();
  expect(screen.getByText('已删除')).toBeInTheDocument();
  expect(screen.getByText('高风险')).toBeInTheDocument();
  expect(screen.getByText('重点证据')).toBeInTheDocument();
  expect(screen.getByText('被 证据分析 引用')).toBeInTheDocument();
});

test('derives the current page table columns from every record field', () => {
  renderWithRouter(<GenericTableRenderer records={[
    {
      record_id: 'rec_1', title: 'One', data_state: 'existing', severity: 'info',
      is_relevant: false, source_table: 'table', source_record_id: '1',
      fields: { first: 'first-value' }, hashes: {}, attachments: [], analysis_references: [],
    },
    {
      record_id: 'rec_2', title: 'Two', data_state: 'existing', severity: 'info',
      is_relevant: false, source_table: 'table', source_record_id: '2',
      fields: { second: 'second-value' }, hashes: {}, attachments: [], analysis_references: [],
    },
  ]} />);

  expect(screen.getByRole('columnheader', { name: 'first' })).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: 'second' })).toBeInTheDocument();
  expect(screen.getByText('second-value')).toBeInTheDocument();
});

test('renders source metadata, hashes, and attachment provenance without clipping the record table', () => {
  const { container } = renderWithRouter(<GenericTableRenderer records={[{
    record_id: 'rec_3', title: 'Artifact', data_state: 'recovered', severity: 'critical',
    is_relevant: false, source_path: '/evidence/artifact.db', source_table: 'artifacts',
    source_record_id: 'row-9', fields: {}, hashes: { sha256: 'deadbeef' },
    attachments: [{
      attachment_id: 'att-1', file_name: 'payload.bin', evidence_path: '/evidence/payload.bin',
      size: 2048, mime: 'application/octet-stream', hashes: { md5: 'cafebabe' },
      original_included: true,
    }],
    analysis_references: [],
  }]} />);

  expect(container.querySelector('.overflow-x-auto')).toBeInTheDocument();
  expect(screen.getByText('/evidence/artifact.db')).toBeInTheDocument();
  expect(screen.getByText('artifacts')).toBeInTheDocument();
  expect(screen.getByText('row-9')).toBeInTheDocument();
  expect(screen.getByText('deadbeef')).toBeInTheDocument();
  expect(screen.getByText('payload.bin')).toBeInTheDocument();
  expect(screen.getByText('/evidence/payload.bin')).toBeInTheDocument();
  expect(screen.getByText(/md5/)).toBeInTheDocument();
  expect(screen.getByText(/已包含原始文件/)).toBeInTheDocument();
});
