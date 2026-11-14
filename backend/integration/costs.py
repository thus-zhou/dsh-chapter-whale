"""Attempt-level usage ledger. Stores metadata, never prompts, keys or replies."""
from __future__ import annotations
import csv
import functools
import hashlib
import inspect
import io
import json
import math
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

STAGES = {"planning":"剧情规划", "draft":"正文初稿", "polish":"润色与修订", "review":"一致性审查",
          "learning":"示范学习", "memory":"共享记忆", "entities":"设定与人物同步", "continuity":"连续性摘要",
          "rag":"检索与向量", "research":"写前调研", "conversation":"创作沟通", "brief":"约定扩写", "authorization":"E 审查决策",
          "publication":"E 发布决策", "probe":"连接测试", "other":"其他模型调用"}
META = ContextVar("novel_cost_context", default={})
# 成本事件写入失败次数（仅本进程）。用于 /api/costs 暴露“可能漏记”的告警。
MISSED_EVENTS = 0
_INITIALIZED_DBS = set()
_INIT_GUARD = None


def _init_guard():
    global _INIT_GUARD
    if _INIT_GUARD is None:
        import threading
        _INIT_GUARD = threading.Lock()
    return _INIT_GUARD


@contextmanager
def scope(**values):
    token = META.set({**META.get(), **{key:value for key,value in values.items() if value is not None}})
    try: yield
    finally: META.reset(token)


def attributed(stage, project=None, chapter=None, role=None):
    """Context propagation across sync, async and streaming workflow functions."""
    def decorate(fn):
        signature = inspect.signature(fn)
        def values(args, kwargs):
            bound = signature.bind_partial(*args, **kwargs).arguments
            current = bound.get("self")
            root = getattr(current, "project_root", None) if project == "self" else bound.get(project) if project else None
            return {"stage":stage, "project":str(Path(root).resolve()) if root else None,
                    "chapter":bound.get(chapter) if chapter else None, "role":role}
        if inspect.isasyncgenfunction(fn):
            @functools.wraps(fn)
            async def wrapped(*args, **kwargs):
                with scope(**values(args,kwargs)):
                    async for piece in fn(*args,**kwargs): yield piece
        elif inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def wrapped(*args, **kwargs):
                with scope(**values(args,kwargs)): return await fn(*args,**kwargs)
        else:
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                with scope(**values(args,kwargs)): return fn(*args,**kwargs)
        return wrapped
    return decorate


def provider(value):
    parts = urlsplit(str(value).strip().rstrip("/"))
    host = parts.hostname or ""
    if ":" in host:host=f"[{host}]"
    if parts.port: host += f":{parts.port}"
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions","/embeddings","/rerank","/models"):
        if path.endswith(suffix): path = path[:-len(suffix)]; break
    if not path.endswith(("/v1","/openai")): path += "/v1"
    return urlunsplit((parts.scheme,host,path,"",""))


