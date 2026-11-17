"""The observed disappearing-label transition must not select another mask."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.divergent_universe import DivergentUniverse


class MaskTransitionTests(unittest.TestCase):
    def refresh_task(self):
        task=object.__new__(DivergentUniverse);task.active={'star':{}}
        events=[];clicks=[];counter=['1/1']
        task.progress=SimpleNamespace(record=lambda name,**k:events.append((name,k)),save=lambda *a:None)
        task.op=SimpleNamespace(text=lambda *a,**k:Box(100,640,50,30,'刷新'),
            read_line=lambda *a,**k:Box(240,640,50,30,counter[0]),
            click_box=lambda box,**k:clicks.append(box.source) or True)
        return task,counter,clicks,events

    def test_free_mask_refresh_requires_counter_change_and_fresh_menu(self):
        task,counter,clicks,events=self.refresh_task()
        bad=[Box(290,270+i*130,100,30,n) for i,n in enumerate(['操盘面具','点子王面具','镜头面具'])]
        good=[Box(290,270+i*130,100,30,n) for i,n in enumerate(['囧之面具','斗士面具','镜头面具'])]
        self.assertTrue(task.maybe_refresh_star_masks(bad))
        self.assertTrue(task.maybe_refresh_star_masks(bad))
        counter[0]='0/1'
        self.assertTrue(task.maybe_refresh_star_masks(good))
        self.assertTrue(task.maybe_refresh_star_masks(good))
        self.assertFalse(task.maybe_refresh_star_masks(good))
        self.assertEqual(clicks,['刷新'])
        self.assertEqual(events[-1][0],'star_mask_refreshed')

    def test_refresh_is_not_spent_on_a_preferred_mask_or_retried_after_timeout(self):
        task,counter,clicks,events=self.refresh_task()
        self.assertFalse(task.maybe_refresh_star_masks([Box(290,270,100,30,'财猫面具')]))
        self.assertEqual(clicks,[])
        bad=[Box(290,270+i*130,100,30,n) for i,n in enumerate(['操盘面具','点子王面具','镜头面具'])]
        self.assertTrue(task.maybe_refresh_star_masks(bad))
        task.active['star']['mask_refresh']['requested_at']-=9
        self.assertFalse(task.maybe_refresh_star_masks(bad))
        self.assertFalse(task.maybe_refresh_star_masks(bad))
        self.assertEqual(clicks,['刷新'])
        self.assertEqual(events[-1][0],'star_mask_refresh_unconfirmed')

    def test_observed_jiong_variants_keep_exact_identity(self):
        from tasks.divergent_universe.star_policy import mask_name, mask_labels
        for title in ('囧之面具','冏之面具'):
            self.assertEqual(mask_name(title),'囧之面具')
            self.assertIn('囧之面具',mask_labels(title))
        for title in ('马之面具','之面具'):
            self.assertEqual(mask_name(title),title)
            self.assertNotIn('囧之面具',mask_labels(title))

    def choose_from_labels(self,names,detail=None,pending=None):
        task=object.__new__(DivergentUniverse)
        task.active={'id':'fixture','selections':0,'star':{
            'mask_choice_screenshot':'fixture.png','mask_detail_screenshot':'fixture-detail.png'}}
        if pending:task.active['star']['mask_candidate']=pending
        task._node_done=False
        task.star_loadout=SimpleNamespace(revision='star-workshop-v8')
        task.selection_kind=lambda:'mask'
        task.world_visible=task.is_combat_executing=lambda:False
        task.reward_close_button=lambda:None
        task.confirm_enabled=lambda _:True
        task.progress=SimpleNamespace(save=lambda *a:None,record=lambda *a,**k:None)
        task.device=SimpleNamespace(click_record_clear=lambda:None)
        clicks=[];confirms=[]
        task.confirm_selection=lambda kind:confirms.append(kind)
        def text(words,*a,**k):
            if words=='确定':return Box(950,630,160,35,'确定')
            if isinstance(words,tuple) and clicks and (detail or clicks[-1]) in words:
                return Box(790,120,230,35,detail or clicks[-1])
        def wait(predicate,action,**k):
            for _ in range(4):
                ready=predicate()
                if ready:return ready
                action()
            raise RuntimeError('面具确认页未出现')
        task.op=SimpleNamespace(text=text,wait_until=wait,
            read_region=lambda *a,**k:[Box(295,275+i*130,100,30,n) for i,n in enumerate(names)],
            click_box=lambda box,**k:clicks.append(box.source) or True)
        return task,clicks,confirms

    def test_observed_317424_menu_keeps_horse_with_its_real_identity(self):
        # Actual mask_choice.png: 马之面具 / 操盘面具 / 财猫面具.
        task,clicks,confirms=self.choose_from_labels(['马之面具','操盘面具','财猫面具'])
        task.handle_choice('mask')
        self.assertEqual(clicks,['马之面具'])
        self.assertEqual(task.active['star']['mask'],'马之面具')
        self.assertEqual(confirms,['mask'])

    def test_offered_horse_is_kept_without_spending_free_refresh(self):
        task,counter,clicks,events=self.refresh_task()
        labels=[Box(295,275+i*130,100,30,n) for i,n in enumerate(['马之面具','操盘面具','战车面具'])]
        self.assertFalse(task.maybe_refresh_star_masks(labels))
        self.assertEqual(clicks,[])
        self.assertNotIn('mask_refresh',task.active['star'])

    def test_without_horse_real_jiong_is_preferred_and_keeps_separate_detail(self):
        for name in ('囧之面具','冏之面具'):
            task,clicks,confirms=self.choose_from_labels(['操盘面具','财猫面具',name])
            task.handle_choice('mask')
            self.assertEqual(clicks,[name])
            self.assertEqual(task.active['star']['mask'],'囧之面具')
        task,clicks,confirms=self.choose_from_labels(['囧之面具'],detail='马之面具')
        with self.assertRaisesRegex(RuntimeError,'面具确认页'):task.handle_choice('mask')
        self.assertEqual(confirms,[])
        self.assertNotIn('mask',task.active['star'])

    def test_missing_first_character_is_skipped_without_inventing_identity(self):
        task,clicks,confirms=self.choose_from_labels(['之面具'])
        with self.assertRaisesRegex(RuntimeError,'面具确认页'):task.handle_choice('mask')
        self.assertEqual(clicks,[])
        self.assertEqual(confirms,[])
        self.assertNotIn('mask_candidate',task.active['star'])
        task,clicks,confirms=self.choose_from_labels(['之面具','财猫面具'],pending='之面具')
        task.handle_choice('mask')
        self.assertEqual(clicks,['财猫面具'])
        self.assertEqual(task.active['star']['mask'],'财猫面具')

    def test_snow_owl_detail_variants_still_confirm_in_the_existing_region(self):
        task,clicks,confirms=self.choose_from_labels(['雪鹃面具'],detail='雪面具')
        task.handle_choice('mask')
        self.assertEqual(clicks,['雪鹃面具'])
        self.assertEqual(confirms,['mask'])
        self.assertEqual(task.active['star']['mask'],'雪鸮面具')

    def test_final_mask_detail_is_saved_once_from_verified_current_frame(self):
        task,clicks,confirms=self.choose_from_labels(['马之面具'])
        task.active['star'].pop('mask_detail_screenshot')
        task.config=SimpleNamespace(config_name='fixture')
        task.op.image=object()
        task.op.snapshot=Mock(side_effect=AssertionError('Reuse the verified frame'))
        task.progress.record=Mock()
        wait=task.op.wait_until
        def repeated_ready(predicate,**kwargs):
            result=wait(predicate,**kwargs)
            self.assertTrue(predicate())
            return result
        task.op.wait_until=repeated_ready
        with patch('tasks.divergent_universe.divergent_universe.save_image') as saved,patch('pathlib.Path.mkdir'):
            task.handle_choice('mask')
        self.assertEqual(saved.call_count,1)
        self.assertIs(saved.call_args.args[0],task.op.image)
        self.assertTrue(saved.call_args.args[1].stem.startswith('mask_detail_'))
        self.assertEqual(saved.call_args.args[1].suffix,'.png')
        self.assertEqual(task.active['star']['mask_detail_raw_title'],'马之面具')
        task.progress.record.assert_any_call('star_mask_detail_observed',raw_title='马之面具',
            resolved_name='马之面具',path=task.active['star']['mask_detail_screenshot'])
        task.op.snapshot.assert_not_called()

    def test_partial_mismatched_or_disabled_details_never_create_success_evidence(self):
        for scenario in ('partial','mismatched','disabled'):
            names=['之面具'] if scenario=='partial' else ['囧之面具']
            detail='马之面具' if scenario=='mismatched' else None
            task,clicks,confirms=self.choose_from_labels(names,detail=detail)
            task.active['star'].pop('mask_detail_screenshot')
            if scenario=='disabled':task.confirm_enabled=lambda _:False
            with patch('tasks.divergent_universe.divergent_universe.save_image') as saved,\
                 self.assertRaisesRegex(RuntimeError,'面具确认页'):
                task.handle_choice('mask')
            saved.assert_not_called()
            self.assertNotIn('mask_detail_screenshot',task.active['star'])
            self.assertEqual(confirms,[])

    def legacy_horse_detail_task(self,menus):
        task,clicks,confirms=self.choose_from_labels(menus[0],pending='囧之面具')
        detail=['马之面具'];seen=[0];events=[]
        def text(words,*a,**k):
            if words=='确定':return Box(950,630,160,35,'确定')
            labels=(words,) if isinstance(words,str) else words
            if detail[0] in labels:return Box(790,120,230,35,detail[0])
        def read(*a,**k):
            names=menus[min(seen[0],len(menus)-1)];seen[0]+=1
            return [Box(295,275+i*130,100,30,name) for i,name in enumerate(names)]
        def click(box,**k):
            clicks.append(box.source);detail[0]=box.source
            return True
        task.op.text=text;task.op.read_region=read;task.op.click_box=click
        task.progress.record=lambda event,**k:events.append((seen[0],event,k))
        return task,clicks,confirms,events

    def test_old_horse_alias_pending_is_invalidated_only_after_two_complete_frames(self):
        menu=['马之面具','操盘面具','财猫面具']
        task,clicks,confirms,events=self.legacy_horse_detail_task([menu,menu])
        task.handle_choice('mask')
        invalidated=[e for e in events if e[1]=='star_mask_pending_invalidated']
        self.assertEqual(len(invalidated),1)
        self.assertEqual(invalidated[0][0],2)
        self.assertEqual(invalidated[0][2]['previous'],'囧之面具')
        self.assertEqual(invalidated[0][2]['raw_detail'],'马之面具')
        self.assertEqual(clicks,['马之面具'])
        self.assertEqual(confirms,['mask'])
        self.assertEqual(task.active['star']['mask'],'马之面具')

    def test_old_pending_survives_incomplete_menu_fades(self):
        menu=['马之面具','操盘面具','财猫面具']
        task,clicks,confirms,events=self.legacy_horse_detail_task([menu,['马之面具'],menu,['马之面具']])
        with self.assertRaisesRegex(RuntimeError,'面具确认页'):task.handle_choice('mask')
        self.assertEqual(task.active['star']['mask_candidate'],'囧之面具')
        self.assertEqual(clicks,[])
        self.assertEqual(confirms,[])
        self.assertFalse(any(e[1]=='star_mask_pending_invalidated' for e in events))

    def test_settlement_only_opening_can_confirm_without_claiming_mask_identity(self):
        task=object.__new__(DivergentUniverse)
        task.active={'id':'fixture','selections':0,'stop_requested':True,
                     'star':{'mask_choice_screenshot':'fixture.png','mask_candidate':'unreadable'}}
        task._node_done=False
        task.star_loadout=SimpleNamespace(revision='star-workshop-v6')
        task.selection_kind=lambda:'mask'
        task.world_visible=task.is_combat_executing=lambda:False
        task.confirm_enabled=lambda _:True
        task.confirm_selection=lambda kind:True
        events=[]
        task.progress=SimpleNamespace(save=lambda *a:None,record=lambda event,**k:events.append(event))
        task.device=SimpleNamespace(click_record_clear=lambda:None)
        task.op=SimpleNamespace(text=lambda label,*a,**k:Box(950,630,160,35,'确定') if label=='确定' else None,
                                wait_until=lambda predicate,**k:predicate())
        task.handle_choice('mask')
        self.assertIn('initial_mask_confirmed_for_settlement',events)
        self.assertNotIn('mask',task.active['star'])
        self.assertNotIn('settlement_observed',task.active)

    def test_initial_choice_survives_menu_fade_until_matching_detail(self):
        task=object.__new__(DivergentUniverse)
        task.active={'id':'fixture','selections':0,'star':{
            'mask_choice_screenshot':'fixture.png','mask_detail_screenshot':'fixture-detail.png'}}
        task._node_done=False
        task.star_loadout=SimpleNamespace(revision='star-workshop-v3')
        task.selection_kind=lambda:'mask'
        task.world_visible=lambda:False
        task.is_combat_executing=lambda:False
        task.reward_close_button=lambda:None
        task.confirm_enabled=lambda _:True
        task.confirm_selection=lambda kind:None
        task.progress=SimpleNamespace(save=lambda *a:None,record=lambda *a,**k:None)
        task.device=SimpleNamespace(click_record_clear=lambda:None)
        step=0
        clicks=[]
        def text(words,region,**kwargs):
            if step==2 and words in ('确定',('斗士面具',)):
                return Box(950,630,160,35,str(words))
            return None
        def read(*args,**kwargs):
            # Exactly what the real log exposed: the preferred mask vanishes
            # from OCR briefly while another menu row remains readable.
            names=['万随面具','点子王面具','斗士面具'] if step==0 else ['万随面具']
            return [Box(295,270+i*130,100,30,name) for i,name in enumerate(names)]
        def wait(predicate,action=None,**kwargs):
            nonlocal step
            for step in range(3):
                ready=predicate()
                if ready:return ready
                action()
            self.fail('The matching detail should become ready')
        task.op=SimpleNamespace(text=text,read_region=read,wait_until=wait,
                                click_box=lambda box,**kw:clicks.append(box.source) or True)
        task.handle_choice('mask')
        self.assertEqual(clicks,['斗士面具'])
        self.assertEqual(task.active['star']['mask'],'斗士面具')

    def test_observed_snow_owl_ocr_variants_keep_exact_identity(self):
        from tasks.divergent_universe.star_policy import mask_name, mask_labels
        for title in ('雪鸮面具','雪鹃面具','雪面具'):
            self.assertEqual(mask_name(title),'雪鸮面具')
            self.assertIn('雪鹃面具',mask_labels(title))
        self.assertNotIn('囧之面具',mask_labels('雪面具'))
        self.assertEqual(mask_name('万随面具'),'万随面具')

    def test_enabled_default_button_does_not_bypass_the_mask_policy(self):
        task=object.__new__(DivergentUniverse)
        task.active={'id':'fixture','selections':0,'star':{
            'mask_choice_screenshot':'fixture.png','mask_detail_screenshot':'fixture-detail.png'}}
        task._node_done=False
        task.star_loadout=SimpleNamespace(revision='star-workshop-v5')
        task.selection_kind=lambda:'mask'
        task.world_visible=task.is_combat_executing=lambda:False
        task.reward_close_button=lambda:None
        task.confirm_enabled=lambda _:True
        task.confirm_selection=lambda *a:None
        task.progress=SimpleNamespace(save=lambda *a:None,record=lambda *a,**k:None)
        task.device=SimpleNamespace(click_record_clear=lambda:None)
        clicks=[]
        def text(words,*a,**k):
            if words=='确定' or (clicks and words==('财猫面具',)):
                return Box(950,630,160,35,'确定')
        def wait(predicate,action,**k):
            self.assertFalse(predicate())
            action()
            self.assertTrue(predicate())
            return True
        task.op=SimpleNamespace(text=text,wait_until=wait,
            read_region=lambda *a,**k:[Box(295,275,100,30,'雪鹃面具'),Box(295,405,100,30,'财猫面具')],
            click_box=lambda box,**k:clicks.append(box.source) or True)
        task.handle_choice('mask')
        self.assertEqual(clicks,['财猫面具'])
        self.assertEqual(task.active['star']['mask'],'财猫面具')


if __name__=='__main__':unittest.main()
