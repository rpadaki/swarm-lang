// wall_hugger.sw -- Ant that follows walls to explore mazes.
//
// Demonstrates: while loops, probe() in multiple directions,
// systematic direction rotation, and wall-following navigation.
//
// Strategy: always keep a wall to the right. At each step the ant
// tries to turn right first; if blocked, go straight; if that is
// also blocked, turn left; as a last resort, reverse. This traces
// the boundary of every reachable wall and systematically covers
// maze corridors.

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

func turn_right() {
    // Rotate direction clockwise: N->E->S->W->N  (1->2->3->4->1)
    dir = last_dir % 4
    dir = dir + 1
}

func turn_left() {
    // Rotate direction counter-clockwise: N->W->S->E->N  (1->4->3->2->1)
    dir = last_dir + 2
    dir = dir % 4
    dir = dir + 1
}

init {
    dx = 0
    dy = 0
    last_dir = id()
    last_dir = last_dir % 4
    last_dir = last_dir + 1
    become explore
}

state explore {
    if carrying() != 0 { become return_home }
    if probe(HERE) == FOOD { become try_pickup }

    // Right-hand wall following:
    // 1. Try turning right
    turn_right()
    scratch = probe(dir)
    if scratch != WALL {
        move(dir)
        become explore
    }

    // 2. Try going straight
    scratch = probe(last_dir)
    if scratch != WALL {
        move(last_dir)
        become explore
    }

    // 3. Try turning left
    turn_left()
    scratch = probe(dir)
    if scratch != WALL {
        move(dir)
        become explore
    }

    // 4. Reverse (dead end)
    dir = last_dir + 1
    dir = dir % 4
    dir = dir + 1
    scratch = probe(dir)
    if scratch != WALL {
        move(dir)
        become explore
    }

    // Completely boxed in
    move(RANDOM)
    become explore
}

state try_pickup {
    pickup()
    become check_carry
}

state check_carry {
    if carrying() != 0 { become return_home }
    become explore
}

state return_home {
    mark(CH_RED, 100)

    scratch = sense(NEST)
    if scratch != 0 {
        move(scratch)
        become do_drop
    }

    // Beeline home using coordinates
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
    become explore
}