def connection(db_path):
    path = Path(db_path); path.parent.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(path,timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=20000")
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    key = str(path.resolve())
    try:
        with _init_guard():
            if key not in _INITIALIZED_DBS:
                db.executescript("""
            CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, project TEXT NOT NULL,
              chapter INTEGER NOT NULL, stage TEXT NOT NULL, model TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS usage_project_chapter ON usage_events(project,chapter);
            CREATE INDEX IF NOT EXISTS usage_created ON usage_events(created_at);
            CREATE TABLE IF NOT EXISTS pricing(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS request_budget(id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
              project TEXT NOT NULL, chapter INTEGER NOT NULL, stage TEXT NOT NULL, day TEXT NOT NULL,
              state TEXT NOT NULL, tokens INTEGER NOT NULL DEFAULT 0, cost_cny TEXT,
              unknown_cost INTEGER NOT NULL DEFAULT 0, operation TEXT);
            CREATE INDEX IF NOT EXISTS budget_project_day ON request_budget(project,day);
                """)
                _INITIALIZED_DBS.add(key)
    except BaseException:
        db.close()
        raise
    return db


def record_gap(db_path, kind):
    """Independent of the possibly broken ledger; contains no prompt or credential."""
    global MISSED_EVENTS
    MISSED_EVENTS += 1
    try:
        from fanqie_auto_publish.publication_safety import atomic_json
        folder = Path(str(db_path) + '.gaps')
        atomic_json(folder / (uuid.uuid4().hex + '.json'), {'at': datetime.now(timezone.utc).isoformat(), 'kind': kind})
    except Exception:
        print('[费用记录] 严重：独立告警也无法写入，禁止自动付费回退', flush=True)


def ledger_gaps(db_path):
    return len(list(Path(str(db_path) + '.gaps').glob('*.json')))


def empty_prices(): return {"revision":0,"usd_to_cny":None,"rates":[]}


def pricing(db_path):
    db=connection(db_path)
    try:
        row = db.execute("SELECT payload FROM pricing WHERE id=1").fetchone()
    finally: db.close()
    if not row: return empty_prices()
    try:
        value=json.loads(row[0])
    except ValueError:
        return empty_prices()
    return value if isinstance(value,dict) else empty_prices()


def number(value):
    try: amount = Decimal(str(value))
    except InvalidOperation as exc: raise ValueError("价格或汇率无效") from exc
    if not amount.is_finite() or amount < 0 or amount > 1000000: raise ValueError("价格或汇率超出范围")
    return str(amount)


class BudgetExceeded(RuntimeError):
    """请求前就被预算拦下：调用方在发请求之前收到，不会产生费用。"""
    error_code = 'budget_exceeded'
    retryable = False

    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def budget_limits(config=None):
    from .resource_policy import limits
    if config is None:
        try:
            from .model_roles import load_config
            config = load_config()
        except Exception:
            config = {}
    return limits(config)


def reserve_request(db_path, project, chapter, stage, *, tokens=0, cost_cny=None,
                    operation=None, config=None, limits=None):
    """发请求前预留一次网络尝试。超限抛 BudgetExceeded，且不写入任何占位。

    未配置任何上限时返回 None（不改动既有行为）。金额未知时记
    ``unknown_cost=1`` 并按 ``unknown_reserve_cny`` 保守占用，不当作 0。
    """
    policy = limits if limits is not None else budget_limits(config)
    if not db_path:
        return None
    capped = any(policy[key] is not None for key in ('requests_per_day', 'request_tokens', 'chapter_tokens',
                                                     'chapter_cost_cny', 'project_tokens', 'project_cost_cny'))
    if not capped:
        return None
    tokens = int(tokens or 0)
    amount = None if cost_cny is None else Decimal(str(cost_cny))
    reserve_amount = amount if amount is not None else Decimal(str(policy['unknown_reserve_cny']))
    day = _today()
    project = str(Path(project).resolve()) if project else ''
    db = None
    try:
        db = connection(db_path)
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT chapter,day,state,tokens,cost_cny,unknown_cost FROM request_budget WHERE project=?",
                          (project,)).fetchall()
        today_rows = [row for row in rows if row['day'] == day]
        chapter_rows = [row for row in rows if int(row['chapter']) == int(chapter or 0)]
        def cost_of(group):
            return sum((Decimal(row['cost_cny']) for row in group if row['cost_cny'] is not None), Decimal(0))
        checks = (
            ('requests_per_day', len(today_rows), 1, '今日请求次数已到上限'),
            ('request_tokens', 0, tokens, '本次请求 Token 超过单次上限'),
            ('chapter_tokens', sum(int(row['tokens']) for row in chapter_rows), tokens, '本章 Token 已到上限'),
            ('project_tokens', sum(int(row['tokens']) for row in rows), tokens, '本书 Token 已到上限'),
            ('chapter_cost_cny', cost_of(chapter_rows), reserve_amount, '本章费用已到上限'),
            ('project_cost_cny', cost_of(rows), reserve_amount, '本书费用已到上限'),
        )
        for key, used, delta, message in checks:
            limit = policy.get(key)
            if limit is None:
                continue
            if Decimal(used) + Decimal(delta) > Decimal(limit):
                raise BudgetExceeded(message, {'limit': key, 'limit_value': str(limit),
                                               'used': str(used), 'requested': str(delta)})
        identity = uuid.uuid4().hex
        db.execute('INSERT INTO request_budget VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (identity, datetime.now(timezone.utc).isoformat(), project, int(chapter or 0), str(stage or 'other'),
                    day, 'reserved', tokens, str(reserve_amount), 1 if amount is None else 0,
                    str(operation or '')))
        db.commit()
        return identity
    except BudgetExceeded:
        if db is not None:
            db.rollback()
        raise
    except Exception as exc:
        # 预算已开启但预留写不进去：不能假装限额仍然有效，必须挡住这次请求。
        if db is not None:
            db.rollback()
        record_gap(db_path, 'budget_reserve_failed')
        raise BudgetExceeded('预算无法预留，已停止新请求', {'error_type': type(exc).__name__}) from exc
    finally:
        if db is not None:
            db.close()


