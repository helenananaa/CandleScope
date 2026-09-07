# F08c 观测成交误称连续

问题：观测模式说明明确不保证交易所序列连续，但共用 live 标签中文仍称“实时连续”，英语称 Live stream，对轮询或仅观测到的成交造成过度承诺。

修复：九种语言的 live 状态改为“有新成交 / Recent trades”等，只表达近期存在成交；连续性由已有严格/观测模式说明表达。等待、60 秒无成交、错误和重连状态不变。

验证：check:i18n、Production build、git diff --check 通过。电脑操控发行版确认观测模式和旧成交提示正常展示；当前数据仍旧，本轮未现场切入有新成交分支，文案内容通过目录检查确认。证据 output/user-audit-20260907/evidence/fix-F08c-state.png/.txt，日志 fix-F08c-i18n.log、fix-F08c-build.log 位于其上级目录。

F08 的全局连接状态适用范围仍待处理。
