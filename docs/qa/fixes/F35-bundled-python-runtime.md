# F35：原生发行包依赖项目外部 Python

日期：2026-09-08。

原包默认运行 PATH 中的 python，本机系统 Python 缺少 uvicorn，无法开箱启动。F25 只补齐错误提示，没有解决依赖缺失。

新增 `npm run desktop:package:dir` 跨平台 Node 构建入口：使用构建机的 uv 下载托管 Python 3.12，将后端依赖及两个 SDK 以非 editable 方式安装到独立目录，完成导入检查后由 electron-builder 放入 `Resources/python-runtime`。开发者仍可显式指定 CANDLESCOPE_PYTHON；发行包默认使用包内解释器，缺少运行时明确报错，不再碰运气调用系统 Python。打包前检查运行时平台与架构，防止误装另一平台依赖。

用户数据继续保存在用户目录，运行时不写安装包字节码，也不依赖用户 site-packages。构建需要 uv、Node、网络或已有下载缓存；运行成品不需要 uv 或项目虚拟环境。Python 来源为 [uv 管理的 python-build-standalone](https://docs.astral.sh/uv/guides/install-python/)。本次实际版本为 Python 3.12.14；运行时包含版本清单和平台 manifest。

## 验证

- 43 项桌面测试通过，含解释器选择、显式覆盖、缺失运行时错误和 Windows 路径单测。
- 标准打包命令在 Mac arm64 完成；用 PATH=/usr/bin:/bin、无 Python 覆盖、全新用户目录实际启动 `.app`，显示 1501 根 K 线和实时盘口。进程路径确认是包内 python3。
- 使用包内 Python 执行 6 类指标首值预览回归：36 passed。
- 证据：`output/user-audit-20260908/native-runtime-{prepare,package,tests,indicator-tests}.log`、`native-standalone-clean-{start,profile}.json`、`native-standalone-clean-ready.txt/png`。

首次 60 秒采样的健康检查就绪约 11.24 秒；聚合 RSS 最大约 1498 MiB（包含多个进程、会重复计入共享页，不等同实际物理内存），说明仍有启动性能优化空间。此提交只解决依赖与打包入口。

Mac 包未签名、公证，仍使用默认应用图标；Windows 仅验证路径计算，未在 Windows 构建和运行。不能将本机结果扩展为所有平台正式发布认证。
