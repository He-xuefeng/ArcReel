export interface ModelInfoResponse {
  display_name: string;
  media_type: string;
  capabilities: string[];
  default: boolean;
  supported_durations: number[];
  duration_resolution_constraints: Record<string, number[]>;
  resolutions: string[];
}

export interface ProviderInfo {
  id: string;
  display_name: string;
  description: string;
  status: "ready" | "unconfigured" | "error";
  media_types: string[];
  capabilities: string[];
  configured_keys: string[];
  missing_keys: string[];
  models: Record<string, ModelInfoResponse>;
}

export interface ProviderField {
  key: string;
  label: string;
  type: "secret" | "text" | "url" | "number" | "file";
  required: boolean;
  is_set: boolean;
  value?: string;
  value_masked?: string;
  placeholder?: string;
}

// 凭证表单需要渲染的 secret 输入字段，由后端 registry 派生。
export interface CredentialSecretField {
  key: string;
  label: string;
}

export type CredentialPoolConcurrencyMode = "shared" | "separate";

export interface CredentialPoolSummary {
  enabled_credentials_count: number;
  active_lease_count: number;
}

export interface ProviderConfigDetail {
  id: string;
  display_name: string;
  description: string;
  status: "ready" | "unconfigured" | "error";
  media_types?: string[];
  fields: ProviderField[];
  credential_pool_enabled: boolean;
  credential_pool_concurrency_mode: CredentialPoolConcurrencyMode;
  credential_pool_summary: CredentialPoolSummary;
  // 凭证是否支持自定义 base_url，后端按 optional_keys 派生。
  supports_base_url: boolean;
  // 凭证表单应渲染的 secret 字段，有序。
  secret_fields: CredentialSecretField[];
  // 凭证“二选一”分组：满足任一组即视为凭证完整。
  secret_field_groups: string[][];
}

export interface ProviderTestResult {
  success: boolean;
  available_models: string[];
  message: string;
}

export interface ProviderCredential {
  id: number;
  provider: string;
  name: string;
  api_key_masked: string | null;
  credentials_filename: string | null;
  base_url: string | null;
  // 逐字段脱敏的可选 secret，其它 provider 可为 null 或缺省。
  access_key_masked?: string | null;
  secret_key_masked?: string | null;
  is_active: boolean;
  is_enabled: boolean;
  active_lease_count: number;
  created_at: string;
}

export type CallType = "image" | "video" | "text" | "audio";

export interface UsageStat {
  provider: string;
  display_name?: string;
  call_type: CallType;
  total_calls: number;
  success_calls: number;
  total_cost_usd: number;
  cost_by_currency: Record<string, number>;
  total_duration_seconds?: number;
}

export interface UsageStatsResponse {
  stats: UsageStat[];
  period: { start: string; end: string };
}
