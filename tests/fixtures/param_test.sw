// Test: parameterized behaviors
// beeline behavior takes register params so it can be reused
// with different register layouts

register scratch, dir, mark_str, dx, dy, next_st, last_dir, tmp

behavior beeline(s, px, py) {
    exit moved
    exit stuck

    if px != 0 {
        if px > 0 {
            s = probe(W)
            if s != WALL {
                move(W)
                become moved
            }
        } else {
            s = probe(E)
            if s != WALL {
                move(E)
                become moved
            }
        }
    }

    if py != 0 {
        if py > 0 {
            s = probe(N)
            if s != WALL {
                move(N)
                become moved
            }
        } else {
            s = probe(S)
            if s != WALL {
                move(S)
                become moved
            }
        }
    }

    become stuck
}

behavior find_open(s, d, counter) {
    exit moved
    exit blocked

    d = rand(4)
    d = d + 1
    counter = 0
    while counter < 4 {
        s = probe(d)
        if s != WALL {
            move(d)
            become moved
        }
        counter = counter + 1
        s = d % 4
        d = s + 1
    }
    become blocked
}

init {
    dx = 0
    dy = 0
    become searching
}

state searching {
    scratch = sense(FOOD)
    if scratch != 0 {
        move(scratch)
        become pickup
    }
    move(RANDOM)
    become searching
}

state pickup {
    pickup()
    become check
}

state check {
    if carrying() != 0 { become homing }
    become searching
}

// Wire beeline with our registers: scratch for s, dx for px, dy for py
state homing = beeline(scratch, dx, dy) {
    moved -> drop_it
    stuck -> wander_home
}

// Wire find_open with scratch, dir, tmp
state wander_home = find_open(scratch, dir, tmp) {
    moved -> drop_it
    blocked -> wander_home
}

state drop_it {
    scratch = sense(NEST)
    if scratch != 0 {
        move(scratch)
        become do_drop
    }
    become homing
}

state do_drop {
    drop()
    become reset
}

state reset {
    dx = 0
    dy = 0
    become searching
}
