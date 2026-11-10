"""Runtime identity and body limits independent of AI/browser work."""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from starlette.responses import JSONResponse

STARTED_AT=datetime.now(timezone.utc).isoformat()
STARTUP_ID=uuid.uuid4().hex


def release_id():
    root=Path(__file__).resolve().parents[1]
    paths=[*sorted((root/'integration').glob('*.py')),*sorted((root/'manager').glob('*.py')),
        *sorted((root/'manager/static').glob('*.*')),root/'fanqie_auto_publish/publish.py',root/'fanqie_auto_publish/publication_safety.py',
        *sorted((root/'integration').glob('*.mjs')),root/'vendor/ofm-source-lock.json',
        *(root/'webnovel-writer/backend/services'/name for name in ('ai_service.py','skill_executor.py'))]
    digest=hashlib.sha256()
    for path in paths:
        if path.is_file():digest.update(str(path.relative_to(root)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class RequestTooLarge(Exception):pass


class BodyLimitMiddleware:
    def __init__(self,app,limit=32*1024*1024):self.app=app;self.limit=limit
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        if scope.get('method') not in {'POST','PUT','PATCH','DELETE'}:
            return await self.app(scope,receive,send)
        # Reject before FastAPI's JSON/multipart parser can turn an exception
        # into a generic 400, including chunked uploads without Content-Length.
        count=0;chunks=[]
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            count+=len(message.get('body',b''))
            if count>self.limit:
                return await JSONResponse({'detail':'请求体超过32MB上限'},status_code=413)(scope,receive,send)
            chunks.append(message)
            if not message.get('more_body',False):break
        cursor=iter(chunks)
        async def replay():
            return next(cursor,None) or await receive()
        return await self.app(scope,replay,send)
