// Package ant provides the standard library for the SWARM ant colony challenge.
// It wraps all antssembly instructions as typed functions and exposes the
// game's direction, cell-type, and pheromone-channel constants.
package ant

// ── Directions ──────────────────────────────────────────────

// N is the north direction (up on the grid).
export const N = 1

// NORTH is an alias for N.
export const NORTH = 1

// E is the east direction (right on the grid).
export const E = 2

// EAST is an alias for E.
export const EAST = 2

// S is the south direction (down on the grid).
export const S = 3

// SOUTH is an alias for S.
export const SOUTH = 3

// W is the west direction (left on the grid).
export const W = 4

// WEST is an alias for W.
export const WEST = 4

// HERE refers to the ant's current cell (direction 0).
export const HERE = 0

// RANDOM selects a uniformly random cardinal direction each time it is used.
export const RANDOM = 5

// ── Cell types ──────────────────────────────────────────────

// EMPTY is the cell type for an unoccupied, passable cell.
export const EMPTY = 0

// WALL is the cell type for an impassable wall cell.
export const WALL = 1

// FOOD is the cell type for a cell containing food.
export const FOOD = 2

// NEST is the cell type for a nest cell. Dropping food here scores a point.
export const NEST = 3

// ── Pheromone channels ──────────────────────────────────────

// CH_RED is pheromone channel 0 (red).
export const CH_RED = 0

// CH_BLUE is pheromone channel 1 (blue).
export const CH_BLUE = 1

// CH_GREEN is pheromone channel 2 (green).
export const CH_GREEN = 2

// CH_YELLOW is pheromone channel 3 (yellow).
export const CH_YELLOW = 3
