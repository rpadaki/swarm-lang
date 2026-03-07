package ant

// libant — standard ant operations
//
// Provides constants, sensing, pheromone marking, and utility functions.

// ── Directions ──────────────────────────────────────────────

export const N = N
export const NORTH = N
export const E = E
export const EAST = E
export const S = S
export const SOUTH = S
export const W = W
export const WEST = W
export const HERE = HERE
export const RANDOM = RANDOM

// ── Cell types ──────────────────────────────────────────────

export const EMPTY = EMPTY
export const WALL = WALL
export const FOOD = FOOD
export const NEST = NEST

// ── Pheromone channels ──────────────────────────────────────

export const CH_RED = CH_RED
export const CH_BLUE = CH_BLUE
export const CH_GREEN = CH_GREEN
export const CH_YELLOW = CH_YELLOW

// ── Sensing ──────────────────────────────────────────────────

// Returns direction (N=1, E=2, S=3, W=4) to nearest cell of type, or 0.
export func sense(target) -> result {
    asm { SENSE target result }
}

// Returns cell type at direction: EMPTY (0), WALL (1), FOOD (2), NEST (3).
export func probe(direction) -> result {
    asm { PROBE direction result }
}

// Returns direction of strongest pheromone on channel, or 0.
export func smell(channel) -> result {
    asm { SMELL channel result }
}

// Returns pheromone intensity (0-255) on channel at direction.
export func sniff(channel, direction) -> result {
    asm { SNIFF channel direction result }
}

// Returns 1 if carrying food, 0 otherwise.
export func carrying() -> result {
    asm { CARRYING result }
}

// Returns ant's unique ID (0-199).
export func id() -> result {
    asm { ID result }
}

// Returns random integer in [0, max).
export func rand(max) -> result {
    asm { RANDOM result max }
}

// Returns random integer in [lo, hi).
export func rand_range(lo, hi) -> result {
    asm { SET r0 hi }
    asm { SUB r0 lo }
    asm { RANDOM result r0 }
    asm { ADD result lo }
}

// ── Actions (tick-consuming) ─────────────────────────────────

// Move in direction. Consumes a tick.
export action func move(direction) {
    asm { MOVE direction }
}

// Pick up food at current cell. Consumes a tick.
export action func pickup() {
    asm { PICKUP }
}

// Drop carried food at current cell. Consumes a tick.
export action func drop() {
    asm { DROP }
}

// ── Marking ──────────────────────────────────────────────────

// Add pheromone (additive, capped at 255). Does not consume a tick.
export func mark(channel, intensity) {
    asm { MARK channel intensity }
}

// Override heatmap tag mid-state. Does not consume a tick.
export func set_tag(tag) {
    asm { TAG tag }
}
