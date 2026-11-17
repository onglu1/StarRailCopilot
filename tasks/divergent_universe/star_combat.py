"""Observe verified parties; only the Fu Xuan trial has a depletion exit rule."""
import re
import time
from pathlib import Path

import cv2
import numpy as np

from module.base.utils import save_image
from module.exception import RequestHumanTakeover
from tasks.combat.assets.assets_combat_state import COMBAT_PAUSE


def first_health_region(image):
    """Separate the higher skill counter from the right-aligned HP glyphs."""
    original=(206,603,280,626)
    if getattr(image,'shape',())[:2]!=(720,1280):
        return original
    crop=image[603:626,206:280].astype(np.int16)
    white=(crop.min(2)>=170)&(crop.max(2)-crop.min(2)<=45)
    red=(crop[:,:,0]>=160)&(crop[:,:,1]<130)&(crop[:,:,2]<130)&(crop[:,:,0]-crop[:,:,1]>=60)
    _,_,stats,_=cv2.connectedComponentsWithStats((white|red).astype(np.uint8),8)
    # Actual Aglaea 6/6 and 2/6 denominators end above the HP baseline.
    prefix=[x+w for x,y,w,h,_ in stats[1:] if x+w<=14 and y<=3 and h>=7 and y+h<=16]
    if not prefix:
        return original
    digits=[x for x,y,w,h,_ in stats[1:] if w>=2 and h>=7 and y>=4 and 18<=y+h<=21]
    left=max(prefix)+1
    if not digits or min(digits)-left<2:
        return None  # Moon cocoon or touching glyphs are unknown, never zero.
    # Keep every lower-baseline digit, including real five/six-digit HP;
    # never remove a leading character from an OCR result.
    return (206+int(left),603,280,626)


def observe_health(op):
    values=[]
    for right in (280,472,660,848):
        roi=first_health_region(getattr(op,'image',None)) if right==280 else (right-74,603,right,626)
        if roi is None:
            return None
        left,top,end,bottom=roi
        text=op.read_line((left/1280,top/720,end/1280,bottom/720),snapshot=False).source.strip()
        if not re.fullmatch(r'\d{1,6}',text):
            return None
        values.append(int(text))
    return tuple(values)


def depleted_for_long_enough(state, health, now):
    if health is None or any(value is None for value in health):
        return False  # Animations hide the HUD; they are not zero health.
    if health[:3] != (0,0,0) or health[3] <= 0:
        state.clear()
        return False
    if now-state.get('last_seen',now)>30:
        state.clear()
    state.setdefault('first_seen',now)
    state['last_seen']=now
    state['observations']=state.get('observations',0)+1
    return state['observations']>=5 and now-state['first_seen']>=90


