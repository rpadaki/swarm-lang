// wall_hugger.sw — Right-hand wall following for maze exploration.
package main

import "../lib/ant"
using ant

register (
    dir,
    dx(ant.dx),
    dy(ant.dy),
    heading(ant.last_dir) = id() % 4 + 1
)

func turn_right() {
    dir = heading % 4 + 1
}

func turn_left() {
    dir = (heading + 2) % 4 + 1
}

init {
    become explore
}

state explore {
    if carrying() { become return_home }
    if probe(HERE) == FOOD {
        pickup()
        become return_home
    }

    // Right-hand rule
    turn_right()
    if probe(dir) != WALL {
        move(dir)
        become explore
    }
    if probe(heading) != WALL {
        move(heading)
        become explore
    }
    turn_left()
    if probe(dir) != WALL {
        move(dir)
        become explore
    }

    // Dead end: reverse
    dir = (heading + 1) % 4 + 1
    move(dir)
    become explore
}

state return_home {
    mark(CH_RED, 100)

    if dir := sense(NEST) {
        move(dir)
        become do_drop
    }

    if dx > 0 {
        if probe(W) != WALL {
            move(W)
            become return_home
        }
    }
    if dx < 0 {
        if probe(E) != WALL {
            move(E)
            become return_home
        }
    }
    if dy > 0 {
        if probe(N) != WALL {
            move(N)
            become return_home
        }
    }
    if dy < 0 {
        if probe(S) != WALL {
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
