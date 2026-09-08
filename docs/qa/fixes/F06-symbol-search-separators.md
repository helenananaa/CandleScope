# F06 交易对搜索常见分隔符

修复：在原字符串匹配之外，查询和候选代码同时忽略空白、斜杠、下划线、连字符并统一大小写。只用于匹配，不修改品种代码、身份或筛选条件。纯分隔符不使用空字符串归一化匹配。

验证：

- 搜索相关测试 8 项通过，新增覆盖 BTC/USDT、btcusdt、BTC-USDT、BTC_USDT、带空白写法对 Binance BTCUSDT 和 OKX BTC-USDT-SWAP 的匹配；同时验证错误计价币、其他品种和纯斜杠查询不会误匹配。
- 相关文件 ESLint、Production build、git diff --check 通过。
- 电脑操控发行版中输入 BTC/USDT，在 OKX 合约、USDT 筛选下正确显示一条 BTC-USDT-SWAP。证据 output/user-audit-20260907/evidence/fix-F06-okx-result.png/.txt。
- 切换 Binance 进行额外 UI 复测时 Mac 锁屏，工具提示自动解锁失败，因此该 UI 场景未完成；Binance 代码形态由上述回归测试覆盖。未将锁屏计为软件缺陷。

日志：output/user-audit-20260907/fix-F06-tests.log、fix-F06-build.log。
