# 预置供应商凭证池化 Design

## 1. 设计边界

凭证池化只作用于预置供应商的调度层。Provider backend 不感知 `credential_pool_enabled`、`is_enabled`、lease 或 binding，只接收已经由指定 `credential_id` overlay 后的 provider config。

第一版保持以下边界：

- 自定义供应商不进入池化逻辑。
- 不实现 RPM / RPD / 余额感知、429 冷却、权重优先级、provider 级 `total_max_workers`。
- `image_max_workers` / `video_max_workers` 继续表示 provider lane 总并发。
- 池化默认关闭，关闭时仍使用当前 `active` credential。
- submit 后绑定实际使用的 `credential_id`，池化开启绑定租赁凭证，池化关闭绑定当时的 active 凭证；poll / resume / download 固定使用同一凭证。

## 2. 数据模型

### 2.1 provider_config 新增 key

继续使用现有 `provider_config` KV 表，新增两个非 secret key：

| key | 类型 | 存储值 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `credential_pool_enabled` | bool | `"true"` / `"false"` | `"false"` | provider 级池化开关 |
| `credential_pool_concurrency_mode` | enum | `"shared"` / `"separate"` | `"shared"` | 凭证图片/视频并发模式 |

`ConfigService._validate_value()` 增加校验：

- `credential_pool_enabled` 只接受可规范化为布尔值的字符串，入库统一为 `"true"` 或 `"false"`。
- `credential_pool_concurrency_mode` 只接受 `shared` / `separate`。
- 未配置时 resolver 使用默认值，不写回 DB。

### 2.2 provider_credential 新增字段

表：`provider_credential`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `is_enabled` | `Boolean NOT NULL` | `false` | 是否参与池化 |
| `last_leased_at` | `DateTime(timezone=True) NULL` | `NULL` | 最近一次被池化租赁的时间，用于近似轮询 |

索引：

| 索引名 | 字段 | 说明 |
| --- | --- | --- |
| `ix_provider_credential_provider_enabled` | `provider, is_enabled` | 批量加载 provider 的可租赁凭证 |
| `ix_provider_credential_provider_last_leased` | `provider, last_leased_at, id` | 按最久未使用优先选择，形成轮询效果 |

新增凭证默认 `is_enabled=false`。如果 provider 已开启池化，前端新增凭证表单显示“参与池化”开关，用户显式选择后随 POST 传入。

### 2.3 provider_credential_lease

新表：`provider_credential_lease`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `id` | `Integer PK autoincrement` | - | 租赁记录 id |
| `task_id` | `String NOT NULL` | - | ArcReel task id，外键 `tasks.task_id` |
| `provider` | `String(32) NOT NULL` | - | provider id，冗余用于高频过滤 |
| `credential_id` | `Integer NOT NULL` | - | 外键 `provider_credential.id` |
| `media_type` | `String(16) NOT NULL` | - | `image` / `video` |
| `status` | `String(16) NOT NULL` | `active` | `active` / `released` |
| `owner_id` | `String(80) NULL` | `NULL` | worker owner id，恢复扫描定位用 |
| `acquired_at` | `DateTime(timezone=True) NOT NULL` | now | 获得租赁时间 |
| `released_at` | `DateTime(timezone=True) NULL` | `NULL` | 释放时间 |
| `release_reason` | `String(64) NULL` | `NULL` | `succeeded` / `failed` / `cancelled` / `recovered` 等 |
| `created_at` | `DateTime(timezone=True) NOT NULL` | now | 创建时间 |
| `updated_at` | `DateTime(timezone=True) NOT NULL` | now | 更新时间 |

索引与约束：

| 名称 | 字段 | 条件 | 说明 |
| --- | --- | --- | --- |
| `uq_provider_credential_lease_task_active` | `task_id` | `status='active'` | 一个任务最多一个 active lease |
| `ix_provider_credential_lease_provider_status_media` | `provider, status, media_type` | - | claim 前批量判断 provider 是否有空闲凭证 |
| `ix_provider_credential_lease_credential_status_media` | `credential_id, status, media_type` | - | 判断单凭证占用 |
| `ix_provider_credential_lease_status_updated` | `status, updated_at` | - | bounded 恢复扫描 |

