// sensing.sw defines read-only query functions that inspect the world
// without consuming a tick.
package ant

// sense scans the four adjacent cells for the given target type and returns
// the direction (N=1, E=2, S=3, W=4) of the nearest match, or 0 if none
// is found. Ties are broken randomly. Valid targets are FOOD, WALL, NEST,
// ANT, and EMPTY. The result is stable for WALL and NEST (they never change).
export func sense(target) -> volatile result stable(target == WALL || target == NEST) {
    asm { SENSE target result }
}

// probe inspects the cell at the given direction and returns its cell type:
// CELL_EMPTY (0), CELL_WALL (1), CELL_FOOD (2), or CELL_NEST (3). The
// result is stable when the cell is a wall or nest.
export func probe(direction) -> volatile result stable(result == CELL_WALL || result == CELL_NEST) {
    asm { PROBE direction result }
}

// smell returns the direction (N/E/S/W) of the strongest pheromone on the
// given channel among the four adjacent cells, or 0 if no pheromone is
// present. Ties are broken randomly.
export func smell(channel) -> volatile result {
    asm { SMELL channel result }
}

// sniff returns the exact pheromone intensity (0–255) on the given channel
// at the given direction. Use HERE to read the ant's own cell.
export func sniff(channel, direction) -> volatile result {
    asm { SNIFF channel direction result }
}

// carrying returns 1 if the ant is holding food, 0 otherwise.
// Each ant can carry at most one food item at a time.
export func carrying() -> result {
    asm { CARRYING result }
}

// id returns the ant's unique index in the range [0, 199].
// The value is constant for the lifetime of the ant.
export func id() -> result {
    asm { ID result }
}

// rand returns a uniformly random integer in the half-open range [0, max).
export func rand(max) -> result {
    asm { RANDOM result max }
}

// rand_range returns a uniformly random integer in [lo, hi).
export func rand_range(lo, hi) -> result {
    asm { SET r0 hi }
    asm { SUB r0 lo }
    asm { RANDOM result r0 }
    asm { ADD result lo }
}
