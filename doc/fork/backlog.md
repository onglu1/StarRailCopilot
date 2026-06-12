# Fork 自有功能待办与技术调研

> 本文档记录这个 fork 要做的自有功能、已查明的技术事实和实现方案。
> 仓库约束和写码规则见根目录 [CLAUDE.md](../../CLAUDE.md)。
> 状态标记：⬜ 未开始 / 🟨 进行中 / ✅ 完成

## 🟨 功能 1：打深渊

忘却之庭/虚构叙事/末日幻影，注册进 GUI 和调度器。

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
