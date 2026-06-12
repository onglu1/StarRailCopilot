"""
Candidate-team composer shared by the abyss modes.

The user lists candidate in-game presets (strongest first) in CandidateTeams.
On the stage prep screen the composer reads the recommended attributes
(= enemy weaknesses) of both nodes, recognizes the members of every candidate
preset from the preset panel, then picks the disjoint ordered pair with the
best weakness coverage, preferring earlier (stronger) presets. Retries on the
same stage walk down the ranking, so all candidate combinations get exhausted
before the stage's retry budget gives up (grind mode).

Recognition facts (calibrated on live 1280x720 frames):
- Preset rows show one 95x89 portrait card per member, same rendering as the
  character list page, so assets/character templates match at scale 1.10.
- The enabled preset overlays a team ribbon on the bottom ~20px of its cards,
  so only the top 60px face region is matched.
- Every occupied card has a colored element badge at its top-left corner.
  Badge hue (median of saturated pixels) separates the elements cleanly,
  which also covers characters whose template is missing (new releases).
- Empty card slots have no saturated badge pixels at all.
- Weakness icons on the prep screen are bare element glyphs; Apocalyptic
  Shadow renders them at ~0.65 scale of the Pure Fiction / Memory of Chaos
  size, so matching sweeps a small scale range.
"""
import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import crop, load_image
from module.logger import logger
from tasks.abyss.prep import PRESET_BLOCK, AbyssPrep

# Element badge hue centers (OpenCV hue 0-179), from live calibration
ELEMENT_HUE = {
    'Fire': 5,
    'Imaginary': 25,
    'Wind': 70,
    'Ice': 100,
    'Quantum': 120,
    'Lightning': 165,
}
# Characters that implant weaknesses or break toughness regardless of type,
# teams containing one match any node
IMPLANT_CHARACTERS = {'Firefly', 'SilverWolf', 'Boothill', 'Rappa'}

# Preset panel geometry at 1280x720
PANEL_AREA = (0, 130, 480, 700)
CARD_X = [35, 143, 251, 359]
CARD_W, CARD_H = 95, 89
FACE_H = 60  # top of the card, below sits the team ribbon of enabled presets
ROW_PITCH = 172

_face_templates = None
_weak_templates = None


def _load_face_templates() -> dict:
    """assets/character templates, normalized to the 95x60 face region."""
    global _face_templates
    if _face_templates is not None:
        return _face_templates
    out = {}
    folder = './assets/character'
    for file in sorted(os.listdir(folder)):
        if not file.endswith('.png'):
            continue
        name = file[:-4]
        image = load_image(os.path.join(folder, file))
        if image.shape[:2] != (81, 86):
            image = cv2.resize(image, (86, 81))
        image = cv2.resize(image[:55, :], (CARD_W, FACE_H))
        out[name] = image
    _face_templates = out
    logger.info(f'Composer loaded {len(out)} character templates')
    return out


def _load_weak_templates() -> dict:
    """assets/element/weak_*.png, {element: [variants]}."""
    global _weak_templates
    if _weak_templates is not None:
        return _weak_templates
    out = {}
    folder = './assets/element'
    for file in sorted(os.listdir(folder)):
        if not file.startswith('weak_') or not file.endswith('.png'):
            continue
        element = file[5:-4].split('.')[0]
        out.setdefault(element, []).append(load_image(os.path.join(folder, file)))
    _weak_templates = out
    return out


def composer_parse_candidates(text) -> list:
    """'1,2,3' / '1 > 2 > 3' / '1 2 3' -> [1, 2, 3], order kept, deduped."""
    out = []
    for token in re.split(r'[^0-9]+', str(text or '')):
        if not token:
            continue
        index = int(token)
        if 1 <= index <= 20 and index not in out:
            out.append(index)
    return out


def composer_person(name: str) -> str:
    """Collapse template names to a person id, forms of the same character
    cannot be fielded on both nodes."""
    name = name.split('.')[0]
    if name.startswith(('Stelle', 'Caelum', 'Trailblazer')):
        return 'Trailblazer'
    if name.startswith('March7th'):
        return 'March7th'
    if name.startswith('DanHeng'):
        return 'DanHeng'
    return name


def _character_of(name: str):
    from tasks.character.keywords import CharacterList
    base = name.split('.')[0]
    if base.startswith(('Stelle', 'Caelum')):
        base = 'Trailblazer' + base[6:]
    for instance in CharacterList.instances.values():
        if instance.name == base:
            return instance
    return None


def composer_element_of(name: str):
    """Element of a template name via CharacterList, None when unknown."""
    character = _character_of(name)
    return character.type_name if character else None


