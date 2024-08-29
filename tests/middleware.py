from asgiref.sync import iscoroutinefunction
from django.utils.decorators import async_only_middleware, sync_only_middleware


@sync_only_middleware
def sync_middleware_1(get_response):
    def middleware(request):
        response = get_response(request)
        return response

    return middleware


@async_only_middleware
def async_middleware_1(get_response):
    async def middleware(request):
        response = await get_response(request)
        return response

    return middleware


@sync_only_middleware
def sync_middleware_2(get_response):
    def middleware(request):
        response = get_response(request)
        return response

    return middleware


@async_only_middleware
def async_middleware_2(get_response):
    async def middleware(request):
        response = await get_response(request)
        return response

    return middleware
