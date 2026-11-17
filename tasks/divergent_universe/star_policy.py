"""Deterministic gates and evidence accounting for reproducible star runs."""
from dataclasses import dataclass
from collections import Counter
from functools import lru_cache
from pathlib import Path
import base64
import hashlib
import json
import re
import zlib


MASK_OCR_LABELS = {
    '雪鸮面具': ('雪鸮面具', '雪鹃面具', '雪面具'),
    '囧之面具': ('囧之面具', '冏之面具'),
}


def mask_name(text):
    # These exact variants were observed on each mask's choice/detail
    # page. Do not fuzzy-match other mask names during a menu transition.
    return next((name for name, labels in MASK_OCR_LABELS.items() if text in labels), text)


def mask_labels(text):
    name = mask_name(text)
    return MASK_OCR_LABELS.get(name, (name,))


def validate_guide_code(text):
    match = re.search(r'DIV##([A-Za-z0-9+/=]+)\$\$UNI', text)
    if not match or len(match[1]) > 8192:
        raise ValueError('攻略码必须包含有效的 DIV##…$$UNI')
    encoded = match[1]
    raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), validate=True)
    if raw[:4] != b'\x01\x00\x00\x00':
        raise ValueError('未知攻略码格式版本')
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    payload = decoder.decompress(raw[4:], 4097)
    if len(payload) > 4096 or not decoder.eof or decoder.unused_data:
        raise ValueError('攻略码校验失败或超过允许大小')
    # The native game defines the payload schema. A valid checksum does not
    # prove a guide is applicable, that a character is owned, or it was applied.
    return match[0]


def policy_signature(team, code, revision):
    normalized = validate_guide_code(code)
    value = '\n'.join([*team, normalized, revision])
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def guide_codes_equivalent(requested, exported):
    """Allow only the observed game import/export header change, byte-for-byte otherwise."""
    def payload(code):
        normalized = validate_guide_code(code)
        s = normalized.split('##', 1)[1].split('$$', 1)[0]
        raw = base64.b64decode(s + '=' * (-len(s) % 4))
        return zlib.decompress(raw[4:], 16 + zlib.MAX_WBITS)
    left, right = payload(requested), payload(exported)
    if left == right:
        return True
    # Actual game readback preserved every build/character byte and changed
    # only the second header word from 1 to 2. Do not generalize other fields.
    return (left[:8] == b'\x03\x00\x00\x00\x01\x00\x00\x00'
            and right[:8] == b'\x03\x00\x00\x00\x02\x00\x00\x00'
            and left[8:] == right[8:])


def decode_guide_plan(code):
    """Decode the supplied v3 plans with bounded counts and no ignored tail.

The game's exported copy was used to check this layout. Unknown nonempty
sections or character record versions are rejected, not guessed.
"""
    normalized = validate_guide_code(code)
    encoded = normalized.split('##', 1)[1].split('$$', 1)[0]
    raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4))
    data = zlib.decompress(raw[4:], 16 + zlib.MAX_WBITS)
    offset = 0
    def read(size):
        nonlocal offset
        if offset + size > len(data):
            raise ValueError('攻略内容不完整')
        value = int.from_bytes(data[offset:offset + size], 'little')
        offset += size
        return value
    if read(4) != 3 or read(4) not in (1, 2):
        raise ValueError('尚未支持的攻略内容版本')
    def ids():
        count = read(1)
        if count > 32:
            raise ValueError('攻略条目数不符合已验证格式')
        return [read(4) for _ in range(count)]
    result = dict(core_equation_ids=ids(), secondary_equation_ids=ids(), weighted_curio_ids=ids())
    if read(1) != 0:
        raise ValueError('攻略包含未适配的附加内容段')
    count = read(1)
    if not 1 <= count <= 4:
        raise ValueError('攻略推荐队伍数量超出范围')
    teams = []
    for _ in range(count):
        slots = []
        for _ in range(4):
            alternatives = read(1)
            if not 1 <= alternatives <= 8:
                raise ValueError('攻略角色备选数量超出范围')
            members = []
            for _ in range(alternatives):
                if read(1) != 1:
                    raise ValueError('攻略角色记录类型未适配')
                members.append(read(4))
            slots.append(members)
        teams.append(slots)
    if offset != len(data):
        raise ValueError('攻略中有未解析的尾部字段')
    result['teams'] = teams
    return result


