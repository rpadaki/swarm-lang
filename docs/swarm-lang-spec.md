# Swarm Language Specification

Swarm is a state-machine language for the SWARM Ant Colony Optimization Challenge.
It compiles to antssembly, the challenge's assembly format. Each ant runs the same
program. Ants communicate only through pheromone trails on a 128x128 grid.

Design principles:

- **State machines.** Programs are collections of named states with `become` transitions.
- **Package system.** Libraries export functions and constants; user programs import and bind registers.
- **Action/instant separation.** Tick-consuming functions (`action func`) are distinct from instant operations.
- **Automatic optimizations.** Dead code elimination, coordinate tracking, and state dispatch are compiler-managed.

## Program Structure

A `.sw` file contains top-level declarations in any order:

```
package name               // library package declaration
import "name"              // import a library
using name                 // bring package exports into scope

const NAME = VALUE         // compile-time constant
register (...)             // allocate named registers with bindings
tag [N] name               // explicit heatmap tag
bool a, b, c               // packed boolean flags (1 register, up to 15 flags)

state name { ... }         // concrete state
state name = beh { ... }   // state instantiated from a behavior
behavior name { ... }      // reusable state template
func name() { ... }        // inline function (no params, no return)
init { ... }               // runs once at startup
```

## Packages

### Declaring a package

Library files declare a package name at the top:

```
package ant
```

### Exporting

Libraries export constants and functions with the `export` keyword:

```
export const N = 1
export func sense(target) -> volatile result { ... }
export action func move(direction) { ... }
```

### Importing

User programs import packages by relative path. Packages are directories
containing `.sw` files:

```
import "../lib/ant"
```

This loads all `.sw` files in the `ant/` directory and makes the package's exports
available via qualified references (`ant.move()`, `ant.N`). The package name comes
from the `package` declaration inside the library files, not from the import path.

Entry point programs declare `package main`.

### Using

`using` brings a package's exported functions and constants into unqualified scope:

```
using ant
```

After this, `move()` and `N` can be used without the `ant.` prefix.

`using` imports functions and constants only -- not registers. Register binding
is always explicit via the register block.

## Registers

Ants have 8 general-purpose 32-bit signed registers (`r0`-`r7`). Register `r0` is
reserved by the compiler as a scratch register and is never exposed to user code.
This leaves 7 user-allocatable registers (`r1`-`r7`).

### Register blocks

Registers are declared in a parenthesized block with optional bindings and initializers:

```
register (
    dir
    x(ant.dx) = 0
    y(ant.dy) = 0
    heading(ant.last_dir) = id() % 4 + 1
    mark_str = GREEN_START
    next_st
    tmp
)
```

Each entry has the form:

```
name                       // plain register
name(pkg.extern)           // bind to an extern register from a package
name = expr                // with initializer (runs before init block)
name(pkg.extern) = expr    // binding + initializer
```

Bindings connect user registers to `extern register` declarations in libraries.
When a library function references `dx`, and the user has declared `x(ant.dx)`,
the compiler maps `dx` to the same physical register as `x`.

The comma-separated flat syntax is also supported:

```
register dir, mark_str, dx, dy, next_st, last_dir, tmp
```

Register initializers are compiled into the program entry point, before the `init`
block body.

State dispatch is handled internally by the compiler. There is no need to declare
a register for it.

## Extern Registers

Libraries declare registers they reference but do not own:

```
extern register dx, dy, last_dir
```

Extern registers are placeholders. They are bound by the importing program's
register block (e.g., `x(ant.dx)`). If an extern register is never bound, all
code in the library that references it is eliminated by dead code elimination.

## Constants

```
const RED_START = 200
const RED_DECAY = 3
```

Constants are inlined at compile time wherever the name appears. In libraries,
use `export const` to make them available to importers.

## States

States are the core construct. Each state is a named block of code that the ant
executes:

