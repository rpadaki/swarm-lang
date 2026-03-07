// minimal.sw — Simplest possible ant: random walk, grab food, return.
package main

import "../lib/ant"
using ant

register dir

init {
    become wander
}

state wander {
    if carrying() { become go_home }
    if probe(HERE) == CELL_FOOD {
        pickup()
        become go_home
    }
    move(RANDOM)
    become wander
}

state go_home {
    if dir := sense(NEST) {
        move(dir)
        become do_drop
    }
    move(RANDOM)
    become go_home
}

state do_drop {
    drop()
    become wander
}
