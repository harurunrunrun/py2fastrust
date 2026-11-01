"""Source-callback effects from semantic operation registries and extensions."""


def register(model,provider):
    providers=getattr(model,'callback_effect_providers',None)
    if providers is None:providers=[];model.callback_effect_providers=providers
    if provider not in providers:providers.append(provider)


def may_call(model,plan,node):
    prefix=(plan.index,id(node))
    for name in ('sorting_sites','extrema_sites'):
        for key,site in getattr(model,name,{}).items():
            if key[:2]==prefix and getattr(site,'callback',None)is not None:return True
    return any(provider(plan,node)for provider in getattr(model,'callback_effect_providers',()))
