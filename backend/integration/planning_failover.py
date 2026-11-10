"""Opt-in, per-book planning failover. Caller owns the book's writer lock."""
import copy
import hashlib
import json
import time
from pathlib import Path
from . import model_roles as roles, writer_runner as writer, failure_info


def transient(exc):
    """Inspect real causes, not the generic wrapper which says 'or timeout'."""
    info = failure_info.details(exc)
    # The shared classifier treats 408 as a terminal 4xx. Planning may fail
    # over this explicit request timeout, but never a quota/auth/budget error.
    request_timeout = info.get('failure_kind') == 'http' and info.get('http_status') == 408
    if info.get('retryable') is False and not request_timeout:
        return False
    if info.get('http_status') is not None:
        return info['http_status'] in (408, 429, 500, 502, 503, 504)
    current = exc
    for _ in range(8):
        if current is None:
            break
        if isinstance(current, (TimeoutError, ConnectionError)) or type(current).__name__ in {
            'ClientConnectionError', 'ClientConnectorError', 'ServerDisconnectedError',
            'ServerTimeoutError', 'ConnectionTimeoutError', 'SocketTimeoutError', 'ClientPayloadError'}:
            return True
        current = current.__cause__ or current.__context__
    return False


def signature(connection):
    # Credentials never enter persistent routing records.
    return hashlib.sha256(json.dumps({k: connection[k] for k in ('base_url', 'model')},
                                    sort_keys=True).encode()).hexdigest()


class PlanningRouter:
    def __init__(self, project):
        root = Path(project) / '.webnovel'
        self.state_path = root / 'planning_failover_state.json'
        self.policy = writer.strict_json(root / 'planning_failover.json', {})
        self.enabled = self.policy.get('enabled') is True
        # Registry-era routing has a single explicit provider fallback chain;
        # legacy role-to-role failover must not bypass its shared budget.
        if roles.load_config().get('provider_schema') == 1:self.enabled=False
        self.selected = 'A'
        if not self.enabled:
            return
        self.config = roles.load_config()
        if not roles.enabled(self.config):
            raise ValueError('规划备用模型需要开启多模型配置')
        self.fallback_role = self.policy.get('fallback_role', 'B')
        if self.fallback_role not in ('B', 'C', 'D', 'E'):
            raise ValueError('规划备用模型必须来自已配置的B–E角色')
        self.primary = roles.connection('A', self.config)
        self.fallback = roles.connection(self.fallback_role, self.config)
        if signature(self.primary) == signature(self.fallback):
            raise ValueError('规划首选和备用模型不能相同')
        self.state = writer.strict_json(self.state_path, {})
        if (self.state.get('primary_signature') == signature(self.primary)
                and self.state.get('cooldown_until', 0) > time.time()):
            self.selected = self.fallback_role

    def record(self, event, **fields):
        events = self.state.get('events', [])[-99:]
        events.append({'at': time.time(), 'event': event, **fields})
        self.state['events'] = events
        writer.atomic_json(self.state_path, self.state)

    async def call(self, prompt, **kwargs):
        if not self.enabled:
            return await roles.json_call('A', prompt, **kwargs)
        if self.selected == 'A':
            try:
                result = await roles.json_call('A', prompt, config=self.config, **kwargs)
            except Exception as exc:
                if not transient(exc):
                    raise
                self.state.update(primary_signature=signature(self.primary),
                                  cooldown_until=time.time() + 1800)
                self.record('primary_transient_failure', model=self.primary['model'],
                            **failure_info.details(exc))
                self.selected = self.fallback_role
            else:
                self.state.update(primary_signature=signature(self.primary), cooldown_until=0)
                self.record('primary_response_received', model=self.primary['model'])
                return result
        # Preserve the logical A role and planning cost attribution, while using
        # the alternate connection's own key. Never change the user's config.
        routed = copy.deepcopy(self.config)
        routed.setdefault('roles', {})['A'] = dict(self.fallback)
        self.record('fallback_started', model=self.fallback['model'],
                    connection_role=self.fallback_role)
        print(f"规划A临时使用已配置的{self.fallback_role}模型（{self.fallback['model']}）；首选配置保持不变", flush=True)
        try:
            result = await roles.json_call('A', prompt, config=routed, **kwargs)
        except Exception as exc:
            self.record('fallback_failed', model=self.fallback['model'], **failure_info.details(exc))
            raise
        self.record('fallback_response_received', model=self.fallback['model'])
        return result
