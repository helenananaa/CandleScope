# F26：原生后端数据写入用户目录

日期：2026-09-08。

## 问题与影响

原生壳只设置后端 cwd，没有传入 CANDLE_DATA_DIR。实际 Mac 包启动后，数据库、回放存档、缓存和商品目录写在 CandleScope.app/Contents/Resources/backend/data（实测 7.2 MB）。安装包替换会丢失这些内容，安装目录只读时启动也可能失败。

## 修复与验证

壳为后端设置 CANDLE_DATA_DIR，默认 app.getPath("userData")/data；保留调用者明确提供的 CANDLE_DATA_DIR，以及既有其他数据库环境变量覆盖。

39 项桌面测试通过，重新打包 Mac arm64；使用已安装依赖的 Python 启动原生应用，行情、订单簿和 1501 根历史正常加载。文件系统确认用户目录生成数据文件，安装包内部不再生成 data。证据 output/user-audit-20260908/native-data-{tests,package,launch}.log、native-data-running.txt/png、native-data-paths.json。

修复前此次测试生成的数据已复制保留至 output/user-audit-20260908/native-before-data-fix/data。此修复不自动合并旧安装目录中的历史数据库；已有部署应备份旧目录，再显式指定 CANDLE_DATA_DIR 或迁移至新的用户目录，不能用覆盖拷贝合并正在使用的数据库。测试没有修改用户原来的 backend/data。
