"""Station-card operations must select their actual target before confirming."""
from types import SimpleNamespace
import unittest
from tasks.currency_wars.operator import Box
from tasks.divergent_universe.divergent_universe import DivergentUniverse


class StationCardTests(unittest.TestCase):
    def task(self, description):
        main=object.__new__(DivergentUniverse)
        selected=['精英'];clicks=[];events=[];regions=[]
        rows=[Box(161,315,52,31,'精英'),Box(344,310,48,30,'战斗'),
              Box(716,470,48,31,'冒险'),Box(159,632,45,26,'铸造')]
        def match(names,region,exact=False):
            regions.append(region)
            return [b for b in rows if region[1]*720 <= b.center[1] <= region[3]*720]
        def click(box,**kwargs):
            if box:
                clicks.append(box.source);selected[0]=box.source
                return True
            return False
        def text(name,region,**kwargs):
            return Box(900,140,60,30,name) if name in ('确定',selected[0]) else None
        def wait(predicate,action=None,**kwargs):
            for _ in range(8):
                result=predicate()
                if result:return result
                if action:action()
            self.fail('Selection did not converge')
        main.op=SimpleNamespace(read_line=lambda *a,**k:Box(95,100,690,30,description),
                                match=match,text=text,click_box=click,wait_until=wait)
        main.confirm_enabled=lambda button:True
        main.save_station_card_frame=lambda:'saved_decision.png'
        main.progress=SimpleNamespace(record=lambda event,**data:events.append((event,data)))
        return main,selected,clicks,events,regions

    def test_enabled_default_cannot_bypass_adventure_replacement(self):
        main,selected,clicks,events,regions=self.task('指定1个区域，使其变为【空白】区域。然后获得2个随机1-2星祝福')
        main.select_station_card()
        self.assertEqual(selected[0],'冒险')
        self.assertEqual(set(clicks),{'冒险'})
        self.assertEqual(events[-1][1]['operation'],'replace_with_empty')
        self.assertEqual(events[-1][1]['selected'],'冒险')
        self.assertTrue(any(r[3]>=670/720 for r in regions))

    def test_delete_region_prefers_bad_route_and_checks_actual_selected_name(self):
        for instruction in ('立即删除4个指定区域','删除2个指定区域，并使随机区域获得其强化等级','指定2个区域，将其删除'):
            with self.subTest(instruction=instruction):
                main,selected,clicks,events,_=self.task(instruction)
                main.select_station_card()
                self.assertEqual(selected[0],'冒险')
                self.assertEqual(events[-1][1]['operation'],'delete_region')

    def test_delete_beacons_keeps_separate_semantics(self):
        for instruction in ('指定1个区域，删除其全部信标','指定1个带有信标的区域，将其删除'):
            main,selected,clicks,events,_=self.task(instruction)
            main.select_station_card()
            self.assertEqual(events[-1][0],'station_card_operation_unclassified')
            self.assertEqual(clicks,[])

    def test_discard_section_shift_does_not_hide_region_at_y548(self):
        main,_,_,_,regions=self.task('立即删除4个指定区域')
        rows=[Box(160,320,50,30,'事件'),Box(160,540,50,30,'异常')]
        def match(names,region,**kwargs):
            if names==('抽牌区','弃牌区'):
                return [Box(50,159,80,27,'抽牌区'),Box(50,374,80,27,'弃牌区')]
            self.assertLessEqual((region[3]-region[1])*720,43)
            return [b for b in rows if region[1]*720<=b.center[1]<=region[3]*720]
        main.op.match=match
        self.assertEqual([b.source for b in main.station_card_candidates()],['事件','异常'])

    def test_unknown_instruction_does_not_apply_destructive_priority(self):
        main,selected,clicks,events,_=self.task('指定一个区域，执行新的面具效果')
        main.select_station_card()
        self.assertEqual(selected[0],'精英')
        self.assertEqual(clicks,[])
        self.assertEqual(events[-1][0],'station_card_operation_unclassified')

    def test_late_missing_weighted_slot_rerolls_low_forge_but_preserves_fallback(self):
        main=object.__new__(DivergentUniverse)
        main.active={'node':17,'node_total':20,'star':{'boss_rewards_seen':True,'weighted_equipment':[{'id':1009}]}}
        main.star_workshop_enabled=lambda:True
        low=Box(300,520,50,30,'铸造');high=Box(550,520,50,30,'铸造');battle=Box(800,520,50,30,'战斗')
        main.station_grade=lambda box:2 if box is low else 3 if box is high else None
        order=['战斗','铸造','事件']
        self.assertIsNone(main.station_target([low,battle],order,allow_reroll=True))
        self.assertIs(main.station_target([low,battle],order),battle)
        self.assertIs(main.station_target([low,battle,high],order,allow_reroll=True),high)
        main.active['star']['weighted_equipment'].append({'id':1010})
        self.assertIs(main.station_target([low,battle,high],order,allow_reroll=True),battle)
        main.active['node']=2
        main.active['star']['weighted_equipment']=[]
        self.assertIs(main.station_target([low,battle,high],order,allow_reroll=True),battle)

    def test_first_weighted_curio_uses_bounded_rerolls_before_safe_battle(self):
        main=object.__new__(DivergentUniverse)
        main.active={'node':4,'node_total':20,'star':{}}
        main.star_workshop_enabled=lambda:True
        main.station_grade=lambda box:1
        battle=Box(300,520,50,30,'战斗');forge=Box(550,520,50,30,'铸造')
        order=['战斗','铸造']
        self.assertIsNone(main.station_target([battle],order,allow_reroll=True))
        self.assertIs(main.station_target([battle],order),battle)
        self.assertIs(main.station_target([battle,forge],order,allow_reroll=True),forge)
        main.active['star']['weighted_equipment']=[{'id':1009}]
        self.assertIs(main.station_target([battle,forge],order,allow_reroll=True),battle)

    def test_same_type_replacement_with_lower_grade_cannot_be_confirmed(self):
        from tasks.divergent_universe.selection import Choice
        main=object.__new__(DivergentUniverse)
        box=Box(550,520,50,30,'铸造');choice=Choice(box,'铸造');choice.station_grade=3
        clicked=[];events=[]
        main.op=SimpleNamespace(snapshot=lambda:None,read_region=lambda *a,**k:[box],
                                click_box=lambda *a,**k:clicked.append(a))
        main.handle_station_warning=lambda:False
        main.selection_kind=lambda:'next_station'
        main.selection_names=lambda *a:('铸造',)
        main.choice_confirm_button=lambda:Box(780,630,100,30,'确定')
        main.confirm_enabled=lambda b:True
        main.station_grade=lambda b:2
        main.progress=SimpleNamespace(record=lambda *a,**k:events.append(k))
        self.assertFalse(main.confirm_selection('next_station',choice))
        self.assertEqual(clicked,[])
        self.assertEqual(events[-1]['expected_grade'],3)
        self.assertEqual(events[-1]['actual_grade'],2)

    def test_risky_star_routes_use_reroll_budget_before_falling_back(self):
        main=object.__new__(DivergentUniverse)
        main.active={'node':2,'node_total':20,'star':{}}
        main.star_workshop_enabled=lambda:True
        main.station_grade=lambda b:self.fail('Unrelated level OCR is unnecessary')
        elite=Box(300,520,50,30,'精英');abnormal=Box(550,520,50,30,'异常');event=Box(800,520,50,30,'事件')
        order=['战斗','奖励','事件','铸造','精英','异常']
        self.assertIsNone(main.station_target([elite,abnormal],order,allow_reroll=True))
        self.assertIs(main.station_target([elite,abnormal],order),elite)
        self.assertIs(main.station_target([elite,event,abnormal],order,allow_reroll=True),event)
        main.star_workshop_enabled=lambda:False
        self.assertIs(main.station_target([elite,abnormal],order,allow_reroll=True),elite)

    def test_star_shop_is_available_with_the_purchasing_adapter(self):
        main=object.__new__(DivergentUniverse)
        main.active={'node':12,'node_total':20,'star':{'weighted_equipment':[{'id':1009}]}}
        main.star_workshop_enabled=lambda:True
        main.station_grade=lambda b:self.fail('No forge grade is needed')
        shop=Box(300,520,50,30,'商店');battle=Box(550,520,50,30,'战斗')
        order=['战斗','奖励','财富','铸造','事件','商店','休整','精英','异常']
        self.assertIs(main.station_target([shop],order,allow_reroll=True),shop)
        self.assertIs(main.station_target([shop],order),shop)
        self.assertIs(main.station_target([shop,battle],order,allow_reroll=True),battle)
        main.star_workshop_enabled=lambda:False
        self.assertIs(main.station_target([shop],order,allow_reroll=True),shop)


if __name__=='__main__':unittest.main()
