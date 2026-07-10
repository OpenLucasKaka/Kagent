"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.updateCommandMenu = updateCommandMenu;
exports.moveCommandSelection = moveCommandSelection;
exports.commandCompletion = commandCompletion;
function updateCommandMenu(catalog, input, previous) {
    const query = commandQuery(input);
    if (query === null) {
        return null;
    }
    const normalized = query.toLowerCase();
    const options = catalog.filter((option) => commandNames(option).some((name) => name.toLowerCase().startsWith(normalized)));
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
function moveCommandSelection(state, offset) {
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
function commandCompletion(state) {
    const selected = state.options[state.selectedIndex];
    if (!selected) {
        return state.query;
    }
    const commandName = selected.command.split(/\s+/, 1)[0];
    return selected.command.includes(" ") ? `${commandName} ` : commandName;
}
function commandQuery(input) {
    const value = input.trimStart();
    if (!value.startsWith("/") || /\s/.test(value)) {
        return null;
    }
    return value;
}
function commandNames(option) {
    return [option.command.split(/\s+/, 1)[0], ...option.aliases];
}
function wrapIndex(value, length) {
    return ((value % length) + length) % length;
}
