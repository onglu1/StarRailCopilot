# Android button templates; source canvases are under assets/cn/currency_wars/ui.
from module.base.button import Button, ButtonWrapper

FAST_BUTTONS = {}

BOARD = ButtonWrapper(
    name='CW_BOARD',
    cn=Button(
        file='./assets/cn/currency_wars/ui/board3.png',
        area=(308, 9, 380, 33),
        search=(275, 0, 410, 72),
        color=(56, 56, 83),
        button=(308, 9, 380, 33),
    ),
)
FAST_BUTTONS.setdefault('备战阶段', []).append(BOARD)
FAST_BUTTONS.setdefault('准备阶段', []).append(BOARD)

BOARD_SHOP = ButtonWrapper(
    name='CW_BOARD_SHOP',
    cn=Button(
        file='./assets/cn/currency_wars/ui/shop_actual.png',
        area=(40, 29, 118, 53),
        search=(0, 0, 175, 105),
        color=(67, 76, 123),
        button=(40, 29, 118, 53),
    ),
)
FAST_BUTTONS.setdefault('备战阶段', []).append(BOARD_SHOP)
FAST_BUTTONS.setdefault('准备阶段', []).append(BOARD_SHOP)
FAST_BUTTONS.setdefault('ShopView', []).append(BOARD_SHOP)

OVERCLOCK = ButtonWrapper(
    name='CW_OVERCLOCK',
    cn=Button(
        file='./assets/cn/currency_wars/ui/wly-20261005-053414_entered.png',
        area=(34, 493, 74, 523),
        search=(15, 478, 95, 528),
        color=(26, 81, 111),
        button=(34, 493, 74, 523),
    ),
)
FAST_BUTTONS.setdefault('OverclockView', []).append(OVERCLOCK)

SHOP = ButtonWrapper(
    name='CW_SHOP',
    cn=Button(
        file='./assets/cn/currency_wars/ui/board3.png',
        area=(1171, 644, 1217, 670),
        search=(1120, 620, 1260, 695),
        color=(203, 205, 215),
        button=(1171, 644, 1217, 670),
    ),
)
FAST_BUTTONS.setdefault('商店', []).append(SHOP)

FOLD = ButtonWrapper(
    name='CW_FOLD',
    cn=Button(
        file='./assets/cn/currency_wars/ui/shop_actual.png',
        area=(1171, 644, 1217, 670),
        search=(1120, 620, 1260, 695),
        color=(57, 57, 57),
        button=(1171, 644, 1217, 670),
    ),
)
FAST_BUTTONS.setdefault('收起', []).append(FOLD)

EQUIPMENT_COMBINE_CANCEL = ButtonWrapper(
    name='CW_EQUIPMENT_COMBINE_CANCEL',
    cn=Button(
        file='./assets/cn/currency_wars/ui/wly-refresh-error.png',
        area=(1021, 386, 1051, 416),
        search=(980, 355, 1085, 445),
        color=(240, 200, 195),
        button=(1021, 386, 1051, 416),
    ),
)
FAST_BUTTONS.setdefault('EquipmentCombineCancel', []).append(EQUIPMENT_COMBINE_CANCEL)

EQUIPMENT_COMBINE_CONFIRM = ButtonWrapper(
    name='CW_EQUIPMENT_COMBINE_CONFIRM',
    cn=Button(
        file='./assets/cn/currency_wars/ui/wly-refresh-error.png',
        area=(1117, 386, 1147, 416),
        search=(1080, 355, 1200, 445),
        color=(210, 225, 206),
        button=(1117, 386, 1147, 416),
    ),
)
FAST_BUTTONS.setdefault('EquipmentCombineConfirm', []).append(EQUIPMENT_COMBINE_CONFIRM)

DIFFICULTY_LOCKED_NEXT = ButtonWrapper(
    name='CW_DIFFICULTY_LOCKED_NEXT',
    cn=Button(
        file='./assets/cn/currency_wars/ui/currency-highest-locked.png',
        area=(598, 149, 617, 175),
        search=(580, 130, 640, 210),
        color=(79, 73, 101),
        button=(598, 149, 617, 175),
    ),
)
FAST_BUTTONS.setdefault('LockedNextDifficulty', []).append(DIFFICULTY_LOCKED_NEXT)

