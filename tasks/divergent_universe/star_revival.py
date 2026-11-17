"""Revive only characters explicitly listed by the game's revival device."""
from pathlib import Path
import re
import time

from module.base.utils import save_image
from tasks.currency_wars.operator import normalize


class StarRevival:
    def __init__(self,preparation):
        self.preparation=preparation
        self.main=preparation.main
        self.op=preparation.op
        self.node=str(self.main.active.get('node',0))
        self.state=self.main.active['star'].setdefault('revivals',{}).setdefault(self.node,dict(scans=0,moves=0))

    def save(self,label):
        folder=Path(__file__).resolve().parents[2]/'log/divergent_universe'/self.main.config.config_name/'star_runs'/self.main.active['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'revival_{self.node}_{label}_{time.time_ns()}.png'
        save_image(self.op.image,path)
        return str(path)

    def targets(self):
        return [box for box in self.op.read_region((.63,.52,.99,.575),snapshot=False)
                if re.fullmatch(r'等级\d{1,3}',normalize(box.source))]

    def number(self,region):
        text=normalize(self.op.read_line(region,snapshot=False).source)
        return int(text) if re.fullmatch(r'\d{1,6}',text) else None

    def funds(self):
        return self.number((.85,.03,.91,.074))

    def cost(self):
        return self.number((.665,.895,.72,.932))

    def close(self):
        from tasks.base.assets.assets_base_page import GUIDE_CLOSE
        requests=0
        def close_visible():
            nonlocal requests
            if requests<3 and self.preparation.revival_page_visible():
                if self.main.appear_then_click(GUIDE_CLOSE,interval=2):
                    requests+=1
        self.op.wait_until(self.main.world_visible,action=close_visible,timeout=12,name='复活检查返回原场地')
        return True

    def reconcile(self):
        pending=self.state.get('pending')
        if not pending:
            return True
        previous=None
        def restored():
            nonlocal previous
            if not self.preparation.revival_page_visible():
                previous=None
                return None
            remaining=len(self.targets());funds=self.funds()
            key=(remaining,funds) if (remaining==pending['before_count']-1
                and funds==pending['before_funds']-pending['cost']) else None
            ready=key is not None and key==previous
            previous=key
            return key if ready else None
        remaining,funds=self.op.wait_until(restored,timeout=15,name='复活名单减少与费用核对')
        receipt=dict(pending,remaining_count=remaining,after_funds=funds,screenshot=self.save('confirmed'))
        self.state.setdefault('revived',[]).append(receipt)
        self.state.pop('pending',None)
        self.main.progress.record('star_character_revived',**receipt)
        self.main.progress.save('star_character_revived')
        return True

    def run(self):
        if not self.preparation.revival_page_visible():
            return False
        self.reconcile()  # A resumed pending request must never pay twice.
        for _ in range(max(0,4-len(self.state.get('revived',[])))):
            if self.op.text('暂无目标',(.74,.51,.90,.62),exact=True):
                self.state['checked_no_targets']=True
                self.main.progress.record('star_revival_no_targets',screenshot=self.save('empty'))
                self.main.progress.save('star_revival_no_targets')
                return self.close()
            targets=self.targets()
            if not 1<=len(targets)<=4:
                self.main.progress.record('star_revival_unreadable_targets',screenshot=self.save('unknown'))
                raise RuntimeError('角色重置名单不可读，未发送付费操作')
            target=targets[0]
            def selected():
                button=self.op.text('重置',(.75,.87,.98,.95),exact=True)
                cost=self.cost()
                return button if button and (self.main.confirm_enabled(button)
                    or cost is not None and cost>0) else None
            button=self.op.wait_until(selected,action=lambda:self.op.click_box(target,interval=2),
                                      timeout=12,name='无法战斗角色已选中')
            cost=self.cost();funds=self.funds()
            if cost is None or funds is None:
                raise RuntimeError('复活费用或余额不可读，未支付')
            if cost>funds:
                self.state.update(unavailable=True,outcome='insufficient_funds')
                self.main.progress.record('star_revival_unaffordable',cost=cost,available=funds,screenshot=self.save('unaffordable'))
                self.main.progress.save('star_revival_unaffordable')
                return self.close()
            def enabled():
                current=self.op.text('重置',(.75,.87,.98,.95),exact=True)
                return current if current and self.main.confirm_enabled(current) else None
            button=self.op.wait_until(enabled,timeout=8,name='复活确认可用')
            if self.cost()!=cost or self.funds()!=funds:
                continue  # A changing quote is not an authorized payment.
            self.state['pending']=dict(before_count=len(targets),before_funds=funds,cost=cost,
                                       target_box=target.button,before_screenshot=self.save('before'))
            self.main.progress.record('star_revival_requested',**self.state['pending'])
            self.main.progress.save('star_revival_requested')
            if not self.op.click_box(button,interval=2):
                self.state.pop('pending',None)
                self.main.progress.save('star_revival_not_sent')
                continue
            self.reconcile()
        return self.close()