并发容量由 repository 在事务内计算，不靠静态唯一约束表达，因为 `shared` / `separate` 是 provider 配置，不能用同一个跨数据库 partial unique index 同时表达两种语义。

### 2.4 provider_job_binding

新表：`provider_job_binding`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `id` | `Integer PK autoincrement` | - | 绑定记录 id |
| `task_id` | `String NOT NULL UNIQUE` | - | ArcReel task id |
| `provider` | `String(32) NOT NULL` | - | provider id |
| `provider_job_id` | `String NOT NULL` | - | provider 侧 job id |
| `credential_id` | `Integer NOT NULL` | - | 提交该 job 使用的 credential |
| `media_type` | `String(16) NOT NULL` | - | 第一版主要为 `video` |
| `model_id` | `String NULL` | `NULL` | 提交使用的模型标识 |
| `created_at` | `DateTime(timezone=True) NOT NULL` | now | 创建时间 |
| `updated_at` | `DateTime(timezone=True) NOT NULL` | now | 更新时间 |

索引：

| 索引名 | 字段 | 说明 |
| --- | --- | --- |
| `uq_provider_job_binding_task` | `task_id` | 一个任务一个 provider job 绑定 |
| `ix_provider_job_binding_provider_job` | `provider, provider_job_id` | resume/download 按 provider job 查找 |
| `ix_provider_job_binding_credential` | `credential_id, media_type` | 删除凭证保护与诊断 |

### 2.5 tasks 新增字段

表：`tasks`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `credential_id` | `Integer NULL` | `NULL` | 当前任务实际租赁/绑定的 credential id；旧任务为空 |
| `wait_reason` | `String(64) NULL` | `NULL` | queued 等待原因，如 `waiting_for_credential` |

索引：

| 索引名 | 字段 | 说明 |
| --- | --- | --- |
| `idx_tasks_status_provider_wait` | `status, provider_id, wait_reason, queued_at` | 任务列表与 claim 前等待标记 |
| `idx_tasks_credential_status` | `credential_id, status` | 删除凭证保护与任务详情 |

`task.payload_json` 不写入 secret，也不复制凭证明文。第一版可不把 `credential_id` 写入 payload，统一以 task 列和 binding 表为准。

## 3. Repository 与服务接口

### 3.1 CredentialRepository

新增/扩展方法：

```python
async def create(..., is_enabled: bool = False) -> ProviderCredential
async def update(..., is_enabled: bool | None = None) -> None
async def list_enabled_by_provider(provider: str) -> list[ProviderCredential]
async def get_by_id_for_provider(provider: str, cred_id: int) -> ProviderCredential | None
async def touch_last_leased(cred_id: int, leased_at: datetime) -> None
```

删除凭证前调用占用检查，存在以下任一条件返回 HTTP 409 / `credential_in_use`：

- active lease。
- `tasks.status IN ('running', 'cancelling') AND tasks.credential_id = cred_id`。
- `provider_job_binding.credential_id = cred_id` 且关联 task 未终态或需要 resume。

### 3.2 CredentialPoolRepository

新增文件：`lib/db/repositories/credential_pool_repository.py`

核心返回类型：

```python
@dataclass(frozen=True)
class CredentialPoolSettings:
    enabled: bool
    concurrency_mode: Literal["shared", "separate"]

@dataclass(frozen=True)
class CredentialLeaseResult:
    acquired: bool
    credential_id: int | None = None
    reason: str | None = None
```

核心方法：

```python
async def get_pool_settings(provider: str) -> CredentialPoolSettings
async def list_pool_summaries(providers: Iterable[str] | None = None) -> dict[str, CredentialPoolSummary]
async def find_full_providers(media_type: str, providers: Iterable[str] | None = None) -> set[str]
async def acquire_lease(provider: str, media_type: str, task_id: str, owner_id: str) -> CredentialLeaseResult
async def release_lease(task_id: str, reason: str) -> bool
async def recover_leases(limit: int = 500) -> int
```

`acquire_lease()` 语义：

