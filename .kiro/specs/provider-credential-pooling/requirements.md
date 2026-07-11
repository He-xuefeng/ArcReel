# 预置供应商凭证池化 Requirements

## 1. 范围与兼容

### Requirement 1.1 默认关闭
系统必须为每个预置供应商提供独立的 `credential_pool_enabled` 配置，类型为布尔值，默认值为 `false`。

验收标准：
- 升级后所有预置供应商默认保持池化关闭。
- 池化关闭时，生成任务仍只使用该 provider 的 `active` 凭证。
- 池化关闭时，租赁表与参与池化标记不得影响生成行为。

### Requirement 1.2 适用范围
第一版凭证池化只适用于预置供应商，不适用于自定义供应商。

验收标准：
- 自定义供应商凭证模型不变。
- 自定义供应商不显示预置供应商池化开关。
- 自定义供应商任务不进入 credential lease 逻辑。

### Requirement 1.3 ADR 兼容
系统必须新增 ADR，说明凭证池化是 ADR 0016 的受开关保护扩展。

验收标准：
- ADR 明确手动 active 凭证仍是默认模式。
- ADR 明确池化是显式 opt-in 模式。

### Requirement 1.4 不改变生成语义
池化不得改写供应商模型选择、价格计算、用量统计的业务语义。

验收标准：
- provider/model 解析优先级保持现有语义。
- 成本快照与用量统计仍按现有 provider/model 归因。
- credential pool 只影响使用哪条凭证调用 provider，不改变模型能力、价格表或调用类型。

### Requirement 1.5 第一版非目标边界
第一版不得把凭证池化扩展为复杂限流、配额或优先级调度系统。

验收标准：
- 第一版不实现凭证级 RPM / RPD / 余额感知调度。
- 第一版不实现 429 冷却、自动摘除故障 key、凭证权重或优先级。
- 第一版不实现 provider 级 `total_max_workers`。
- 第一版不要求池化状态管理页或批量测试所有凭证。
- 第一版不自动识别供应商免费/付费层级。

## 2. 凭证参与池化

### Requirement 2.1 凭证启用标记
每条预置供应商凭证必须支持 `is_enabled`，用于表示是否参与池化。

验收标准：
- `is_enabled=true` 时，该凭证在 provider 池化开启后可被新任务租赁。
- `is_enabled=false` 时，该凭证不接新任务。
- 池化关闭时，`is_enabled` 不影响生成行为。

### Requirement 2.2 新增凭证默认策略
实现设计必须明确新增凭证的默认参与策略。

验收标准：
- 若选择默认不参与池化，新凭证 `is_enabled=false`。
- 若选择 active 凭证默认参与，仍不得改变 `credential_pool_enabled=false` 下的旧行为。
- 前端在池化开启时新增凭证，必须明确提示用户是否参与池化。

## 3. 前端交互

### Requirement 3.1 池化关闭 UI
池化关闭时，凭证列表必须保持当前 active 单选语义。

验收标准：
- 每个 provider 最多一条凭证显示为“使用中”。
- 点击未激活凭证仍表示切换 active 凭证。
- 生成任务只使用 active 凭证。

### Requirement 3.2 池化开启 UI
池化开启时，凭证列表必须切换为参与池化语义。

验收标准：
- 凭证行不再用单选圆点表达唯一生效凭证。
- 每条凭证显示“参与池化”开关，对应 `is_enabled`。
- `active` 凭证只作为默认/首选标记，用于连接测试默认项和关闭池化后的回退。
- 没有任何凭证参与池化时，provider 详情或凭证列表提示“当前没有可用池化凭证”。

### Requirement 3.3 开关幂等与失败回滚
池化开关、参与池化开关、并发模式切换必须按幂等 PATCH 语义实现。

验收标准：
- 前端保存期间禁用对应控件。
- 保存失败时回滚 UI 或重新拉取后端状态。
- 双击或慢连接不得造成 UI 与后端状态不一致。
- 保存成功后刷新 provider 配置状态与凭证列表，避免旧 UI 状态残留。

### Requirement 3.4 关闭池化时的运行中任务提示
关闭池化只影响关闭后的新任务，已租赁或已绑定任务继续使用原凭证。

验收标准：
- 已绑定任务继续显示其实际凭证名称或脱敏标识。
- UI 不得暗示运行中任务已切换到 active 凭证。
- 有活跃 lease 时，provider 详情或任务详情可提示仍有任务使用池化凭证运行中。

## 4. 租赁与调度

### Requirement 4.1 租赁前置
池化开启时，任务必须在 submit 前租赁凭证。

验收标准：
- 租赁成功后，任务使用该凭证构造 backend。
- 租赁失败时，任务不得 submit。
- 租赁失败时，任务不得回退 active 凭证。
- 租赁失败时，任务不得切换 provider。

### Requirement 4.2 Claim 前过滤
凭证可用性必须作为 worker claim 前的调度过滤条件。

验收标准：
- provider 开启池化且无可租赁凭证时，任务保持 `queued`。
- 无可租赁凭证时，worker 不得先 claim 为 `running` 再等待。
- 无可租赁凭证时，不得注册 `SlotTable` 占用。

