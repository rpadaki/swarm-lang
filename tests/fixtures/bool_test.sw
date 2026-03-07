// Test: bool variables packed into a single register
// Frees up registers for other uses

register scratch, dir, mark_str, dx, dy, next_st, last_dir
bool has_target, going_home, seen_food

init {
    dx = 0
    dy = 0
    has_target = 0
    going_home = 0
    become search
}

state search {
    if going_home != 0 { become return_home }

    scratch = sense(FOOD)
    if scratch != 0 {
        has_target = 1
        move(scratch)
        become try_pickup
    }

    seen_food = carrying()

    move(RANDOM)
    become search
}

state try_pickup {
    pickup()
    become check
}

state check {
    if carrying() != 0 {
        going_home = 1
        has_target = 0
        become return_home
    }
    become search
}

state return_home {
    scratch = sense(NEST)
    if scratch != 0 {
        move(scratch)
        become do_drop
    }
    move(RANDOM)
    become return_home
}

state do_drop {
    going_home = 0
    drop()
    become search
}