class StarCombat:
    def __init__(self,main):
        self.main=main
        self.op=main.op

    def observe(self):
        main=self.main
        star=main.active.get('star',{})
        # member_ids is populated only after StarTeam verifies all four slots.
        members=star.get('member_ids',[])
        if (main.active.get('mode')!='star' or not star.get('candidate')
                or not isinstance(members,(list,tuple)) or len(members)!=4
                or any(type(member) is not int or member<=0 for member in members)
                or len(set(members))!=4):
            return False
        now=time.monotonic()
        key=(main.active['id'],main.active.get('node',0),main.active.get('battles',0))
        if getattr(main,'_star_health_battle',None)!=key:
            main._star_health_battle=key
            main._star_health_last_read=None
            main._star_depleted_health={}
        last_read=getattr(main,'_star_health_last_read',None)
        if last_read is not None and now-last_read<10:
            return False
        main._star_health_last_read=now
        health=observe_health(self.op)
        self.record_health(health,key[1],key[2])
        if star.get('candidate')!='followup_fuxuan' or list(members)!=[1220,8008,1403,1208]:
            return False
        state=main.__dict__.setdefault('_star_depleted_health',{})
        if not depleted_for_long_enough(state,health,now):
            return False
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        image=folder/f'combat_depleted_{main.active.get("node",0)}.png'
        save_image(self.op.image,image)
        main.active.update(stop_requested=True,exit_reason='combat_damage_slots_depleted')
        main.progress.record('star_combat_depleted',health=health,seconds=now-state['first_seen'],screenshot=str(image))
        main.progress.save('combat_depleted')
        return self.withdraw()

    def record_health(self,health,node,battle_index):
        """Bounded first/last/zero summaries, not death timestamps or new frames."""
        main=self.main;star=main.active['star'];now=time.time()
        key=f'{node}:{battle_index}'
        state=star.setdefault('combat_health',{}).setdefault(key,dict(
            node=node,battle_index=battle_index,member_ids=list(star['member_ids']),
            samples=0,valid_samples=0,unknown_samples=0,observed_zero={}))
        # Elapsed measures wall time since the first observed frame, including
        # any pauses/reloads. It does not claim the exact combat start time.
        elapsed=round(max(0,now-state.get('first',{}).get('time',now)),3)
        valid=(health is not None and len(health)==4
               and all(type(value) is int and value>=0 for value in health))
        zeros=[slot+1 for slot,value in enumerate(health) if value==0] if valid else None
        sample=dict(time=now,elapsed=elapsed,health=list(health) if health is not None else None,
                    observed_zero_slots=zeros)
        state.setdefault('first',sample)
        state['last']=sample
        state['samples']+=1
        state['valid_samples' if valid else 'unknown_samples']+=1
        changed=valid and zeros!=state.get('last_valid_zero_slots')
        if valid:
            state['last_valid_zero_slots']=zeros
            for slot in zeros:
                observed=state['observed_zero'].setdefault(str(slot),dict(
                    member_id=star['member_ids'][slot-1],first=dict(time=now,elapsed=elapsed),observations=0))
                observed['last']=dict(time=now,elapsed=elapsed)
                observed['observations']+=1
        initial='last_recorded_at' not in state
        if initial or changed or now-state['last_recorded_at']>=30:
            state['last_recorded_at']=now
            # Keep small, unparsed context crops on the existing health cadence.
            # The selected target can change or disappear during animations;
            # these images do not claim the complete enemy roster or a victory.
            context={}
            if getattr(self.op.image,'shape',())[:2]==(720,1280):
                folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
                folder.mkdir(parents=True,exist_ok=True)
                capture_id=time.time_ns()
                for label,roi in (('target',(480,12,995,56)),('wave',(44,6,120,32))):
                    left,top,right,bottom=roi
                    path=folder/f'combat_{label}_{node}_{battle_index}_{capture_id}.png'
                    save_image(self.op.image[top:bottom,left:right],path)
                    context[label]=dict(screenshot=str(path),roi=roi)
            sample['context']=context
            main.progress.record('star_combat_health_observed',node=node,battle_index=battle_index,
                                 elapsed=elapsed,elapsed_basis='since_first_observed_frame',
                                 health=sample['health'],observed_zero_slots=zeros,
                                 context=context,
                                 reason=('initial_observation' if initial else
                                         'observed_zero_slots_changed' if changed else 'periodic_observation'))
            main.progress.save()

    def withdraw(self):
        main,op=self.main,self.op
        # Use the native combat pause asset. Only observed retreat controls
        # can follow it; do not synthesize back/escape or alter the result.
        main.appear_then_click(COMBAT_PAUSE,interval=2)
        def menu():
            return op.text(('撤退','退出战斗','终止战斗并结算'),(.12,.30,.90,.96),exact=True)
        try:
            button=op.wait_until(menu,timeout=12,name='战斗撤退菜单')
        except RuntimeError:
            folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
            save_image(op.image,folder/'combat_pause_unrecognized.png')
            raise RequestHumanTakeover('战斗停滞已保存；暂停菜单尚未识别撤退控件')
        op.click_box(button,interval=2)
        def finish():
            if main.world_visible() or main.settlement_title():
                return True
            return False
        def confirm():
            prompt=op.text(('撤退','终止战斗','退出战斗'),(.15,.15,.90,.66))
            if prompt:
                return op.click_text(('确认','确定'),(.5,.5,.85,.9),exact=True,interval=2)
            return False
        op.wait_until(finish,action=confirm,timeout=35,name='撤退返回探索或结算')
        return True
