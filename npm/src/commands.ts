import type { SessionCommandOption } from "./protocol";

export type CommandMenuState = {
  query: string;
  options: SessionCommandOption[];
  selectedIndex: number;
  selectedCommand: string;
};

export function updateCommandMenu(
  catalog: SessionCommandOption[],
  input: string,
  previous: CommandMenuState | string | null,
): CommandMenuState | null {
  const query = commandQuery(input);
  if (query === null) {
    return null;
  }
  const normalized = query.toLowerCase();
  const options = catalog.filter((option) =>
    commandNames(option).some((name) => name.toLowerCase().startsWith(normalized)),
  );
  if (options.length === 0) {
    return null;
  }

  const selectedCommand = typeof previous === "string" ? previous : previous?.selectedCommand;
  const previousIndex = selectedCommand
    ? options.findIndex((option) => option.command === selectedCommand)
    : -1;
  const selectedIndex = previousIndex >= 0 ? previousIndex : 0;
  return {
    query,
    options,
    selectedIndex,
    selectedCommand: options[selectedIndex].command,
  };
}

export function moveCommandSelection(
  state: CommandMenuState,
  offset: number,
): CommandMenuState {
  if (offset === 0 || state.options.length === 0) {
    return state;
  }
  const selectedIndex = wrapIndex(state.selectedIndex + offset, state.options.length);
  return {
    ...state,
    selectedIndex,
    selectedCommand: state.options[selectedIndex].command,
  };
}

export function commandCompletion(state: CommandMenuState): string {
  const selected = state.options[state.selectedIndex];
  if (!selected) {
    return state.query;
  }
  const commandName = selected.command.split(/\s+/, 1)[0];
  return selected.command.includes(" ") ? `${commandName} ` : commandName;
}

function commandQuery(input: string): string | null {
  const value = input.trimStart();
  if (!value.startsWith("/") || /\s/.test(value)) {
    return null;
  }
  return value;
}

function commandNames(option: SessionCommandOption): string[] {
  return [option.command.split(/\s+/, 1)[0], ...option.aliases];
}

function wrapIndex(value: number, length: number): number {
  return ((value % length) + length) % length;
}
