# Fork 自有功能待办与技术调研

> 本文档记录这个 fork 要做的自有功能、已查明的技术事实和实现方案。
> 仓库约束和写码规则见根目录 [CLAUDE.md](../../CLAUDE.md)。
> 状态标记：⬜ 未开始 / 🟨 进行中 / ✅ 完成

## 🟨 功能 1：打深渊

忘却之庭/虚构叙事/末日幻影，注册进 GUI 和调度器。

**🗑 自动配队 v1（2026-06-12 晚 ebf557d7，2026-06-13 移除——见上方产品定型）**：三任务各加 `CandidateTeams` 参数（候选预设序号、强度从高到低，留空=旧行为）。`tasks/abyss/composer.py`：预设面板识别成员（assets/character 脸模板 1.10 倍 + 卡片元素徽章色相分类兜底未知新角色，空槽=无饱和像素；行定位=固定 172 行距网格相位搜索+脸命中精化）→ 准备屏读节点弱点（assets/element/weak_* 裸字形多尺度，AS 约 0.65 倍）→ 评分（植入角色流萤/银狼/波提欧/乱破无视弱点 > 元素命中 > 未知 0.5 + 顺序先验）→ 有序不重叠配对（同人异形态归一：开拓者/三月七/丹恒），attempt 序号轮换组合（凹分衔接 MaxRetry 记账）。wly 实测：PF 关4 固定预设 0★ → composer 选双冰+流萤队一把 1★，全链路日志验证。45 离线断言（log/pf_dev/test_composer.py）。**已知缺口**：物理徽章无样本（hue 网关未实测）；预设 4+ 的签名寻找点击路径未实测（wly 仅 4 预设且当次选中 1/3）；新预设套用与另一节点残留队伍冲突时的游戏行为未验证（依赖 abyss_set_team 3 次重试 + filled 校验兜底）；first_clear 不重打 1-2★ 关（凹满星用 push/sweep）。

**⬜ 后续：自动配队/灵活配队**——现状两个固定预设序号对低练度号难满星。方案调研完成（同行项目/数据源/其他游戏先例/战斗模拟可行性），详见 [2026-06-12-team-comp-research.md](2026-06-12-team-comp-research.md)。**计划提上游**：面向维护者的分级提案（1 候选对轮换→2 弱点匹配→3 编队自动识别，模拟/统计/米游社 API 明确排除）见 [team-comp-proposal-upstream.md](team-comp-proposal-upstream.md)，用户拿去与维护者讨论（建议贴在上游 #298，维护者自开且仍 open）。关键论据：上游实质单人维护（LmeSzinc 1866 commits vs 第二名 72）；CharacterList 关键词已含 type_name/path_name 五语言（keyword_extract 每版本再生，角色→属性映射零边际成本）；switch.py 已有 OcrCharacterName + 头像模板两套角色识别先例。若上游不收，按调研文档的 fork 层方案（含 B0 自己战报/B1 MocStats 等上游不适合的增强）实施。设计定型（用户反馈）：命途是伪信号仅作生存位兜底；体系标签（击破/超击破/DOT/追击/记忆/群攻…）为引擎，词表/角色标签/亲和表全在数据文件（社区 PR+用户 override+缺失降级不卡版本）；队伍体系=主C体系；用户预设即固定队伍，社区固定队模板库延后到 C 路线。凹分模式（用户提出）：候选按打分排序穷举到目标星数，打分降级为排序器、实战做真值，不新增模式名（push/sweep 隐含满星目标+MaxRetry 泛化为单关总预算），#298 有需求存量。

**✅ 产品定型简化（2026-06-13，用户使用后定向）**：真实用法="两套万金油先碾一遍，打不过的手动调队后让脚本死磕"，多策略+自动配队无意义。定型为：策略=默认（只打最高可挑战）/攻坚（循环第一个未满星）/指定（AssignedStage 手动指定层）；编队=固定两预设，**失败重试自动上下交换**，MaxRetry 语义=单层最多轮数；PF 增益=BuffSelect 选第 1/2/3 个或随机（卡片高度随文案可变，卡 2/3 用 OCR 标题锚定，失败回退卡1）；任务回每周菜单排最后，Enable 关=不进调度（框架原生）。**移除**：composer 自动配队 + CandidateTeams + assets/element + 工具页白名单（代码在 ebf557d7/3234ade0 可捞回）。**待办**：pr/abyss 三连 commit 还是旧设计（first_clear/sweep/CandidateTeams 前身），提交 PR 前需按定型设计重切。

