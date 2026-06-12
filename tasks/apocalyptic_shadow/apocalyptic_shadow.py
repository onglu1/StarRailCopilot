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
        logger.attr('Team presets', f'{team1}, {team2}')
        logger.attr('ChallengeMode', mode)

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(self.SETTLE_BUTTON) or self.appear(PF_WAVE_FLAG) or self.appear(MAP_CHECK):
            logger.info('Resuming inside an apocalyptic shadow dungeon')
            self.abyss_dungeon_loop()

        cleared = 0
        skipped = set()
        # At most all stages of a season plus margin
        for _ in range(8):
            self.as_goto()
            nodes = self.as_scan_stages()
            target = self.as_get_target_stage(nodes, mode=mode, skipped=skipped)
            if target is None:
                logger.info('Apocalyptic shadow finished, nothing to challenge')
                break
            logger.hr(f'Challenge {target}', level=1)
            if not self.as_prep_stage(target, team1_preset=team1, team2_preset=team2):
                # Probably a star-origin (3-node) stage, unsupported yet
                skipped.add(target.index)
                continue
            self.abyss_dungeon_loop()
            cleared += 1

            # Check progress to avoid retrying the same stage forever
            nodes = self.as_scan_stages()
            after = [n for n in nodes if n.index == target.index]
            if after and after[0].status == 'open':
                logger.warning(f'{target} still not cleared after challenge, '
                               f'teams may be too weak, stop')
                break

        logger.attr('Stages challenged', cleared)
        monday = get_server_next_monday_update(self.config.Scheduler_ServerUpdate)
        self.config.task_delay(target=monday)
        self.ui_goto_main()
