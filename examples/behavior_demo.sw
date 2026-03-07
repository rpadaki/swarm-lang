// behavior_demo.sw — Reusable behaviors with exit wiring.
package main

import "../lib/ant"
using ant

register (
    dir,
    dx(ant.dx),
    dy(ant.dy),
    heading(ant.last_dir) = id() % 4 + 1
)

behavior wander {
    exit found_food

    if probe(HERE) == FOOD { become found_food }
    if dir := sense(FOOD) {
        move(dir)
        become found_food
    }

    if probe(heading) != WALL {
        move(heading)
        become self
    }

    dir = rand(4) + 1
    move(dir)
    become self
}

behavior beeline_home {
    exit arrived

    if dir := sense(NEST) { become arrived }

    if dx > 0 {
        if probe(W) != WALL {
            move(W)
            become self
        }
    }
    if dx < 0 {
        if probe(E) != WALL {
            move(E)
            become self
        }
    }
    if dy > 0 {
        if probe(N) != WALL {
            move(N)
            become self
        }
    }
    if dy < 0 {
        if probe(S) != WALL {
            move(S)
            become self
        }
    }

    move(RANDOM)
    become self
}

init {
    become exploring
}

state exploring = wander {
    found_food -> try_grab
}

state try_grab {
    pickup()
    become check_carry
}

state check_carry {
    if carrying() { become heading_home }
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
