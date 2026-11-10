"""Persist actionable error classes without credentials or provider response bodies."""
import re


def details(exc):
    chain=[];current=exc
    for _ in range(8):
        if current is None:break
        chain.append(current)
        current=current.__cause__ or current.__context__
    for item in chain:
        if getattr(item,'failure_kind',None)=='executor_stop':return {'failure_kind':'executor_stop','retryable':False}
    for item in chain:
        if getattr(item,'failure_kind',None) in {'free_pool_wait','recovery_cooldown'}:
            result={'failure_kind':item.failure_kind,'retryable':True}
            if getattr(item,'next_retry_at',None):result['next_retry_at']=item.next_retry_at
            if getattr(item,'error_code',None)=='daily_recovery_budget_exhausted':
                result['error_code']='daily_recovery_budget_exhausted'
            return result
    hard_codes={'insufficient_quota','billing_hard_limit_reached','billing_not_active',
                'invalid_api_key','account_deactivated'}
    for item in chain:
        code=getattr(item,'error_code',None)
        if isinstance(code,str) and code in hard_codes:
            result={'failure_kind':'configuration_or_access','error_code':code,'retryable':False}
            status=getattr(item,'http_status',None)
            if type(status) is int:result['http_status']=status
            return result
    status=None
    for item in chain:
        value=getattr(item,'http_status',None)
        if type(value) is int:status=value;break
        found=re.search(r'(?:HTTP\s*|API returned\s*)([45]\d\d)',str(item),re.I)
        if found:status=int(found[1]);break
    if status is not None:
        return {'failure_kind':'authentication' if status in (401,403) else 'http',
                'http_status':status,'retryable':status==429 or status>=500}
    text=' '.join((type(item).__name__+' '+str(item)).casefold() for item in chain)
    if any(word in text for word in ('invalid_api_key','insufficient_quota','缺少模型或密钥','余额不足','额度不足','验证码','风控')):
        return {'failure_kind':'configuration_or_access','retryable':False}
    for item in chain:
        retryable=getattr(item,'retryable',None)
        if type(retryable) is bool:
            result={'failure_kind':getattr(item,'failure_kind','memory_extraction'),'retryable':retryable}
            code=getattr(item,'error_code',None)
            if isinstance(code,str) and re.fullmatch(r'[a-z0-9_.-]{1,80}',code):result['error_code']=code
            if getattr(item,'next_retry_at',None):result['next_retry_at']=item.next_retry_at
            return result
    if any(word in text for word in ('timeout','timed out','超时','连接中断','connection')):
        return {'failure_kind':'transport','retryable':True}
    return {'failure_kind':'unknown','retryable':None}


class PostSaveIncomplete(RuntimeError):
    def __init__(self, result):
        message=str(result.get('message') or '本章记忆同步未完成')
        if type(result.get('http_status')) is int:
            message+=f'（HTTP {result["http_status"]}）'
        super().__init__('本章记忆同步未完成，可恢复当前正文，未提交发布：'+message)
        self.retryable=result.get('retryable')
        self.http_status=result.get('http_status')
        self.failure_kind=result.get('failure_kind','unknown')
        self.error_code=result.get('error_code')
        self.next_retry_at=result.get('next_retry_at')


class PolishIncomplete(RuntimeError):
    def __init__(self, result, stage):
        result = result if isinstance(result, dict) else {}
        super().__init__(stage + '：' + str(result.get('error') or '模型未返回有效正文'))
        self.retryable = result.get('retryable')
        self.http_status = result.get('http_status')
        self.failure_kind = result.get('failure_kind', 'unknown')
        self.error_code = result.get('error_code')
        self.next_retry_at = result.get('next_retry_at')


class ReviewIncomplete(PolishIncomplete):
    pass


class WriteIncomplete(PolishIncomplete):
    pass


class EmptyModelStream(RuntimeError):
    retryable=True
    failure_kind='model_output'


class ExecutorStopped(ValueError):
    retryable=False
    failure_kind='executor_stop'


class InvalidStructuredOutput(ValueError):
    retryable=False
    failure_kind='model_output'


class PublicationPreflightIncomplete(PolishIncomplete):
    pass


def require_polish(result, stage):
    if not isinstance(result, dict) or result.get('success') is not True or not str(result.get('content') or '').strip():
        raise PolishIncomplete(result, stage)
    return str(result['content']).strip()
