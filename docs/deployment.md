# 服务器与容器部署

## 适用范围

Linux 是 AIBox 的服务器 / WebUI 运行面。按产品范围，Linux 不构建本地桌面壳，只提供 Fluent WebUI（浏览器或 PWA）与 HTTP API。

## 直接运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "services/api[asr]"
pnpm install --store-dir .pnpm-store
pnpm build:web
.venv/bin/python -m aibox_api --host 0.0.0.0 --port 8765
```

生产环境建议用 systemd / supervisor 托管，前置 Nginx 或 Caddy。

```ini
# /etc/systemd/system/aibox.service
[Unit]
Description=AIBox local AI studio
After=network.target

[Service]
User=aibox
WorkingDirectory=/opt/aibox
Environment=AIBOX_HOST=127.0.0.1
Environment=AIBOX_PORT=8765
Environment=AIBOX_DATA_DIR=/var/lib/aibox
ExecStart=/opt/aibox/.venv/bin/python -m aibox_api
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aibox
```

## Docker

CPU：

```bash
docker compose up -d --build
```

GPU：

```bash
docker compose -f docker-compose.gpu.yml up -d --build
```

Compose 暴露：

| 端口 | 协议 | 用途 |
| --- | --- | --- |
| `8765` | TCP | WebUI、OpenAI HTTP、WebSocket |
| `50051` | TCP | gRPC |
| `8060` | UDP | MRCP SIP |
| `8061` | TCP | MRCPv2 控制通道（共享） |
| `50000-50100` | UDP | MRCP RTP 端口池 |

MRCP 的 SDP 必须广告客户端可达地址；在 `.env` 或 shell 中设置：

```bash
AIBOX_MRCP_ADVERTISE_HOST=192.0.2.10 docker compose up -d
```

如果不想暴露 MRCP/gRPC，删除对应端口映射，或设置：

```bash
AIBOX_GRPC_PORT=0 AIBOX_MRCP_PORT=0
```

### TTS / IndexTTS

默认镜像包含 ASR 与 TTS API 代码，但不包含 IndexTTS 的 PyTorch 运行时与 5 GB+ 权重。可以：

- 设置 `AIBOX_DEMO_TTS=1` 验证 OpenAI TTS / UI 链路；
- 或在镜像内额外安装 IndexTTS 运行时，并设置 `AIBOX_INDEXTTS_HOME` / `AIBOX_INDEXTTS_PYTHON`；
- 或把外部 IndexTTS 运行时挂载进容器。TTS worker 会在需要时启动独立 Python 进程，模型权重应在 `/data/models/tts` 中。

TTS 与 ASR 共用弹性预算；GPU 容器建议给 IndexTTS 预留 10 GB 以上显存。

### 图像生成 / ComfyUI

默认镜像不包含 PyTorch / diffusers。可以：

- `AIBOX_DEMO_IMAGE=1` 验证图像 UI、任务队列和 OpenAI Images；
- 把 ComfyUI 运行在宿主机并设置 `AIBOX_COMFYUI_URL=http://host.docker.internal:8188`；
- 或构建自定义镜像安装 diffusers + torch，并设置 `AIBOX_IMAGE_PYTHON`。

ComfyUI 默认无鉴权，不要直接暴露到公网。图像模型权重体积较大，建议挂载独立数据卷。

### 人声分离

默认镜像不包含 Demucs / audio-separator。可安装到独立 Python 环境并设置：

```bash
AIBOX_SEPARATION_PYTHON=/opt/separation-venv/bin/python
AIBOX_SEPARATION_DEVICE=cuda
```

或使用 `AIBOX_DEMO_SEPARATION=1` 做 UI/CI 验证。分轨写入 `/data/separations`。

### 视频生成

MiniMax H3 / Hailuo 使用云端 API：

```bash
MINIMAX_API_KEY=...
AIBOX_MINIMAX_BASE_URL=https://api.minimax.io/v1
```

ComfyUI 视频使用 `AIBOX_COMFYUI_URL`；`AIBOX_DEMO_VIDEO=1` 可生成测试 MP4。视频写入 `/data/videos`。

### 语言模型

本地 GGUF 需要镜像或挂载 `llama-server`：

```bash
AIBOX_LLAMA_SERVER=/opt/llama.cpp/build/bin/llama-server
AIBOX_LLM_CONTEXT=8192
AIBOX_LLM_GPU_LAYERS=99
```

或连接外部 OpenAI 兼容服务：

```bash
AIBOX_LLM_BASE_URL=http://host.docker.internal:11434/v1
AIBOX_LLM_MODEL=qwen2.5:7b
```

`AIBOX_DEMO_LLM=1` 可用于 UI 验证。

前置条件：

- Docker 24+ 与 Compose v2；
- GPU 服务器安装 NVIDIA 驱动与 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)；
- `docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi` 能通过。

`docker-compose.gpu.yml` 会把 `INSTALL_CUDA=1` 传给镜像，在镜像内安装 `nvidia-cublas-cu12`、`nvidia-cudnn-cu12` 等用户态库，并由 AIBox 注册到加载路径。

数据卷：

```bash
docker volume inspect aibox_aibox-data
docker compose exec aibox ls -lah /data
```

备份：

```bash
docker run --rm -v aibox_aibox-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/aibox-data.tar.gz -C /data .
```

## 反向代理

