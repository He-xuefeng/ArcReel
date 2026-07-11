# 预置供应商凭证池化 Tasks

## 任务清单

### 1. 数据库模型与迁移

- [x] 1.1 扩展 `ProviderCredential` ORM
  - 文件：`lib/db/models/credential.py`
  - 增加 `is_enabled: bool = False`
  - 增加 `last_leased_at: datetime | None`
  - 增加索引 `ix_provider_credential_provider_enabled(provider, is_enabled)`
  - 增加索引 `ix_provider_credential_provider_last_leased(provider, last_leased_at, id)`
  - 覆盖：Requirement 2.1、2.2、12.2、13.1；Design 2.2

- [x] 1.2 新增租赁与绑定 ORM 模型
  - 文件：`lib/db/models/credential_pool.py`
  - 新增 `ProviderCredentialLease`
  - 新增 `ProviderJobBinding`
  - 定义 active lease partial unique index、provider/status/media、credential/status/media、status/updated_at、provider/job、credential/media 索引
  - 更新 `lib/db/models/__init__.py`
  - 覆盖：Requirement 4.1、4.2、6.1、10.1、12.2、13.1；Design 2.3、2.4

- [x] 1.3 扩展 `Task` ORM
  - 文件：`lib/db/models/task.py`
  - 增加 `credential_id: int | None`
  - 增加 `wait_reason: str | None`
  - 增加索引 `idx_tasks_status_provider_wait(status, provider_id, wait_reason, queued_at)`
  - 增加索引 `idx_tasks_credential_status(credential_id, status)`
  - 覆盖：Requirement 7.1、10.1、11.2、12.1；Design 2.5

- [x] 1.4 生成并校正 Alembic migration
  - 文件：`alembic/versions/<revision>_add_provider_credential_pooling.py`
  - 设置 `provider_credential.is_enabled Boolean NOT NULL DEFAULT false`
  - 设置 `provider_credential.last_leased_at DateTime NULL`
  - 创建 `provider_credential_lease`、`provider_job_binding`
  - 增加 `tasks.credential_id`、`tasks.wait_reason`
  - 创建所有索引与 partial unique index
  - 不回填历史任务，lease/binding 空表启动
  - 覆盖：Requirement 12.1、13.1；Design 11

### 2. 稳定 code 与配置解析

- [x] 2.1 增加池化配置校验与解析
  - 文件：`lib/config/service.py`
  - 允许并校验 `credential_pool_enabled` 为 bool 字符串，入库规范化为 `true` / `false`
  - 允许并校验 `credential_pool_concurrency_mode` 为 `shared` / `separate`
  - 保留 `image_max_workers` / `video_max_workers` 原语义
  - 覆盖：Requirement 1.1、5.3、13.1；Design 2.1

- [x] 2.2 固化范围与非目标守卫
  - 文件：`lib/custom_provider/*`、`server/routers/custom_providers.py`、相关前端自定义供应商页面（如有）
  - 自定义供应商不读取 `credential_pool_enabled`，不进入 credential lease 逻辑
  - 自定义供应商 UI 不显示预置供应商池化开关
  - 不新增 RPM / RPD / 余额感知、429 冷却、权重优先级、provider 级 `total_max_workers`
  - 覆盖：Requirement 1.2、1.5、5.3；Design 1

- [x] 2.3 定义池化错误/等待 code
  - 文件：`lib/task_failure.py` 或新增稳定 code 常量模块
  - 增加/登记 `waiting_for_credential`
  - 增加/登记 `credential_lease_conflict`
  - 增加/登记 `credential_binding_persist_failed`
  - 增加/登记 `credential_binding_missing`
  - 增加/登记 `credential_in_use`
  - 增加/登记 `credential_lease_release_failed`
  - 覆盖：Requirement 10.1、10.2；Design 9

### 3. Repository 层

