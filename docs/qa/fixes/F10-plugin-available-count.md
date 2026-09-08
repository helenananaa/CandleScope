# F10 运行时可用数量统计错误

原因：“可用”徽标使用 contributions.length，把不可用条目一起计入。

修复：可用数量使用与每个条目相同的 available 条件；零可用时使用中性徽标。顶部运行时总数保留总条目数。

验证：相关 ESLint、Production build、git diff --check 通过。电脑操控发行版插件中心显示总数 2、“0 个可用”，两个条目均为不可用，零可用徽标为中性色。证据 output/user-audit-20260907/evidence/fix-F10-count.png/.txt，构建日志 output/user-audit-20260907/fix-F10-build.log。