**✅ 战斗 auto/2x 对齐上游状态机（2026-06-13，用户实测反馈）**：删除"进场盲点 AUTO"——用户开着二倍速、关着自动进战斗时，盲点+淡入期误读会把二倍速点关。现在 auto/2x 全由上游 `handle_combat_state` 驱动（总闸=暂停键可见，读真实按钮状态只点没开的），额外约束：总闸连续两帧通过才放行（防 HUD 淡入误读）；HUD 隐藏且 auto/2x 未核验时才发唤醒点击（点 AUTO 位置，深渊开局必 auto-off 故无害，误翻会被状态机自纠）；停滞看门狗改为"可见只重置状态机、隐藏才唤醒"。注意首夜结论"按钮检测不到"只对 HUD 闲置隐藏后成立，进场窗口按钮可见。

**✅ 工具页接入 + 导航回归框架标准（2026-06-12 深夜）**：用户实点暴露两洞已修（bb89e7b0/5c097b25）：① 工具页启动有硬编码白名单 `module/webui/submodule/utils.py get_available_func`（[fork] 加三任务名）；② 手动运行路径不绑定任务，src.py 三方法需显式 `task="..."` 否则静默读模板默认（实测 unbound=None vs bound='1,2,3,4'），与 daemon/planner_scan 同款写法。三任务移到 Tool 菜单（page:tool，点击→设置+启动按钮+实时日志，`alas.start(task)`→`run(underscore)` 即跑；Scheduler 组保留，每周调度不受影响——调度器只看 Scheduler 组不看菜单）。导航删掉自造的"回主界面+escape 重试"包装，改为与 Dungeon 相同的裸 `ui_ensure(page_guide)`；框架恢复语义已核实：GameNotRunning/GameStuck→自动 Restart，**GamePageUnknown→exit(1)+推送（不会自动恢复）**，故保留"准备屏先退出"守卫（非注册页面）。任务域内的 escape_stray_dialog/exit_prep 仅在自有流程中使用。**重构候选**：composer 预设面板滚动改用 module/ui/scroll.py 的 AdaptiveScroll（support.py 用法）；脸模板加载复用 SupportCharacter.load_image。注意与 pr/abyss 的分叉：PR 保持 Weekly 菜单，合并时 task.yaml 取一边。

**⬜ 后续：末日幻影星启模式（难度4，3节点3编队）**——当前检测到后优雅跳过；完整支持需：第3套编队配置项、3行准备屏坐标适配（布局与常规不同，数字块标记节点）、`前往节点三` 中场资产。另：MoC 选关 v1 只扫当前可见水晶（默认停在进度处，足够覆盖正常使用）；MoC 1-2 星关卡不会重打（金星检测只分有星/无星）。

**✅ PR 化重构（2026-06-12 中午，master f41f7153）**：共享层抽成独立 `tasks/abyss/` 包（stage 感知与选关 / nav 导航与恢复 / prep 配队 / combat 副本循环与奖励），三任务线性继承零跨模式依赖；共享资产移到 `assets/{share,cn}/abyss/`（PF_WAVE_FLAG→WAVE_FLAG）。PR 分支 **`pr/abyss`** 基于 upstream/master，三个干净 commit（Add: PureFiction / MemoryOfChaos / ApocalypticShadow），无 fork 标记无 fork 文档，每个 commit 自洽可构建。master 已采纳同一布局——**深渊相关条目在上游文件里不再打 `# [fork]` 标记**（以 PR 分支为准识别，PR 合并后随上游同步自然消化）。注意：资产仅 cn，PR 描述里需说明 en 资产缺口。

**✅ 第二轮改进完成（2026-06-12 上午，commit 0b0660da）**：快速 auto+二倍速（复用上游 CombatState，3 秒内全开）；挑战策略改为 首通/攻坚/扫描/只打最高 + 单关重试上限 + 超限 defer/give_up；PF/MoC 星数奖励自动领取（AS 结算自发无需领）；金星簇数星感知；快速通关弹窗/迷路弹窗/未注册 prep 屏的恢复链。ztj 弱号实测通过。

