# 持续运行创建定义与财务预检

依赖#245的单份当前代码/参数provider定义，为创建控制器提供有限纯预检。输入Manager的完整SeriesKey、当前代码、执行条件和预热BAR数；只生成可保存的定义，不建立运行、用户策略版本/快照smoke记录、市场订阅、输入复制或provider进程。不是已接线的HTTP/WS或三模式UI，#157/#158/#165继续开放。

从固定历史_execution_from_payload原样提取26条基础账户/费用/Host风控/费率确认校验，AST与父提交8952f5b0逐条一致；固定历史随后原有provider版本和选定快照smoke校验不变。创建定义复用该公共财务预检、既有执行真实度与价格/数量约束，不伪造StrategyRevision或snapshot来跳过旧规则。配置64KiB、预热0–200000根闭合BAR、有完整11维源身份。源/参数只保存一份。

首个合同限定原生crypto、raw、continuous、base_asset、UTC1m；Spot现金账户须明确匹配Spot，合约只接现有Binance USD-M profile的market_type=futures/V1线性账户。别名usdm、币本位、其他合约、V2/历史标记或规则、资金费、杠杆不为1、跨gap跳过均显式拒绝，后续需各自资格而非静默降级。费用/仓位风控/实际度参数与固定历史归一化结果一致，孤立风险或真实度字段拒绝。预检并不替代创建时的来源前缀围栏、实际provider准备与原子账户创建；控制器仍待实现。

最终本地192项通过、5条既有FastAPI提示；包含固定历史版本smoke、编辑器、Host风控、Spot现金、执行模型与持续源/Store/Runtime/Manager/退出。内置和真实SDK Python在实际Spot/合约Manager SQLite数据上，冻结首20根，按7根批量执行，转后5根尾部；同一次账户的决策/订单/成交/流水/权益与相同输入固定参考一致。非法财务/账户/源和资源前校验均有回归。

另外使用当前SDK/bridge与已资格Pine0.3.3+cs.1实际核心进程，BAR/V2工作台27通过、1条提示；元数据记录来源和二进制sha。不能当成Pine持续执行或安装包保存/完全退出重启、Windows验收。后端架构与main原有10条逐字节一致。CI新增创建定义回归，开发期间继续后续任务，合main前再核对最终head。

初次测试误用SeriesKey构造参数identity导致收集失败；改用create后，集成用例暴露项目Manager市场名是futures而非内部profile名usdm。对照实际Binance USD-M profile修正支持合同与测试源，不增加别名绕过或放宽capability，保留两份失败日志；144项通过后再扩展Spot/退出组合到最终192项。