### Requirement 4.3 Claim 后竞态处理
如果因并发竞态导致 claim 后租赁失败，系统必须 requeue 任务并避免本轮反复 claim。

验收标准：
- 任务被重新置为 `queued`。
- 当前调度轮次将该 provider 加入 credential-full 黑名单。
- 用户看到等待可用凭证，而不是任务失败。

### Requirement 4.4 Provider 隔离
租赁必须按 provider 隔离。

验收标准：
- Agnes key 全忙只影响 Agnes 任务。
- OpenAI 池化关闭时仍走 active 凭证。
- Vidu 或其他 provider 的池化状态不受 Agnes 影响。

### Requirement 4.5 平台层边界
租赁池是平台调度层能力，不是 provider backend 能力。

验收标准：
- 各 provider backend 不感知 `credential_pool_enabled`、lease、`is_enabled`。
- Provider backend 只接收已由 `credential_id` overlay 后的配置。
- 新增预置供应商走统一 backend assembly 路径即可获得池化能力。

### Requirement 4.6 租赁生命周期
租赁必须随任务执行结果正确释放或恢复。

验收标准：
- 任务终态后释放对应 credential lease。
- 任务 submit 前租赁成功但 submit 失败时，按现有失败/重试语义处理，并在任务终态释放租赁。
- submit 出现 ambiguous error 时不得自动换 key 重新提交，避免重复扣费。
- worker 崩溃后遗留的 active lease，系统恢复时必须根据 task 状态决定保留、恢复或释放。

## 5. 并发模式

### Requirement 5.1 Shared 模式
系统必须支持 `shared` 并发模式，表示图片与视频共享同一凭证并发名额。

验收标准：
- 同一凭证正在跑图片任务时，视频任务不能租赁该凭证。
- 同一凭证正在跑视频任务时，图片任务不能租赁该凭证。
- 第一版 `shared` 模式默认容量为 `total_max_inflight=1`。

### Requirement 5.2 Separate 模式
系统必须支持 `separate` 并发模式，表示图片与视频分别计算凭证并发名额。

验收标准：
- 同一凭证可同时运行 1 个 image 任务和 1 个 video 任务。
- 同一凭证不能同时运行第 2 个 image 任务。
- 同一凭证不能同时运行第 2 个 video 任务。
- 第一版 `separate` 模式默认容量为 `image_max_inflight=1`、`video_max_inflight=1`。

### Requirement 5.3 Provider lane 并发保持原语义
现有 `image_max_workers` / `video_max_workers` 保持 provider lane 总闸门语义。

验收标准：
- 池化不改变 provider lane 并发配置含义。
- key 级租赁作为 provider lane 之后的最终闸门。
- 第一版不新增 provider 级 `total_max_workers`。

## 6. Provider Job 绑定与恢复

### Requirement 6.1 绑定持久化
视频 submit 成功后，系统必须持久化 provider job 与 credential 的绑定。

验收标准：
- 绑定至少包含 `task_id`、`provider_id`、`provider_job_id`、`credential_id`、`media_type`、`model_id`。
- poll、resume、download 必须使用绑定的 `credential_id`。
- 后续不得重新从池中选择凭证。
- 后续不得使用当前 active 凭证兜底。

### Requirement 6.2 绑定失败 fail-fast
provider job 已 submit 但绑定 `credential_id` 持久化失败时，任务必须 fail-fast。

验收标准：
- 任务不得静默继续 poll。
- 任务失败原因使用 `credential_binding_persist_failed`。
- 该策略与现有 provider_job_id 持久化失败语义一致。

### Requirement 6.3 旧任务兼容
旧任务没有 `credential_id` 绑定时，系统必须走历史兼容路径。

验收标准：
- 旧任务 resume 可使用 active 凭证兼容。
- 系统记录 `credential_binding_missing` warning。
- 旧任务兼容不得影响新任务绑定逻辑。

## 7. Backend 缓存隔离

### Requirement 7.1 Cache key 包含 credential_id
池化开启时，backend cache key 必须包含 `credential_id`。

验收标准：
- 不同 `credential_id` 不复用同一 backend。
- 池化关闭时可使用 `credential_id=None` 的统一 key。
- 配置变化后仍触发现有 backend cache 失效。

## 8. 禁用与删除

### Requirement 8.1 禁用凭证
禁用凭证只阻止新任务租赁。

验收标准：
- 已租赁或已绑定任务不被打断。
- 新任务不再租赁该凭证。

### Requirement 8.2 删除凭证保护
删除凭证时，如果存在关联运行中或可恢复任务，系统必须拒绝删除。

验收标准：
- 存在 active lease 时返回 HTTP 409。
- 存在 running task、pending resume task 或未终态 provider job 绑定时返回 HTTP 409。
- 用户看到“凭证仍有关联运行中任务，无法删除”。
- 删除/禁用接口必须校验凭证属于指定 provider。

## 9. 连接测试

