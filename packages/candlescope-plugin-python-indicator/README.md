# Python 指标运行时

开发中的 `python.indicator.batch/1` 指标作者入口，通过 CandleScope Script Runtime SDK
接入；桌面构建默认打包并启用，已有显式路由配置保持优先。编辑器和原生图表验证尚未完成。

作者定义 `compute(bars, params)`，返回 `{"lines": {"main": values}}`。
`bars` 是不可变列字典，包含 `time/open/high/low/close/volume/isClosed`；每个输出与
输入位置严格对应，预热不足用 `None`。可选字面量 `INDICATOR` 声明名称、overlay、
window、parameters 和 outputs。默认窗口为 500，最大 10000 根，输出最大 16 个。
输出 ID 遵循公共绘图协议的小写标识符规则。

运行时按声明窗口选择最近确认输入，输出明确报告计算偏移、窗口和排除的形成中尾部。
较早输入和形成中尾部输出为 `None`；窗口变化会改变算法起点，不承诺等于全历史递归计算。
当前为收盘批量模式，每次调用使用新的 Python 进程，支持 line 和 histogram。
源码分析仅解析 AST 字面量声明，不执行模块。参数拒绝未知字段及隐式类型转换。

当前依赖 profile 为标准库；NumPy/pandas 和状态增量接口尚未提供。
任意函数的因果资格保持 `unverified`，不能据此认证策略或回测信号。
进程提供执行与依赖边界，不是完整安全沙箱。POSIX 退出会清理执行进程组；Windows
原生进程树清理与平台资格单独验证。此 Python 契约独立于 Pine 和 Python 策略。
