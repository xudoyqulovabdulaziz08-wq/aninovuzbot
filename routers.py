from aiogram import Router

from handlers import start
from handlers.menu import (
    qolnlanma, 
    reklama,
    search,
    admin_menu,
    reyting,
    vip_buy,
    cabinet,
    referel
    
    
)
from handlers.admin_panel import (
    channel,
    anime_menu,
    reklama_menu,
    vip_menu,
    user_control
    
    
)
from handlers.creator_panel import (
    creator_admin_menu
)
# Asosiy router
main_router = Router()

# Routerlarni birlashtirish
main_router.include_routers(
    start.router, # start router
    creator_admin_menu.router, #creator panel router
    admin_menu.router, #menu/admin va creator menu router
    anime_menu.router, #admin_panel/anime_menu router
    reklama_menu.router, #admin_panel/reklama_menu router
    vip_menu.router, #admin_panel/vip_menu router
    user_control.router, #admin_panel/user_control router
    channel.router, #admin_panel/channel router
    qolnlanma.router, #menu/qollanma router (fayl yozilisida xatolik)
    reklama.router, #menu/reklama router
    reyting.router, #menu/reyting routter
    vip_buy.router, #menu/vip bolimi router
    cabinet.router, #menu/cabinet router
    referel.router, #menu/referel router
    search.router   #menu/ search router doimo pastda
    
)