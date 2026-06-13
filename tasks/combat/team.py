import re

import cv2
import numpy as np

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from tasks.base.ui import UI
from tasks.combat.assets.assets_combat_team import *


def button_to_index(button: ButtonWrapper) -> int:
    res = re.search(r'(\d+)', button.name)
    if res:
        return int(res.group(1))
    else:
        logger.warning(f'Cannot convert team button to index: {button}')
        return 0


class CombatTeam(UI):
    def _match_team_gold(self, button, similarity=0.92):
        """
        Match team tab using gold channel (R-B) instead of luma.
        Luma fails when character portraits alter background brightness;
        gold channel is immune because gold text has R>>B while backgrounds have R≈B.
        """
        image = self.device.image
        for assets in button.buttons:
            search_image = crop(image, assets.search, copy=False)
            r, _, b = cv2.split(search_image)
            search_gold = cv2.subtract(r, b)
            r, _, b = cv2.split(assets.image)
            template_gold = cv2.subtract(r, b)
            res = cv2.matchTemplate(template_gold, search_gold, cv2.TM_CCOEFF_NORMED)
            _, sim, _, point = cv2.minMaxLoc(res)
            assets._button_offset = np.array(point) + assets.search[:2] - assets.area[:2]
            if sim > similarity:
                button._matched_button = assets
                return True
        return False

    def _get_team(self) -> int:
        """
        Returns:
            int: Current team index, or 0 if current team is not insight
        """
        team = 0
        for button in [
            TEAM_1_CHECK, TEAM_2_CHECK, TEAM_3_CHECK, TEAM_4_CHECK, TEAM_5_CHECK,
            TEAM_6_CHECK, TEAM_7_CHECK, TEAM_8_CHECK, TEAM_9_CHECK, TEAM_10_CHECK,
            TEAM_11_CHECK, TEAM_12_CHECK,
        ]:
            button.load_search(TEAM_SEARCH.area)
            if self._match_team_gold(button):
                if self.image_color_count(button.button, color=(255, 234, 191), threshold=180, count=50):
                    team = button_to_index(button)
                    break

        return team

    def team_set(self, index: int = 1) -> bool:
        """
        Args:
            index: Team index, 1 to 12.

        Returns:
            bool: If clicked

        Pages:
            in: page_team
        """
        logger.info(f'Team set: {index}')
        # Wait teams show up
        timeout = Timer(1, count=5).start()
        for _ in self.loop():
            # End
            if timeout.reached():
                logger.warning('Wait current team timeout')
                break
            current = self._get_team()
            if current:
                if current == index:
                    logger.attr('Team', current)
                    logger.info(f'Already selected to the correct team')
                    return False
                else:
                    break

        # Set team
        retry = Timer(2, count=10)
        skip_first_screenshot = True
        clicked = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            current = self._get_team()
            logger.attr('Team', current)
            if current == index:
                logger.info(f'Selected to the correct team')
                return clicked
            # Click
            if retry.reached():
                diff = index - current
                right = diff % 12
                left = -diff % 12
                if right <= left:
                    self.device.multi_click(TEAM_NEXT, right, interval=(0.2, 0.3))
                    clicked = True
                else:
                    self.device.multi_click(TEAM_PREV, left, interval=(0.2, 0.3))
                    clicked = True
                retry.reset()
                continue

        return clicked

    def handle_combat_team_prepare(self, team: int = 1) -> bool:
        """
        Set team and click prepare before dungeon combat.

        Args:
            team: Team index, 1 to 12.

        Returns:
            int: If clicked
        """
        if self.appear(COMBAT_TEAM_PREPARE, interval=5):
            self.team_set(team)
            self.device.click(COMBAT_TEAM_PREPARE)
            return True

        return False