```
state search {
    if carrying() { become start_return }
    if probe(HERE) == FOOD { become try_pickup }
    move(RANDOM)
    become search
}
```

### Auto-tagging

Every state automatically gets a heatmap tag (up to the 8-tag limit). The
compiler emits `TAG <index>` at the start of each state body. Manual `tag`
declarations can override or supplement this.

### Transitions with `become`

`become` is the only transition keyword. It performs an instant jump to another
state (no tick consumed):

```
become search
become try_pickup
```

Actions and transitions are always separate statements:

```
move(dir)
become search
```

This replaces the old `move(dir) -> search` syntax. The `->` arrow is now used
only in function return type annotations.

## Behaviors

Behaviors are reusable state templates with abstract exit points:

```
behavior random_walk {
    exit found_food
    exit found_trail

    if probe(HERE) == FOOD { become found_food }

    scratch = sense(FOOD)
    if scratch != 0 { become found_food }

    scratch = smell(CH_RED)
    if scratch != 0 { become found_trail }

    if last_dir != 0 {
        scratch = probe(last_dir)
        if scratch != WALL {
            move(last_dir)
            become self
        }
    }

    dir = rand(4)
    dir = dir + 1
    move(dir)
    become self
}
```

Instantiate with concrete wiring:

```
state exploring = random_walk {
    found_food -> try_grab
    found_trail -> follow_trail
}
```

The behavior body is inlined into the state. All `exit` names are replaced with
their wired targets. `self` maps to the instantiating state's own name. Behaviors
can also accept parameters:

```
behavior walk(threshold) { ... }
state exploring = walk(10) { ... }
```

## Init Block

Runs once when the ant spawns, before entering any state:

```
init { become search }
```

Register initializers execute before the init block body, so a simple `become`
is often sufficient:

```
register (
    x(ant.dx) = 0
    y(ant.dy) = 0
    heading(ant.last_dir) = id() % 4 + 1
)

init { become search }
```

## Functions

### Inline functions

Zero-parameter, no-return functions whose body is pasted at each call site:

```
func mark_green() {
    mark(CH_GREEN, 50)
}

state search {
    mark_green()
    move(E)
    become search
}
```

### Export functions (efuncs)

Parameterized functions defined in library packages. They support parameters,
return values, `action` annotation, volatility annotations, and `local` temporaries:

```
export func sense(target) -> volatile result stable(target == WALL || target == NEST) {
    asm { SENSE target result }
}

export action func move(direction) {
    asm { MOVE direction }
}

export func rand_range(lo, hi) -> result {
    local range
    range = hi - lo
    asm { RANDOM result range }
    result += lo
}
```

#### `action func`

Functions annotated with `action` consume the ant's tick. Only one action can
execute per tick. The standard actions are `move`, `pickup`, and `drop`.

```
export action func move(direction) {
    asm { MOVE direction }
}
```

When calling an action function, it is written as a statement:

```
move(dir)
pickup()
drop()
```

#### Return values

Functions can declare a return value with `-> result`:

```
export func carrying() -> result {
    asm { CARRYING result }
}
```

The caller receives the return value by assigning the call to a register:

```
scratch = carrying()
```

#### `local`

The `local` keyword declares compiler-assigned temporaries inside efuncs. These
use the scratch register (`r0`) without exposing it to the library author:

```
export func rand_range(lo, hi) -> result {
    local range
    range = hi - lo
    asm { RANDOM result range }
    result += lo
}
```

## Volatility and Stability

Functions that read environmental state may return values that change between
ticks. The volatility system tracks this to warn about stale reads.

### `volatile`

A function return annotated with `volatile` means its value may change after any
action (tick boundary):

```
export func smell(channel) -> volatile result {
    asm { SMELL channel result }
}
```

### `stable(predicate)`

A predicate can declare conditions under which a volatile return is actually
stable (will not change between ticks):

```
export func probe(direction) -> volatile result stable(result == WALL || result == NEST) {
    asm { PROBE direction result }
}
```

