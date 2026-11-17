"""Read the game's own path totals without deriving them from reward logs."""
from pathlib import Path
from itertools import product
import re
import time

from module.base.utils import save_image
from module.exception import RequestHumanTakeover
from tasks.currency_wars.operator import normalize


class InventoryPageChanged(Exception):
    """The original reward has already returned to gameplay."""


class InventoryCountsUnverified(Exception):
    """One frame does not supply a unique, total-consistent inventory."""


class StarInventory:
    PATHS={'繁育','虚无','巡猎','同谐','欢愉','毁灭','智识','记忆'}

    def __init__(self,main):
        self.main=main
        self.op=main.op

    def blessing_page(self):
        title=normalize(self.op.read_line((.065,.048,.24,.093),snapshot=False).source)
        return title.startswith('祝福/') and title[3:] in self.PATHS|{'全部'}

    def observe_equations(self):
        """Record visible game status; owning an equation is not expansion."""
        from tasks.divergent_universe.star_policy import catalog_name,star_catalog
        op,main=self.op,self.main
        tabs=op.read_region((.12,.12,.31,.166),snapshot=False)
        counts={}
        for box in tabs:
            match=re.fullmatch(r'(已展开|未展开)(\d+)',normalize(box.source))
            if match and 0<=int(match[2])<=200:
                counts['expanded' if match[1]=='已展开' else 'unexpanded']=int(match[2])
        if len(counts)!=2:
            return  # Transient/unknown text supplies no expansion evidence.
        heading=normalize(op.read_line((.12,.195,.37,.245),snapshot=False).source)
        if counts['expanded'] and heading!='已展开方程':
            expanded_tab=next((b for b in tabs if normalize(b.source).startswith('已展开')),None)
            if expanded_tab:
                try:
                    op.wait_until(lambda:normalize(op.read_line((.12,.195,.37,.245),snapshot=False).source)=='已展开方程',
                                  action=lambda:op.click_box(expanded_tab,interval=2),timeout=8,
                                  name='已展开方程页签')
                except RuntimeError:
                    # This optional observation must not turn an unreadable
                    # tab into invented expansion or block the real reward.
                    main.progress.record('star_equation_tab_unverified')
                heading=normalize(op.read_line((.12,.195,.37,.245),snapshot=False).source)
        tab='expanded' if heading=='已展开方程' else 'unexpanded' if heading=='未展开方程' else None
        table=star_catalog()['equations']
        visible=[]
        expanded=[]
        if tab:
            # The tabs scroll to a group; they do not filter the entire row.
            # A visible unexpanded core can sit beside the expanded group.
            # Require its own in-card label, below the group headers.
            markers=op.match('已展开',(.11,.265,.97,.325),exact=True)
            for box in op.read_region((.12,.477,.97,.535),snapshot=False):
                name=catalog_name(box.source,table)
                if name and name not in visible:
                    visible.append(name)
                    if any(abs(marker.center[0]-box.center[0])<150 for marker in markers):
                        expanded.append(name)
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'equation_inventory_{main.active.get("node",0)}_{time.time_ns()}.png'
        save_image(op.image,path)
        result=dict(counts=counts,visible_tab=tab,visible_names=visible,node=main.active.get('node',0),
                    screenshot=str(path),visible_only=True)
        result['visible_expanded_names']=expanded
        result['visible_expanded_core']=[n for n in expanded if n in main.star_loadout.core_equations]
        result['expansion_evidence']='individual_card_marker'
        result['decision_watermark']=dict(run_id=main.active.get('id'),
            session=getattr(main.progress,'session_id',None),node=main.active.get('node'),
            selection=main.active.get('selections'),choice_index=len(main.active['star'].get('choices',[])),
            observation=time.time_ns())
        main.active['star']['equation_inventory']=result
        main.progress.record('star_equation_inventory_observed',**result)
        main.progress.save('star_equation_inventory_observed')
        return result

    def read(self, close=True, force=False):
        try:
            return self._read(close,force)
        except InventoryPageChanged:
            self.main.progress.record('star_inventory_page_changed',reason='reward_already_left')
            return None

    def wait_inventory(self,predicate,**kwargs):
        def detected():
            if self.main.world_visible() or self.main.is_combat_executing():
                raise InventoryPageChanged
            return predicate()
        return self.op.wait_until(detected,**kwargs)

    def _read(self, close=True, force=False):
        main,op=self.main,self.op
        op.snapshot()
        if main.world_visible() or main.is_combat_executing():
            raise InventoryPageChanged
        if (close and not force and op.text('拥有祝福',(.02,.03,.14,.08),exact=True) and main.active['star'].get('inventory_observed')
                and main.active['star'].get('inventory_choice_index') is not None
                and main.active['star'].get('inventory_node')==main.active.get('node',0)):
            self.close()
            return main.active['star']['path_counts']
        equations=None
        if not self.blessing_page():
            if op.text(('方程','地图','奇物','加权奇物','沿途站点'),(.035,.035,.20,.10),exact=True):
                control=self.wait_inventory(lambda:op.template('star_inventory_second_tab',(.02,.24,.08,.35),confidence=.92),
                                      timeout=12,name='祝福分类控件出现')
                if op.text('方程',(.035,.035,.20,.10),exact=True):
                    equations=self.observe_equations()
                op.click_box(control)
            else:
                self.wait_inventory(lambda:op.text('拥有祝福',(.02,.03,.14,.08),exact=True),
                    action=lambda:op.click_text('查看祝福与方程',(.67,.015,.87,.08),exact=True,interval=3),
                    timeout=15,name='拥有祝福概览')
                op.click_text('查看方程详情',(.84,.02,.97,.09),exact=True)
                self.wait_inventory(lambda:op.text('方程',(.035,.035,.20,.10),exact=True),
                              action=lambda:op.click_text('查看方程详情',(.84,.02,.97,.09),exact=True,interval=2),
                              timeout=12,name='实际方程详情页面')
                control=self.wait_inventory(lambda:op.template('star_inventory_second_tab',(.02,.24,.08,.35),confidence=.92),
                                      timeout=12,name='祝福分类控件出现')
                equations=self.observe_equations()
                op.click_box(control)
            self.wait_inventory(self.blessing_page,
                          action=lambda:op.click_box(op.template('star_inventory_second_tab',(.02,.24,.08,.35),confidence=.92),interval=2),
                          timeout=12,name='祝福库存列表')
        order=main.progress.data.get('star_path_order')
        if not order or len(order)!=8 or set(order)!=self.PATHS:
            order=[]
            for index in range(8):
                # These are the eight observed path tabs in the verified
                # blessing page. Read their actual titles before assigning
                # meaning to the corresponding numeric fields.
                op.click_point((284+index*100)/1280,101/720,tag=f'DU_INVENTORY_PATH_{index}',interval=1)
                def title():
                    value=normalize(op.read_line((.065,.048,.23,.09),snapshot=False).source)
                    matches=[path for path in self.PATHS if value.endswith(path)]
                    return matches[0] if len(matches)==1 and matches[0] not in order else None
                name=self.wait_inventory(title,timeout=8,name='祝福分类名称')
                order.append(name)
            main.progress.data['star_path_order']=order
            main.progress.record('star_path_order_observed',order=order)
        counts,total=self.read_counts(order)
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'blessing_inventory_{main.active.get("node",0)}_{time.time_ns()}.png'
        save_image(op.image,path)
        main.active['star'].update(inventory_observed=True,path_counts=counts,
                                  inventory_node=main.active.get('node',0),inventory_screenshot=str(path),
                                  inventory_path_counts=dict(counts),
                                  inventory_total=total,
                                  inventory_choice_index=len(main.active['star'].get('choices',[])),
                                  inventory_equation_watermark=(dict(equations['decision_watermark'])
                                      if equations else None))
        main.progress.record('star_inventory_observed',counts=counts,total=total,screenshot=str(path))
        main.progress.save('star_inventory_observed')
        if close:
            if main.active.get('node',0)>0 and not main.active['star'].get('curio_inventory'):
                main.active['star']['curio_inventory']=self.observe_curios()
                main.progress.save('star_curio_inventory_observed')
            self.close()
        return counts

    def read_counts(self,order):
        """Retry three independent frames, then use the bounded recovery path."""
        reason='blessing_page_unconfirmed'
        for attempt in range(1,4):
            self.op.snapshot()
            if self.main.world_visible() or self.main.is_combat_executing():
                raise InventoryPageChanged
            if self.blessing_page():
                try:
                    return self.read_counts_frame(order)
                except InventoryCountsUnverified:
                    reason='same_frame_total_unreadable_or_not_unique'
            else:
                reason='blessing_page_unconfirmed'
            self.main.progress.record('star_inventory_counts_retry',attempt=attempt,reason=reason)
        raise RuntimeError(f'实际祝福数量连续3帧未能一致读取，交还有界恢复：{reason}')

    def read_counts_frame(self,order):
        """Resolve only same-frame numeric readings against the visible total."""
        op=self.op
        def number(text,maximum=200):
            value=normalize(text)
            return int(value) if re.fullmatch(r'\d{1,4}',value) and int(value)<=maximum else None
        raw={}
        for index,name in enumerate(order):
            x=284+index*100
            raw[name]=op.read_line(((x+12)/1280,101/720,(x+49)/1280,122/720),snapshot=False).source
        # The wider field preserves tens but can include the All-tab icon
        # (6 -> 26). The tighter field excludes it but can drop tens (41 ->
        # 1). Neither has authority alone: retain both actual OCR candidates.
        total_readings=[]
        for left in (194,198):
            text=op.read_line((left/1280,101/720,224/1280,122/720),snapshot=False).source
            total_readings.append(dict(roi=[left,101,224,122],text=text))
        totals={value for reading in total_readings if (value:=number(reading['text'],1600)) is not None}
        values={name:number(text) for name,text in raw.items()}
        expanded={}
        candidates={name:{value} if value is not None else set() for name,value in values.items()}
        # Complete the same-frame category candidates even if both original
        # total crops failed; a later total must not rely on truncated tens.
        for index,name in enumerate(order):
            x=284+index*100
            expanded[name]=op.read_line(((x+6)/1280,101/720,(x+49)/1280,122/720),snapshot=False).source
            value=number(expanded[name])
            if value is not None:
                candidates[name].add(value)
        def matching_counts():
            solutions=[]
            for row in product(*(sorted(candidates[name]) for name in order)):
                total=sum(row)
                if total in totals:
                    solutions.append((dict(zip(order,row)),total))
                    if len(solutions)>1:
                        break
            return solutions
        solutions=matching_counts()
        if len(solutions)!=1:
            # Actual 17 was read as "1.7" beside the All icon/underline;
            # the tighter original crop lost the 1 entirely. Preserve its
            # full glyph from x193 while excluding the underline at y118.
            roi=(193,104,224,118)
            text=op.read_line((roi[0]/1280,roi[1]/720,roi[2]/1280,roi[3]/720),snapshot=False).source
            total_readings.append(dict(roi=list(roi),text=text))
            value=number(text,1600)
            if value is not None:
                totals.add(value)
            solutions=matching_counts()
        if len(solutions)==1:
            counts,total=solutions[0]
            if counts!=values or len(totals)>1 or len(total_readings)>2:
                self.main.progress.record('star_inventory_counts_reconciled',counts=counts,total=total,
                                          raw=raw,expanded=expanded,total_readings=total_readings,
                                          reason='unique_same_frame_total')
            return counts,total
        self.main.progress.record('star_inventory_counts_unverified',raw=raw,expanded=expanded,
                                  total_text=total_readings[0]['text'],total_readings=total_readings,
                                  reason='same_frame_total_unreadable_or_not_unique')
        raise InventoryCountsUnverified

    def inspect_curios(self):
        """Observe the real inventory from a reward page, without changing items."""
        main,op=self.main,self.op
        if not (main.active or {}).get('star'):
            raise RequestHumanTakeover('奇物检查需要保留中的拓星原局')
        op.snapshot()
        if not op.text('奇物',(.035,.035,.20,.10),exact=True):
            self.read(close=False)
        result=self.observe_curios()
        self.close()
        return result

    def observe_curios(self):
        """Save the observed curio page once; no effect/curse is inferred from icons."""
        main,op=self.main,self.op
        if not op.text('奇物',(.035,.035,.20,.10),exact=True):
            control=op.wait_until(lambda:op.template('star_inventory_curio_tab',(.02,.73,.08,.84),confidence=.92),
                                  timeout=10,name='奇物库存分类控件')
            op.wait_until(lambda:op.text('奇物',(.035,.035,.20,.10),exact=True),
                          action=lambda:op.click_box(control,interval=2),timeout=12,name='实际奇物库存页')
        main.wait_until_stable((130,130,1230,640));op.snapshot()
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'curio_inventory_{main.active.get("node",0)}.png'
        save_image(op.image,path)
        result=dict(screenshot=str(path),node=main.active.get('node'),effects_verified=False)
        main.progress.record('star_curio_inventory_observed',**result)
        return result

    def close(self):
        op=self.op
        from tasks.base.assets.assets_base_page import GUIDE_CLOSE
        def visible_layer():
            if self.main.world_visible() or self.main.is_combat_executing():
                return None
            if op.text('拥有祝福',(.02,.03,.14,.08),exact=True):
                return 'overview'
            if self.blessing_page() or op.text(('方程','奇物','加权奇物','地图','沿途站点'),(.035,.035,.20,.10),exact=True):
                return 'detail'
            return None
        def close_layer():
            layer=visible_layer()
            if layer is None:
                return False
            # GUIDE_CLOSE shares its location with the overview's entry to
            # equation details. A late close can therefore reopen the panel.
            # Refresh through the operator, keeping its image and caches in
            # sync with the native device before validating the same layer.
            op.snapshot()
            if visible_layer()!=layer:
                return False
            if layer=='overview':
                control=op.template('star_inventory_collapse',(.86,.32,.995,.43),confidence=.94)
                if control:
                    return op.click_box(control,interval=2)
                return op.click_text('收起',(.92,.345,.97,.39),exact=True,interval=2)
            if layer=='detail':
                return self.main.appear_then_click(GUIDE_CLOSE,interval=2)
            return False
        op.wait_until(lambda:self.main.selection_kind() in ('equation','blessing')
                      or self.main.world_visible() or self.main.is_combat_executing(),
                      action=close_layer,
                      timeout=15,name='库存返回原奖励页')
