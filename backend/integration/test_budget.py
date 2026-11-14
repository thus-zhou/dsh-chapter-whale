"""M02 checks: request reservations, unknown-cost handling, context budgets.

全部离线；不读作者真实 ai_config（用临时文件 + 环境变量覆盖），不发任何请求。
"""
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from integration import context_budget, costs, fallback_budget, resource_policy


class BudgetBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cw-budget-')
        self.root = Path(self.tmp.name)
        self.db = self.root / 'costs.sqlite3'
        self.project = self.root / 'book'
        self.project.mkdir()
        self.config_path = self.root / 'ai_config.json'
        self._old = os.environ.get('NOVEL_HELPER_AI_CONFIG')
        os.environ['NOVEL_HELPER_AI_CONFIG'] = str(self.config_path)

    def tearDown(self):
        if self._old is None:
            os.environ.pop('NOVEL_HELPER_AI_CONFIG', None)
        else:
            os.environ['NOVEL_HELPER_AI_CONFIG'] = self._old
        costs.MISSED_EVENTS = 0
        self.tmp.cleanup()

    def policy(self, **values):
        base = dict(values)
        self.config_path.write_text(json.dumps({'resource_policy': base}), encoding='utf-8')
        return base


class LimitsTest(BudgetBase):
    def test_defaults_are_unlimited_but_rounds_and_attempts_are_bounded(self):
        policy = resource_policy.limits({})
        self.assertIsNone(policy['requests_per_day'])
        self.assertIsNone(policy['project_cost_cny'])
        self.assertEqual(policy['revision_rounds'], 1)
        self.assertEqual(policy['network_attempts'], 2)

    def test_invalid_values_are_rejected(self):
        for bad in ({'revision_rounds': 4}, {'network_attempts': 3}, {'context_profile': 'huge'},
                    {'requests_per_day': 'many'}, {'chapter_cost_cny': '-1'}):
            with self.assertRaises(ValueError):
                resource_policy.limits({'resource_policy': bad})

    def test_configure_only_tightens_retries(self):
        class Client: pass
        client = Client()
        client.max_retries = 1
        resource_policy.configure(client, {'resource_policy': {'network_attempts': 2}})
        self.assertEqual(client.max_retries, 1)
        fresh = Client()
        resource_policy.configure(fresh, {'resource_policy': {'network_attempts': 2}})
        self.assertEqual(fresh.max_retries, 2)


class ContextBudgetTest(unittest.TestCase):
    def test_profile_is_an_upper_bound_even_with_a_big_window(self):
        plan = context_budget.plan([], profile='quick', model_window=200000, max_output=1024, safety=1024)
        self.assertEqual(plan['available'], 8000)
        plan = context_budget.plan([], profile='generous', model_window=200000, max_output=1024, safety=1024)
        self.assertEqual(plan['available'], 32000)

    def test_window_output_and_margin_shrink_the_budget(self):
        plan = context_budget.plan([], profile='generous', model_window=20000, max_output=4096, safety=1024)
        self.assertEqual(plan['available'], 20000 - 4096 - 1024)
        self.assertEqual(plan['window_origin'], 'model_reported')

    def test_unknown_window_requires_configuration(self):
        with self.assertRaises(context_budget.BudgetUnconfigured) as raised:
            context_budget.plan([], profile='standard')
        self.assertEqual(raised.exception.reason, 'model_window_unknown')

    def test_configured_conservative_window_is_used_and_reported(self):
        plan = context_budget.plan([], profile='standard', conservative_window=12000,
                                   max_output=2048, safety=1024)
        self.assertEqual(plan['window_origin'], 'configured_conservative')
        self.assertEqual(plan['available'], min(16000, 12000 - 2048 - 1024))

    def test_required_blocks_stop_instead_of_being_trimmed(self):
        with self.assertRaises(context_budget.CannotFit) as raised:
            context_budget.plan([{'name': 'task', 'content': '任' * 5000, 'required': True},
                                 {'name': 'contract', 'content': '约' * 5000, 'required': True}],
                                profile='quick', conservative_window=16000, estimator=len)
        self.assertEqual(raised.exception.reason, 'required_exceeds_budget')
        self.assertGreater(raised.exception.detail['over_by'], 0)

    def test_optional_blocks_fill_in_order_and_dropped_ones_are_named(self):
        plan = context_budget.plan([{'name': 'task', 'content': 'x' * 10, 'required': True},
                                    {'name': 'ref', 'content': 'y' * 100},
                                    {'name': 'big', 'content': 'z' * 100000}],
                                   profile='quick', conservative_window=12000, estimator=len)
        self.assertIn('ref', plan['included'])
        self.assertEqual([item['name'] for item in plan['dropped']], ['big'])
        self.assertEqual(plan['dropped'][0]['reason'], 'budget_exhausted')
        self.assertTrue(plan['estimated'])

    def test_fits_wrapper(self):
        self.assertFalse(context_budget.fits([], profile='standard'))
        self.assertTrue(context_budget.fits([], profile='standard', conservative_window=20000))