CHARACTER_PANEL = ButtonWrapper(
    name='CW_CHARACTER_PANEL',
    cn=Button(
        file='./assets/cn/currency_wars/ui/char_popup.png',
        area=(1133, 642, 1179, 670),
        search=(1100, 615, 1245, 695),
        color=(70, 50, 57),
        button=(1133, 642, 1179, 670),
    ),
)
FAST_BUTTONS.setdefault('出售', []).append(CHARACTER_PANEL)
FAST_BUTTONS.setdefault('详情', []).append(CHARACTER_PANEL)

BATTLE = ButtonWrapper(
    name='CW_BATTLE',
    cn=Button(
        file='./assets/cn/currency_wars/ui/board3.png',
        area=(1165, 462, 1227, 501),
        search=(1100, 440, 1275, 525),
        color=(100, 60, 62),
        button=(1165, 462, 1227, 501),
    ),
)
FAST_BUTTONS.setdefault('出战', []).append(BATTLE)

CONTINUE = ButtonWrapper(
    name='CW_CONTINUE',
    cn=Button(
        file='./assets/cn/currency_wars/ui/first_battle_current.png',
        area=(596, 642, 686, 673),
        search=(470, 610, 815, 695),
        color=(196, 192, 184),
        button=(596, 642, 686, 673),
    ),
)
FAST_BUTTONS.setdefault('继续挑战', []).append(CONTINUE)
FAST_BUTTONS.setdefault('继续', []).append(CONTINUE)

GO_SETTLE = ButtonWrapper(
    name='CW_GO_SETTLE',
    cn=Button(
        file='./assets/cn/currency_wars/ui/third_finish_screen.png',
        area=(596, 642, 686, 673),
        search=(470, 610, 815, 695),
        color=(183, 180, 180),
        button=(596, 642, 686, 673),
    ),
)
FAST_BUTTONS.setdefault('前往结算', []).append(GO_SETTLE)

START = ButtonWrapper(
    name='CW_START',
    cn=Button(
        file='./assets/cn/currency_wars/ui/currency_lobby2.png',
        area=(899, 632, 1103, 666),
        search=(765, 607, 1249, 689),
        color=(177, 179, 194),
        button=(899, 632, 1103, 666),
    ),
)
FAST_BUTTONS.setdefault('开始货币战争', []).append(START)

INVEST_STRATEGY = ButtonWrapper(
    name='CW_INVEST_STRATEGY',
    cn=Button(
        file='./assets/cn/currency_wars/ui/20261005-012357_board_expected.png',
        area=(552, 48, 727, 82),
        search=(460, 30, 830, 100),
        color=(128, 125, 226),
        button=(552, 48, 727, 82),
    ),
)
FAST_BUTTONS.setdefault('选择投资策略', []).append(INVEST_STRATEGY)

ENCOUNTER = ButtonWrapper(
    name='CW_ENCOUNTER',
    cn=Button(
        file='./assets/cn/currency_wars/ui/20261005-005925_board_expected.png',
        area=(587, 45, 695, 81),
        search=(470, 25, 820, 100),
        color=(92, 88, 170),
        button=(587, 45, 695, 81),
    ),
)
FAST_BUTTONS.setdefault('遭遇节点', []).append(ENCOUNTER)

FESTIVITIES = ButtonWrapper(
    name='CW_FESTIVITIES',
    cn=Button(
        file='./assets/cn/currency_wars/ui/festivities.png',
        area=(665, 35, 759, 61),
        search=(490, 15, 850, 86),
        color=(94, 82, 62),
        button=(665, 35, 759, 61),
    ),
)
FAST_BUTTONS.setdefault('盛会之星', []).append(FESTIVITIES)

WEAPON_BOX = ButtonWrapper(
    name='CW_WEAPON_BOX',
    cn=Button(
        file='./assets/cn/currency_wars/ui/occupied_item.png',
        area=(704, 22, 809, 46),
        search=(540, 0, 960, 75),
        color=(92, 92, 92),
        button=(704, 22, 809, 46),
    ),
)
FAST_BUTTONS.setdefault('简易武装箱', []).append(WEAPON_BOX)
FAST_BUTTONS.setdefault('武装箱', []).append(WEAPON_BOX)

