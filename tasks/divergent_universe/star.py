"""Detected entry preparation for DU star-rank progression.

Preparations use native controls and never launch an unverified difficulty or
replace a retained exploration. Rank results will require game observations.
"""
import re
import json
import struct
import hashlib
import time
import shutil
from pathlib import Path
import cv2
import numpy as np

from module.base.timer import Timer
from module.base.utils import save_image
from module.exception import RequestHumanTakeover
from tasks.currency_wars.operator import normalize
from tasks.divergent_universe.entry import EntrySettings
from tasks.character.switch import OcrCharacterName


class StarCharacterName(OcrCharacterName):
    def after_process(self,result):
        # DU trial badges can merge with the name (白厄试用/阿格莱雅试用).
        value=re.sub(r'试用\s*$','',result)
        if value=='昔连':
            value='昔涟'  # Observed in the actual world HUD, not a fuzzy match.
        return super().after_process(value)


def missing_world_health_bars(image):
    """Find missing health-bar cues; the device determines actual eligibility."""
    visible=[]
    for index in range(4):
        y=193+78*index
        edges=image[[y-1,y+2],1072:1092].astype(int)
        visible.append(bool((np.max(np.abs(edges-np.array([47,63,63])),axis=2)<=12).mean()>.80))
    return tuple(i+1 for i,shown in enumerate(visible) if not shown) if any(visible) else None


