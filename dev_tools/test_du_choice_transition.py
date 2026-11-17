"""Regression for the real expanded 活的隐→活的隐喻 title, with no emulator."""
import unittest
from tasks.divergent_universe.selection import next_choice_set


class ChoiceTransitionTests(unittest.TestCase):
    def test_selected_old_set_with_completed_ocr_title_never_finishes(self):
        before=('感知赤骨与红叶','活的隐','激箭流星远')
        selected=('感知赤骨与红叶','活的隐喻','激箭流星远')
        previous=None;count=0
        for _ in range(5):
            previous,count,ready=next_choice_set(selected,before,True,True,True,previous,count)
            self.assertFalse(ready)
        self.assertEqual(count,0)

    def test_next_set_requires_same_gray_footer_names_on_two_frames(self):
        old=('a','b','c');new=('d','e','f')
        previous,count,ready=next_choice_set(new,old,True,True,False,None,0)
        self.assertFalse(ready)
        self.assertTrue(next_choice_set(new,old,True,True,False,previous,count)[2])

    def test_two_different_ocr_sets_do_not_accumulate_confirmation(self):
        p,c,_=next_choice_set(('new1',),('old',),True,True,False,None,0)
        self.assertFalse(next_choice_set(('new2',),('old',),True,True,False,p,c)[2])

    def test_resume_selected_card_still_needs_its_first_confirm(self):
        self.assertFalse(next_choice_set(('selected',),('before',),False,True,True,None,0)[2])
        self.assertFalse(next_choice_set(('new',),('before',),False,True,False,('new',),4)[2])

    def test_missing_footer_or_empty_names_is_not_a_new_reward(self):
        self.assertFalse(next_choice_set(('new',),('old',),True,False,False,('new',),4)[2])
        self.assertFalse(next_choice_set((),('old',),True,True,False,(),4)[2])


if __name__=='__main__':unittest.main()
