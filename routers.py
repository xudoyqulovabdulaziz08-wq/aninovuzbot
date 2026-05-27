from aiogram import Router

from handlers import start
from handlers.menu import (
    qollanma, 
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
from handlers.admin_panel.anime_main import(
    anime_add,
    anime_lists
)
# Asosiy router
main_router = Router()

# Routerlarni birlashtirish
main_router.include_routers(
    # 1 start routeri doimo yuqorida bo'lishi kerak, chunki u eng umumiy va ko'p ishlatiladi
    start.router, # start router

    # 2. Admin va Creator menu routerlari (ular bir-biriga yaqin joylashgan, chunki ular boshqaruv paneli bilan bog'liq)
    creator_admin_menu.router, #creator panel router
    admin_menu.router, #menu/admin va creator menu router

    # 3. Admin panelining ichki routerlari (ular bir-biriga yaqin joylashgan, chunki ular admin paneli bilan bog'liq)
    anime_menu.router, #admin_panel/anime_menu router
    reklama_menu.router, #admin_panel/reklama_menu router
    vip_menu.router, #admin_panel/vip_menu router
    user_control.router, #admin_panel/user_control router
    channel.router, #admin_panel/channel router

    # 4. Anime  routerlari
    anime_add.router, #admin_panel/anime_main/anime_add router
    anime_lists.router, #admin_panel/anime_main/anime_lists router
    # 5. Qo'llanma, reklama, reyting, vip_buy, cabinet, referel va search routerlari (ular menyu bilan bog'liq)
    qollanma.router, #menu/qollanma router 
    reklama.router, #menu/reklama router
    reyting.router, #menu/reyting routter
    vip_buy.router, #menu/vip bolimi router
    cabinet.router, #menu/cabinet router
    referel.router, #menu/referel router

    # 6. Search routeri doimo pastda bo'lishi kerak, chunki u eng umumiy va ko'p ishlatiladi
    search.router   #menu/ search router doimo pastda
    
)