- [x] 3.1 扩展 `CredentialRepository`
  - 文件：`lib/db/repositories/credential_repository.py`
  - `create(..., is_enabled=False)`
  - `update(..., is_enabled: bool | None = None)`
  - `list_enabled_by_provider(provider)`
  - `get_by_id_for_provider(provider, cred_id)`
  - `touch_last_leased(cred_id, leased_at)`
  - 删除/禁用接口可复用 provider 归属校验
  - 覆盖：Requirement 2.1、2.2、8.1、8.2；Design 3.1

- [x] 3.2 新增 `CredentialPoolRepository`
  - 文件：`lib/db/repositories/credential_pool_repository.py`
  - 实现 `CredentialPoolSettings`
  - 实现 `CredentialLeaseResult`
  - 实现 `get_pool_settings(provider)`
  - 实现 `list_pool_summaries(providers=None)`
  - 实现 `find_full_providers(media_type, providers=None)`
  - 覆盖：Requirement 4.2、4.4、5.1、5.2、11.1；Design 3.2、5.1

- [x] 3.3 实现原子 acquire/release/recover
  - 文件：`lib/db/repositories/credential_pool_repository.py`
  - `acquire_lease(provider, media_type, task_id, owner_id)` 按 `last_leased_at NULLS FIRST, ASC, id ASC` 轮询
  - shared 模式任意 media active lease 互斥
  - separate 模式同 media active lease 互斥
  - 租赁成功写 active lease、`tasks.credential_id`、清空 wait_reason、更新 `last_leased_at`
  - 租赁失败返回 `waiting_for_credential` 或 `credential_lease_conflict`
  - `release_lease(task_id, reason)` 幂等释放
  - `recover_leases(limit=500)` bounded 修复 active lease
  - 覆盖：Requirement 4.1、4.2、4.3、4.6、5.1、5.2、12.1、12.2；Design 3.2、6.4

- [x] 3.4 新增 `ProviderJobBindingRepository`
  - 文件：`lib/db/repositories/provider_job_binding_repository.py`
  - `create_binding(...)`
  - `get_by_task(task_id)`
  - `get_by_provider_job(provider, provider_job_id)`
  - `has_active_or_resumable_binding(credential_id)`
  - 覆盖：Requirement 6.1、6.2、6.3、8.2；Design 3.3、6.1-6.3

- [x] 3.5 扩展 `TaskRepository` / `GenerationQueue`
  - 文件：`lib/db/repositories/task_repo.py`
  - 文件：`lib/generation_queue.py`
  - `requeue_for_credential_wait(task_id, reason)`
  - `mark_waiting_for_credential(provider_id, media_type, limit=200)`
  - `clear_wait_reason(task_id)`
  - `persist_provider_job_binding(...)`
  - `_task_to_dict()` 返回 `credential_id`、`wait_reason`
  - claim 成功清空 `wait_reason`
  - 覆盖：Requirement 4.2、4.3、6.1、10.1、11.2；Design 3.4、5.1

### 4. Resolver、Backend Assembly 与缓存

- [x] 4.1 扩展 `ConfigResolver.provider_config()`
  - 文件：`lib/config/resolver.py`
  - 签名增加 `credential_id: int | None = None`
  - `credential_id=None` 保持 active overlay
  - `credential_id` 指定时校验 credential 属于 provider 并 overlay 指定凭证
  - 新增 `pool_settings(provider_id)`
  - 自定义供应商不支持指定 credential
  - 覆盖：Requirement 1.1、4.5、6.1、6.3；Design 4.1

- [x] 4.2 扩展 `assemble_backend()`
  - 文件：`lib/backend_assembly/assembler.py`
  - `assemble_backend(..., credential_id: int | None = None)`
  - `_load_builtin_config()` 透传 `credential_id`
  - 自定义供应商保持现有路径
  - 覆盖：Requirement 4.5、7.1；Design 4.2

- [x] 4.3 更新 generation backend cache key
  - 文件：`server/services/generation_tasks.py`
  - `_backend_cache` key 改为 `(media_type, provider_id, model_id, credential_id)`
  - `_get_or_create_*_backend()` 接收并透传 `credential_id`
  - 池化任务和绑定视频任务不复用其他 credential backend
  - 缓存失效保持配置变化后生效
  - 覆盖：Requirement 7.1、1.4；Design 4.3

