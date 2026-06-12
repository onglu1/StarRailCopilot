from module.config.utils import get_server_next_monday_update
from module.logger import logger
from tasks.memory_of_chaos.assets.assets_memory_of_chaos_battle import MOC_SETTLE_BACK
from tasks.memory_of_chaos.prep import MemoryOfChaosPrep
from tasks.pure_fiction.abyss import AbyssCombatLoop
from tasks.pure_fiction.assets.assets_pure_fiction_battle import PF_WAVE_FLAG
from tasks.pure_fiction.assets.assets_pure_fiction_map import MAP_CHECK


class MemoryOfChaos(MemoryOfChaosPrep, AbyssCombatLoop):
    SETTLE_BUTTON = MOC_SETTLE_BACK

    def abyss_home_check(self) -> bool:
        return self.moc_in_stage_screen()

    def run(self):
        logger.hr('Memory of Chaos', level=1)
        team1 = int(self.config.MemoryOfChaos_Team1Preset)
        team2 = int(self.config.MemoryOfChaos_Team2Preset)
        mode = self.config.MemoryOfChaos_ChallengeMode
        logger.attr('Team presets', f'{team1}, {team2}')
        logger.attr('ChallengeMode', mode)

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(self.SETTLE_BUTTON) or self.appear(PF_WAVE_FLAG) or self.appear(MAP_CHECK):
            logger.info('Resuming inside a memory of chaos dungeon')
            self.abyss_dungeon_loop()

        cleared = 0
        skipped = set()
        # At most all 12 stages plus margin
        for _ in range(14):
            self.moc_goto()
            nodes = self.moc_scan_stages()
            target = self.moc_get_target_stage(nodes, mode=mode, skipped=skipped)
            if target is None:
                logger.info('Memory of chaos finished, nothing to challenge')
                break
            logger.hr(f'Challenge {target}', level=1)
            if not self.moc_prep_stage(target, team1_preset=team1, team2_preset=team2):
                # Probably locked, never retry it this run
                skipped.add(target.index)
                continue
            self.abyss_dungeon_loop()
            cleared += 1

            # Check progress to avoid retrying the same stage forever
            nodes = self.moc_scan_stages()
            after = [n for n in nodes if n.index == target.index]
            if after and after[0].status == 'open':
                logger.warning(f'{target} still has no stars after challenge, '
                               f'teams may be too weak, stop')
                break

        logger.attr('Stages challenged', cleared)
        monday = get_server_next_monday_update(self.config.Scheduler_ServerUpdate)
        self.config.task_delay(target=monday)
        self.ui_goto_main()
