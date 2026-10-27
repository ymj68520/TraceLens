import pytest
from httpserver.services.ingestion_quality import ingestion_quality
from httpserver.services.ingestion_job_manager import IngestionJobManager
from httpserver.services.ingestion_job_models import IngestionJob, IngestionMode, JobStatus
from httpserver.config import Settings

def test_partial_completed_job_is_limited_and_retryable():
    result=ingestion_quality({'status':'COMPLETED','result':{'total':909,'successful':908,'failed':1}})
    assert result['status']=='limited' and result['failed']==1 and result['retryable']
    assert result['successful']==908 and result['total']==909

def test_missing_counters_are_unknown_not_zero_and_active_job_is_pending():
    result=ingestion_quality({'status':'COMPLETED','result':{}})
    assert result['status']=='limited' and result['failed'] is None
    assert ingestion_quality({'status':'RUNNING'})['status']=='pending'
    assert ingestion_quality({'status':'unknown','result':{'total':1,'successful':1,'failed':0}})['status']=='limited'
    assert ingestion_quality({'status':'completed','result':{'total':1,'successful':0,'failed':1}})['status']=='failed'

@pytest.mark.asyncio
async def test_job_history_is_newest_first_without_cross_task_counts():
    manager=IngestionJobManager(Settings(_env_file=None));manager._use_redis=False
    for name,task,date in [('old','A','2026-01-01'),('foreign','B','2026-12-01'),('new','A','2026-10-01')]:
        job=IngestionJob(job_id=name,task_id=task,mode=IngestionMode.ANALYZED_ONLY)
        job.created_at=date;job.status=JobStatus.COMPLETED;job.result={'successful':908,'failed':1,'total':909}
        manager._jobs[name]=job
    jobs=await manager.list_jobs(task_id='A',limit=1)
    assert [j['job_id'] for j in jobs]==['new'] and jobs[0]['quality']['failed']==1
