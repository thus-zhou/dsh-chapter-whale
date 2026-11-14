"""Author settings for request limits, separate from retries and platform rules."""
from . import context_budget

DEFAULTS = {'requests_per_day': None, 'request_tokens': None, 'chapter_tokens': None,
            'chapter_cost_cny': None, 'project_tokens': None, 'project_cost_cny': None,
            'unknown_reserve_cny': '1', 'revision_rounds': 1, 'network_attempts': 2,
            'context_profile': context_budget.DEFAULT_PROFILE,
            'model_window': None, 'output_tokens': 4096, 'safety_tokens': 1024}
_INT_KEYS = ('requests_per_day', 'request_tokens', 'chapter_tokens',
             'project_tokens', 'model_window', 'output_tokens', 'safety_tokens')
_COST_KEYS = ('chapter_cost_cny', 'project_cost_cny')


def _optional_int(value, label, low, high):
    if value is None:
        return None
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label}无效')
    return value


def limits(config):
    """请求数、Token、费用上限与轮数策略；未设置即 None（不擅自设限）。"""
    value = config.get('resource_policy', {}) if isinstance(config, dict) else {}
    if not isinstance(value, dict):
        raise ValueError('模型资源策略损坏')
    result = dict(DEFAULTS)
    for key in _INT_KEYS:
        if key in value:
            result[key] = _optional_int(value[key], f'{key} 上限', 0, 10 ** 9)
    from .costs import number
    for key in _COST_KEYS:
        if key in value and value[key] is not None:
            result[key] = number(value[key])
    if 'unknown_reserve_cny' in value:
        result['unknown_reserve_cny'] = number(value['unknown_reserve_cny'])
    rounds = value.get('revision_rounds', DEFAULTS['revision_rounds'])
    if type(rounds) is not int or not 0 <= rounds <= 3:
        raise ValueError('自动修订轮数只能是 0 到 3')
    result['revision_rounds'] = rounds
    attempts = value.get('network_attempts', DEFAULTS['network_attempts'])
    if type(attempts) is not int or not 1 <= attempts <= 2:
        raise ValueError('每步网络尝试次数只能是 1 或 2')
    result['network_attempts'] = attempts
    profile = value.get('context_profile', DEFAULTS['context_profile'])
    if profile not in context_budget.PROFILES:
        raise ValueError('上下文档位无效')
    result['context_profile'] = profile
    return result


def context(config, **overrides):
    """供 context_budget.plan 使用的窗口参数（未知窗口保持 Unknown）。"""
    policy = limits(config)
    options = {'profile': policy['context_profile'], 'model_window': policy['model_window'],
               'max_output': policy['output_tokens'], 'safety': policy['safety_tokens']}
    options.update({key: value for key, value in overrides.items() if value is not None})
    return options


def public(config):
    value = config.get('resource_policy', {})
    if not isinstance(value, dict): raise ValueError('模型资源策略损坏')
    managed = value.get('provider_managed_tokens', False)
    if type(managed) is not bool: raise ValueError('Token策略无效')
    limit = value.get('fallback_cost_limit_cny', '20')
    if limit is not None and str(limit) != '20': raise ValueError('费用策略无效')
    policy = limits(config)
    return {'provider_managed_tokens': managed, 'fallback_cost_limit_cny': limit,
            'cache_policy': 'provider_managed', 'retry_limits_preserved': True,
            'limits': {key: policy[key] for key in sorted(policy)},
            'context_profile': policy['context_profile']}


def configure(client, config):
    policy = limits(config)
    client.provider_managed_tokens = public(config)['provider_managed_tokens']
    # 只收紧、不放松：调用方原先设得更少（例如 1 次）时保持原值，避免多计费。
    current = getattr(client, 'max_retries', None)
    client.max_retries = policy['network_attempts'] if current is None else min(int(current), policy['network_attempts'])
    return client
