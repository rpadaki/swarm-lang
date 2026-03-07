// actions.sw defines functions that mutate the world or the ant's state.
// Action functions (move, pickup, drop) consume the ant's tick; only one
// action may execute per tick. Non-action functions (mark, set_tag) are
// free and can be called any number of times within a tick.
package ant

// dx tracks the ant's horizontal displacement from its starting cell.
// Incremented on east moves, decremented on west moves.
// Approximate — wall collisions are not detected.
// Bind via register ( myname(ant.dx) ); DCE'd if unbound.
extern register dx

// dy tracks the ant's vertical displacement from its starting cell.
// Decremented on north moves, incremented on south moves.
// Approximate — wall collisions are not detected.
// Bind via register ( myname(ant.dy) ); DCE'd if unbound.
extern register dy

// last_dir stores the direction of the ant's most recent move (N=1..W=4).
// Bind via register ( myname(ant.last_dir) ); DCE'd if unbound.
extern register last_dir

// move moves the ant one cell in the given direction (N/E/S/W/RANDOM).
// Moving into a wall is a no-op but still consumes the tick. Consumes a tick.
// When extern registers are bound, updates dead reckoning state:
//   last_dir = direction, dx/dy adjusted by +/-1.
// Dead reckoning is approximate — wall collisions are not detected.
export action func move(direction) {
    asm { MOVE direction }
    last_dir = direction
    if direction == 1 { dy -= 1 }
    if direction == 3 { dy += 1 }
    if direction == 2 { dx += 1 }
    if direction == 4 { dx -= 1 }
}

// pickup picks up one food item from the ant's current cell.
// Each ant can carry at most one food. Picking up when no food is present
// or already carrying is a no-op but still consumes the tick. Consumes a tick.
export action func pickup() {
    asm { PICKUP }
}

// drop releases the ant's carried food onto the current cell.
// If the ant is on a nest cell, the food scores a point. Otherwise the
// food is placed on the ground for other ants to pick up. Consumes a tick.
export action func drop() {
    asm { DROP }
}

// mark deposits pheromone on the ant's current cell. The intensity is
// additive and capped at 255. All pheromones decay by 1 per global tick.
// Does not consume a tick.
export func mark(channel, intensity) {
    asm { MARK channel intensity }
}

// set_tag sets the ant's debug tag (0–7) for the heatmap viewer.
// Tags are purely cosmetic and useful for visualizing ant roles.
// Does not consume a tick.
export func set_tag(tag) {
    asm { TAG tag }
}
