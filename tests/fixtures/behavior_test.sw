// Test: behavior definitions with exit wiring

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

behavior search_for_food {
    exit found
    exit smelled_trail

    scratch = sense(FOOD)
    if scratch != 0 { become found }

    scratch = smell(CH_RED)
    if scratch != 0 { become smelled_trail }

    // Random walk
    dir = rand(4)
    dir = dir + 1
    move(dir)
    become self
}

init {
    dx = 0
    dy = 0
    become exploring
}

state exploring = search_for_food {
    found -> go_pickup
    smelled_trail -> exploring
}

state go_pickup {
    pickup()
    become check
}

state check {
    if carrying() != 0 { become go_home }
    become exploring
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
    become exploring
}
