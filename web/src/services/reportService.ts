import type { AxiosInstance } from 'axios';
import { pythonApi } from './api';

/** Structured report snapshot data source (R-series contracts). */

export interface ReportAttachment {
  attachment_id: string;
  preview_path?: string;
  [key: string]: unknown;
}

export interface ReportDataSource {
  listVersions(scopeType: string, scopeId: string): Promise<unknown>;
  createVersion(scopeType: string, scopeId: string): Promise<unknown>;
  getStatus(reportId: string): Promise<unknown>;
  getManifest(reportId: string): Promise<unknown>;
  getCategoryPage(reportId: string, categoryId: string, page: number): Promise<unknown>;
  search(reportId: string, query: string, opts?: { offset?: number; limit?: number }): Promise<unknown>;
  getPreviewUrl(reportId: string, attachment: ReportAttachment): string | null;
  getOfflineBundleUrl(reportId: string): string | null;
}

export class HttpReportDataSource implements ReportDataSource {
  constructor(private client: AxiosInstance) {}

  listVersions(scopeType: string, scopeId: string) {
    return this.client.get('/api/reports', {
      params: { scope_type: scopeType, scope_id: scopeId },
    }) as unknown as Promise<unknown>;
  }

  createVersion(scopeType: string, scopeId: string) {
    return this.client.post('/api/reports', {
      scope_type: scopeType,
      scope_id: scopeId,
    }) as unknown as Promise<unknown>;
  }

  getStatus(reportId: string) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/status`) as unknown as Promise<unknown>;
  }

  getManifest(reportId: string) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/manifest`) as unknown as Promise<unknown>;
  }

  getCategoryPage(reportId: string, categoryId: string, page: number) {
    return this.client.get(
      `/api/reports/${encodeURIComponent(reportId)}/categories/${encodeURIComponent(categoryId)}/pages/${page}`,
    ) as unknown as Promise<unknown>;
  }

  search(reportId: string, query: string, { offset = 0, limit = 50 } = {}) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/search`, {
      params: { q: query, offset, limit },
    }) as unknown as Promise<unknown>;
  }

  getPreviewUrl(reportId: string, attachment: ReportAttachment): string | null {
    return attachment.preview_path
      ? `/api/reports/${encodeURIComponent(reportId)}/previews/${encodeURIComponent(attachment.attachment_id)}`
      : null;
  }

  getOfflineBundleUrl(reportId: string): string | null {
    return `/api/reports/${encodeURIComponent(reportId)}/offline`;
  }
}

export const reportDataSource = new HttpReportDataSource(pythonApi);

export const listReportVersions = (scopeType: string, scopeId: string) =>
  reportDataSource.listVersions(scopeType, scopeId);
export const createReportVersion = (scopeType: string, scopeId: string) =>
  reportDataSource.createVersion(scopeType, scopeId);
export const getReportStatus = (reportId: string) => reportDataSource.getStatus(reportId);
export const getReportManifest = (reportId: string) => reportDataSource.getManifest(reportId);
export const getReportCategoryPage = (reportId: string, categoryId: string, page: number) =>
  reportDataSource.getCategoryPage(reportId, categoryId, page);
export const searchReport = (reportId: string, query: string, opts?: { offset?: number; limit?: number }) =>
  reportDataSource.search(reportId, query, opts);
