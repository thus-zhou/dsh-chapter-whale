"""Credential-safe registry under the existing management authorization."""
import copy
from pathlib import Path
from integration import providers, model_roles, bridge, writer_runner


def _registered_projects(app):
    """Projects the user actually registered (store) or scheduled (jobs)."""
    paths=set()
    store=getattr(app.state,'store',None)
    if store is not None:
        try:
            paths.update(str(Path(x['path']).resolve()) for x in store.projects() if isinstance(x,dict) and x.get('path'))
        except (AttributeError,KeyError,TypeError,ValueError):
            pass
    from integration import scheduler
    try:
        jobs=scheduler.load_scheduler().get('jobs',{})
        paths.update(str(Path(job['project']).resolve()) for job in jobs.values() if isinstance(job,dict) and job.get('project'))
    except (OSError,ValueError,AttributeError,TypeError):
        pass
    return paths


def _resolve_project_value(value, app):
    text=str(value or '').strip()
    if not text:return ''
    if Path(text).is_absolute():return str(Path(text).resolve())
    store=getattr(app.state,'store',None)
    if store is not None:
        try:
            matched=next((x['path'] for x in store.projects() if x.get('id')==text),None)
        except (AttributeError,KeyError,TypeError):
            matched=None
        if matched:return str(Path(matched).resolve())
    return str(Path(text).resolve())


def _explicit_projects(payload, app):
    """Explicit project scope only; never “all registered books”."""
    raw=[]
    projects=payload.get('projects')
    if isinstance(projects,list):
        raw.extend(x for x in projects if isinstance(x,str) and x.strip())
    elif projects is not None:
        raise ValueError('projects 必须是作品路径列表')
    project=payload.get('project')
    if isinstance(project,str) and project.strip():
        raw.append(_resolve_project_value(project, app))
    elif project is not None:
        raise ValueError('project 必须是作品路径')
    project_id=payload.get('project_id')
    if project_id:
        if not isinstance(project_id,str):raise ValueError('project_id 无效')
        matched=next((x['path'] for x in app.state.store.projects() if x.get('id')==project_id),None)
        if not matched:raise ValueError('所选作品未登记，无法授权')
        raw.append(str(Path(matched).resolve()))
    return list(dict.fromkeys(raw))


