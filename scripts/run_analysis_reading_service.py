"""Versioned read-only extension of the frozen authenticated HTTP service.

Reuses existing Graphiti query/source readers, never its model/ingestion init.
Core release identity remains the base release; extension identity is separate.
"""
import asyncio, hashlib, ipaddress, json, sys
from contextlib import asynccontextmanager
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE/'python_service'))
import uvicorn
from fastapi import APIRouter, Query
from neo4j import AsyncGraphDatabase, READ_ACCESS
from redis.asyncio import Redis
from httpserver.main import get_app
from httpserver.config import get_settings, get_project_root
from httpserver.services import get_service_manager
from httpserver.services.graphiti_service import GraphitiService
from httpserver.routes.graphiti_endpoints import _admin, _query, _trace
from httpserver.services.investigation.offline_translation import OfflineArgosTranslator

class ReadDriver:
    def __init__(self, driver): self.driver=driver
    def session(self, **kw):
        kw['default_access_mode']=READ_ACCESS
        return self.driver.session(**kw)
    async def close(self): await self.driver.close()

class ExistingGraphReader(GraphitiService):
    async def initialize(self): raise RuntimeError('reading mode never initializes model ingestion')
    async def _get_shared_driver(self):
        if self._neo_driver is None:
            self._neo_driver=ReadDriver(AsyncGraphDatabase.driver(self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user,self.settings.neo4j_password),connection_timeout=3,
                connection_acquisition_timeout=3,max_transaction_retry_time=0))
        return self._neo_driver
    async def health_check(self, task_id=None): return await self._check_neo4j_connection()

app=get_app(); original_lifespan=app.router.lifespan_context
@asynccontextmanager
async def reading_lifespan(application):
    async with original_lifespan(application):
        manager=get_service_manager()
        manager._graphiti_service=ExistingGraphReader(get_settings())
        yield
app.router.lifespan_context=reading_lifespan
router=APIRouter()
@router.get('/status')
async def graph_status(task_id: str|None=Query(None)):
    data=await get_service_manager().graphiti_service.get_status(task_id)
    return {**data,'read_only':True,'ingestion_enabled':False,'search_mode':'keyword'}
router.add_api_route('/tasks',_admin.list_task_graphs,methods=['GET'])
router.add_api_route('/graph',_admin.get_graph_data,methods=['GET'])
router.add_api_route('/entities',_query.list_entities,methods=['GET'])
router.add_api_route('/relationships',_query.list_relationships,methods=['GET'])
router.add_api_route('/search',_query.search_graph,methods=['POST'])
router.include_router(_trace.router)
app.include_router(router,prefix='/api/knowledge-graph',tags=['Existing graph reading'])

translation_ok=None
@app.get('/api/system/analysis-health')
async def analysis_health():
    global translation_ok
    settings=get_settings()
    graph=await get_service_manager().graphiti_service.health_check()
    redis=Redis.from_url(settings.redis_url,socket_connect_timeout=2,socket_timeout=2)
    try: cache=bool(await redis.ping())
    except Exception: cache=False
    finally: await redis.aclose()
    if translation_ok is None:
        try:
            text,_=await asyncio.to_thread(OfflineArgosTranslator(get_project_root()/'build/models/translate-en_zh-1_9').translate,
                'This configuration file describes application settings and a local cleanup rule.')
            translation_ok=sum('\u4e00'<=c<='\u9fff' for c in text)>5
        except Exception: translation_ok=False
    return {'neo4j':{'connected':graph},'redis':{'connected':cache},
        'translation':{'connected':translation_ok,'local':True},'general_llm_enabled':False,
        'graph_read_only':True,'extension_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

if __name__=='__main__':
    settings=get_settings()
    if not ipaddress.ip_address(settings.python_http_host).is_loopback:raise RuntimeError('loopback required')
    uvicorn.run(app,host=settings.python_http_host,port=settings.python_http_port,workers=1)