class StarPreparation:
    def __init__(self, main):
        self.main = main
        self.op = main.op

    def observe(self, name):
        folder = Path(__file__).resolve().parents[2] / 'log/divergent_universe' / self.main.config.config_name
        folder.mkdir(parents=True, exist_ok=True)
        save_image(self.op.image, folder / f'star_{name}.png')
        return folder / f'star_{name}.png'

    def begin_run(self):
        """Bind real team/rank observations to one deterministic policy."""
        from tasks.divergent_universe.star_team import StarTeam, TeamMismatch
        from tasks.divergent_universe.star_policy import loadout_from_guide, verified_start, verified_secondary_equations
        main = self.main
        if not main.active and main.progress.data.get('recovery'):
            # A failed pre-run login can leave the client on its startup
            # screen. Use the normal bounded entry route before menu setup.
            main.go_to_lobby()
        key = main.config.DivergentUniverse_StarStrategy
        data = json.loads((Path(__file__).parent/'star_guides.json').read_text('utf-8'))
        guide = next(g for g in data['guides'] if g['key'] == key)
        # Team variants may reuse an unchanged imported guide. The code hash
        # is still checked below; actual member verification remains separate.
        import_key=guide.get('import_key',key)
        proof_path = (Path(__file__).resolve().parents[2]/'log/divergent_universe'/
                      main.config.config_name/f'star_guide_details_{import_key}.json')
        if not proof_path.exists():
            self.import_guide(dict(guide,key=import_key))
        imported = json.loads(proof_path.read_text('utf-8'))
        signature = hashlib.sha256(guide['code'].encode()).hexdigest()
        if not imported.get('import_verified') or imported.get('guide_signature') != signature:
            raise RequestHumanTakeover('攻略导入回读证据与当前策略不一致')
        try:
            team = StarTeam(self).verify_team(guide)
        except TeamMismatch:
            team = StarTeam(self).set_team(guide)
        rank = self.open_entry()
        if rank['mode'] != '拓星模式':
            raise RequestHumanTakeover('当前不是已选中的拓星模式，未开始')
        loadout = loadout_from_guide(guide, imported)
        rank_path = self.observe('launch_rank')
        observation = dict(rank, members=team['members'], guide_signature=signature,
                           guide_policy_applied=True, team_screenshot=team['screenshot'],
                           rank_screenshot=str(rank_path))
        star = verified_start(loadout, observation)
        star['secondary_equation_evidence']=verified_secondary_equations(guide,imported)
        star.update(member_ids=team['member_ids'], member_screenshots=team['member_screenshots'],
                    guide_import_screenshot=imported['screenshot'],
                    guide_application='production selection policy; in-game guide is a reference/favorite',
                    loadout=dict(candidate=loadout.candidate,team=list(loadout.team),guide_code=loadout.guide_code,
                                 core_equations=list(loadout.core_equations),
                                 survival_blessings=list(loadout.survival_blessings),revision=loadout.revision),
                    choices=[])
        # This actual page offers a new exploration, not retained progress.
        # Preserve the obsolete local run and its recovery state as unconfirmed.
        if main.progress.data.get('active'):
            main.progress.data['active']['superseded_recovery'] = main.progress.data.get('recovery')
            main.progress.supersede('Verified fresh star entry while preparing the newly authorized campaign')
        main.progress.data.pop('recovery',None)
        main.active = main.progress.begin('star','standard')
        folder = proof_path.parent/'star_runs'/main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        for field in ('team_screenshot','rank_screenshot','guide_import_screenshot'):
            source = Path(star[field])
            target = folder/source.name
            shutil.copy2(source,target)
            star[field] = str(target)
            if field == 'rank_screenshot' and star.get('star_rank_evidence'):
                star['star_rank_evidence']['entry_screenshot'] = str(target)
            if field == 'guide_import_screenshot' and star.get('secondary_equation_evidence'):
                star['secondary_equation_evidence']['screenshot'] = str(target)
        member_proofs = []
        for source in set(star['member_screenshots']):
            target = folder/Path(source).name
            shutil.copy2(source,target)
            member_proofs.append(str(target))
        star['member_screenshots'] = member_proofs
        (folder/'preparation.json').write_text(json.dumps(star,ensure_ascii=False,indent=2),encoding='utf-8')
        main.active['star'] = star
        main.star_loadout = loadout
        main._entry_prepared = True
        main._run_deadline = time.monotonic()+max(1,main.config.DivergentUniverse_MaxMinutes)*60
        main.op.deadline = main._run_deadline
        main.progress.save('star_prepared')
        main.progress.record('star_prepared',threshold=rank['threshold'],candidate=key,
                             members=team['members'],policy_signature=loadout.signature,
                             rank_title=star['rank_title'],star_rank=star['star_rank'],
                             star_rank_evidence=star['star_rank_evidence'])
        return star

    def read_rank(self):
        op = self.op
        if not op.text('星阶模式', (0.035, 0.035, 0.24, 0.095), exact=True):
            return None
        label = op.text('阈值协议', (0.31, 0.78, 0.70, 0.86))
        if not label:
            return None
        match = re.search(r'阈值协议\D*(10|[1-9])(?!\d)', normalize(label.source))
        if not match:
            # The red rank digit is a separate text item from its label;
            # detection can omit it. Read this observed numeric field alone.
            numbers = [normalize(b.source) for b in op.read_region((.515,.765,.57,.86),snapshot=False)
                       if re.fullmatch(r'10|[1-9]',normalize(b.source))]
            value = numbers[0] if len(numbers)==1 else normalize(
                op.read_line((665/1280,569/720,711/1280,608/720),snapshot=False).source)
            match = re.fullmatch(r'(10|[1-9])', value)
            if not match:
                return None
        title = op.read_line((0.40, 0.535, 0.61, 0.59), snapshot=False).source
        selected = (op.text('拓星模式', (.32,.118,.49,.166), exact=True)
                    and (op.image[88:94,409:625].mean(axis=2)>210).mean() > .8)
        return {'threshold': int(match[1]), 'title': title, 'observed_text': label.source,
                'mode': '拓星模式' if selected else '练习模式'}

    def inspect_progression(self):
        """Inspect the actual campaign growth board from a confirmed hub."""
        op=self.op
        op.snapshot()
        if not op.text('灵感回路',(.03,.03,.34,.13),exact=True):
            if not self.main.lobby_visible():
                raise RequestHumanTakeover('成长检查只在已确认入口执行，保留当前探索')
            button=op.text('灵感回路',(.03,.36,.20,.46),exact=True)
            if not button:
                raise RequestHumanTakeover('未识别灵感回路入口')
            op.click_box(button)
            op.wait_until(lambda:op.text('灵感回路',(.03,.03,.34,.13),exact=True),timeout=15)
        self.main.wait_until_stable((40,100,1240,650));op.snapshot()
        path=self.observe('progression')
        labels=[dict(text=b.source,box=b.button) for b in op.read_region((.02,.015,.98,.95),snapshot=False)]
        path.with_suffix('.json').write_text(json.dumps(labels,ensure_ascii=False,indent=2),encoding='utf-8')
        return dict(page='progression',screenshot=str(path),labels=labels)

    def inspect_run_inventory(self):
        from tasks.divergent_universe.star_inventory import StarInventory
        return StarInventory(self.main).read()

    def prepare_combat_opener(self):
        """Use SRC's selected-character check and switch before normal attacks."""
        from tasks.character.switch import CharacterSwitch,OCR_MAP_CHARACTERS
        from tasks.character.keywords import KEYWORDS_CHARACTER_LIST,CharacterList
        from module.base.utils import area_center
        from module.ocr.ocr import BoxedResult,OcrResultButton
        main,op=self.main,self.op
        target={'phainon':KEYWORDS_CHARACTER_LIST.Cyrene,
                'aglaea':KEYWORDS_CHARACTER_LIST.Aglaea,
                'aglaea_sustain':KEYWORDS_CHARACTER_LIST.Aglaea,
                'followup':KEYWORDS_CHARACTER_LIST.Feixiao,
                'followup_fuxuan':KEYWORDS_CHARACTER_LIST.Feixiao,
                'dot':KEYWORDS_CHARACTER_LIST.Hysilens,
                'dot_blackswan':KEYWORDS_CHARACTER_LIST.Hysilens}.get(main.star_loadout.candidate)
        if target is None or not main.world_visible():
            return False
        switch=CharacterSwitch(config=main.config,device=main.device)
        deadline=time.monotonic()+8
        class SwitchInterrupted(Exception):
            pass
        def actual_world():
            op.image=main.device.image
            op._ocr_cache.clear();op.frame_cache.clear()
            op.check()
            if time.monotonic()>=deadline or not main.world_visible():
                raise SwitchInterrupted
            return True
        switch.is_in_main=actual_world
        native_selected=switch._update_current_character
        used_skill_cue=False
        def current_character():
            nonlocal used_skill_cue
            actual_world()
            selected=native_selected()
            if len(selected)<=1:
                return selected
            # DU can produce two native highlight peaks. Do not let that
            # cancel selection immediately. A real character-specific world
            # skill icon resolves the target; otherwise native switch clicks
            # the already-recognized character button and checks again.
            cue=op.templates/f'star_active_{target.name}.png'
            if cue.exists() and op.template_matches(str(cue),
                    (865/1280,580/720,960/1280,670/720),confidence=.94,scales=(1.0,)):
                used_skill_cue=True
                return [switch.characters.index(target)+1]
            return []
        switch._update_current_character=current_character
        verified=False
        reason='character_not_detected'
        try:
            buttons=StarCharacterName(OCR_MAP_CHARACTERS).matched_ocr(main.device.image,keyword_classes=CharacterList)
            expected=main.active['star']['member_ids']
            buttons=[b for b in buttons if b.matched_keyword.id in expected]
            for button in switch._iter_character_by_avatar():
                if (button.matched_keyword.id in expected
                        and button.matched_keyword not in [b.matched_keyword for b in buttons]):
                    buttons.append(button)
            for character in (KEYWORDS_CHARACTER_LIST.Cyrene, KEYWORDS_CHARACTER_LIST.Feixiao):
                if character.id not in expected or character.id in [b.matched_keyword.id for b in buttons]:
                    continue
                # The native detector can drop a complete short name. Use
                # only a validated HUD portrait in its verified team slot;
                # other party faces are negative fixtures for each template.
                slot=expected.index(character.id)
                top=138+78*slot
                matches=op.template_matches(str(op.templates/f'star_world_{character.name}.png'),
                    (1155/1280,top/720,1245/1280,(top+76)/720),confidence=.94,scales=(1.0,))
                if matches:
                    match=max(matches,key=lambda b:b.score)
                    result=BoxedResult(box=match.button,text_img=None,ocr_text=character.cn,score=match.score)
                    buttons.append(OcrResultButton(boxed_result=result,matched_keyword=character))
                    main.progress.record('star_world_character_avatar',character=character.cn,slot=slot+1,score=match.score)
            switch.character_buttons=sorted(buttons,key=lambda b:area_center(b.area)[1])
            switch.characters=[b.matched_keyword for b in switch.character_buttons]
            # The native switch uses list position as the physical slot. Do
            # not compress a missing first trial character into three slots.
            if [c.id for c in switch.characters]==main.active['star']['member_ids'] and target in switch.characters:
                verified=switch.character_switch(target)
                reason='selected' if verified else 'native_switch_not_confirmed'
        except SwitchInterrupted:
            reason='page_changed_or_switch_budget'
        op.image=main.device.image
        op._ocr_cache.clear();op.frame_cache.clear()
        if verified and not main.world_visible():
            verified=False
            reason='page_changed_before_verification'
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'opener_{main.active.get("node",0)}_{main.active.get("battles",0)}.png'
        save_image(op.image,path)
        proof=dict(character=target.cn,verified=bool(verified),reason=reason,
                   node=main.active.get('node'),battle_index=main.active.get('battles',0),screenshot=str(path),
                   observed_ids=[c.id for c in switch.characters],skill_cue_verified=used_skill_cue)
        main.active['star'].setdefault('combat_openers',[]).append(proof)
        main.progress.record('star_combat_opener',**proof)
        main.progress.save('star_combat_opener')
        return verified

    def restore_party_before_boss(self):
        """Reach a real revival device before attacking with fallen members."""
        main,op=self.main,self.op
        if main.active.get('station')!='首领' or not main.world_visible():
            return False
        missing=missing_world_health_bars(op.image)
        if not missing:
            return False
        op.snapshot()
        if not main.world_visible() or missing_world_health_bars(op.image)!=missing:
            return False
        node=str(main.active.get('node',0))
        state=main.active['star'].setdefault('revivals',{}).setdefault(node,dict(scans=0,moves=0))
        if state.get('unavailable') or state.get('checked_no_targets'):
            return False
        main.progress.record('star_health_bars_missing',slots=list(missing))
        for _ in range(20):
            op.snapshot()
            if main.is_combat_executing():
                return False
            if not main.world_visible():
                break
            prompt=op.text('复活装置',(.58,.48,.92,.70),exact=True)
            if prompt and main.interact_with_label(prompt,interval=2):
                state['opened']=True
                main.progress.save('star_revival_opening')
                break
            target=op.text('复活装置',(.03,.15,.90,.48),exact=True)
            if target and state['moves']<12:
                state['moves']+=1
                main.progress.save('star_revival_approach')
                main.move(main.event_direction(target),.5,run=False,interaction_text=('复活装置',))
            elif state['scans']<6:
                state['scans']+=1
                main.progress.save('star_revival_search')
                main.rotation_swipe(45,box=main.ROTATION_BOX)
            else:
                state['unavailable']=True
                # A missing bar is an observation to inspect at the device,
                # not sufficient evidence to abandon a retained exploration.
                main.progress.save('star_revival_unavailable')
                return False
        if state.get('opened'):
            op.wait_until(self.revival_page_visible,timeout=12,name='角色重置页面')
            main.wait_until_stable((200,90,1100,650));op.snapshot()
            return self.handle_revival_page()
        return False

    def revival_page_visible(self):
        return bool(self.op.text('角色重置',(.035,.035,.25,.10),exact=True)
                    and self.op.text('选择无法战斗的角色',(.63,.34,.97,.42)))

    def handle_revival_page(self):
        from tasks.divergent_universe.star_revival import StarRevival
        return StarRevival(self).run()

    def open_run_guide(self):
        """Reach the observed in-run guide control before the first equation."""
        op=self.op
        op.snapshot()
        if op.text('更换编队',(.16,.12,.32,.20),exact=True):
            return self.keep_run_team()
        if op.text('确定应用',(.54,.70,.75,.80),exact=True):
            return self.confirm_run_guide()
        if self.imported_details_visible() and op.text('取消应用',(.75,.80,.91,.88),exact=True):
            return self.verify_run_guide()
        if not self.imported_details_visible():
            if not op.text('攻略推荐',(.04,.035,.23,.10),exact=True):
                control=op.wait_until(lambda:op.text('局内攻略',(.025,.11,.16,.18),exact=True),
                                      timeout=15,name='首个方程页局内攻略入口')
                op.click_box(control)
                op.wait_until(lambda:op.text('攻略推荐',(.04,.035,.23,.10),exact=True),
                              timeout=15,name='局内攻略页面')
            favorite=op.wait_until(lambda:op.text('收藏',(.61,.11,.78,.17),exact=True),timeout=15)
            op.click_box(favorite)
            codes=op.wait_until(lambda:op.text('攻略码',(.24,.19,.39,.25)),timeout=15,name='收藏攻略码分页')
            op.click_box(codes)
            op.wait_until(lambda:op.text('来自攻略码的方案',(.04,.27,.47,.79)),timeout=15,name='已收藏攻略码列表')
            self.main.wait_until_stable((50,150,1220,625));op.snapshot()
            core=self.main.star_loadout.core_equations[0]
            row=self.find_favorite_guide(core)
            op.click_box(row)
            op.wait_until(self.imported_details_visible,timeout=15,name='局内攻略详情')
            self.main.wait_until_stable((100,120,1180,640));op.snapshot()
        path=self.observe('run_guide_page')
        path.with_suffix('.json').write_text(json.dumps([dict(text=b.source,box=b.button)
            for b in op.read_region((.03,.15,.97,.91),snapshot=False)],ensure_ascii=False,indent=2),encoding='utf-8')
        guides=json.loads((Path(__file__).parent/'star_guides.json').read_text('utf-8'))['guides']
        guide=next(g for g in guides if g['key']==self.main.star_loadout.candidate)
        self.read_guide_details(guide)
        button=op.wait_until(lambda:op.text('应用方案',(.75,.80,.91,.88),exact=True),timeout=15)
        op.click_box(button)
        op.wait_until(lambda: not op.text('应用方案',(.75,.80,.91,.88),exact=True),timeout=15,name='应用局内方案响应')
        op.wait_until(lambda:op.text('确定应用',(.54,.70,.75,.80),exact=True)
                      or op.text('更换编队',(.16,.12,.32,.20),exact=True)
                      or op.text('取消应用',(.75,.80,.91,.88),exact=True),timeout=15,name='攻略应用下一步骤')
        return self.open_run_guide()

    def find_favorite_guide(self, core):
        """Six favorite slots may put the third row's label below the viewport."""
        op = self.op
        for attempt in range(3):
            op.snapshot()
            if (self.imported_details_visible()
                    or not op.text('攻略推荐', (.04,.035,.23,.10), exact=True)
                    or not op.text('攻略码', (.24,.19,.39,.25))):
                raise RuntimeError('收藏攻略列表已离页，停止滚动')
            row = op.text(core, (.03,.28,.86,.875), exact=True)
            if row:
                return row
            if attempt < 2:
                op.check()
                self.main.device.swipe((1120, 590), (1120, 380))
                self.main.wait_until_stable((40,200,1230,630))
        self.observe('favorite_guide_missing')
        raise RuntimeError('有限滚动后仍未找到指定核心方程攻略')

    def confirm_run_guide(self):
        op=self.op
        if not op.text('未拥有该方案推荐的方程和加权奇物',(.33,.34,.70,.41)):
            raise RequestHumanTakeover('攻略应用条件与已观察提示不一致，保留原局')
        button=op.text('确定应用',(.54,.70,.75,.80),exact=True)
        if not button:
            raise RequestHumanTakeover('未核对到确定应用按钮')
        op.click_box(button)
        op.wait_until(lambda:op.text('更换编队',(.16,.12,.32,.20),exact=True)
                      or op.text('取消应用',(.75,.80,.91,.88),exact=True),
                      action=lambda:op.click_text('确定应用',(.54,.70,.75,.80),exact=True,interval=3),
                      timeout=20,name='游戏攻略应用结果')
        if op.text('更换编队',(.16,.12,.32,.20),exact=True):
            return self.keep_run_team()
        return self.verify_run_guide()

    def keep_run_team(self):
        op=self.op
        keep=op.wait_until(lambda:op.text('不更换编队',(.64,.25,.80,.32),exact=True),
                           timeout=12,name='保留当前编队按钮')
        self.observe('guide_keep_verified_team')
        op.click_box(keep)
        op.wait_until(lambda: self.main.selection_kind()=='equation'
                      or op.text('取消应用',(.75,.80,.91,.88),exact=True),
                      action=lambda:op.click_text('不更换编队',(.64,.25,.80,.32),exact=True,interval=3),
                      timeout=20,name='保留阵容并应用攻略')
        self.main.wait_until_stable((40,80,1240,650));op.snapshot()
        path=self.observe('run_guide_final_response')
        self.main.progress.record('star_run_guide_team_kept',screenshot=str(path),members=self.main.active['star']['members'])
        self.main.progress.save('star_run_guide_verification_pending')
        return self.verify_run_guide()

    def verify_run_guide(self):
        op=self.op
        op.wait_until(lambda:op.text('取消应用',(.75,.80,.91,.88),exact=True),timeout=15,name='攻略已应用标记')
        guides=json.loads((Path(__file__).parent/'star_guides.json').read_text('utf-8'))['guides']
        guide=next(g for g in guides if g['key']==self.main.star_loadout.candidate)
        exported=self.read_guide_details(guide)
        path=self.observe('run_guide_verified')
        folder=path.parent/'star_runs'/self.main.active['id'];folder.mkdir(parents=True,exist_ok=True)
        saved=folder/'guide_applied.png';shutil.copy2(path,saved)
        star=self.main.active['star']
        star.update(run_guide_verified=True,run_guide_screenshot=str(saved),
                    run_guide_exported_signature=exported['exported_signature'],
                    guide_application='game applied code and production policy; retained verified team')
        self.main.progress.record('star_run_guide_verified',screenshot=str(saved),code_signature=star['guide_signature'])
        self.main.progress.save('star_guide_applied')
        op.wait_until(lambda:self.main.selection_kind()=='equation',action=self.entry_back,
                      timeout=20,name='已应用攻略返回方程选择')
        return {'applied':True,'team_kept':True,'screenshot':str(saved)}

    def entry_back(self):
        if self.op.back():
            return True
        # The bright mode picker uses the observed black variant of the
        # native return icon; use it only while on a known entry page.
        control = (self.op.template('star_back_dark', (0.93, 0, 1, 0.11), confidence=0.94)
                   or self.op.template('star_guide_close', (0.86, 0, 0.99, 0.17), confidence=0.94))
        return self.op.click_box(control, interval=3)

    def return_to_hub(self):
        op = self.op
        timeout = Timer(45, count=3).start()
        closed_page = None
        seen_page = None
        page_frames = hub_frames = 0
        while not timeout.reached():
            op.snapshot()
            if self.main.lobby_visible():
                hub_frames += 1
                if hub_frames >= 2:
                    return
                continue
            hub_frames = 0
            if self.main.world_visible() or self.main.is_combat_executing():
                raise RequestHumanTakeover('准备操作遇到进行中的探索，保留原局停止')
            if self.main.is_in_main():
                self.main.go_to_lobby()
                closed_page = seen_page = None
                page_frames = 0
                continue
            page = 'guide_details' if self.imported_details_visible() else next(
                (label for label in ('攻略推荐', '星阶模式', '模式选择', '常规演算', '周期演算', '灵感回路')
                 if op.text(label, (0.03, 0.03, 0.38, 0.14))), None)
            if page is None and op.text('开始「货币战争」',(.56,.83,.98,.96),exact=True):
                page = 'currency_entry'
            page_frames = page_frames + 1 if page and page == seen_page else 1
            seen_page = page
            # CLOSE can queue while the old page is still drawn. After one
            # successful input, require a different observed page before any
            # further close, even if the old native click interval elapsed.
            if page and page != closed_page and page_frames >= 2 and self.entry_back():
                closed_page = page
        self.observe('return_hub_timeout')
        if closed_page is not None:
            raise RuntimeError('已知准备菜单返回后未确认入口，交由有界恢复')
        raise RequestHumanTakeover('未能从已知准备菜单返回入口')

    def open_entry(self):
        """Reach the star entry via detected controls without starting a run."""
        main, op = self.main, self.op
        op.snapshot()
        if op.text('角色列表', (.045,.10,.18,.16), exact=True):
            # The editor holds the selected draft. Back would discard it.
            op.wait_until(lambda: self.read_rank(),
                          action=lambda: op.click_text('进入星阶模式', (.70,.84,.98,.96), interval=3),
                          timeout=30, name='保留下载阵容进入星阶')
            self.observe('entry')
            return self.read_rank()
        if self.imported_details_visible() or op.text('攻略推荐', (0.03, 0.03, 0.38, 0.14)):
            self.return_to_hub()
        if not op.text('星阶模式', (0, 0, 0.48, 0.22)):
            main.go_to_lobby()
            op.snapshot()
            if main.world_visible() or main.is_combat_executing() or main.selection_kind():
                raise RequestHumanTakeover('已有探索仍在进行；拓星准备保留原局，等待本局结算')
            launch = EntrySettings(main).launch_button()
            if launch and '继续进度' in normalize(launch.source):
                raise RequestHumanTakeover('入口仍有可继续进度；拓星准备不会覆盖原局')
            EntrySettings(main).prepare('standard')
        timeout = Timer(45, count=3).start()
        while not timeout.reached():
            op.snapshot()
            if main.world_visible():
                raise RequestHumanTakeover('拓星准备意外进入探索，保留现场并停止')
            # The actual mode heading plus a rank label are required; the
            # normal difficulty V screen is not proof of star-rank readiness.
            rank = self.read_rank()
            if rank:
                self.observe('entry')
                return rank
            button = op.text('进入星阶模式', (0.30, 0.65, 0.99, 0.97), exact=True)
            if button:
                op.click_box(button, interval=3)
                continue
            # Entry fades before its rank labels appear. Poll fresh frames
            # within this budget rather than rejecting the first dark frame.
        self.observe('entry_timeout')
        raise RequestHumanTakeover('星阶入口未在限定时间内确认')

    def open_guides(self):
        """Find the in-game guide page from known entry pages, without launch."""
        op = self.op
        timeout = Timer(50, count=3).start()
        while not timeout.reached():
            op.snapshot()
            if self.main.world_visible() or self.main.is_combat_executing():
                raise RequestHumanTakeover('攻略准备遇到进行中的探索，保留原局停止')
            if op.text(('攻略推荐', '攻略广场', '我的攻略', '攻略详情', '攻略大全'), (0.02, 0.015, 0.96, 0.20)):
                self.observe('guides')
                return {'page': 'guides', 'labels': [b.source for b in op.read_region((0, 0, 1, 0.94), snapshot=False)]}
            button = op.text(('攻略大全', '差分宇宙攻略', '攻略'), (0.01, 0.08, 0.30, 0.75), exact=True)
            if button:
                op.click_box(button, interval=3)
                continue
            if (op.text('星阶模式', (0, 0, 0.48, 0.22))
                    or EntrySettings(self.main).launch_button()
                    or any(name in self.main.header_text() for name in ('模式选择', '常规演算', '周期演算'))):
                self.entry_back()
                continue
            # The hub layout is a prerequisite. Save its actual labels/icons
            # before implementing an icon-only control; never guess its point.
            # A faded transition can temporarily expose only the UID. Wait
            # for detected controls within the page budget, without clicks.
        path = self.observe('guide_hub')
        labels = [dict(text=b.source, box=b.button) for b in op.read_region((0, 0, 1, 0.94), snapshot=False)]
        path.with_suffix('.json').write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding='utf-8')
        raise RequestHumanTakeover('攻略页面未在限定时间内出现')

    def open_import(self):
        op = self.op
        op.snapshot()
        clipboard_prompt = op.text('请求从剪切板粘贴', (0.23, 0.35, 0.80, 0.60))
        existing_input = op.text('攻略码', (0.23, 0.19, 0.80, 0.67))
        if not clipboard_prompt and not existing_input:
            self.open_guides()
        def ready():
            return (not op.text('请求从剪切板粘贴', (0.23, 0.35, 0.80, 0.60))
                    and op.text('攻略码', (0.23, 0.19, 0.80, 0.67)))
        def advance():
            if op.text('请求从剪切板粘贴', (0.23, 0.35, 0.80, 0.60)):
                # This workflow supplies the explicit selected code itself;
                # do not let the game consume an unrelated device clipboard.
                return op.click_text('不粘贴', (0.25, 0.60, 0.48, 0.70), exact=True)
            return op.click_text('输入攻略码', (0.70, 0.02, 0.85, 0.09), exact=True, interval=3)
        op.wait_until(ready, action=advance,
                      timeout=20, name='攻略码输入对话框')
        self.observe('guide_import')
        return {'page': 'guide_import', 'labels': [dict(text=b.source, box=b.button)
                for b in op.read_region((0.15, 0.15, 0.88, 0.85), snapshot=False)]}

    def import_guide(self, guide):
        from tasks.divergent_universe.star_policy import validate_guide_code
        code = validate_guide_code(guide['code'])
        op = self.op
        op.snapshot()
        if self.imported_details_visible():
            return self.read_guide_details(guide)
        self.open_import()
        paste = op.template('star_guide_paste', (0.78, 0.43, 0.85, 0.56), confidence=0.94)
        if not paste:
            self.observe('guide_missing_paste')
            raise RequestHumanTakeover('没有识别到攻略输入框的粘贴按钮')
        # SRC's redemption-code workflow uses this native clipboard backend.
        # Whole-string paste avoids losing initial characters during the
        # text-field focus animation, and replaces the previous field value.
        self.main.device.u2.set_clipboard(code)
        op.click_box(paste)
        paste_attempts = 1
        submitted = False
        def imported():
            # The compressed code contains build data, not the author's
            # accompanying display title. Do not wait for that external title.
            return self.imported_details_visible()
        def confirm():
            nonlocal paste_attempts, submitted
            if op.text('请求从剪切板粘贴', (0.23, 0.35, 0.80, 0.60)):
                # Clipboard now contains only this validated requested code.
                return op.click_text('粘贴', (0.53, 0.60, 0.77, 0.70), exact=True)
            if submitted and op.text(('攻略码无效', '攻略码错误', '攻略不存在', '无法识别攻略码'),
                                     (0.18, 0.15, 0.90, 0.80)):
                raise RequestHumanTakeover('游戏拒绝该攻略码，不能标记为已应用')
            if op.text('输入攻略码', (0.32, 0.20, 0.69, 0.32)):
                prefix = normalize(op.read_line((0.165, 0.36, 0.33, 0.42), snapshot=False).source)
                if not prefix.startswith('DIV'):
                    # The permission dialog can consume the first paste tap.
                    # Retry the observed paste control, never submit old text.
                    if paste_attempts >= 3:
                        raise RequestHumanTakeover('未在攻略输入框确认完整DIV前缀，停止提交旧内容')
                    if op.click_box(op.template('star_guide_paste', (0.78, 0.43, 0.85, 0.56), confidence=0.94), interval=3):
                        paste_attempts += 1
                    return
                if op.click_text('确认', (0.54, 0.68, 0.78, 0.78), exact=True, interval=3):
                    submitted = True
        try:
            op.wait_until(imported, action=confirm, timeout=25, name='导入攻略详情')
        except Exception:
            self.observe('guide_import_result')
            raise
        return self.read_guide_details(guide)

    def imported_details_visible(self):
        return (self.op.text('来自攻略码的方案', (0.12, 0.065, 0.50, 0.16))
                and self.op.text('核心方程', (0.09, 0.16, 0.28, 0.23)))

    def read_guide_details(self, guide):
        import hashlib
        from tasks.divergent_universe.star_policy import guide_codes_equivalent, validate_guide_code
        op = self.op
        if not self.imported_details_visible():
            raise RequestHumanTakeover('没有可确认的已导入攻略详情页')
        # Clear only this workflow's emulator clipboard before asking the
        # game to copy its current guide, so a swallowed tap cannot echo the
        # code we previously supplied and falsely prove a successful import.
        self.main.device.u2.set_clipboard('')
        copied = op.click_text('复制攻略码', (0.095, 0.81, 0.29, 0.88), exact=True)
        if not copied:
            raise RequestHumanTakeover('没有识别到攻略详情的复制控件')
        observed = None
        def exported():
            nonlocal observed
            value = self.game_clipboard()
            if 'DIV##' not in value:
                return False
            observed = validate_guide_code(value)
            return True
        op.wait_until(exported, timeout=10, name='游戏导出攻略码')
        if not guide_codes_equivalent(guide['code'], observed):
            path = self.observe('guide_export_comparison')
            path.with_suffix('.json').write_text(json.dumps(
                {'requested': guide['code'], 'game_exported': observed}, ensure_ascii=False, indent=2), encoding='utf-8')
            raise RequestHumanTakeover('游戏当前导出的攻略码与指定方案不一致，不能作为配置完成')
        path = self.observe('guide_details_' + guide['key'])
        result = {'page': 'guide_details', 'candidate': guide['key'],
                  'guide_signature': hashlib.sha256(guide['code'].encode('utf-8')).hexdigest(),
                  'exported_signature': hashlib.sha256(observed.encode('utf-8')).hexdigest(),
                  'import_verified': True, 'applied': False, 'screenshot': str(path),
                  'core_equations': [b.source for b in op.read_region((0.20, 0.23, 0.55, 0.40), snapshot=False)],
                  'labels': [dict(text=b.source, box=b.button)
                             for b in op.read_region((0.09, 0.065, 0.92, 0.90), snapshot=False)]}
        path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    def game_clipboard(self):
        """Read the explicitly copied game code through SRC's scrcpy channel."""
        from module.device.method.scrcpy import const
        device = self.main.device
        device.scrcpy_init()
        control = device._scrcpy_control
        sock = control.control_socket
        with control.control_socket_lock:
            previous_timeout = sock.gettimeout()
            try:
                sock.setblocking(False)
                try:
                    while sock.recv(1024):
                        pass
                except BlockingIOError:
                    pass
                sock.settimeout(3)
                sock.sendall(struct.pack('>B', const.TYPE_GET_CLIPBOARD))
                def receive(length):
                    result = bytearray()
                    while len(result) < length:
                        packet = sock.recv(length - len(result))
                        if not packet:
                            raise ConnectionError('原生剪贴板连接已关闭')
                        result.extend(packet)
                    return bytes(result)
                kind, length = struct.unpack('>BI', receive(5))
                if kind != 0 or length > 16384:
                    raise ValueError('原生剪贴板响应格式错误')
                return receive(length).decode('utf-8')
            finally:
                sock.settimeout(previous_timeout)

    def settle_unverified_setup(self, expected_run, reason='replace_unverified_star_setup'):
        """End only an explicitly identified setup run through real game UI."""
        active = self.main.progress.data.get('active')
        if not expected_run or not active or active['id'] != expected_run:
            raise ValueError('准备阶段待结束的run ID与当前原局不一致')
        if reason not in ('replace_unverified_star_setup','replace_star_candidate'):
            raise ValueError('未知准备结算原因')
        active.update(stop_requested=True, exit_reason=reason)
        self.main.progress.save('setup_settlement_requested')
        self.main.progress.record('setup_settlement_requested', expected_run=expected_run)
        self.main.go_to_lobby()
        result = self.main.play_run()
        self.main.progress.finish(result)
        self.main.progress.save('finished')
        return {'run_id': expected_run, 'result': result, 'real_settlement': True, 'new_run_started': False}

    def open_team(self):
        """Open the observed downloaded-member row, without selecting a preset."""
        self.op.snapshot()
        if (self.op.text('下载角色', (0.13, 0.025, 0.30, 0.095), exact=True)
                and self.op.text('角色列表', (0.045, 0.10, 0.18, 0.16), exact=True)):
            return {'page': 'team_picker', 'members_verified': False}
        if self.op.text('星阶模式', (.035,.035,.24,.095), exact=True):
            self.op.wait_until(lambda: self.op.text('角色列表', (.045,.10,.18,.16), exact=True)
                               or self.op.text('下载角色', (.45,.73,.74,.82)),
                               action=self.entry_back,timeout=15,name='返回下载角色页')
            if self.op.text('角色列表', (.045,.10,.18,.16), exact=True):
                return {'page':'team_picker','members_verified':False}
        if not EntrySettings(self.main).launch_button():
            self.return_to_hub()
        EntrySettings(self.main).prepare('standard')
        op = self.op
        op.snapshot()
        if not op.text('下载角色', (0.45, 0.73, 0.74, 0.82)):
            self.observe('team_entry_missing')
            raise RequestHumanTakeover('常规入口没有识别到下载角色区域')
        image = cv2.cvtColor(op.image[603:696, 594:932], cv2.COLOR_RGB2GRAY)
        circles = cv2.HoughCircles(image, cv2.HOUGH_GRADIENT, dp=1, minDist=54,
                                   param1=100, param2=25, minRadius=22, maxRadius=37)
        if circles is None or len(circles[0]) != 4:
            self.observe('team_row_unrecognized')
            raise RequestHumanTakeover('未核对到四个下载角色槽位，停止猜测点击')
        x, y, _ = sorted(circles[0], key=lambda c: c[0])[0]
        op.click_point((594 + float(x)) / 1280, (603 + float(y)) / 720, tag='DU_STAR_TEAM_EDITOR')
        op.wait_until(lambda: op.text(('预设编队', '试用角色', '角色选择', '队伍预设'),
                                      (0.01, 0.01, 0.99, 0.30)),
                      timeout=20, name='拓星角色选择页')
        path = self.observe('team_picker')
        result = {'page': 'team_picker', 'members_verified': False,
                  'labels': [dict(text=b.source, box=b.button)
                             for b in op.read_region((0, 0, 1, 0.95), snapshot=False)]}
        path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
