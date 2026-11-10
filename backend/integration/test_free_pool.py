import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock,AsyncMock
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from integration import bridge,free_pool,costs,retry_budget,ofm_runtime
from integration.provider_client import ProviderClient


class FreePoolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.change=patch.object(bridge,'RUNTIME_ROOT',self.root);self.change.start()
        self.current=datetime(2026,10,19,12,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.clock=patch.object(free_pool,'now',return_value=self.current);self.now_mock=self.clock.start()
        self.ready=patch.object(ofm_runtime,'ensure_started',return_value={'url':'http://127.0.0.1:18900'});self.ready.start()
        self.config={'provider_schema':1,'multi_model':True,'roles':{'B':{'provider_id':'free-pool','model_id':'auto','fallbacks':[]}},
            'default_binding':{'provider_id':'free-pool','model_id':'auto'},'providers':{
            'free-pool':{'id':'free-pool','name':'免费池','protocol':'free_pool','base_url':'http://127.0.0.1:18900/v1','api_key':'fictional',
                'allowed_projects':[str(self.root)],'pool_members':[{'model_id':'first/free','roles':['B']},{'model_id':'second/free','roles':['B']}]},
            'ofm-standalone':{'id':'ofm-standalone','protocol':'ofm_standalone','base_url':'http://127.0.0.1:18900/v1','api_key':'fictional'},
            'paid':{'id':'paid','name':'paid','protocol':'openai_compatible','base_url':'https://paid.invalid/v1','pricing':{'paid':{'input':'1','output':'2','currency':'CNY'}}}}}
        for item in self.config['providers'].values():item['revision']=1

    def tearDown(self):
        self.ready.stop();self.clock.stop();self.change.stop();self.temp.cleanup()

    def test_members_require_real_list_explicit_quota_and_roles(self):
        rows=[{'model_id':'a','roles':['B'],'quota_confirmed':True}]
        self.assertEqual(free_pool.validate_members(rows,[{'id':'a'}]),rows)
        for invalid in ([{'model_id':'a','roles':[1],'quota_confirmed':True}],
                        [{'model_id':'a','roles':['B']}],rows*2,[{'model_id':'b','roles':['B'],'quota_confirmed':True}]):
            with self.assertRaises(ValueError):free_pool.validate_members(invalid,[{'id':'a'}])

    def test_free_rotation_records_shared_budget_and_actual_provider_scope(self):
        first=Mock(chat=AsyncMock(side_effect=TimeoutError('fictional timeout')))
        async def reply(*args,**kwargs):
            self.assertEqual(costs.META.get()['provider_id'],'ofm-standalone')
            self.assertEqual(costs.META.get()['provider_price']['input'],'0');return 'fictional prose'
        second=Mock(chat=AsyncMock(side_effect=reply))
        factory=Mock(side_effect=[first,second]);client=free_pool.FreePoolClient('B',self.config,factory)
        with costs.scope(project=str(self.root)):
            self.assertEqual(asyncio.run(client.chat([])),'fictional prose')
        self.assertEqual(retry_budget.status(self.root,self.current)['used'],1)
        self.assertIsNotNone(free_pool.blocked(self.root,'first/free'))
        self.assertEqual([x.args[0]['model_id'] for x in factory.call_args_list],['first/free','second/free'])

    def test_expired_failure_resume_consumes_budget_and_preserves_history(self):
        free_pool.defer(self.root,'first/free',{'retryable':True,'failure_kind':'transport'})
        self.now_mock.return_value=self.current+timedelta(minutes=31)
        client=free_pool.FreePoolClient('B',self.config,Mock(return_value=Mock(chat=AsyncMock(return_value='done'))))
        with costs.scope(project=str(self.root)):self.assertEqual(asyncio.run(client.chat([])),'done')
        entry=free_pool.states()[free_pool.identity(self.root,'first/free')]
        self.assertEqual(entry['status'],'recovered');self.assertEqual(entry['attempts'],1)
        self.assertEqual(retry_budget.status(self.root,self.current)['used'],1)

    def test_auth_failure_waits_for_successful_login_not_daily_blind_retries(self):
        free_pool.defer(self.root,'first/free',{'retryable':False,'failure_kind':'authentication','http_status':401})
        self.now_mock.return_value=self.current+timedelta(days=3)
        self.assertIsNotNone(free_pool.blocked(self.root,'first/free'))
        free_pool.authorized_login('first')
        self.assertIsNone(free_pool.blocked(self.root,'first/free'))

    def test_seventh_extra_route_waits_instead_of_requesting(self):
        job={'project':str(self.root),'recovery_policy':{'extra_attempts_per_day':6}}
        for _ in range(6):self.assertIsNotNone(retry_budget.extension(job,self.current,immediate=True,routing=True))
        free_pool.defer(self.root,'first/free',{'retryable':True,'failure_kind':'transport'})
        self.now_mock.return_value=self.current+timedelta(minutes=31)
        factory=Mock();client=free_pool.FreePoolClient('B',self.config,factory)
        with costs.scope(project=str(self.root)),self.assertRaises(free_pool.PoolWait):asyncio.run(client.chat([]))
        factory.assert_not_called()

    def test_partial_stream_never_changes_model(self):
        async def stream(*args,**kwargs):
            yield '已开始的正文'
            raise TimeoutError('timeout')
        factory=Mock(return_value=Mock(chat_stream=stream));client=free_pool.FreePoolClient('B',self.config,factory)
        async def consume():return [x async for x in client.chat_stream([])]
        with costs.scope(project=str(self.root)),self.assertRaises(TimeoutError):asyncio.run(consume())
        self.assertEqual(factory.call_count,1)

    def test_invalid_request_and_explicit_e_stop_do_not_rotate(self):
        from integration.failure_info import ExecutorStopped
        for failure in (ExecutorStopped('stop'),ValueError('invalid request')):
            factory=Mock(return_value=Mock(chat=AsyncMock(side_effect=failure)))
            with costs.scope(project=str(self.root)),self.assertRaises(type(failure)):
                asyncio.run(free_pool.FreePoolClient('B',self.config,factory).chat([]))
            self.assertEqual(factory.call_count,1)

    def test_pool_exhaustion_then_paid_budget_exhaustion_becomes_durable_wait(self):
        self.config['roles']['B']['fallbacks']=[{'provider_id':'paid','model_id':'paid'}]
        first=Mock(chat=AsyncMock(side_effect=free_pool.PoolWait()))
        backup=Mock(chat=AsyncMock(return_value='must not run'))
        client=ProviderClient('B',self.config,first,Mock(return_value=backup))
        with costs.scope(project=str(self.root),db=str(self.root/'costs.sqlite3')),patch('integration.fallback_budget.reserve',side_effect=ValueError('每日20元自动回退预算不足')):
            with self.assertRaises(free_pool.PoolWait) as result:asyncio.run(client.chat([]))
        self.assertEqual(datetime.fromisoformat(result.exception.next_retry_at).day,20)
        backup.chat.assert_not_called()


class RuntimeSafetyTests(unittest.TestCase):
    def test_wait_survives_review_and_memory_wrappers_and_e_stop_wins(self):
        from integration.failure_info import details,ReviewIncomplete,PostSaveIncomplete,ExecutorStopped
        target=free_pool.next_day().isoformat()
        result={'retryable':True,'failure_kind':'free_pool_wait','next_retry_at':target}
        for wrapped in (ReviewIncomplete(result,'review'),PostSaveIncomplete(result)):
            self.assertEqual(details(wrapped)['next_retry_at'],target)
        stopped=ExecutorStopped('stop');stopped.__context__=free_pool.PoolWait()
        self.assertEqual(details(stopped),{'failure_kind':'executor_stop','retryable':False})
    def test_rpc_rejects_vault_export_key_access_and_unknown_fields(self):
        for method,payload in [('backup.export',{}),('gateway.getEnabled',{}),('account.create',{'provider':'gemini','shell':'bad'}),('captcha.contribute',{})]:
            with patch.object(ofm_runtime,'request') as request,self.assertRaises(ValueError):ofm_runtime.rpc(method,payload)
            request.assert_not_called()

    def test_nested_credentials_and_error_strings_are_never_exposed(self):
        result=ofm_runtime.clean({'accounts':[{'nickname':'test','credentialRef':'SECRET','access_token':'SECRET'}],
            'apiKey':{'value':'SECRET'},'balances':[{'error':'SECRET','balance':None}]})
        self.assertNotIn('SECRET',json.dumps(result));self.assertEqual(result['accounts'],[{'nickname':'test'}])

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_current_user_dpapi_roundtrip(self):
        from integration.credential_codec import transform
        original='fictional-测试-credential'.encode()
        protected=transform(original)
        self.assertNotIn(original,protected);self.assertEqual(transform(protected,False),original)
