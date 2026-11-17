"""Only the observed first Life Divergence page gets a star-safe preset."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from module.base.button import ClickButton
from module.config.config import TaskEnd
from tasks.divergent_universe.events import DivergentEvent, MAINTENANCE_REGION
from tasks.rogue.event import event as native
from tasks.rogue.keywords import KEYWORDS_ROGUE_EVENT_OPTION as O, KEYWORDS_ROGUE_EVENT_TITLE as T


class LifeDivergenceTests(unittest.TestCase):
    def handler(self,star=True,title=None):
        handler=object.__new__(DivergentEvent)
        handler.config=NS(RogueWorld_DomainStrategy='review-fixture')
        handler._du_main=NS(active={'id':'run','mode':'star' if star else 'full',
                                   'star':{'candidate':'dot'} if star else None})
        handler.event_title=title
        handler.device=NS(image=object(),click=Mock(side_effect=AssertionError('filter must not input')))
        handler.appear=Mock(return_value=False)
        handler._event_option_ocr=Mock()
        handler.options=[native.OptionButton(ClickButton((600,200,620,220)),
                            NS(matched_keyword=O.Ignore_the_mistakes)),
                         native.OptionButton(ClickButton((600,400,620,420)),
                            NS(matched_keyword=O.Perform_corrections))]
        return handler

    def native_filter(self,handler,strategy,title_result=None):
        with patch.dict(native.STRATEGIES,{'review-fixture':strategy}), \
             patch.object(native,'SCROLL_OPTION',NS(appear=Mock(return_value=False))), \
             patch.object(native,'OcrRogueEventTitle') as ocr, \
             patch.object(native.random,'choice',return_value=0) as random:
            ocr.return_value.matched_ocr.return_value=([NS(matched_keyword=title_result)] if title_result else [])
            result=handler._event_option_filter()
        return result,random

    def test_exact_native_keyword_wins_after_native_title_read_without_preset_leak(self):
        handler=self.handler();strategy={}
        result,random=self.native_filter(handler,strategy,T.Life_Divergence_I)
        self.assertIs(result,handler.options[1])
        self.assertIs(handler._du_selected_option,handler.options[1])
        self.assertEqual(result.button.matched_keyword.id,647)
        handler._event_option_ocr.assert_called_once_with(2)
        random.assert_not_called();handler.device.click.assert_not_called()
        self.assertNotIn(T.Life_Divergence_I,strategy)

    def test_nonstar_second_chapter_and_maintenance_keep_native_behavior(self):
        for star,title in ((False,T.Life_Divergence_I),(True,T.Life_Divergence_II)):
            handler=self.handler(star,title);strategy={}
            result,random=self.native_filter(handler,strategy)
            self.assertIs(result,handler.options[0]);random.assert_called_once()
            handler._event_option_ocr.assert_not_called();self.assertEqual(strategy,{})
        handler=self.handler(True,MAINTENANCE_REGION)
        bottom=handler.options[1];bottom.button.matched_keyword=O.Ignore_him;bottom.is_bottom_page=True
        strategy={MAINTENANCE_REGION:[O.Ignore_him]}
        result,_=self.native_filter(handler,strategy)
        self.assertIs(result,bottom)
        self.assertEqual(strategy,{MAINTENANCE_REGION:[O.Ignore_him]})

    def test_unknown_title_missing_safe_option_and_native_failure_do_not_invent_choice(self):
        handler=self.handler();result,random=self.native_filter(handler,{})
        self.assertIs(result,handler.options[0]);random.assert_called_once()
        handler=self.handler(True,T.Life_Divergence_I)
        handler.options[1].button.matched_keyword=O.Ignore_the_mistakes
        strategy={T.Life_Divergence_I:[O.Ignore_the_mistakes]}
        original=strategy[T.Life_Divergence_I]
        result,_=self.native_filter(handler,strategy)
        self.assertIs(result,handler.options[-1])  # Native unmatched-preset fallback.
        self.assertIs(result.button.matched_keyword,O.Ignore_the_mistakes)
        self.assertIs(strategy[T.Life_Divergence_I],original)
        for error in (TaskEnd(),RuntimeError('native OCR failed')):
            handler=self.handler(True,T.Life_Divergence_I)
            handler._event_option_ocr.side_effect=error
            with self.assertRaises(type(error)):self.native_filter(handler,strategy)
            self.assertIs(strategy[T.Life_Divergence_I],original)


if __name__=='__main__':unittest.main()
