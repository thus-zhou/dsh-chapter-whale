"""Per-book, credential-revision-bound cooldown after evidenced API failures."""
import hashlib
from datetime import datetime,timedelta,timezone
from pathlib import Path
from . import bridge,writer_runner


def key(project,role,config,binding):
    provider=config['providers'][binding['provider_id']]
    value='\0'.join((str(Path(project).resolve()).casefold(),role,binding['provider_id'],str(provider['revision']),binding['model_id']))
    return hashlib.sha256(value.encode()).hexdigest()


def active(project,role,config,binding,now=None):
    if not project:return False
    doc=writer_runner.strict_json(bridge.RUNTIME_ROOT/'provider-circuits.json',{})
    item=doc.get(key(project,role,config,binding),{})
    # Older releases incorrectly cooled a whole model after one small-output
    # extraction. Those request-specific failures cannot ban later gate calls.
    if item.get('reason',{}).get('failure_kind')=='model_output':return False
    target=item.get('until')
    return bool(target and datetime.fromisoformat(target)>(now or datetime.now(timezone.utc)))


def defer(project,role,config,binding,reason,now=None):
    if not project:return
    path=bridge.RUNTIME_ROOT/'provider-circuits.json'
    with writer_runner.file_lock(path.with_suffix('.lock'),blocking=True):
        doc=writer_runner.strict_json(path,{})
        at=now or datetime.now(timezone.utc)
        doc[key(project,role,config,binding)]={'at':at.isoformat(),'until':(at+timedelta(minutes=30)).isoformat(),
            'reason':{k:reason[k] for k in ('failure_kind','http_status','retryable') if k in reason}}
        bridge.write_json_atomic(path,doc)