@dataclass(frozen=True)
class StarLoadout:
    candidate: str
    team: tuple
    guide_code: str
    core_equations: tuple = ()
    survival_blessings: tuple = ('超高速云际介质','受迫性跃迁','放射性衰变','新星爆发','双极喷流')
    revision: str = 'star-workshop-v8'

    @property
    def signature(self):
        if len(self.team) != 4 or len(set(self.team)) != 4:
            raise ValueError('拓星队伍必须是四名不同角色')
        revision = self.revision
        if revision=='star-paths-v2' or revision.startswith('star-workshop-'):
            rules = dict(catalog=star_catalog(), core_equations=self.core_equations,
                         survival_blessings=self.survival_blessings)
            revision += ':' + hashlib.sha256(json.dumps(rules,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return policy_signature(self.team, self.guide_code, revision)


def verified_secondary_equations(guide, imported):
    """Retain actual secondary-card labels, never infer them from path affinity."""
    signature=hashlib.sha256(guide['code'].encode('utf-8')).hexdigest()
    if not imported or not imported.get('import_verified') or imported.get('guide_signature')!=signature:
        return None
    labels=[row for row in imported.get('labels',[]) if len(row.get('box',[]))==4
            and 256<=row['box'][0]<704 and 350<=row['box'][1]<565]
    labels.sort(key=lambda row:(round((row['box'][1]+row['box'][3])/120),row['box'][0]))
    names=[re.sub(r'\s+','',row['text']) for row in labels]
    expected=len(decode_guide_plan(guide['code'])['secondary_equation_ids'])
    if (len(names)!=expected or len(set(names))!=expected
            or any(name not in star_catalog()['equations'] for name in names)
            or not imported.get('screenshot')):
        return None
    return dict(names=names,guide_signature=signature,screenshot=imported['screenshot'],
                source='verified_import_secondary_cards')


def loadout_from_guide(guide, imported=None):
    core=guide.get('core_equations')
    if not core:
        signature=hashlib.sha256(validate_guide_code(guide['code']).encode('utf-8')).hexdigest()
        if not imported or not imported.get('import_verified') or imported.get('guide_signature')!=signature:
            raise ValueError('缺少当前攻略的实际导入回读证明')
        # OCR may order adjacent cards by one-pixel baseline differences.
        # The actual guide has two rows; preserve their visual left-to-right order.
        labels=[row for row in imported.get('labels',[]) if len(row.get('box',[]))==4
                and 256<=row['box'][0]<704 and 165<=row['box'][1]<288]
        labels.sort(key=lambda row:(round((row['box'][1]+row['box'][3])/120),row['box'][0]))
        names=[row['text'] for row in labels] if labels else imported.get('core_equations',[])
        core=[catalog_name(name,star_catalog()['equations']) for name in names]
        expected=len(decode_guide_plan(guide['code'])['core_equation_ids'])
        if len(core)!=expected or not all(core) or len(set(core))!=expected:
            raise ValueError('导入攻略核心方程未能完整识别，不能开始新方案')
    return StarLoadout(guide['key'],tuple(guide.get('selected_team_names') or guide['candidate_team']),
                       guide['code'],core_equations=tuple(core))


def reconcile_imported_core_order(active, guide, imported):
    star=active.get('star',{});saved=star.get('loadout',{})
    if guide.get('core_equations') or saved.get('candidate')!=guide['key'] or saved.get('guide_code')!=guide['code']:
        return None
    corrected=loadout_from_guide(guide,imported)
    before=list(saved.get('core_equations',[]));after=list(corrected.core_equations)
    if before==after or sorted(before)!=sorted(after):
        return None
    if tuple(saved.get('team',[]))!=corrected.team:
        return None
    revision={'before':before,'after':after,'previous_policy_signature':star.get('policy_signature'),
              'node':active.get('node'),'selections':active.get('selections'),
              'guide_screenshot':imported.get('screenshot'),'reason':'verified_guide_visual_order'}
    star.setdefault('policy_order_corrections',[]).append(revision)
    saved['core_equations']=after
    star['policy_signature']=corrected.signature
    active.setdefault('execution',{})['policy_corrected_during_run']=True
    return revision


def entry_rank_evidence(threshold, title, screenshot):
    """Map only the official X10 title/protocol pair observed at entry."""
    if type(threshold) is int and threshold == 9 and title == '万机之王' and screenshot:
        return dict(star_rank=10, rank_title=title, threshold=threshold,
                    source='entry_title_protocol', entry_screenshot=screenshot,
                    mapping_source='https://www.miyoushe.com/sr/article/77624815',
                    mapping_version='4.5')
    return None


def verified_star_rank(star):
    """A protocol number or a promotion result cannot prove entry rank."""
    evidence = entry_rank_evidence(star.get('threshold'), star.get('rank_title'),
                                   star.get('rank_screenshot'))
    if (evidence and type(star.get('star_rank')) is int
            and star['star_rank'] == evidence['star_rank']
            and star.get('star_rank_evidence') == evidence):
        return evidence['star_rank']
    return None


def verified_start(loadout, observation):
    """Return persisted start evidence or reject; a config alone never passes."""
    if tuple(observation.get('members', ())) != loadout.team:
        raise ValueError('实际队伍尚未核对为预期四名角色')
    if observation.get('guide_signature') != hashlib.sha256(
            validate_guide_code(loadout.guide_code).encode('utf-8')).hexdigest():
        raise ValueError('攻略尚未确认已应用')
    if observation.get('guide_policy_applied') is not True:
        raise ValueError('攻略尚未绑定生产选牌策略')
    threshold = observation.get('threshold')
    if type(threshold) is not int or not 1 <= threshold <= 10:
        raise ValueError('未从实际星阶页面确认阈值等级')
    if observation.get('mode') != '拓星模式':
        raise ValueError('尚未确认拓星模式标签处于选中状态')
    if not observation.get('team_screenshot') or not observation.get('rank_screenshot'):
        raise ValueError('缺少开局阵容或星阶的实机证据')
    title = observation.get('title', '')
    evidence = entry_rank_evidence(threshold, title, observation['rank_screenshot'])
    return dict(candidate=loadout.candidate, policy_signature=loadout.signature,
                members=list(loadout.team), guide_signature=observation['guide_signature'],
                threshold=threshold, threshold_text=observation.get('observed_text', ''),
                rank_title=title, star_rank=evidence['star_rank'] if evidence else None,
                star_rank_evidence=evidence, mode=observation['mode'],
                guide_policy_applied=True,
                team_screenshot=observation['team_screenshot'], rank_screenshot=observation['rank_screenshot'])


def upgrade_effect_policy(active):
    """Keep the retained run, while explicitly marking this strategy intervention."""
    star = active.get('star', {})
    saved = star.get('loadout', {})
    if saved.get('revision') not in ('star-workshop-v6','star-workshop-v7'):
        return None
    previous = star.get('policy_signature')
    before = saved['revision']
    saved['revision'] = 'star-workshop-v8'
    loadout = StarLoadout(**saved)
    star['policy_signature'] = loadout.signature
    change = dict(from_revision=before, to_revision=loadout.revision,
                  previous_signature=previous, signature=loadout.signature, node=active.get('node'))
    star.setdefault('policy_changes', []).append(change)
    active.setdefault('execution', {})['policy_corrected_during_run'] = True
    return change


@lru_cache(maxsize=1)
def star_catalog():
    return json.loads((Path(__file__).parent/'star_catalog.json').read_text('utf-8'))


def catalog_name(title, table):
    """Ignore punctuation; accept a clipped prefix only if it is unique."""
    def clean(value):
        return re.sub(r'[^A-Za-z0-9\u4e00-\u9fff]','',value)
    value = clean(title)
    # Exact readings reproduced on the real equation list/detail screenshots.
    # These are not edit-distance guesses and apply only if that item exists.
    aliases={'殷铸人生':'骰铸人生','首美丽的诗':'一首美丽的诗','梦魔主':'梦魇主'}
    if value in aliases and aliases[value] in table:
        return aliases[value]
    exact = [name for name in table if clean(name)==value]
    if len(exact)==1:
        return exact[0]
    prefixes = [name for name in table if len(value)>=5 and clean(name).startswith(value)]
    return prefixes[0] if len(prefixes)==1 else None


def observed_blessings(choices):
    """Replay confirmed selections/discards, without claiming unseen rewards."""
    table = star_catalog()['blessings']
    held = {}
    for choice in choices:
        key = catalog_name(choice['title'],table) or choice['title']
        if choice['kind']=='blessing':
            held[key]=choice['title']
        elif choice['kind']=='discard':
            held.pop(key,None)
    return list(held.values())


def decision_inventory(star):
    """Bound counts after the last real inventory, without rewriting that evidence.

    A reward may duplicate an unseen inventory item. New confirmed names give
    an upper bound; the current unique names give an independent lower bound.
    Neither path names nor removals are guessed from the old catalogue.
    """
    snapshot = star.get('inventory_path_counts')
    index = star.get('inventory_choice_index')
    choices = star.get('choices', [])
    if snapshot is None or type(index) is not int or not 0 <= index <= len(choices):
        return dict(counts=snapshot, upper_counts=snapshot, requires_refresh=True, source='missing_watermark')
    lower, upper = dict(snapshot), dict(snapshot)
    table = star_catalog()['blessings']
    held = {}
    after_snapshot = {}
    unknown = False
    for position, choice in enumerate(choices):
        kind = choice.get('kind')
        if kind not in ('blessing','discard'):
            continue
        title = catalog_name(choice.get('title',''),table) or choice.get('title','')
        paths = choice.get('paths', [])
        path = paths[0] if len(paths) == 1 and paths[0] in snapshot else None
        previous = held.get(title)
        if kind == 'blessing':
            if position >= index and title not in held:
                if path:
                    upper[path] += 1
                else:
                    unknown = True
            held[title] = path or previous
            if position >= index:
                after_snapshot[title] = path
        else:
            path = path or previous
            if position >= index:
                # A confirmed discard removes one actual item; an unknown
                # path cannot leave the old inventory labelled a lower bound.
                if path:
                    lower[path] = max(0,lower[path]-1)
                    upper[path] = max(0,upper[path]-1)
                else:
                    unknown = True
            held.pop(title,None)
            after_snapshot.pop(title,None)
    reliable = Counter(path for path in after_snapshot.values() if path)
    for path in lower:
        lower[path] = max(lower[path],reliable[path])
        upper[path] = max(upper[path],lower[path])
    return dict(counts=lower, upper_counts=upper, requires_refresh=unknown,
                source='observed_inventory_and_confirmed_choice_bounds', inventory_choice_index=index,
                current_choice_index=len(choices), inventory_node=star.get('inventory_node'))


def uncertain_growth_threshold(loadout, inventory, requirements=None, threshold=None, growth_target=None):
    """Completes-at-one is nonmonotone; checking only interval ends is unsafe."""
    if inventory.get('requires_refresh'):
        return True
    low,high=inventory.get('counts') or {},inventory.get('upper_counts') or {}
    targets=[equation_requirements(n,requirements,threshold) for n in loadout.core_equations]
    if growth_target and not growth_target.get('done'):
        targets.append(growth_target.get('requirements',{}))
    return any(low.get(p,0)<high.get(p,0) and low.get(p,0)<need and high.get(p,0)>=need-1
               for target in targets for p,need in target.items())


def equation_requirements(name, requirements=None, threshold=None):
    """Current-run readings override rank-specific planning evidence."""
    if name in (requirements or {}):
        return requirements[name]
    item=star_catalog()['equations'].get(name,{})
    ranks=item.get('requires_by_rank',{})
    known=[int(rank) for rank in ranks if type(threshold) is int and int(rank)<=threshold]
    # Higher, unseen ranks retain the strongest observed lower-rank planning
    # target until their UI is read. This never proves equation expansion.
    return ranks[str(max(known))] if known else item.get('requires',{})


def secondary_completion_path(target):
    if not target or target.get('name')!='永恒竞走' or target.get('source')!='same_frame_rewrite_strip':
        return None
    needs=target.get('requirements',{});counts=target.get('counts_after_removal',{})
    if (set(needs)!={'虚无','巡猎'} or set(counts)!=set(needs)
            or any(type(n) is not int or not 1<=n<=200 for n in needs.values())
            or any(type(n) is not int or not 0<=n<=200 for n in counts.values())):
        return None
    missing={path:max(0,need-counts[path]) for path,need in needs.items()}
    return next((path for path,value in missing.items() if value==1),None) if sum(missing.values())==1 else None


def pending_secondary_completion(active, kind, session):
    """A saved optional target belongs to one worker's current paid choice only."""
    star=active.get('star',{});visit=star.get('workshops',{}).get(str(active.get('node')), {})
    target=visit.get('secondary_completion')
    if not target:
        return None
    proof=star.get('secondary_equation_evidence') or {}
    last=star.get('choices',[])[-1:]
    if (kind!='blessing' or active.get('stop_requested') or not visit.get('blessing_choice_pending')
            or not session or target.get('session')!=session
            or (target.get('run_id'),target.get('node'),target.get('selection'),target.get('request'))
               !=(active.get('id'),active.get('node'),active.get('selections'),visit.get('blessing_rewrites'))
            or target.get('choice_index')!=len(star.get('choices',[]))-1
            or not last or last[0].get('kind')!='discard' or last[0].get('source')!='blessing_rewrite'
            or last[0].get('title')!=target.get('removed_title')
            or last[0].get('paths')!=[target.get('removed_path')]
            or proof.get('source')!='verified_import_secondary_cards'
            or target.get('name') not in proof.get('names',())
            or not star.get('guide_signature')
            or target.get('guide_signature')!=star.get('guide_signature')
            or proof.get('guide_signature')!=star.get('guide_signature')
            or not secondary_completion_path(target)):
        visit.pop('secondary_completion',None)
        return None
    return target


def visible_secondary_growth(active, loadout, inventory, kind, session):
    """A visible DOT secondary near expansion, not proof that the core is absent.

    Use only the next ordinary choice after one paired equation/blessing read.
    Missing evidence falls back to existing scoring; it never requests a read.
    """
    star=active.get('star',{})
    visit=star.get('workshops',{}).get(str(active.get('node')), {})
    if (kind!='blessing' or loadout.revision!='star-workshop-v8'
            or loadout.candidate not in ('dot','dot_blackswan') or active.get('mode')!='star'
            or active.get('stop_requested') or visit.get('blessing_choice_pending') or not session):
        return None
    name='永恒竞走'
    guide=star.get('secondary_equation_evidence') or {}
    equation=star.get('equation_inventory') or {}
    watermark=equation.get('decision_watermark') or {}
    current=dict(run_id=active.get('id'),session=session,node=active.get('node'),
                 selection=active.get('selections'),choice_index=len(star.get('choices',[])))
    if (not current['run_id'] or any(watermark.get(key)!=value for key,value in current.items())
            or type(watermark.get('observation')) is not int
            or watermark!=star.get('inventory_equation_watermark')
            or equation.get('node')!=current['node'] or star.get('inventory_node')!=current['node']
            or inventory.get('inventory_choice_index')!=current['choice_index']
            or inventory.get('current_choice_index')!=current['choice_index']
            or inventory.get('requires_refresh') or not inventory.get('counts')
            or inventory['counts']!=inventory.get('upper_counts')
            or equation.get('counts',{}).get('expanded')!=0
            or equation.get('visible_tab')!='unexpanded' or equation.get('visible_only') is not True
            or name not in equation.get('visible_names',())
            or name in equation.get('visible_expanded_names',())
            or not equation.get('screenshot') or not star.get('inventory_screenshot')
            or guide.get('source')!='verified_import_secondary_cards' or name not in guide.get('names',())
            or not star.get('guide_signature') or guide.get('guide_signature')!=star['guide_signature']):
        return None
    needs=star.get('observed_equation_requirements',{}).get(name,{})
    if (set(needs)!={'虚无','巡猎'}
            or any(type(n) is not int or not 1<=n<=200 for n in needs.values())
            or any(type(inventory['counts'].get(p)) is not int or not 0<=inventory['counts'][p]<=200
                   for p in needs)):
        return None
    counts={path:inventory['counts'][path] for path in needs}
    missing={path:max(0,need-counts[path]) for path,need in needs.items()}
    if not 1<=sum(missing.values())<=2:
        return None
    return dict(name=name,source='visible_inventory_near_secondary',requirements=dict(needs),counts=counts,
                missing=missing,watermark=dict(watermark),guide_signature=star['guide_signature'],
                equation_screenshot=equation['screenshot'],inventory_screenshot=star['inventory_screenshot'],
                primary_ownership='not_inferred')


def rank_star_choices(choices, loadout, kind, owned=(), requirements=None, path_counts=None, threshold=None, owned_effect_tags=(), growth_target=None, secondary_completion=None, secondary_growth=None):
    """Core/survival first; gallery completion never outranks the build."""
    if not choices:
        raise ValueError('没有可识别候选')
    catalog = star_catalog() if loadout.revision=='star-paths-v2' or loadout.revision.startswith('star-workshop-') else None
    blessings = catalog['blessings'] if catalog else {}
    equations = catalog['equations'] if catalog else {}
    primary = equation_requirements(next(iter(loadout.core_equations),''),requirements,threshold) if catalog else {}
    if (loadout.revision=='star-workshop-v8' and kind in ('blessing','discard') and growth_target
            and not growth_target.get('done') and growth_target.get('requirements')):
        primary = growth_target['requirements']
    targets = dict(primary)
    for name in loadout.core_equations:
        req=equation_requirements(name,requirements,threshold) if catalog else {}
        for path, required in req.items():
            targets[path] = max(targets.get(path,0),required)
    observed = {catalog_name(title,blessings) for title in owned}
    counts = Counter(blessings[name]['path'] for name in observed if name)
    if path_counts is not None:
        if any(type(value) is not int or not 0<=value<=200 for value in path_counts.values()):
            raise ValueError('实际命途祝福数量无效')
        counts=Counter(path_counts)
    secondary_path=(secondary_completion_path(secondary_completion)
                    if kind=='blessing' and loadout.candidate in ('dot','dot_blackswan') else None)
    growth_paths=()
    if (kind=='blessing' and loadout.revision=='star-workshop-v8'
            and loadout.candidate in ('dot','dot_blackswan') and secondary_growth
            and not growth_target and not secondary_completion
            and secondary_growth.get('name')=='永恒竞走'
            and secondary_growth.get('source')=='visible_inventory_near_secondary'):
        needs=secondary_growth.get('requirements',{})
        actual=secondary_growth.get('counts',{})
        if (set(needs)==set(actual)=={'虚无','巡猎'}
                and all(type(n) is int and 1<=n<=200 for n in needs.values())
                and all(type(n) is int and 0<=n<=200 for n in actual.values())
                and all(counts[p]==actual[p] for p in needs)
                and 1<=sum(max(0,needs[p]-actual[p]) for p in needs)<=2):
            growth_paths=tuple(p for p in needs if actual[p]<needs[p])
    primary_missing=sum(max(0,need-counts[path]) for path,need in primary.items())
    primary_offered=False
    if secondary_path and primary_missing==1:
        for choice in choices:
            paths=getattr(choice,'paths',())
            path=paths[0] if len(paths)==1 else blessings.get(catalog_name(choice.title,blessings),{}).get('path')
            if path in primary and counts[path]<primary[path]:
                primary_offered=True
                break
    def score(choice):
        name = choice.title.replace(' ', '')
        survival = any(term in name for term in loadout.survival_blessings)
        core = any(term in name for term in loadout.core_equations)
        # Explicit guide/core names beat unknown suggestions. Preserve a
        # survival option even if uncollected flags favour an unrelated item.
        value = (survival and (kind == 'discard' or name not in owned), core,
                 choice.recommended, choice.rarity)
        if catalog:
            core_priority = next((len(loadout.core_equations)-i for i,term in enumerate(loadout.core_equations)
                                  if term in name),0)
            affinity = 0
            if kind in ('blessing','discard'):
                canonical = catalog_name(name,blessings)
                paths=getattr(choice,'paths',())
                path = paths[0] if len(paths)==1 else blessings.get(canonical,{}).get('path')
                # Counts cover explicitly selected blessings only. Missing
                # automatic rewards cannot be mistaken for verified expansion.
                affinity = (4 if path in primary and counts[path]<primary[path] else
                            3 if path in targets and counts[path]<targets[path] else
                            2 if path in primary else 1 if path in targets else 0)
            elif kind == 'equation':
                canonical = catalog_name(name,equations)
                req=dict(getattr(choice,'requirements',()) or equation_requirements(canonical,requirements,threshold))
                affinity = sum(required*(2 if path in primary else 1 if path in targets else 0)
                               for path,required in req.items())
            value = (survival,core_priority,affinity,choice.recommended,choice.rarity)
            if (loadout.revision in ('star-workshop-v7','star-workshop-v8') and kind in ('blessing','discard')
                    and (growth_paths or any(getattr(c, 'effect_text', '') for c in choices))):
                tags = set(getattr(choice, 'effect_tags', ()))
                known = bool(getattr(choice, 'effect_text', ''))
                # Effect evidence is from this game's visible card. A missing
                # description keeps the old path rules, not old wiki effects.
                incompatible = loadout.candidate == 'followup_fuxuan' and 'damage_share' in tags
                missing = sum(max(0, need-counts[p]) for p, need in primary.items())
                completes = bool(missing == 1 and path in primary and counts[path] < primary[path])
                # Preserve primary completion first; a verified secondary can
                # then use the same tier without replacing primary affinity.
                if (not primary_offered and secondary_path and len(getattr(choice,'paths',()))==1
                        and choice.paths[0]==secondary_path):
                    completes=True
                held = set(owned_effect_tags) if kind != 'discard' else set()
                missing_dot_team_heal=(loadout.candidate in ('dot','dot_blackswan')
                    and 'dot_team_heal' in tags and 'dot_team_heal' not in held)
                insurance = (3 if 'revive' in tags and 'revive' not in held else
                             2 if missing_dot_team_heal else
                             2 if 'heal' in tags and 'heal' not in held else 0)
                functional = (3 if 'enemy_delay' in tags else
                              2 if tags.intersection(('cycle','damage','heal','defense','enemy_weaken')) else
                              1 if 'kill_heal' in tags else 0)
                # A directly working automatic effect can beat distant path
                # filler. Finish an actually one-card-away primary first.
                value = (not incompatible, insurance, completes, core_priority,
                         affinity + functional, functional,
                         survival if not known else False, choice.recommended, choice.rarity)
                if growth_paths:
                    # This one decision has an explicit extra score column.
                    # Insurance and existing completion tiers remain ahead;
                    # no primary requirement or original affinity is replaced.
                    near_secondary=(len(getattr(choice,'paths',()))==1 and choice.paths[0] in growth_paths)
                    value=value[:4]+(near_secondary,)+value[4:]
        return tuple(-int(x) for x in value) if kind == 'discard' else value
    return sorted(((choice,score(choice)) for choice in choices),key=lambda item:item[1],reverse=True)


def star_choice(choices, loadout, kind, owned=(), requirements=None, path_counts=None, threshold=None):
    return rank_star_choices(choices,loadout,kind,owned,requirements,path_counts,threshold)[0][0]


def observe_choice_paths(op,choices,kind):
    """Read current-game path labels, not a full card's description."""
    if kind not in ('blessing','equation'):
        return
    paths=('毁灭','巡猎','智识','欢愉','记忆','存护','同谐','虚无','丰饶','繁育')
    for choice in choices:
        card=choice.box
        left=max(0,card.left+5);right=min(1280,card.left+card.width-5)
        if right-left<60:
            continue
        line=op.read_line((left/1280,533/720,right/1280,566/720),snapshot=False).source
        observed=tuple(sorted((p for p in paths if p in line),key=line.index))
        choice.paths=observed
        if kind=='equation' and len(observed)==2:
            items=op.read_region((left/1280,369/720,right/1280,402/720),snapshot=False)
            pairs=re.findall(r'(\d+)\s*/\s*(\d+)',' '.join(x.source for x in sorted(items,key=lambda b:b.left)))
            if len(pairs)==2 and all(1<=int(need)<=20 for _,need in pairs):
                choice.requirements=tuple((path,int(pair[1])) for path,pair in zip(observed,pairs))


def star_station_order(active):
    # Rank-dependent routes have different first-boss node numbers. A
    # confirmed boss reward, not a fixed node index, switches the strategy.
    if not active.get('star',{}).get('boss_rewards_seen'):
        return ['战斗','奖励','事件','财富','商店','铸造','休整','精英','异常']
    star=active.get('star',{})
    primary=next(iter(star.get('loadout',{}).get('core_equations',())),None)
    held=primary and any(c.get('kind')=='equation' and c.get('title')==primary for c in star.get('choices',()))
    needs=equation_requirements(primary,star.get('observed_equation_requirements'),star.get('threshold'))
    counts=star.get('path_counts')
    missing=sum(max(0,needed-counts.get(path,0)) for path,needed in needs.items()) if counts and needs else None
    if not star.get('weighted_equipment') and not (held and missing is not None and 1<=missing<=3):
        # Do not postpone every weighted curio until the primary equation is
        # fully built. Keep ordinary rewards first when only a few blessings
        # are missing; otherwise obtain the first equipment opportunity.
        return ['铸造','战斗','奖励','财富','事件','商店','休整','精英','异常']
    if held and (not counts or not needs or any(counts.get(path,0)<needed for path,needed in needs.items())):
        # Finding the golden equation alone gives no power. Ordinary fights
        # supply the missing blessings; passive shop visits currently do not.
        return ['战斗','奖励','财富','铸造','事件','商店','休整','精英','异常']
    # Observed forge rooms offer weighted equipment, not equation rewriting.
    # Once the first item is equipped, collect blessings/funds for the next
    # boss workshop. The late >=3 forge rule separately obtains slot two.
    return ['战斗','奖励','财富','铸造','事件','商店','休整','精英','异常']


def campaign_summary(history, target=10, required=11, unconfirmed=()):
    """Count actual target-rank wins, never starts or config target values."""
    unique = {}
    for run in [*history,*unconfirmed]:
        if run.get('star') and run.get('id'):
            unique.setdefault(run['id'], run)
    target_runs = [r for r in unique.values() if verified_star_rank(r['star']) == target]
    wins = [r for r in target_runs if r.get('settlement_observed') is True
            and r.get('result') == 'win' and r['star'].get('rank_screenshot')
            and len(set(r['star'].get('members', ()))) == 4
            and r['star'].get('mode') == '拓星模式' and r['star'].get('team_screenshot')
            and r['star'].get('guide_signature') and r['star'].get('policy_signature')]
    cohorts = {}
    attempts = {}
    winning_ids = {run['id'] for run in wins}
    for run in target_runs:
        proof = run.get('execution', {})
        builds = proof.get('worker_builds', [])
        if (proof.get('tracked_from_start') is not True or proof.get('disk_changed') is not False
                or proof.get('policy_corrected_during_run')
                or proof.get('development_inspection')
                or len(builds) != 1 or not builds[0] or not run['star'].get('policy_signature')):
            continue
        key = run['star']['policy_signature'] + ':' + builds[0]
        attempts[key] = attempts.get(key, 0) + 1
        if run['id'] in winning_ids:
            cohorts.setdefault(key,[]).append(run['id'])
    qualifying = max(cohorts.values(),key=len,default=[])
    return dict(target=target, target_kind='star_rank', required=required,
                unverified_rank_runs=sum(verified_star_rank(r['star']) is None for r in unique.values()),
                observed_target_runs=len(target_runs),
                wins=len(wins), nonwins=len(target_runs) - len(wins),
                achieved=len(qualifying) >= required, qualifying_wins=len(qualifying),
                winning_run_ids=[r['id'] for r in wins],cohort_wins={key:len(value) for key,value in cohorts.items()},
                cohort_attempts=attempts,
                cohort_success_rates={key:len(cohorts.get(key,[]))/count for key,count in attempts.items()},
                unqualified_wins=len(wins)-sum(map(len,cohorts.values())))