1. 读取 provider 池化设置。关闭时返回 `acquired=False, reason='pool_disabled'`，调用方走 active 凭证路径。
2. 只读取同 provider 且 `is_enabled=true` 的凭证。
3. 候选顺序为 `last_leased_at NULLS FIRST, last_leased_at ASC, id ASC`，形成轮询。
4. 在同一事务内锁定候选 credential 行并统计 active lease：
   - `shared`：该 credential 任意 media 的 active lease 数必须 `< 1`。
   - `separate`：该 credential 当前 media 的 active lease 数必须 `< 1`。
5. 插入 active lease，更新 `provider_credential.last_leased_at`，更新 `tasks.credential_id` 并清空 `wait_reason`。
6. 若没有候选，返回 `acquired=False, reason='waiting_for_credential'`。

跨数据库策略：

- PostgreSQL：对候选 `provider_credential` 行使用 `SELECT ... FOR UPDATE SKIP LOCKED`，避免两个 worker 同时选择同一凭证。
- SQLite：在单写事务内完成候选选择、active lease 统计与插入；SQLite 写事务串行化，避免双租赁。
- 若 insert/update 因竞态失败，返回 `credential_lease_conflict`，由 worker requeue。

### 3.3 ProviderJobBindingRepository

新增文件：`lib/db/repositories/provider_job_binding_repository.py`

```python
async def create_binding(
    *,
    task_id: str,
    provider: str,
    provider_job_id: str,
    credential_id: int,
    media_type: str,
    model_id: str | None,
) -> None

async def get_by_task(task_id: str) -> ProviderJobBinding | None
async def get_by_provider_job(provider: str, provider_job_id: str) -> ProviderJobBinding | None
async def has_active_or_resumable_binding(credential_id: int) -> bool
```

`create_binding()` 与 `tasks.provider_job_id` / `tasks.credential_id` 更新放在同一事务里。失败时抛异常，由调用方编码为 `credential_binding_persist_failed`，不继续 poll。

### 3.4 TaskRepository / GenerationQueue

新增方法：

```python
async def requeue_for_credential_wait(task_id: str, reason: str) -> int
async def mark_waiting_for_credential(provider_id: str, media_type: str, limit: int = 200) -> int
async def clear_wait_reason(task_id: str) -> None
async def persist_provider_job_binding(...) -> None
```

`claim_next(media_type, pool_full_providers=...)` 继续接收黑名单。新增约定：

- claim 成功时清空 `wait_reason`。
- `pool_full_providers` 中的 provider 任务保持 `queued`。
- 对这些 provider 的 queued 任务做 bounded `wait_reason='waiting_for_credential'` 更新，避免每轮全表写。
- 池化关闭的新视频任务在 claim 后解析 provider 时，同时解析并保存当时 active credential id，用于后续 binding。

## 4. Resolver / Backend Assembly

### 4.1 ConfigResolver

扩展方法签名：

```python
async def provider_config(self, provider_id: str, credential_id: int | None = None) -> dict[str, str]
async def pool_settings(self, provider_id: str) -> CredentialPoolSettings
```

行为：

- `credential_id is None`：保持现有 active credential overlay。
- `credential_id is not None`：校验 credential 存在且属于 provider，然后 overlay 该 credential。
- 自定义供应商不支持指定 `credential_id`。

### 4.2 assemble_backend

扩展入口：

```python
async def assemble_backend(
    *,
    provider_id: str,
    media_type: str,
    model_id: str | None,
    resolver: ConfigResolver,
    rate_limiter: Any | None = None,
    credential_id: int | None = None,
) -> Any
```

`_load_builtin_config()` 调 `resolver.provider_config(provider_id, credential_id=credential_id)`。

### 4.3 backend cache

`server/services/generation_tasks.py` 中 `_backend_cache` key 改为：

```python
(media_type, provider_id, model_id, credential_id)
```

- 调用方未指定 credential：`credential_id=None`，复用当前 active 凭证路径。
- 调用方指定 credential：cache key 必须包含该 `credential_id`；池化开启任务和池化关闭的新视频绑定任务都走这一路径，避免 key-2 复用 key-1 客户端，也避免 active 切换后 resume/download 用错 key。
- 凭证更新、active 切换、池化开关切换、并发模式切换都调用 `invalidate_backend_cache()`。

## 5. Worker 调度流程

### 5.1 claim 前过滤

每个 media lane 调度循环：

