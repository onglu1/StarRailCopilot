from module.config.utils import get_server_next_monday_update
from module.logger import logger
from tasks.apocalyptic_shadow.assets.assets_apocalyptic_shadow_battle import (
    AS_GOTO_NODE2,
    AS_SETTLE_BACK,
    AS_SETTLE_EXIT
)
from tasks.apocalyptic_shadow.prep import ApocalypticShadowPrep
from tasks.pure_fiction.abyss import AbyssCombatLoop
from tasks.pure_fiction.assets.assets_pure_fiction_battle import PF_WAVE_FLAG
from tasks.pure_fiction.assets.assets_pure_fiction_map import MAP_CHECK


class ApocalypticShadow(ApocalypticShadowPrep, AbyssCombatLoop):
    SETTLE_BUTTON = AS_SETTLE_BACK

    def abyss_home_check(self) -> bool:
        return self.as_in_stage_screen()

    def abyss_goto(self):
        self.as_goto()

    def abyss_scan_stages(self) -> list:
        return self.as_scan_stages()

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        return self.as_prep_stage(node, team1_preset=team1_preset, team2_preset=team2_preset)

    def abyss_mid_settle_handler(self) -> bool:
        """
        Apocalyptic shadow shows a mid-run settlement after node 1 with
        exit / retry / go-to-node-2 buttons, continue to node 2.
        If node 1 failed there is no go-to-node-2, exit instead.
        """
        if self.match_template_color(AS_GOTO_NODE2, interval=3):
            logger.info(f'{AS_GOTO_NODE2} -> click')
            self.device.click(AS_GOTO_NODE2)
            return True
        if self.appear(AS_SETTLE_EXIT, interval=3) and not self.match_template_luma(AS_GOTO_NODE2):
            logger.info(f'{AS_SETTLE_EXIT} -> click, node 1 may have failed')
            self.device.click(AS_SETTLE_EXIT)
            return True
        return False

    def run(self):
        logger.hr('Apocalyptic Shadow', level=1)
        team1 = int(self.config.ApocalypticShadow_Team1Preset)
        team2 = int(self.config.ApocalypticShadow_Team2Preset)
        mode = self.config.ApocalypticShadow_ChallengeMode
        max_retry = int(self.config.ApocalypticShadow_MaxRetry)
        on_exhausted = self.config.ApocalypticShadow_RetryExceeded
        logger.attr('ChallengeMode', mode)

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(self.SETTLE_BUTTON) or self.appear(PF_WAVE_FLAG) or self.appear(MAP_CHECK):
            logger.info('Resuming inside an apocalyptic shadow dungeon')
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