The predicate can reference both parameters and the result. It is evaluated at
compile time when arguments are constants; for register arguments, the compiler
assumes volatile.

### Stable returns

Functions without `volatile` return stable values that never go stale:

```
export func carrying() -> result { ... }
export func id() -> result { ... }
```

### Stale-read lint

The linter tracks volatile-derived values across statements. When an action
(tick-consuming function) executes, all volatile-derived registers become stale.
Reading a stale register produces a warning:

```
dir = smell(CH_RED)    // dir is volatile
move(dir)              // action: dir becomes stale
if dir != 0 { ... }   // WARNING: stale read of 'dir'
```

## Assignments

### Simple assignment

```
scratch = 42              // literal
scratch = other_reg       // register copy
scratch = sense(FOOD)     // function call
scratch = a + b           // binary expression
```

### Compound assignments

Compound assignment operators desugar to `target = target op expr`:

```
mark_str -= 1             // mark_str = mark_str - 1
x += dx                   // x = x + dx
count *= 2                // count = count * 2
```

Supported operators: `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`.

### Condition assignments (`:=`)

Inside `if` conditions, `:=` assigns and tests in one expression:

```
if dir := sense(FOOD) {
    move(dir)
    become try_pickup
}
```

This is equivalent to:

```
dir = sense(FOOD)
if dir != 0 {
    move(dir)
    become try_pickup
}
```

## Operators

### Binary operators

Arithmetic and bitwise operators, listed by precedence (highest first):

| Precedence | Operators | Description |
|---|---|---|
| 6 | `*` `/` `%` | Multiply, divide, modulo |
| 5 | `+` `-` | Add, subtract |
| 4 | `<<` `>>` | Left shift, right shift |
| 3 | `&` | Bitwise AND |
| 2 | `^` | Bitwise XOR |
| 1 | `\|` | Bitwise OR |

This follows C-style operator precedence. Parentheses can override precedence:

```
dir = (last_dir + 1) % 4 + 1
tmp = ((last_dir + 1) % 4) + 1
```

### Comparison operators

Used in `if` and `while` conditions: `==`, `!=`, `>`, `<`, `>=`, `<=`.

## Control Flow

### if / else

```
if carrying() { become start_return }

if dx > 0 {
    move(W)
    become return_home
} else {
    move(E)
    become return_home
}

if dir := sense(FOOD) {
    move(dir)
    become try_pickup
}
```

Truthiness shorthand: `if expr { ... }` is equivalent to `if expr != 0 { ... }`.

### while

```
tmp = 0
while tmp < 4 {
    if probe(dir) != WALL {
        move(dir)
        become search
    }
    tmp += 1
    dir = dir % 4 + 1
}
```

### loop / break / continue

```
loop {
    scratch = probe(dir)
    if scratch != WALL { break }
    dir += 1
}
```

### match

```
match probe(HERE) {
    case FOOD { become try_pickup }
    case NEST { become drop_food }
    default   { become search }
}
```

## Inline Assembly

### Block form

For multi-instruction sequences inside efuncs. Tokens are resolved against
parameter bindings and register aliases:

```
asm { SENSE target result }
asm { MOVE direction }
```

### String form

Escape hatch for raw antssembly instructions:

```
asm("NOP")
asm("HALT")
```

## Dead Code Elimination

The compiler performs two levels of DCE:

### Extern register DCE (AST level)

When inlining library functions, the compiler checks whether each statement
references unbound extern registers. Statements that reference unbound externs
are silently dropped. This means a library can include coordinate-tracking code
in `move()` that is automatically removed if the user does not bind `dx`/`dy`.

### Antssembly DCE (post-compilation)

After generating antssembly, the compiler removes:

- **Dead instructions:** Instructions after an unconditional `JMP` that are not
  jump targets.
- **Duplicate labels:** Consecutive identical labels.
- **No-op SETs:** `SET rX rX` instructions where source equals destination.

