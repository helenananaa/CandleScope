# 持续策略当前代码与参数恢复边界

本批为持续策略控制器准备内部provider定义与重建工厂。只接已资格的内置/SDK Python收盘BAR provider；Pyne明确拒绝，Pine与external留待各自时钟/连接恢复合同。尚未接HTTP/WS、用户三模式按钮或默认应用启动恢复，#157/#158/#165不因此完成。

运行定义只保存一份当前代码、参数、输出模式、明确选择的Python运行模式及布尔确认；内部builtin实现标识不等于用户管理的策略历史版本。准备只作有限JSON/AST/作者协议校验，无用户代码执行、文件写入、StrategyRevision/假dataset/snapshot/smoke记录。实际创建仍需控制器完成财务与输入校验，工厂不能替代这些责任。固定历史路径既有snapshot smoke规则完整保留。

固定历史与持续编辑器代码共用同一SDK bundle文件构造，复用现有AST静态诊断、独立Python进程与能力边界。重建只读运行自有定义，不引用当前编辑器或数据库策略版本；拒绝定义、财务配置和输入计划之间的语言/参数/源/输出错配。Python源256KiB、参数64KiB、结构深度64/节点10000；完整定义/检查点仍受既有Store预算。没有额外防篡改哈希或逐事件复制，现有runner使用有界transcript。

每个Python provider拥有独立、最多既有bundle上限1MiB的临时进程输入；完整定义/源在金融Store中，临时路径不进检查点。物理退出后删除自己的临时目录；关闭失败保留至显式重试。controller今后必须拥有scratch根目录，先排空Runtime再回收，并处理进程崩溃遗留；本批未声称已解决默认应用启动时的遗留回收。sandbox不可用会显式报错，不回退到TRUSTED_LOCAL；可信编辑器仍须明确确认。

最终109项本地组合通过、5条既有FastAPI提示，含Python bundle/编辑器固定历史/财务控制平面/持续Store、Host、源与Manager生命周期。内置和真实Python SDK进程11→20→25恢复与固定历史参考的决策、订单、成交、流水、权益一致。另在新的后端Python父进程从持久化定义与第11根检查点恢复至第25根，结果相同，provider子进程完全退出且自有临时源已清理。修改原始编辑器请求不改变保存定义；不支持语言、非法源/参数、混用输入和失效sandbox均被拒绝。该证据是源码与实际本机Python进程，不是安装包完整退出/重启或Windows验收。

第一次扩展测试命令误写test_python_strategy_bundle.py（实际为bundles），未执行用例；纠正后105通过，加入退出/单份定义回归后最终109通过。架构与main原有10条逐字节一致。CI增加实际provider回归，不等待CI开发；合main前核对最终head。

Host仅在factory校验通过后派生临时配置与输入计划，不把源和参数重复保存三份。旧的手工Host fixture定义保持原状。最终代码包含新的Host接线和UTF-8/结构预算检查；完整109项复跑通过。

## CI继承失败后的组合

原8952f5b0的x64 job在未变化的Klines日历尾部1秒用例耗时1.2726秒失败（其余1565通过、3跳过），不能合main。已无冲突整合#248日历直接定位修复及#244共享权重：应用组合1ae6e6db，provider/编辑器/Host/持续Runtime/Manager、日历与Klines、公网准入的本地238通过、6条提示。原1秒门槛保持，完整原CI失败和性能/语义证据在session-calendar-tail-20261104；新最终head CI须另行资格，开发继续，不等待。
