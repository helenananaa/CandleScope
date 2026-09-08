# F36：发行包每次启动重复解析 Python 依赖

日期：2026-09-08。

独立包首次启动时，Python 子进程连续约 7 秒接近占用一个核心，健康检查约 11.24 秒就绪。运行时不应往安装目录写缓存，因此需要在构建阶段生成可携带的缓存，而不是每次启动重复解析。

增加 electron-builder afterPack：在包内解释器下为后端、SDK、依赖和标准库生成基于内容哈希的 pyc，复制或移动安装包后仍然有效。保留源码与运行时不写字节码的设置。

ccxt 4.5.60 自带的 `static_dependencies/bip/conf` 中有 7 个包含 `from  import` 的无效配置文件，整体 compileall 会失败。构建仅跳过该配置目录的预编译，保留原始文件；正常导入 ccxt 和本软件使用的行情路径通过。未修改供应商文件，也未宣称这些未使用配置可运行。

## 验证

- Mac arm64 原生包完整打包通过，源码保留，后端 main 的哈希字节码已生成。
- 同一成品、同一解释器，串行交替执行 `import uvicorn; import app.main` 各 3 次。禁用缓存发现时 5.510 / 5.502 / 5.509 秒；使用成品字节码时 1.662 / 1.746 / 1.682 秒。中位数从 5.509 降至 1.682 秒，减少约 69.5%。
- 上述仅衡量 Python 导入，不代表端到端图表加载提升 69.5%。两组均禁止写新字节码；禁用缓存组使用不存在的 PYTHONPYCACHEPREFIX，使同一成品源码不读取预编译结果。
- 原生界面再次显示 1501 根历史与实时盘口，Cmd+Q 后日志出现 `Application shutdown complete` 和 `Finished server process`。
- 证据：`output/user-audit-20260908/native-runtime-compiled-package.log`、`native-import-comparison.{json,log}`、`compare_native_imports.py`、`native-compiled-ready.txt/png`。

初次预编译包的进程采样与导入对照同时运行，不能作为严格性能对照；另做串行启动采样保存为 `native-standalone-compiled-serial-profile.json`。原始文件保留，不混用不受控数字。
