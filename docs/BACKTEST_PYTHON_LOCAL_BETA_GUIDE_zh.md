# Python 策略指南

在图表旁边用 Python 写策略并回测。策略只负责决策；行情数据、撮合、费用、资金费、风控、
账户、报告和参数研究都由 CandleScope 生成。

Python 策略在桌面应用和源码安装中运行，浏览器版不支持。

## 第一次运行

1. 在桌面应用中打开一个图表，打开它的 **策略测试器**。
2. 选择 **使用策略模板** → **SMA 交叉**，模板会复制为可编辑草稿，并自动保存。
3. 阅读编辑器旁的权限说明，勾选“我已阅读以上权限说明，并接受在本机沙箱外运行 Python”。
4. 点 **运行**。结果出来后，交易标在图上，**概览** 和 **交易** 标签页给出报告和每笔交易。

运行只使用图表上已有的历史。图表还在准备历史数据时，请等它加载完再运行。

### 权限说明

图表策略以 `TRUSTED_LOCAL` 方式运行：策略代码在一个普通的本机 Python 进程中执行，
没有 AppContainer 隔离，可以访问该进程能看到的解释器和文件系统。只运行你信任的代码。
桌面版使用应用自带的 CPython 3.12。

勾选只对当前草稿的当前源码有效。改动源码或换一个草稿后，需要重新勾选。

### 跟随实时行情

图表上的结果只覆盖已有历史，不会随着新 K 线收盘自动延伸。要让 Python 策略在实时 K 线上
继续运行，在策略面板的 **运行模式** 中选择 **历史接实时** 或 **纯实时**（默认是 **纯历史**）。
这两种模式只支持 1 分钟图表。

## 策略结构

策略是一个 `Strategy` 类，必须实现全部七个方法，缺一个都会在运行前报错：

| 方法 | 作用 |
| --- | --- |
| `prepare(context)` | 初始化状态；`context.parameters` 是本次运行的参数 |
| `warmup(observation)` | 读取回看窗口内的 K 线，只建立状态，不返回决策 |
| `step(observation)` | 每根完结 K 线调用一次，返回一个决策 |
| `on_execution_report(report)` | 收到宿主对上一个决策的执行回报 |
| `snapshot()` | 返回可 JSON 编码的状态 |
| `restore(payload)` | 从 `snapshot()` 的结果恢复，之后的决策必须与未中断时相同 |
| `close()` | 运行结束 |

`step` 只能返回以下一种决策（都从 `candlescope_backtest_sdk` 导入）：

- `Signal(direction=...)`：`LONG`、`SHORT` 或 `FLAT`
- `TargetPosition(quantity=...)`：绝对目标仓位数量
- `OrderIntent(side=..., type=..., quantity=...)`：`MARKET`、`LIMIT`、`STOP` 或 `STOP_LIMIT`

宿主把数量映射为仓位或订单。返回值是意图，不是已接受的订单；是否成交看
`on_execution_report` 收到的回报。

`observation.bar` 有 `open_time_ms`、`close_time_ms`、`open`、`high`、`low`、`close` 和
`volume`。价格和数量是十进制字符串，计算前自己转换，例如 `float(observation.bar.close)`。

最小示例（即 **SMA 交叉** 模板）：

```python
from candlescope_backtest_sdk import Signal


class Strategy:
    def prepare(self, context):
        self.fast = 3
        self.slow = 5
        self.closes = []

    def warmup(self, observation):
        self.closes.append(float(observation.bar.close))
        self.closes = self.closes[-self.slow:]

    def step(self, observation):
        self.warmup(observation)
        if len(self.closes) < self.slow:
            return Signal(direction="FLAT")
        fast = sum(self.closes[-self.fast:]) / self.fast
        slow = sum(self.closes) / len(self.closes)
        return Signal(direction="LONG" if fast > slow else "FLAT")

    def on_execution_report(self, report):
        pass

    def snapshot(self):
        return {"closes": list(self.closes)}

    def restore(self, payload):
        self.closes = list(payload["closes"])

    def close(self):
        pass
```

