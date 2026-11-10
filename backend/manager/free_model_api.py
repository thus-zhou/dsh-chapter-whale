"""Same authorized Novel Helper origin; OFM management key never reaches JS."""
import copy
from pathlib import Path
from integration import ofm_runtime,free_pool,bridge,providers


def install(app,load,transaction,listing):
    @app.get('/api/free-model/status')
    def status():
        value=ofm_runtime.status();doc=load()
        value['pool_members']=doc.get('providers',{}).get('free-pool',{}).get('pool_members',[])
        value['pool_configured']='free-pool' in doc.get('providers',{})
        from integration.resource_policy import public
        value['resource_policy']=public(doc)
        return value

    @app.post('/api/free-model/start')
    def start(payload:dict):
        if payload:raise ValueError('启动独立渠道不接受额外参数')
        ofm_runtime.ensure_started(start=True)
        return status()

    @app.get('/api/free-model/summary')
    def summary():
        raw=ofm_runtime.request('/api/management/summary')
        return {k:ofm_runtime.clean(raw.get(k)) for k in ('product','version','channels','catalogSyncedAt','catalog')}

    @app.post('/api/free-model/refresh')
    def refresh(payload:dict):
        if payload:raise ValueError('模型清单刷新不接受探测参数')
        ofm_runtime.request('/api/management/models/refresh',{'probe':False},timeout=150)
        return summary()

    @app.post('/api/free-model/rpc')
    def rpc(payload:dict):
        if set(payload)-{'method','payload'}:raise ValueError('渠道操作包含未知字段')
        return ofm_runtime.rpc(payload.get('method'),payload.get('payload',{}))

    @app.put('/api/free-model/pool')
    def pool(payload:dict):
        if set(payload)-{'members','project','authorize_project'}:raise ValueError('免费池包含未知字段')
        if payload.get('authorize_project') is not True:raise ValueError('请确认所选作品正文和必要记忆的渠道处理授权')
        from integration import scheduler
        project=payload.get('project')
        choices={str(Path(x['project']).resolve()) for x in scheduler.load_scheduler().get('jobs',{}).values()}
        choices.update(str(Path(x['path']).resolve()) for x in app.state.store.projects())
        if not isinstance(project,str) or str(Path(project).resolve()) not in choices:raise ValueError('请选择已有日更作品，不扩大隐私授权范围')
        project=str(Path(project).resolve())
        raw=ofm_runtime.request('/api/management/summary')
        members=free_pool.validate_members(payload.get('members'),[r for r in raw.get('catalog',[]) if r.get('routable')])
        info=ofm_runtime.health();key=ofm_runtime.strict(ofm_runtime.HOME/'settings.json').get('forwardKey')
        ids=[r['id'] for r in raw.get('catalog',[]) if r.get('routable')]
        def change(doc):
            previous=doc['providers'].get('free-pool',{})
            permitted=list(dict.fromkeys([*previous.get('allowed_projects',[]),project]))
            updated,_=providers.save(doc,'ofm-standalone',{'name':'Our Free Model · 独立服务','base_url':info['url']+'/v1',
                'protocol':'ofm_standalone','api_key':key,'allowed_projects':permitted})
            updated['providers']['ofm-standalone'].update(models=ids,free_models=[r['model_id'] for r in members])
            updated,_=providers.save(updated,'free-pool',{'name':'免费渠道池','base_url':info['url']+'/v1',
                'protocol':'free_pool','api_key':key,'allowed_projects':permitted})
            updated['providers']['free-pool'].update(models=['auto'],pool_members=members)
            doc['providers']=updated['providers']
        transaction(change)
        return {'status':'saved','members':members,**listing()}
