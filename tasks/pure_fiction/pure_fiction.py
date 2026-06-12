from module.config.utils import get_server_next_monday_update
from module.logger import logger
from tasks.pure_fiction.abyss import AbyssCombatLoop
from tasks.pure_fiction.assets.assets_pure_fiction_battle import SETTLE_BACK
from tasks.pure_fiction.prep import PureFictionPrep


class PureFiction(PureFictionPrep, AbyssCombatLoop):
    SETTLE_BUTTON = SETTLE_BACK

    def abyss_home_check(self) -> bool:
        return self.pf_in_stage_map()

    def run(self):
        logger.hr('Pure Fiction', level=1)
        team1 = int(self.config.PureFiction_Team1Preset)
        team2 = int(self.config.PureFiction_Team2Preset)
        mode = self.config.PureFiction_ChallengeMode
        logger.attr('Team presets', f'{team1}, {team2}')
        logger.attr('ChallengeMode', mode)

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(self.SETTLE_BUTTON) or self.pf_resume_check():
            logger.info('Resuming inside a pure fiction dungeon')
            self.abyss_dungeon_loop()

        cleared = 0
        # At most all stages of a season plus margin
        for _ in range(8):
            self.pf_goto()
            nodes = self.pf_scan_stages()
            target = self.pf_get_target_stage(nodes, mode=mode)
            if target is None:
                logger.info('Pure fiction finished, nothing to challenge')
                break
            logger.hr(f'Challenge {target}', level=1)
            self.pf_prep_stage(target, team1_preset=team1, team2_preset=team2)
            self.abyss_dungeon_loop()
            cleared += 1

            # Check progress to avoid retrying the same stage forever
            nodes = self.pf_scan_stages()
            after = [n for n in nodes if n.index == target.index]
            if after and after[0].status == 'open':
                logger.warning(f'{target} still not cleared after challenge, '
                               f'teams may be too weak, stop')
                break

        logger.attr('Stages challenged', cleared)
        # Pure fiction seasons rotate bi-weekly, run weekly is safe and simple
        monday = get_server_next_monday_update(self.config.Scheduler_ServerUpdate)
        self.config.task_delay(target=monday)
        self.ui_goto_main()

    def pf_resume_check(self) -> bool:
        from tasks.pure_fiction.assets.assets_pure_fiction_battle import PF_WAVE_FLAG
        from tasks.pure_fiction.assets.assets_pure_fiction_map import MAP_CHECK
        return self.appear(PF_WAVE_FLAG) or self.appear(MAP_CHECK)
