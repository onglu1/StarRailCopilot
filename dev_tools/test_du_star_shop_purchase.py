"""A shop request needs stable price, real funds, and a stock transition."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from module.exception import RequestHumanTakeover
from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_shop import StarShop


class ShopPurchaseTests(unittest.TestCase):
    def task(self,remove_stock=True,changed_price=False,bonus=False):
        bought=[];events=[];funds=[1313];reads=[0];stage=['store']
        main=SimpleNamespace(active={'id':'retained','node':16,'station':'商店','node_done':False,
            'star':{'threshold':5,'choices':[]}},
            star_loadout=SimpleNamespace(core_equations=('除魔士','铁臂侠'),
                survival_blessings=(),revision='star-workshop-v6'))
        main.progress=SimpleNamespace(save=lambda *a:None,record=lambda event,**data:events.append((event,data)))
        main.wait_until_stable=lambda *a:None
        main.confirm_enabled=lambda button:True
        main.reward_close_button=lambda:Box(590,650,100,25,'close') if stage[0] in ('receipt','bonus') else None
        def text(label,*a,**k):
            if stage[0]=='receipt' and label in ('获得方程','超级体育生','已展开'):
                return Box(220,340,150,30,label)
            if stage[0]=='bonus' and isinstance(label,tuple) and '站点卡升级' in label:
                return Box(500,100,150,30,'站点卡升级')
            return Box(1080,640,80,30,'购买') if label=='购买' else None
        def click(button,**kwargs):
            if button.source=='购买':
                funds[0]-=338;bought.append('超级体育生');stage[0]='awaiting_receipt'
            if button.source=='close':stage[0]='receipt' if stage[0]=='bonus' else 'store_after'
            return True
        def wait(predicate,action=None,**kwargs):
            for _ in range(4):
                result=predicate()
                if result:return result
                if stage[0]=='awaiting_receipt' and remove_stock:stage[0]='bonus' if bonus else 'receipt'
                if action:action()
            raise RuntimeError(kwargs.get('name','页面切换')+'超时，目标界面未出现')
        main.op=SimpleNamespace(snapshot=lambda:None,text=text,click_box=click,
                                wait_until=wait)
        shop=StarShop(main);shop.visible=lambda:stage[0]!='receipt';shop.save_frame=lambda name:name+'.png'
        shop.funds=lambda:funds[0]
        def fields():
            reads[0]+=1
            return dict(name='超级体育生',cost=339 if changed_price and reads[0]>1 else 338,
                        funds=funds[0],counts={'智识':8,'巡猎':6},requirements={'智识':6,'巡猎':4})
        shop.selected_fields=fields
        def cards(_):
            return [] if bought and remove_stock else [(Box(240,270,130,25,'超级体育生'),'超级体育生')]
        return shop,main,bought,events,cards

    def test_payment_before_obtain_popup_cannot_finish_until_matching_receipt(self):
        shop,main,bought,events,cards=self.task()
        with patch('tasks.divergent_universe.star_workshop.StarWorkshop.equation_cards',cards),patch(
                'tasks.divergent_universe.star_workshop.StarWorkshop.selected_equation',lambda _: '超级体育生'):
            result=shop.buy_equations('retained')
        self.assertEqual(bought,['超级体育生'])
        self.assertEqual(result['purchased'][0]['after_funds'],975)
        self.assertTrue(result['purchased'][0]['receipt_observed'])
        self.assertEqual(main.active['star']['choices'][0]['title'],'超级体育生')
        self.assertFalse(main.active['node_done'])
        self.assertNotIn('settlement_observed',main.active)

    def test_changed_final_price_cannot_send_a_purchase(self):
        shop,main,bought,events,cards=self.task(changed_price=True)
        with patch('tasks.divergent_universe.star_workshop.StarWorkshop.equation_cards',cards),patch(
                'tasks.divergent_universe.star_workshop.StarWorkshop.selected_equation',lambda _: '超级体育生'):
            result=shop.buy_equations('retained')
        self.assertEqual(bought,[])
        self.assertEqual(result['outcome'],'purchase_fields_changed')
        self.assertEqual(main.active['star']['choices'],[])

    def test_station_card_bonus_is_closed_before_the_item_receipt(self):
        shop,main,bought,events,cards=self.task(bonus=True)
        with patch('tasks.divergent_universe.star_workshop.StarWorkshop.equation_cards',cards),patch(
                'tasks.divergent_universe.star_workshop.StarWorkshop.selected_equation',lambda _: '超级体育生'):
            result=shop.buy_equations('retained')
        self.assertEqual(bought,['超级体育生'])
        self.assertEqual(len(result['purchased'][0]['intermediate_receipts']),1)
        self.assertTrue(result['purchased'][0]['receipt_observed'])

    def test_missing_receipt_keeps_pending_request_and_cannot_pay_twice(self):
        shop,main,bought,events,cards=self.task(remove_stock=False)
        with patch('tasks.divergent_universe.star_workshop.StarWorkshop.equation_cards',cards),patch(
                'tasks.divergent_universe.star_workshop.StarWorkshop.selected_equation',lambda _: '超级体育生'):
            result=shop.buy_equations('retained')
            retry=shop.buy_equations('retained')
        self.assertEqual(bought,['超级体育生'])
        self.assertIn('pending',result)
        self.assertIn('pending',retry)
        self.assertEqual(main.active['star']['choices'],[])


if __name__=='__main__':unittest.main()