## 数据和不看未来

`Observation` 只包含当前已完结的 K 线和时间水位。`warmup` 只拿到回看窗口；`step` 只在水位
推进后调用。策略看不到未来的 K 线，也读不到完整的历史表或数据库。需要更长的回看时，在策略
状态里保留一个有限窗口，并写进 `snapshot()`。

运行前的静态检查会拒绝这些导入：`app`、`sqlite3`、`socket`、`http`、`urllib`、`requests`、
`subprocess`、`multiprocessing`、`ctypes` 和 `pathlib`。

## 撮合精度

`BAR_APPROX` 用 K 线近似成交，不代表 K 线内部只有一种价格路径。`AGG_TRADE_EXECUTION`
使用聚合成交，不是逐笔成交，也不模拟挂单排队。

## 常见错误

| 错误代码 | 含义 |
| --- | --- |
| `BUNDLE_STATIC_DIAGNOSTIC` | 静态检查失败：语法错误、缺少生命周期方法或使用了被拒绝的导入；错误给出行列 |
| `TRUSTED_LOCAL_UNCONFIRMED` | 运行前没有勾选权限说明 |
| `NEEDS_DATA` | 图表的历史还没准备好；等图表加载完再运行 |
| `PROVIDER_TIMEOUT` | 策略进程在限定时间内没有返回 |
| `PROVIDER_CRASH_UNRECOVERABLE` | 策略进程异常退出，无法恢复 |

失败面板和错误的 `details.next_step` 会写出下一步该做什么。

## 参数研究

**在高级研究中打开** 可以对同一份源码和参数定义做参数批量和走前（walk-forward）样本外
检验。测试窗口不参与参数选择；样本外结果只由测试窗口的运行拼成。参数空间的写法见
`packages/candlescope-backtest-sdk/templates/study_parameter_space.json`。

## 从普通 Python 脚本迁移

1. 去掉遍历整张 DataFrame 的循环和直接下单的函数。
2. 把状态放进 `prepare`、`snapshot` 和 `restore`。
3. 每根完结 K 线只返回一个决策。
4. 不要导入 `app`、`sqlite3` 或网络库。

## 开发者：官方模板与离线探针

SDK 和官方模板在 `packages/candlescope-backtest-sdk`：

- `templates/sma_cross`
- `templates/rsi_wilder_24`
- `templates/donchian_breakout`
- `templates/mean_reversion`
- `templates/buy_and_hold`
- `templates/always_flat`
- `templates/order_intents`
- `templates/snapshot_restore`

每个模板目录写明策略假设、信号时钟、warmup、参数范围、支持的撮合精度和不能声称的内容；
golden hash 在 `templates/goldens/<name>.json`。`fixtures/` 是作者合同探针，不是模板。

不启动应用也能验证模板。在仓库根目录用 PowerShell 执行（不联网安装任何包，也不改用户级
`PYTHONPATH`）：

```powershell
$Offline = Join-Path $env:TEMP ("cs-py-first-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Offline | Out-Null
Set-Location packages/candlescope-backtest-sdk
python -m pip wheel --no-deps -w "$Offline\dist" .
python -m pip install --no-index --no-deps --target "$Offline\site" (Get-ChildItem "$Offline\dist\*.whl").FullName
Copy-Item -Recurse templates "$Offline\templates"
$env:PYTHONPATH = "$Offline\site"
$env:PYTHONNOUSERSITE = "1"
python -c "from candlescope_backtest_sdk import Observation, TargetPosition, Signal, OrderIntent; print('sdk-ok')"
Set-Location ../..
python backend/scripts/python_template_bar_probe.py --template sma_cross --work-dir "$Offline"
```

验证结束后关闭该终端即可。

研究页上传 Python 策略包的接口（`/api/v1/backtests/strategy-bundles` 和
`/api/v1/backtests/strategy-revisions/python`）仍由 `BACKTEST_PYTHON_STRATEGY_ENABLED` 控制，
默认关闭。图表策略测试器不需要这个开关。
