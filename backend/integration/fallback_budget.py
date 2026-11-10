"""Atomic conservative reservations for author-approved paid fallbacks."""
import json
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from . import costs


def reserve(db_path, project, price, messages, max_tokens):
    if not db_path or not project or costs.ledger_gaps(db_path) or costs.MISSED_EVENTS:
        raise ValueError('成本记录不完整，禁止自动付费回退')
    price = dict(price or {})
    if any(k not in price for k in ('input','output','currency')):raise ValueError('备选模型缺少报价')
    if price['currency'] not in {'CNY','USD'}:raise ValueError('备选模型币种无效')
    for key in ('input','output'):costs.number(price[key])
    if 'cached' in price:costs.number(price['cached'])
    if type(max_tokens) is not int or max_tokens<=0:raise ValueError('备选请求缺少输出上限')
    input_bound=max(costs.estimate(messages),len(json.dumps(messages,ensure_ascii=False).encode('utf-8'))+64*(len(messages) if isinstance(messages,list) else 1))
    input_rate=max(Decimal(str(price['input'])),Decimal(str(price.get('cached',price['input']))))
    amount = (Decimal(input_bound)*input_rate + Decimal(max_tokens)*Decimal(str(price['output'])))/Decimal(1000000)
    if price['currency'] == 'USD':
        if not price.get('usd_to_cny') or Decimal(costs.number(price['usd_to_cny']))<=0:raise ValueError('备选模型缺少汇率')
        amount *= Decimal(str(price['usd_to_cny']))
    if not amount.is_finite() or amount < 0:raise ValueError('备选模型报价无效')
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    db = costs.connection(db_path)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS fallback_reservations(id TEXT PRIMARY KEY,project TEXT,day TEXT,amount TEXT,state TEXT)')
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('SELECT amount FROM fallback_reservations WHERE project=? AND day=?',(str(project),day)).fetchall()
        if sum((Decimal(row[0]) for row in rows),Decimal(0))+amount > Decimal(20):raise ValueError('每日20元自动回退预算不足')
        identity=uuid.uuid4().hex
        db.execute('INSERT INTO fallback_reservations VALUES (?,?,?,?,?)',(identity,str(project),day,str(amount),'reserved'))
        db.commit();return identity
    except BaseException:db.rollback();raise
    finally:db.close()


def settle(db_path, identity):
    db=costs.connection(db_path)
    try:
        db.execute('BEGIN IMMEDIATE')
        events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM usage_events')]
        selected=[e for e in events if e.get('fallback_reservation')==identity]
        if not selected or any(e.get('cost_cny') is None or e.get('metering')!='reported' or e.get('status')=='pending' for e in selected):
            costs.record_gap(db_path,'fallback_settlement_unknown')
        else:
            amount=sum((Decimal(e['cost_cny']) for e in selected),Decimal(0))
            db.execute('UPDATE fallback_reservations SET amount=?,state=? WHERE id=?',(str(amount),'settled',identity))
        db.commit()
    except BaseException:
        db.rollback();costs.record_gap(db_path,'fallback_settlement_failed');raise
    finally:db.close()


def status(db_path,project=None,limit_cny='20'):
    day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    db=costs.connection(db_path)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fallback_reservations'").fetchone():return []
        rows=db.execute('SELECT project,amount,state FROM fallback_reservations WHERE day=?'+(' AND project=?' if project else ''),(day,str(project)) if project else (day,)).fetchall()
        groups={}
        for row in rows:
            entry=groups.setdefault(row['project'],{'project':row['project'],'day':day,'limit_cny':limit_cny,'reserved_cny':Decimal(0),'settled_cny':Decimal(0)})
            entry['settled_cny' if row['state']=='settled' else 'reserved_cny']+=Decimal(row['amount'])
        for entry in groups.values():
            entry['remaining_cny']=None if limit_cny is None else str(max(Decimal(0),Decimal(limit_cny)-entry['reserved_cny']-entry['settled_cny']))
            for key in ('reserved_cny','settled_cny'):entry[key]=str(entry[key])
        return list(groups.values())
    finally:db.close()
