# Unified Kagent Home Design

## Context

Kagent currently stores user-level data across XDG-style directories:

- provider configuration under `${XDG_CONFIG_HOME:-~/.config}/kagent`;
- conversation state, prompt history, approvals, and patch checkpoints under
  `${XDG_STATE_HOME:-~/.local/state}/kagent`;
- the npm-managed Python runtime and update metadata under
  `${XDG_CACHE_HOME:-~/.cache}/kagent`.

This layout follows Linux conventions but makes a terminal product harder to
understand, back up, migrate, and remove. Kagent should expose one predictable
user-level product directory while preserving project-local `.kagent` state.

## Goals

1. Make `~/.kagent` the default root for all user-level Kagent data.
2. Keep project-specific runtime workspaces and skills under `$PWD/.kagent`.
3. Preserve every existing explicit `KAGENT_*_PATH` or directory override.
4. Introduce `KAGENT_HOME` as the shared root override.
5. Safely migrate durable data from the old XDG layout on first use.
6. Keep Python and npm entrypoints consistent.
7. Preserve owner-only permissions and reject unsafe symlink layouts.

## Non-goals

- Moving project-local `.kagent/runtime-workspace` into the user home.
- Migrating disposable Python virtual environments or update caches.
- Adding Redis, MySQL, PostgreSQL, or cloud synchronization.
- Replacing the current session-memory format with a multi-session database.
- Removing existing environment-variable overrides.

## Directory Layout

The default user-level layout is:

```text
~/.kagent/
├── config/
│   └── provider.json
├── state/
│   ├── session-memory.json
│   ├── history
│   ├── pending-approvals/
│   └── patches/
├── cache/
│   ├── npm-python/
│   └── npm-self-update.json
└── .migration-v1-complete
```

Project-specific state remains:

```text
$PWD/.kagent/
├── runtime-workspace/
└── skills/
```

## Path Resolution

Every existing explicit path override retains the highest precedence:

```text
explicit KAGENT_* path or directory
    > KAGENT_HOME-derived path
    > ~/.kagent-derived path
```

`KAGENT_HOME` must be a non-empty absolute or home-relative user path after
expansion. Python and Node path helpers normalize it consistently.

The XDG variables stop influencing new default writes. They are consulted only
to locate legacy migration sources. This prevents Kagent from continuing to
split new state after migration.

## Migration

Migration runs before user state is read from default paths. It copies only
durable data:

| Legacy source | New destination |
| --- | --- |
| XDG config `provider.json` | `config/provider.json` |
| XDG state `session-memory.json` | `state/session-memory.json` |
| XDG state `history` | `state/history` |
| XDG state `pending-approvals/` | `state/pending-approvals/` |
| XDG state `patches/` | `state/patches/` |

The migration does not copy cache content. A new npm-managed Python runtime is
bootstrapped under `~/.kagent/cache/npm-python` when needed.

Migration rules:

- never overwrite an existing destination;
- copy files atomically with mode `0600`;
- create directories with mode `0700`;
- reject symlink sources, destinations, or parent chains;
- reject unexpected non-file entries inside migrated state directories;
- leave legacy sources untouched;
- retry safely after an interrupted or failed migration;
- write `.migration-v1-complete` only after all eligible items succeed;
- skip legacy discovery when `KAGENT_HOME` is explicitly set, because a custom
  home must not silently import unrelated state.

Python owns durable-state migration so direct Python entrypoints behave the
same as npm-launched sessions. The npm launcher owns only its cache paths and
does not migrate disposable cache data.

## Components

### Python path module

`kagent.utils.paths` owns:

- resolving `KAGENT_HOME`;
- deriving config, state, and cache paths;
- locating legacy XDG sources;
- performing safe, idempotent durable-state migration.

Existing provider, memory, approval, patch, and runtime modules call this
module instead of independently reconstructing home paths.

### Node path module

`npm/src/kagent-home.ts` owns the Node-side `KAGENT_HOME` resolution and cache
paths. The npm launcher uses it for the private Python runtime and update state.
The stdio runtime client uses the same module for pending-approval defaults.

### Entry points

Durable migration is invoked by Python CLI and service startup before default
provider or state paths are consumed. Direct library calls that request a
default durable path also trigger migration defensively.

## Error Handling

Unsafe migration sources fail with a concise configuration error and do not
write the completion marker. Existing new-layout data remains authoritative.
Missing legacy paths are normal and produce no warning. Cache recreation is
silent unless bootstrap itself fails.

## Security

- User home, config, state, and cache directories use mode `0700`.
- Provider configuration, memory, history, and marker files use mode `0600`.
- Migration never follows symlinks.
- Migration never overwrites new-layout data.
- Existing redaction and secret-handling behavior remains unchanged.

## Compatibility

Existing overrides such as `KAGENT_LLM_CONFIG_PATH`,
`KAGENT_SESSION_MEMORY_PATH`, `KAGENT_HISTORY_PATH`,
`KAGENT_PENDING_APPROVAL_PATH`, `KAGENT_PATCH_STATE_DIR`, and
`KAGENT_NODE_VENV` continue to work unchanged.

Documentation will describe `KAGENT_HOME` and the new default layout. Legacy
XDG paths remain documented only as migration sources.

## CI Prerequisite

The current GitHub Actions workflow invokes `npm run check` without installing
npm dependencies. A clean checkout therefore uses an incompatible global
TypeScript compiler and fails before Python checks. The workflow must set up a
supported Node version and run `npm ci` before `scripts/run_checks.sh`.

This is a prerequisite verification repair, not part of the storage behavior.

## Testing

Tests must cover:

1. default `~/.kagent` path derivation;
2. `KAGENT_HOME` and explicit-path precedence;
3. migration of each durable legacy artifact;
4. destination-wins behavior;
5. idempotent retry and completion marking;
6. symlink and permission rejection;
7. Python and Node path parity;
8. clean-checkout npm installation and build;
9. the complete Python, npm, Ruff, packaging, and smoke gates.

## Acceptance Criteria

- New installations write user-level data only below `~/.kagent` unless an
  explicit override is configured.
- Existing installations retain provider configuration and durable state after
  first launch.
- No legacy file is deleted or overwritten.
- Project-local `.kagent` behavior is unchanged.
- Python and npm entrypoints agree on the same home layout.
- A clean GitHub Actions runner installs npm dependencies and passes the full
  repository check suite.
