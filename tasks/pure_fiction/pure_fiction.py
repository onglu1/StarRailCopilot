from module.base.button import ClickButton
from tasks.pure_fiction.assets.assets_pure_fiction_battle import SETTLE_BACK
from tasks.pure_fiction.prep import PureFictionPrep


class PureFiction(PureFictionPrep):
    SETTLE_BUTTON = SETTLE_BACK
    # Chest icon at the bottom right of the stage map, next to the star count
    REWARD_ENTRY = ClickButton((1228, 640, 1268, 680), name='PF_REWARD_ENTRY')
    # Second tab: per-stage score rewards
    REWARD_TABS = [ClickButton((395, 115, 490, 153), name='PF_REWARD_TAB2')]
    REWARD_PANEL_CLOSE = ClickButton((1073, 112, 1113, 153), name='REWARD_PANEL_CLOSE')

    def run(self):
        self.abyss_run('PureFiction')