## Auto-generated Code

### Coordinate Tracking

The standard library's `move()` function includes conditional updates to `dx`/`dy`
based on `last_dir`. If the user binds these extern registers, coordinate tracking
is active. If not, the tracking code is eliminated by DCE.

### Heatmap Tags

States are automatically assigned heatmap tag indices (up to 8). The compiler
emits `.tag` directives and `TAG` instructions at state entry.

## Standard Library (`lib/ant/`)

The standard library (`package ant`) provides all built-in operations. Import it
with `import "../lib/ant"`. The library is split across multiple files in the
`lib/ant/` directory: `constants.sw`, `sensing.sw`, and `actions.sw`.

### Docstrings

Comments immediately above an `export func` or `export const` serve as
documentation (Go-style). These are shown in hover tooltips by the LSP:

```
// Returns direction (N=1, E=2, S=3, W=4) to nearest cell of type, or 0.
export func sense(target) -> volatile result stable(target == WALL || target == NEST) {
    asm { SENSE target result }
}
```

### Constants

#### Directions

| Name | Value | Description |
|---|---|---|
| `N`, `NORTH` | 1 | North |
| `E`, `EAST` | 2 | East |
| `S`, `SOUTH` | 3 | South |
| `W`, `WEST` | 4 | West |
| `HERE` | 0 | Current cell |
| `RANDOM` | 5 | Random direction |

#### Cell Types

| Name | Value | Description |
|---|---|---|
| `EMPTY` | 0 | Empty cell |
| `WALL` | 1 | Wall |
| `FOOD` | 2 | Food source |
| `NEST` | 3 | Ant nest |

#### Pheromone Channels

| Name | Value | Description |
|---|---|---|
| `CH_RED` | 0 | Red channel |
| `CH_GREEN` | 1 | Green channel |
| `CH_BLUE` | 2 | Blue channel |
| `CH_YELLOW` | 3 | Yellow channel |

### Extern Registers

The library declares three extern registers: `dx`, `dy`, `last_dir`. Bind them
in your register block to enable coordinate tracking:

```
register (
    x(ant.dx) = 0
    y(ant.dy) = 0
    heading(ant.last_dir) = id() % 4 + 1
)
```

### Sensing Functions

| Function | Returns | Volatility |
|---|---|---|
| `sense(target)` | Direction to nearest cell of type (1-4), or 0 | volatile, stable when `target == WALL \|\| target == NEST` |
| `probe(direction)` | Cell type: EMPTY(0), WALL(1), FOOD(2), NEST(3) | volatile, stable when `result == WALL \|\| result == NEST` |
| `smell(channel)` | Direction of strongest pheromone (1-4), or 0 | volatile |
| `sniff(channel, direction)` | Pheromone intensity (0-255) | volatile |
| `carrying()` | 1 if carrying food, 0 otherwise | stable |
| `id()` | Ant's unique ID (0-199) | stable |
| `rand(max)` | Random integer in [0, max) | stable |
| `rand_range(lo, hi)` | Random integer in [lo, hi) | stable |

Note: `rand()` can be called with two arguments (`rand(1, 5)`) as a shorthand
for `rand_range(1, 5)`. The compiler automatically dispatches to `rand_range`.

### Action Functions

| Function | Description |
|---|---|
| `move(direction)` | Move in direction. Consumes a tick. |
| `pickup()` | Pick up food at current cell. Consumes a tick. |
| `drop()` | Drop carried food. Consumes a tick. |

### Instant Functions

| Function | Description |
|---|---|
| `mark(channel, intensity)` | Mark pheromone (additive, capped at 255). |
| `set_tag(tag)` | Override the heatmap tag mid-state. |

## Bool Flags

Pack up to 15 boolean flags into a single register using bitfield operations:

```
bool visited, has_trail

visited = 1
if visited { become skip }
visited = 0
```

