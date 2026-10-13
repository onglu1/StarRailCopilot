# 整局推进统计与验收

最新发布结果见[无人值守上线验收](DU_UNATTENDED_RELEASE.md)：固定版本双开各连续5局，至少9局真实通关，非战斗P50≤60秒、P90≤120秒；恢复或结算重开需有实机证据。

## 统计口径

- 仅统计 `Mode=full`，首站速刷不计整局。固定时刻以后每配置最先开始的5局全部纳入，不挑选成功窗口；仍在进行的局不能算通过。
- 每关从实际识别本关编号到下一关编号或真实结算。仅扣除已记录的原生战斗，保留识别、移动、领奖、加载、暂离重进和故障恢复时间。
- 每次原生战斗被控制器重载打断时，未观察到的时间不得凭空算作战斗；缺失时段的非战斗值只能视为保守上界，不能作为完整计时验收。
- 真实结算并回到入口才能结束一局；确认弹窗、一次战斗、只见新入口都不算结算。胜利、战败、冒险/问题局主动退出、未确认和终止错误分别保留，后四类均不算通关。
- 固定版本要求运行源码/模板指纹一致、每局控制器会话不变、没有受控故障注入。受控实机恢复专项单独列出。
- 重启登录成功不代表恢复成功。须在原run ID观察到后续节点或真实结算；重复故障结算恢复则需实际中断结算和新局第1关。
- P50使用中位数，P90使用nearest-rank。公开样本未删慢关，未把不同版本混作同一版本。

## 只读工具

`dev_tools/du_full_report.py`读取`state/divergent_universe/<配置>.events.jsonl`，输出完整节点、战斗、故障、原生重启和会话信息。

`dev_tools/du_release_report.py`固定选取开始边界以后的首5局/配置，检查完整性、同版本、真实结算、受控注入排除及速度门槛。其默认配置标签为本次本地验收使用的两项；其他配置可调用`du_full_report.build_report`指定配置列表。工具只读日志与状态，不向模拟器输入动作。

PowerShell（仓库根目录，使用已安装项目依赖的Python）：

```powershell
python -m dev_tools.du_full_report --profiles profile_a profile_b --since 2026-10-13T10:35:22 --out full-run-report.json
python -m unittest dev_tools.test_du_recovery -v
```

原始截图、完整日志和checkpoint不随源码发布。去除个人标识后的[最终汇总](validation/du-release-20261013-summary.json)及[逐关CSV](validation/du-release-20261013-rooms.csv)保留全部130关，包括3次自然故障后的恢复耗时。历史开发记录继续保存在维护者本地，没有用本次汇总替换或清空游戏历史。
