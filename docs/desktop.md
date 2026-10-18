# 桌面壳（Windows / macOS）

## 范围

- Windows 10/11：Tauri 2 + WebView2。
- macOS 12+：Tauri 2 + WKWebView。
- Linux：**不构建桌面壳**，只提供 WebUI / Docker，符合当前产品范围。

桌面壳不复制业务逻辑，只做三件事：

1. 用 WebView 承载同一套 Fluent WebUI；
2. 确保本地 API 正在运行；
3. 退出时清理自己启动的 API 进程。

## 目录

```text
apps/desktop/
  package.json
  src-tauri/
    Cargo.toml
    build.rs
    tauri.conf.json
    rust-toolchain.toml
    capabilities/default.json
    icons/
    src/main.rs
    src/lib.rs
```

## 前置

- Node.js 20+ / pnpm 10+
- Python 3.10+ 与仓库 `.venv`
- Rust：由 `rust-toolchain.toml` 固定到 1.90.0；`rustup` 会自动安装
- Windows：WebView2 Runtime（Windows 11 自带）
- macOS：Xcode Command Line Tools

## 开发

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev-desktop.ps1
```

流程：

- Tauri CLI 执行 `beforeDevCommand`，启动 Vite（5173）；
- Rust 启动时检查 `127.0.0.1:8765`；
- 未运行时，从仓库根目录拉起 `.venv` 的 `python -m aibox_api`；
- 窗口加载 `http://127.0.0.1:5173`；
- 关闭窗口时终止后端。

也可以分三步手动运行：

```powershell
.\.venv\Scripts\python.exe -m aibox_api --host 127.0.0.1 --port 8765
pnpm dev:web
pnpm --filter @aibox/desktop dev
```

Tauri 会检测到端口已监听，不再重复启动后端。

## 发布构建

发布态不依赖用户安装 Python / Node，需要把 API 打成 sidecar：

```powershell
# 1. 构建 API 单文件可执行程序并放入 src-tauri/binaries
powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1

# 2. 构建 Fluent WebUI（VITE_API_BASE=http://127.0.0.1:8765）
pnpm --filter @aibox/web build:desktop

# 3. 打包 Tauri 安装包
pnpm --filter @aibox/desktop build
```

产物：

- Windows：`apps/desktop/src-tauri/target/release/bundle/msi/*.msi`、`nsis/*.exe`
- macOS：`.app` / `.dmg`

### Sidecar 约定

Tauri `bundle.externalBin` 声明：

```json
"externalBin": ["binaries/aibox-server"]
```

实际文件名必须包含目标三元组：

```text
binaries/aibox-server-x86_64-pc-windows-msvc.exe
binaries/aibox-server-aarch64-apple-darwin
binaries/aibox-server-x86_64-apple-darwin
```

`scripts/build-sidecar.ps1` 会读取 `rustc -vV` 的 host triple 自动命名。PyInstaller 会收集：
CTranslate2、faster-whisper、tokenizers、onnxruntime、av、uvicorn、gRPC 子模块。

sidecar 启动后会同时提供本地 HTTP/WS 与 gRPC/MRCP 接入（默认均为 `127.0.0.1`）。如果桌面端只需要 WebUI，可通过 `AIBOX_GRPC_PORT=0`、`AIBOX_MRCP_PORT=0` 关闭外部端口，避免额外的监听与防火墙提示。

> sidecar 体积通常在数百 MB 量级。发布前请检查安装包大小与杀毒软件误报。

## 配置

| 变量 | 作用 |
| --- | --- |
| `AIBOX_PYTHON` | 开发态指定 Python 可执行文件 |
| `VITE_API_BASE` | 桌面构建时前端 API 地址，`.env.desktop` 已设 |
| `AIBOX_DATA_DIR` | 桌面数据目录 |

桌面 release 使用 `http://127.0.0.1:8765`，API CORS 默认允许：

- `tauri://localhost`
- `http://tauri.localhost`
- `https://tauri.localhost`

如果自定义 API 端口，需要同步修改 `apps/web/.env.desktop`、Rust `PORT` 和 CORS。

## 安全

- 窗口加载本地构建资源，不加载远程站点；
- `csp: null` 是当前开发配置；正式发布前建议配置严格 CSP；
- API 仅监听本机回环地址；
- sidecar 只随安装包分发，不接受外部命令注入；
- 关闭窗口会结束 AIBox 自己启动的后端。

## 已知限制

- 本仓库不附带预编译安装包；
- Linux 不构建桌面壳；
- 桌面壳与 API 之间没有额外鉴权，依赖回环地址隔离；
- macOS 需要在 macOS 上构建并签名 / 公证；
- Tauri 的 WebView 版本差异可能影响字体与滚动条表现，发布前需在目标系统回归。
