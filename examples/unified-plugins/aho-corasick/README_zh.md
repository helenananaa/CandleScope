# Aho-Corasick 统一格式候选

`candlescope.aho-corasick@0.2.1` 使用 `candlescope.unified-plugin/1` 清单和 `candlescope.unified-entry/1` JSONL 协议，提供一个 `restricted` 原生 sidecar，权限集合为空。命令面板中选择 **Run aho-corasick Search**，可直接运行清单样例，也可编辑 JSON 搜索参数。Host 核对包版本、摘要、激活代次和进程实例，通过 `invoke` 传入搜索参数。命令面板显示 `candlescope.aho-corasick.matches/1` 结果及 UTF-8 字节偏移。搜索直接复用 0.1.0 的 Rust 实现，依赖版本和校验和沿用旧锁文件。旧包、构建回执、对照回执和用户安装数据继续保留。 [旧参考包](../../plugins/aho-corasick-adapter/)

## 本地构建和验证

在仓库根目录用安装了后端依赖的 Python 环境执行。macOS arm64 验证使用 Rust 1.97.1。首次构建时用 `cargo fetch --locked --manifest-path examples/unified-plugins/aho-corasick/Cargo.toml` 预取精确锁定的依赖，构建本身使用离线模式。

```sh
candidate=examples/unified-plugins/aho-corasick
legacy=examples/plugins/aho-corasick-adapter
work=$(mktemp -d)
python "$candidate/build_candidate.py" "$work/aho-corasick.cspkg"
cargo test --locked --offline --manifest-path "$candidate/Cargo.toml" --target-dir "$work/tests"
cargo build --release --locked --offline --manifest-path "$legacy/Cargo.toml" --target-dir "$work/reference"
PYTHONPATH=backend:packages/candlescope-plugin-sdk/src \
  python "$candidate/verify_candidate.py" "$work/aho-corasick.cspkg" \
  "$work/reference/release/candlescope-aho-corasick-adapter"
```

探针复算旧协议的 12 条参考响应及整段回执的摘要，从暂存的 `.cspkg` 校验 SBOM 和许可文件，再用 Host 的统一 sidecar 执行器调用包内二进制。覆盖同一搜索输入的完整输出、最左最长匹配、1 万条匹配上限、未激活或过期代次、错误协议、重复激活和进程退出。探针只对本地构建的可信产物运行，并使用临时包存储和私有目录。

在同一 macOS arm64 环境的两个独立构建目录得到逐字节相同的 587,981 字节候选，SHA-256 为 `a2a33d7e248bf1fef3de2e5e15fd3b454b7c48e7a752555aa638c9ee94cd8e12`。

本地浏览器用共享命令面板和实际管理 API 验证了发现、执行、无效参数后重试、1 万条结果显示、停用及重新启用。验证使用临时存储及显式批准的 full-trust 测试包，其原生二进制与受限候选字节相同。

macOS 的产品运行时拒绝启动缺少合格隔离环境的受限原生 sidecar。市场重发仍需 Windows AppContainer、旧安装回滚验收和原发布者签名。

Windows runner 使用同一个探针并加 `--require-appcontainer`。这个模式还会在临时存储中通过统一生命周期批准受限候选，核对真实 AppContainer 的进程限制，调用同一参考搜索，并检查停用后的命令撤销、进程退出和启动文件清理。
