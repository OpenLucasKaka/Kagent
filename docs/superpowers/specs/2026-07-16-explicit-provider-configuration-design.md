# Explicit Provider Configuration Design

## Context

Kagent currently mixes two different classes of configuration:

- system execution policy, such as request timeout and retry behavior;
- deployment identity, such as provider, endpoint, model, and credentials.

System execution policy may have product-owned defaults. Deployment identity must not.
The current provider setup violates that boundary by defaulting to an
OpenAI-compatible provider, inferring a provider from endpoint or model text, selecting
the first setup option, and pre-filling provider-specific endpoints and models.

This design makes provider configuration explicit across the Python CLI, stdio runtime,
and npm Ink interface.

## Goals

- Require the user to explicitly select a provider.
- Require the user to explicitly enter the Base URL and model.
- Accept the API key exactly as supplied; an explicitly empty key is valid only for
  providers that do not require authentication.
- Preserve system-owned defaults for timeout, retry count, and retry backoff.
- Never infer, replace, downgrade, or fall back to another provider, endpoint, model, or
  credential.
- Fail clearly when deployment identity is missing, invalid, or unusable.

## Non-goals

- Removing the supported-provider menu.
- Removing system execution defaults.
- Adding provider discovery or endpoint probing.
- Validating that a model exists before the first provider request.
- Automatically migrating incomplete or previously inferred configuration.

## Configuration Classification

| Field | Classification | Default allowed |
|---|---|---|
| `provider` | Deployment identity | No |
| `base_url` | Deployment identity | No |
| `model` | Deployment identity | No |
| `api_key` | Deployment identity | No |
| `timeout_seconds` | System execution policy | Yes |
| `max_retries` | System execution policy | Yes |
| `retry_backoff_seconds` | System execution policy | Yes |

An empty API key is a user-supplied value, not a product default. It is accepted only
when the selected provider does not require a key.

## Provider Configuration Model

`LLMProviderConfig.provider` will represent the unconfigured state explicitly instead
of defaulting to `OPENAI_COMPATIBLE`. Its type will be `Optional[ProviderKind]` with a
default of `None`.

The remaining deployment identity fields keep empty strings as their unconfigured
representation. They must not receive provider-specific defaults anywhere in the
configuration pipeline.

`missing_provider_config_fields()` will report `KAGENT_LLM_PROVIDER` when no provider
was supplied, in addition to the existing Base URL and model checks. API-key presence
continues to depend on the explicitly selected provider.

Provider normalization validates an explicitly supplied provider value. It does not
infer a provider from the Base URL or model. The existing endpoint/model detection path
will be removed from configuration loading.

## Configuration Sources and Precedence

Configuration precedence remains:

```text
system defaults < saved configuration < environment variables
```

The semantics differ by classification:

- Deployment identity environment variables override saved values when the variable is
  present, including when its value is empty. This lets an operator explicitly clear a
  stored identity value; required-field validation then fails rather than silently
  falling back to the file.
- System execution environment variables override saved values only when non-empty.
  Empty operational values retain the saved value or system default.

Loading a saved configuration without an explicit provider produces an unconfigured
provider state. It must not assume `openai_compatible`.

Saving is allowed only after strict validation succeeds. Saved identity values are the
exact normalized user inputs; Kagent does not substitute provider presets.

## Supported Provider Catalog

Kagent retains a catalog of supported provider kinds because provider kind controls
protocol handling, display names, and API-key requirements. A catalog entry contains
only:

```text
provider identifier
display label
whether an API key is required
```

Catalog entries do not contain a Base URL or model. The global `DEFAULT_LLM_MODEL`
constant and provider-specific endpoint/model presets will be removed.

## Python CLI Setup

`kagent --configure` continues to display a numbered or arrow-key provider menu.

- No provider is selected initially.
- The numeric prompt has no `[1]` default.
- Pressing Enter without choosing a provider returns a validation error.
- Arrow-key mode requires an explicit arrow-key selection before Enter can continue.
- Base URL and Model prompts start empty and reject empty input.
- API Key input starts empty. Empty input is accepted only when the chosen provider does
  not require a key.

The CLI setup functions no longer accept or pass a `default_model` parameter.

Runtime configuration errors use neutral examples such as `your-provider`,
`https://your-endpoint/v1`, and `your-model`. No vendor or model is recommended.

## Stdio Runtime and Ink Setup

The stdio `runtime_ready` event continues to expose supported provider options, but the
provider option protocol removes `base_url` and `model` fields.

The Ink setup state uses `selectedIndex: number | null` and begins with `null`.

- Enter with no selection stays on the provider stage and displays an error.
- The first Up or Down action creates an explicit selection.
- Moving from provider selection to Base URL always initializes an empty editor.
- Moving to Model always initializes an empty editor.
- Returning to an earlier stage preserves only values the user already entered during
  the current setup session.

The final `provider_configure` request contains exactly the provider, Base URL, model,
and API key collected from the user.

## Runtime Behavior

The LangGraph runtime and LLM request implementation do not choose configuration.
They receive a validated `LLMProviderConfig` and use it exactly as supplied.

If configuration is incomplete, Runtime construction fails before a request. If the
endpoint is unreachable, the model does not exist, authentication fails, or the selected
provider is incompatible, the existing provider error is returned. Kagent does not try
another endpoint, model, provider, or credential.

## Compatibility

This is an intentional configuration tightening:

- Existing saved configurations with an explicit provider remain valid.
- Existing configurations that relied on the historical implicit
  `openai_compatible` provider become unconfigured until the provider is added.
- Environments that set only Base URL and model must also set
  `KAGENT_LLM_PROVIDER`.
- Existing timeout and retry behavior remains unchanged.

## Documentation

Public setup documentation will describe all deployment identity fields as required
operator input. Examples use neutral placeholders and do not present a vendor endpoint
or model as a default.

Provider names may appear when documenting supported adapters. Provider-specific URLs
and models may appear only as clearly labeled examples, never as defaults, presets, or
pre-filled configuration.

## Testing Strategy

Python tests will prove:

- a new config has no provider, Base URL, model, or API key;
- missing provider is reported as a configuration error;
- Base URL and model no longer infer provider kind;
- environment presence can explicitly clear saved deployment identity values;
- provider setup rejects an empty provider selection, Base URL, and model;
- provider setup never pre-fills endpoint or model values;
- saved explicit configurations still load and environment values still override them;
- runtime uses the exact validated configuration supplied by the user.

TypeScript and npm integration tests will prove:

- provider options contain no endpoint or model presets;
- Ink setup begins without a selected provider;
- Enter cannot continue until the user selects a provider;
- Base URL and model editors begin empty;
- the emitted provider configuration exactly matches user input;
- system timeout and retry defaults remain unchanged.

Repository searches will reject production references to `DEFAULT_LLM_MODEL` and the
removed provider-specific preset values. Test fixtures use an explicit supported
provider identifier with synthetic values such as `https://example.test/v1` and
`test-model`.

## Acceptance Criteria

The change is complete when no production path can obtain provider, Base URL, model, or
API key from a product-owned default, preset, inference, or fallback; both setup UIs
require explicit user input; incomplete or unusable configuration fails clearly; and
all Python, npm, and smoke checks pass.
