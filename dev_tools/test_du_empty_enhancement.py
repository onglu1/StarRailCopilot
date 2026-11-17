"""A real empty enhancement list has no heat field, and costs nothing."""
from types import SimpleNamespace as NS
import unittest
from tasks.divergent_universe.star_workshop import StarWorkshop


class EmptyEnhancementTests(unittest.TestCase):
    def task(self,empty_frames,heat=None):
        frame=[-1];events=[];closed=[]
        def text(name,*args,**kwargs):
            return name if name=='祝福强化' or (name=='暂无可强化祝福' and empty_frames[frame[0]]) else None
        def wait(predicate,action,**kwargs):
            for index in range(len(empty_frames)):
                frame[0]=index
                result=predicate()
                if result:return result
                action()
            raise RuntimeError('not observed')
        main=NS(op=NS(text=text,wait_until=wait),active={'node':6,'star':{}},
                progress=NS(record=lambda *a,**kw:events.append((a,kw)),save=lambda *a:None))
        worker=StarWorkshop(main);worker.enhancement_heat=lambda:heat
        worker.close_reward_overlay=lambda:None;worker.return_to_menu=lambda:closed.append(True)
        worker.save_frame=lambda *a:'saved-current-empty.png'
        return worker,events,closed

    def test_two_empty_frames_exit_without_inventing_heat_or_payment(self):
        worker,events,closed=self.task([True,True])
        worker.enhancement_heat=lambda:self.fail('The empty page has no heat field')
        worker.enhance()
        self.assertTrue(worker.state()['enhancement_done'])
        self.assertEqual(worker.state()['enhancement_outcome'],'no_enhanceable_blessings')
        self.assertIsNone(events[-1][1]['remaining_heat'])
        self.assertEqual(closed,[True])

    def test_one_empty_frame_is_not_enough(self):
        worker,_,closed=self.task([True,False,True])
        with self.assertRaises(RuntimeError):worker.enhance()
        self.assertFalse(worker.state().get('enhancement_done',False))
        self.assertEqual(closed,[])

    def test_real_zero_heat_keeps_its_distinct_outcome(self):
        worker,events,closed=self.task([False],heat=0)
        worker.enhance()
        self.assertEqual(worker.state()['enhancement_outcome'],'heat_exhausted')
        self.assertEqual(events[-1][1]['remaining_heat'],0)


if __name__=='__main__':unittest.main()
