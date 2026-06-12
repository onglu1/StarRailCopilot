from module.base.button import ClickButton
from module.config.utils import get_server_next_monday_update
from module.logger import logger
from tasks.pure_fiction.abyss import AbyssCombatLoop
from tasks.pure_fiction.assets.assets_pure_fiction_battle import PF_WAVE_FLAG, SETTLE_BACK
from tasks.pure_fiction.assets.assets_pure_fiction_map import MAP_CHECK
from tasks.pure_fiction.prep import PureFictionPrep


class PureFiction(PureFictionPrep, AbyssCombatLoop):
    SETTLE_BUTTON = SETTLE_BACK
    # Chest icon at the bottom right of the stage map, next to the star count
    REWARD_ENTRY = ClickButton((1228, 640, 1268, 680), name='PF_REWARD_ENTRY')
    # Second tab: per-stage score rewards
    REWARD_TABS = [ClickButton((395, 115, 490, 153), name='PF_REWARD_TAB2')]
    REWARD_PANEL_CLOSE = ClickButton((1073, 112, 1113, 153), name='REWARD_PANEL_CLOSE')

    def abyss_home_check(self) -> bool:
        return self.pf_in_stage_map()

    def abyss_goto(self):
        self.pf_goto()

    def abyss_scan_stages(self) -> list:
        return self.pf_scan_stages()

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        return self.pf_prep_stage(node, team1_preset=team1_preset, team2_preset=team2_preset)

    def run(self):
        logger.hr('Pure Fiction', level=1)
        team1 = int(self.config.PureFiction_Team1Preset)
        team2 = int(self.config.PureFiction_Team2Preset)
        mode = self.config.PureFiction_ChallengeMode
        max_retry = int(self.config.PureFiction_MaxRetry)
        on_exhausted = self.config.PureFiction_RetryExceeded
        logger.attr('ChallengeMode', mode)

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(self.SETTLE_BUTTON) or self.appear(PF_WAVE_FLAG) or self.appear(MAP_CHECK):
            logger.info('Resuming inside a pure fiction dungeon')
            self.abyss_dungeon_loop()

        fought, exhausted = self.abyss_run_challenges(
            mode=mode, team1_preset=team1, team2_preset=team2, max_retry=max_retry)
        logger.attr('Battles fought', fought)

        self.abyss_claim_rewards()

        if exhausted and on_exhausted == 'defer':
            logger.info('Some stage ran out of retries, try again after the daily reset')
            self.config.task_delay(server_update=True)
        else:
            self.config.task_delay(target=get_server_next_monday_update(
                self.config.Scheduler_ServerUpdate))
        self.ui_goto_main()