def install(app, load, config_path, *, costs_db=None):
    from fastapi import HTTPException
    from manager import role_checks
    cost_db_path = costs_db or (config_path.parent / 'costs.sqlite3')
    role_checks.install(app,load,config_path)
    def write_config(doc):
        bridge.write_json_atomic(config_path, doc)
        bridge.harden_secret_file(config_path)

    def transaction(change):
        with writer_runner.file_lock(config_path.with_suffix('.lock'), blocking=True):
            doc=providers.migrate(load());result=change(doc)
            from integration import secret_store
            secret_store.save(config_path.parent, doc, write_config)
            return result
    from manager import free_model_api
    free_model_api.install(app,load,transaction,lambda:listing())
    @app.get('/api/ai/providers')
    def listing():
        doc=load()
        from integration.resource_policy import public as resource_policy
        from integration.editorial_release import public as editorial_rule
        try:checks=role_checks.snapshot(config_path);checks_error=False
        except (ValueError,OSError):checks={};checks_error=True
        return {'providers':providers.public(doc),'resource_policy':resource_policy(doc),'editorial_release_rule':editorial_rule(doc),'default_binding':doc.get('default_binding',{}),
            'role_checks':checks,'checks_unavailable':checks_error,
            'roles':{r:{k:v for k,v in b.items() if k in {'provider_id','model_id','fallbacks','reasoning_effort'}} for r,b in doc.get('roles',{}).items()},
            'needs_migration':doc.get('provider_schema')!=1,
            **{k:doc.get(k) for k in ('multi_model','polish_mode','review_policy')}}
    @app.post('/api/ai/providers/migrate')
    def migrate():
        transaction(lambda doc:None);return listing()
    @app.post('/api/ai/providers')
    def add(payload:dict):
        if payload.get('protocol') in {'free_pool','ofm_standalone'}:raise ValueError('请在免费额度工作台创建此托管连接')
        def change(doc):
            updated,identity=providers.save(doc,None,payload);doc.clear();doc.update(updated);return identity
        return {'id':transaction(change),**listing()}
    @app.put('/api/ai/providers/{identity}')
    def update(identity:str,payload:dict):
        def change(doc):
            if identity not in doc['providers']:raise KeyError('供应商不存在')
            if doc['providers'][identity].get('protocol') in {'free_pool','ofm_standalone'} or payload.get('protocol') in {'free_pool','ofm_standalone'}:raise ValueError('请在免费额度工作台管理此连接')
            updated,_=providers.save(doc,identity,payload);doc.clear();doc.update(updated)
        transaction(change);return listing()
    @app.delete('/api/ai/providers/{identity}')
    def remove(identity:str):
        def change(doc):
            if providers.referenced(doc,identity):raise ValueError('请先解除模型和备选链绑定')
            if identity not in doc['providers']:raise KeyError('供应商不存在')
            del doc['providers'][identity]
        transaction(change);return listing()
    @app.post('/api/ai/providers/{identity}/models')
    def models(identity:str):
        doc=load();result=providers.discover(doc,identity);revision=doc['providers'][identity]['revision']
        def change(latest):
            if latest['providers'][identity]['revision']!=revision:raise ValueError('供应商已更新，请重新读取')
            latest['providers'][identity].update(models=result['models'],last_check=doc['providers'][identity]['last_check'])
        transaction(change);return result
    @app.post('/api/ai/providers/{identity}/test')
    async def test(identity:str,payload:dict):
        import asyncio
        from integration import costs
        doc=load();binding={'provider_id':identity,'model_id':str(payload.get('model_id','')).strip()}
        providers.resolve(doc,binding)
        probe=copy.deepcopy(doc);probe.update(multi_model=False,default_binding=binding)
        client=model_roles.service('E',probe);client.timeout=90
        try:
            with costs.scope(stage='probe'):
                text=await asyncio.wait_for(client.chat([{'role':'user','content':'仅回复：连接成功'}],max_tokens=1024),timeout=120)
        except TimeoutError as exc:
            raise HTTPException(504, '模型探测超时，请检查接口连通性或稍后重试') from exc
        except (ValueError, KeyError, RuntimeError):
            raise
        except Exception as exc:
            raise HTTPException(502, f'模型连接测试失败：{str(exc)[:300] or type(exc).__name__}') from exc
        received = bool(isinstance(text, str) and text.strip())
        if not received:
            raise HTTPException(502, '模型未返回有效文本，请检查模型配置或额度')
        return {'status':'ok','provider_id':identity,'model_id':binding['model_id'],'content_received':True}
    @app.post('/api/ai/providers/{identity}/reprice')
    def reprice(identity:str):
        from integration import costs
        item=load().get('providers',{}).get(identity)
        if not item:raise KeyError('供应商不存在')
        return {'recalculated':costs.reprice_provider(cost_db_path,item)}
    @app.put('/api/ai/bindings')
    def bindings(payload:dict):
        if set(payload)-{'default_binding','roles','multi_model','polish_mode','review_policy'}:raise ValueError('模型绑定包含未知字段')
        def change(doc):
            if 'multi_model' in payload and type(payload['multi_model']) is not bool:raise ValueError('分工开关必须为布尔值')
            if 'polish_mode' in payload and payload['polish_mode'] not in {'key','all','none'}:raise ValueError('润色范围无效')
            if 'review_policy' in payload and payload['review_policy'] not in {'strict','e_decides'}:raise ValueError('审稿决策无效')
            doc.update({k:payload[k] for k in ('multi_model','polish_mode','review_policy') if k in payload})
            values=dict(payload.get('roles',{}))
            if set(values)-set(model_roles.ROLES):raise ValueError('分工只能为A–E')
            if 'default_binding' in payload:values['default']=payload['default_binding']
            for role,value in values.items():
                if not isinstance(value,dict) or set(value)-{'provider_id','model_id','fallbacks','reasoning_effort'}:raise ValueError('模型绑定无效')
                from integration.reasoning import validate
                if 'reasoning_effort' in value:validate(value['reasoning_effort'])
                fallback=value.get('fallbacks',[])
                if not isinstance(fallback,list) or len(fallback)>3:raise ValueError('最多3个备选模型')
                if role!='default' and not value.get('provider_id') and not value.get('model_id') and not fallback:
                    doc.setdefault('roles',{})[role]={'reasoning_effort':value['reasoning_effort']} if 'reasoning_effort' in value else {}
                    continue
                for candidate in [value,*fallback]:providers.resolve(doc,candidate)
                for candidate in [value,*fallback]:
                    provider=doc['providers'][candidate['provider_id']]
                    if provider.get('protocol')=='free_pool':
                        needed=set(model_roles.ROLES) if role=='default' else {role}
                        available={r for member in provider.get('pool_members',[]) for r in member.get('roles',[])}
                        if not needed.issubset(available):raise ValueError('免费池没有覆盖此绑定的角色；请先为相应角色选入模型')
                if role=='default':doc['default_binding']=copy.deepcopy(value);doc.update(providers.resolve(doc,value))
                else:doc.setdefault('roles',{})[role]={**doc.get('roles',{}).get(role,{}),**copy.deepcopy(value),**providers.resolve(doc,value)}
        transaction(change);return listing()
    @app.post('/api/ai/providers/dsh/import')
    def dsh(payload: dict | None = None):
        payload=payload or {}
        if set(payload)-{'project','project_id','projects'}:raise ValueError('dsh 导入包含未知字段')
        named=_explicit_projects(payload,app)
        known=_registered_projects(app)
        allowed=[p for p in named if p in known]
        if named and not allowed:raise ValueError('请选择已登记的作品，不扩大隐私授权范围')
        # No explicit project means the provider is saved with an empty
        # authorization list and can process nothing until a book is named.
        def change(doc):
            updated,identity=providers.import_dsh(doc,projects=allowed);doc.clear();doc.update(updated);return identity
        return {'id':transaction(change),**listing()}

    from integration import free_channels

    @app.get('/api/ai/free-channels')
    def free_listing():
        return free_channels.snapshot(load(),cost_db_path)

    @app.post('/api/ai/free-channels/scan')
    def free_scan(payload:dict):
        if set(payload)-{'port'}:raise ValueError('渠道扫描包含未知字段')
        catalog,_=free_channels.scan(payload.get('port'))
        bridge.write_json_atomic(free_channels.cache_path(),catalog)
        return free_listing()

    @app.post('/api/ai/free-channels/import')
    def free_import(payload:dict):
        if set(payload)-{'port','channel_id','authorize_project','project','project_id','projects'}:raise ValueError('渠道接入包含未知字段')
        named=_explicit_projects(payload,app)
        if not named:raise ValueError('请先选择需要授权的作品，再接入渠道')
        known=_registered_projects(app)
        allowed=[p for p in named if p in known]
        if not allowed:raise ValueError('请选择已登记的作品，不扩大隐私授权范围')
        payload = {**payload, 'projects': allowed}
        # Network work stays outside the AI configuration lock.
        current=load()
        updated,identity,catalog=free_channels.import_channel(current,payload,known_projects=known)
        def change(latest):
            if latest.get('providers')!=providers.migrate(current).get('providers'):
                raise ValueError('供应商设置已变化，请重新接入')
            latest['providers']=updated['providers']
        transaction(change)
        bridge.write_json_atomic(free_channels.cache_path(),catalog)
        return {'id':identity,**listing()}