class ReserveTest(BudgetBase):
    def test_unlimited_means_no_reservation(self):
        self.assertIsNone(costs.reserve_request(self.db, self.project, 1, 'draft', tokens=10))

    def test_daily_request_cap_blocks_before_the_request(self):
        limits = dict(resource_policy.limits({'resource_policy': {'requests_per_day': 2}}))
        self.assertIsNotNone(costs.reserve_request(self.db, self.project, 1, 'draft', limits=limits))
        self.assertIsNotNone(costs.reserve_request(self.db, self.project, 1, 'draft', limits=limits))
        with self.assertRaises(costs.BudgetExceeded) as raised:
            costs.reserve_request(self.db, self.project, 1, 'draft', limits=limits)
        self.assertEqual(raised.exception.detail['limit'], 'requests_per_day')
        self.assertEqual(costs.budget_status(self.db, self.project, limits=limits)['requests_today'], 2)

    def test_chapter_and_project_token_caps(self):
        limits = dict(resource_policy.limits({'resource_policy': {'chapter_tokens': 1000, 'project_tokens': 1500}}))
        costs.reserve_request(self.db, self.project, 1, 'draft', tokens=900, limits=limits)
        with self.assertRaises(costs.BudgetExceeded):
            costs.reserve_request(self.db, self.project, 1, 'draft', tokens=200, limits=limits)
        costs.reserve_request(self.db, self.project, 2, 'draft', tokens=500, limits=limits)
        with self.assertRaises(costs.BudgetExceeded) as raised:
            costs.reserve_request(self.db, self.project, 3, 'draft', tokens=200, limits=limits)
        self.assertEqual(raised.exception.detail['limit'], 'project_tokens')

    def test_unknown_cost_is_reserved_conservatively_not_zero(self):
        limits = dict(resource_policy.limits({'resource_policy': {'project_cost_cny': '1.5',
                                                                  'unknown_reserve_cny': '1'}}))
        costs.reserve_request(self.db, self.project, 1, 'draft', tokens=10, cost_cny=None, limits=limits)
        status = costs.budget_status(self.db, self.project, limits=limits)
        self.assertEqual(status['unknown_cost_requests'], 1)
        self.assertEqual(Decimal(status['cost_project_cny']), Decimal('1'))
        with self.assertRaises(costs.BudgetExceeded) as raised:
            costs.reserve_request(self.db, self.project, 1, 'draft', tokens=10, cost_cny=None, limits=limits)
        self.assertEqual(raised.exception.detail['limit'], 'project_cost_cny')

    def test_settle_records_actual_usage_and_state(self):
        limits = dict(resource_policy.limits({'resource_policy': {'requests_per_day': 5}}))
        identity = costs.reserve_request(self.db, self.project, 1, 'review', tokens=100, cost_cny='0.5', limits=limits)
        costs.settle_request(self.db, identity, tokens=1200, cost_cny='0.42', state='settled')
        status = costs.budget_status(self.db, self.project, limits=limits)
        self.assertEqual(status['tokens_project'], 1200)
        self.assertEqual(Decimal(status['cost_project_cny']), Decimal('0.42'))
        self.assertEqual(status['pending'], 0)

    def test_counts_survive_a_new_process_and_are_shared(self):
        limits = dict(resource_policy.limits({'resource_policy': {'requests_per_day': 1}}))
        costs.reserve_request(self.db, self.project, 1, 'draft', limits=limits)
        costs._INITIALIZED_DBS.clear()  # 模拟新进程重新打开同一数据库
        with self.assertRaises(costs.BudgetExceeded):
            costs.reserve_request(self.db, self.project, 2, 'draft', limits=limits)

    def test_missing_reservation_on_settle_records_a_gap(self):
        costs.settle_request(self.db, 'not-a-real-id')
        self.assertEqual(costs.ledger_gaps(self.db), 1)


class AttemptHookTest(BudgetBase):
    def _payload(self):
        return {'messages': [{'role': 'user', 'content': '写一段'}], 'max_tokens': 100}

    def test_attempt_raises_before_any_event_when_the_budget_is_gone(self):
        self.policy(requests_per_day=0)
        with costs.scope(db=str(self.db), project=str(self.project), chapter=1):
            with self.assertRaises(costs.BudgetExceeded):
                costs.Attempt('https://api.example.com/v1', 'm', self._payload())
        self.assertEqual(costs.event_rows(self.db), [])

    def test_attempt_reserves_then_settles_on_finish(self):
        self.policy(requests_per_day=3, chapter_tokens=100000)
        with costs.scope(db=str(self.db), project=str(self.project), chapter=1, stage='draft'):
            meter = costs.Attempt('https://api.example.com/v1', 'm', self._payload())
            meter.completed = True
            meter.output('正文')
            meter.finish()
        status = costs.budget_status(self.db, self.project)
        self.assertEqual(status['requests_today'], 1)
        self.assertEqual(status['pending'], 0)

    def test_without_policy_attempts_behave_as_before(self):
        with costs.scope(db=str(self.db), project=str(self.project), chapter=1, stage='draft'):
            meter = costs.Attempt('https://api.example.com/v1', 'm', self._payload())
            meter.completed = True
            meter.finish()
        self.assertEqual(len(costs.event_rows(self.db)), 1)
        self.assertTrue(costs.budget_status(self.db, self.project)['unlimited'])


class FallbackCancelTest(BudgetBase):
    def test_cancel_keeps_the_reservation_as_conservative_hold(self):
        identity = fallback_budget.reserve(self.db, self.project,
                                          {'input': '1', 'output': '2', 'currency': 'CNY'},
                                          [{'role': 'user', 'content': 'x'}], 100)
        fallback_budget.cancel(self.db, identity)
        rows = fallback_budget.status(self.db, self.project)
        self.assertGreater(Decimal(rows[0]['reserved_cny']), Decimal(0))


class MemoryBudgetTest(BudgetBase):
    def test_unconfigured_model_window_keeps_the_legacy_budget(self):
        from integration import memory_library
        self.assertEqual(memory_library.context_budget_default(), 12000)

    def test_configured_window_caps_the_memory_context(self):
        from integration import memory_library
        self.policy(model_window=24000, context_profile='standard', output_tokens=4096, safety_tokens=1024)
        self.assertEqual(memory_library.context_budget_default(), min(16000, 24000 - 4096 - 1024))


if __name__ == '__main__':
    unittest.main()
