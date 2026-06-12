# PR 草稿：Add weekly tasks for the three Treasures Lightward modes

> 分支 `pr/abyss`（基于 upstream/master，3 个 commit）。提交时把下面内容贴进 PR 描述，按需删改。
> 创建命令参考：`gh pr create --repo LmeSzinc/StarRailCopilot --base master --head onglu1:pr/abyss`

---

## What

Three new weekly tasks under the Weekly menu, sharing one machinery package `tasks/abyss/`:

- **PureFiction** (虚构叙事)
- **MemoryOfChaos** (忘却之庭/混沌回忆)
- **ApocalypticShadow** (末日幻影)

One commit per mode, each self-contained and buildable.

## How it works

- **Stage perception**: OCR on stage numbers/status texts plus gold-star cluster counting (counts 0-3 stars per stage; robust against star glint animation and transition fades).
- **Challenge strategy** (per task config): `first_clear` (default, only 0-star stages) / `push` (hammer the first non-3-star stage) / `sweep` (all non-3-star stages) / `highest_only`. `MaxRetry` caps attempts per stage per run; when retries are exhausted, `RetryExceeded` chooses between deferring to the next daily reset or waiting for next Monday.
- **Teams**: applies in-game preset teams (configurable preset index per node) with pixel verification and retry, since clicks during the node-focus animation can be swallowed. Per-node effects (PF buffs / AS axioms) are equipped automatically (first option).
- **In-dungeon loop**: one state machine for all modes — map walking (joystick + A), battle detection via the wave flag (battle UI buttons auto-hide when idle, so on battle entry it blind-clicks auto once, which also wakes the UI, then `CombatState.handle_combat_state()` verifies auto and enables 2x speed), stall watchdog as backstop, settlement exit. AS additionally handles its mid-run settlement (go to node 2 / exit on failed node 1).
- **Failure handling**: a lost battle returns to the prep screen, which is recognized and feeds the retry accounting; locked stages are detected behaviorally (prep never opens) and skipped; stray dialogs (quick-clear offer, material popups, unlock tutorials) have a recovery chain.
- **Rewards**: PF/MoC star-tier panels are claimed after the run; AS grants clear rewards on its settlement directly.

## Tested

On live CN game (1280x720), two accounts (one strong, one mid-strength):

- PF: full season cleared end to end (4 stages, 3-star), season intro popups, reward claiming.
- MoC: stage clears, failed-battle retry, quick-clear confirmation, reward panel.
- AS: stages cleared fully autonomously with 3 stars, mid-run settlement, axiom equipping, two-page boss info, star-origin (3-node) stage detected and skipped, unlock tutorial carousel.
- Offline perception suites (90+ assertions against ~80 captured frames) pass for all assets and scan parsing.

## Known limitations

- **Assets are `cn` only** — I only have a CN client. The OCR keywords are also CN. Happy to adjust the structure if you prefer a different layout for other servers to fill in later. (GUI i18n texts are filled for all five languages with official localized mode names; this limitation is about image assets and in-game OCR keywords only.)
- AS star-origin stages (3 nodes / 3 teams, this season's new mode) are detected and skipped, not yet played.
- MoC scans the currently visible crystals only (the list opens at current progress, which covers normal use).

---

> 备注（不进 PR）：若维护者要求 en 资产或别的结构，再在 pr/abyss 上迭代；fork master 已采纳同一布局，PR 被合并后正常 merge upstream 即可消化。
