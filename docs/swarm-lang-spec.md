# Swarm Language Specification

A structured language for the SWARM Ant Colony Optimization Challenge.
Compiles to antssembly via `uv run python -m swarm <file.sw>`.

## Overview

Swarm Language is a state-machine-first language designed for writing ant brains.
Each ant runs the same program. Ants communicate only through pheromone trails
marked on the grid. The language compiles to antssembly (the challenge's assembly
format) with automatic coordinate tracking and state dispatch.

Key design principles:
- **No gotos.** State machines with `become` (instant) and `->` (post-action) transitions.
- **Auto-tagging.** States automatically get heatmap tags for debugging.
- **Reusable behaviors.** Abstract state templates with named exit points.
- **Minimal boilerplate.** Coord tracking and dispatch are auto-generated.

## Program Structure

A `.sw` file contains top-level declarations in any order:

```
const NAME = VALUE       // compile-time constant
register a, b, c, ...   // allocate named registers (max 8 total)
tag [N] name             // explicit heatmap tag (optional — states auto-tag)

behavior name { ... }    // reusable state template
state name { ... }       // concrete state
state name = beh { ... } // state instantiated from a behavior

func name() { ... }      // inline function (expanded at call sites)
init { ... }             // runs once at startup, before any state
```

## Registers

Ants have 8 general-purpose 32-bit signed registers (`r0`–`r7`).
Declare them with `register`:

```
register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp
```

This assigns `scratch=r0`, `dir=r1`, etc. in order. The names `dx`, `dy`,
and `last_dir` are special — the compiler uses them for automatic coordinate
tracking and direction bookkeeping.

## Constants

```
const GREEN_INT = 50
const RED_START = 200
```

Constants are inlined at compile time. They can be used anywhere a value is expected.

## States

States are the core construct. Each state is a named block of code:

```
state search {
    // ... body
}
```

### Auto-tagging

Every state automatically gets a heatmap tag (up to the 8-tag limit).
The compiler emits `TAG <index>` at the start of each state body.
No need for manual `tag` declarations or `set_tag()` at state entry.

### Transitions

There are two kinds of transitions:

**`become state`** — instant jump (no action consumed):
```
if carrying() != 0 { become return_home }
```

**`action() -> state`** — transition after an action (MOVE/PICKUP/DROP):
```
move(E) -> search          // move east, then go to search state
pickup() -> check_carry    // pick up food, then go to check_carry
drop() -> reset_coords     // drop food, then go to reset_coords
```

The `->` transitions go through the auto-generated `__post_move` dispatch,
which updates `dx`/`dy` coordinates based on `last_dir`.

## Behaviors

Behaviors are reusable state templates with abstract exit points:

```
behavior random_walk {
    exit found_food       // abstract — wired at instantiation
    exit found_trail

    scratch = sense(FOOD)
    if scratch != 0 { become found_food }

    scratch = smell(CH_RED)
    if scratch != 0 { become found_trail }

    // momentum walk
    if last_dir != 0 {
        scratch = probe(last_dir)
        if scratch != WALL {
            move(last_dir) -> self    // loop back to this state
        }
    }

    dir = rand(4)
    dir = dir + 1
    move(dir) -> self
}
```

Instantiate with concrete wiring:

```
state exploring = random_walk {
    found_food -> try_pickup
    found_trail -> follow_red
}
```

The behavior body is inlined into the state. All `exit` names are replaced
with their wired targets. `self` maps to the state's own name.

A behavior can have any number of exits. All exits must be wired.

## Init Block

Runs once when the ant spawns, before entering any state:

```
init {
    dx = 0
    dy = 0
    last_dir = id()
    last_dir = last_dir % 4
    last_dir = last_dir + 1
    become search
}
```

## Actions

Actions consume the ant's tick. Only one action per tick.

### move(direction) -> state

Move in a direction. Automatically sets `last_dir` to the direction value.

```
move(N) -> search       // move north
move(scratch) -> search // move in direction stored in scratch
move(RANDOM) -> search  // move randomly
move(last_dir) -> search // continue same direction
```

Directions: `N`/`NORTH` (1), `E`/`EAST` (2), `S`/`SOUTH` (3), `W`/`WEST` (4), `RANDOM`, `HERE`.

### pickup() -> state

Pick up food at the current cell:
```
pickup() -> check_carry
```

### drop() -> state

Drop carried food:
```
drop() -> reset_coords
```

## Non-action Statements

These don't consume a tick (up to 64 per tick before a forced action):

### mark(channel, intensity)

Mark pheromone (additive, capped at 255):
```
mark(CH_GREEN, 50)
mark(CH_RED, mark_str)
```

Channels: `CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW`.

### set_tag(name)

Override the heatmap tag mid-state (for debugging sub-states):
```
set_tag(stuck)     // reference a tag name or state name
```

### Assignment

```
scratch = 42              // literal
scratch = other_reg       // register copy
scratch = scratch + 1     // binary op (result goes to left operand's register)
scratch = sense(FOOD)     // sense function
```

Binary operators: `+`, `-`, `*`, `/`, `%`, `&`, `|`, `^`, `<<`, `>>`.

### Sense Functions

