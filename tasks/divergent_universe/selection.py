"""Choice detection and collection priority for Android DU screens.

Strategy adapted from StarRailAssistant (AGPL-3.0); uses SRC's unrecorded
marker alongside the current DU marker instead of assuming every card is new.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from tasks.currency_wars.operator import Box, normalize

TEMPLATES = Path(__file__).parent / 'templates'


@dataclass
class Choice:
    box: Box
    title: str = ''
    uncollected: bool = False
    recommended: bool = False
    rarity: int = 0


def card_boxes(image):
    frame = cv2.cvtColor(image[125:620, 100:1210], cv2.COLOR_RGB2GRAY)
    edges = cv2.morphologyEx(cv2.Canny(frame, 35, 110), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 120 <= w <= 400 and 190 <= h <= 490 and cv2.contourArea(contour) > w * h * 0.55:
            result.append(Box(x + 100, y + 125, w, h, 'DU_CARD'))
    distinct = []
    for box in sorted(result, key=lambda b: b.width * b.height, reverse=True):
        if all(abs(box.center[0] - old.center[0]) > min(box.width, old.width) * 0.6
               or abs(box.center[1] - old.center[1]) > min(box.height, old.height) * 0.6 for old in distinct):
            distinct.append(box)
    return sorted(distinct, key=lambda b: b.left) if 1 <= len(distinct) <= 5 else []


@lru_cache(maxsize=2)
def star_templates(miracle=False):
    names = ('choice_diamond.png',) if miracle else ('choice_star.png', 'choice_star_gold.png')
    return tuple(cv2.imread(str(TEMPLATES / name), cv2.IMREAD_GRAYSCALE) for name in names)


def choice_rarity(image, card, kind):
    # Count the gold stars/diamonds below the icon/title, without reading the
    # description. Erosion separates touching points and removes their glow.
    y1, y2 = (309, 341) if kind == 'miracle' else (339, 385)
    x = card.center[0]
    hsv = cv2.cvtColor(image[y1:y2, max(0, x - 65):x + 65], cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array((15, 70, 165)), np.array((40, 255, 255)))
    mask = cv2.erode(mask, np.ones((2, 2), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    stars = []
    for contour in contours:
        left, top, width, height = cv2.boundingRect(contour)
        if 4 <= width <= 18 and 5 <= height <= 14 and cv2.contourArea(contour) >= 18:
            stars.append((left + width / 2, top + height / 2))
    count = max((sum(abs(y - other_y) <= 4 for _, other_y in stars) for _, y in stars), default=0)
    gray = cv2.cvtColor(image[y1:y2, max(0, x - 65):x + 65], cv2.COLOR_RGB2GRAY)
    matches = []
    for sample in star_templates(kind == 'miracle'):
        values = cv2.matchTemplate(gray, sample, cv2.TM_CCOEFF_NORMED)
        for _ in range(5):
            _, score, _, (px, py) = cv2.minMaxLoc(values)
            if score < 0.80:
                break
            if all(abs(px - old_x) > 8 or abs(py - old_y) > 8 for old_x, old_y in matches):
                matches.append((px, py))
            values[max(0, py - 8):py + 9, max(0, px - 8):px + 9] = 0
    count = max(count, max((sum(abs(y - other_y) <= 4 for _, other_y in matches)
                           for _, y in matches), default=0))
    return count if 1 <= count <= 5 else 0


def read_choices(op, kind):
    cards = card_boxes(op.image)
    # Only names are needed for tie-breaking; full descriptions are expensive
    # and contain unrelated keywords such as "exploration interrupted".
    title_region = (0.08, 0.49, 0.96, 0.55) if kind == 'miracle' else (0.08, 0.42, 0.96, 0.50)
    labels = op.read_region(title_region, snapshot=False)
    markers = [b for b in labels if normalize(b.source).lower() in ('未收集', '未收录', '未获得', '首次获得', 'new')]
    markers += op.template_matches(str(TEMPLATES / 'collection.png'), (0.06, 0.12, 0.98, 0.82), confidence=0.87)
    markers += op.template_matches(str(TEMPLATES / 'collection_android.png'), (0.06, 0.12, 0.98, 0.82), confidence=0.87)
    from tasks.rogue.assets.assets_rogue_ui import FLAG_UNRECORD
    sample = FLAG_UNRECORD.buttons[0].image_luma
    gray = cv2.cvtColor(op.image[85:580, 80:1250], cv2.COLOR_RGB2GRAY)
    matches = cv2.matchTemplate(gray, sample, cv2.TM_CCOEFF_NORMED)
    for _ in range(5):
        _, score, _, (x, y) = cv2.minMaxLoc(matches)
        if score < 0.88:
            break
        markers.append(Box(x + 80, y + 85, sample.shape[1], sample.shape[0], 'DU_UNRECORDED', score))
        matches[max(0, y - 25):y + 26, max(0, x - 25):x + 26] = 0
    recommended = [b for b in labels if '推荐' in b.source]
    recommended += op.template_matches(str(TEMPLATES / 'recommended_blessing.png'), (0.06, 0.12, 0.98, 0.82), confidence=0.87)
    if not cards and markers:
        # A marker is an observed card anchor even if animations obscure its
        # border. Click inside the card below the marker, not a guessed column.
        cards = [Box(max(80, b.left - 65), min(430, b.top + 20), 130, 140, 'DU_MARKED_CARD') for b in markers]
    if not cards:
        # Current SRA fallback, used only on a confirmed selection screen.
        cards = [Box(370, 210, 210, 300, 'DU_DEFAULT_CARD')]
    choices = []
    for card in cards:
        inside = [b.source for b in labels if card.left <= b.center[0] <= card.left + card.width
                  and card.top <= b.center[1] <= card.top + card.height]
        near = lambda b: (card.left - 25 <= b.center[0] <= card.left + card.width + 25
                          and card.top - 90 <= b.center[1] <= card.top + card.height)
        choices.append(Choice(card, ' '.join(inside)[:180], any(near(b) for b in markers),
                              any(near(b) for b in recommended), choice_rarity(op.image, card, kind)))
    return choices


def choose(choices, prefer_uncollected=True, priorities=(), discard=False):
    def score(choice):
        priority = next((len(priorities) - i for i, p in enumerate(priorities) if p in choice.title), 0)
        value = (bool(prefer_uncollected and choice.uncollected), choice.recommended, choice.rarity, priority)
        return tuple(-int(v) for v in value) if discard else value
    return max(choices, key=score)
