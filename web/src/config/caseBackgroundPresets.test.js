import { expect, test } from 'vitest';
import {
  CASE_BACKGROUND_PRESETS,
  PRESET_GROUPS,
  getPresetById,
  matchPresetId,
  presetsByGroup,
} from './caseBackgroundPresets';

test('every preset has the fields the picker and prompts rely on', () => {
  const ids = new Set();
  for (const preset of CASE_BACKGROUND_PRESETS) {
    expect(preset.id).toMatch(/^[a-z0-9_]+$/);
    expect(ids.has(preset.id)).toBe(false);
    ids.add(preset.id);

    expect(preset.label.length).toBeGreaterThan(0);
    expect(preset.icon.length).toBeGreaterThan(0);
    expect(preset.summary.length).toBeGreaterThan(0);
    expect(PRESET_GROUPS.some((g) => g.key === preset.group)).toBe(true);

    // The background text goes straight into LLM prompts, so it must be a
    // usable paragraph rather than a placeholder.
    expect(preset.background.length).toBeGreaterThan(80);
    expect(preset.background).not.toMatch(/TODO|待补充|示例/);
  }
});

test('presets cover the mainstream forensic scenarios', () => {
  const ids = CASE_BACKGROUND_PRESETS.map((p) => p.id);
  for (const required of [
    'telecom_fraud', 'malware_infection', 'ransomware', 'data_breach',
    'homicide', 'android_mobile', 'windows_workstation', 'linux_server',
    'memory_forensics', 'cloud_oss',
  ]) {
    expect(ids).toContain(required);
  }
  // Every group has at least one entry, so no picker tab renders empty.
  for (const group of PRESET_GROUPS) {
    expect(CASE_BACKGROUND_PRESETS.some((p) => p.group === group.key)).toBe(true);
  }
});

test('preset backgrounds are unique so text matching is unambiguous', () => {
  const bodies = CASE_BACKGROUND_PRESETS.map((p) => p.background);
  expect(new Set(bodies).size).toBe(bodies.length);
});

test('matchPresetId detects a preset after trimming and ignores edits', () => {
  const preset = getPresetById('telecom_fraud');
  expect(matchPresetId(`  ${preset.background}\n`)).toBe('telecom_fraud');
  expect(matchPresetId(`${preset.background}补充一句`)).toBe('');
  expect(matchPresetId('')).toBe('');
  expect(matchPresetId('   ')).toBe('');
  expect(matchPresetId(undefined)).toBe('');
});

test('recommended filter profiles reference names that can be selected', () => {
  // These are the profile_name values shipped in config/filter_profiles plus
  // the two Chinese-named site profiles; an unknown name would leave the
  // filter selector showing nothing.
  const known = new Set([
    'general_forensics', 'virus_intrusion', 'telecom_fraud', 'data_breach',
    '诈骗平台服务器专项', '诈骗窝点工作站专项',
  ]);
  for (const preset of CASE_BACKGROUND_PRESETS) {
    for (const name of preset.filterProfiles || []) {
      expect(known.has(name)).toBe(true);
    }
    for (const scenario of preset.scenarios || []) {
      expect(['android', 'windows', 'linux', 'server_cloud']).toContain(scenario);
    }
  }
});

test('presetsByGroup keeps group order and drops empty groups', () => {
  const groups = presetsByGroup();
  expect(groups.length).toBeGreaterThan(0);
  expect(groups.every((g) => g.presets.length > 0)).toBe(true);
  const keys = groups.map((g) => g.key);
  const expected = PRESET_GROUPS.filter((g) => keys.includes(g.key)).map((g) => g.key);
  expect(keys).toEqual(expected);
  expect(groups.flatMap((g) => g.presets).length).toBe(CASE_BACKGROUND_PRESETS.length);
});
