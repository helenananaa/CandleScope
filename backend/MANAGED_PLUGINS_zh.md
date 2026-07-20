# 受管插件安装层

CandleScope 现在只有一条 fail-closed 的可下载插件准备链路。它与 runtime API、交易所
plugin API 分离，只负责把仓库内明确声明、锁定的产物安全地放进选定后端环境。

## 分层

- `CANDLESCOPE_PLUGINS.json` 是宿主注册表；setup 默认处理 `autoInstall: true` 的项，
  CLI 也能按 id 选择或排除。
- 每份 `CANDLESCOPE_PLUGIN.json` 是不可变安装锁，声明插件身份、安装驱动、Python
  distribution/module/version、源码与 Release 身份、manifest 摘要和验证探针。
- `scripts/managed_plugin_installer.py` 统一完成注册表/锁校验、限长 HTTPS 下载、
  SHA-256 校验、原子缓存、平台选择、安装、stamp、独立进程复验，以及升级失败后的
  已校验缓存回滚。
- `scripts/managed_plugin_probes.py` 只放宿主语义检查。普通 Python 插件使用通用
  `python-import`；Pine 的公开 v0.2 锁使用 `pine-runtime-v1` 做 schema/SMA smoke，
  realtime 发布锁则使用 `pine-runtime-v2` 校验渲染元数据和真实持久会话生命周期。

当前只有 `python-wheel` 驱动，并固定使用
`pip --no-index --no-deps --force-reinstall` 安装一个已校验 wheel。依赖必须进入后端
锁定 requirements，或作为独立受管产物声明。未知驱动、平台、ABI、探针或 schema
都会终止 setup；不会回退源码编译，也不会临时访问 PyPI 安装未锁定包。

## 常用命令

```powershell
# 只列声明，不导入、不安装
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py --list

# 只读检查全部自动安装项
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py --check

# 离线确保一个已注册插件
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py `
  --plugin pine-compat --offline
```

`CANDLESCOPE_PLUGIN_CACHE_DIR` 可覆盖用户缓存；迁移期继续兼容旧的
`CANDLESCOPE_RUNTIME_CACHE_DIR` 和已有 `runtime-cache` 目录。新 stamp 位于
`<venv>/.candlescope/plugins/<plugin-id>.json`。Pine 的旧
`pine-runtime-install.json` 仍可读取，正常 setup 会原地生成新 stamp 而不重装；
`--check` 始终只读。

替换已安装插件前，只有 canonical/legacy stamp 的插件、package、module 身份一致，且
旧缓存 wheel 仍与 stamp 中的 SHA-256 匹配，安装器才会记录回滚源。新 wheel 安装或
探针失败时，会重装这一个确定的旧 wheel，在独立进程复验版本/导入，并恢复 canonical
stamp。首次安装、缓存缺失或被改动、stamp 非法、恢复失败都不存在可信回滚路径，因而
直接 fail closed。

## 新增 verified wheel 插件

一份只做通用导入检查的最小锁如下；占位身份与摘要必须全部替换为已发布 Release
的真实值：

```json
{
  "schemaVersion": 1,
  "pluginId": "example-plugin",
  "displayName": "Example plugin",
  "installer": {
    "kind": "python-wheel",
    "package": "example-plugin",
    "pythonModule": "example_plugin",
    "version": "1.2.3",
    "pythonRequires": ">=3.10",
    "pythonTag": "cp310",
    "abiTag": "abi3"
  },
  "source": {"url": "https://github.com/org/repo", "commit": "<40 hex>"},
  "release": {
    "tag": "v1.2.3",
    "commit": "<40 hex>",
    "manifestUrl": "https://host/release/v1.2.3/manifest.json",
    "manifestSha256": "<64 hex>",
    "assetBaseUrl": "https://host/release/v1.2.3"
  },
  "verification": {"probe": "python-import"},
  "legacyStampFiles": []
}
```

注册项只保留宿主选择策略：

```json
{"id": "example-plugin", "lockFile": "../packages/example/CANDLESCOPE_PLUGIN.json", "autoInstall": true}
```

1. 发布稳定 Release，包含 `manifest.json` 和平台 wheel；manifest 必须锁定
   distribution、module、version、tag、commit、Python 下限、wheel tags、字节数和
   SHA-256。
2. 增加 `CANDLESCOPE_PLUGIN.json`，选择 `python-wheel`，锁定 manifest 摘要与
   Release 身份。没有额外宿主语义时使用 `python-import` 探针。
3. 在 `backend/CANDLESCOPE_PLUGINS.json` 增加 id、相对锁路径和明确的
   `autoInstall` 策略。
4. 如需更强验证，只在 `managed_plugin_probes.py` 增加命名探针和配置校验；探针里
   不放下载或安装逻辑。
5. 覆盖锁/manifest 身份、目标选择、离线缓存、stamp 和探针测试，再验证 `--list`、
   `--check`、一次临时 venv 冷安装和一次重复安装。

以后若支持非 wheel 产物，应在同一注册表、缓存、摘要、stamp、探针生命周期后增加
新的安装驱动，不应伪装成 wheel，也不应把临时解压/安装代码重新塞回 setup 脚本。
