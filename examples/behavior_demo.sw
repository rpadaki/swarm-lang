// behavior_demo.sw -- Demonstrates the behavior/exit system.
//
// Defines three reusable behaviors and wires them into concrete states:
//   - wander:       random walk with momentum, exits on food or trail
//   - beeline_home: navigate toward nest using dx/dy coordinates
//   - pickup_food:  attempt pickup, exit to a check state
//
// Shows how `self` maps to the instantiating state's own name,
// and how `exit` names are replaced with concrete wired targets.

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

// ── Behavior: random walk with two exit conditions ──

behavior wander {
    exit found_food
    exit found_trail

    if probe(HERE) == FOOD { become found_food }

    scratch = sense(FOOD)
    if scratch != 0 { become found_food }

    scratch = smell(CH_RED)
    if scratch != 0 { become found_trail }

    // Momentum walk
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

// ── Behavior: beeline toward nest using coordinate tracking ──

behavior beeline_home {
    exit arrived

    scratch = sense(NEST)
    if scratch != 0 { become arrived }

    if dx > 0 {
        scratch = probe(W)
        if scratch != WALL {
            move(W)
            become self
        }
    }
    if dx < 0 {
        scratch = probe(E)
        if scratch != WALL {
            move(E)
            become self
        }
    }
    if dy > 0 {
        scratch = probe(N)
        if scratch != WALL {
            move(N)
            become self
        }
    }
    if dy < 0 {
        scratch = probe(S)
        if scratch != WALL {
            move(S)
            become self
        }
    }

    move(RANDOM)
    become self
}

// ── Behavior: try to pick up food, exit based on result ──
// pickup() is an action that consumes the tick, so the check
// must happen in a separate state. This behavior just does
// the pickup and exits to a check target.

behavior pickup_food {
    exit check_result

    pickup()
    become check_result
}

// ── Init ──

init {
    dx = 0
    dy = 0
    last_dir = id()
    last_dir = last_dir % 4
    last_dir = last_dir + 1
    become exploring
}

// ── Concrete states wired from behaviors ──

state exploring = wander {
    found_food -> try_grab
    found_trail -> follow_trail
}

state follow_trail {
    scratch = smell(CH_RED)
    if scratch != 0 {
        move(scratch)
        become follow_trail
    }
    become exploring
}

state try_grab = pickup_food {
    check_result -> check_carry
}

state check_carry {
    if carrying() != 0 { become heading_home }
    become exploring
}

state heading_home {
    mark(CH_RED, 200)
    become navigate
}

state navigate = beeline_home {
    arrived -> do_drop
}

state do_drop {
    drop()
    become after_drop
}

state after_drop {
    dx = 0
    dy = 0
    become exploring
}
