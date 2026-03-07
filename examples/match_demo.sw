// match_demo.sw -- Demonstrates match/case on probe results.
//
// The ant probes adjacent cells and uses match statements to decide
// what to do based on what it finds (FOOD, WALL, NEST, EMPTY).
//
// Strategy: probe the current cell and each cardinal direction,
// dispatching to different logic depending on cell contents.

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

init {
    dx = 0
    dy = 0
    last_dir = id()
    last_dir = last_dir % 4
    last_dir = last_dir + 1
    become scout
}

state scout {
    if carrying() != 0 { become go_home }

    // Check what is directly underfoot
    match probe(HERE) {
        case FOOD { become try_pickup }
        case NEST { become fan_out }
        default   { become scan_around }
    }
}

state fan_out {
    // At the nest: pick a direction and leave
    dir = rand(4)
    dir = dir + 1
    move(dir)
    become scout
}

state scan_around {
    // Probe in our current direction of travel
    scratch = probe(last_dir)

    match scratch {
        case FOOD {
            // Food ahead: move toward it
            move(last_dir)
            become scout
        }
        case WALL {
            // Wall ahead: try turning right (rotate direction)
            dir = last_dir % 4
            dir = dir + 1
            scratch = probe(dir)
            match scratch {
                case WALL {
                    // Right is also a wall, try random
                    move(RANDOM)
                    become scout
                }
                default {
                    move(dir)
                    become scout
                }
            }
        }
        default {
            // Empty or nest ahead: keep momentum
            move(last_dir)
            become scout
        }
    }
}

state try_pickup {
    pickup()
    become check_carry
}

state check_carry {
    if carrying() != 0 { become go_home }
    become scout
}

state go_home {
    // Probe toward nest and react
    scratch = sense(NEST)
    if scratch != 0 {
        move(scratch)
        become at_nest
    }

    // Beeline using coordinates
    if dx > 0 {
        scratch = probe(W)
        if scratch != WALL {
            move(W)
            become go_home
        }
    }
    if dx < 0 {
        scratch = probe(E)
        if scratch != WALL {
            move(E)
            become go_home
        }
    }

    move(RANDOM)
    become go_home
}

state at_nest {
    match probe(HERE) {
        case NEST {
            become do_drop
        }
        default {
            become go_home
        }
    }
}

state do_drop {
    drop()
    become after_drop
}

state after_drop {
    dx = 0
    dy = 0
    become scout
}
