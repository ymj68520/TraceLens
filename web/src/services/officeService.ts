/** Office document parsing — Python sidecar. */
import { pythonApi } from './api';

export const parseFile = (taskId: string, filePath: string) =>
  pythonApi.post('/api/office/parse', { task_id: taskId, file_path: filePath });

export const getSupportedFormats = () =>
  pythonApi.get('/api/office/supported-types');
