"""Small visual checks validate locally remembered character states."""
import cv2
import numpy as np


class RosterCache:
    def __init__(self):
        self.entries = {}
        self.hits = 0
        self.reads = 0

    @staticmethod
    def token(character):
        return (character.name, int(character.stars)) if character is not None else None

    @staticmethod
    def signature(image, point):
        x, y = round(point[0] * 1280), round(point[1] * 720)
        crop = image[y - 24:y + 43, x - 24:x + 24]
        portrait = cv2.resize(crop, (12, 18), interpolation=cv2.INTER_AREA)
        # Star changes can affect too few pixels to change the mean portrait.
        band = image[y + 18:y + 43, x - 24:x + 24]
        hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV)
        stars = cv2.inRange(hsv, np.array((8, 80, 160)), np.array((42, 255, 255)))
        return portrait, cv2.resize(stars, (24, 13), interpolation=cv2.INTER_NEAREST)

    def matches(self, key, image, point, character):
        entry = self.entries.get(key)
        if entry is None or entry['token'] != self.token(character):
            return False
        if abs(entry['point'][0] - point[0]) * 1280 > 2 or abs(entry['point'][1] - point[1]) * 720 > 2:
            return False
        portrait, stars = self.signature(image, entry['point'])
        difference = np.abs(portrait.astype(np.int16) - entry['portrait'].astype(np.int16))
        if difference.mean() > 2.5 or np.mean(difference > 20) > 0.015 or np.mean(stars != entry['stars']) > 0.035:
            return False
        self.hits += 1
        return True

    def remember(self, key, image, point, character):
        portrait, stars = self.signature(image, point)
        self.entries[key] = dict(point=tuple(point), token=self.token(character), portrait=portrait, stars=stars)

    def invalidate(self, *keys):
        for key in keys:
            self.entries.pop(key, None)

    def invalidate_name(self, name):
        for key, entry in list(self.entries.items()):
            if entry['token'] and entry['token'][0] == name:
                self.entries.pop(key)

    def clear(self):
        self.entries.clear()

    def dump(self):
        return {key: dict(point=list(e['point']), token=list(e['token']) if e['token'] else None,
                          portrait=e['portrait'].tolist(), stars=e['stars'].tolist()) for key, e in self.entries.items()}

    def load(self, entries):
        self.entries = {key: dict(point=tuple(e['point']), token=tuple(e['token']) if e['token'] else None,
                                 portrait=np.asarray(e['portrait'], dtype=np.uint8), stars=np.asarray(e['stars'], dtype=np.uint8))
                        for key, e in entries.items()}