```text
load provider lane capacity
load credential pool summaries for this media lane
pool_full_providers = providers where pool enabled and no idle credential
mark queued tasks for those providers with wait_reason=waiting_for_credential (bounded)
claim_next_task(media_type, pool_full_providers)
```

新入队任务已有 `tasks.provider_id`，因此可在 claim SQL 前过滤。历史 `provider_id IS NULL` 任务可能被 claim，claim 后 worker 解析出 provider 后再执行池化检查；如果发现池满，立即 requeue。

### 5.2 claim 后租赁

claim 返回 running task 后：

1. 解析实际 provider/model。
2. 若 provider 是自定义供应商：使用 `credential_id=None`，走现有自定义供应商路径。
3. 若预置 provider 池化关闭：解析当前 active credential id；视频任务保存该 id 供后续 binding，图片任务可继续使用 `credential_id=None` 的 active 路径。
4. 若预置 provider 池化开启：调用 `CredentialPoolRepository.acquire_lease()`。
5. 租赁成功后再 `SlotTable.register()`。
6. 租赁失败：调用 `requeue_for_credential_wait(task_id, reason)`，本轮把该 provider 加入 credential-full 黑名单，不注册 SlotTable，不 submit。

### 5.3 执行与释放

任务执行入口把 `credential_id` 传入 `get_media_generator()`：

```python
await get_media_generator(..., credential_context=CredentialContext(provider_id, media_type, credential_id))
```

worker finally：

- `succeeded` / `failed` / `cancelled` 后调用 `release_lease(task_id, reason)`。
- 释放失败记录 `credential_lease_release_failed` warning，不覆盖任务终态；恢复扫描后续修复。
- `SlotTable.release()` 与 lease release 都幂等。

## 6. Provider Job 绑定与 Resume

### 6.1 submit 后绑定

`lib/video_backends/base.py` 扩展：

```python
async def persist_provider_job_binding(
    task_id: str,
    job_id: str,
    *,
    provider: str,
    credential_id: int | None,
    media_type: str = "video",
    model_id: str | None = None,
) -> None
```

`ProviderJobIdPersistenceMixin._persist_provider_job_id()` 仍是所有提交-轮询型 video backend 的收口点：

- 新任务必须带 `credential_id`：池化开启时为租赁凭证，池化关闭时为 submit 当时的 active 凭证。
- `credential_id is not None`：同事务写 `tasks.provider_job_id`、`tasks.credential_id`、`provider_job_binding`。
- `credential_id is None` 仅允许旧任务/非 worker 兼容路径使用，不得作为新预置供应商视频任务的正常路径。
- 持久化失败抛异常，worker 终态失败码为 `credential_binding_persist_failed`。

`VideoGenerationRequest` 新增字段：

```python
credential_id: int | None = None
model_id: str | None = None
```

`MediaGenerator.generate_video_async()` 构造 request 时传入当前 video credential id 和 backend model。

池化关闭的新视频任务在构造 backend 前也必须解析并记录当时 active credential id。这样用户在 submit 后切换 active key，已提交 provider job 的后续 poll / resume / download 仍使用原 active credential，而不是切到新的 active credential。

### 6.2 resume 固定 credential

`GenerationWorker._process_resume_task()`：

1. 先按 `task_id` 查询 `provider_job_binding`。
2. 找到 binding：把 `provider` 注入 payload 的 `video_provider`，并把 `credential_id` 传给 `execute_resume_video_task()` / `get_media_generator()`。
3. 找不到 binding：记录 `credential_binding_missing` warning，走历史 active 兼容路径。
4. resume 使用绑定 credential 构造 backend，不重新租赁其他凭证。

### 6.3 poll/download 固定 credential

任何独立 poll、download 或 provider job 查询入口都必须先读取 `provider_job_binding`：

1. 找到 binding：使用 binding 的 `provider`、`provider_job_id`、`credential_id` 构造 backend 并执行查询/下载。
2. 找不到 binding：仅旧任务可走历史 active 兼容路径，并记录 `credential_binding_missing` warning。
3. 不得因为当前 active credential 变化而改用其他凭证查询同一个 provider job。

### 6.4 worker 崩溃后的 lease 恢复

启动或定时执行 bounded `recover_leases(limit=500)`：

