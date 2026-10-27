import { configureStore } from '@reduxjs/toolkit';
import { beforeEach,expect,test,vi } from 'vitest';
import reducer,{createCaseWithTasks,fetchCases} from './caseSlice';
import * as cases from '../services/caseGroupService';
import * as tasks from '../services/taskService';
vi.mock('../services/caseGroupService',()=>({ listCases:vi.fn(),createCase:vi.fn(),associateTasksToCase:vi.fn(),caseTaskAnalysisOptions:vi.fn() }));
vi.mock('../services/taskService',()=>({ createTask:vi.fn() }));
beforeEach(()=>vi.resetAllMocks());
const store=()=>configureStore({ reducer:{cases:reducer} });
test('existing-task composition only creates case metadata, never a new scan or AI state',async()=>{
 cases.createCase.mockResolvedValue({id:'c1',task_ids:['t1','t2']});
 const result=await store().dispatch(createCaseWithTasks({name:'case',description:'context',associateTaskIds:['t1','t2','t1']})).unwrap();
 expect(cases.createCase).toHaveBeenCalledWith('case','context',['t1','t2']);
 expect(tasks.createTask).not.toHaveBeenCalled();expect(cases.associateTasksToCase).not.toHaveBeenCalled();
 expect(cases.caseTaskAnalysisOptions).not.toHaveBeenCalled();expect(result.tasks).toEqual([]);
});
test('new synthetic image tasks respect disabled AI instead of forcing an LLM call',async()=>{
 cases.caseTaskAnalysisOptions.mockResolvedValue({llm_analyze:false,llm_event_analyze:false});
 tasks.createTask.mockResolvedValue({id:'new-t1'});cases.createCase.mockResolvedValue({id:'c1'});
 await store().dispatch(createCaseWithTasks({name:'case',description:'context',imagePaths:['/synthetic/input.img']})).unwrap();
 expect(tasks.createTask).toHaveBeenCalledWith(expect.objectContaining({image_path:'/synthetic/input.img',llm_analyze:false}));
});
test('a case-level analysis budget is forwarded to every new image task',async()=>{
 cases.caseTaskAnalysisOptions.mockResolvedValue({llm_analyze:true,llm_event_analyze:false});
 tasks.createTask.mockResolvedValueOnce({id:'new-t1'}).mockResolvedValueOnce({id:'new-t2'});
 cases.createCase.mockResolvedValue({id:'c1'});
 await store().dispatch(createCaseWithTasks({name:'case',description:'context',imagePaths:['/a.img','/b.img'],llmMaxFiles:300})).unwrap();
 expect(tasks.createTask).toHaveBeenCalledTimes(2);
 for (const call of tasks.createTask.mock.calls) expect(call[0]).toMatchObject({llm_max_files:300});
});
test('an unset case-level budget leaves the server default in charge',async()=>{
 cases.caseTaskAnalysisOptions.mockResolvedValue({llm_analyze:true,llm_event_analyze:false});
 tasks.createTask.mockResolvedValue({id:'new-t1'});cases.createCase.mockResolvedValue({id:'c1'});
 await store().dispatch(createCaseWithTasks({name:'case',description:'context',imagePaths:['/a.img']})).unwrap();
 expect(tasks.createTask.mock.calls[0][0]).not.toHaveProperty('llm_max_files');
});
test('case loading recovers cleanly from a previous endpoint failure',async()=>{
 const s=store();cases.listCases.mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce({cases:[{id:'c1'}],total:1});
 await s.dispatch(fetchCases());expect(s.getState().cases.status).toBe('failed');
 await s.dispatch(fetchCases());expect(s.getState().cases).toMatchObject({status:'succeeded',error:null,cases:[{id:'c1'}]});
});
