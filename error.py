import logging
from aiohttp import web

logger = logging.getLogger("ErrorHandler")

async def error_middleware(app, handler):
    """Aiohttp uchun HTTP-level middleware."""
    async def middleware_handler(request):
        try:
            return await handler(request)
        except web.HTTPException as ex:
            # 404 yoki boshqa ma'lum HTTP xatolar bo'lsa, o'z holicha qaytaramiz
            if ex.status != 404:
                logger.warning(f"HTTP Warning: {request.path} -> {ex.status}")
            raise ex
        except Exception as e:
            # Kutilmagan (500) xatolar uchun
            logger.exception(f"💥 CRITICAL WEB ERROR: {request.method} {request.path} | Error: {e}")
            return web.json_response(
                {"ok": False, "error": "Internal Server Error"}, 
                status=500
            )
    return middleware_handler

async def handle_404(request):
    """Noma'lum endpointlar uchun."""
    return web.json_response({"ok": False, "error": "Endpoint not found"}, status=404)

async def handle_500(request):
    """Global 500 xatolar uchun (Agar middleware'dan o'tib ketsa)."""
    return web.json_response({"ok": False, "error": "Unexpected server error"}, status=500)