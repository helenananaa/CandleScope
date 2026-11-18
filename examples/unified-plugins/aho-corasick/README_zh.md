# Aho-Corasick 统一格式候选

`candlescope.aho-corasick@0.2.0` 使用 `candlescope.unified-plugin/1` 清单和 `candlescope.unified-entry/1` JSONL 协议，提供一个 `restricted` 原生 sidecar，权限集合为空。Host 激活时核对包版本、摘要、代次和进程实例的回执，随后通过 `invoke` 传入搜索参数。输出保留 `candlescope.aho-corasick.matches/1` 及 UTF-8 字节偏移。搜索直接复用 0.1.0 的 Rust 实现，依赖版本和校验和沿用旧锁文件。旧包、构建回执、对照回执和用户安装数据继续保留。 [旧参考包](../../plugins/aho-corasick-adapter/)

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

在同一 macOS arm64 环境的两个独立构建目录得到逐字节相同的 587,684 字节候选，SHA-256 为 `831c23806dafb2fecc0785191fb32ccfe80aafd653645a22170806ac32bee0da`。3 项 Rust 测试和 61 项市场、执行器及包存储后端回归通过。

macOS 的产品运行时拒绝启动缺少合格隔离环境的受限原生 sidecar。市场重发仍需统一命令入口、Windows AppContainer 和旧安装回滚验收，以及原发布者签名。
