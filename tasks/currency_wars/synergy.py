"""Select an available team by guide synergies, then cost and stars."""
import re


TRAITS = ('仙舟', '公司', '列车同行', '贝洛伯格', '夜之半神', '昼之半神', '盛会之星',
          '星核猎手', '星间旅人', '银河学者', '巡海游侠', '狼狩', '战技点', '量子同频',
          '追击', '能量', '群攻', '燃血', '持续伤害', '减益', '击破', '治疗', '护盾',
          '命运圣杯', '妖星间旅人', '欢愉')
ALIASES = {'追加攻击': '追击', '量子': '量子同频', '列车': '列车同行', 'DOT': '持续伤害'}


def extract_traits(text):
    text = text.replace('追加攻击', '追击')
    return tuple(trait for trait in TRAITS if trait in text)


def parse_synergy_targets(title):
    match = re.search(r'【([^】]+)】', title)
    text = match.group(1) if match else ''
    labels = sorted(set(TRAITS) | set(ALIASES), key=len, reverse=True)
    pattern = r'(\d+)\s*(' + '|'.join(map(re.escape, labels)) + ')'
    return {ALIASES.get(label, label): int(count) for count, label in re.findall(pattern, text) if int(count) > 0}


def trait_counts(characters):
    unique = {c.name: c for c in characters if c is not None and not c.is_npc}
    return {trait: sum(trait in c.traits for c in unique.values()) for trait in TRAITS}


def select_team(characters, planned, targets, capacity, front_slots=4, back_slots=9,
                required=None, fixed=()):
    """Choose one complete team; include temporary units and preserve ties."""
    required = targets if required is None else required
    goals = dict(targets)
    for trait, goal in required.items():
        goals[trait] = max(goal, goals.get(trait, 0))
    labels = tuple(goals)
    fixed_names = {c.name for c in fixed}
    available = {}
    for character in characters:
        if character is None or character.is_npc or character.is_locked or character.name in fixed_names:
            continue
        old = available.get(character.name)
        if old is None or (character.stars, character.cost, character.is_placed) > (old.stars, old.cost, old.is_placed):
            available[character.name] = character
    base = trait_counts(fixed)
    # States with the same occupancy/traits need only retain their strongest
    # roster. This avoids repeatedly enumerating every bench/field subset.
    states = {(0, 0, 0, tuple(min(base.get(t, 0), goals[t]) for t in labels)): ((0, 0, 0, 0), ())}
    for c in available.values():
        quality = (c.cost, c.stars, int(c.name in planned), int(c.is_placed))
        for (n, front, back, counts), (old_quality, names) in list(states.items()):
            nf, nb = front + int(c.position == 1), back + int(c.position == 2)
            if n >= capacity or n >= front_slots + back_slots or nf > front_slots or nb > back_slots:
                continue
            counts = tuple(min(goals[t], value + int(t in c.traits)) for t, value in zip(labels, counts))
            key = (n + 1, nf, nb, counts)
            candidate = (tuple(a + b for a, b in zip(old_quality, quality)), names + (c.name,))
            if key not in states or candidate[0] > states[key][0]:
                states[key] = candidate
    def score(item):
        (n, _, _, values), (quality, _) = item
        counts = dict(zip(labels, values))
        return (n, sum(counts[t] >= goal for t, goal in required.items()),
                sum(min(counts[t], goal) / goal for t, goal in required.items()),
                sum(counts[t] >= goal for t, goal in targets.items()),
                sum(min(counts[t], goal) / goal for t, goal in targets.items()), *quality)
    return set(max(states.items(), key=score)[1][1])


def minimum_team_size(characters, targets):
    """Minimum population using known unit traits, excluding emblem bonuses."""
    if not targets:
        return None
    characters = [c for c in characters if c is not None]
    planned = {c.name for c in characters}
    for size in range(1, min(10, len(planned)) + 1):
        names = select_team(characters, planned, targets, size)
        counts = trait_counts(c for c in characters if c.name in names)
        if all(counts[t] >= goal for t, goal in targets.items()):
            return size
    return None
