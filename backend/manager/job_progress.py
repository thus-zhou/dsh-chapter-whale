"""Read-only per-book runtime metadata; never returns prompts or credentials."""
import json
import sqlite3
from pathlib import Path
from integration import retry_budget


def read(job,db_path,now):
    result={'recovery_budget':retry_budget.status(job['project'],now)}
    if not Path(db_path).is_file():return result
    db=sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro',uri=True,timeout=2)
    try:
        row=db.execute('SELECT payload FROM usage_events WHERE project=? ORDER BY created_at DESC LIMIT 1',(str(Path(job['project']).resolve()),)).fetchone()
        if row:
            event=json.loads(row[0])
            result['last_request']={key:event.get(key) for key in ('created_at','chapter','stage','role','model','provider_id','provider_name','status','elapsed_ms')}
        return result
    finally:db.close()