### 5. Worker 调度与租赁生命周期

- [x] 5.1 在 worker claim 前加载 credential pool summary
  - 文件：`lib/generation_worker.py`
  - 每个 media lane 调度周期批量加载池化状态
  - 生成 `pool_full_providers`
  - 对池满 provider 的 queued 任务 bounded 标记 `waiting_for_credential`
  - `claim_next_task(media_type, pool_full_providers)` 过滤池满 provider
  - 覆盖：Requirement 4.2、4.4、12.1；Design 5.1

- [x] 5.2 在 claim 后执行凭证租赁
  - 文件：`lib/generation_worker.py`
  - claim 后解析实际 provider/model
  - 自定义供应商走现有路径
  - 预置供应商池化开启时调用 `acquire_lease()`
  - 租赁成功后再注册 SlotTable 并 submit
  - 租赁失败时 requeue，加入本轮 credential-full 黑名单，不注册 SlotTable
  - 覆盖：Requirement 4.1、4.3、4.4；Design 5.2

- [x] 5.3 处理池化关闭的视频 active credential 绑定
  - 文件：`lib/generation_worker.py`
  - 文件：`server/services/generation_tasks.py`
  - 预置供应商池化关闭时，视频任务解析 submit 当时 active credential id
  - 该 id 传入 `get_media_generator()` 与 `VideoGenerationRequest`
  - 图片任务保持现有 active 路径，不改变旧行为
  - 覆盖：Requirement 6.1、6.3、12.3；Design 5.2、6.1

- [x] 5.4 任务终态释放 lease
  - 文件：`lib/generation_worker.py`
  - succeeded/failed/cancelled 后调用 `release_lease(task_id, reason)`
  - 释放失败记录 `credential_lease_release_failed` warning，不覆盖任务终态
  - shutdown/orphan 恢复路径触发 bounded recovery
  - 覆盖：Requirement 4.6、10.2、12.2；Design 5.3、6.4

### 6. Provider Job 绑定与 Resume

- [x] 6.1 扩展 `VideoGenerationRequest`
  - 文件：`lib/video_backends/base.py`
  - 增加 `credential_id: int | None = None`
  - 增加 `model_id: str | None = None`
  - `ProviderJobIdPersistenceMixin` 调新 binding 持久化函数
  - 覆盖：Requirement 6.1、6.2；Design 6.1

- [x] 6.2 实现 binding 持久化 fail-fast
  - 文件：`lib/video_backends/base.py`
  - 文件：`lib/generation_queue.py`
  - 文件：`lib/db/repositories/task_repo.py`
  - 新函数同事务写 `tasks.provider_job_id`、`tasks.credential_id`、`provider_job_binding`
  - 持久化失败抛出并编码为 `credential_binding_persist_failed`
  - 不继续 poll
  - 覆盖：Requirement 6.1、6.2、10.2；Design 6.1

- [x] 6.3 `MediaGenerator.generate_video_async()` 传递 credential 信息
  - 文件：`lib/media_generator.py`
  - 构造 `VideoGenerationRequest` 时传入当前 credential id 和 model id
  - 不改变 provider/model 计费归因
  - 覆盖：Requirement 1.4、6.1；Design 6.1

- [x] 6.4 resume 使用 binding credential
  - 文件：`lib/generation_worker.py`
  - 文件：`server/services/resume_executor.py`
  - resume 前查 `provider_job_binding`
  - 找到 binding 时注入 provider 与 credential id
  - 找不到 binding 时记录 `credential_binding_missing` warning 并走旧 active 兼容
  - 不重新租赁、不使用当前 active 兜底新任务
  - 覆盖：Requirement 6.1、6.3、10.2、12.3；Design 6.2

- [x] 6.5 固定 poll/download 查询 credential
  - 文件：涉及独立 provider job poll/download 的服务入口
  - 新增 helper：按 `task_id` 或 `(provider, provider_job_id)` 读取 binding 并构造 backend
  - 找不到 binding 时仅旧任务走 active 兼容并记录 warning
  - 覆盖：Requirement 6.1、6.3；Design 6.3

