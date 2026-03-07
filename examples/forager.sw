import "libant"

// v7: Nest gradient + wall-following + anti-oscillation
//
// Key insight: mark_str does double duty:
//   Search: green step counter (255 at nest, decrements each step)
//   Return: red intensity (200 near food, decrements each step)
// Green gradient encodes shortest-path distance from nest through corridors.
// Returning ants follow green uphill toward nest.

const RED_START = 200
const RED_DECAY = 3
const GREEN_START = 255

register dir, mark_str, dx, dy, next_st, last_dir, tmp

init {
    dx = 0
    dy = 0
    last_dir = id() % 4
    last_dir = last_dir + 1
    mark_str = GREEN_START
    become search
}

// ─────────────────────── SEARCH ───────────────────────

state search {
    if carrying() { become start_return }
    if probe(HERE) == FOOD { become try_pickup }

    // Mark green gradient from nest (high near nest, low far away)
    if mark_str {
        mark(CH_GREEN, mark_str)
        mark_str = mark_str - 1
    }

    if dir := sense(FOOD) {
        move(dir)
        become try_pickup
    }

    // Foragers (75%) follow red; scouts (25%) explore
    tmp = id() % 4
    if tmp {
        if dir := smell(CH_RED) {
            move(dir)
            become search
        }
    }

    // Momentum + wall-following turns
    if last_dir {
        if probe(last_dir) != WALL {
            move(last_dir)
            become search
        }

        // Right turn
        dir = last_dir % 4
        dir = dir + 1
        if probe(dir) != WALL {
            move(dir)
            become search
        }

        // Left turn: (last_dir + 2) % 4 + 1
        dir = last_dir + 2
        dir = dir % 4
        dir = dir + 1
        if probe(dir) != WALL {
            move(dir)
            become search
        }
    }

    // Try 4 random directions (unrolled)
    dir = rand(1, 5)
    if probe(dir) != WALL {
        move(dir)
        become search
    }
    dir = dir % 4
    dir = dir + 1
    if probe(dir) != WALL {
        move(dir)
        become search
    }
    dir = dir % 4
    dir = dir + 1
    if probe(dir) != WALL {
        move(dir)
        become search
    }
    dir = dir % 4
    dir = dir + 1
    if probe(dir) != WALL {
        move(dir)
        become search
    }

    move(RANDOM)
    become search
}

// ─────────────────────── PICKUP ───────────────────────

state try_pickup {
    if probe(HERE) != FOOD { become search }
    pickup()
    become check_carry
}

state check_carry {
    if carrying() { become start_return }
    become search
}

// ─────────────────────── RETURN ───────────────────────

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
    mark_str = mark_str - RED_DECAY
    if mark_str < 1 { mark_str = 1 }

    become beeline_home
}

state do_drop {
    drop()
    become reset_coords
}

state reset_coords {
    dx = 0
    dy = 0
    mark_str = GREEN_START
    become search
}

// ─────────────────────── BEELINE ───────────────────────

state beeline_home {
    // Beeline via dx/dy
    if dx {
        if dx > 0 {
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

    if dy {
        if dy > 0 {
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

    // Follow green gradient toward nest (anti-oscillation: skip backward)
    if dir := smell(CH_GREEN) {
        tmp = ((last_dir + 1) % 4) + 1
        if dir != tmp {
            move(dir)
            become return_home
        }
    }

    // Try 4 random directions (unrolled)
    dir = rand(1, 5)
    if probe(dir) != WALL {
        move(dir)
        become return_home
    }
    dir = dir % 4
    dir = dir + 1
    if probe(dir) != WALL {
        move(dir)
        become return_home
    }
    dir = dir % 4
    dir = dir + 1
    if probe(dir) != WALL {
        move(dir)
        become return_home
    }
    dir = dir % 4
    dir = dir + 1
    if probe(dir) != WALL {
        move(dir)
        become return_home
    }

    move(RANDOM)
    become return_home
}
