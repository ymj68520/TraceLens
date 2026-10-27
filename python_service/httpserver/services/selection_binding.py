"""Bind each existing file-analysis operation to one native selection run."""
from contextlib import closing
from pathlib import Path
from .source_identity import file_row,decode_reference,analysis_reference,SourceIdentityError
from .source_reading import connect
from .extraction_layout import candidate_roots


def canonical_references(task,paths):
    roots=candidate_roots(task.get('extraction_directory') or Path(task['output_files_db']).parent/'extracted_files')
    result=[]
    with closing(connect(task['output_files_db'])) as db:
        for original in paths:
            logical,sid=decode_reference(original)
            try:row,_=file_row(db,logical,sid)
            except SourceIdentityError as error:
                if error.code!='SOURCE_NOT_FOUND' or sid:raise
                matches=[]
                for root in roots:
                    try:relative=Path(original).relative_to(root)
                    except ValueError:continue
                    try:
                        if len(relative.parts)==4 and relative.parts[0]=='by-source' and relative.parts[2]=='payload':
                            item,_=file_row(db,'',relative.parts[1])
                            if relative.parts[3]!=(item.get('name') or Path(item['path']).name):raise SourceIdentityError('SOURCE_PATH_ID_MISMATCH')
                        else:item,_=file_row(db,'/'+relative.as_posix())
                        matches.append(item)
                    except SourceIdentityError as exc:
                        if exc.code!='SOURCE_NOT_FOUND':raise
                if not matches:raise error
                ids={str(item.get('source_id') or item['source_row_id']) for item in matches}
                if len(ids)!=1:raise SourceIdentityError('SOURCE_PATH_AMBIGUOUS')
                row=matches[0]
            result.append(analysis_reference(row['path'],row.get('source_id')))
    return list(dict.fromkeys(result))


async def bind_sources(backend,task_id,paths,case_context=''):
    task=await backend.get_task(task_id)
    if not task or not task.get('output_files_db'):raise ValueError('任务来源索引不存在')
    references=canonical_references(task,paths)
    if not references:return {'schema_version':1,'plan_id':None,'selected':[]},[],[]
    if len(references)>1000:raise ValueError('单次指定来源超过 1000 项，请按预算分批处理')
    plan=await backend.selection_plan([task_id],len(references),case_context=case_context,file_references=references)
    if not isinstance(plan,dict) or plan.get('schema_version')!=1:raise ValueError('无法建立有预算的来源分析计划')
    selected=[item['reference'] for item in plan['selected'] if item['task_id']==task_id]
    if len(selected)>len(references) or not set(selected)<=set(references):raise ValueError('选择计划超出指定来源范围')
    deferred=[{'file_path':reference,'description':'','success':False,'error':'本轮因读取能力、有效内容或预算限制暂缓；来源仍保留','selection_state':'deferred'}
              for reference in references if reference not in set(selected)]
    return plan,selected,deferred
