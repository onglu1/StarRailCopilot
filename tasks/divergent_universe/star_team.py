"""Identify candidate members with SRC character assets in DU's download list."""
from pathlib import Path
import json

import cv2
import numpy as np

from module.base.timer import Timer
from module.exception import RequestHumanTakeover
from tasks.character.keywords import CharacterList
from tasks.currency_wars.operator import Box


class TeamMismatch(RequestHumanTakeover):
    pass


class StarTeam:
    PANEL = (25, 124, 468, 635)

    def __init__(self, preparation):
        self.preparation = preparation
        self.main = preparation.main
        self.op = preparation.op
        self.assets = Path(__file__).resolve().parents[2] / 'assets/character'
        self._portraits = {}

    def portrait(self, path):
        """Match the unobscured face; retain a whole-portrait identity check."""
        if path not in self._portraits:
            from tasks.combat.support import SupportCharacter
            image = cv2.cvtColor(SupportCharacter.load_image(str(path)), cv2.COLOR_RGB2GRAY)
            self._portraits[path] = [cv2.resize(image, None, fx=s, fy=s)
                                    for s in np.linspace(1.05, 1.16, 12)]
        frame = cv2.cvtColor(self.op.image[116:616, 25:468], cv2.COLOR_RGB2GRAY)
        best = None
        for sample in self._portraits[path]:
            h, w = sample.shape
            # Trial and selected-slot badges cover the upper corners. The
            # central lower face retains the native pixels and scale.
            x1, y1, x2, y2 = round(w*20/86), round(h*28/81), round(w*78/86), round(h*78/81)
            face = sample[y1:y2, x1:x2]
            values = cv2.matchTemplate(frame, face, cv2.TM_CCOEFF_NORMED)
            for _ in range(4):
                _, score, _, point = cv2.minMaxLoc(values)
                if score < .84:
                    break
                x, y = point[0]-x1, point[1]-y1
                if 0 <= x <= frame.shape[1]-w and 0 <= y <= frame.shape[0]-h:
                    whole = cv2.matchTemplate(frame[y:y+h, x:x+w], sample, cv2.TM_CCOEFF_NORMED)[0, 0]
                    candidate = Box(x+25, y+116, w, h, path.stem, float(score))
                    # A trial label plus selected-slot badge obscures both
                    # corners; require the independent numbered-white-border
                    # proof before accepting that lower full-image score.
                    accepted = whole >= .70 or (whole >= .64 and score >= .86
                                                and self.selected_slot({'box': candidate.button}))
                    if accepted and (best is None or score > best.score):
                        best = candidate
                px, py = point
                values[max(0,py-h//2):py+h//2+1, max(0,px-w//2):px+w//2+1] = 0
        return best

    def candidates(self, ids):
        result = {}
        for identity in ids:
            character = CharacterList.instances[identity]
            names = ([f'Stelle{character.name[11:]}', f'Caelum{character.name[11:]}']
                     if character.is_trailblazer else [character.name])
            names += [p.stem for name in list(names) for p in sorted(self.assets.glob(f'{name}.*.png'))]
            for name in names:
                path = self.assets / f'{name}.png'
                if not path.exists():
                    continue
                box = self.portrait(path)
                if box:
                    result[identity] = dict(id=identity, name=character.cn, asset=name,
                                            box=box.button, score=box.score)
                    break
        return result

    def scroll(self, up=False):
        from module.ui.scroll import Scroll
        self.op.snapshot()
        bar = Scroll((478,126,482,615),(134,134,134),name='DU_STAR_CHARACTER_SCROLL')
        current = bar.cal_position(self.main)
        if not 20 <= bar.length <= 200:
            raise RequestHumanTakeover('未核对到角色列表滚动条')
        target = 0 if up else min(1,current+.70*bar.length/(bar.total-bar.length))
        if abs(target-current)<.015:
            return False
        def point(position):
            a=bar.position_to_screen(position,random_range=(0,0))
            return ((a[0]+a[2])//2,(a[1]+a[3])//2)
        self.main.device.drag(point(current),point(target),point_random=(0,0,0,0),name=bar.name)
        self.main.wait_until_stable(self.PANEL)
        self.op.snapshot()
        moved = abs(bar.cal_position(self.main)-current)>.005
        if moved:
            self.main.device.stuck_record_clear()
            self.main.device.click_record_clear()
        # A swallowed drag is not the end of the list. The callers already
        # bound their retries; only the observed boundary above returns False.
        return True

    def inspect_candidates(self, guide):
        from tasks.divergent_universe.star_policy import decode_guide_plan
        self.reset_list()
        plan = decode_guide_plan(guide['code'])
        wanted = list(dict.fromkeys(x for team in plan['teams'] for slot in team for x in slot))
        scan_name=guide['key']
        if any(CharacterList.instances[x].is_trailblazer for x in wanted):
            wanted=list(dict.fromkeys(wanted+[c.id for c in CharacterList.instances.values() if c.is_trailblazer]))
            scan_name+='_trailblazers'
        timeout = Timer(100, count=3).start()
        found = {}
        for page in range(14):
            self.op.check()
            self.op.snapshot()
            if not self.op.text('角色列表', (.045, .10, .18, .16), exact=True):
                raise RequestHumanTakeover('角色列表页面已变化，停止扫描')
            new = self.candidates([x for x in wanted if x not in found])
            screenshot = str(self.preparation.observe(f'team_candidates_{scan_name}_{page}'))
            if new:
                for item in new.values():
                    item['screenshot'] = screenshot
                    item['availability_confirmed'] = False
                found.update(new)
            if len(found) == len(wanted) or timeout.reached() or not self.scroll():
                break
        result = dict(candidate=guide['key'], found=list(found.values()),
                      missing=[CharacterList.instances[x].cn for x in wanted if x not in found],
                      members_verified=False, scope='Visible native portraits only; not a selected-team verification')
        path = self.preparation.observe('team_scan_' + scan_name)
        path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    def reset_list(self):
        self.op.snapshot()
        if not self.op.text('筛选规则', (.12, .15, .42, .24), exact=True):
            self.preparation.open_team()
            control = self.op.template('star_character_filter', (.015, .875, .065, .96), confidence=.90)
            if not control:
                raise RequestHumanTakeover('未识别角色筛选按钮')
            self.op.click_box(control)
            self.op.wait_until(lambda: self.op.text('筛选规则', (.12,.15,.42,.24), exact=True), timeout=10)
        clear = self.op.wait_until(lambda: self.op.text('全部清除', (.24,.77,.49,.85)), timeout=10)
        self.op.click_box(clear)
        self.op.wait_until(lambda: self.op.text('角色列表', (.045,.10,.18,.16), exact=True),
                           action=lambda: self.op.click_text('确认', (.52,.77,.76,.85), interval=2), timeout=10)
        self.top()

    def top(self):
        for _ in range(14):
            if not self.scroll(up=True):
                return
        raise RequestHumanTakeover('角色列表无法在预算内回到顶部')

    def selected_cards(self):
        """Find numbered selected cards, including drafts not sorted to top."""
        if not self.op.text('角色列表', (.045,.10,.18,.16), exact=True):
            raise RequestHumanTakeover('角色列表已离开，停止调整阵容')
        cards = []
        for x in (32, 144, 256, 368):
            roi = cv2.cvtColor(self.op.image[116:616, x-5:x+18], cv2.COLOR_RGB2GRAY)
            for slot in range(1,5):
                sample = cv2.imread(str(Path(__file__).parent / 'templates' / f'star_slot_{slot}.png'), 0)
                scores = cv2.matchTemplate(roi, sample, cv2.TM_CCOEFF_NORMED)
                for _ in range(4):
                    _, score, _, (px,py) = cv2.minMaxLoc(scores)
                    if score < .90:
                        break
                    cx,cy = x-5+px+1,116+py+1
                    box = Box(cx,cy,95,90,'DU_STAR_SELECTED_MEMBER')
                    if cy+90 < 630 and self.selected_slot({'box': box.button}) == slot:
                        if all(box.distance(old)>30 for old in cards):
                            cards.append(box)
                    scores[max(0,py-20):py+21,:]=0
        return sorted(cards,key=lambda c:(c.top,c.left))

    def set_team(self, guide, allow_path_change=True):
        ids = guide.get('selected_team_ids') or [slot[0] for slot in guide['decoded']['teams'][0]]
        if len(ids) != 4 or len(set(ids)) != 4:
            raise ValueError('实际候选阵容必须有四名不同角色')
        self.reset_list()
        cleared = 0
        for _ in range(16):
            self.op.snapshot()
            while (cards := self.selected_cards()):
                count = len(cards)
                self.op.click_box(cards[0])
                self.op.wait_until(lambda: len(self.selected_cards()) == count-1,
                                   timeout=12, name='取消旧阵容成员')
                cleared += 1
                if cleared > 4:
                    raise RequestHumanTakeover('取消成员次数异常')
            if cleared == 4 or not self.scroll():
                break
        for identity in ids:
            self.top()
            for _ in range(14):
                self.op.snapshot()
                found = self.candidates([identity])
                if found:
                    item = found[identity]
                    x1,y1,x2,y2 = item['box']
                    self.op.click_box(Box(x1,y1,x2-x1,y2-y1, item['name']))
                    self.main.wait_until_stable(self.PANEL)
                    self.op.snapshot()
                    self.preparation.observe('team_added_' + str(identity))
                    break
                if not self.scroll():
                    if identity==8008 and allow_path_change:
                        self.main.progress.record('star_trailblazer_path_preparation_requested',requested_id=8008)
                        self.inspect_trailblazer_details()
                        self.inspect_trailblazer_path()
                        self.inspect_path_selector()
                        self.change_to_remembrance()
                        return self.set_team(guide,allow_path_change=False)
                    self.preparation.observe('team_missing_' + str(identity))
                    raise RequestHumanTakeover(f'完整列表未核对到目标角色{CharacterList.instances[identity].cn}')
            else:
                raise RequestHumanTakeover('角色扫描超过预算')
        return self.verify_team(guide)

    def verify_team(self, guide):
        ids = guide.get('selected_team_ids') or [slot[0] for slot in guide['decoded']['teams'][0]]
        self.preparation.open_team()
        # Back cancels the draft team. Verify numbered selected badges in
        # this editor, then enter star mode directly to retain the selection.
        self.top()
        observed, screenshots = {}, []
        for page in range(16):
            self.op.snapshot()
            for identity, item in self.candidates(ids).items():
                slot = self.selected_slot(item)
                if slot:
                    if slot in observed and observed[slot] != identity:
                        raise RequestHumanTakeover('两名角色匹配同一队伍位置，停止')
                    observed[slot] = identity
                    screenshots.append(str(self.preparation.observe(f'team_proof_{guide["key"]}_{slot}')))
            if len(observed) == 4 or not self.scroll():
                break
        actual = [observed.get(slot) for slot in range(1,5)]
        path = self.preparation.observe('team_verified_' + guide['key'])
        if actual != ids:
            raise TeamMismatch(f'实际下载角色{actual}与目标{ids}不一致')
        result = dict(candidate=guide['key'], member_ids=actual,
                      members=[CharacterList.instances[i].cn for i in actual],
                      members_verified=True, screenshot=str(path), member_screenshots=screenshots)
        path.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2), encoding='utf-8')
        return result

    def selected_slot(self, item):
        x,y,x2,y2 = item['box']
        # A selected white outline and its numbered circle must agree.
        white = np.all(self.op.image[y+24:y2-8, max(0,x-2):x+2] > 220, axis=2)
        if not white.size or white.mean() < .4 or y < 116:
            return None
        roi = cv2.cvtColor(self.op.image[y-6:y+25, max(0,x-6):x+22], cv2.COLOR_RGB2GRAY)
        matches = []
        for slot in range(1,5):
            path = Path(__file__).parent / 'templates' / f'star_slot_{slot}.png'
            sample = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            score = cv2.minMaxLoc(cv2.matchTemplate(roi, sample, cv2.TM_CCOEFF_NORMED))[1]
            matches.append((score,slot))
        matches.sort(reverse=True)
        return matches[0][1] if matches[0][0] >= .80 and matches[0][0]-matches[1][0] >= .08 else None

    def inspect_filter(self):
        self.op.snapshot()
        if not self.op.text('筛选规则', (.12, .15, .42, .24), exact=True):
            self.preparation.open_team()
            control = self.op.template('star_character_filter', (.015, .875, .065, .96), confidence=.90)
            if not control:
                raise RequestHumanTakeover('角色筛选按钮未识别，停止准备')
            self.op.click_box(control)
        self.op.wait_until(lambda: self.op.text(('筛选', '筛选条件'), (.08, .06, .93, .60)),
                           timeout=15, name='角色筛选界面')
        path = self.preparation.observe('team_filter')
        result = {'page': 'team_filter', 'labels': [dict(text=b.source, box=b.button)
                  for b in self.op.read_region((0.02, .02, .98, .95), snapshot=False)]}
        path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        self.main.device.swipe((852, 483), (852, 235), name='DU_STAR_FILTER_OPTIONS')
        self.main.wait_until_stable((165, 177, 1118, 541))
        self.op.snapshot()
        bottom = self.preparation.observe('team_filter_bottom')
        result['bottom_labels'] = [dict(text=b.source, box=b.button)
                                   for b in self.op.read_region((.12, .16, .88, .84), snapshot=False)]
        bottom.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    def inspect_trailblazer_details(self):
        """Inspect the downloaded character UI; do not launch a wrong path."""
        if self.main.progress.data.get('active'):
            raise RequestHumanTakeover('主角命途准备只在原局已正常结算后进行')
        self.preparation.open_team()
        self.top()
        found=None
        ids=[c.id for c in CharacterList.instances.values() if c.is_trailblazer]
        for _ in range(14):
            self.op.snapshot()
            rows=self.candidates(ids)
            if rows:
                identity,found=next(iter(rows.items()))
                break
            if not self.scroll():
                break
        if not found:
            raise RequestHumanTakeover('完整列表没有核对到当前主角头像')
        if not self.selected_slot(found):
            x1,y1,x2,y2=found['box']
            self.op.click_box(Box(x1,y1,x2-x1,y2-y1,found['name']))
            self.main.wait_until_stable(self.PANEL);self.op.snapshot()
        button=self.op.text('查看详情',(.58,.78,.75,.85),exact=True)
        if not button:
            raise RequestHumanTakeover('当前下载角色页没有查看详情控件')
        self.op.click_box(button)
        self.op.wait_until(lambda:self.op.text('角色详情',(.035,.01,.20,.055),exact=True),
                           timeout=15,name='实际角色详情页')
        self.main.wait_until_stable((520,90,1230,650));self.op.snapshot()
        path=self.preparation.observe('trailblazer_details')
        result=dict(current_candidate=identity,screenshot=str(path),run_started=False,
                    labels=[dict(text=b.source,box=b.button) for region in ((.035,.01,.35,.10),(.70,.85,.97,.96))
                            for b in self.op.read_region(region,snapshot=False)])
        path.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result

    def inspect_trailblazer_path(self):
        from tasks.combat.support import SupportCharacter
        if self.main.progress.data.get('active'):
            raise RequestHumanTakeover('命途准备不能覆盖进行中的探索')
        self.op.snapshot()
        if not self.op.text('角色详情',(.035,.01,.20,.055),exact=True):
            raise RequestHumanTakeover('需要已打开的角色详情页')
        frame=cv2.cvtColor(self.op.image[70:630,15:105],cv2.COLOR_RGB2GRAY)
        found=[]
        for identity in (8002,8004,8006,8008,8010):
            character=CharacterList.instances[identity]
            for stem in (f'Stelle{character.name[11:]}',f'Caelum{character.name[11:]}'):
                path=self.assets/f'{stem}.png'
                if not path.exists():
                    continue
                original=cv2.cvtColor(SupportCharacter.load_image(str(path)),cv2.COLOR_RGB2GRAY)
                for scale in np.linspace(.60,.72,25):
                    sample=cv2.resize(original,None,fx=scale,fy=scale);h,w=sample.shape
                    x1,y1,x2,y2=round(w*20/86),round(h*25/81),round(w*76/86),round(h*76/81)
                    face=sample[y1:y2,x1:x2]
                    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(frame,face,cv2.TM_CCOEFF_NORMED))
                    if score>=.88:
                        found.append((score,identity,Box(point[0]+15,point[1]+70,face.shape[1],face.shape[0],stem)))
        if not found:
            raise RequestHumanTakeover('未在详情栏核对到主角头像')
        score,identity,box=max(found,key=lambda x:x[0])
        expected={8002:'毁灭',8004:'存护',8006:'同谐',8008:'记忆',8010:'欢愉'}[identity]
        self.op.wait_until(lambda:self.op.text(expected,(.065,.045,.16,.09)),
                          action=lambda:self.op.click_box(box,interval=2),timeout=12,name='主角详情命途核对')
        path=self.preparation.observe('trailblazer_path_controls')
        result=dict(current_candidate=identity,path_name=expected,avatar_score=float(score),
                    screenshot=str(path),run_started=False,
                    labels=[dict(text=b.source,box=b.button) for region in ((.035,.01,.35,.10),(.70,.85,.97,.96))
                            for b in self.op.read_region(region,snapshot=False)])
        path.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result

    def inspect_path_selector(self):
        if self.main.progress.data.get('active'):
            raise RequestHumanTakeover('命途准备不能覆盖进行中的探索')
        self.op.snapshot()
        button=self.op.text('切换',(.77,.87,.96,.96),exact=True)
        if not self.op.text('角色详情',(.035,.01,.20,.055),exact=True) or not button:
            raise RequestHumanTakeover('需要主角详情页的实际切换按钮')
        self.op.wait_until(lambda:self.op.text('记忆',(.01,.10,.35,.92),exact=True),
                          action=lambda:self.op.click_box(button,interval=2),timeout=12,name='主角命途选项')
        path=self.preparation.observe('trailblazer_path_selector')
        result=dict(screenshot=str(path),path_switched=False,run_started=False,
                    labels=[dict(text=b.source,box=b.button) for region in ((.035,.01,.35,.10),(.01,.10,.35,.92),(.70,.85,.97,.96))
                            for b in self.op.read_region(region,snapshot=False)])
        path.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result

    def change_to_remembrance(self):
        if self.main.progress.data.get('active'):
            raise RequestHumanTakeover('命途准备不能覆盖进行中的探索')
        op=self.op
        op.snapshot()
        if not op.text('命途切换',(.035,.045,.24,.10),exact=True):
            raise RequestHumanTakeover('需要实际主角命途切换页')
        def selected():
            return op.text('记忆',(.105,.56,.29,.69),exact=True)
        def choose():
            label=op.text('记忆',(.035,.15,.35,.76),exact=True)
            if label:
                # Observed radial options place their icon above the caption.
                return op.click_point(label.center[0]/1280,(label.center[1]-55)/720,
                                      tag='DU_TRAILBLAZER_REMEMBRANCE',interval=2)
            return False
        op.wait_until(selected,action=choose,timeout=15,name='记忆命途选中')
        def applied():
            return (selected() and op.text('当前选择',(.70,.85,.97,.96),exact=True)) or (
                op.text('记忆',(.065,.045,.17,.09)) and not op.text('命途切换',(.035,.045,.24,.10),exact=True))
        def apply():
            if self.main.handle_popup_confirm(interval=2):
                return True
            return op.click_text('切换',(.70,.85,.97,.96),exact=True,interval=2)
        op.wait_until(applied,action=apply,timeout=15,name='记忆命途实际应用')
        proof=self.preparation.observe('trailblazer_remembrance_applied')
        self.main.progress.record('star_trailblazer_path_applied',requested_id=8008,screenshot=str(proof))
        op.wait_until(lambda:op.text('角色列表',(.045,.10,.18,.16),exact=True),
                      action=op.back,timeout=20,name='返回下载角色列表')
        result=dict(path_surface_verified=True,requested_id=8008,screenshot=str(proof),team_verified=False,run_started=False)
        proof.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result
