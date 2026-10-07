from module.base.button import ClickButton
from tasks.memory_of_chaos.assets.assets_memory_of_chaos_battle import MOC_SETTLE_BACK
from tasks.memory_of_chaos.prep import MemoryOfChaosPrep


class MemoryOfChaos(MemoryOfChaosPrep):
    SETTLE_BUTTON = MOC_SETTLE_BACK
    # Gift box at the bottom right of the crystal list
    REWARD_ENTRY = ClickButton((1165, 610, 1245, 685), name='MOC_REWARD_ENTRY')
    REWARD_TABS = [ClickButton((395, 115, 490, 153), name='MOC_REWARD_TAB2')]
    REWARD_PANEL_CLOSE = ClickButton((1073, 112, 1113, 153), name='REWARD_PANEL_CLOSE')

    def run(self):
        self.abyss_run('MemoryOfChaos')
