"""Choice detection and collection priority for Android DU screens.

Strategy adapted from StarRailAssistant (AGPL-3.0); uses SRC's unrecorded
marker alongside the current DU marker instead of assuming every card is new.
"""
from dataclasses import dataclass
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


def read_choices(op, kind):
    cards = card_boxes(op.image)
    labels = op.read_region((0.06, 0.16, 0.98, 0.84), snapshot=False)
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
                              any(near(b) for b in recommended)))
    return choices


def choose(choices, prefer_uncollected=True, priorities=(), discard=False):
    def score(choice):
        priority = next((len(priorities) - i for i, p in enumerate(priorities) if p in choice.title), 0)
        value = (bool(prefer_uncollected and choice.uncollected), priority, choice.recommended)
        return tuple(-int(v) for v in value) if discard else value
    return max(choices, key=score)
