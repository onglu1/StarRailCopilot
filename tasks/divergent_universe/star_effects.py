"""Observe current card effects and score only explicit, applicable mechanics."""
import hashlib
import json
import re
import time
from pathlib import Path

from module.base.utils import save_image
from module.config.config import TaskEnd


def effect_features(description, candidate):
    text = re.sub(r'\s+', '', description)
    if not text:
        return ()
    followup = candidate in ('followup', 'followup_fuxuan')
    dot = candidate in ('dot','dot_blackswan')
    # The current DOT inventory establishes Murmur's damage and charging
    # source. A stack cap or a different keyword is not interchangeable
    # with its observed damage or charging-efficiency improvements.
    if dot and re.fullmatch(
            r'【呢喃】(?:伤害提高|获得充能时的充能效率提高)(?:\d+(?:\.\d+)?%)?。?', text):
        return ('damage',)
    # Current cards confirm these automatic links to the observed DOT trait.
    # Match the whole trigger; neither titles nor unknown caps prove a bonus.
    if dot and re.fullmatch(
            r'(?:敌方目标陷入持续伤害时，为【呢喃】充能|'
            r'敌方目标每回合首次受到攻击后，触发1次【呢喃】伤害|'
            r'敌方目标回合结束时，【呢喃】获得充能值)。?', text):
        return ('damage',)
    if dot and re.fullmatch(
            r'敌方目标每次受到【呢喃】伤害后，造成的伤害降低。?', text):
        return ('enemy_weaken',)
    # This complete current card has an independent ATK bonus before its
    # cocoon clause. Only that bonus is credited in these reviewed candidates.
    if candidate in ('aglaea','aglaea_sustain','dot','dot_blackswan') and re.fullmatch(
            r'(?:我方目标)?攻击力提高，获得或消耗战技点后，为【魂茧】充能。?', text):
        return ('damage',)
    if dot and re.fullmatch(r'(?:我方目标)?施加负面状态后，攻击力提高。?', text):
        return ('damage',)
    # Do not infer unknown charge/stack mechanics from their decorative names.
    if any(word in text for word in ('回味', '呢喃', '魂茧', '蝶魄', '会心', '耀变', '罐中脑', '执念')):
        return ()
    if ('持续伤害' in text and not dot) or ('追加攻击' in text and not followup):
        return ()
    # These are different triggers from follow-up attacks. Their source has
    # not been established by this card alone. A later conditional bonus
    # does not invalidate an independent effect at the start of the text.
    if text.startswith(('阿哈行动后', '阿哈行动时', '阿哈首次行动后', '【发牌员】造成伤害时',
                        '忆灵行动后', '我方目标造成欢愉伤害时')):
        return ()
    tags = []
    if ('抵抗致命伤害' in text or
            ('致命' in text and '不会陷入无法战斗' in text)):
        tags.append('revive')
    elif re.search(r'(回复|恢复|回復).{0,24}生命', text):
        # Kill-only healing is unreliable during a boss without adds.
        tags.append('kill_heal' if '消灭' in text else 'heal')
    if dot and re.fullmatch(
            r'敌方目标每受到1次持续伤害[，,]我方全体(?:目标)?(?:回复|恢复|回復)'
            r'(?:等同于各自\d+(?:\.\d+)?%生命上限的)?生命值[。.]?', text):
        # Current cards explicitly cover the whole party on every DoT event.
        # Break/SP-triggered healing alone does not establish this coverage.
        tags.append('dot_team_heal')
    if '分摊' in text:
        tags.append('damage_share')
    # The game's simplified descriptions omit the ally subject. Accept the
    # observed base sentences, without treating enemy or named-mechanic
    # clauses as unconditional ally benefits.
    # Conditional matches retain their SP/low-health trigger in effect_text;
    # the defense tag does not assert that reduction is always active.
    simple_defense = re.fullmatch(
        r'(受到的伤害降低|防御力提高(?:，忆灵额外提高)?|'
        r'消耗战技点时，防御力提高|施放终结技后，生命上限提高|'
        r'消耗战技点后，受到的伤害降低|'
        r'生命百分比低于50%时，受到的伤害降低，回复量提高)。?', text)
    if (simple_defense or ('我方' in text and '防御力提高' in text)
            or re.search(r'(我方|角色|自身).{0,20}受到的伤害降低', text)):
        tags.append('defense')
    if '敌方' in text and ('造成的伤害降低' in text or '攻击力降低' in text):
        tags.append('enemy_weaken')
    if '行动延后' in text and '敌方' in text:
        tags.append('enemy_delay')
    if re.search(r'(恢复|回复).{0,15}(能量|战技点)', text) or '速度提高' in text or '行动提前' in text:
        tags.append('cycle')
    simple_damage = re.fullmatch(
        r'(?:造成的伤害提高(?:，忆灵额外提高)?|'
        r'攻击处于弱点击破状态下的敌方(?:目标|自标)后，造成超击破伤害)。?', text)
    if (simple_damage or ('敌方' in text and any(x in text for x in ('受到的伤害提高', '防御力降低')))
            or ('持续伤害' in text and ('提高' in text or '触发' in text))):
        tags.append('damage')
    if followup and ('追加攻击' in text or '附加伤害' in text) and any(x in text for x in ('伤害提高', '无视', '暴击')):
        tags.append('damage')
    return tuple(dict.fromkeys(tags))


