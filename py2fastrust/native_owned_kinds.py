"""Reachable native operations expose the concrete storage kinds they own."""


def register(model,provider):
    providers=getattr(model,'owned_kind_providers',None)
    if providers is None:providers=[];model.owned_kind_providers=providers
    if provider not in providers:providers.append(provider)


def kinds(model):
    for provider in getattr(model,'owned_kind_providers',()):yield from provider()
