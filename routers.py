from aiogram import Router

from handlers import start
from handlers.menu import (
    qolnlanma, 
    reklama,
    search,
    admin_menu
    
)


# Asosiy router
main_router = Router()

# Routerlarni birlashtirish
main_router.include_routers(
    start.router, 
    admin_menu.router,
    qolnlanma.router,
    reklama.router,
    search.router
)