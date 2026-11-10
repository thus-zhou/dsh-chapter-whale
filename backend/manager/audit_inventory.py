"""Reproducible syntax/dependency inventory; excludes installed dependencies."""
from __future__ import annotations
import ast
import json
import os
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {".git", ".venv", "node_modules", "playwright-browsers", "__pycache__", "dist", "build", "integration_data", "accounts", "books"}


def inventory():
    report = {"python_files": 0, "frontend_files": 0, "syntax_errors": [], "modules": {}, "paths": [],
        'coverage_kind':'inventory_and_syntax_only_not_exhaustive_semantic_review','file_hashes':{}}
    for directory, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name not in EXCLUDED]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(ROOT)
            if path.suffix not in {".py", ".vue", ".js", ".css", ".html", '.ps1','.cmd','.toml','.yml','.yaml'} and not name.startswith('requirements'):
                continue
            module = str(relative.parts[0])
            report["modules"][module] = report["modules"].get(module, 0) + 1
            report["paths"].append(str(relative))
            report['file_hashes'][str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
            if path.suffix == ".py":
                report["python_files"] += 1
                try:
                    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(relative))
                except (SyntaxError, UnicodeError) as exc:
                    report["syntax_errors"].append({"path": str(relative), "error": str(exc)})
            elif path.suffix in {'.vue','.js','.css','.html'}:
                report["frontend_files"] += 1
    # One-time helpers are executable entry points too, despite living beside
    # generated runtime data. Inventory code, not account states or novel prose.
    for path in sorted((ROOT/'integration_data/operations').glob('*.py')):
        relative=str(path.relative_to(ROOT))
        report['paths'].append(relative);report['python_files']+=1
        report['file_hashes'][relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        report['modules']['integration_data/operations']=report['modules'].get('integration_data/operations',0)+1
        try:ast.parse(path.read_text(encoding='utf-8-sig'),filename=relative)
        except (SyntaxError,UnicodeError) as exc:report['syntax_errors'].append({'path':relative,'error':str(exc)})
    report['protected_runtime_configs']=[{'path':str(p.relative_to(ROOT)),'exists':p.is_file(),'contents':'not_exported'} for p in
        [ROOT/'integration_data/ai_config.json',ROOT/'integration_data/scheduler.json',*(ROOT/'accounts').glob('*/state.json')]]
    return report


if __name__ == "__main__":
    result = inventory()
    print(json.dumps({k: v for k, v in result.items() if k != "paths"}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["syntax_errors"] else 0)