def settle_request(db_path, identity, *, tokens=None, cost_cny=None, state='settled'):
    """请求结束后结算这次预留；未知金额保持未知并带 unknown_cost 标记。"""
    if not db_path or not identity:
        return None
    db = connection(db_path)
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM request_budget WHERE id=?', (identity,)).fetchone()
        if row is None:
            db.rollback()
            record_gap(db_path, 'budget_settlement_missing')
            return None
        amount = row['cost_cny']
        if cost_cny is not None:
            amount = str(Decimal(str(cost_cny)))
        elif row['unknown_cost']:
            amount = row['cost_cny']
        db.execute('UPDATE request_budget SET state=?, tokens=COALESCE(?,tokens), cost_cny=? WHERE id=?',
                   (state, None if tokens is None else int(tokens), amount, identity))
        db.commit()
        return identity
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def budget_status(db_path, project=None, config=None, limits=None):
    """给面板看的请求预算状态；未配置上限时明确 unlimited。"""
    policy = limits if limits is not None else budget_limits(config)
    day = _today()
    result = {'day': day, 'limits': {key: policy[key] for key in
                                     ('requests_per_day', 'request_tokens', 'chapter_tokens', 'chapter_cost_cny',
                                      'project_tokens', 'project_cost_cny')},
              'unknown_reserve_cny': policy['unknown_reserve_cny'],
              'unlimited': not any(policy[key] is not None for key in
                                   ('requests_per_day', 'request_tokens', 'chapter_tokens',
                                    'chapter_cost_cny', 'project_tokens', 'project_cost_cny'))}
    if not db_path:
        return result
    db = connection(db_path)
    try:
        rows = db.execute("SELECT chapter,day,state,tokens,cost_cny,unknown_cost FROM request_budget" +
                          (" WHERE project=?" if project else ""),
                          ((str(Path(project).resolve()),) if project else ())).fetchall()
    finally:
        db.close()
    today = [row for row in rows if row['day'] == day]
    result.update({
        'requests_today': len(today),
        'tokens_today': sum(int(row['tokens']) for row in today),
        'cost_today_cny': str(sum((Decimal(row['cost_cny']) for row in today if row['cost_cny'] is not None), Decimal(0))),
        'tokens_project': sum(int(row['tokens']) for row in rows),
        'cost_project_cny': str(sum((Decimal(row['cost_cny']) for row in rows if row['cost_cny'] is not None), Decimal(0))),
        'unknown_cost_requests': sum(1 for row in rows if row['unknown_cost']),
        'pending': sum(1 for row in rows if row['state'] == 'reserved'),
    })
    return result


def price_for(doc, base_url, model, provider_id=None):
    rates = doc.get("rates") if isinstance(doc, dict) else None
    if not isinstance(rates, list):
        return None
    found = next((rate for rate in rates if isinstance(rate, dict) and rate.get("base_url")==base_url and rate.get("model")==model and (not rate.get('provider_id') or rate.get('provider_id') == provider_id)), None)
    return {**found, "revision":doc.get("revision",0), "usd_to_cny":doc.get("usd_to_cny")} if found else None