STRATEGY_DETAIL = ButtonWrapper(
    name='CW_STRATEGY_DETAIL',
    cn=Button(
        file='./assets/cn/currency_wars/ui/native_detail_loaded.png',
        area=(84, 35, 173, 64),
        search=(65, 22, 210, 82),
        color=(116, 115, 221),
        button=(84, 35, 173, 64),
    ),
)
FAST_BUTTONS.setdefault('攻略详情', []).append(STRATEGY_DETAIL)

SUPPLY = ButtonWrapper(
    name='CW_SUPPLY',
    cn=Button(
        file='./assets/cn/currency_wars/ui/supply_current.png',
        area=(596, 96, 686, 126),
        search=(430, 75, 850, 145),
        color=(190, 152, 99),
        button=(596, 96, 686, 126),
    ),
)
FAST_BUTTONS.setdefault('补给阶段', []).append(SUPPLY)

CONFIRM_SUPPLY = ButtonWrapper(
    name='CW_CONFIRM_SUPPLY',
    cn=Button(
        file='./assets/cn/currency_wars/ui/supply_current.png',
        area=(1083, 645, 1134, 674),
        search=(900, 610, 1255, 700),
        color=(204, 204, 204),
        button=(1083, 645, 1134, 674),
    ),
)
FAST_BUTTONS.setdefault('确认', []).append(CONFIRM_SUPPLY)

UPGRADE = ButtonWrapper(
    name='CW_UPGRADE',
    cn=Button(
        file='./assets/cn/currency_wars/ui/board3.png',
        area=(44, 541, 135, 575),
        search=(0, 520, 150, 585),
        color=(55, 72, 157),
        button=(44, 541, 135, 575),
    ),
)
FAST_BUTTONS.setdefault('购买经验', []).append(UPGRADE)

REFRESH = ButtonWrapper(
    name='CW_REFRESH',
    cn=Button(
        file='./assets/cn/currency_wars/ui/shop_actual.png',
        area=(1166, 375, 1215, 406),
        search=(1110, 350, 1260, 445),
        color=(199, 201, 211),
        button=(1166, 375, 1215, 406),
    ),
)
FAST_BUTTONS.setdefault('刷新', []).append(REFRESH)

EQUIP_RECOMMEND = ButtonWrapper(
    name='CW_EQUIP_RECOMMEND',
    cn=Button(
        file='./assets/cn/currency_wars/ui/char_popup.png',
        area=(899, 560, 982, 589),
        search=(840, 530, 1010, 610),
        color=(70, 70, 70),
        button=(899, 560, 982, 589),
    ),
)
FAST_BUTTONS.setdefault('装备推荐', []).append(EQUIP_RECOMMEND)

CONFIRM_EVENT = ButtonWrapper(
    name='CW_CONFIRM_EVENT',
    cn=Button(
        file='./assets/cn/currency_wars/ui/festivities.png',
        area=(1040, 438, 1125, 468),
        search=(80, 275, 1260, 695),
        color=(146, 104, 112),
        button=(1040, 438, 1125, 468),
    ),
)
FAST_BUTTONS.setdefault('确认选择', []).append(CONFIRM_EVENT)

SELECT = ButtonWrapper(
    name='CW_SELECT',
    cn=Button(
        file='./assets/cn/currency_wars/ui/20261005-005925_board_expected.png',
        area=(618, 647, 665, 675),
        search=(350, 595, 965, 700),
        color=(196, 196, 196),
        button=(618, 647, 665, 675),
    ),
)
FAST_BUTTONS.setdefault('选择', []).append(SELECT)

CONFIRM_INVEST = ButtonWrapper(
    name='CW_CONFIRM_INVEST',
    cn=Button(
        file='./assets/cn/currency_wars/ui/20261005-012357_board_expected.png',
        area=(632, 644, 675, 672),
        search=(300, 460, 1260, 700),
        color=(61, 61, 69),
        button=(632, 644, 675, 672),
    ),
)
FAST_BUTTONS.setdefault('确认', []).append(CONFIRM_INVEST)

CONFIRM_DIALOG = ButtonWrapper(
    name='CW_CONFIRM_DIALOG',
    cn=Button(
        file='./assets/cn/currency_wars/ui/code_input.png',
        area=(810, 516, 857, 547),
        search=(300, 360, 1260, 700),
        color=(187, 187, 187),
        button=(810, 516, 857, 547),
    ),
)
FAST_BUTTONS.setdefault('确认', []).append(CONFIRM_DIALOG)
