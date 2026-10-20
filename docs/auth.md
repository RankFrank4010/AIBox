# 账户、登录与权限

AIBox 内置轻量账户系统，默认不强制登录；设置 `AIBOX_AUTH_ENABLED=1` 后启用。

## 模式

| 模式 | 配置 | 说明 |
| --- | --- | --- |
| 内置登录 | `AIBOX_AUTH_MODE=builtin` | 用户名/密码、scrypt 哈希、会话 Token |
| 外置登录 | `AIBOX_AUTH_MODE=external` | 读取反向代理/身份网关注入的用户和角色头 |

外置模式适合 Authentik、Authelia、OAuth2 Proxy、OIDC 网关等：AIBox 不直接实现
OIDC 回调，而信任上游已完成认证的请求头。

```text
AIBOX_AUTH_MODE=external
AIBOX_AUTH_EXTERNAL_HEADER=X-Forwarded-User
AIBOX_AUTH_EXTERNAL_ROLES_HEADER=X-Forwarded-Roles
```

**必须确保这些头只能由可信反向代理写入，外部客户端不能直接伪造。**

## 首次启动

启用内置登录后，首次打开 WebUI 会进入创建管理员页面：

```http
POST /api/auth/bootstrap
{"username":"admin","password":"至少 8 位"}
```

如果账户已存在，`bootstrap` 返回 409。

## 会话

- 登录返回 opaque Token；
- 浏览器保存到 `localStorage`，请求携带 `Authorization: Bearer <token>`；
- 会话默认 12 小时；
- 退出使当前会话失效；
- 密码使用 `scrypt`（N=16384, r=8, p=1）加盐哈希。

## 角色

| 角色 | 读 | 推理/任务 | 设置/账户/集群管理 |
| --- | --- | --- | --- |
| `viewer` | ✓ |  |  |
| `operator` | ✓ | ✓ |  |
| `admin` | ✓ | ✓ | ✓ |

当前规则：

- `GET/HEAD` 需要 `viewer`；
- 其他 `/api/*` 默认需要 `operator`；
- `/api/settings` 写入、`/api/auth/users` 管理需要 `admin`；
- `/v1/*` 继续使用 `AIBOX_API_TOKEN`，不混用 WebUI 会话；
- 集群 Worker 使用 `AIBOX_CLUSTER_TOKEN` 注册，可绕过 WebUI 会话。

## API

```http
GET    /api/auth/status
POST   /api/auth/bootstrap
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/auth/users
POST   /api/auth/users
PATCH  /api/auth/users/{id}
DELETE /api/auth/users/{id}
```

## 配置

```text
AIBOX_AUTH_ENABLED=1
AIBOX_AUTH_MODE=builtin
AIBOX_AUTH_SESSION_HOURS=12
AIBOX_AUTH_EXTERNAL_HEADER=X-Forwarded-User
AIBOX_AUTH_EXTERNAL_ROLES_HEADER=X-Forwarded-Roles
```

## 当前限制

- 账户、会话目前保存在 SQLite；PostgreSQL/Redis 账户后端尚未接入。
- 外置模式是可信头模式，不是完整 OIDC 客户端。
- 没有密码找回、MFA、审计日志导出。
- 权限矩阵是路径级，不是每个模型/任务级 ACL。