- active lease 对应 task 已终态：释放 lease，`release_reason='recovered'`。
- active lease 对应 task 为 running/cancelling 且有 provider job binding：保留 lease，等待 resume 完成。
- active lease 对应 task 为 queued 且没有 binding：释放 lease，让任务重新调度。
- binding 存在但 lease 缺失的 resume task：resume 前按绑定 credential 创建恢复 lease；如果该 credential 被占用，则等待 `waiting_for_credential`，不得换 key。

## 7. API 设计

### 7.1 GET `/api/v1/providers/{provider_id}/config`

响应新增字段：

```json
{
  "credential_pool_enabled": false,
  "credential_pool_concurrency_mode": "shared",
  "credential_pool_summary": {
    "enabled_credentials_count": 0,
    "active_lease_count": 0
  }
}
```

### 7.2 PATCH `/api/v1/providers/{provider_id}/config`

继续使用现有 PATCH，新增允许 key：

```json
{
  "credential_pool_enabled": "true",
  "credential_pool_concurrency_mode": "shared"
}
```

成功后：

- commit。
- invalidate backend cache。
- `worker.reload_limits()`。
- 前端重新拉取 provider config 和 credentials。

### 7.3 GET `/api/v1/providers/{provider_id}/credentials`

`CredentialResponse` 新增：

```json
{
  "is_enabled": false,
  "active_lease_count": 0
}
```

`active_lease_count` 只返回数量，不返回 secret。

### 7.4 POST/PATCH credential

`CreateCredentialRequest` 新增：

```json
{ "is_enabled": false }
```

`UpdateCredentialRequest` 新增：

```json
{ "is_enabled": true }
```

PATCH 是幂等语义。保存失败前端回滚或重新拉取。

### 7.5 DELETE credential

删除前检查 active lease、running/cancelling task、未终态 provider job binding。占用时返回：

```json
HTTP 409
{
  "detail": {
    "code": "credential_in_use",
    "message": "凭证仍有关联运行中任务，无法删除"
  }
}
```

池化相关 API 错误统一返回结构化 detail：`{ "detail": { "code": string, "message": string } }`。`code` 是稳定机器码，`message` 由 Translator 按请求语言渲染；前端优先按 `code` 识别场景，任务/日志持久化只使用稳定 code。

### 7.6 POST `/api/v1/providers/{provider_id}/test`

保留现有 `credential_id` query：

- 指定 `credential_id`：测试该凭证并校验 provider 归属。
- 未指定：测试 active 凭证，即使池化开启也把 active 当默认/首选测试项。
- provider 错误截断到 200 字符，并避免 secret/base_url token 泄露。

“测试池中所有凭证”第一版不作为阻塞项；若实现，单独增加 `POST /providers/{provider_id}/test-pool`，逐条返回脱敏结果。

### 7.7 Tasks API

任务 dict 新增：

```json
{
  "credential_id": 123,
  "credential_name": "Agnes key 1",
  "credential_label": "Agnes key 1 / ****abcd",
  "wait_reason": "waiting_for_credential"
}
```

列表和详情均不返回明文 secret。`wait_reason` 由前端 i18n 渲染。

## 8. 前端设计

### 8.1 类型与 API

修改：

- `frontend/src/types/provider.ts`
  - `ProviderConfigDetail` 增加 `credential_pool_enabled`、`credential_pool_concurrency_mode`、`credential_pool_summary`。
  - `ProviderCredential` 增加 `is_enabled`、`active_lease_count`。
- `frontend/src/api.ts`
  - `patchProviderConfig()` 类型允许 pool key。
  - `createCredential()` / `updateCredential()` 类型允许 `is_enabled`。

### 8.2 ProviderDetail

在凭证列表上方增加池化控制区：

- Toggle：`启用凭证池化`。
- Segmented control：`shared` / `separate`，仅池化开启时启用。
- 摘要：参与池化凭证数量、active lease 数量。
- 若开启池化但 `enabled_credentials_count=0`，展示 warning：当前没有可用池化凭证。

交互：

- 保存期间禁用对应控件。
- 保存成功后重新拉取 provider config 和 credentials。
- 保存失败时展示错误并重新拉取后端状态。

### 8.3 CredentialList

新增 props：

```ts
poolEnabled: boolean
poolConcurrencyMode: "shared" | "separate"
```

池化关闭：

