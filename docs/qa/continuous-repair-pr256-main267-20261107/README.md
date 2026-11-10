# 常驻策略修复层 #256

测试源 `d43345da4e032ec876b65f23e8cc6d59f580eb1e`，实际 main `b442555d582dc0bb473bad92ac5e699efdaa78d5`。覆盖Manager 修复 worker、取消与完整进程退出后的修复恢复及新基线数据回归。

后端 21 套件单次 317 项通过，零跳过。架构检查通过。上层签名应用与 Windows 的资格单独记录。

[精确命令和证据指纹](receipt.json)