def observe_candidate_frame(main, choices, kind):
    """Best-effort original frame plus existing metadata; no recognition/input."""
    active = getattr(main, 'active', None) or {}
    if (active.get('mode') != 'star' or not active.get('id') or not active.get('star')
            or not choices or kind == 'blessing' or not re.fullmatch(r'[a-z_]+', kind)):
        return
    try:
        image = main.op.image
        if getattr(image, 'shape', ())[:2] != (720, 1280):
            return
        cards = []
        for choice in choices:
            requirements = getattr(choice, 'requirements', ()) or ()
            if isinstance(requirements, dict):
                requirements = requirements.items()
            cards.append(dict(title=str(choice.title), rarity=int(choice.rarity),
                recommended=bool(choice.recommended), uncollected=bool(choice.uncollected),
                box=[int(value) for value in choice.box.button],
                paths=[str(path) for path in getattr(choice, 'paths', ())],
                requirements=[[str(path), int(count)] for path, count in requirements],
                effect_text=str(getattr(choice, 'effect_text', ''))))
        pixel_hash = hashlib.sha256(image.tobytes()).hexdigest()
        signature = hashlib.sha256((pixel_hash+json.dumps(cards, ensure_ascii=False,
            sort_keys=True, allow_nan=False)).encode('utf-8')).hexdigest()
        cache = getattr(main, '_star_candidate_evidence', None)
        if not cache or cache['run_id'] != active['id']:
            cache = dict(run_id=active['id'], frames={})
            main._star_candidate_evidence = cache
        node, selection = int(active.get('node') or 0), int(active.get('selections') or 0)
        entry = cache['frames'].setdefault((node, selection, kind), dict(seen=set(), attempts=0))
        if signature in entry['seen'] or entry['attempts'] >= 4:
            return
        entry['seen'].add(signature)
        entry['attempts'] += 1
        folder = Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/active['id']
        folder.mkdir(parents=True, exist_ok=True)
        screenshot = folder/f'choice_candidates_{node}_{selection}_{kind}_{time.time_ns()}_{entry["attempts"]}.png'
        payload = dict(kind=kind, run_id=active['id'], node=node, selection=selection,
            screenshot=str(screenshot), cards=cards, captured_at=time.time(),
            source='existing_op_image', pixel_sha256=pixel_hash, body_ocr_performed=False,
            frame_limit_per_selection_kind=4, frame_limit_scope='current_worker')
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        save_image(image, screenshot)
        screenshot.with_suffix('.json').write_text(encoded, encoding='utf-8')
        main.progress.record('star_candidate_frame_observed', **payload)
    except (TaskEnd, KeyboardInterrupt):
        raise
    except Exception as error:
        # Optional evidence must not turn a valid choice into a game fault.
        # This catch covers only this new recording path, never native actions
        # or the existing blessing OCR/scoring below.
        try:
            main.progress.record('star_candidate_frame_unavailable', kind=kind,
                                 error_type=type(error).__name__)
        except (TaskEnd, KeyboardInterrupt):
            raise
        except Exception:
            pass


def observe_effects(main, choices, kind):
    """Read only the description inside each observed full card, on this frame."""
    if kind != 'blessing':
        observe_candidate_frame(main, choices, kind)
        return
    op = main.op
    start = time.monotonic()
    for choice in choices:
        card = choice.box
        # Fallback/marker-only cards cannot locate the effect paragraph safely.
        if not (120 <= card.width <= 400 and card.top <= 200 and card.top + card.height >= 535):
            continue
        left, right = max(0, card.left + 9), min(1280, card.left + card.width - 9)
        if right - left < 100:
            continue
        region = (left / 1280, 390 / 720, right / 1280, 528 / 720)
        boxes = op.read_region(region, snapshot=False)
        choice.effect_text = ''.join(b.source for b in sorted(boxes, key=lambda b: (round(b.top / 10), b.left)))[:500]
        choice.effect_tags = effect_features(choice.effect_text, main.star_loadout.candidate)
        choice.effect_roi = (left, 390, right, 528)
    # Save the already captured frame; no extra device capture or GPU session.
    folder = Path(__file__).resolve().parents[2] / 'log/divergent_universe' / main.config.config_name / 'star_runs' / main.active['id']
    folder.mkdir(parents=True, exist_ok=True)
    screenshot = folder / f'choice_effects_{main.active.get("node",0)}_{main.active.get("selections",0)}.png'
    save_image(op.image, screenshot)
    main.progress.record('star_effects_observed', seconds=round(time.monotonic()-start, 3), screenshot=str(screenshot),
                         cards=[dict(title=c.title, text=getattr(c,'effect_text',''),
                                     tags=getattr(c,'effect_tags',()), roi=getattr(c,'effect_roi',None)) for c in choices])