- 保持当前 active radio。
- 点击 radio 调 `/activate`。
- `is_enabled` 不展示为主要控制。

池化开启：

- 不显示 active radio 作为唯一生效含义。
- 每行显示“参与池化”开关，对应 `is_enabled`。
- `is_active` 只显示“默认”或“首选” badge，用于连接测试默认项和关闭池化回退。
- 行内展示 active lease 数量。
- 删除占用凭证时展示 `credential_in_use` 的本地化提示。

新增凭证表单：

- provider 池化开启时显示“参与池化”复选框，默认不勾选。
- provider 池化关闭时不改变旧表单行为。

## 9. i18n

后端新增 errors/providers 文案，前端新增 dashboard 文案，zh/en/vi 三语保持一致。至少包含：

- `credential_pool_enabled`
- `credential_pool_participation`
- `credential_pool_concurrency_mode`
- `credential_pool_shared`
- `credential_pool_separate`
- `waiting_for_credential`
- `credential_in_use`
- `credential_binding_persist_failed`
- `credential_binding_missing`
- `credential_lease_conflict`
- `credential_lease_release_failed`
- `no_enabled_pool_credentials`
- `active_pool_leases_hint`

任务失败类 code 优先补到 `lib/task_failure.py`，等待类 code 存 `tasks.wait_reason` 并由前端渲染。

## 10. 可观测性与诊断

日志允许输出：

- `provider_id`
- `credential_id`
- credential name
- `task_id`
- `provider_job_id`

禁止输出：

- `api_key`
- `access_key`
- `secret_key`
- 未脱敏的敏感 `base_url`

`server/services/diagnostics.py` 增加脱敏池化摘要：

```text
Provider credential pools
- agnes: enabled=true mode=shared enabled_credentials=4 active_leases=4
- openai: enabled=false mode=shared enabled_credentials=0 active_leases=0
```

不写明文 secret，不输出完整 base_url。

## 11. 迁移与 ADR

新增 Alembic migration：

- `provider_credential.is_enabled Boolean NOT NULL DEFAULT false`
- `provider_credential.last_leased_at DateTime NULL`
- 新建 `provider_credential_lease`
- 新建 `provider_job_binding`
- `tasks.credential_id Integer NULL`
- `tasks.wait_reason String(64) NULL`
- 添加上述索引与 partial unique index

发布顺序：

1. DB migration + 后端兼容字段。
2. 后端 API / worker / resolver 支持。
3. 前端开关入口。

新增 ADR：`docs/adr/00xx-provider-credential-pooling.md`，说明这是 ADR 0016 的 opt-in 扩展；手动 active 仍是默认模式。

## 12. 测试设计

后端测试：

- 池化关闭：仍只使用 active credential。
- `shared`：4 条 key 同时 4 个图片/视频混合任务各租一次，第 5 个 queued + `waiting_for_credential`。
- `separate`：同一 key 可同时 1 image + 1 video，不可第 2 个 image。
- claim 前过滤：全忙时不进入 running，不注册 SlotTable。
- claim 后竞态：租赁失败 requeue，本轮 provider 黑名单生效。
- submit 成功后 binding 持久化失败：`credential_binding_persist_failed` fail-fast。
- submit 失败释放 lease；ambiguous submit 不换 key。
- resume：binding credential_id 后重启仍使用同 credential。
- 删除占用凭证返回 409 / `credential_in_use`。
- 禁用占用凭证不影响运行中任务，新任务不再租赁。
- backend cache 不同 `credential_id` 不复用 backend。
- 连接测试指定 credential、默认 active、provider 归属校验、错误脱敏。

前端测试：

- 池化关闭显示 active radio。
- 池化开启显示参与池化开关，active 变默认/首选 badge。
- 开关保存期间禁用，失败回滚或刷新后端状态。
- 无 enabled credentials 时提示。
- 新增凭证在池化开启时显示参与池化复选框且默认 false。
- 删除占用凭证显示本地化错误。

质量检查：

- Python 修改文件执行 `uv run ruff check <files> && uv run ruff format <files>`。
- 后端相关测试执行 `uv run python -m pytest <tests>`。
- 前端执行 `pnpm lint && pnpm check`。
- i18n 执行 `uv run python -m pytest tests/test_i18n_consistency.py`。
