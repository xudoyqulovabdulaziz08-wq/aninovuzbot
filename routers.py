from aiogram import Router

from handlers import start
from handlers.menu import (
    qolnlanma, 
    reklama,
    search,
    admin_menu,
    reyting,
    vip_buy,
    cabinet
    
    
)
from handlers.admin_panel import (
    channel
)

# Asosiy router
main_router = Router()

# Routerlarni birlashtirish
main_router.include_routers(
    start.router, # start router
    admin_menu.router, #menu/admin va creator menu router
    channel.router, #admin_panel/channel router
    qolnlanma.router, #menu/qollanma router (fayl yozilisida xatolik)
    reklama.router, #menu/reklama router
    reyting.router, #menu/reyting routter
    vip_buy.router, #menu/vip bolimi router
    cabinet.router, #menu/cabinet router
    search.router   #menu/ search router doimo pastda
    
)