**✅ 三模式全部完成（2026-06-12）**：`PureFiction` / `MemoryOfChaos` / `ApocalypticShadow` 三个任务（Weekly 组），代码在 `tasks/pure_fiction|memory_of_chaos|apocalyptic_shadow/`，共享基类在 `tasks/pure_fiction/abyss*.py`。设计与实测记录见 [2026-06-12-pure-fiction-design.md](2026-06-12-pure-fiction-design.md)。流程：自动导航 → 按挑战策略选关（默认从最低难度逐层，highest_only 可选）→ 套用游戏内预设编队 1/2 + 每节点装第一个增益/公理 → 走图触敌 → 停滞看门狗保 AUTO → 两半场（AS 含中场结算）→ 结算退出 → 循环 → 延到下周一 04:00。用户侧启用：GUI → 周常 → 各任务 → Enable。

- ~~上游已有底子：`tasks/forgotten_hall/`~~ 实测上游该目录代码已烂（tab switch 缺 Treasures_Lightward 状态，玩法是老版走图）。PF 实现未复用它，仅复用了其 `TELEPORT` 资产（0.999 匹配）。MoC/AS 建议直接仿 `tasks/pure_fiction/` 的骨架（选关 OCR 多趟并集、状态机循环、停滞看门狗都可搬）。
- 注意：**PF 战斗界面没有标准位置的暂停/AUTO/2x 按钮**（上游 `is_combat_executing` 失效），MoC/AS 是否同样需要实测确认。
- 云崩铁与本地客户端**共用一份代码**：客户端差异只在登录壳层（`tasks/login/cloud.py`、`login.py`、`base/ui.py`、`rogue/entry/entry.py`、`src.py` 共 5 处分支），玩法任务全部基于截图识别，客户端无关。深渊功能只写一份。
- 可选借鉴：`rogue/entry/entry.py:338` 的"云游戏且无畅玩卡则跳过"开关，避免长任务烧免费时长。

## ⬜ 功能 2：日常任务一天一次模式

任务成功完成后直接延到第二天（服务器刷新时间），不在一天内重复调度。

- 现状：Dungeon 等任务按体力回复重新调度，一天会跑多次。
- 要改的是任务完成后的重调度逻辑（`task_delay`），具体方案实现时再定。

## ⬜ 功能 3：多配置连同一模拟器的不同应用分身

onglu/ztj 两个配置连同一个 MuMu 实例里的两个星铁分身（2026-06-11 实测）。

**现状拓扑：**

```
MuMu 多开器（MuMuNxMain.exe 只是管理器界面，VM 本体是 MuMuVMMHeadless.exe，窗口是 MuMuNxDevice.exe）
├── 实例 0 "wly"  → 127.0.0.1:16384  ← onglu 配置（云客户端），常用
│     ├── user 0:  com.miHoYo.hkrpg（本地国服）+ com.miHoYo.cloudgames.hkrpg（云星铁）
│     └── user 10: com.miHoYo.hkrpg（分身，nemu_multi_user_10）
│         └── 即"星铁wly"/"星铁ztj"两个图标（哪个名对应哪个 user 待实测）
└── 实例 1 "ztj"  → 127.0.0.1:16416  ← ztj 配置（本地客户端），平时关机
```

**目标态**：两个配置都连 wly 实例（16384）内的两个本地分身，弃用 ztj 实例。

**已查明的技术事实：**

- MuMu 应用分身 = Android 多用户机制，同一包名 `com.miHoYo.hkrpg` 装在 user 0 和 user 10 下，ADB 用 `--user <id>` 区分。
- 前台是哪个分身：`dumpsys activity` 的 ActivityRecord 带 `u0`/`u10` 标记。
- 截图/点击是显示层操作，与用户无关，无需改动；要改的是 app 启动/停止/前台检测的 user 感知，外加一个配置项（如"分身用户 ID"）。
- 两个配置共用同一块屏幕，**绝不能同时跑**，需要设备级串行机制（如按 serial 的文件锁）。

**MuMu 实例管理命令**（`C:/Program Files/Netease/MuMu Player 12/nx_main/MuMuManager.exe`）：

- `info -v all` —— 查全部实例名/端口/状态（JSON，关键字段 `is_process_started`、`is_android_started`、`player_state`、`adb_port`）
- `control -v <index> launch|shutdown` —— 启停实例（同步返回 errcode）
- **杀 `MuMuNxMain.exe` 进程关不掉虚拟机**（教训：2026-06-11 两次误杀只关掉了管理器界面）。