# Paths whose members are damage dealers nearly without exception. Nihility
# is excluded on purpose: it mixes main DPS (Acheron) with pure supports
# (Pela, Silver Wolf), undercounting is safer than overcounting
DPS_PATHS = {'The_Hunt', 'Erudition', 'Destruction'}


def composer_is_dps(name: str) -> bool:
    character = _character_of(name)
    return character is not None and character.path_name in DPS_PATHS


@dataclass
class PresetTeam:
    index: int
    # Per occupied slot: name (template name or 'unknown_<i>_<slot>'), element or None
    members: list = field(default_factory=list)
    elements: set = field(default_factory=set)
    faces: dict = field(default_factory=dict)  # member id -> face crop of unknowns
    signature: tuple = ()

    @property
    def persons(self) -> set:
        return {composer_person(m) for m, _ in self.members}

    @property
    def has_implant(self) -> bool:
        return any(m.split('.')[0] in IMPLANT_CHARACTERS for m, _ in self.members)

    @property
    def has_unknown(self) -> bool:
        return any(m.startswith('unknown') for m, _ in self.members)

    def __str__(self):
        members = ', '.join(f'{m}({e or "?"})' for m, e in self.members)
        return f'Preset_{self.index}[{members}]'

    __repr__ = __str__


def composer_match_score(team: PresetTeam, weaknesses: set) -> float:
    """
    How well a team fits a node. Hits are counted per member and a hit by a
    damage-dealer path weighs double, so a team built around an on-element
    main DPS beats a team that merely contains an on-element support.
    Weakness implanting (Firefly etc.) is a floor, not a trump: it
    guarantees a mid-tier fit but never outranks a real specialist.
    """
    if not weaknesses:
        # Weakness reading failed, no signal, treat all teams as fitting
        return 2.0
    hits = 0.0
    for name, element in team.members:
        if element and element in weaknesses:
            hits += 2.0 if composer_is_dps(name) else 1.0
    if team.has_implant:
        hits = max(hits, 1.5)
    elif hits == 0 and team.has_unknown:
        hits = 0.75
    return hits


def composer_rank_pairs(presets: list, weaknesses: dict) -> list:
    """
    All ordered disjoint pairs, best first.

    Args:
        presets: list of PresetTeam in user order (strongest first)
        weaknesses: {1: set, 2: set}

    Returns:
        list[tuple[PresetTeam, PresetTeam]]
    """
    n = len(presets)
    scored = []
    for i, team1 in enumerate(presets):
        for j, team2 in enumerate(presets):
            if i == j:
                continue
            if team1.persons & team2.persons:
                continue
            match = composer_match_score(team1, weaknesses.get(1, set())) \
                + composer_match_score(team2, weaknesses.get(2, set()))
            prior = (n - i) + (n - j)
            scored.append((match * 10 * n + prior, team1, team2))
    scored.sort(key=lambda x: -x[0])
    return [(t1, t2) for _, t1, t2 in scored]


