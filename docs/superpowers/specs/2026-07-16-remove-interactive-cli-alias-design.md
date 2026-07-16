# Remove the `--interactive` CLI Alias

## Goal

Keep one explicit entry point for the classic Python terminal UI:
`kagent --classic`. Remove the redundant `--interactive` public option so
`kagent --interactive` can no longer select a different UI accidentally.

## Scope

The npm launcher continues to open the Ink UI for a bare interactive TTY
invocation (`kagent`). It continues to strip `--classic` and invoke the Python
CLI with no goal, which makes the Python CLI enter its internal interactive
mode.

The Python CLI removes the `--interactive` argument while retaining an internal
interactive state. With no goal and no introspection command, the CLI sets that
state automatically. This preserves direct development invocations and the
`--classic` launcher path without exposing a second interactive option.

The following behavior is intentionally unchanged:

- Ink startup failure may fall back to the Python CLI.
- `KAGENT_CLASSIC_UI` may select the classic path.
- Piped and other non-TTY invocations may use the Python CLI without rendering
  the classic terminal UI.
- Ink continues to use `kagent.cli.stdio_runtime` as its Python backend.
- One-shot goals and discovery commands continue to use the Python CLI.

## CLI Changes

Remove `--interactive` from argparse help and accepted arguments. Update help
and error text that currently tells users to combine options with
`--interactive`; those messages should describe interactive mode instead.

Because removing the argparse option also removes the automatically-created
`args.interactive` attribute, default-mode initialization must explicitly set
the internal value before later validation and dispatch read it.

Documentation and verification scripts must stop invoking `--interactive`.
Classic UI documentation should point only to `kagent --classic`. Direct
`python -m kagent.cli` references may remain where they are explicitly intended
for development or operations.

## Tests

Add or update tests to prove:

1. `--interactive` is rejected as an unknown argument and absent from help.
2. A Python CLI invocation with no goal still enters internal interactive mode.
3. Options such as `--interactive-json` and `--session-memory` still work when
   no goal causes interactive mode automatically.
4. The existing npm launcher test continues to prove that `kagent --classic`
   invokes Python with an empty argument list.
5. Ink fallback and non-TTY routing remain unchanged.

## Non-goals

This change does not remove the classic Python UI, redesign either UI, migrate
one-shot commands to Ink, or remove the Python CLI/backend.
