# 高可用多机并行架构

AIBOX Compute Fabric 将单机 AIBox 扩展为“协调器 + Worker 节点”的计算集群。目标：

- 翻译 / OCR / ASR 等工作负载可跨机器调度；
- 节点故障自动摘除，任务重试到其他节点；
- 无状态协调器可横向扩展；
- 为数据并行、模型分片和 GPU 池预留统一入口。

## 总体结构

```text
                    ┌────────────────────────────┐
                    │  Load Balancer / API GW     │
                    └─────────────┬──────────────┘
                                  │
             ┌────────────────────┼────────────────────┐
             │                    │                    │
      ┌──────▼──────┐      ┌──────▼──────┐      ┌──────▼──────┐
      │ AIBox API   │      │ AIBox API   │      │ AIBox API   │
      │ coordinator │      │ coordinator │      │ coordinator │
      └──────┬──────┘      └──────┬──────┘      └──────┬──────┘
             └────────────────────┼────────────────────┘
                                  │ shared DB / object store
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
 ┌──────▼──────┐           ┌──────▼──────┐           ┌──────▼──────┐
 │ Worker GPU  │           │ Worker GPU  │           │ Worker CPU  │
 │ ASR/TTS/LLM │           │ OCR/MT      │           │ OCR/MT      │
 └─────────────┘           └─────────────┘           └─────────────┘
```

### 控制面

- AIBox API 接收客户端请求、持久化任务、选择节点；
- `ClusterManager` 维护节点租约、能力和负载；
- 生产环境建议多个 API 副本置于负载均衡后，共享 PostgreSQL / Redis / S3；
- 调度器可用数据库租约选主，保证同一时刻只有一个写入调度器。

### 数据面

- 每台机器运行一个 `aibox_worker`；
- Worker 注册 `url`、`capabilities`、`labels`、`max_concurrency`；
- 每 5 秒发送心跳，超过 TTL 未心跳标记 offline；
- Worker 暴露 `/internal/execute`，执行翻译、OCR 等任务；
- 任务结果返回协调器，协调器持久化。

## 调度

候选节点过滤：

1. 状态为 `online`；
2. `capabilities` 包含任务类型；
3. 当前活跃任务数小于 `max_concurrency`。

排序：

```text
(active_tasks, last_heartbeat)
```

即最少负载优先，其次最早心跳/最久未使用。失败后按顺序尝试下一个节点，最多
`cluster_max_retries + 1` 次。

调度器不会把任务发给 `draining` 节点。

## 高可用

### 节点故障

- 心跳租约过期 -> `offline`，不再参与调度；
- 执行失败 -> 任务记录失败，换节点重试；
- 最终失败 -> 任务 `failed`，错误保留。

### 协调器故障

原型使用 SQLite，适合单机协调器验证。生产建议：

- API 无状态，多副本；
- PostgreSQL 存节点、任务、模型元数据；
- Redis 存短期租约和限流；
- S3 / NFS 存工件；
- 数据库 advisory lock 实现调度器 leader；
- 客户端使用 `Idempotency-Key`，重试不会重复产生任务。

### Worker 故障

- Worker 无状态，模型缓存可重建；
- 使用 `--max-concurrency` 限制并发，避免 OOM；
- 运维排空：`POST /api/cluster/nodes/{id}/drain`。

## 高性能

- 按能力与负载路由，避免把所有请求打到单机；
- Worker 本机并发槽位，保护 GPU / CPU；
- 协调器复用 HTTP 连接（生产建议连接池）；
- 大模型/ASR 预热与模型缓存留在 Worker；
- 数据并行：同一请求可拆分为多个翻译/OCR 分片；
- 张量/流水并行：单机 llama.cpp 已支持多 GPU 切分，跨机 NCCL/Ray 为后续扩展；
- 流式结果优先走 SSE / WebSocket，避免轮询。

## 原型 API

```http
GET  /api/cluster/status
GET  /api/cluster/nodes
POST /api/cluster/nodes
POST /api/cluster/nodes/{id}/heartbeat
POST /api/cluster/nodes/{id}/drain
POST /api/cluster/tasks
GET  /api/cluster/tasks
GET  /api/cluster/tasks/{id}
```

### 注册 Worker

```bash
export AIBOX_CLUSTER_TOKEN="..."
python -m aibox_api.worker \
  --id worker-1 \
  --url http://worker-1:9101 \
  --coordinator http://aibox:8765 \
  --capabilities translation,ocr \
  --max-concurrency 2
```

### 提交任务

```bash
curl -X POST http://aibox:8765/api/cluster/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "translation",
    "payload": {
      "text": "Hello",
      "source": "en",
      "target": "zh",
      "provider": "demo"
    }
  }'
```

### OCR 任务

```json
{
  "kind": "ocr",
  "payload": {
    "image_b64": "...",
    "filename": "scan.png",
    "provider": "glm",
    "language": "zh"
  }
}
```

## 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AIBOX_CLUSTER_ENABLED` | `0` | 启用协调器调度 |
| `AIBOX_CLUSTER_TOKEN` | 空 | Worker/协调器共享 Token |
| `AIBOX_CLUSTER_NODE_TTL` | `20` | 心跳租约秒数 |
| `AIBOX_CLUSTER_MAX_RETRIES` | `2` | 失败后额外重试次数 |

## 已验证实践

本机启动了：

- 1 个协调器（`AIBOX_CLUSTER_ENABLED=1`）；
- 2 个 Worker（`worker-1`、`worker-2`，各 1 并发，翻译 + OCR）；
- 2 个并发翻译任务（各延迟 2 秒）分别落在两个 Worker；
- OCR 任务可落到 Worker 并返回结果。

这验证了注册、心跳、能力过滤、最低负载选择、并发槽位、失败重试与任务持久化。
真正的跨物理机部署只需把 Worker 的 `--url` 换成各机器可达地址，并共享协调器
数据库与对象存储。

## 限制

- 原型协调器状态在 SQLite，不是多协调器强一致；生产需 PostgreSQL/Redis。
- 跨机大模型张量并行尚未实现；当前多 GPU 切分是单机 llama.cpp。
- Worker 只执行 translation/OCR/echo；ASR/TTS/图像/视频 worker 执行器可按同一
  协议扩展。
- 没有 mTLS；生产应使用私有网络、Token/mTLS 和出口控制。
