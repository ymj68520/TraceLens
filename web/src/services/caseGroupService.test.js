import { beforeEach, expect, test, vi } from 'vitest';
import api, { pythonApi } from './api';
import { addTasksToCase, associateTasksToCase, caseTaskAnalysisOptions, createCase, deleteCase,
  getCase, listCases, startMultiImageAnalysis } from './caseGroupService';
vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  pythonApi: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../config/runtime', () => ({ FIELD_AUTH_ENABLED: true }));
beforeEach(() => vi.resetAllMocks());

test('case list/read/create/delete use authoritative metadata API, never disabled LLM prefix', async () => {
  api.get.mockResolvedValue({ cases: [{ id: 'c1' }], total: 1 });
  expect(await listCases()).toEqual({ cases: [{ id: 'c1' }], total: 1 });
  await getCase('c1');await createCase('name','context',['t1']);await deleteCase('c1');
  expect(api.get).toHaveBeenCalledWith('/api/cases');
  expect(api.get).toHaveBeenCalledWith('/api/cases/c1');
  expect(api.post).toHaveBeenCalledWith('/api/cases',{ name:'name',description:'context',task_ids:['t1'] });
  expect(api.delete).toHaveBeenCalledWith('/api/cases/c1');
  expect(pythonApi.get).not.toHaveBeenCalled();expect(pythonApi.post).not.toHaveBeenCalled();
});
test('task metadata update uses PUT and confirms returned linkage', async () => {
  api.put.mockResolvedValue({ id:'c1',task_ids:['t1'] });
  await addTasksToCase('c1',['t1','t1']);
  expect(api.put).toHaveBeenCalledWith('/api/cases/c1/tasks',{ task_ids:['t1'] });
});
test('missing/malformed update is not reported as a successful association', async () => {
  api.put.mockResolvedValue({ id:'',task_ids:[] });
  await expect(addTasksToCase('c1',['t1'])).rejects.toThrow('未确认');
});
test('association filters incomplete/missing tasks, skips linked IDs, does not claim AI state was prepared', async () => {
  api.get.mockImplementation((path) => {
    if(path==='/api/cases/c1')return Promise.resolve({ id:'c1',task_ids:['already'] });
    if(path.endsWith('/done'))return Promise.resolve({ id:'done',status:'COMPLETED',output_files_db:'/synthetic/files.db' });
    if(path.endsWith('/running'))return Promise.resolve({ id:'running',status:'running' });
    return Promise.reject({ status:404 });
  });
  api.put.mockResolvedValue({ id:'c1',task_ids:['already','done'] });
  const result=await associateTasksToCase('c1',['already','done','done','running','missing']);
  expect(result).toMatchObject({ associated:['done'],skipped:['already'],not_completed:['running'],not_found:['missing'],
    reused:[],analysis_state_prepared:false });
  expect(api.put).toHaveBeenCalledOnce();expect(pythonApi.post).not.toHaveBeenCalled();
});
test('all-already-linked association is idempotent', async () => {
  api.get.mockResolvedValue({ id:'c1',task_ids:['t1'] });
  expect((await associateTasksToCase('c1',['t1'])).skipped).toEqual(['t1']);
  expect(api.put).not.toHaveBeenCalled();
});
test('permission errors are not swallowed as task-not-found', async () => {
  api.get.mockResolvedValueOnce({ id:'c1',task_ids:[] }).mockRejectedValueOnce({ status:403 });
  await expect(associateTasksToCase('c1',['t1'])).rejects.toMatchObject({ status:403 });
  expect(api.put).not.toHaveBeenCalled();
});
test('disabled model policy does not force AI for new image tasks', async () => {
  pythonApi.get.mockResolvedValue({ field_auth:true,outbound_policy:'disabled' });
  expect(await caseTaskAnalysisOptions()).toEqual({ llm_analyze:false,llm_event_analyze:false });
});
test('unavailable policy fails closed before creating image tasks', async () => {
  pythonApi.get.mockResolvedValue({});
  await expect(caseTaskAnalysisOptions()).rejects.toThrow();
});
test('AI run is still an explicit separate optional call', async () => {
  await startMultiImageAnalysis({ caseId:'c1',taskIds:['t1'],filesDbPaths:['/synthetic/files.db'],caseDescription:'context' });
  expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/multi-image-analysis',expect.objectContaining({ case_id:'c1' }));
  expect(api.post).not.toHaveBeenCalled();
});