class AbyssComposer(AbyssPrep):
    # {node_index: (x1, y1, x2, y2)} of the recommended-attribute icon strip
    # on the prep screen, override per mode
    WEAKNESS_STRIP = {}

    _composer_candidates = None
    _composer_presets = None
    _composer_stage_attempt = 0

    def composer_init(self, candidate_text):
        """Call at task start, parses config and resets per-run caches."""
        self._composer_candidates = composer_parse_candidates(candidate_text)
        self._composer_presets = None
        self._composer_stage_attempt = 0
        if self._composer_candidates and len(self._composer_candidates) < 2:
            logger.warning('CandidateTeams needs at least 2 presets, composer disabled')
            self._composer_candidates = []
        if self._composer_candidates:
            logger.info(f'Composer enabled, candidate presets: {self._composer_candidates}')

    @property
    def composer_enabled(self) -> bool:
        return bool(self._composer_candidates)

    """
    Weakness reading
    """

    def composer_read_weaknesses(self) -> dict:
        """
        Pages:
            in: PREP_CHECK
        """
        templates = _load_weak_templates()
        out = {}
        for node_index, strip in self.WEAKNESS_STRIP.items():
            found = set()
            image = crop(self.device.image, strip, copy=False)
            for element, variants in templates.items():
                best = 0.
                for template in variants:
                    for scale in (0.60, 0.65, 0.72, 0.80, 1.0, 1.10, 1.30, 1.45):
                        t = cv2.resize(template, None, fx=scale, fy=scale)
                        th, tw = t.shape[:2]
                        if th >= image.shape[0] or tw >= image.shape[1]:
                            continue
                        res = cv2.matchTemplate(image, t, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, _ = cv2.minMaxLoc(res)
                        best = max(best, float(max_val))
                if best >= 0.82:
                    found.add(element)
            out[node_index] = found
        logger.info(f'Node weaknesses: {out}')
        return out

    """
    Preset panel recognition
    """

    @staticmethod
    def composer_classify_badge(card_region) -> str:
        """
        Classify the element badge at the top-left of a preset card by hue.

        Args:
            card_region: RGB crop of the full card (95x89+)

        Returns:
            str: element name, 'empty' for an empty slot, 'unknown' otherwise
        """
        badge = card_region[7:20, 7:20]
        hsv = cv2.cvtColor(badge, cv2.COLOR_RGB2HSV)
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        sel = (s > 90) & (v > 80)
        n = int(sel.sum())
        if n >= 8:
            median = int(np.median(h[sel].astype(int)))
            best, best_dist = 'unknown', 999
            for element, center in ELEMENT_HUE.items():
                dist = min(abs(median - center), 180 - abs(median - center))
                if dist < best_dist:
                    best, best_dist = element, dist
            return best if best_dist <= 16 else 'unknown'
        # Physical badges are grey: bright but unsaturated. Untested against a
        # live physical badge yet, gates chosen from the glyph colors
        gray = int(((s <= 60) & (v > 130)).sum())
        if gray >= 25:
            return 'Physical'
        return 'empty'

    def _composer_scan_frame(self, image) -> list:
        """
        Detect preset rows and recognize members on one panel frame.

        Returns:
            list[dict]: [{'top': int, 'slots': [(name, element, face) or None x4]}]
            sorted by y, fully visible rows only
        """
        templates = _load_face_templates()
        x1, y1, x2, y2 = PANEL_AREA

        # Card rows sit on a fixed-pitch grid whose phase shifts with scroll.
        # Coarse phase: badge boxes are saturated while the title band above
        # every card row is flat dark. The optimum has a few pixels of
        # plateau, a face-template hit below refines it to the exact top.
        panel = image[y1:y2]
        hsv = cv2.cvtColor(panel, cv2.COLOR_RGB2HSV)
        sat = (((hsv[..., 1] > 90) & (hsv[..., 2] > 80))
               | ((hsv[..., 1] <= 60) & (hsv[..., 2] > 130))).astype(np.uint8)
        integral = cv2.integral(sat)

        def band_energy(top, dy1, dy2):
            yy1, yy2 = top - y1 + dy1, top - y1 + dy2
            if yy1 < 0 or yy2 >= sat.shape[0]:
                return None
            total = 0
            for cx in CARD_X:
                total += int(integral[yy2, cx + 20] - integral[yy1, cx + 20]
                             - integral[yy2, cx + 7] + integral[yy1, cx + 7])
            return total

        def phase_score(phase):
            total = 0
            for k in range(4):
                top = y1 + phase + k * ROW_PITCH
                badge = band_energy(top, 7, 20)
                if badge is None:
                    continue
                title = band_energy(top, -22, -9)
                total += badge - 2 * (title or 0)
            return total

        best_phase = max(range(ROW_PITCH), key=phase_score)

        # Identify faces with a wide vertical margin, the best hit pins the phase
        raw = {}
        best_hit = None  # (score, coarse_top, matched_top)
        for k in range(4):
            top = y1 + best_phase + k * ROW_PITCH
            if top < y1 - 12 or top + CARD_H > y2:
                continue
            for cx in CARD_X:
                region = image[max(0, top - 16):top + CARD_H + 4, cx - 4:cx + CARD_W + 4]
                if region.shape[0] < FACE_H + 4 or region.shape[1] < CARD_W:
                    continue
                best_name, best_score, best_y = None, 0., 0
                for name, template in templates.items():
                    res = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val > best_score:
                        best_name, best_score = name, float(max_val)
                        best_y = max(0, top - 16) + max_loc[1]
                raw[(top, cx)] = (best_name, best_score, best_y)
                if best_score >= 0.65 and (best_hit is None or best_score > best_hit[0]):
                    best_hit = (best_score, top, best_y)

        shift = best_hit[2] - best_hit[1] if best_hit else 0

        out = []
        for k in range(4):
            coarse = y1 + best_phase + k * ROW_PITCH
            top = coarse + shift
            if top < y1 + 5 or top + CARD_H > y2:
                continue
            slots = []
            occupied = 0
            for cx in CARD_X:
                best_name, best_score, _ = raw.get((coarse, cx), (None, 0., 0))
                card = image[top:top + CARD_H, cx:cx + CARD_W]
                element = self.composer_classify_badge(card)
                if best_score >= 0.65:
                    known = composer_element_of(best_name)
                    fallback = element if element not in ('empty', 'unknown') else None
                    slots.append((best_name, known or fallback, None))
                    occupied += 1
                elif element == 'empty':
                    slots.append(None)
                else:
                    el = element if element != 'unknown' else None
                    slots.append(('unknown', el, card[:FACE_H, :].copy()))
                    occupied += 1
            if occupied:
                out.append({'top': top, 'slots': slots})
        return out

    @staticmethod
    def _composer_row_signature(slots) -> tuple:
        sig = []
        for slot in slots:
            if slot is None:
                sig.append('empty')
            elif slot[0] == 'unknown':
                sig.append(f'unknown_{slot[1]}')
            else:
                sig.append(slot[0])
        return tuple(sig)

    def composer_open_preset_tab(self, skip_first_screenshot=True):
        """
        Pages:
            in: PREP_CHECK
            out: PREP_CHECK with character picker open on the preset tab
        """
        from tasks.abyss.assets.assets_abyss_prep import (
            PREP_CHECK,
            TAB_PRESET_CHECK,
            TAB_PRESET_CLICK
        )
        slot = self.TEAM_SLOT[1]
        timeout = Timer(20, count=10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.match_template_color(TAB_PRESET_CHECK):
                return True
            if timeout.reached():
                logger.warning('composer_open_preset_tab timeout')
                return False
            if self.match_template_luma(TAB_PRESET_CLICK, interval=2):
                self.device.click(TAB_PRESET_CLICK)
                continue
            if self.appear(PREP_CHECK, interval=2):
                self.device.click(slot)
                self._abyss_focused_node = 1
                continue

    def composer_scroll_top(self):
        for _ in range(2):
            self.device.swipe((240, 240), (240, 620), name='PRESET_SCROLL_TOP')
            self.device.sleep((0.4, 0.6))

    def composer_scan_presets(self) -> dict:
        """
        Scan candidate presets from the preset panel.

        Pages:
            in: PREP_CHECK
            out: PREP_CHECK with character picker open on the preset tab

        Returns:
            dict[int, PresetTeam]
        """
        logger.hr('Composer scan presets', level=2)
        if not self.composer_open_preset_tab():
            return {}
        self.composer_scroll_top()

        wanted = set(self._composer_candidates)
        results = {}
        prev_rows = None
        next_ordinal = 1
        for _ in range(10):
            self.device.screenshot()
            rows = self._composer_scan_frame(self.device.image)
            if not rows:
                logger.warning('No preset rows recognized on this frame')
                break

            # Anchor ordinals on rows shared with the previous frame
            signatures = [self._composer_row_signature(r['slots']) for r in rows]
            if prev_rows is None:
                ordinals = list(range(1, len(rows) + 1))
                next_ordinal = len(rows) + 1
            else:
                prev_sigs, prev_ords = prev_rows
                anchor = None
                for k, sig in enumerate(signatures):
                    if sig in prev_sigs:
                        anchor = (k, prev_ords[prev_sigs.index(sig)])
                        break
                if anchor is None:
                    ordinals = list(range(next_ordinal, next_ordinal + len(rows)))
                else:
                    k, ordinal = anchor
                    ordinals = [ordinal - k + idx for idx in range(len(rows))]
                next_ordinal = max(next_ordinal, ordinals[-1] + 1)
            prev_frame_max = max(ordinals)

            for row, ordinal, signature in zip(rows, ordinals, signatures):
                if ordinal in results:
                    continue
                team = PresetTeam(index=ordinal)
                for slot_index, slot in enumerate(row['slots']):
                    if slot is None:
                        continue
                    name, element, face = slot
                    if name == 'unknown':
                        name = f'unknown_{ordinal}_{slot_index}'
                        team.faces[name] = face
                    team.members.append((name, element))
                    if element:
                        team.elements.add(element)
                team.signature = signature
                results[ordinal] = team
                logger.info(f'Composer recognized {team}')

            if wanted and wanted.issubset(results.keys()):
                break
            if not wanted and prev_rows is not None and signatures == prev_rows[0]:
                break
            # Scroll for more rows; identical frame after a swipe = bottom
            if prev_rows is not None and signatures == prev_rows[0]:
                logger.info('Preset list bottom reached')
                break
            prev_rows = (signatures, ordinals)
            if max(wanted, default=0) <= prev_frame_max:
                break
            self.device.swipe((240, 560), (240, 250), name='PRESET_SCROLL')
            self.device.sleep((0.6, 0.8))

        self._composer_merge_unknowns(results)
        missing = wanted - set(results.keys())
        if missing:
            logger.warning(f'Candidate presets not found on the panel: {sorted(missing)}')
        return results

    @staticmethod
    def _composer_merge_unknowns(results: dict):
        """Unknown members sharing near-identical face crops are the same
        character, merge their ids so the overlap check sees the conflict."""
        entries = []
        for team in results.values():
            for name, face in team.faces.items():
                entries.append((team, name, face))
        for a in range(len(entries)):
            for b in range(a + 1, len(entries)):
                team_a, name_a, face_a = entries[a]
                team_b, name_b, face_b = entries[b]
                if team_a.index == team_b.index:
                    continue
                res = cv2.matchTemplate(face_a, face_b, cv2.TM_CCOEFF_NORMED)
                if float(res.max()) >= 0.80:
                    team_b.members = [(name_a if m == name_b else m, e) for m, e in team_b.members]
                    logger.info(f'Unknown member shared between preset {team_a.index} '
                                f'and {team_b.index}')

    """
    Picking and applying
    """

    def composer_pick_teams(self, default1: int, default2: int) -> tuple:
        """
        Pick preset indices for both nodes. Falls back to the configured
        fixed presets when disabled or when recognition failed.

        Pages:
            in: PREP_CHECK
        """
        if not self.composer_enabled:
            return default1, default2

        weaknesses = self.composer_read_weaknesses()
        if self._composer_presets is None:
            self._composer_presets = self.composer_scan_presets()
        presets = [self._composer_presets[i] for i in self._composer_candidates
                   if i in self._composer_presets]
        good = [p for p in presets if p.members]
        ranked = composer_rank_pairs(good, weaknesses)
        if not ranked:
            logger.warning('Composer found no valid disjoint pair, '
                           'fallback to fixed presets')
            return default1, default2

        for rank, (t1, t2) in enumerate(ranked[:5]):
            match = composer_match_score(t1, weaknesses.get(1, set())) \
                + composer_match_score(t2, weaknesses.get(2, set()))
            logger.info(f'  Pair #{rank + 1}: node1=Preset_{t1.index} '
                        f'node2=Preset_{t2.index} match={match:.2f}')
        attempt = int(self._composer_stage_attempt)
        team1, team2 = ranked[attempt % len(ranked)]
        logger.info(f'Composer pick (attempt {attempt + 1}, {len(ranked)} pairs): '
                    f'node1={team1}, node2={team2}')
        return team1.index, team2.index

    @staticmethod
    def _composer_signature_compatible(sig_a: tuple, sig_b: tuple) -> bool:
        """Unknown slots act as wildcards: their badge element can drift with
        the enabled-preset highlight, only known names and empties are firm."""
        if len(sig_a) != len(sig_b):
            return False
        for a, b in zip(sig_a, sig_b):
            a_open = a.startswith('unknown')
            b_open = b.startswith('unknown')
            if a_open or b_open:
                if (a == 'empty') != (b == 'empty'):
                    return False
                continue
            if a != b:
                return False
        return True

    def _abyss_click_preset(self, preset: int) -> bool:
        """Scroll-aware preset click, used by abyss_set_team."""
        if not self.composer_enabled or self._composer_presets is None:
            return super()._abyss_click_preset(preset)
        self.composer_scroll_top()
        # Top 3 presets sit at fixed positions once scrolled to the top
        if preset in PRESET_BLOCK:
            return super()._abyss_click_preset(preset)

        team = self._composer_presets.get(preset)
        if team is None:
            return super()._abyss_click_preset(3)
        for _ in range(8):
            self.device.screenshot()
            rows = self._composer_scan_frame(self.device.image)
            for row in rows:
                signature = self._composer_row_signature(row['slots'])
                if self._composer_signature_compatible(signature, team.signature):
                    top = row['top']
                    button = ClickButton((60, top, 460, top + CARD_H), name=f'PRESET_{preset}')
                    self.device.click(button)
                    return True
            self.device.swipe((240, 560), (240, 250), name='PRESET_SCROLL')
            self.device.sleep((0.6, 0.8))
        logger.warning(f'Preset {preset} not found while clicking, use slot fallback')
        return super()._abyss_click_preset(3)

    def abyss_prep_teams_and_enter(self, team1_preset=1, team2_preset=2):
        """
        Pages:
            in: PREP_CHECK
            out: loading screen towards in-dungeon map
        """
        if self.composer_enabled:
            team1_preset, team2_preset = self.composer_pick_teams(team1_preset, team2_preset)
        super().abyss_prep_teams_and_enter(team1_preset=team1_preset, team2_preset=team2_preset)
