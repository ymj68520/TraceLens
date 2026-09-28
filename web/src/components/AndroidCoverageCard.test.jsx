import { render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import AndroidCoverageCard from './AndroidCoverageCard';
import { getAndroidSourceCoverage } from '../services/evidenceIntakeService';

vi.mock('../services/evidenceIntakeService', () => ({
  getAndroidSourceCoverage: vi.fn(),
  androidCoverageManifestUrl: (id) => `/coverage/${id}`,
  androidNormalizationManifestUrl: (id) => `/normalization/${id}`,
}));
beforeEach(() => vi.clearAllMocks());

test('distinguishes a missing source from an absence of evidence', async () => {
  getAndroidSourceCoverage.mockResolvedValue({ coverage: {
    available: true, coverage_recorded: true, warnings: ['Some sources were not parsed'],
    artifact_counts: { wechat_messages: 1 },
    sources: [{ artifact_kind: 'wechat', source_path: 'data/data/account/EnMicroMsg.db',
      status: 'no_candidate_path', detail: 'not found in this extraction' }],
  } });
  render(<AndroidCoverageCard taskId="task-a" />);
  expect(await screen.findByText(/未找到候选文件/)).toBeInTheDocument();
  expect(screen.getByText(/不能证明数据不存在/)).toBeInTheDocument();
  expect(screen.getByText(/wechat_messages: 1/)).toBeInTheDocument();
  expect(getAndroidSourceCoverage).toHaveBeenCalledWith('task-a');
});

test('legacy Android database has a clear coverage warning', async () => {
  getAndroidSourceCoverage.mockResolvedValue({ coverage: {
    available: true, coverage_recorded: false,
    warnings: ['旧版任务未记录来源覆盖'], artifact_counts: {}, sources: [],
  } });
  render(<AndroidCoverageCard taskId="legacy" />);
  expect(await screen.findByText('旧版任务未记录来源覆盖')).toBeInTheDocument();
});

test('final report can cite and download the image coverage manifest', async () => {
  getAndroidSourceCoverage.mockResolvedValue({ coverage: {
    available: true, coverage_recorded: true, warnings: [], artifact_counts: {}, sources: [],
    manifest: { filesystem: 'f2fs', encryption: 'FBE_DETECTED', container: 'e01',
      partition: { offset: '9437184' }, reader: 'qnxprobe 1.34',
      source_image_sha256: 'a'.repeat(64), artifact_types: {} },
  } });
  render(<AndroidCoverageCard taskId="task-image" />);
  const link = await screen.findByRole('link', { name: '下载本报告引用的覆盖清单' });
  expect(link).toHaveAttribute('href', '/coverage/task-image');
  expect(screen.getByText(/来源 SHA-256/)).toHaveTextContent('a'.repeat(64));
});

test('super normalization states userdata is not present and EROFS is unsupported', async () => {
  getAndroidSourceCoverage.mockResolvedValue({ coverage: {
    available: true, coverage_recorded: true, warnings: [], artifact_counts: {}, sources: [],
    manifest: { filesystem: 'not_applicable', encryption: 'UNKNOWN', container: 'android-container',
      partition: {}, reader: 'AOSP liblp', source_image_sha256: 'b'.repeat(64),
      artifact_types: {}, userdata: { status: 'NOT_PRESENT_IN_SOURCE' } },
    normalization_manifest: { kind: 'ANDROID_SPARSE_SUPER', selected_slot: 0,
      userdata: { status: 'NOT_PRESENT_IN_SOURCE' },
      partition_provenance: [{ logical_partition_name: 'product_a',
        filesystem_type: 'EROFS', derived_partition_sha256: 'c'.repeat(64) }] },
  } });
  render(<AndroidCoverageCard taskId="task-super" />);
  expect(await screen.findByText(/super 来源不包含 userdata/)).toBeInTheDocument();
  expect(screen.getByText(/product_a/)).toHaveTextContent('UNSUPPORTED_FILESYSTEM');
  expect(screen.getByRole('link', { name: '下载完整规范化来源链' })).toHaveAttribute('href', '/normalization/task-super');
});
