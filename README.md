# Swarm Language

A (vibecoded) language for programming ant colony brains in the [SWARM challenge](https://dev.moment.com/swarm).

One program controls all 200 ants. Each ant runs the same brain — a state machine where each state executes until an action (move/pickup/drop) consumes the tick.

## Quick Start

```bash
# Install
uv tool install git+https://github.com/rpadaki/swarm-lang

# Compile a .sw file to antssembly
swarm examples/minimal.sw

# Lint
swarm check examples/minimal.sw

# Format
swarm fmt examples/minimal.sw
```

## Example

```swarm
package main

import "../lib/ant"
using ant

register dir

init {
    become wander
}

state wander {
    if carrying() { become go_home }
    if probe(HERE) == FOOD {
        pickup()
        become go_home
    }
    move(RANDOM)
    become wander
}

state go_home {
    if dir := sense(NEST) {
        move(dir)
        become do_drop
    }
    move(RANDOM)
    become go_home
}

state do_drop {
    drop()
    become wander
}
```

## Language Overview

- **States** — named blocks of logic. `become` transitions instantly (no tick).
- **Actions** — `move()`, `pickup()`, `drop()` consume the ant's tick.
- **Registers** — up to 8 named storage slots, with optional bindings to library extern registers.
- **Behaviors** — reusable state templates with exit wiring.
- **Packages** — `import`/`using`/`export` for modularity. The standard library (`lib/ant/`) wraps all antssembly instructions.
- **Inline asm** — `asm { SENSE target result }` for direct antssembly.

See [docs/swarm-lang-spec.md](docs/swarm-lang-spec.md) for the full language reference.

## Editor Support

### Zed

Install the [zed-swarm](https://github.com/rpadaki/zed-swarm) extension for syntax highlighting, outline symbols, and LSP features (diagnostics, completions, hover, go-to-definition, find references, formatting).

### LSP

Start the language server for other editors:

```bash
swarm lsp
```

### bat / terminal

```bash
mkdir -p "$(bat --config-dir)/syntaxes"
cp editors/bat/swarm.sublime-syntax "$(bat --config-dir)/syntaxes/"
bat cache --build
```

## Project Structure

```
swarm/              Python package (compiler, LSP, linter, formatter)
lib/ant/            Standard library (sensing, actions, constants)
parsers/            Tree-sitter grammar
examples/           Example programs
editors/            Editor integrations (bat, vim)
docs/               Language and antssembly specs
tests/              Test suite
```
