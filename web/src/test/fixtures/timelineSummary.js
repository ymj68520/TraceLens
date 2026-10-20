// Synthetic contract fixture; contains no case data.
export function timelineSummaryFixture({ truncated = false, communication = true } = {}) {
  const context = {
    context_id: 'a'.repeat(64), source_version: 'b'.repeat(64), scanned_content_hash: 'c'.repeat(64),
    statistics_version: 'timeline-summary:v1', scope: { kind: communication ? 'wechat_import' : 'events', scope_id: 'synthetic-T',
      record_origin: communication ? 'decrypted_import_table' : 'derived_event_table', timestamp_unit: communication ? 'milliseconds' : 'seconds' },
    filters: { timezone: 'Asia/Shanghai', start_date: null, end_date: null, event_type: '', direction: 'all' },
    counts: { valid_records: 6, missing_records: 1, invalid_records: 1, inferred_records: 1,
      processing_records: 1, duplicate_records: 1, identity_conflict_records: 0, scanned_records: 11,
      outside_time_records: 0, outside_direction_records: 0 },
    candidate_records: truncated ? 111 : 11,
    coverage: { truncated, unscanned_records: truncated ? 100 : 0, missing_tables: [],
      daily_truncated: false, displayed_days_limit: 3660, observed_days: 3,
      first_observed_time: 1767276000, last_observed_time: 1767448800,
      quality_scope: '缺失/无效时间来自同一非时间筛选范围，无法判断其是否落在所选日期内。' },
    deduplication: { description: '仅合并同一来源、相同原始记录标识且内容一致的记录；冲突记录保留。', identity: '合成消息标识' },
  };
  const item = value => ({ context_id: context.context_id, ...value });
  const hours = Array.from({ length: 24 }, (_, hour) => item({ hour, count: hour === 22 ? 6 : 0,
    share: hour === 22 ? 1 : 0, observed_days: hour === 22 ? 3 : 0, observed_day_denominator: 3, selector: { hour } }));
  return {
    context, summary: item({ text: '合成记录在22时出现6条，分布在3个日期。' }),
    warnings: ['统计范围内没有记录不等于没有活动。', '收到消息不证明账号主人当时操作。'],
    hours, repeated_hours: [hours[22]],
    heatmap: Array.from({ length: 168 }, (_, i) => item({ weekday: Math.floor(i / 24), hour: i % 24,
      count: i % 24 === 22 && i < 72 ? 2 : 0, selector: { weekday: Math.floor(i / 24), hour: i % 24 } })),
    daily: [1, 3, 4].map((day, i) => item({ day: `2026-01-0${day}`, count: 2,
      previous_count: i === 2 ? 2 : null, delta: i === 2 ? 0 : null, selector: { day: `2026-01-0${day}` } })),
    communication: item({ available: communication, counts: { sent: 3, received: 1, unknown: 1, system: 1 },
      hourly: { sent: hours.map(h => h.hour === 22 ? 3 : 0), received: hours.map(h => h.hour === 22 ? 1 : 0) } }),
    time_bases: communication ? { message: 6 } : { file_metadata: 6 },
  };
}

export function timelineRecordsFixture(context, selection = {}) {
  return {
    context, total: 1, page_truncated: false, selection: { offset: 0, limit: 50, ...selection },
    records: [{ record_ref: 'message:1', original_id: '12345', timestamp_raw: 1767276000000,
      timestamp_iso: '2026-01-01T22:00:00+08:00', direction: 'sent', talker: '合成账号A',
      time_basis: 'message', content: '<img src=x onerror="window.__injected=true">合成消息', content_truncated: false,
      raw_fields: { msgId: 12345, isSend: 1 }, record_sha256: 'd'.repeat(64) }],
  };
}
