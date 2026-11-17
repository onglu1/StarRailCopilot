"""Detected optional workshop access for the star campaign.

Native SRC owns camera, movement and interaction. A workshop attempt never
marks a room or an equation complete; equipment needs its own UI evidence.
"""
from pathlib import Path
import re
import time
import numpy as np

from module.base.utils import save_image
from module.base.timer import Timer
from module.exception import RequestHumanTakeover
from tasks.currency_wars.operator import normalize
from tasks.currency_wars.operator import Box


def parse_rewrite_count(text):
    # A selected blessing previews removal as 4»3/6. The owned count is
    # before the arrow; normal text normalization would concatenate it to 43.
    value=re.sub(r'[^0-9/>»›≫》→⇒]', '',text.replace('O','0').replace('o','0'))
    match=re.fullmatch(r'(\d{1,3})(?:[>»›≫》→⇒]+(\d{1,3}))?/(\d{1,2})',value)
    if not match:
        return None
    have,preview,need=int(match[1]),match[2],int(match[3])
    if not 0<=have<=200 or not 1<=need<=20:
        return None
    if preview is not None and int(preview)!=have-1:
        return None
    return have,need


class StarWorkshop:
    NAMES = ('造物调试台','始生调试台')
    MAX_APPROACH_MOVES = 24
    MAX_SEARCH_TURNS = 8

    def __init__(self, main):
        self.main = main
        self.op = main.op
        self.active = main.active

    def state(self):
        return self.active['star'].setdefault('workshops',{}).setdefault(
            str(self.active.get('node',0)),dict(scans=0,moves=0,done=False))

    def visible(self):
        return bool(self.op.text(self.NAMES+('选择加权奇物','加权奇物','方程覆写','覆写方程','祝福覆写','祝福强化'),
                                 (.025,.015,.55,.13)))

    def save_frame(self, name):
        folder = Path(__file__).resolve().parents[2]/'log/divergent_universe'/self.main.config.config_name/'star_runs'/self.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'workshop_{self.active.get("node",0)}_{name}.png'
        save_image(self.op.image,path)
        return str(path)

    def navigate(self):
        main,op=self.main,self.op
        if self.active.get('stop_requested') or self.active.get('station') not in ('铸造','休整','首领'):
            return False
        if self.active['station']=='首领' and not main._node_done:
            return False
        state=self.state()
        prompt=op.text(self.NAMES,(.58,.48,.92,.70),exact=True)
        if state['done'] and not (prompt and state.get('outcome')=='no_reachable_workshop'):
            return False
        if prompt and main.interact_with_label(prompt,interval=2):
            state['done']=False
            state['entered']=True
            main.progress.save('star_workshop_entering')
            self.wait_for_panel()
            return True
        target=(op.text(self.NAMES,(.035,.15,.88,.46),exact=True)
                or op.text(self.NAMES,(.30,0,.88,.16),exact=True))
        # The X5 boss room can start far across the hall. Twelve native
        # short steps ended with the real target still visible and closer.
        # Allow another bounded approach segment, still stopping on a prompt.
        if target and state['moves']<self.MAX_APPROACH_MOVES:
            state['moves']+=1
            direction=main.event_direction(target)
            state.update(last_direction=float(direction),last_seen=time.monotonic(),occluded_steps=0)
            main.progress.save('star_workshop_approach')
            main.move(direction,.6,run=False,interaction_text=self.NAMES)
            return True
        if (not target and state.get('last_direction') is not None
                and time.monotonic()-state.get('last_seen',0)<6 and state.get('occluded_steps',0)<3):
            # The label can leave the top crop or hide behind the character
            # during the final approach. Retain its observed native heading
            # briefly; every step still stops at an actual interaction prompt.
            state['occluded_steps']=state.get('occluded_steps',0)+1
            main.progress.save('star_workshop_near_approach')
            main.move(state['last_direction'],.3,run=False,interaction_text=self.NAMES)
            return True
        if not target and state['scans']<self.MAX_SEARCH_TURNS:
            state['scans']+=1
            main.progress.save('star_workshop_search')
            main.rotation_swipe(45,box=main.ROTATION_BOX)
            state.pop('last_direction',None)
            return True
        state.update(done=True,outcome='no_reachable_workshop')
        main.progress.record('star_workshop_unavailable',screenshot=self.save_frame('unavailable'),
                             reason='approach_budget_exhausted' if target else 'search_exhausted',
                             moves=state['moves'],scans=state['scans'],
                             target=target.button if target else None)
        main.progress.save()
        return False

    def wait_for_panel(self):
        main,op=self.main,self.op
        requests=1
        adjustments=0
        missing_prompt=Timer(1.5,count=2).start()
        def retry():
            nonlocal requests,adjustments
            if not main.world_visible():
                return
            prompt=op.text(self.NAMES,(.58,.48,.92,.70),exact=True)
            if prompt:
                missing_prompt.reset()
                if requests<3 and main.interact_with_label(prompt,interval=2):
                    requests+=1
                    main.progress.record('star_workshop_interaction_retried',request=requests)
            elif adjustments<2 and missing_prompt.reached():
                target=(op.text(self.NAMES,(.035,.15,.88,.46),exact=True)
                        or op.text(self.NAMES,(.30,0,.88,.16),exact=True))
                if target:
                    # A final walking animation can carry the player just
                    # outside the prompt. Use the current label, not an old
                    # heading, for at most two short native corrections.
                    adjustments+=1
                    main.move(main.event_direction(target),.2,run=False,interaction_text=self.NAMES)
                    main.progress.record('star_workshop_interaction_adjusted',adjustment=adjustments)
                missing_prompt.reset()
        op.wait_until(lambda:not main.world_visible(),action=retry,timeout=15,name='造物台面板打开')

    def handle(self):
        main,op=self.main,self.op
        if not self.active.get('node'):
            return False
        if self.close_reward_overlay():
            return True
        state=self.state()
        if state['done']:
            # Closing the equation page returns to the workshop menu first.
            # Finish that layer too, without setting room completion flags.
            if not main.world_visible() and self.visible():
                return self.close_panel()
            return False
        if op.text('加权奇物',(.035,.035,.25,.10),exact=True):
            return self.equip_weighted()
        if op.text('方程覆写',(.035,.035,.30,.10),exact=True):
            if state.get('rewrite_done'):
                return self.return_to_menu()
            return self.rewrite()
        if op.text('祝福覆写',(.035,.035,.30,.10),exact=True):
            if state.get('blessing_rewrite_done'):
                return self.return_to_menu()
            return self.rewrite_blessings()
        if state.get('entered') and op.text('祝福强化',(.035,.035,.30,.10),exact=True):
            return self.enhance()
        if op.text('选择加权奇物',(.03,.02,.55,.13)):
            self.inspect_open_page('weighted_selector')
        title=op.text(self.NAMES,(.025,.015,.31,.115),exact=True)
        if not title and not main.forge_panel_visible():
            return False
        state['entered']=True
        def current_control():
            control=self.menu_control('选择加权奇物')
            if control:
                return control
            for flag,label in (('rewrite_done','方程覆写'),('blessing_rewrite_done','祝福覆写'),
                               ('enhancement_done','祝福强化')):
                if not state.get(flag):
                    control=self.menu_control(label)
                    if control:
                        return control
            return None
        control=current_control()
        if not control and all(state.get(flag) for flag in ('rewrite_done','blessing_rewrite_done','enhancement_done')):
            return self.close('workshop_actions_finished')
        if not control:
            # The title appears before the translucent menu text finishes
            # rendering. A recognized workshop is not an unknown layout yet.
            try:
                control=op.wait_until(current_control,timeout=8,name='造物台菜单项加载')
            except RuntimeError as error:
                if not str(error).startswith('造物台菜单项加载超时'):
                    raise
                self.inspect_open_page('unknown_panel')
        if control:
            main.progress.record('star_workshop_control',label=control.source,screenshot=self.save_frame('panel'))
            if op.click_box(control,interval=2):
                # A stable black transition is not a loaded function page.
                requests=1
                def retry_visible_control():
                    nonlocal requests
                    if requests>=3 or not op.text(self.NAMES,(.025,.015,.31,.115),exact=True):
                        return
                    current=self.menu_control(control.source)
                    if current and op.click_box(current,interval=2):
                        requests+=1
                        main.progress.record('star_workshop_function_retried',label=control.source,request=requests)
                op.wait_until(lambda:op.text(('方程覆写','祝福覆写','加权奇物','祝福强化'),(.035,.035,.30,.10),exact=True),
                              action=retry_visible_control,timeout=15,name='造物台功能标题出现')
                main.wait_until_stable((40,100,1240,650))
                op.snapshot()
                if op.text('方程覆写',(.035,.035,.30,.10),exact=True):
                    return self.rewrite()
                if op.text('祝福覆写',(.035,.035,.30,.10),exact=True):
                    return self.rewrite_blessings()
                if op.text('加权奇物',(.035,.035,.25,.10),exact=True):
                    return self.equip_weighted()
                if op.text('祝福强化',(.035,.035,.30,.10),exact=True):
                    return self.enhance()
                self.inspect_open_page('opened')
            return True
        self.inspect_open_page('unknown_panel')

    def menu_control(self,names):
        # Read just the three observed title rows. The broad menu crop can
        # merge a title with its icon/description and fail exact matching.
        for top,bottom in ((.16,.22),(.418,.475),(.678,.735)):
            control=self.op.text(names,(.62,top,.95,bottom),exact=True)
            if control:
                return control
        return None

    def close_reward_overlay(self):
        if not self.op.text(('祝福强化','方程展开','获得祝福','获得奇物'),(.30,.03,.76,.17),exact=True):
            return False
        close=self.main.reward_close_button()
        if close:
            return self.op.click_box(close,interval=2)
        return False

    def resume_approach(self,attempt):
        state=self.state()
        if (attempt<=0 or not state.get('entered') or state.get('done')
                or state.get('approach_recovery_attempt',0)>=attempt):
            return False
        state.setdefault('approach_attempts',[]).append(dict(
            scans=state.get('scans',0),moves=state.get('moves',0),recovery_attempt=attempt))
        state.update(scans=0,moves=0,approach_recovery_attempt=attempt)
        state.pop('last_direction',None)
        state.pop('last_seen',None)
        state.pop('occluded_steps',None)
        self.main.progress.record('star_workshop_resume_approach',recovery_attempt=attempt)
        self.main.progress.save('star_workshop_resume_approach')
        return True

    def equation_cards(self):
        from tasks.divergent_universe.star_policy import star_catalog, catalog_name
        op=self.op
        catalog=star_catalog()['equations']
        labels=op.read_region((.03,.36,.64,.43),snapshot=False)
        labels+=op.read_region((.025,.59,.65,.82),snapshot=False)
        rows=[]
        for box in labels:
            name=catalog_name(box.source,catalog)
            if not name and len(re.findall(r'[\u4e00-\u9fff]',box.source))>=3:
                # The real golden list title lost 昏 in a multi-card strip.
                # Re-read only its observed text box, preserving its original
                # click location. Never infer an absent equation from a name.
                x1,y1,x2,y2=box.button
                region=(max(0,x1-8)/1280,max(0,y1-5)/720,
                        min(1280,x2+8)/1280,min(720,y2+5)/720)
                name=catalog_name(op.read_line(region,snapshot=False).source,catalog)
            if name:
                rows.append((box,name))
        return rows

    def rewrite(self):
        from tasks.divergent_universe.star_policy import star_catalog
        main,op=self.main,self.op
        state=self.state()
        growth=getattr(main.star_loadout,'revision',None)=='star-workshop-v8'
        if growth and state.get('equation_rewrite_pending'):
            # An interrupted request keeps its reservation. Do not pay again
            # merely because the old target is still visible after a reload.
            return self.close('equation_rewrite_unconfirmed')
        catalog=star_catalog()['equations']
        cards=self.equation_cards
        previous=None
        def stable_cards():
            nonlocal previous
            rows=cards()
            names=tuple(name for _,name in rows)
            result=rows if names and names==previous else None
            previous=names
            return result
        observed=op.wait_until(stable_cards,timeout=12,name='可覆写方程列表')
        main.progress.record('star_rewrite_inventory',equations=[name for _,name in observed],
                             screenshot=self.save_frame('rewrite_inventory'))
        core=main.star_loadout.core_equations
        protected=set(core)
        primary_present=any(name==core[0] for _,name in observed)
        if primary_present:
            star=self.active['star']
            needs=star.get('observed_equation_requirements',{}).get(core[0])
            counts=star.get('path_counts')
            if not needs or counts is None or any(counts.get(path,0)<need for path,need in needs.items()):
                return self.close('primary_needs_blessings')
        candidates=[(box,name) for box,name in observed if name not in protected
                    and (catalog[name]['rarity']==3 if not primary_present else catalog[name]['rarity']<3)]
        if not candidates or state.get('rewrites',0)>=(2 if growth else 5):
            return self.close('no_unwanted_equation' if not candidates else 'rewrite_budget_reached')
        target,name=max(candidates,key=lambda item:catalog[item[1]]['rarity'])
        op.click_box(target,interval=2)
        op.wait_until(lambda:self.selected_equation()==name,
                      action=lambda:op.click_box(target,interval=2),timeout=10,name='覆写目标选中')
        price=normalize(op.read_line((.72,.88,.765,.936),snapshot=False).source)
        funds=normalize(op.read_line((.85,.032,.90,.068),snapshot=False).source)
        price_match=re.fullmatch(r'x?(\d+)',price,flags=re.I)
        funds_match=re.fullmatch(r'\d+',funds)
        if not price_match or not funds_match:
            self.inspect_open_page('rewrite_price_unknown')
        cost=int(price_match[1]);available=int(funds)
        if not 0<cost<=250 or available-cost<50:
            return self.close('insufficient_rewrite_reserve')
        if growth:
            if 'equation_rewrite_budget' not in state:
                state.update(equation_rewrite_initial_funds=available,
                             equation_rewrite_budget=min(200,available//3))
                main.progress.record('star_equation_rewrite_budget',available=available,
                                     budget=state['equation_rewrite_budget'],
                                     reason='v8_reserve_majority_for_blessing_growth')
                main.progress.save('star_equation_rewrite_budget')
            reserved=max(state.get('equation_rewrite_reserved',0),state.get('equation_rewrite_spent',0))
            if reserved+cost>state['equation_rewrite_budget']:
                return self.close('equation_rewrite_growth_budget')
        button=op.text('覆写',(.78,.87,.97,.95),exact=True)
        if not button:
            self.inspect_open_page('rewrite_control_unknown')
        state['rewrites']=state.get('rewrites',0)+1
        if growth:
            state['equation_rewrite_reserved']=reserved+cost
            state['equation_rewrite_pending']=dict(name=name,cost=cost)
        main.progress.record('star_equation_rewrite_requested',name=name,cost=cost,available=available,
                             screenshot=self.save_frame('rewrite_before'))
        main.progress.save('star_workshop_rewrite')
        op.click_box(button,interval=2)
        op.wait_until(lambda: main.selection_kind()=='equation'
                      or self.selected_equation()!=name,timeout=15,name='方程覆写结果')
        op.wait_until(lambda:main.selection_kind()=='equation',timeout=15,name='覆写新方程候选')
        self.save_frame(f'rewrite_candidates_{state["rewrites"]}')
        self.finish_equation_rewrite()
        current=op.wait_until(cards,timeout=12,name='更新后的方程列表')
        if growth:
            state['equation_rewrite_spent']=state.get('equation_rewrite_spent',0)+cost
            state.pop('equation_rewrite_pending',None)
        main.progress.record('star_equation_rewrite_observed',removed=name,
                             current=[n for _,n in current],screenshot=self.save_frame(f'rewrite_after_{state["rewrites"]}'))
        main.progress.save('star_workshop_rewrite_observed')
        return True

    def finish_equation_rewrite(self):
        main,op=self.main,self.op
        selections=0
        def follow_visible_reward():
            nonlocal selections
            if self.close_reward_overlay():
                return
            if selections<6 and main.selection_kind()=='equation':
                selections+=1
                if selections>1:
                    main.progress.record('star_equation_rewrite_followup',selection=selections,
                                         screenshot=self.save_frame(f'rewrite_followup_{time.time_ns()}'))
                main.handle_choice('equation')
        op.wait_until(lambda:op.text('方程覆写',(.035,.035,.30,.10),exact=True),
                      action=follow_visible_reward,timeout=45,name='返回方程覆写列表')
        return True

    def selected_equation(self):
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name
        op=self.op
        names=set()
        for box in op.read_region((.68,.12,.97,.18),snapshot=False):
            name=catalog_name(box.source,star_catalog()['equations'])
            if not name:
                # The leading 一 can be dropped as a horizontal decoration.
                # Include one character's width on the left, excluding the
                # gold underline that corrupted the broader single-line OCR.
                x1,y1,x2,y2=box.button
                region=(max(870,x1-box.height-4)/1280,max(0,y1-3)/720,
                        min(1280,x2+8)/1280,min(720,y2+1)/720)
                name=catalog_name(op.read_line(region,snapshot=False).source,star_catalog()['equations'])
            if name:
                names.add(name)
        return next(iter(names)) if len(names)==1 else None

    def close(self, outcome):
        from tasks.base.assets.assets_base_page import GUIDE_CLOSE
        if outcome in ('no_unwanted_equation','rewrite_budget_reached','insufficient_rewrite_reserve','primary_needs_blessings',
                       'equation_rewrite_growth_budget','equation_rewrite_unconfirmed'):
            self.state().update(rewrite_done=True,rewrite_outcome=outcome)
            self.main.progress.save('star_workshop_rewrite_finished')
            return self.return_to_menu()
        self.state().update(done=True,outcome=outcome)
        self.main.progress.record('star_workshop_finished',outcome=outcome,screenshot=self.save_frame('finished'))
        self.main.progress.save('star_workshop_finished')
        return self.close_panel()

    def close_panel(self):
        from tasks.base.assets.assets_base_page import GUIDE_CLOSE
        main,op=self.main,self.op
        requests=0
        def close_visible_panel():
            nonlocal requests
            if requests<3 and not main.world_visible() and self.visible():
                if main.appear_then_click(GUIDE_CLOSE,interval=2):
                    requests+=1
        op.wait_until(main.world_visible,action=close_visible_panel,timeout=12,name='退出造物台返回场景')
        return True

    def return_to_menu(self):
        from tasks.base.assets.assets_base_page import GUIDE_CLOSE
        main,op=self.main,self.op
        def close_function_page():
            if op.text(('方程覆写','祝福覆写','祝福强化'),(.035,.035,.30,.10),exact=True):
                return main.appear_then_click(GUIDE_CLOSE,interval=2)
            return False
        op.wait_until(lambda:op.text(self.NAMES,(.025,.015,.31,.115),exact=True) or main.world_visible(),
                      action=close_function_page,timeout=12,name='返回造物台菜单')
        return True

    def rewrite_blessings(self):
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name
        main,op=self.main,self.op
        state=self.state();star=self.active['star'];table=star_catalog()['blessings']
        state.pop('secondary_completion',None)
        primary=main.star_loadout.core_equations[0]
        growth=getattr(main.star_loadout,'revision',None)=='star-workshop-v8'
        bridge=state.get('blessing_bridge_target') if growth else None
        if bridge and bridge.get('done'):
            return self.return_to_menu()
        if bridge:
            primary=bridge['name']
        def finish(reason):
            state.update(blessing_rewrite_done=True,blessing_rewrite_outcome=reason)
            if growth:
                state['blessing_choice_pending']=False
            if bridge:
                bridge.update(done=True,outcome=reason)
                state.update(rewrite_done=True,rewrite_outcome='bridge_growth_finished')
            elif reason=='primary_requirements_met' and state.get('rewrite_outcome')=='primary_needs_blessings':
                state.update(rewrite_done=False,rewrite_outcome='requirements_met_return_to_equations')
            main.progress.record('star_blessing_rewrite_finished',reason=reason,screenshot=self.save_frame('blessing_rewrite_finished'))
            main.progress.save('star_blessing_rewrite_finished')
            return self.return_to_menu()
        progress=self.blessing_rewrite_progress(primary)
        if not progress and not bridge and any(c.get('kind')=='equation' and catalog_name(c.get('title',''),star_catalog()['equations'])==primary
                                for c in star.get('choices',[])):
            try:
                progress=self.find_blessing_rewrite_progress(primary)
            except RuntimeError:
                progress=None
        if not progress and growth and not bridge:
            bridge=self.select_blessing_bridge(primary)
            if bridge:
                primary=bridge['name']
                progress=self.blessing_rewrite_progress(primary)
        if not progress:
            return finish('bridge_progress_unreadable' if bridge else 'primary_progress_unreadable')
        counts,needs=progress
        if bridge:
            bridge.update(counts=counts,requirements=needs)
        star.setdefault('path_counts',{}).update(counts)
        star.setdefault('observed_equation_requirements',{})[primary]=needs
        main.progress.record('star_core_path_counts_observed',equation=primary,counts=counts,requirements=needs,
                             source='blessing_rewrite_equation_strip')
        if all(counts[p]>=needs[p] for p in needs):
            return finish('bridge_requirements_met' if bridge else 'primary_requirements_met')
        if state.get('blessing_rewrites',0)>=12:
            return finish('blessing_rewrite_budget_reached')
        protected=set(needs)
        held={catalog_name(c['title'],star_catalog()['equations']) for c in star.get('choices',[]) if c['kind']=='equation'}
        for name in main.star_loadout.core_equations:
            if name in held:
                protected.update(star.get('observed_equation_requirements',{}).get(name,
                    star_catalog()['equations'].get(name,{}).get('requires',{})))
        enhanced={name for visit in star.get('workshops',{}).values() for name in visit.get('enhanced',[])}
        effect_protected=set()
        skipped=set(state.get('blessing_rewrite_path_skips',[])) if growth else set()
        if growth:
            from tasks.divergent_universe.star_effects import effect_features
            for choice in star.get('choices',[]):
                if (choice.get('kind')=='blessing' and
                        {'revive','heal'}.intersection(effect_features(
                            choice.get('effect_text',''),getattr(main.star_loadout,'candidate',None)))):
                    effect_protected.add(catalog_name(choice.get('title',''),table) or normalize(choice.get('title','')))
        rows=self.blessing_rewrite_cards()
        candidates=[]
        for box,name in rows:
            if (name in main.star_loadout.survival_blessings or name in enhanced or name in effect_protected
                    or name in skipped or (not growth and table[name]['path'] in protected)):
                continue
            x1,y1,x2,y2=box.button
            status=(max(0,x1-10)/1280,min(719,y2+20)/720,min(1280,x2+10)/1280,min(720,y2+76)/720)
            if status[1]<status[3] and op.text('已强化',status,exact=True):
                continue
            candidates.append((box,name))
        if not candidates:
            if self.scroll_blessing_list():
                return True
            return finish('no_safe_visible_blessing')
        target,name=min(candidates,key=lambda item:table[item[1]]['rarity'])
        op.wait_until(lambda:self.blessing_rewrite_title()==name,
                      action=lambda:op.click_box(target,interval=2),timeout=10,name='祝福覆写目标选中')
        if growth:
            # Selection can reveal removal previews or change the visible
            # strip. Re-read its owned counts before every paid request;
            # prices, funds and the enabled control are then read this frame.
            op.snapshot()
            path_region=(.685,.33,.81,.375)
            path_labels=[normalize(box.source) for box in op.read_region(path_region,snapshot=False)]
            paths=set(path_labels).intersection(('记忆','虚无','巡猎','毁灭','欢愉','繁育','智识','同谐'))
            if len(paths)!=1:
                main.progress.record('star_blessing_rewrite_path_unverified',name=name,
                                     labels=path_labels,region=path_region,
                                     reason='current_selected_path_not_unique',
                                     screenshot=self.save_frame('blessing_rewrite_path_unverified'))
                return finish('blessing_rewrite_path_unknown')
            actual_path=next(iter(paths))
            if actual_path in protected:
                state.setdefault('blessing_rewrite_path_skips',[]).append(name)
                main.progress.record('star_blessing_rewrite_path_protected',name=name,path=actual_path,
                                     protected=sorted(protected),reason='current_selected_path_is_protected',
                                     screenshot=self.save_frame('blessing_rewrite_path_protected'))
                main.progress.save('star_blessing_rewrite_path_protected')
                return True
            fresh=self.blessing_rewrite_progress(primary)
            if not fresh:
                return finish('bridge_progress_unreadable' if bridge else 'primary_progress_unreadable')
            counts,needs=fresh
            if bridge:
                bridge.update(counts=counts,requirements=needs)
            deficit=sum(max(0,need-counts[path]) for path,need in needs.items())
            if not deficit:
                return finish('bridge_requirements_met' if bridge else 'primary_requirements_met')
            if bridge and deficit>2:
                return finish('bridge_progress_changed')
        price=normalize(op.read_line((248/1280,186/720,292/1280,215/720),snapshot=False).source)
        funds=normalize(op.read_line((.85,.032,.90,.068),snapshot=False).source)
        match=re.fullmatch(r'x?(\d+)',price,re.I)
        if not match or not funds.isdigit():
            self.inspect_open_page('blessing_rewrite_price_unknown')
        cost=int(match[1]);available=int(funds)
        reserved=max(state.get('blessing_rewrite_reserved',0),state.get('blessing_rewrite_spent',0))
        # Keep one persisted allowance for this visit. An increasing global
        # rewrite price must not disable all later visits at an arbitrary 80.
        # Requests remain bounded even if a transaction is interrupted.
        budget=state.setdefault('blessing_rewrite_budget',available)
        if cost>available or reserved+cost>budget:
            return finish('blessing_rewrite_cost_budget')
        button=op.text('覆写',(.78,.87,.97,.95),exact=True)
        if not button or not main.confirm_enabled(button):
            return finish('blessing_rewrite_control_unavailable')
        request=state.get('blessing_rewrites',0)+1
        secondary=(self.observe_secondary_completion(name,actual_path,request)
                   if growth and not bridge else None)
        state['blessing_rewrites']=request
        if secondary:
            state['secondary_completion']=secondary
        # A request may be interrupted after payment. Reserve its maximum
        # cost before acting, while recording actual spending only on return.
        state['blessing_rewrite_reserved']=reserved+cost
        screenshot=self.save_frame(f'blessing_rewrite_before_{state["blessing_rewrites"]}')
        if secondary:
            secondary['screenshot']=screenshot
        main.progress.record('star_blessing_rewrite_requested',name=name,cost=cost,available=available,
                             core_counts=counts,screenshot=screenshot,secondary_completion=secondary,
                             **({'paths':[actual_path]} if growth else {}))
        main.progress.save('star_blessing_rewrite_requested')
        try:
            if not op.click_box(button,interval=2):
                state.pop('secondary_completion',None)
            op.wait_until(lambda:main.selection_kind()=='blessing',timeout=15,name='覆写后的祝福候选')
            if growth:
                state['blessing_choice_pending']=True
            star['choices'].append(dict(kind='discard',title=name,node=self.active['node'],source='blessing_rewrite',
                                       **({'paths':[actual_path]} if growth else {})))
            main.progress.save('star_blessing_rewrite_choice')
            main.handle_choice('blessing')
        finally:
            # This optional priority ends with this transaction, including a
            # failed payment, page departure, stop or interrupted selection.
            state.pop('secondary_completion',None)
            if secondary:
                main.progress.save()
        op.wait_until(lambda:op.text('祝福覆写',(.035,.035,.30,.10),exact=True),
                      action=self.close_reward_overlay,timeout=15,name='返回祝福覆写列表')
        if growth:
            state['blessing_choice_pending']=False
        state['blessing_rewrite_spent']=state.get('blessing_rewrite_spent',0)+cost
        main.progress.save('star_blessing_rewrite_returned')
        try:
            observed=op.wait_until(lambda:self.blessing_rewrite_progress(primary),timeout=6,name='覆写后核心计数')
        except RuntimeError as error:
            if not str(error).startswith('覆写后核心计数超时'):
                raise
            observed=None
        if observed:
            star['path_counts'].update(observed[0])
            if bridge:
                bridge.update(counts=observed[0],requirements=observed[1])
        main.progress.record('star_blessing_rewrite_observed',removed=name,cost=cost,core_counts=observed[0] if observed else None,
                             screenshot=self.save_frame(f'blessing_rewrite_after_{state["blessing_rewrites"]}'))
        main.progress.save('star_blessing_rewrite_observed')
        if not observed:
            return finish('core_counts_unreadable_after_confirmed_choice')
        if bridge and all(observed[0][p]>=need for p,need in observed[1].items()):
            return finish('bridge_requirements_met')
        return True

    def observe_secondary_completion(self,removed_title,removed_path,request):
        """One reviewed DOT secondary, visible and one card short after removal."""
        import hashlib
        main=self.main;star=self.active['star']
        proof=star.get('secondary_equation_evidence') or {}
        if (main.star_loadout.candidate not in ('dot','dot_blackswan') or self.active.get('stop_requested')
                or removed_path not in ('记忆','虚无','巡猎','毁灭','欢愉','繁育','智识','同谐')
                or proof.get('source')!='verified_import_secondary_cards'
                or '永恒竞走' not in proof.get('names',())
                or not proof.get('screenshot') or not getattr(main.progress,'session_id',None)):
            return None
        signature=hashlib.sha256(main.star_loadout.guide_code.encode('utf-8')).hexdigest()
        if proof.get('guide_signature')!=signature or star.get('guide_signature')!=signature:
            return None
        observed=star.get('observed_equation_requirements',{}).get('永恒竞走',{})
        if set(observed)!={'虚无','巡猎'}:
            return None
        # The aggregate inventory can lag a rewrite. Protect a primary that
        # is one card away using this same frame, not that older aggregate.
        primary=self.blessing_rewrite_progress(main.star_loadout.core_equations[0])
        if not primary or sum(max(0,need-primary[0].get(path,0)) for path,need in primary[1].items())<=1:
            return None
        progress=self.blessing_rewrite_progress('永恒竞走')
        if not progress:
            return None
        counts,needs=progress
        if (set(counts)!=set(observed) or set(needs)!=set(observed)
                or any(type(n) is not int or not 0<=n<=200 for n in counts.values())
                or any(type(n) is not int or not 1<=n<=200 for n in needs.values())
                or sum(max(0,needs[p]-counts[p]) for p in needs)!=1):
            return None
        after=dict(counts)
        if removed_path in after:
            after[removed_path]-=1
        if any(n<0 for n in after.values()) or sum(max(0,needs[p]-after[p]) for p in needs)!=1:
            return None
        return dict(name='永恒竞走',source='same_frame_rewrite_strip',run_id=self.active['id'],
                    node=self.active['node'],selection=self.active.get('selections'),request=request,
                    session=main.progress.session_id,choice_index=len(star.get('choices',[])),
                    guide_signature=signature,counts_before_removal=dict(counts),counts_after_removal=after,
                    requirements=dict(needs),removed_title=removed_title,removed_path=removed_path)

    def select_blessing_bridge(self,primary):
        """A visible near-complete equation is an experimental interim target."""
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name,equation_requirements
        main,op=self.main,self.op
        star=self.active['star'];observed=star.get('observed_equation_requirements',{})
        core_paths=set(equation_requirements(primary,observed,star.get('threshold')))
        catalog=star_catalog()['equations']
        names={catalog_name(box.source,catalog) for box in op.read_region((.03,.13,.97,.18),snapshot=False)}
        candidates=[]
        for name in sorted(names-{None,primary}):
            # Historical choices and the old catalog cannot prove that a
            # chip is held now or supply unobserved requirement path labels.
            if name not in observed or len(observed[name])!=2:
                continue
            progress=self.blessing_rewrite_progress(name)
            if not progress:
                continue
            counts,needs=progress
            shared=sorted(core_paths.intersection(needs))
            deficit=sum(max(0,need-counts[path]) for path,need in needs.items())
            if shared and 1<=deficit<=2:
                candidates.append(dict(name=name,counts=counts,requirements=needs,
                                       deficit=deficit,shared_paths=shared))
        if not candidates:
            return None
        bridge=min(candidates,key=lambda row:(row['deficit'],-len(row['shared_paths']),row['name']))
        bridge.update(reason='visible_shared_paths_near_completion_experiment',
                      effects_verified=False,done=False,screenshot=self.save_frame('blessing_bridge_selected'))
        self.state()['blessing_bridge_target']=bridge
        main.progress.record('star_blessing_bridge_selected',**bridge)
        main.progress.save('star_blessing_bridge_selected')
        return bridge

    def primary_chip_title(self,primary):
        for region in ((.13,.13,.88,.18),(.03,.13,.38,.18),(.62,.13,.97,.18)):
            title=self.op.text(primary,region,exact=True)
            if title:
                return title
        return None

    def find_blessing_rewrite_progress(self,primary):
        main,op=self.main,self.op
        swipes=0;direction=-1
        def reveal():
            nonlocal swipes,direction
            title=self.primary_chip_title(primary)
            if (title and title.left+181<=1260) or swipes>=8:
                return
            before=op.image[95:170,40:1230].copy()
            start,end=((1130,133),(470,133)) if direction<0 else ((150,133),(1130,133))
            main.device.drag(start,end,point_random=(0,0,0,0),name='DU_EQUATION_CHIP_SCROLL')
            main.wait_until_stable((40,95,1230,170));op.snapshot()
            after=op.image[95:170,40:1230]
            changed=before.shape==after.shape and np.abs(before.astype(int)-after.astype(int)).mean()>2
            swipes+=1
            if changed:
                main.device.stuck_record_clear();main.device.click_record_clear()
            else:
                direction=-direction
            main.progress.record('star_core_chip_scrolled',equation=primary,swipe=swipes,changed=bool(changed),
                                 screenshot=self.save_frame(f'core_scan_{time.time_ns()}'))
        return op.wait_until(lambda:self.blessing_rewrite_progress(primary),action=reveal,
                             timeout=20,name='核心方程需求出现')

    def blessing_rewrite_progress(self,primary):
        from tasks.divergent_universe.star_policy import star_catalog
        title=self.primary_chip_title(primary)
        if not title or title.left+181>1260:
            return None
        keys=list(self.active['star'].get('observed_equation_requirements',{}).get(primary,
            star_catalog()['equations'].get(primary,{}).get('requires',{})))
        if len(keys)!=2:
            return None
        pairs=[]
        for left,widths in ((32,(80,105)),(108,(157,181))):
            for right in widths:
                region=((title.left+left)/1280,126/720,
                        min(1280,title.left+right)/1280,160/720)
                text=self.op.read_line(region,snapshot=False).source
                pair=parse_rewrite_count(text)
                if not pair:
                    # The recognizer-only crop read a dim 7/6 as 716. A
                    # detected text box in this same small field preserves
                    # the slash; never infer it from a digit-only string.
                    detected=[parsed for box in self.op.read_region(region,snapshot=False)
                              if (parsed:=parse_rewrite_count(box.source))]
                    if len(detected)==1:
                        pair=detected[0]
                if pair:
                    pairs.append(pair)
                    break
        if len(pairs)!=2:
            return None
        return ({p:int(pair[0]) for p,pair in zip(keys,pairs)},
                {p:int(pair[1]) for p,pair in zip(keys,pairs)})

    def blessing_rewrite_cards(self):
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name
        op=self.op;table=star_catalog()['blessings'];result=[]
        regions=[(.03,.50,.65,.55),(.03,.81,.65,.885)]
        if self.state().get('blessing_grid_scrolled'):
            # Scrolling need not align a row with its original fixed band.
            # Locate titles in only the first column, then read matching thin
            # rows across the grid. Do not OCR all icons/descriptions.
            anchors=op.read_region((.035,.325,.18,.97),snapshot=False)
            centers=[]
            for box in anchors:
                if catalog_name(box.source,table) and all(abs(box.center[1]-y)>40 for y in centers):
                    centers.append(box.center[1])
            regions=[(.03,max(234,y-25)/720,.65,min(698,y+25)/720) for y in centers
                     if min(698,y+25)-max(234,y-25)>=20]
        for region in regions:
            for box in op.read_region(region,snapshot=False):
                name=catalog_name(box.source,table)
                if name:
                    result.append((box,name))
        return result

    def scroll_blessing_list(self):
        from module.ui.scroll import Scroll
        state=self.state();main,op=self.main,self.op
        if state.get('blessing_scrolls',0)>=8:
            state['blessing_scroll_outcome']='scan_budget_reached'
            return False
        op.snapshot()
        if not op.text('祝福覆写',(.035,.035,.30,.10),exact=True):
            return False
        # Actual list thumb is RGB ~191, y234..694 at x854..856.
        bar=Scroll((853,234,858,694),(191,191,191),name='DU_BLESSING_REWRITE_SCROLL')
        bar.match_color(main)
        if not 20<=bar.length<=bar.total-15:
            state['blessing_scroll_outcome']='no_verified_draggable_bar'
            return False
        current=bar.cal_position(main)
        if current>=.98:
            state['blessing_scroll_outcome']='bottom_observed'
            return False
        target=min(1,current+.8*bar.length/(bar.total-bar.length))
        def point(position):
            area=bar.position_to_screen(position,random_range=(0,0))
            return ((area[0]+area[2])//2,(area[1]+area[3])//2)
        state['blessing_scrolls']=state.get('blessing_scrolls',0)+1
        state['blessing_grid_scrolled']=True
        main.progress.save('star_blessing_rewrite_scan')
        main.device.drag(point(current),point(target),point_random=(0,0,0,0),name=bar.name)
        main.wait_until_stable((40,230,820,698));op.snapshot()
        after=bar.cal_position(main)
        if abs(after-current)>.005:
            main.device.stuck_record_clear();main.device.click_record_clear()
        main.progress.record('star_blessing_rewrite_scrolled',before=current,after=after,
                             screenshot=self.save_frame(f'blessing_scan_{state["blessing_scrolls"]}'))
        # A swallowed drag is a bounded retry, not proof that the list ended.
        return True

    def blessing_rewrite_title(self):
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name
        table=star_catalog()['blessings']
        for box in self.op.read_region((.68,.25,.97,.30),snapshot=False):
            name=catalog_name(box.source,table)
            if name:
                return name
        return None

    def enhance(self):
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name
        main,op=self.main,self.op
        state=self.state()
        table=star_catalog()['blessings']
        empty_frames=0
        def enhancement_status():
            nonlocal empty_frames
            empty=bool(op.text('祝福强化',(.035,.035,.30,.10),exact=True)
                       and op.text('暂无可强化祝福',(.40,.55,.60,.62),exact=True))
            empty_frames=empty_frames+1 if empty else 0
            if empty_frames>=2:
                return {'value':None,'empty':True}
            if empty:
                return None
            value=self.enhancement_heat()
            return {'value':value,'empty':False} if value is not None else None
        observed=op.wait_until(enhancement_status,action=self.close_reward_overlay,
                               timeout=10,name='强化剩余热量')
        heat=observed['value']
        def finish(reason):
            state.update(enhancement_done=True,enhancement_outcome=reason)
            main.progress.record('star_enhancement_finished',remaining_heat=heat,reason=reason,
                                 screenshot=self.save_frame('enhancement_finished'))
            main.progress.save('star_enhancement_finished')
            return self.return_to_menu()
        if observed['empty']:
            return finish('no_enhanceable_blessings')
        if heat==0:
            return finish('heat_exhausted')
        order=main.progress.data.get('star_path_order')
        if not order or len(order)!=8:
            self.inspect_open_page('enhancement_path_order_unknown')
        primary=star_catalog()['equations'].get(main.star_loadout.core_equations[0],{}).get('requires',{})
        paths=list(dict.fromkeys(['毁灭',*primary]))
        enhanced=state.setdefault('enhanced',[])
        candidates={}
        def open_path(path):
            index=order.index(path)
            x=190+100*index
            if x>=850:
                return False  # The final tab is outside this observed viewport.
            op.wait_until(lambda:op.text(path,(.03,.18,.36,.245)),
                action=lambda:op.click_point(x/1280,102/720,tag='DU_ENHANCEMENT_PATH_'+path,interval=2),
                timeout=10,name='强化祝福命途分类')
            main.wait_until_stable((40,140,840,610));op.snapshot()
            return True
        for path in paths:
            if not open_path(path):
                continue
            labels=op.read_region((.03,.43,.65,.48),snapshot=False)
            labels+=op.read_region((.03,.77,.65,.815),snapshot=False)
            labels=[b for b in labels if len(re.findall(r'[\u4e00-\u9fff]',b.source))>=3]
            for box in labels:
                op.click_box(box,interval=2)
                main.wait_until_stable((875,90,1240,580));op.snapshot()
                name=self.enhancement_title()
                button=op.text('强化',(.78,.87,.97,.95),exact=True)
                cost=self.enhancement_cost()
                if (not name or name in enhanced or not button or not main.confirm_enabled(button)
                        or cost is None or not 1<=cost<=heat):
                    continue
                # Reading the actual selected title prevents a clipped list
                # label from being treated as a different purchased blessing.
                survival=next((len(main.star_loadout.survival_blessings)-i
                    for i,n in enumerate(main.star_loadout.survival_blessings) if n==name),0)
                score=(survival>0,survival,path in primary,table[name]['rarity'],-cost)
                candidates[name]=dict(name=name,path=path,box=box,cost=cost,score=score)
        if not candidates:
            return finish('no_affordable_recognized_blessing')
        chosen=max(candidates.values(),key=lambda c:c['score'])
        open_path(chosen['path'])
        op.wait_until(lambda:self.enhancement_title()==chosen['name'],
                      action=lambda:op.click_box(chosen['box'],interval=2),timeout=10,name='强化目标选中')
        before=self.enhancement_heat();cost=self.enhancement_cost()
        button=op.text('强化',(.78,.87,.97,.95),exact=True)
        if before is None or cost!=chosen['cost'] or cost>before or not button or not main.confirm_enabled(button):
            main.progress.record('star_enhancement_unverified',name=chosen['name'],expected_cost=chosen['cost'],
                                 observed_cost=cost,heat=before,screenshot=self.save_frame('enhancement_unverified'))
            return finish('selected_cost_unverified')
        main.progress.record('star_enhancement_requested',name=chosen['name'],cost=cost,heat=before,
                             screenshot=self.save_frame('enhancement_before'))
        op.click_box(button,interval=2)
        op.wait_until(lambda:self.enhancement_heat()==before-cost,action=self.close_reward_overlay,
                      timeout=15,name='强化热量实际减少')
        enhanced.append(chosen['name'])
        main.progress.record('star_blessing_enhanced',name=chosen['name'],cost=cost,remaining_heat=before-cost,
                             screenshot=self.save_frame(f'enhanced_{len(enhanced)}'))
        main.progress.save('star_blessing_enhanced')
        return True

    def enhancement_heat(self):
        if not (self.op.text('祝福强化',(.035,.035,.30,.10),exact=True)
                and self.op.text('剩余热量',(.77,.829,.845,.875),exact=True)):
            return None
        value=normalize(self.op.read_line((1108/1280,598/720,1140/1280,626/720),snapshot=False).source)
        # The observed integer counter 4 acquired a trailing OCR dot. Never
        # accept a decimal or concatenate separated digits into a heat value.
        match=re.fullmatch(r'(\d{1,2})[.。]?',value)
        return int(match[1]) if match and int(match[1])<=20 else None

    def enhancement_cost(self):
        # The multiplication glyph beside a single digit was read as '.1'.
        # Read only the actual digit; retain the original region as fallback.
        value=normalize(self.op.read_line((945/1280,640/720,966/1280,674/720),snapshot=False).source)
        if re.fullmatch(r'[1-9]',value):
            return int(value)
        value=normalize(self.op.read_line((940/1280,641/720,975/1280,676/720),snapshot=False).source)
        match=re.fullmatch(r'x?(\d)',value,re.I)
        return int(match[1]) if match else None

    def enhancement_title(self):
        from tasks.divergent_universe.star_policy import star_catalog,catalog_name
        table=star_catalog()['blessings']
        boxes=self.op.read_region((.68,.12,.97,.18),snapshot=False)
        for box in boxes:
            name=catalog_name(box.source,table)
            if name:
                return name
        return catalog_name(self.op.read_line((.685,.122,.97,.164),snapshot=False).source,table)

    def equip_weighted(self):
        main,op=self.main,self.op
        from tasks.divergent_universe.star_policy import decode_guide_plan
        desired=decode_guide_plan(main.star_loadout.guide_code)['weighted_curio_ids']
        if main.star_loadout.candidate in ('aglaea','aglaea_sustain'):
            desired=[1009,1010]  # Shield/healing support before the second core.
        def slots():
            label=op.read_line((.03,.124,.24,.17),snapshot=False).source
            match=re.search(r'(\d+)\s*/\s*(\d+)',label)
            return (int(match[1]),int(match[2])) if match else None
        count=op.wait_until(slots,timeout=12,name='加权装备槽数')
        if count[0]>=count[1]:
            return self.close('weighted_slots_full')
        op.wait_until(lambda:op.text(('装备','卸下'),(.75,.87,.94,.95),exact=True)
                      and bool(op.read_region((.68,.12,.96,.17),snapshot=False)),
                      timeout=12,name='加权奇物详情加载')
        equipped=self.active['star'].setdefault('weighted_equipment',[])
        if count[0]>=len(desired) and all(any(x['id']==identity for x in equipped) for identity in desired):
            return self.close('desired_weighted_equipped')
        known_names={1002:'静谧的歌声',1004:'祈祷之路',1009:'尊严与热忱',1010:'寻爱金镖',
                     1011:'神之足迹',1013:'自娱自乐',1016:'平行宇宙对讲机'}
        def selected_name():
            boxes=op.read_region((.68,.12,.96,.17),snapshot=False)
            name=normalize(''.join(box.source.strip() for box in sorted(boxes,key=lambda box:box.left)))
            return '尊严与热忱' if name=='尊严与热忧' else name
        for identity in desired:
            if any(x['id']==identity for x in equipped):
                continue
            # The selected card's bright border can invalidate the unselected
            # icon template. Its exact right-panel title already identifies
            # the active equipment target; no extra list click is needed.
            already_selected=identity in known_names and selected_name()==known_names[identity]
            path=op.templates/f'star_weighted_list_{identity}.png'
            matches=[]
            if already_selected:
                pass
            elif path.exists():
                matches=op.template_matches(str(path),(.025,.19,.33,.88),confidence=.89,
                                             scales=np.linspace(.94,1.06,7))
            if not already_selected and not matches:
                expected=known_names.get(identity)
                if not expected or not self.active['star'].get('run_guide_verified'):
                    continue
                badges=op.template_matches(str(op.templates/'star_weighted_recommended.png'),
                                           (.025,.19,.33,.87),confidence=.90,scales=(1.0,))
                matches=[]
                for badge in badges:
                    candidate=Box(badge.left-34,badge.top+35,20,20,'DU_RECOMMENDED_WEIGHTED',badge.score)
                    op.click_box(candidate,interval=2)
                    main.wait_until_stable((870,85,1250,600));op.snapshot()
                    if selected_name()==expected:
                        matches=[candidate]
                        break
            if not already_selected and not matches:
                continue
            if not already_selected:
                op.click_box(max(matches,key=lambda b:b.score),interval=2)
                main.wait_until_stable((870,85,1250,600));op.snapshot()
            name=selected_name()
            if identity in known_names and name!=known_names[identity]:
                self.inspect_open_page('weighted_identity_mismatch')
            if not name:
                self.inspect_open_page('weighted_name_missing')
            button=op.wait_until(lambda:op.text('装备',(.75,.87,.94,.95),exact=True),timeout=10)
            main.progress.record('star_weighted_equip_requested',id=identity,name=name,
                                 before=count,screenshot=self.save_frame('weighted_before'))
            op.click_box(button,interval=2)
            op.wait_until(lambda:slots() and slots()[0]==count[0]+1,timeout=15,name='加权奇物装备计数增加')
            screenshot=self.save_frame(f'weighted_equipped_{identity}')
            equipped.append(dict(id=identity,name=name,node=self.active['node'],screenshot=screenshot))
            main.progress.record('star_weighted_equipped',id=identity,name=name,screenshot=screenshot)
            main.progress.save('star_weighted_equipped')
            return True
        self.inspect_open_page('weighted_core_not_in_visible_grid')

    def inspect_open_page(self, name):
        path=self.save_frame(name)
        self.main.progress.record('star_workshop_page_observed',screenshot=path,
                                  header=self.main.header_text(),equipment_verified=False)
        self.main.progress.save('star_workshop_adapter_pending')
        raise RequestHumanTakeover('造物台新功能页已保存；保留原局，等待补齐并验证当前页面适配')
