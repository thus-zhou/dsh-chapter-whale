"""Recoverable reset of derived indexes, never of credentials or author settings."""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
import uuid


def backup_and_clear(root):
    root=Path(root).resolve();state=root/'.webnovel'
    if not state.is_dir() or state.is_symlink() or state.resolve()!=state:raise ValueError('无有效的项目状态目录')
    if (state/'reset-backups').resolve().parent!=state:raise ValueError('重置备份目录路径不安全')
    backup=state/'reset-backups'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    databases=[path for pattern in ('index.db','rag.db','vectors*.db') for path in state.glob(pattern)]
    for path in databases:
        if path.is_symlink() or path.resolve().parent!=state:raise ValueError('派生索引路径不安全')
    backup.mkdir(parents=True)
    # Backup all databases before clearing the first one; SQLite backups include
    # committed WAL contents. No original database file is unlinked or replaced.
    for path in databases:
        source=sqlite3.connect(path,timeout=5);target=sqlite3.connect(backup/path.name)
        try:source.backup(target)
        finally:target.close();source.close()
    for path in databases:
        db=sqlite3.connect(path,timeout=5)
        try:
            db.execute('BEGIN IMMEDIATE')
            tables=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            # FTS shadow tables are owned by their virtual table. Deleting the
            # root clears them; touching shadow tables independently corrupts FTS.
            roots={name for (name,) in tables if db.execute("SELECT sql FROM sqlite_master WHERE name=?",(name,)).fetchone()[0].upper().startswith('CREATE VIRTUAL TABLE')}
            names=[name for (name,) in tables if not any(name.startswith(r+'_') for r in roots)]
            for name in names:db.execute('DELETE FROM "'+name.replace('"','""')+'"')
            db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()
    # Source-bound state cannot survive a content reset and be mistaken for
    # facts about the newly empty story. Move it to the same recoverable backup.
    for name in ('writer_receipts.json','shared_memory.json','story_plan.json','planning_failover_state.json'):
        path=state/name
        if path.exists():
            if path.is_symlink():raise ValueError('派生状态路径不安全')
            os.replace(path,backup/name)
    return backup
