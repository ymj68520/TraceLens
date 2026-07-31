export class ReportDataSource {
  async listVersions() { throw new Error('not implemented'); }
  async createVersion() { throw new Error('not implemented'); }
  async getStatus() { throw new Error('not implemented'); }
  async getManifest() { throw new Error('not implemented'); }
  async getCategoryPage() { throw new Error('not implemented'); }
  async search() { throw new Error('not implemented'); }
  getPreviewUrl() { throw new Error('not implemented'); }
  getOfflineBundleUrl() { throw new Error('not implemented'); }
}

export class HttpReportDataSource extends ReportDataSource {
  constructor(client) {
    super();
    this.client = client;
  }

  listVersions(scopeType, scopeId) {
    return this.client.get('/api/reports', {
      params: { scope_type: scopeType, scope_id: scopeId },
    });
  }

  createVersion(scopeType, scopeId) {
    return this.client.post('/api/reports', {
      scope_type: scopeType,
      scope_id: scopeId,
    });
  }

  getStatus(reportId) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/status`);
  }

  getManifest(reportId) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/manifest`);
  }

  getCategoryPage(reportId, categoryId, page) {
    return this.client.get(
      `/api/reports/${encodeURIComponent(reportId)}/categories/${encodeURIComponent(categoryId)}/pages/${page}`,
    );
  }

  search(reportId, query, { offset = 0, limit = 50 } = {}) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/search`, {
      params: { q: query, offset, limit },
    });
  }

  getPreviewUrl(reportId, attachment) {
    return attachment.preview_path
      ? `/api/reports/${encodeURIComponent(reportId)}/previews/${encodeURIComponent(attachment.attachment_id)}`
      : null;
  }

  getOfflineBundleUrl(reportId) {
    return `/api/reports/${encodeURIComponent(reportId)}/offline`;
  }
}

export class FixtureReportDataSource extends ReportDataSource {
  constructor(fixture) {
    super();
    this.fixture = fixture;
  }

  async listVersions() { return this.fixture.versions || []; }
  async createVersion() { throw new Error('fixture data source is read-only'); }

  async getStatus(reportId) {
    return (this.fixture.versions || []).find((item) => item.report_id === reportId) || null;
  }

  async getManifest(reportId) { return this.fixture.manifests[reportId]; }

  async getCategoryPage(reportId, categoryId, page) {
    return this.fixture.pages[`${reportId}:${categoryId}:${page}`];
  }

  async search(reportId, query) {
    return this.fixture.searches?.[`${reportId}:${query}`] || { total: 0, hits: [] };
  }

  getPreviewUrl(_reportId, attachment) { return attachment.preview_path || null; }
  getOfflineBundleUrl() { return null; }
}
