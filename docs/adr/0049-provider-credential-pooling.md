# ADR 0049: Built-in Provider Credential Pooling

## Status

Accepted

## Context

ADR 0016 introduced multiple credentials for built-in providers with a single manually selected active credential. That active credential path is still the default behavior and remains the rollback path for this change.

Some built-in providers allow users to operate several independent credentials for the same provider. We need an opt-in way for the generation scheduler to distribute work across those credentials without changing provider backend semantics, model selection, pricing attribution, or custom provider behavior.

## Decision

Add provider credential pooling as an explicit opt-in extension of ADR 0016 for built-in providers only.

Each built-in provider gets two non-secret config values:

- `credential_pool_enabled`, default `false`
- `credential_pool_concurrency_mode`, either `shared` or `separate`

Each built-in provider credential gets an `is_enabled` flag. New credentials default to `is_enabled=false`; when pooling is enabled, the UI asks explicitly whether the credential participates in the pool.

When pooling is disabled, new work continues to use the provider's manually active credential. Existing active credential semantics, connection testing defaults, and rollback behavior stay unchanged.

When pooling is enabled, the scheduler leases a participating credential before submitting work. Provider backends do not know about pool settings, leases, or `is_enabled`; they only receive config already overlaid for a specific `credential_id`. This keeps pooling as a scheduling-layer capability, not a provider backend capability.

Video provider jobs persist a binding from provider job id to credential id after submit. Poll, resume, and download paths use that binding so running or resumable jobs continue with their original credential even if active credentials or pool settings change later.

## Consequences

- Pooling is safe to roll out behind a per-provider default-off switch.
- Custom providers stay on their existing credential model.
- Manual active credential remains the default and rollback mode.
- Scheduler and repository code own lease acquisition, release, recovery, and pool diagnostics.
- Provider backend implementations remain simpler and do not need to model pooling.
- Disabling pooling affects only future scheduling; already leased or bound jobs continue on their original credential.
