"""Per-binding reasoning settings, independent of credentials and model routing."""
LEVELS=('auto','off','low','medium','high','max')


def validate(value):
    if not isinstance(value,str) or value not in LEVELS:
        raise ValueError('思考强度必须为auto、off、low、medium、high或max')
    return value


def selected(config,role,binding=None):
    """Explicit role setting wins; inherited connections keep role preferences."""
    own=config.get('roles',{}).get(role,{}) if config.get('multi_model') else {}
    default=config.get('default_binding',{})
    source=binding if binding is not None else own if own.get('provider_id') else default
    return validate(own.get('reasoning_effort',source.get('reasoning_effort','auto')))


def apply(client,role,setting):
    setting=validate(setting)
    client.reasoning_setting=setting
    name=client.model.casefold().split('/')[-1]
    if setting=='auto':
        client.reasoning_effort=('high' if role in {'A','D'} else 'low') if name.startswith('deepseek-v4') or name in {'deepseek-flash','glm-5.3','glm-5.3-flash','glm-5.3-flashx'} else None
    else:client.reasoning_effort=None if setting=='off' else setting
    return client