### Requirement 9.1 单条凭证测试
连接测试必须保留按指定凭证测试的能力。

验收标准：
- 测试单条凭证时使用该 `credential_id`。
- 测试接口校验凭证属于指定 provider。
- 测试响应不得回显明文 secret。
- 连接测试失败返回的 provider 错误必须截断，并避免回显 secret。

### Requirement 9.2 默认凭证测试
未指定凭证时，测试供应商默认凭证。

验收标准：
- 池化关闭或未指定凭证时使用 `active` 凭证。
- 池化开启时 `active` 可作为默认/首选测试凭证。

### Requirement 9.3 池测试可选增强
池化开启时，可选提供“测试池中所有凭证”的入口。

验收标准：
- 该能力不作为第一版阻塞项。
- 若实现，必须逐条返回脱敏测试结果。

## 10. 错误与等待原因

### Requirement 10.1 稳定 code
池化相关等待原因、失败原因和接口错误必须使用稳定 code。

验收标准：
- 不持久化中文文案。
- 用户可见文案走 i18n。
- 任务失败类原因优先复用或扩展 `lib/task_failure.py`。

### Requirement 10.2 必需错误/等待码
系统必须定义并使用以下 code：

- `waiting_for_credential`
- `credential_lease_conflict`
- `credential_binding_persist_failed`
- `credential_binding_missing`
- `credential_in_use`
- `credential_lease_release_failed`

验收标准：
- 每个 code 都有明确处理方式。
- 用户可见 code 都有 zh/en/vi 文案。

## 11. 安全与可观测性

### Requirement 11.1 密钥不复制
池化层只处理凭证身份，不复制凭证明文。

验收标准：
- 租赁表、task payload、provider job binding 只保存 `credential_id`。
- 不复制 `api_key` / `access_key` / `secret_key`。
- 日志不得输出明文 secret。
- `base_url` 含敏感信息时应避免完整输出或做脱敏。
- 前端池化 UI 只展示脱敏字段，与现有凭证列表一致。

### Requirement 11.2 诊断信息
系统必须提供足够的脱敏诊断信息。

验收标准：
- 任务列表或详情暴露稳定等待原因 code。
- Provider 详情或诊断信息展示池化摘要：`credential_pool_enabled`、并发模式、参与池化凭证数量、active lease 数量。
- 单个任务详情可展示绑定的凭证名称或脱敏标识。
- 系统诊断日志下载包含脱敏 lease 摘要。

### Requirement 11.3 国际化文案
新增用户可见文案必须补齐 zh/en/vi。

验收标准：
- 至少包含“启用凭证池化”“参与池化”“并发模式”。
- 至少包含“图片/视频共享并发”“图片/视频分别并发”。
- 至少包含“等待可用凭证”“凭证仍有关联运行中任务，无法删除”。
- i18n 一致性测试通过。

## 12. 性能与数据库访问

### Requirement 12.1 高频 claim 性能
凭证池状态进入 worker 高频 claim 路径，不得引入 N+1 查询。

验收标准：
- worker claim 前的凭证池状态批量加载，或按 provider 缓存当前调度周期快照。
- active lease 查询不得扫描全表。
- SQLite 下无空闲凭证时优先 claim 前过滤，避免频繁 claim/requeue 写锁竞争。

### Requirement 12.2 索引与恢复扫描
租赁表必须支持高频查询与 bounded 恢复扫描。

验收标准：
- 租赁表支持按 `provider_id`、`credential_id`、`status`、`media_type` 查询的索引。
- 租赁释放与恢复扫描使用 bounded batch。
- 启动或定时修复不得持有长事务。

## 13. 迁移与回滚

### Requirement 13.1 数据库迁移默认值
数据库迁移必须保持旧行为。

验收标准：
- 所有 provider 的 `credential_pool_enabled=false`。
- `provider_credential.is_enabled` 的迁移默认值必须在实现设计中明确，且不得改变 `credential_pool_enabled=false` 下的旧行为。
- 新 lease/binding 表可空表启动。
- 不要求回填历史任务。

### Requirement 13.2 发布顺序
发布应先后端兼容，再前端入口。

验收标准：
- 先发布数据库迁移和后端兼容字段。
- 再发布前端池化开关。
- 前端未发布时后端默认行为不变。

### Requirement 13.3 回滚策略
关闭所有 provider 的 `credential_pool_enabled` 必须能回到 active key 路径。

验收标准：
- 新任务回到 active key 路径。
- 已绑定任务继续使用绑定 credential 完成。
- 回滚不得把已绑定任务改用 active 凭证。

## 14. 测试要求

### Requirement 14.1 自动化测试矩阵
实现必须覆盖需求文档中的测试矩阵。

验收标准：
- 后端测试覆盖池化关闭、shared、separate、claim 前过滤、claim 后竞态、绑定失败、resume、submit 失败释放、ambiguous submit 不换 key、删除/禁用、backend cache。
- 前端测试覆盖 UI 模式切换、保存失败回滚、无可用池化凭证提示。
- i18n 测试覆盖新增 zh/en/vi key 一致性。
