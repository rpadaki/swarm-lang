// pheromone_trail.sw — Ants lay red pheromone trails back from food.
package main

import "../lib/ant"
using ant

const RED_START = 200
const RED_DECAY = 5

register (
    dir,
    mark_str,
    dx(ant.dx),
    dy(ant.dy),
    heading(ant.last_dir) = id() % 4 + 1
)

init {
    become search
}

state search {
    if carrying() { become start_return }
    if probe(HERE) == FOOD {
        pickup()
        become start_return
    }

    // Follow red trail toward food
    if dir := smell(CH_RED) {
        move(dir)
        become search
    }

    // Momentum: keep heading
    if probe(heading) != WALL {
        move(heading)
        become search
    }

    // Random fallback
    dir = rand(4) + 1
    move(dir)
    become search
}

state start_return {
    mark_str = RED_START
    become return_home
}

state return_home {
    mark(CH_RED, mark_str)
    mark_str -= RED_DECAY
    if mark_str < 1 { mark_str = 1 }

    if dir := sense(NEST) {
        move(dir)
        become do_drop
    }

    // Beeline via coordinates
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
    become reset
}

state reset {
    dx = 0
    dy = 0
    mark_str = 0
    become search
}
