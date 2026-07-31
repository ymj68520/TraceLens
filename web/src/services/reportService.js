import { pythonApi } from './api';
import { HttpReportDataSource } from './reportDataSource';

export const reportDataSource = new HttpReportDataSource(pythonApi);
export const listReportVersions = (...args) => reportDataSource.listVersions(...args);
export const createReportVersion = (...args) => reportDataSource.createVersion(...args);
export const getReportStatus = (...args) => reportDataSource.getStatus(...args);
export const getReportManifest = (...args) => reportDataSource.getManifest(...args);
export const getReportCategoryPage = (...args) => reportDataSource.getCategoryPage(...args);
export const searchReport = (...args) => reportDataSource.search(...args);
