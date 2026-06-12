"""
Stage models and target selection shared by the three abyss-like weekly
modes: Pure Fiction / Memory of Chaos / Apocalyptic Shadow.
"""
import cv2
import numpy as np

from module.base.utils import crop
from module.logger import logger


class AbyssStageNode:
    """
    A stage entry on an abyss stage-select screen.

    status: 'open' / 'cleared' / 'locked' / 'unknown'
    stars: 0-3 counted from gold star glyphs, None when unreadable
        (e.g. the selected tab in apocalyptic shadow renders enlarged)
    """

    def __init__(self, index, button):
        self.index: int = index
        self.button = button
        self.status: str = 'unknown'
        self.stars = None

    @property
    def enterable(self) -> bool:
        return self.status != 'locked'

    @property
    def full_starred(self) -> bool:
        return self.stars is not None and self.stars >= 3

    @property
    def stars_known_zero(self) -> bool:
        if self.stars is not None:
            return self.stars == 0
        # Stars unreadable: only un-attempted stages count as zero
        return self.status in ['open', 'unknown']

    def __repr__(self):
        stars = '?' if self.stars is None else self.stars
        return f'Stage_{self.index:02d}({self.status}, {stars}*)'


def abyss_count_stars(image, area) -> int:
    """
    Count gold star glyphs inside the area via connected components.
    Gold measures ~(241, 189, 110), one star is a 45-155 px cluster
    depending on the mode, empty star outlines and backgrounds measure 0.
    Star glint animation can hide a cluster in a single frame, callers
    should keep the max count across scan passes.
    """
    img = crop(image, area, copy=False)
    height, width = img.shape[:2]
    px = img.reshape(-1, 3).astype(int)
    mask = (np.abs(px[:, 0] - 241) < 30) & (np.abs(px[:, 1] - 189) < 30) & (np.abs(px[:, 2] - 110) < 40)
    mask = mask.reshape(height, width).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    count = 0
    for i in range(1, n):
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        # Stars are roughly square blobs, gold decoration lines are thin
        if stats[i, cv2.CC_STAT_AREA] >= 12 and h >= 5 and w <= h * 3:
            count += 1
    return min(count, 3)


def abyss_select_target(nodes, mode='first_clear', attempts=None, max_retry=2):
    """
    Args:
        nodes: list of AbyssStageNode
        mode:
            'first_clear': lowest stage with zero stars
            'push': the first (lowest) stage that is not full-starred,
                hammer it until full or retries exhausted
            'sweep': all stages that are not full-starred, lowest first,
                each up to max_retry attempts
            'highest_only': the highest unlocked stage if not full-starred
        attempts: {stage_index: attempts_this_run}
        max_retry: max attempts per stage per run

    Returns:
        AbyssStageNode: or None if nothing left to do
    """
    attempts = attempts or {}

    def tried(n):
        return attempts.get(n.index, 0)

    enterable = [n for n in nodes if n.enterable]
    if not enterable:
        logger.warning('No enterable stage found')
        return None

    if mode == 'highest_only':
        top = max(enterable, key=lambda n: n.index)
        if top.full_starred or (top.status == 'cleared' and top.stars is None):
            return None
        if tried(top) >= max_retry:
            return None
        return top
    if mode == 'push':
        nonfull = [n for n in enterable if not n.full_starred]
        if not nonfull:
            return None
        first = min(nonfull, key=lambda n: n.index)
        if tried(first) >= max_retry:
            return None
        return first
    if mode == 'sweep':
        candidates = [n for n in enterable if not n.full_starred and tried(n) < max_retry]
    else:
        # first_clear
        candidates = [n for n in enterable if n.stars_known_zero and tried(n) < max_retry]
    if not candidates:
        return None
    return min(candidates, key=lambda n: n.index)


def abyss_has_exhausted(nodes, mode='first_clear', attempts=None, max_retry=2) -> bool:
    """
    Whether some mode-relevant stage still needs work but ran out of retries.
    Used to decide between deferring the task and finishing the week.
    """
    attempts = attempts or {}

    def tried(n):
        return attempts.get(n.index, 0)

    enterable = [n for n in nodes if n.enterable]
    if mode == 'first_clear':
        relevant = [n for n in enterable if n.stars_known_zero]
    elif mode == 'highest_only':
        if not enterable:
            return False
        top = max(enterable, key=lambda n: n.index)
        relevant = [top] if not top.full_starred and top.stars is not None else []
    else:
        relevant = [n for n in enterable if not n.full_starred and n.stars is not None]
    return any(tried(n) >= max_retry for n in relevant)
