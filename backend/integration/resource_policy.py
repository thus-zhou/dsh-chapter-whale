"""Author settings for request limits, separate from retries and platform rules."""

def public(config):
    value=config.get('resource_policy',{})
    if not isinstance(value,dict):raise ValueError('模型资源策略损坏')
    managed=value.get('provider_managed_tokens',False)
    if type(managed) is not bool:raise ValueError('Token策略无效')
    limit=value.get('fallback_cost_limit_cny','20')
    if limit is not None and str(limit)!='20':raise ValueError('费用策略无效')
    return {'provider_managed_tokens':managed,'fallback_cost_limit_cny':limit,
            'cache_policy':'provider_managed','retry_limits_preserved':True}


def configure(client,config):
    client.provider_managed_tokens=public(config)['provider_managed_tokens']
    return client