默认没有内置鉴权。公网部署必须至少加 TLS 与访问控制。

### Nginx + Basic Auth

```nginx
server {
    listen 443 ssl http2;
    server_name aibox.example.com;

    ssl_certificate     /etc/letsencrypt/live/aibox.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/aibox.example.com/privkey.pem;

    client_max_body_size 512m;

    location / {
        auth_basic "AIBox";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

`Upgrade` / `Connection` 头用于 WebSocket。Basic Auth 会要求 OpenAI SDK / WebSocket 客户端也带上代理层凭据；如果业务客户端不方便使用 Basic Auth，可以仅对 `/api/` 加 Basic Auth，对 `/v1/`、`/ws/` 使用 `AIBOX_API_TOKEN`：

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd aibox
```

```nginx
location /api/ {
    auth_basic "AIBox UI";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8765;
    # ... proxy headers
}

location /v1/ {
    proxy_pass http://127.0.0.1:8765;
    # ... proxy headers, no Basic Auth; AIBOX_API_TOKEN still applies
}

location /ws/ {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### gRPC

gRPC 使用 HTTP/2，不要把 gRPC 端口直接交给普通 HTTP `location`。可以：

- 直接暴露 `50051` 给可信内网；
- 或在 Nginx `stream` 模块中转发 TCP：

```nginx
stream {
    upstream aibox_grpc {
        server 127.0.0.1:50051;
    }
    server {
        listen 50051;
        proxy_pass aibox_grpc;
    }
}
```

### MRCP

MRCP 依赖 SIP/UDP + RTP/UDP，不能通过普通 HTTP 反向代理。建议：

- 内网直接暴露 `8060/udp`、`8061/tcp`、`50000-50100/udp`；
- 公网经 SBC（如 Kamailio / OpenSIPS / 厂商 SBC）转发；
- 设置 `AIBOX_MRCP_ADVERTISE_HOST` 为 SBC 可达的媒体地址；
- 使用防火墙限制来源 IP。

### Caddy

```caddy
aibox.example.com {
    basicauth {
        aibox $2a$14$REPLACE_WITH_HASH
    }
    request_body {
        max_size 512MB
    }
    reverse_proxy 127.0.0.1:8765
}
```

> Basic Auth 只解决“谁能访问”。需要多用户、配额、审计时，应在独立网关或后续 API Token 功能中实现。

## 外部服务配置

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `AIBOX_API_TOKEN` | `change-me` | OpenAI / WS / gRPC Bearer Token |
| `AIBOX_PUBLIC_BASE_URL` | `https://aibox.example.com` | 反向代理后的公开地址 |
| `AIBOX_GRPC_HOST` | `127.0.0.1` | 不暴露公网时保持回环 |
| `AIBOX_GRPC_PORT` | `50051` | `0` 禁用 |
| `AIBOX_MRCP_HOST` | `0.0.0.0` | SIP/控制/RTP 绑定 |
| `AIBOX_MRCP_PORT` | `8060` | `0` 禁用 |
| `AIBOX_MRCP_CONTROL_PORT` | `8061` | 共享控制端口 |
| `AIBOX_MRCP_RTP_PORT_START/END` | `50000/50100` | RTP 端口池 |
| `AIBOX_MRCP_ADVERTISE_HOST` | `192.0.2.10` | SDP 广告地址，必须是客户端可达 IP |

systemd 中不要把 Token 写进 unit 文件；使用 `EnvironmentFile=/etc/aibox.env` 并限制文件权限。

## 数据目录

| 路径 | 内容 |
| --- | --- |
| `models/whisper/<id>/` | Whisper CTranslate2 权重与 manifest |
| `uploads/` | 上传音频 |
| `state/aibox.db` | SQLite（WAL）转写历史 |
| `state/settings.json` | 默认参数 |
| `logs/` | 预留日志目录 |

迁移时复制整个数据目录即可。模型可单独备份，manifest 会描述来源与文件大小。

## 并发与资源

- 默认最多 1 个转写任务，避免 CPU / 显存争用；设置中的并发数在重启后生效。
- 每个任务会加载 / 复用 1 个 Whisper 模型；切换模型会卸载旧模型。
- 大文件上传上限 512 MB（`AIBOX_MAX_UPLOAD_MB`）。
- 反向代理需同步放宽请求体与超时限制（见上）。
- 磁盘：预留至少 4 GB 给 Large v3；同时保留上传音频与字幕。
- GPU：首次 CUDA 推理会初始化 cuBLAS / cuDNN，耗时数秒。

## 健康检查

```bash
curl http://127.0.0.1:8765/api/health
```

Docker 镜像已内置 `HEALTHCHECK`。

## 升级

```bash
docker compose pull
docker compose up -d --build
```

SQLite 表结构在启动时自动迁移新增列（`engine / device / compute_type / warning`），历史数据保留。

## 安全清单

- [ ] 不把 8765 直接暴露公网
- [ ] 启用 TLS
- [ ] 反向代理鉴权 / SSO
- [ ] 外部接口设置 `AIBOX_API_TOKEN`
- [ ] MRCP 仅在内网 / SBC 后暴露
- [ ] 限制上传大小
- [ ] 数据目录最小权限（容器内 UID 10001）
- [ ] 定期备份 `/data`
- [ ] 只从官方 / 可信镜像构建
- [ ] 审核模型许可证
- [ ] 不把 `HF_TOKEN` 写入镜像