## ⬜ 功能 4：MuMu 12 启动可靠性改造

解决"有概率打不开模拟器 / 找半天打不开 / 能启动一个启动不了另一个"（2026-06-11 诊断，上游 master 8ceaf2ca）。

**上游 `module/device/platform/platform_windows.py` 的问题：**

1. `emulator_start()` 永远先 shutdown 再 launch，两步都是 Popen fire-and-forget，**中间不等待**——半关机状态上叠加启动 → 概率性启动失败（症状"有概率打不开"）。
2. `_emulator_function_wrapper` 只看 Popen 是否抛异常，"进程拉起来了"≠"模拟器启动了"。
3. `emulator_start_watch()`（180 秒轮询 adb）超时返回 False **被忽略**，`emulator_start()` 照样返回 True；上层误判后下一轮重试的 shutdown 会把快启动好的实例干掉重来——机器越忙越陷循环（症状"找半天打不开"，最坏 3×180s 内层 + 4 次外层重试）。
4. 全程不查 MuMu 真实状态，只靠 adb 连通性推断，而 MuMu 启动期 adb 恰恰最不可靠。
5. **多配置并发启动竞态**：`MuMuNxMain.exe` 单主进程托管所有实例窗口，两个调度进程同时各发 `-v 0`/`-v 1` 时，后到的命令打到正在初始化的主进程上会被静默丢弃；叠加双 VM 同时冷启动的资源竞争（症状"能启动一个启动不了另一个"）。
6. 已实测**排除**实例发现问题：两实例 `.nemu` 的 ADB_PORT 转发记录正常（16384/16416），serial→实例匹配无误。

**改造方案：**

- 新建自有 Platform 子类（如 `module/device/platform/platform_mumu_fork.py`），基于 MuMuManager 做状态机：
  - 启动前先 `info` 查状态，已在运行则跳过启动直接连 adb；
  - 需要启动用 `control launch`，轮询 `info` 至 `is_android_started` 再连 adb；
  - 关机用 `control shutdown`，轮询至状态落定；
  - 所有命令同步等待并检查 errcode。
- 跨进程文件锁串行化"启动模拟器"这一段，消除并发竞态。
- 接入点：`plat.py` 一行切换，加 `# [fork]` 标记。
- 与功能 3 互补：单实例化减少启动次数，本功能保证每次启动必成功。

**上游 PR 查重结果（2026-06-11）**：最小修复已做完并推到 fork 分支 `fix_emulator_start`（重写后 e22347b9），查重确认不重复——SRC 从无 PR 动过启动路径；SRC#904（症状相同，4 点启动失败）根因是 device 缓存未清，已由 SRC#916 修复，与本修复互补；Alas 仓库同文件同 bug 未修；Alas#4049（开放）指出 MuMu 4.0 后 `api` 命令族为旧式、官方推荐 `control`，PR 中应引用说明选 `api` 是为与既有 shutdown_player 一致。若上游不收，按上文状态机方案在 fork 实施。

**PR 已提交，维护者问 3.x/4.x 兼容性，验证完成（2026-06-12）**：从官方 CDN 下载 V3.6.4.2333 和 V4.1.10.3552 离线包（均验过 NetEase 签名）实机安装验证——V3.6.4 帮助文本明文列出 `api launch_player`，实际执行返回 `player launch: result=0`；V4.1.10 新式 CLI 下 `api` 作为兼容垫片继续可用，`launch_player` 同样 result=0 且窗口能拉起。结论：3.x（≥3.3.7）/4.x/5.x 全支持，与既有 shutdown_player 同命令族同版本下限。注意：旧版客户端有服务端强制升级门（启动后要求升级），不影响 CLI 接口结论。两个旧版安装包已存到用户 Downloads；本机 `MuMuPlayer-12.0` 目录现装的是 V4.1.10（3.6.4 被原地覆盖，3.x/4.x 同目录互斥），与 5.0 的 `MuMu Player 12` 目录共存。

## 实施顺序建议

功能 4（最独立，适合当第一个 `[fork]` 提交验证防冲突规则）→ 功能 1 骨架 → 功能 3 → 功能 2。
