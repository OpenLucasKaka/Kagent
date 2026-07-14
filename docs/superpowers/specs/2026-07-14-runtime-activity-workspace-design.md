# Runtime Activity Workspace Design

## Context

The Ink terminal currently shows active work through one spinner line with a
generic status such as `Thinking`, `Working`, or `Reviewing result`. The
runtime already emits structured planner, tool, approval, and answer events,
and completed tools may provide a redacted user-facing presentation. However,
the frontend reduces those events to a broad label while a run is active.

This leaves operators unable to tell what the agent is doing, what it has
already found, how far the run has progressed, or whether the agent needs a
decision. Writing every event into the transcript would make a transparent but
noisy terminal. Kagent needs a compact, temporary workspace for the active run.

## Goals

1. Show the current user-facing activity, elapsed time, recent result, and
   progress count during every active runtime run.
2. Let an operator expand safe supporting details without exposing internal
   tool identifiers, raw inputs, secrets, or unredacted output.
3. Make approval state unambiguous: the interface must say it is waiting for
   the operator rather than implying that work is still progressing.
4. Preserve the editable Ink prompt, IME-safe cursor behavior, transcript
   pagination, cancellation, steering, and existing idle-state result expansion.
5. Fit the panel into 40-column terminals and degrade safely for small heights.

## Non-goals

- Adding a web dashboard or changing the Python classic terminal UI.
- Revealing chain-of-thought, hidden plan text, raw tool arguments, or internal
  tool names in the operator transcript.
- Persisting activity events after a run ends.
- Replacing the existing completed-result transcript entries.
- Changing the runtime tool policy, approval rules, or provider protocol.

## Operator Experience

During a run, the terminal reserves space immediately above the prompt for a
Runtime Activity Workspace. The compact default is intentionally short:

```text
⠹ Collecting release guidance · 18s
  Inspecting operations documentation
  Latest: Found 4 reusable checks
  2 completed · Ctrl+O details · Esc stop
› Add: apply this to the internal release path
```

The first row gives the current phase and elapsed time. The second row gives a
safe target or action summary. The third row shows the most recent completed
outcome when one is available. The fourth row provides a completed-step count
and discoverable controls. The existing prompt remains editable while the
runtime works, so Enter continues to queue a steering instruction.

When the operator presses `Ctrl+O` during an active run, the workspace expands
to include the most recent safe detail plus a bounded timeline of completed
phases and outcomes. It never displays raw event payloads. When idle, `Ctrl+O`
retains its current behavior of expanding or collapsing the latest completed
transcript result.

When approval is required, the Activity Workspace changes its first row to
`Waiting for your decision` and displays the action title and target already
prepared for the Approval Panel. The Approval Panel remains the only place for
Allow/Deny controls and is rendered after the activity workspace. This makes
the blocked condition obvious without duplicating a decision control.

On completion, cancellation, or failure, the workspace disappears before the
next idle prompt. The final answer, cancellation message, error, and completed
tool outcome remain in the normal transcript under their existing retention
rules.

## Event And Data Design

### Runtime presentation contract

`tool_completed` already carries a redacted `presentation` object. Runtime
execution will add an equivalent presentation projection to `tool_started`.
The projection has only the fields used by the Ink UI:

```json
{
  "title": "Inspecting operations documentation",
  "detail": "Reading a project guide"
}
```

The presentation helper owns this projection and receives the tool name and
resolved input. It must apply the same redaction and safe-target rules used for
completed presentations. If it cannot derive a safe title, it returns a
generic user-facing action such as `Preparing the next step`; it must never
fall back to the tool identifier.

Planner events require no new payload. The Ink reducer maps their known event
types to safe phrases: `Planning next steps`, `Plan ready`, and `Replanning`.
Approval events use the existing user-facing title and target. Answer streaming
maps to `Writing the response`.

### Frontend activity state

The npm UI adds a focused `RuntimeActivityState` separate from `TranscriptState`.
It contains:

- `phase`: current safe label;
- `detail`: current safe detail or target;
- `latestOutcome`: the latest safe completed-result detail;
- `completedCount`: count of completed planner and tool phases;
- `timeline`: a bounded, newest-last list of safe activity records;
- `expanded`: whether the active workspace details are visible.

