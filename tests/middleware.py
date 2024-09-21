from django.utils.decorators import async_only_middleware, sync_only_middleware


@sync_only_middleware
def sync_middleware_1(get_response):
    def middleware(request):
        return get_response(request)

    return middleware


@async_only_middleware
def async_middleware_1(get_response):
    async def middleware(request):
        return await get_response(request)

    return middleware


@sync_only_middleware
def sync_middleware_2(get_response):
    def middleware(request):
        return get_response(request)

    return middleware


@async_only_middleware
def async_middleware_2(get_response):
    async def middleware(request):
        return await get_response(request)

    return middleware