Bools are stored as individual bits in a shared flags register. They can be used
in conditions and assignments but not in arithmetic expressions.

## CLI

The compiler is invoked via `uv run python -m swarm` with subcommands:

```
uv run python -m swarm compile program.sw              # compile to stdout
uv run python -m swarm compile program.sw -o out.ant   # compile to file
uv run python -m swarm compile program.sw --copy       # compile to clipboard
uv run python -m swarm check program.sw                # lint
uv run python -m swarm fmt program.sw                  # format to stdout
uv run python -m swarm fmt program.sw --in-place       # format in place
uv run python -m swarm stats program.sw                # print program stats
uv run python -m swarm lsp                             # start LSP server
uv run python -m swarm antssembly file.ant             # preprocess .ant file
```

The `compile` subcommand is the default -- bare `uv run python -m swarm program.sw`
compiles directly.

### Linter checks (`check`)

- Unused registers
- Undeclared identifiers
- Unreachable states (not targeted by any transition)
- States with no outgoing transitions
- Unwired behavior exits
- Stale reads (volatile-derived values used after an action)

### Formatter (`fmt`)

Re-indents with 4 spaces per nesting level, normalizes blank lines between
top-level blocks, strips trailing whitespace.

### Stats (`stats`)

Reports source line counts, register usage, state/behavior/function counts,
and compiled output metrics (instructions, labels, directives).

### Antssembly preprocessor (`antssembly`)

Preprocesses raw `.ant` files with `#include`, `#define`, `#ifdef`/`#ifndef`/`#endif`
directives. Supports `--analyze` for static analysis, `--copy` for clipboard output,
and `--strip` to remove comments.

## Complete Example

```
package main

import "../lib/ant"
using ant

const RED_START = 200
const RED_DECAY = 3
const GREEN_START = 255

register (
    dir,
    mark_str = GREEN_START,
    x(ant.dx) = 0,
    y(ant.dy) = 0,
    heading(ant.last_dir) = id() % 4 + 1,
    tmp
)

init { become search }

state search {
    if carrying() { become start_return }
    if probe(HERE) == FOOD { become try_pickup }

    if mark_str {
        mark(CH_GREEN, mark_str)
        mark_str -= 1
    }

    if dir := sense(FOOD) {
        move(dir)
        become try_pickup
    }

    if heading {
        if probe(heading) != WALL {
            move(heading)
            become search
        }
    }

    dir = rand(1, 5)
    if probe(dir) != WALL {
        move(dir)
        become search
    }

    move(RANDOM)
    become search
}

state try_pickup {
    if probe(HERE) != FOOD { become search }
    pickup()
    become check_carry
}

state check_carry {
    if carrying() { become start_return }
    become search
}

state start_return {
    mark_str = RED_START
    become return_home
}

state return_home {
    if dir := sense(NEST) {
        mark(CH_RED, mark_str)
        move(dir)
        become do_drop
    }

    mark(CH_RED, mark_str)
    mark_str -= RED_DECAY
    if mark_str < 1 { mark_str = 1 }

    become beeline_home
}

state do_drop {
    drop()
    become reset_coords
}

state reset_coords {
    x = 0
    y = 0
    mark_str = GREEN_START
    become search
}

state beeline_home {
    if x {
        if x > 0 {
            if probe(W) != WALL {
                move(W)
                become return_home
            }
        } else {
            if probe(E) != WALL {
                move(E)
                become return_home
            }
        }
    }

    if y {
        if y > 0 {
            if probe(N) != WALL {
                move(N)
                become return_home
            }
        } else {
            if probe(S) != WALL {
                move(S)
                become return_home
            }
        }
    }

    if dir := smell(CH_GREEN) {
        tmp = ((heading + 1) % 4) + 1
        if dir != tmp {
            move(dir)
            become return_home
        }
    }

    dir = rand(1, 5)
    move(dir)
    become return_home
}
```
