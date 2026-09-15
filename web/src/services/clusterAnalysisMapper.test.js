import { expect, test } from 'vitest';
import {
  availableBucketSeconds,
  mapClusterAnalysisRecords,
} from './clusterAnalysisMapper';

const record = (overrides = {}) => ({
  id: 1,
  task_id: 't',
  bucket_epoch_offset: 0,
  bucket_seconds: 60,
  bucket_index: 2,
  event_type: 'MODIFIED',
  parent_directory: '/foo/',
  member_count: 3,
  member_min_id: 1,
  member_max_id: 9,
  members_hash: 'h',
  summary: 'summary text',
  description: 'description text',
  keywords: 'k1, k2',
  model: 'test-model',
  trigger_source: 'pipeline',
  analysis_id_upstream: null,
  created_at: 100,
  ingested_at: null,
  ...overrides,
});

test('maps an analysis record to the legacy cluster-card shape', () => {
  const [card] = mapClusterAnalysisRecords([record()]);

  expect(card).toMatchObject({
    id: 1,
    analysis_id: 1,
    event_type: 'MODIFIED',
    parent_directory: '/foo/',
    cluster_count: 3,
    llm_summary: 'summary text',
    llm_keywords: 'k1, k2',
    llm_analyzed_at: 100,
    llm_model_used: 'test-model',
    trigger_source: 'pipeline',
    is_latest: true,
    versions: 1,
    // window start = index * seconds + offset
    timestamp: 120,
    llm_is_relevant: 1,
  });
});

test('marks the newest version per coordinate and counts versions', () => {
  const cards = mapClusterAnalysisRecords([
    record({ id: 1, summary: 'v1', created_at: 1 }),
    record({ id: 3, summary: 'v3', created_at: 3, bucket_seconds: 300 }),
    record({ id: 2, summary: 'v2', created_at: 2 }),
  ]);

  const byId = new Map(cards.map((card) => [card.id, card]));
  expect(byId.get(1).is_latest).toBe(false);
  expect(byId.get(2).is_latest).toBe(true);
  expect(byId.get(3).is_latest).toBe(true);
  expect(byId.get(1).versions).toBe(2);
  expect(byId.get(2).versions).toBe(2);
  // Newest first for stable display.
  expect(cards.map((card) => card.id)).toEqual([3, 2, 1]);
});

test('separate coordinates never share version state', () => {
  const cards = mapClusterAnalysisRecords([
    record({ id: 1, event_type: 'MODIFIED' }),
    record({ id: 2, event_type: 'CREATED' }),
  ]);
  expect(cards.every((card) => card.is_latest && card.versions === 1)).toBe(true);
});

test('availableBucketSeconds lists distinct windows ascending', () => {
  const records = [
    record({ bucket_seconds: 300 }),
    record({ bucket_seconds: 60 }),
    record({ bucket_seconds: 60 }),
  ];
  expect(availableBucketSeconds(records)).toEqual([60, 300]);
  expect(availableBucketSeconds([])).toEqual([]);
});
