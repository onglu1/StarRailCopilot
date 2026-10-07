"""Only the DU-specific interaction appearance; controls stay in SRC."""
from module.base.button import Button, ButtonWrapper

DU_INTERACT = ButtonWrapper(
    name='DU_INTERACT',
    cn=Button(
        file='./assets/cn/divergent_universe/interaction.png',
        area=(779, 407, 811, 438),
        search=(748, 383, 848, 469),
        color=(139, 122, 140),
        button=(784, 412, 807, 433),
    ),
)
