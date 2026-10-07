from module.logger import logger
from tasks.apocalyptic_shadow.assets.assets_apocalyptic_shadow_battle import (
    AS_GOTO_NODE2,
    AS_SETTLE_BACK,
    AS_SETTLE_EXIT
)
from tasks.apocalyptic_shadow.prep import ApocalypticShadowPrep


class ApocalypticShadow(ApocalypticShadowPrep):
    SETTLE_BUTTON = AS_SETTLE_BACK

    def abyss_mid_settle_handler(self) -> bool:
        """
        Apocalyptic shadow shows a mid-run settlement after node 1 with
        exit / retry / go-to-node-2 buttons, continue to node 2.
        If node 1 failed there is no go-to-node-2, exit instead.
        """
        if self.match_template_color(AS_GOTO_NODE2, interval=3):
            logger.info(f'{AS_GOTO_NODE2} -> click')
            self.device.click(AS_GOTO_NODE2)
            return True
        if self.appear(AS_SETTLE_EXIT, interval=3) and not self.match_template_luma(AS_GOTO_NODE2):
            logger.info(f'{AS_SETTLE_EXIT} -> click, node 1 may have failed')
            self.device.click(AS_SETTLE_EXIT)
            return True
        return False

    def run(self):
        self.abyss_run('ApocalypticShadow')