def save_prices(db_path, payload):
    rates=[]; seen=set()
    for item in payload.get("rates",[]):
        from .model_roles import validate_url
        url=provider(validate_url(item["base_url"])); model=str(item["model"]).strip()
        if not model or len(model)>200 or any(ord(c)<32 for c in model): raise ValueError("模型名称无效")
        key=(url,model)
        if key in seen: raise ValueError("相同接口与模型的价格重复")
        seen.add(key)
        currency=item.get("currency","CNY")
        if currency not in {"CNY","USD"}: raise ValueError("仅支持人民币或美元报价")
        rates.append({"base_url":url,"model":model,"currency":currency,
                      "input":number(item["input_per_million"]),"output":number(item["output_per_million"]),
                      "cached":number(item.get("cached_per_million") if item.get("cached_per_million") is not None else item["input_per_million"])})
    fx=payload.get("usd_to_cny")
    fx=number(fx) if fx is not None else None
    if fx is not None and Decimal(fx)<=0: raise ValueError("美元换算汇率必须大于零")
    db=connection(db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT payload FROM pricing WHERE id=1").fetchone()
        previous=json.loads(row[0]) if row else empty_prices()
        if previous["revision"]!=payload["revision"]: raise ValueError("价格已更新，请重新载入")
        document={"revision":previous["revision"]+1,"rates":rates,"usd_to_cny":fx}
        db.execute("INSERT INTO pricing VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",(json.dumps(document),))
        recalculated=0
        if payload.get("reprice_unpriced"):
            for row in db.execute("SELECT id,payload FROM usage_events").fetchall():
                event=json.loads(row["payload"])
                if event["status"]=="pending":continue
                # Historical priced calls remain immutable; only missing rates are filled.
                if event.get("price") is not None:
                    if event.get('pricing_scope')!='provider' and event["price"]["currency"]=="USD" and event["price"].get("usd_to_cny") is None and fx is not None:
                        event["price"]["usd_to_cny"]=fx;event["price_origin"]="later_fx"
                        event.update(calculate(event));recalculated+=1
                        db.execute("UPDATE usage_events SET payload=? WHERE id=?",(json.dumps(event),event["id"]))
                    continue
                if event.get('pricing_scope')=='provider':continue
                rate=price_for(document,event["base_url"],event["model"])
                if rate is not None:
                    event["price"]=rate; event["price_origin"]="later_configured"
                    event.update(calculate(event)); recalculated+=1
                    db.execute("UPDATE usage_events SET payload=? WHERE id=?",(json.dumps(event),event["id"]))
        db.commit()
        return {**document,"recalculated":recalculated}
    except BaseException: db.rollback(); raise
    finally: db.close()


def calculate(event):
    price=event.get("price")
    if price is None or event.get("metering") not in {"reported","estimated"}: return {"cost":None,"cost_cny":None}
    million=Decimal(1000000)
    amount=(Decimal(event["input_tokens"]-event["cached_tokens"])*Decimal(price["input"])
             +Decimal(event["cached_tokens"])*Decimal(price["cached"])
             +Decimal(event["output_tokens"])*Decimal(price["output"]))/million
    cny=amount if price["currency"]=="CNY" else amount*Decimal(price["usd_to_cny"]) if price.get("usd_to_cny") is not None else None
    return {"cost":str(amount),"cost_cny":str(cny) if cny is not None else None}


def reprice_provider(db_path,item):
    """Explicitly backfill only this connection's unpriced events, not history."""
    db=connection(db_path)
    try:
        db.execute('BEGIN IMMEDIATE');changed=0
        rows=db.execute("SELECT id,payload FROM usage_events WHERE json_extract(payload,'$.provider_id')=?",(item['id'],)).fetchall()
        for row in rows:
            event=json.loads(row['payload'])
            if event.get('price') is not None or event.get('status')=='pending':continue
            rate=item.get('pricing',{}).get(event['model'])
            if event['model'] in item.get('free_models',[]):rate={'input':'0','output':'0','cached':'0','currency':'CNY'}
            if not isinstance(rate,dict):continue
            event.update(price={**rate,'revision':item['revision']},price_origin='later_provider_configured')
            event.update(calculate(event))
            db.execute('UPDATE usage_events SET payload=? WHERE id=?',(json.dumps(event),row['id']));changed+=1
        db.commit();return changed
    except BaseException:db.rollback();raise
    finally:db.close()


def tokens(value):
    """Token 计数兼容 int / 整数值 float / 纯数字字符串（部分网关返回 10.0）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 10**12 else None
    if isinstance(value, float):
        if value.is_integer() and 0 <= value <= 10**12:
            return int(value)
        return None
    if isinstance(value, str) and re.fullmatch(r"\d{1,13}", value.strip()):
        return int(value.strip())
    return None


def parse_usage(usage, embedding=False):
    if not isinstance(usage,dict): return None
    incoming=tokens(usage.get("prompt_tokens",usage.get("input_tokens")))
    outgoing=tokens(usage.get("completion_tokens",usage.get("output_tokens")))
    if embedding:
        incoming=incoming if incoming is not None else tokens(usage.get("total_tokens")); outgoing=0
    if incoming is None or outgoing is None: return None
    detail=usage.get("prompt_tokens_details",usage.get("input_tokens_details",{})) or {}
    detail=detail if isinstance(detail,dict) else {}
    cached=tokens(detail.get("cached_tokens",usage.get("prompt_cache_hit_tokens",0)))
    cached=0 if cached is None else min(cached,incoming)
    output_detail=usage.get("completion_tokens_details",usage.get("output_tokens_details",{})) or {}
    reasoning=tokens(output_detail.get("reasoning_tokens",0)) if isinstance(output_detail,dict) else 0
    return {"input_tokens":incoming,"output_tokens":outgoing,"cached_tokens":cached,"reasoning_tokens":min(reasoning or 0,outgoing)}


def estimate(value):
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,default=str)
    cjk=len(re.findall(r"[\u3400-\u9fff]",text))
    return max(0,math.ceil(cjk*1.5+(len(text)-cjk)/4))


def _reserve_cost(price, input_tokens, max_tokens):
    """按报价与输出上限估算保守费用；缺报价或汇率时返回 None（记为未知，不当作 0）。"""
    if not isinstance(price, dict):
        return None
    try:
        inp = Decimal(str(price["input"]))
        out = Decimal(str(price["output"]))
        limit = int(max_tokens or 0)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
    if limit <= 0:
        return None
    amount = (Decimal(int(input_tokens or 0)) * inp + Decimal(limit) * out) / Decimal(1000000)
    if price.get("currency") == "USD":
        rate = price.get("usd_to_cny")
        if rate is None:
            return None
        amount *= Decimal(str(rate))
    return amount


class Attempt:
    def __init__(self, base_url, model, inputs, attempt=1, embedding=False, secret="", stage=None):
        self.db_path=META.get().get("db") or os.getenv("NOVEL_HELPER_COST_DB")
        self.secret=secret
        self.embedding=embedding; self.started=time.monotonic();self.usage=None;self.completed=False;self.output_chars=0;self.output_cjk=0
        self.input_estimate=estimate(inputs)
        self.event=None
        self.reservation=None
        if not self.db_path: return
        try:
            meta=META.get();url=provider(base_url)
            if secret: url=url.replace(secret,"[redacted]");model=str(model).replace(secret,"[redacted]")
            project=str(Path(meta["project"]).resolve()) if meta.get("project") else ""
            self.event={"id":uuid.uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),"base_url":url,"model":str(model)[:200],
              "project":project,"chapter":int(meta.get("chapter") or 0),"stage":stage or meta.get("stage","other"),"role":meta.get("role",""),
              "operation":meta.get("operation") or os.getenv("NOVEL_HELPER_OPERATION_ID",""),"attempt":attempt,
              "status":"pending","metering":"unknown","input_tokens":0,"output_tokens":0,"cached_tokens":0,"reasoning_tokens":0,
              "price":price_for(pricing(self.db_path),url,str(model)),"price_origin":"at_request","cost":None,"cost_cny":None}
            self.event.update({k: meta[k] for k in ('provider_id', 'provider_name', 'pricing_scope', 'fallback_from', 'fallback_from_model', 'fallback_reason', 'fallback_reservation') if meta.get(k)})
            selected_price = meta.get('provider_price')
            if 'provider_price' in meta:
                self.event['price'] = dict(selected_price) if isinstance(selected_price,dict) else None
            # 预留必须发生在发请求之前：超限时这里直接抛 BudgetExceeded，不产生费用。
            try:
                self.reservation = reserve_request(
                    self.db_path, self.event["project"], self.event["chapter"], self.event["stage"],
                    tokens=self.input_estimate + int((inputs or {}).get("max_tokens") or 0),
                    cost_cny=_reserve_cost(self.event["price"], self.input_estimate, (inputs or {}).get("max_tokens")),
                    operation=self.event["operation"])
            except BudgetExceeded:
                raise
            except Exception as exc:
                # 限额已开启时，预留失败就等于没有限额：这次请求不能发出去。
                record_gap(self.db_path, 'budget_reserve_failed')
                raise BudgetExceeded('预算无法预留，已停止新请求',
                                     {'error_type': type(exc).__name__}) from exc
            self.persist()
        except BudgetExceeded:
            self.event=None
            raise
        except Exception:
            self.event=None
            record_gap(self.db_path, 'initial_record_failed')
            print("[费用记录] 无法建立记录；请检查成本数据库",flush=True)

    def observe(self, payload):
        if not isinstance(payload,dict): return
        if self.event is not None and isinstance(payload.get('model'),str):
            self.event['response_model']=payload['model'].replace(self.secret,'[redacted]')[:200] if self.secret else payload['model'][:200]
        parsed=parse_usage(payload.get("usage"),self.embedding)
        if parsed is not None: self.usage=parsed
        choices=payload.get('choices')
        if self.event is not None and isinstance(choices,list) and choices and isinstance(choices[0],dict):
            reason=choices[0].get('finish_reason')
            if reason in {'stop','length','tool_calls','content_filter','function_call'}:
                self.event['finish_reason']=reason

    def output(self, value):
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,default=str)
        self.output_chars+=len(text);self.output_cjk+=len(re.findall(r"[\u3400-\u9fff]",text))

    def persist(self):
        event=self.event
        db=connection(self.db_path)
        try:
            with db:
                db.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                    (event["id"],event["created_at"],event["project"],event["chapter"],event["stage"],event["model"],json.dumps(event)))
        finally: db.close()

    def finish(self):
        if self.event is None: return
        try:
            self.event.update(status="success" if self.completed else "interrupted" if self.output_chars else "failed",
                              elapsed_ms=round((time.monotonic()-self.started)*1000))
            if self.usage is not None and not (self.output_chars and self.usage['input_tokens'] == 0 and self.usage['output_tokens'] == 0): self.event.update(self.usage,metering="reported")
            elif self.completed or self.output_chars:
                self.event.update(input_tokens=self.input_estimate,
                    output_tokens=0 if self.embedding else math.ceil(self.output_cjk*1.5+(self.output_chars-self.output_cjk)/4),metering="estimated")
            self.event.update(calculate(self.event));self.persist()
            if self.reservation is not None:
                settle_request(self.db_path, self.reservation, tokens=int(self.event.get("input_tokens") or 0)+int(self.event.get("output_tokens") or 0),
                               cost_cny=self.event.get("cost_cny"),
                               state={"success":"settled","interrupted":"cancelled"}.get(self.event["status"],"failed"))
        except Exception:
            record_gap(self.db_path, 'finalization_failed')
            print("[费用记录] 无法完成记录；保留待核对状态",flush=True)


def event_rows(db_path, project=None, chapter=None, days=0):
    clauses=[];params=[]
    if project is not None: clauses.append("project=?");params.append(str(Path(project).resolve()))
    if chapter is not None: clauses.append("chapter=?");params.append(chapter)
    if days:
        start=datetime.now(ZoneInfo("Asia/Shanghai")).date()-timedelta(days=days-1)
        boundary=datetime.combine(start,datetime.min.time(),ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc).isoformat()
        clauses.append("created_at>=?");params.append(boundary)
    query="SELECT payload FROM usage_events"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY created_at,id"
    db=connection(db_path)
    try: return [json.loads(row[0]) for row in db.execute(query,params)]
    finally: db.close()


def aggregate(events):
    result={"calls":len(events),"input_tokens":0,"output_tokens":0,"cached_tokens":0,"reasoning_tokens":0,
            "reported_calls":0,"estimated_calls":0,"unknown_usage":0,"unpriced":0,"unconverted":0,"failed_calls":0,
            "cost_cny":"0","reported_cost_cny":"0","estimated_cost_cny":"0","currencies":{},"unconverted_amounts":{}}
    total=Decimal(0);reported=Decimal(0);estimated=Decimal(0);currencies={};unconverted={}
    for event in events:
        for key in ("input_tokens","output_tokens","cached_tokens","reasoning_tokens"): result[key]+=int(event.get(key) or 0)
        metering=event.get("metering") or "unknown"
        result[{"reported":"reported_calls","estimated":"estimated_calls"}.get(metering,"unknown_usage")]+=1
        if event["status"]!="success":result["failed_calls"]+=1
        if event.get("price") is None:result["unpriced"]+=1
        if event.get("cost") is not None:
            currency=event["price"]["currency"];currencies[currency]=currencies.get(currency,Decimal(0))+Decimal(event["cost"])
        if event.get("cost_cny") is not None:
            cost=Decimal(event["cost_cny"]);total+=cost
            if metering=="reported":reported+=cost
            else:estimated+=cost
        elif event.get("cost") is not None:
            result["unconverted"]+=1
            currency=event["price"]["currency"];unconverted[currency]=unconverted.get(currency,Decimal(0))+Decimal(event["cost"])
    result.update(cost_cny=str(total),reported_cost_cny=str(reported),estimated_cost_cny=str(estimated),currencies={k:str(v) for k,v in currencies.items()},unconverted_amounts={k:str(v) for k,v in unconverted.items()})
    result["complete"]=not (result["unknown_usage"] or result["unpriced"] or result["unconverted"])
    return result


def report(db_path, project=None, chapter=None, days=0):
    from .fallback_budget import status as fallback_status
    from .resource_policy import public as resource_policy
    from .model_roles import load_config
    policy=resource_policy(load_config())
    events=event_rows(db_path,project,chapter,days)
    def groups(key, label):
        grouped={}
        for event in events:grouped.setdefault(key(event),[]).append(event)
        return [{"key":value,"label":label(items[0]),**aggregate(items)} for value,items in sorted(grouped.items())]
    summary = aggregate(events)
    gaps = ledger_gaps(db_path)
    summary.update(ledger_gaps=gaps, complete=summary['complete'] and not gaps)
    return {"summary":summary,"stages":groups(lambda e:e["stage"],lambda e:STAGES.get(e["stage"],e["stage"])),
            'providers':groups(lambda e:e.get('provider_id') or e['base_url'],lambda e:e.get('provider_name') or e['base_url']),
            'fallback':aggregate([e for e in events if e.get('fallback_from')]),
            'resource_policy':policy,'budget':budget_status(db_path,project,limits=policy['limits']),
            'fallback_budgets':fallback_status(db_path,project,limit_cny=policy['fallback_cost_limit_cny']),
            "models":groups(lambda e:(e.get('provider_id') or e["base_url"])+"|"+e["model"],lambda e:e["model"]+(' · '+e['provider_name'] if e.get('provider_name') else '')),
            "chapters":groups(lambda e:(e["project"],e["chapter"]),lambda e:f"第 {e['chapter']} 章" if e["chapter"] else "全书与共用"),
            "daily":groups(lambda e:datetime.fromisoformat(e["created_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                           lambda e:datetime.fromisoformat(e["created_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()),
            "recent":list(reversed(events[-100:])),"total_records":len(events),
            "missed_events":max(gaps, MISSED_EVENTS)}


def export_csv(db_path, **filters):
    output=io.StringIO();writer=csv.writer(output)
    columns=["created_at","project","chapter","stage","role","base_url","model","attempt","status","metering",
             "input_tokens","cached_tokens","output_tokens","reasoning_tokens","cost","cost_cny","price_origin","operation"]
    writer.writerow(columns+["currency"])
    for event in event_rows(db_path,**filters):
        row=[event.get(column,"") for column in columns]+[(event.get("price") or {}).get("currency","")]
        writer.writerow(["'"+str(value) if isinstance(value,str) and (
            value[:1] in ("=","+","-","@","\t","\r","\n") or value[:1].isspace()
        ) else value for value in row])
    return "\ufeff"+output.getvalue()


def catalog(db_path, config):
    from . import model_roles
    values={}
    def add(url,model,role=None):
        if not model:return
        key=(provider(url),model)
        item=values.setdefault(key,{"base_url":key[0],"model":model,"roles":[]})
        if role and role not in item["roles"]:item["roles"].append(role)
    for role in model_roles.ROLES:
        try:
            item=model_roles.connection(role,config);add(item["base_url"],item["model"],role)
        except ValueError:pass
    document=pricing(db_path)
    for rate in document["rates"]:add(rate["base_url"],rate["model"])
    db=connection(db_path)
    try:
        for row in db.execute("SELECT DISTINCT json_extract(payload,'$.base_url'),model FROM usage_events"):
            add(row[0],row[1])
    finally:db.close()
    return {**document,"models":list(values.values())}
