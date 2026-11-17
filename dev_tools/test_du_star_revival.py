from types import SimpleNamespace
import unittest
from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_revival import StarRevival


class RevivalTests(unittest.TestCase):
    def task(self,remaining=1,funds=200,cost=50):
        state={'remaining':remaining,'funds':funds,'cost':cost,'selected':False,'payments':0,'closed':False}
        main=SimpleNamespace(active={'id':'retained','node':6,'star':{}},config=SimpleNamespace(config_name='fixture'))
        events=[]
        main.progress=SimpleNamespace(record=lambda name,**k:events.append((name,k)),save=lambda *a:None)
        main.confirm_enabled=lambda b:state['selected']
        def text(name,*a,**k):
            if name=='暂无目标' and state['remaining']==0:return Box(980,380,100,30,name)
            if name=='重置':return Box(1070,645,80,30,name)
        def click(box,**kwargs):
            if box.source=='重置':
                state['payments']+=1;state['funds']-=state['cost'];state['remaining']-=1;state['selected']=False
            else:state['selected']=True
            return True
        def wait(predicate,action=None,**kwargs):
            for _ in range(8):
                value=predicate()
                if value:return value
                if action:action()
            raise RuntimeError('fixture timeout')
        main.op=SimpleNamespace(text=text,click_box=click,wait_until=wait)
        prep=SimpleNamespace(main=main,op=main.op,revival_page_visible=lambda:True)
        worker=StarRevival(prep);worker.save=lambda *a:'fixture.png'
        worker.targets=lambda:[Box(830+i*105,380,70,25,'等级80') for i in range(state['remaining'])]
        worker.funds=lambda:state['funds'];worker.cost=lambda:state['cost'] if state['selected'] else 0
        worker.close=lambda:state.__setitem__('closed',True) or True
        return worker,state,events

    def test_paid_and_free_revives_require_list_and_balance_receipts(self):
        for cost in (0,50):
            worker,state,events=self.task(remaining=2,cost=cost)
            self.assertTrue(worker.run())
            self.assertEqual(state['payments'],2)
            self.assertEqual(state['remaining'],0)
            self.assertEqual(len(worker.state['revived']),2)
            self.assertEqual(state['funds'],200-cost*2)
            self.assertTrue(state['closed'])
            self.assertNotIn('settlement_observed',worker.main.active)

    def test_reload_reconciles_an_existing_payment_without_paying_again(self):
        worker,state,events=self.task(remaining=0,funds=150)
        worker.state['pending']={'before_count':1,'before_funds':200,'cost':50}
        self.assertTrue(worker.run())
        self.assertEqual(state['payments'],0)
        self.assertEqual(len(worker.state['revived']),1)

    def test_missing_receipt_never_repeats_payment_or_claims_revival(self):
        worker,state,events=self.task(remaining=1,funds=150)
        worker.state['pending']={'before_count':1,'before_funds':200,'cost':50}
        with self.assertRaises(RuntimeError):worker.run()
        self.assertEqual(state['payments'],0)
        self.assertNotIn('revived',worker.state)
        self.assertIn('pending',worker.state)

    def test_unaffordable_revival_preserves_the_run_without_payment(self):
        worker,state,events=self.task(funds=20,cost=50)
        self.assertTrue(worker.run())
        self.assertEqual(state['payments'],0)
        self.assertEqual(state['remaining'],1)
        self.assertTrue(worker.state['unavailable'])
        self.assertEqual(worker.main.active['id'],'retained')


if __name__=='__main__':unittest.main()
