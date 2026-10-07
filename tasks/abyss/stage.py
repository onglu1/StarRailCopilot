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


def _abyss_stage_done(node) -> bool:
    """Full-starred, or cleared with unreadable stars (nothing to gain)."""
    return node.full_starred or (node.status == 'cleared' and node.stars is None)


def abyss_select_target(nodes, mode='highest', attempts=None, max_retry=2, assigned=1):
    """
    Args:
        nodes: list of AbyssStageNode
        mode:
            'highest': the highest unlocked stage if not full-starred (default)
            'push': the first (lowest) stage that is not full-starred,
                hammer it until full or rounds exhausted
            'assign': the manually assigned stage only
        attempts: {stage_index: attempts_this_run}
        max_retry: max rounds per stage per run, retries swap team order
        assigned: stage index for the 'assign' mode

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

    if mode == 'push':
        nonfull = [n for n in enterable if not n.full_starred]
        if not nonfull:
            return None
        first = min(nonfull, key=lambda n: n.index)
        if tried(first) >= max_retry:
            return None
        return first
    if mode == 'assign':
        match = [n for n in enterable if n.index == int(assigned)]
        if not match:
            logger.warning(f'Assigned stage {assigned} not found or locked')
            return None
        node = match[0]
        if _abyss_stage_done(node) or tried(node) >= max_retry:
            return None
        return node
    # 'highest' (default)
    top = max(enterable, key=lambda n: n.index)
    if _abyss_stage_done(top) or tried(top) >= max_retry:
        return None
    return top


def abyss_has_exhausted(nodes, mode='highest', attempts=None, max_retry=2, assigned=1) -> bool:
    """
    Whether the mode-relevant stage still needs work but ran out of rounds.
    Used to decide between deferring the task and finishing the week.
    """
    attempts = attempts or {}

    def tried(n):
        return attempts.get(n.index, 0)

    enterable = [n for n in nodes if n.enterable]
    if not enterable:
        return False
    if mode == 'push':
        relevant = [n for n in enterable if not n.full_starred and n.stars is not None]
    elif mode == 'assign':
        relevant = [n for n in enterable if n.index == int(assigned) and not _abyss_stage_done(n)]
    else:
        top = max(enterable, key=lambda n: n.index)
        relevant = [] if _abyss_stage_done(top) else [top]
    return any(tried(n) >= max_retry for n in relevant)
