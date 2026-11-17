"""Native, bounded access to the merchant in an observed DU shop room.

The initial inspection records the real shop controls before any purchase is
implemented. A body template only guides movement; interaction still requires
the current merchant label and SRC's native interaction icon.
"""
from pathlib import Path
import re
import time
import numpy as np

from module.base.timer import Timer
from module.base.utils import save_image
from module.exception import RequestHumanTakeover
from tasks.rogue.route.exit import RogueExit
from tasks.currency_wars.operator import normalize


class ShopObserved(Exception):
    def __init__(self,result):
        self.result=result
        super().__init__('Observed merchant page; retain the current exploration')


def visit_shop(main,expected_run):
    """Resume one retained run until a real shop is offered, then inspect it."""
    from tasks.divergent_universe.divergent_universe import DivergentUniverse
    active=main.active or {}
    if not expected_run or active.get('id')!=expected_run or not active.get('star'):
        raise RequestHumanTakeover('商店访问只能继续指定的拓星原局')
    class ShopVisit(DivergentUniverse):
        def choose_station(self,prefer_shop=False):
            return super().choose_station(prefer_shop=True)
        def navigate_station(self):
            if self.active.get('station')=='商店':
                raise ShopObserved(StarShop(self).inspect(expected_run))
            return super().navigate_station()
    # Use the normal run owner, native combat/navigation, and real settlement
    # path. No coordinates are supplied by the caller and no new run is made.
    probe=ShopVisit(config=main.config,device=main.device,task='DivergentUniverse')
    probe.progress=main.progress
    probe._initialize()
    probe._run_deadline=min(probe._run_deadline,time.monotonic()+900)
    probe.apply_recovery_deadline()
    probe.active.setdefault('execution',{})['development_inspection']=True
    probe.progress.record('star_shop_visit_started',expected_run=expected_run)
    probe.progress.save('star_shop_visit')
    try:
        if not probe.go_to_lobby():
            return {'visited':False,'reason':'entry_limit'}
        result=probe.play_run()
    except ShopObserved as observed:
        return observed.result
    except Exception as error:
        evidence=StarShop(probe).save_frame('visit_error')
        probe.progress.record('star_shop_visit_failed',error=str(error),screenshot=evidence)
        probe.progress.save('star_shop_visit_failed')
        raise
    else:
        # If combat ends the run before a shop is offered, record only the
        # normal observed result. Never relabel a battle as a complete run.
        probe.progress.finish(result)
        return {'visited':False,'result':result,'run_id':expected_run}


