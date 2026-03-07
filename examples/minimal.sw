// minimal.sw -- Simplest possible ant program.
//
// Demonstrates: states, transitions (become), init block,
// carrying() check, pickup/drop actions, and random movement.
//
// Strategy: wander randomly until food is underfoot, pick it up,
//           wander randomly toward the nest, drop it, repeat.

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

init {
    dx = 0
    dy = 0
    become wander
}

state wander {
    if carrying() != 0 { become go_home }
    if probe(HERE) == FOOD { become grab }
    move(RANDOM)
    become wander
}

state grab {
    pickup()
    become got_food
}

state got_food {
    if carrying() != 0 { become go_home }
    become wander
}

state go_home {
    scratch = sense(NEST)
    if scratch != 0 {
        move(scratch)
        become do_drop
    }
    move(RANDOM)
    become go_home
}

state do_drop {
    drop()
    become reset
}

state reset {
    dx = 0
    dy = 0
    become wander
}