The state is created on `run_started`, updated from `run_progress`, switched to
a waiting phase for `approval_required`, and cleared only after terminal run
completion, cancellation, or failure has been reduced. A new run always starts
with a fresh activity state. Command palette operations and provider setup do
not create one.

The reducer treats incomplete or malformed presentation metadata as absent and
uses the safe phase fallback. It limits timeline retention to six records so
long-running sessions cannot consume the viewport or grow unbounded state.

### Rendering and layout

`RuntimeActivityWorkspace` is rendered after the transcript and before the
Approval Panel, status line, command palette, and prompt. It replaces the
generic active `StatusLine` for runtime runs; startup and provider-saving
states keep their existing spinner behavior.

`createTerminalLayout` receives the workspace state and reserves its exact
wrapped row count. The compact form uses at most three rows: phase, latest
detail/outcome, and controls. At 56 columns or wider it uses up to four rows.
Expanded details reserve additional rows only while visible. If vertical space
is constrained, the panel hides the latest outcome before hiding the phase,
approval panel, or prompt.

The existing `Ctrl+O` handler is contextual:

- while an activity workspace exists, toggle its `expanded` flag;
- otherwise, toggle the latest transcript result exactly as it does today.

`Ctrl+C`, `Esc`, Enter-to-steer, transcript PageUp/PageDown, and command menu
navigation keep their current meanings.

## Error Handling And Safety

- A malformed progress event cannot throw from the UI reducer or render raw
  JSON; it is reduced to the generic phase when appropriate.
- A failed run records the existing user-facing error transcript entry and
  clears the active workspace; no stale `Working` panel remains.
- Cancellation changes the active phase to `Stopping` until the terminal
  completion event arrives, then clears it.
- Approval details remain opt-in behind the existing `d` control and are not
  copied into the activity timeline.
- All activity strings pass through the existing terminal-safe text handling
  and runtime redaction path before rendering.

## Components And Ownership

| Area | Responsibility |
| --- | --- |
| `src/kagent/runtime/presentation.py` | Build redacted safe presentation for tool start and completed outcomes. |
| `src/kagent/runtime/agent.py` | Attach the start presentation to emitted `tool_started` progress events. |
| `npm/src/activity.ts` | Define activity state, progress-event mapping, bounded timeline, and reducer. |
| `npm/src/app-state.ts` | Own activity lifecycle alongside transcript and status reduction. |
| `npm/src/ui-components.tsx` | Render the workspace, estimate its rows, and include it in terminal layout. |
| `npm/src/App.tsx` | Render the workspace and route contextual `Ctrl+O`. |

## Testing

1. Unit-test every planner, tool-start, tool-complete, approval, answer,
   cancellation, and failure event mapping in the activity reducer.
2. Test absent, malformed, and unsafe presentation payloads use a safe fallback
   and never render a tool identifier.
3. Test bounded timeline retention, completed-count updates, run reset, and
   contextual `Ctrl+O` behavior.
4. Test workspace row estimation at 40, 56, and 100 columns, including
   expanded state, long CJK text, active approval, and a short terminal.
5. Test Ink render trees for compact, expanded, approval, cancellation, and
   completion states without regressing prompt visibility or IME cursor sync.
6. Test the Python runtime's start presentation is redacted and matches the
   existing user-facing presentation policy.
7. Run `npm run test:cli`, `pytest`, `ruff check src tests`, and the repository
   check gate before release.

## Acceptance Criteria

- A running Kagent session communicates current work, last result, elapsed
  time, completed work, and decision state without requiring raw logs.
- Operators can expand and collapse safe run evidence during execution.
- No normal activity view exposes a raw tool name, input, secret, or hidden
  chain-of-thought.
- The prompt remains editable while a run is active and behaves exactly as it
  does today for steering, history, IME, and cancellation.
- The compact interface remains legible at 40 columns and does not displace
  the approval panel or active prompt.
- Existing runtime, npm, and UI tests pass alongside the new coverage.