class StarShop:
    NAMES=('阮·梅','阮•梅','阮梅','黑塔','螺丝咕姆')
    MAX_GATE_BACKOFFS=8

    def __init__(self,main):
        self.main=main
        self.op=main.op

    def save_frame(self,name):
        active=self.main.active
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/self.main.config.config_name/'star_runs'/active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'shop_{active.get("node",0)}_{name}_{time.time_ns()}.png'
        save_image(self.op.image,path)
        return str(path)

    def prompt(self):
        # Keep party-member names outside the crop; the native icon on this
        # same row remains the final interaction check.
        return self.op.text(self.NAMES,(.58,.48,.83,.70))

    def reenter_and_inspect(self,expected_run):
        active=self.main.active or {}
        if not expected_run or active.get('id')!=expected_run or active.get('station')!='商店':
            raise RequestHumanTakeover('只能重进指定原局的商店')
        self.main.reenter_station()
        self.op.wait_until(self.main.world_visible,
            action=lambda:self.main.start_or_resume() or self.main.handle_misc(),
            timeout=120,name='恢复原商店入口')
        return self.inspect(expected_run)

    def inspect_options(self,expected_run):
        from tasks.divergent_universe.events import DivergentEvent
        from tasks.rogue.assets.assets_rogue_event import CHOOSE_STORY
        main,op=self.main,self.op
        if (not expected_run or (main.active or {}).get('id')!=expected_run
                or main.active.get('station')!='商店'):
            raise RequestHumanTakeover('交易选项观察只适用于指定商店原局')
        op.snapshot()
        if not op.text('方程商店',(.10,.79,.58,.91)):
            raise RequestHumanTakeover('未识别已观察的方程商店对话标题')
        handler=DivergentEvent(main.config,device=main.device)
        clicks=0
        def options_visible():
            handler.options=[]
            return (op.text('打开方程商店',(.64,.65,.95,.75))
                    or handler._event_option_match()>0)
        def advance_story():
            nonlocal clicks
            if clicks>=8:
                return
            arrow=op.template('event_next',(.60,.40,.96,.86))
            if ((arrow and op.click_box(arrow,interval=2))
                    or (not arrow and handler.appear_then_click(CHOOSE_STORY,interval=2))):
                clicks+=1
        op.wait_until(options_visible,action=advance_story,timeout=30,name='商店交易选项')
        main.wait_until_stable((770,110,1230,650));op.snapshot()
        rows=op.read_region((.62,.65,.96,.86),snapshot=False)
        result=dict(screenshot=self.save_frame('options'),
                    rows=[dict(text=b.source,box=b.button) for b in rows],purchased=False)
        main.progress.record('star_shop_options_observed',**result)
        main.progress.save('star_shop_options_observed')
        return result

    def open_equation_store(self,expected_run):
        from tasks.divergent_universe.events import DivergentEvent
        from tasks.rogue.assets.assets_rogue_event import CHOOSE_OPTION_CONFIRM
        self.inspect_options(expected_run)
        main,op=self.main,self.op
        handler=DivergentEvent(main.config,device=main.device)
        def enter():
            if handler.appear_then_click(CHOOSE_OPTION_CONFIRM,interval=2):
                return
            op.click_box(op.text('打开方程商店',(.64,.65,.95,.75)),interval=2)
        op.wait_until(lambda:not op.text('打开方程商店',(.64,.65,.95,.75))
                      and bool(op.read_region((.025,.015,.45,.12),snapshot=False)),
                      action=enter,timeout=15,name='打开实际方程商店')
        main.wait_until_stable((30,100,1250,680));op.snapshot()
        result=dict(screenshot=self.save_frame('store'),purchased=False)
        main.progress.record('star_shop_page_observed',**result)
        main.progress.save('star_shop_page_observed')
        return result

    def visible(self):
        return bool(self.op.text('方程商店',(.035,.035,.30,.10),exact=True))

    def can_handle_page(self):
        active=self.main.active or {}
        if active.get('station')!='商店' or not active.get('star'):
            return False
        pending=active['star'].get('shops',{}).get(str(active.get('node')),{}).get('pending_purchase')
        return bool(self.visible() or self.op.text('商店',(.10,.79,.58,.91))
                    or (pending and self.main.reward_close_button()))

    def handle_room(self,expected_run):
        main,op=self.main,self.op
        active=main.active or {}
        if active.get('id')!=expected_run or active.get('station')!='商店' or not active.get('star'):
            return False
        state=active['star'].setdefault('shops',{}).setdefault(str(active['node']),{})
        if main.world_visible():
            if state.get('done'):
                return False
            try:
                self.inspect(expected_run)
            except RequestHumanTakeover:
                if not main.world_visible():
                    raise RuntimeError('商店接近期间页面变化，保留原局')
                try:
                    self.reenter_and_inspect(expected_run)
                except (RequestHumanTakeover,RuntimeError):
                    if not main.world_visible():
                        raise
                    state.update(done=True,outcome='merchant_not_reached')
                    main.progress.record('star_shop_skipped',reason='merchant_not_reached',screenshot=self.save_frame('unavailable'))
                    main.progress.save('star_shop_unavailable')
                    return False
        if not self.visible() and not state.get('pending_purchase'):
            if op.text('方程商店',(.10,.79,.58,.91)):
                self.open_equation_store(expected_run)
            else:
                state['outcome']='unadapted_merchant'
                main.progress.record('star_shop_skipped',reason='unadapted_merchant',screenshot=self.save_frame('unadapted'))
                return self.leave(expected_run)
        result=self.buy_equations(expected_run)
        if result.get('pending'):
            raise RuntimeError('商店购买收据未能核验，禁止重复付款')
        return self.leave(expected_run)

    def funds(self):
        value=normalize(self.op.read_line((.85,.03,.91,.074),snapshot=False).source)
        return int(value) if re.fullmatch(r'\d{1,6}',value) else None

    def price(self):
        value=normalize(self.op.read_line((.72,.88,.77,.94),snapshot=False).source)
        match=re.fullmatch(r'x?(\d{1,5})',value,re.I)
        return int(match[1]) if match else None

    def selected_fields(self):
        from tasks.divergent_universe.star_workshop import StarWorkshop,parse_rewrite_count
        from tasks.divergent_universe.star_policy import star_catalog
        name=StarWorkshop(self.main).selected_equation()
        keys=list(star_catalog()['equations'].get(name,{}).get('requires',{}))
        if not name or len(keys)!=2:
            return None
        pairs=[]
        for region in ((920/1280,298/720,980/1280,324/720),
                       (1005/1280,298/720,1065/1280,324/720)):
            pair=parse_rewrite_count(self.op.read_line(region,snapshot=False).source)
            if pair is None:
                return None
            pairs.append(pair)
        return dict(name=name,cost=self.price(),funds=self.funds(),
                    counts={k:v[0] for k,v in zip(keys,pairs)},
                    requirements={k:v[1] for k,v in zip(keys,pairs)})

    def reconcile_purchase(self,state):
        from tasks.divergent_universe.star_workshop import StarWorkshop
        main,op=self.main,self.op
        pending=state['pending_purchase'];name=pending['name']
        def received():
            return (pending.get('receipt_observed') and self.visible()
                    and self.funds()==pending['funds']-pending['cost'])
        def receipt():
            if (op.text('获得方程',(.44,.18,.58,.23),exact=True)
                    and op.text(name,(.14,.45,.38,.53),exact=True)):
                if not pending.get('receipt_observed'):
                    pending.update(receipt_observed=True,
                        receipt_expanded=bool(op.text('已展开',(.14,.25,.235,.30),exact=True)),
                        receipt_screenshot=self.save_frame('purchase_receipt'))
                    main.progress.record('star_shop_purchase_receipt_observed',**pending)
                    main.progress.save('star_shop_purchase_receipt_observed')
                close=main.reward_close_button()
                if close:op.click_box(close,interval=2)
            elif op.text(('站点卡升级','方程展开','祝福强化','获得物品','信标已部署'),(.25,.08,.80,.20)):
                close=main.reward_close_button()
                if close:
                    pending.setdefault('intermediate_receipts',[]).append(self.save_frame('purchase_bonus'))
                    op.click_box(close,interval=2)
        try:
            confirmed=op.wait_until(received,action=receipt,timeout=20,name='商店获得方程并核对扣款')
        except RuntimeError as error:
            if not str(error).startswith('商店获得方程并核对扣款超时'):
                raise
            confirmed=False
        if not confirmed:
            main.progress.record('star_shop_purchase_pending_verification',**pending)
            main.progress.save('star_shop_purchase_pending_verification')
            return False
        pending.update(after_funds=self.funds(),after_screenshot=self.save_frame('purchase_after'),
                       proof='matching_obtain_receipt_and_exact_balance_decrease')
        state.setdefault('purchases',[]).append(dict(pending));state.pop('pending_purchase')
        main.active['star']['choices'].append(dict(kind='equation',title=name,node=main.active['node'],source='shop'))
        main.active['star'].setdefault('observed_equation_requirements',{})[name]=pending['requirements']
        main.progress.record('star_shop_equation_purchased',**pending)
        main.progress.save('star_shop_equation_purchased')
        return True

    def leave(self,expected_run):
        from tasks.base.assets.assets_base_page import GUIDE_CLOSE
        main,op=self.main,self.op
        if not expected_run or (main.active or {}).get('id')!=expected_run:
            raise RequestHumanTakeover('离店原局身份不匹配')
        state=main.active['star'].setdefault('shops',{}).setdefault(str(main.active['node']),{})
        if state.get('pending_purchase'):
            raise RequestHumanTakeover('购物收据尚未核验，保留界面')
        def close_layer():
            if self.visible():
                main.appear_then_click(GUIDE_CLOSE,interval=2)
                return
            exit_button=op.text('离开',(.63,.64,.97,.87))
            if exit_button:
                op.click_box(exit_button,interval=2)
                return
            arrow=op.template('event_next',(.60,.40,.96,.86))
            if arrow:op.click_box(arrow,interval=2)
        op.wait_until(main.world_visible,action=close_layer,timeout=25,name='商店正常返回地图')
        state['done']=True
        main.progress.record('star_shop_left',screenshot=self.save_frame('left'),purchases=len(state.get('purchases',[])))
        main.progress.save('star_shop_left')
        return True

    def buy_equations(self,expected_run):
        from types import SimpleNamespace
        from tasks.divergent_universe.star_workshop import StarWorkshop
        from tasks.divergent_universe.star_policy import star_catalog,rank_star_choices
        main,op=self.main,self.op
        if (not expected_run or (main.active or {}).get('id')!=expected_run
                or main.active.get('station')!='商店' or not main.star_loadout):
            raise RequestHumanTakeover('购买仅适用于指定的拓星商店原局')
        op.snapshot()
        star=main.active['star'];state=star.setdefault('shops',{}).setdefault(str(main.active['node']),{})
        if state.get('pending_purchase'):
            if not self.reconcile_purchase(state):
                return dict(purchased=state.get('purchases',[]),pending=state['pending_purchase'])
        if not self.visible():
            raise RequestHumanTakeover('当前不是已识别的方程商店')
        purchases=state.setdefault('purchases',[])
        for _ in range(max(0,3-len(purchases))):
            previous=None
            def stable_stock():
                nonlocal previous
                rows=StarWorkshop(main).equation_cards()
                names=tuple(name for _,name in rows)
                result=rows if names and names==previous else None
                previous=names
                return result
            try:
                offers=op.wait_until(stable_stock,timeout=6,name='商店商品列表加载')
            except RuntimeError as error:
                if not str(error).startswith('商店商品列表加载超时'):
                    raise
                state['outcome']='empty_or_unreadable_stock'
                break
            eligible=[]
            for box,name in offers:
                if any(row['name']==name for row in purchases):
                    continue
                op.wait_until(lambda:StarWorkshop(main).selected_equation()==name,
                    action=lambda:op.click_box(box,interval=2),timeout=10,name='商店商品选中')
                main.wait_until_stable((875,90,1240,680));op.snapshot()
                fields=self.selected_fields()
                button=op.text('购买',(.78,.87,.97,.95),exact=True)
                if (not fields or fields['name']!=name or fields['cost'] is None or fields['funds'] is None
                        or fields['cost']<=0 or fields['funds']-fields['cost']<50
                        or not button or not main.confirm_enabled(button)):
                    continue
                rarity=star_catalog()['equations'][name]['rarity']
                choice=SimpleNamespace(title=name,rarity=rarity,recommended=False,
                                       requirements=tuple(fields['requirements'].items()))
                score=rank_star_choices([choice],main.star_loadout,'equation',
                    requirements=star.get('observed_equation_requirements'),
                    threshold=star.get('threshold'))[0][1]
                deficit=sum(max(0,need-fields['counts'].get(path,0)) for path,need in fields['requirements'].items())
                core=score[1];ready=deficit==0;affinity=score[2]
                if core or ready or (rarity>=2 and affinity>0 and deficit<=3):
                    eligible.append(dict(fields,box=box,score=(core,ready,affinity,rarity,-deficit,-fields['cost'])))
            if not eligible:
                state['outcome']='no_affordable_matching_equation'
                break
            selected=max(eligible,key=lambda row:row['score'])
            op.wait_until(lambda:StarWorkshop(main).selected_equation()==selected['name'],
                action=lambda:op.click_box(selected['box'],interval=2),timeout=10,name='购买目标复核')
            main.wait_until_stable((875,90,1240,680));op.snapshot()
            before=self.selected_fields();button=op.text('购买',(.78,.87,.97,.95),exact=True)
            if (not before or before['name']!=selected['name'] or before['cost']!=selected['cost']
                    or before['funds'] is None or before['funds']-before['cost']<50
                    or not button or not main.confirm_enabled(button)):
                state['outcome']='purchase_fields_changed'
                break
            pending=dict(before,requested_at=time.time(),before_screenshot=self.save_frame('purchase_before'))
            state['pending_purchase']=pending
            main.progress.record('star_shop_purchase_requested',**pending)
            main.progress.save('star_shop_purchase_requested')
            op.click_box(button,interval=2)
            if not self.reconcile_purchase(state):
                return dict(purchased=purchases,pending=pending)
        return dict(purchased=purchases,outcome=state.get('outcome','purchase_limit_reached'),
                    screenshot=self.save_frame('purchase_finished'))

    def inspect(self,expected_run):
        main,op=self.main,self.op
        active=main.active or {}
        if (not expected_run or active.get('id')!=expected_run or active.get('station')!='商店'
                or not active.get('star')):
            raise RequestHumanTakeover('商店观察仅接管指定拓星原局的实际商店房间')
        timeout=Timer(60,count=3).start()
        moves=scans=interactions=0
        gate_backoffs=0
        last_direction=None
        last_seen=0
        occluded_steps=0
        while not timeout.reached():
            op.snapshot()
            if main.is_combat_executing():
                raise RequestHumanTakeover('商店观察遇到战斗，保留原局交还生产控制器')
            if not main.world_visible():
                if interactions==0:
                    self.save_frame('unexpected_initial_page')
                    raise RequestHumanTakeover('商店观察开始前页面已变化，未发送商店操作')
                # A black loading frame is not a merchant page. Require
                # actual visible text before preserving the inspection.
                header=op.read_region((.025,.015,.58,.15),snapshot=False)
                footer=op.read_region((.55,.77,.98,.95),snapshot=False)
                if header or footer:
                    main.wait_until_stable((40,100,1240,650));op.snapshot()
                    evidence=self.save_frame('inspection')
                    result=dict(screenshot=evidence,header=[b.source for b in header],
                                footer=[b.source for b in footer],purchased=False,
                                native_interactions=interactions,moves=moves,scans=scans)
                    main.progress.record('star_shop_inspected',**result)
                    main.progress.save('star_shop_inspected')
                    return result
                continue
            prompt=self.prompt()
            if prompt:
                main.wait_until_stable((40,130,1050,600));op.snapshot()
                prompt=self.prompt()
                if prompt and interactions<3 and main.interact_with_label(prompt,interval=2):
                    interactions+=1
                continue
            if interactions:
                continue  # Observe the accepted interaction before walking.
            exit_prompt=op.text(('随意门','前往下一区域'),(.58,.48,.92,.70))
            if (exit_prompt or gate_backoffs) and gate_backoffs<self.MAX_GATE_BACKOFFS:
                door=(getattr(main,'find_near_portal',lambda:None)()
                      or getattr(main,'find_door',lambda:None)())
                if door:
                    ratio=1 if door.source in ('door_edge','door_panel') else 4 if door.source.startswith('door_top') else 2.45
                    foot=max(280,min(610,door.top+door.height*ratio))
                    direction=RogueExit.screen2direction((door.center[0],foot),at_floor=True)
                    gate_backoffs+=1;moves+=1
                    main.move((direction+360)%360-180,.6,run=False,interaction_text=self.NAMES)
                    main.progress.record('star_shop_gate_backoff',attempt=gate_backoffs,gate=door.button)
                    continue
            if moves>=24:
                break
            name=op.text(self.NAMES,(.035,.15,.83,.48),exact=True)
            far=False
            if name:
                direction=main.event_direction(name)
            else:
                heads=op.template_matches(str(op.templates/'star_shop_npc_head.png'),
                    (.025,.12,.83,.80),confidence=.86,scales=np.unique(np.r_[np.geomspace(.55,1.5,15),1.]))
                head=max(heads,key=lambda b:b.score,default=None)
                if head:
                    # At close range the NPC's feet can lie below the frame.
                    # Project the observed head/body proportion rather than
                    # continuing toward a gate that would leave her behind.
                    foot=head.top+head.height*5.3
                    direction=RogueExit.screen2direction((head.center[0],foot),at_floor=True)
                    moves+=1
                    main.move(direction,.35,run=False,interaction_text=self.NAMES)
                    continue
                matches=[]
                for template in ('star_shop_npc_world','star_shop_npc_far'):
                    # Animated distant sprites vary more than UI icons.
                    # This lower movement-hint threshold has real positive
                    # (.757) and negative (<=.545) frames; native merchant
                    # name/icon verification is still required to interact.
                    matches.extend(op.template_matches(str(op.templates/f'{template}.png'),
                        (40/1280,120/720,1050/1280,600/720),confidence=.72 if template.endswith('_far') else .88,
                        scales=np.unique(np.r_[np.geomspace(.7,3.4,24),1.])))
                matches=[box for box in matches if box.top+box.height<540]
                target=max(matches,key=lambda b:b.score,default=None)
                if not target:
                    # The observed merchants stand beside the shop exit.
                    # Reuse the existing gate projection to approach that
                    # area, but never interact with the gate during a visit.
                    door=(getattr(main,'find_near_portal',lambda:None)()
                          or getattr(main,'find_door',lambda:None)())
                    if door and not exit_prompt and not gate_backoffs and moves<16:
                        ratio=1 if door.source in ('door_edge','door_panel') else 4 if door.source.startswith('door_top') else 2.45
                        foot=max(280,min(610,door.top+door.height*ratio))
                        direction=RogueExit.screen2direction((door.center[0],foot),at_floor=True)
                        moves+=1
                        main.move(direction,.6,run=True,interaction_text=self.NAMES)
                        continue
                    if last_direction is not None and time.monotonic()-last_seen<6 and occluded_steps<3:
                        moves+=1;occluded_steps+=1
                        main.move(last_direction,.4,run=False,interaction_text=self.NAMES)
                        continue
                    if scans>=8:
                        break
                    scans+=1
                    main.rotation_swipe(45,box=main.ROTATION_BOX)
                    main.wait_until_stable((40,130,1050,560))
                    last_direction=None
                    continue
                direction=RogueExit.screen2direction((target.center[0],target.top+target.height),at_floor=True)
                far=target.height<95
            last_direction=direction;last_seen=time.monotonic();occluded_steps=0
            moves+=1
            main.move(direction,1.0 if far else .5,run=far,interaction_text=self.NAMES)
        evidence=self.save_frame('merchant_not_reached')
        main.progress.record('star_shop_inspection_unavailable',screenshot=evidence,moves=moves,scans=scans)
        raise RequestHumanTakeover('商店NPC的有限观察未完成，已保留原局和现场')