Read environmental information into a register:

| Function | Returns |
|---|---|
| `sense(FOOD)` | Direction to nearest food (1-4) or 0 |
| `sense(NEST)` | Direction to nest (1-4) or 0 |
| `probe(dir)` | Cell type at direction: EMPTY(0), WALL(1), FOOD(2), NEST(3) |
| `smell(channel)` | Direction of strongest pheromone (1-4) or 0 |
| `sniff(channel, dir)` | Pheromone intensity at direction (0-255) |
| `carrying()` | 1 if carrying food, 0 otherwise |
| `id()` | Ant's unique ID (0-199) |
| `rand(max)` | Random integer in [0, max) |

## Control Flow

### if / else

```
if scratch != WALL {
    move(dir) -> search
}

if dx > 0 {
    move(E) -> search
} else {
    move(W) -> search
}

if carrying() != 0 { become return_home }    // single-line peephole
```

Comparison operators: `==`, `!=`, `>`, `<`.

### while

```
tmp = 0
while tmp < 4 {
    scratch = probe(dir)
    if scratch != WALL {
        move(dir) -> search
    }
    tmp = tmp + 1
    scratch = dir % 4
    dir = scratch + 1
}
```

### loop / break / continue

```
loop {
    scratch = probe(dir)
    if scratch != WALL { break }
    dir = dir + 1
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

## Inline Functions

```
func mark_green() {
    mark(CH_GREEN, GREEN_INT)
}

state search {
    mark_green()    // body is inlined here
    move(E) -> search
}
```

Functions are purely syntactic — the body is pasted at each call site.
No arguments, no return values, no recursion.

## Raw Assembly

Escape hatch for antssembly instructions:

```
asm("NOP")
asm("HALT")
```

## Auto-generated Code

The compiler automatically generates:

### Coordinate Tracking (`__post_move`)

After every `move()`, updates `dx`/`dy` based on `last_dir`:
- N (1): dy -= 1
- E (2): dx += 1
- S (3): dy += 1
- W (4): dx -= 1

### State Dispatch

After coordinate update, dispatches to the target state via a jump table
indexed by the `next_st` register.

### Direction Bookkeeping

`move(dir)` automatically sets `last_dir` to the numeric direction value.
The compiler skips redundant `SET rX rX` when `move(last_dir)` is used.

## Built-in Names

| Name | Context | Value |
|---|---|---|
| `N`, `E`, `S`, `W` | direction | 1, 2, 3, 4 |
| `NORTH`, `EAST`, `SOUTH`, `WEST` | direction | 1, 2, 3, 4 |
| `HERE` | direction | current cell |
| `RANDOM` | direction | random |
| `EMPTY` | cell type | 0 |
| `WALL` | cell type | 1 |
| `FOOD` | cell type | 2 |
| `NEST` | cell type | 3 |
| `CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW` | channel | pheromone channels |
| `FOOD`, `NEST` | sense target | for `sense()` |

## Compilation

```
uv run python -m swarm program.sw              # stdout
uv run python -m swarm program.sw --copy        # clipboard (pbcopy)
uv run python -m swarm program.sw -o out.ant    # file output
```

## Complete Example

```
const GREEN_INT = 50
const RED_START = 200
const RED_DECAY = 3

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

init {
    dx = 0
    dy = 0
    last_dir = id()
    last_dir = last_dir % 4
    last_dir = last_dir + 1
    become search
}

state search {
    if carrying() != 0 { become start_return }
    if probe(HERE) == FOOD { become try_pickup }

    scratch = sense(FOOD)
    if scratch != 0 {
        mark(CH_GREEN, GREEN_INT)
        move(scratch) -> try_pickup
    }

    scratch = smell(CH_RED)
    if scratch != 0 {
        mark(CH_GREEN, GREEN_INT)
        move(scratch) -> search
    }

    // Momentum walk
    if last_dir != 0 {
        scratch = probe(last_dir)
        if scratch != WALL {
            mark(CH_GREEN, GREEN_INT)
            move(last_dir) -> search
        }
    }

    // Random fallback
    dir = rand(4)
    dir = dir + 1
    move(dir) -> search
}

state try_pickup {
    pickup() -> check_carry
}

state check_carry {
    if carrying() != 0 { become start_return }
    become search
}

state start_return {
    mark_str = RED_START
    become return_home
}

state return_home {
    scratch = sense(NEST)
    if scratch != 0 {
        mark(CH_RED, mark_str)
        move(scratch) -> do_drop
    }
    mark(CH_RED, mark_str)
    mark_str = mark_str - RED_DECAY
    if mark_str < 1 { mark_str = 1 }
    become beeline_home
}

state do_drop {
    drop() -> reset_coords
}

state reset_coords {
    dx = 0
    dy = 0
    become search
}

state beeline_home {
    if dx > 0 {
        scratch = probe(W)
        if scratch != WALL { move(W) -> return_home }
    }
    if dx < 0 {
        scratch = probe(E)
        if scratch != WALL { move(E) -> return_home }
    }
    scratch = smell(CH_GREEN)
    if scratch != 0 { move(scratch) -> return_home }
    move(RANDOM) -> return_home
}
```
