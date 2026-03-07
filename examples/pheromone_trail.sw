// pheromone_trail.sw -- Ants that communicate via pheromone trails.
//
// Demonstrates: mark() to lay pheromone, smell() to detect trails,
// pheromone decay on return path, and trail-following during search.
//
// Strategy:
//   Search phase  - follow CH_RED if detected, otherwise random walk.
//   Return phase  - lay CH_RED trail (decaying intensity) while heading home.
//   Other ants smell the CH_RED trail and follow it to food sources.

const RED_START = 200
const RED_DECAY = 5

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

    // Follow existing CH_RED trail toward food
    scratch = smell(CH_RED)
    if scratch != 0 {
        move(scratch)
        become search
    }

    // Momentum: keep moving same direction
    if last_dir != 0 {
        scratch = probe(last_dir)
        if scratch != WALL {
            move(last_dir)
            become search
        }
    }

    // Random fallback
    dir = rand(4)
    dir = dir + 1
    move(dir)
    become search
}

state try_pickup {
    pickup()
    become check_carry
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
    // Lay CH_RED trail on each step home
    mark(CH_RED, mark_str)
    mark_str = mark_str - RED_DECAY
    if mark_str < 1 { mark_str = 1 }

    scratch = sense(NEST)
    if scratch != 0 {
        move(scratch)
        become do_drop
    }

    // Beeline toward nest using dx/dy
    if dx > 0 {
        scratch = probe(W)
        if scratch != WALL {
            move(W)
            become return_home
        }
    }
    if dx < 0 {
        scratch = probe(E)
        if scratch != WALL {
            move(E)
            become return_home
        }
    }
    if dy > 0 {
        scratch = probe(N)
        if scratch != WALL {
            move(N)
            become return_home
        }
    }
    if dy < 0 {
        scratch = probe(S)
        if scratch != WALL {
            move(S)
            become return_home
        }
    }

    move(RANDOM)
    become return_home
}

state do_drop {
    drop()
    become after_drop
}

state after_drop {
    dx = 0
    dy = 0
    become search
}
