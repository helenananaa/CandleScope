# #351 市场迁移 macOS 安装版验收

[旧市场包重发清单](INVENTORY_zh.md)基于仓库内的制品和清单。本次验收使用独立的 LIVE
桌面配置和临时 Ed25519 信任根。签名制品先由受保护的制品导入接口校验并缓存，桌面
发起下载时核对缓存命中。该流程覆盖桌面市场界面、内置后端和实际窗口。公网 HTTPS
分发、Windows 旧侧车执行及 AppContainer 隔离需要各自的验收。

## 启动回归

原 #485 提交 `287d1e67c444f7c10a1f0867e97c41bf37eac783` 的安装包能启动窗口，但市场
目录返回 404。LIVE 启动代码读取了 CorePluginPlatform 上不存在的 `enabled` 字段，
把插件平台降级为禁用。修复提交 `58b0fc731999d0ecda44cde46e67041e462be8b3` 根据实际
平台类型接线，并在应用启动回归中验证市场和统一执行器共用生命周期实例。

## 安装版观测

源码为 `58b0fc731999d0ecda44cde46e67041e462be8b3`。在 macOS 26.6.2 arm64 上使用
标准桌面打包，从复制的应用启动。ad hoc 签名通过 `codesign --verify --deep --strict`。
包内后端迁移模块和 Electron 主入口经逐文件比对，内置 Pine 和 Python 签名清单及归档
摘要与此前 [#482 的验收记录](../unified-script-retirement-351-20261118/macos-arm64.json)一致。

| 场景 | 实际观测 |
| --- | --- |
| 首次安装和审批 | 桌面市场通过已验证缓存下载，同一窗口暂存并打开摘要审批。取消时没有激活记录，明确批准后主题显示 `#ece5d2`。 |
| 健康升级 | 更新后当前窗口显示 `#dcefe4`，运行代次增加。 |
| 旧安装接管 | 同一测试发布者的统一包接管已预置的旧 ID。新版主题显示 `#dfe7f8`，旧入口从旧平台目录移除。设置、Host 存储和沙箱文件按发布者复制，原始文件摘要保持一致。 |
| 再打开并手动回滚 | 完全退出再启动后保持接管主题。市场手动回滚恢复旧激活 `0.1.0`，窗口移除新版主题。macOS 上旧侧车仍不可用。 |
| 坏版本自动回滚 | 签名正常的坏包通过分发校验。宿主解析第二个数据入口失败，回到 `1.1.0` 并分配新代次。窗口显示旧版底色 `#dcefe4`。 |
| 两类回滚后的重启 | 同一配置重启后，健康主题保持生效，两侧数据仍存在。三次退出均核对所属进程。 |

[原生回执](macos-arm64.json)记录应用文件摘要、签名制品、窗口颜色、错误及运行代次。
相关后端回归 98 项通过，Windows 专用用例 1 项跳过。

## 重跑

将签名后的 macOS 应用复制到测试目录。用能运行后端测试的 Python 环境生成数据，再用
Playwright Core 启动复制的应用。从仓库根目录执行以下命令。

```sh
qa_root="$(mktemp -d)"
qa_scripts=docs/qa/unified-marketplace-migration-351-20261118
PYTHONPATH=backend UV_OFFLINE=1 python "$qa_scripts/seed_marketplace.py" "$qa_root"
ditto "$CANDLESCOPE_APP" "$qa_root/CandleScope.app"
CANDLESCOPE_QA_PLAYWRIGHT="$PLAYWRIGHT_CORE" node "$qa_scripts/accept_installed.cjs" \
  "$qa_root/CandleScope.app" "$qa_root" "$qa_root/macos-arm64.json"
```

设置 `CANDLESCOPE_APP` 为签名后的应用路径，`PLAYWRIGHT_CORE` 为 Playwright Core 的
模块路径。生成器写入全新的配置、测试信任根和签名包，旧安装和其中的数据均为测试夹具。
签名私钥只用于本次生成。回执记录实际观察及 PID 退出检查。
