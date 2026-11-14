"""Isolated worker for AI, browser login and publish operations."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from integration import bridge, scheduler, writer_runner, model_roles, studio, memory_library
from integration import costs


def sanitized_result(result):
    import re
    try:
        text=json.dumps(result,ensure_ascii=False,default=str)
        for secret in model_roles.secrets(model_roles.load_config()):text=text.replace(secret,'[redacted]')
        text=re.sub(r'\bsk-[A-Za-z0-9_\-]{8,}','[redacted]',text)
        text=re.sub(r"(?i)(authorization[\s\"':=]+(?:bearer\s+)?)[^\s,\"}]+",r'\1[redacted]',text)
        return json.loads(text)
    except Exception:
        return {'status':'failed','error':'结果脱敏失败；原始结果未落盘或输出'}


def result_file(result):
    destination=os.getenv('NOVEL_HELPER_MANAGER_RESULT')
    if destination:bridge.write_json_atomic(Path(destination),sanitized_result(result))


def login(name):
    from playwright.sync_api import sync_playwright
    folder = bridge.account_dir(name)
    folder.mkdir(parents=True, exist_ok=True)
    environment = bridge.child_environment()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = environment["PLAYWRIGHT_BROWSERS_PATH"]
    with bridge.runtime_lock("account-login-" + name), sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            state = folder / "state.json"
            context = browser.new_context(storage_state=str(state) if state.is_file() else None)
            page = context.new_page()
            page.goto("https://fanqienovel.com/main/writer/book-manage", timeout=60000)
            print("NOVEL_HELPER_WAITING_LOGIN 请在浏览器中登录，然后在管理界面点击完成登录", flush=True)
            if not sys.stdin.readline():
                raise RuntimeError("登录操作已取消")
            page.goto("https://fanqienovel.com/main/writer/book-manage", timeout=60000)
            page.wait_for_timeout(1200)
            if "book-manage" not in page.url:
                raise RuntimeError("尚未进入作品管理页，登录状态未保存")
            visible = page.locator("body").inner_text(timeout=10000)
            if not any(x in visible for x in ("我的作品", "我的小说", "创建作品", "创建新书", "章节管理", "创作中心")):
                raise RuntimeError("无法确认作者后台，登录状态未保存")
            saved = context.storage_state()
            if not saved.get("cookies"):
                raise RuntimeError("没有有效的登录 Cookie，登录状态未保存")
            bridge.write_json_atomic(state, saved)
            bridge.harden_secret_file(state)
            bridge.write_json_atomic(folder / "profile.json", {"name": name, "updated_at": bridge.now_iso(), "verified_login_at": bridge.now_iso()})
            return {"status": "logged_in", "account": name, "verified": "creator_center_controls"}
        finally:
            browser.close()


@costs.attributed("probe")
async def test_ai(role=None):
    _, get_ai = writer_runner._load_webnovel_services()
    service = get_ai()
    if role:service=model_roles.service(role,fallback=service)
    service.timeout = 90
    # Reasoning models may spend the output budget before producing visible text.
    # A ten-token probe incorrectly reports those working connections as empty.
    try:
        with costs.scope(role=role or ""):
            reply = await asyncio.wait_for(service.chat(
                [{"role": "user", "content": "Reply only OK."}], temperature=0, max_tokens=1024), timeout=120)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise RuntimeError(f"模型 {role or '通用'}（{service.model}）连接测试超过 120 秒，请检查接口或稍后重试") from exc
    if not str(reply or "").strip():
        raise RuntimeError("模型返回空内容")
    return {"status": "ok", "model": service.model, "message": "模型连接可用"}


def main():
    os.environ.setdefault("NOVEL_HELPER_COST_DB",str(bridge.COMBINED_ROOT / "integration_data" / "costs.sqlite3"))
    os.environ.setdefault('NOVEL_HELPER_RETRIEVAL_HEALTH',str(bridge.COMBINED_ROOT/'integration_data'/'retrieval_health.json'))
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "review", "stage", "publish", "run", "login", "ai-test", "ai-roles-test", "learn", "plan", "batch", "polish", "memory-rebuild"])
    parser.add_argument("--project")
    parser.add_argument("--book")
    parser.add_argument("--account")
    parser.add_argument("--job-id")
    parser.add_argument("--word-count", type=int, default=3500)
    parser.add_argument("--max-revisions", type=int, default=2)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--chapter", type=int, action="append")
    parser.add_argument("--role",choices=list(model_roles.ROLES))
    parser.add_argument("--sample-id")
    parser.add_argument("--revision",type=int,default=0)
    parser.add_argument("--full",action="store_true")
    parser.add_argument("--batch-id")
    parser.add_argument("--ai-used", choices=["0", "1"], default="1")
    parser.add_argument("--serial-step", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "login":
            result = login(args.account)
        elif args.command == "ai-test":
            result = asyncio.run(test_ai(args.role))
        elif args.command == "ai-roles-test":
            async def all_roles():
                tested=[]
                for role in model_roles.ROLES:
                    tested.append({"role":role,**await test_ai(role)})
                return {"status":"ok","roles":tested}
            result=asyncio.run(all_roles())
        elif args.command == "memory-rebuild":
            result=memory_library.rebuild(Path(args.project))
        elif args.command == "learn":
            result=studio.learn(Path(args.project),args.sample_id,args.revision,args.full)
        elif args.command == "plan":
            result=studio.plan(Path(args.project),args.count)
        elif args.command == "batch":
            result=studio.batch(Path(args.project),args.count,args.word_count,args.max_revisions,args.batch_id)
        elif args.command == "polish":
            if not args.chapter or len(args.chapter)!=1:raise ValueError("请选择一个章节")
            result=studio.polish_existing(Path(args.project),args.chapter[0],preview=args.preview)
        elif args.command == "generate":
            result = writer_runner.generate_chapter(Path(args.project), args.word_count, args.max_revisions)
            result.pop("review", None)
        elif args.command == "review":
            if not args.chapter or len(args.chapter) != 1:
                raise ValueError("请选择一个章节审查")
            result = writer_runner.review_existing_chapter(Path(args.project), args.chapter[0])
        elif args.command == "stage":
            project = Path(args.project)
            receipts = writer_runner.reviewed_chapters(project)
            selected = set(args.chapter) if args.chapter else set(receipts)
            if not selected:
                raise ValueError("没有有效的审查或 E 授权记录，请先处理正文")
            if not selected.issubset(receipts):
                raise ValueError("所选正文缺少当前有效的审查／E 授权，或内容已被修改，请重新处理")
            result = bridge.stage_project(project, book_name=args.book, selected_ids=selected)
            result["skipped_unreviewed"] = sorted(writer_runner.existing_chapter_ids(project) - set(receipts))
            result["status"] = "queued" if not result["conflicts"] and not result["invalid"] else "failed"
        elif args.command == "publish":
            os.environ["NOVEL_HELPER_AI_USED"] = args.ai_used
            # Explicit publication consumes only the existing queue. It must never
            # silently enqueue all older chapters when the user selects a book.
            code = bridge.run_publish(args.book, count=args.count, account=args.account, project=Path(args.project))
            report = bridge.latest_publish_report(args.book, args.account)
            result = {"status": "success" if code == 0 and report.get("verified_success") else "failed", "exit_code": code,
                      "publication": report, "queue": bridge.sync_manifest(), "book": args.book, "account": args.account}
        else:
            job = scheduler.load_scheduler()['jobs'].get(args.job_id, {})
            if job.get('delivery_mode') == 'serial' and not args.serial_step:
                from integration.serial_service import ensure_started
                result = ensure_started()
            else:
                result = scheduler.run_once(args.job_id)
        result=sanitized_result(result)
        result_file(result)
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        return 0 if result.get("status") in {"success", "progress", "configured", "generated", "reviewed", "authorized", "queued", "logged_in", "already_run", "already_ran", "ok", "learned", "planned", "polished", "preview", "memory_synced"} else 2
    except Exception as exc:
        from integration.failure_info import details
        message=str(exc) or type(exc).__name__
        failure=details(exc)
        waiting=args.command=='batch' and failure.get('failure_kind') in {'recovery_cooldown','free_pool_wait'} and failure.get('next_retry_at')
        result_file({"status": "waiting" if waiting else "failed", "error": message,"batch_id":args.batch_id,"project":args.project,**failure})
        safe=sanitized_result({'error':message})
        print('操作失败：'+safe.get('error','未知错误'),file=sys.stderr,flush=True)
        return 1


if __name__ == "__main__":
    with model_roles.execution_snapshot():
        raise SystemExit(main())
