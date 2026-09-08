# F25：原生应用启动失败时向用户显示原因与日志位置

日期：2026-09-08。来源：剩余原生发行验证。

Mac arm64 production 应用打包成功，但默认 Python 环境没有 uvicorn。原程序只在日志记录 SidecarStartupError 并退出，用户看不到任何提示。默认启动失败证据：output/user-audit-20260908/native-launch-default.log、native-user-data/logs/backend-sidecar.log、desktop-startup-error.log。

修复：启动异常显示系统原生错误对话框，区分后端启动失败与其他初始化失败，提供排查方向和本地日志位置；写日志失败也不阻止显示提示。依据系统语言显示中文或英文。

验证：39 项桌面测试通过；先前 production dist 未变，重新打包 Mac arm64 成功；实际启动原生应用，Computer Use 读取到后端依赖提示及日志目录并关闭对话框。证据 startup-error-tests.log、startup-error-package.log、startup-error-dialog.txt/png。

边界：此项修复无提示退出，不把缺失 Python 依赖本身视为已经解决；继续使用已安装后端依赖的环境验证原生功能，运行环境打包另行核查。没有验证 Windows 或中文系统的实际弹窗渲染。