### 7. Provider API 与诊断

- [x] 7.1 扩展 provider config 响应与 PATCH
  - 文件：`server/routers/providers.py`
  - `ProviderConfigResponse` 增加 `credential_pool_enabled`
  - 增加 `credential_pool_concurrency_mode`
  - 增加 `credential_pool_summary.enabled_credentials_count`
  - 增加 `credential_pool_summary.active_lease_count`
  - PATCH 成功后 invalidate backend cache 与 worker reload
  - 覆盖：Requirement 1.1、3.3、11.2；Design 7.1、7.2

- [x] 7.2 扩展 credential CRUD API
  - 文件：`server/routers/providers.py`
  - `CredentialResponse` 增加 `is_enabled`、`active_lease_count`
  - `CreateCredentialRequest` / `UpdateCredentialRequest` 增加 `is_enabled`
  - PATCH 参与池化开关幂等
  - DELETE 前做占用检查，返回 HTTP 409 结构化 detail `{code,message}`
  - 所有 credential 操作校验 provider 归属
  - 覆盖：Requirement 2.1、2.2、3.3、8.1、8.2、10.1；Design 7.3-7.5

- [x] 7.3 连接测试脱敏与归属校验补强
  - 文件：`server/routers/providers.py`
  - 保留 `credential_id` query
  - 未指定 credential 时使用 active 凭证
  - provider 错误截断并脱敏 secret/base_url token
  - 可选池测试不作为阻塞项，不在第一版任务中实现
  - 覆盖：Requirement 9.1、9.2、9.3、10.1；Design 7.6

- [x] 7.4 Tasks API 返回 wait/credential 摘要
  - 文件：`server/routers/tasks.py`
  - 文件：`lib/db/repositories/task_repo.py`
  - list/detail 返回 `wait_reason`
  - 返回 `credential_id`、`credential_name` 或脱敏 `credential_label`
  - 不返回明文 secret
  - 覆盖：Requirement 3.4、10.1、11.2；Design 7.7

- [x] 7.5 诊断日志增加池化摘要
  - 文件：`server/services/diagnostics.py`
  - 输出 provider 级池化摘要：enabled、mode、enabled credential count、active lease count
  - 不输出明文 secret 或完整敏感 base_url
  - 覆盖：Requirement 11.1、11.2；Design 10

### 8. 前端 UI 与类型

- [x] 8.1 更新前端类型与 API client
  - 文件：`frontend/src/types/provider.ts`
  - 文件：`frontend/src/api.ts`
  - `ProviderConfigDetail` 增加 pool 字段与 summary
  - `ProviderCredential` 增加 `is_enabled`、`active_lease_count`
  - create/update credential 支持 `is_enabled`
  - provider config PATCH 支持 pool key
  - 覆盖：Requirement 3.1、3.2、3.3；Design 8.1

- [x] 8.2 ProviderDetail 增加池化控制区
  - 文件：`frontend/src/components/pages/ProviderDetail.tsx`
  - 增加“启用凭证池化” toggle
  - 增加 shared/separate segmented control
  - 显示参与池化凭证数量和 active lease 数量
  - 开启但无 enabled 凭证时显示提示
  - 保存期间禁用控件，失败时展示错误并刷新后端状态
  - 覆盖：Requirement 3.2、3.3、5.1、5.2、11.2；Design 8.2

- [x] 8.3 CredentialList 支持池化开启/关闭两种 UI
  - 文件：`frontend/src/components/pages/CredentialList.tsx`
  - 池化关闭保持 active radio 和当前行为
  - 池化开启隐藏唯一 active radio 语义，显示“参与池化”开关
  - active 凭证改显示“默认/首选” badge
  - 行内显示 active lease 数量
  - 删除占用凭证展示 `credential_in_use` 本地化提示
  - 覆盖：Requirement 3.1、3.2、3.4、8.2；Design 8.3

