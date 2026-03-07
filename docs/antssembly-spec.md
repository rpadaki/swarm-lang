# Antssembly Specification

The assembly language for the SWARM Ant Colony Optimization Challenge.

## Overview

Antssembly is a simple assembly language for programming ant brains. The program
counter persists across ticks — each ant's brain is a continuous loop, not
restarted each tick. Each tick runs until an action instruction (MOVE/PICKUP/DROP)
or the 64-operation limit, then the next ant goes.

## Registers

8 general-purpose registers: `r0`–`r7`. Signed 32-bit integers, initialized to 0.
Overflow wraps (32-bit signed).

## Directives

Directives are preprocessor instructions, not runtime operations.

| Directive | Description |
|---|---|
| `.alias name reg` | Name a register (e.g., `.alias dir r1`) |
| `.const name value` | Named constant (e.g., `.const FOOD CH_RED`) |
| `.tag index name` | Name a tag index 0–7 for the viewer (also creates a constant) |

`.tag` names double as constants: after `.tag 0 forager`, you can write `TAG forager` instead of `TAG 0`.

## Labels

Labels are identifiers followed by a colon. They define jump targets.

```
search:
  SENSE FOOD dir
  JEQ dir 0 wander
  MOVE dir
wander:
  MOVE RANDOM
```

## Entrypoint

If a `main:` label exists and isn't the first instruction, a `JMP main` is
automatically prepended.

## Comments

Everything after a semicolon (`;`) is a comment.

```
SENSE FOOD r1   ; scan for food
```

## Instructions

### Sensing

All sensing ops take an optional destination register (defaults to `r0`).

| Instruction | Description |
|---|---|
| `SENSE <target> [reg]` | Scan 4 adjacent cells for target. Returns direction (N=1, E=2, S=3, W=4) or 0 if none. Ties broken randomly. Targets: `FOOD`, `WALL`, `NEST`, `ANT`, `EMPTY`. |
| `SMELL <ch> [reg]` | Direction of strongest pheromone on channel. Ties broken randomly. Returns 0 if none. |
| `SNIFF <ch> <dir> [reg]` | Exact pheromone intensity (0–255) at direction on channel. Direction can be `HERE`, `N`, `E`, `S`, `W`, `RANDOM`, or a register. |
| `PROBE <dir> [reg]` | Cell type at direction. Returns: 0=EMPTY, 1=WALL, 2=FOOD, 3=NEST. |
| `CARRYING [reg]` | 1 if holding food, 0 otherwise. |
| `ID [reg]` | Ant's unique index (0–199). |

### Actions

Actions consume the ant's tick. Only one action per tick.

| Instruction | Description |
|---|---|
| `MOVE <dir>` | Move in direction: `N`/`E`/`S`/`W`, `RANDOM`, or a register. Moving into a wall is a no-op (tick still consumed). |
| `PICKUP` | Pick up 1 food from current cell. Each ant carries at most 1 food. |
| `DROP` | Drop carried food. Scores a point if at the nest. |

### Pheromones

| Instruction | Description |
|---|---|
| `MARK <ch> <amount>` | Add pheromone to current cell. Additive, capped at 255. Amount can be a register or literal. |

Channels: `CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW`.

### Arithmetic

All arithmetic instructions modify the first operand in place. The second operand
can be a register or literal.

| Instruction | Description |
|---|---|
| `SET r val` | Set register to value |
| `ADD r val` | r += val |
| `SUB r val` | r -= val |
| `MUL r val` | r *= val |
| `DIV r val` | r /= val (truncates toward zero, no-op if val=0) |
| `MOD r val` | r %= val (always non-negative, no-op if val=0) |
| `AND r val` | r &= val |
| `OR r val` | r \|= val |
| `XOR r val` | r ^= val |
| `LSHIFT r val` | r <<= val |
| `RSHIFT r val` | r >>= val (arithmetic, sign-preserving) |
| `RANDOM r max` | r = random integer in [0, max) |

### Control Flow

| Instruction | Description |
|---|---|
| `JMP <label>` | Unconditional jump |
| `JMP <reg>` | Indirect jump (jump to address in register) |
| `CALL <reg> <label>` | Save return address in reg, jump to label |
| `JEQ a b <label>` | Jump if a == b |
| `JNE a b <label>` | Jump if a != b |
| `JGT a b <label>` | Jump if a > b |
| `JLT a b <label>` | Jump if a < b |

Operands `a` and `b` can be registers or literals.

Function call pattern:
```
CALL r7 my_func     ; save return addr, jump
; ...returns here...

my_func:
  ; do work
  JMP r7             ; return to caller
```

### Tags

| Instruction | Description |
|---|---|
| `TAG <value>` | Set ant's tag to 0–7. Zero cost (doesn't count toward 64-op limit). |

Tags are for debugging — toggle tag heatmaps in the viewer to see where each
role's ants have walked.

## Constants

### Directions
| Name | Value |
|---|---|
| `N` / `NORTH` | 1 |
| `E` / `EAST` | 2 |
| `S` / `SOUTH` | 3 |
| `W` / `WEST` | 4 |
| `RANDOM` | Random cardinal direction (re-rolled each use) |
| `HERE` | Current cell |

### Cell Types (returned by PROBE)
| Name | Value |
|---|---|
| `EMPTY` | 0 |
| `WALL` | 1 |
| `FOOD` | 2 |
| `NEST` | 3 |

### Sense Targets (used by SENSE)
`FOOD`, `WALL`, `NEST`, `ANT`, `EMPTY`

### Pheromone Channels
`CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW`

## Execution Model

1. Each tick, every ant executes instructions until an action or the 64-op limit.
2. After all 200 ants act, pheromones decay by 1 on all channels on all cells.
3. Multiple ants can share a cell (no collisions).
4. Moving into a wall consumes the tick but the ant doesn't move.
5. PICKUP on a cell with no food is a no-op (tick consumed).
6. DROP at the nest scores a point. DROP elsewhere places food on the ground.