- [x] 8.4 新增凭证表单支持参与池化
  - 文件：`frontend/src/components/pages/CredentialList.tsx`
  - provider 池化开启时显示“参与池化”复选框
  - 默认不勾选
  - provider 池化关闭时表单行为不变
  - 覆盖：Requirement 2.2、3.2；Design 8.3

### 9. i18n 与 ADR

- [x] 9.1 补齐后端 i18n key
  - 文件：`lib/i18n/zh/*.py` 或对应 namespace 文件
  - 文件：`lib/i18n/en/*.py`
  - 文件：`lib/i18n/vi/*.py`
  - 增加池化错误与提示文案
  - 确保 `tests/test_i18n_consistency.py` 通过
  - 覆盖：Requirement 10.1、10.2、11.3；Design 9

- [x] 9.2 补齐前端 i18n key
  - 文件：`frontend/src/i18n/zh/dashboard.json`
  - 文件：`frontend/src/i18n/en/dashboard.json`
  - 文件：`frontend/src/i18n/vi/dashboard.json`
  - 增加池化开关、参与池化、并发模式、等待可用凭证、删除占用凭证等文案
  - 覆盖：Requirement 11.3；Design 9

- [x] 9.3 新增 ADR
  - 文件：`docs/adr/00xx-provider-credential-pooling.md`
  - 说明凭证池化是 ADR 0016 的 opt-in 扩展
  - 明确手动 active credential 仍是默认模式
  - 明确 pool 是调度层能力，不是 provider backend 能力
  - 覆盖：Requirement 1.3、13.2、13.3；Design 11

### 10. 测试

- [x] 10.1 Repository 单元测试
  - 文件：`tests/...`
  - 覆盖 `CredentialPoolRepository.acquire_lease()` shared/separate
  - 覆盖所有 key 忙返回 `waiting_for_credential`
  - 覆盖 release/recover 幂等
  - 覆盖删除占用凭证判断
  - 覆盖：Requirement 4.1、4.6、5.1、5.2、8.2、12.2；Design 12

- [x] 10.2 Worker 调度测试
  - 文件：`tests/...`
  - 池化关闭仍只用 active
  - shared 下 4 key 对应 4 混合任务，第 5 queued
  - claim 前过滤不进入 running、不注册 SlotTable
  - claim 后竞态 requeue + provider 黑名单
  - 覆盖：Requirement 1.1、4.2、4.3、4.4、13.1；Design 12

- [x] 10.3 Binding / resume / cache 测试
  - 文件：`tests/...`
  - submit 后 binding 失败 fail-fast
  - 池化关闭视频绑定当时 active key，active 切换后 resume 仍用原 key
  - 池化开启视频 resume 使用租赁 key
  - ambiguous submit 不换 key
  - 不同 `credential_id` 不复用 backend cache
  - 覆盖：Requirement 6.1、6.2、6.3、7.1、4.6；Design 12

- [x] 10.4 Provider API 测试
  - 文件：`tests/...`
  - config GET/PATCH pool 字段
  - credential GET/POST/PATCH is_enabled
  - DELETE 占用凭证返回 409 结构化 code
  - 连接测试 credential 归属校验与错误脱敏
  - 覆盖：Requirement 2.1、3.3、8.2、9.1、9.2、10.1；Design 12

- [x] 10.5 前端组件测试
  - 文件：`frontend/src/components/pages/CredentialList.test.tsx`
  - 文件：新增或扩展 `ProviderDetail` 测试
  - 池化关闭 active radio
  - 池化开启参与池化开关
  - active 显示默认/首选 badge
  - 保存失败回滚/刷新
  - 无 enabled 凭证提示
  - 新增凭证默认不参与池化
  - 删除占用凭证错误展示
  - 覆盖：Requirement 3.1、3.2、3.3、3.4、8.2；Design 12

- [x] 10.6 验证命令
  - 后端修改文件执行 `uv run ruff check <files> && uv run ruff format <files>`
  - 后端相关测试执行 `uv run python -m pytest <tests>`
  - i18n 执行 `uv run python -m pytest tests/test_i18n_consistency.py`
  - 前端执行 `pnpm lint && pnpm check`
  - 覆盖：Requirement 14.1；Design 12
