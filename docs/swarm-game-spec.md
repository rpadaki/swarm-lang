# SWARM — Ant Colony Optimization Challenge

## Game Overview

200 ants share one program ("brain") on a 128x128 grid. Find food, bring it to
the nest. Communicate only through pheromone trails. Score is averaged across
120 maps drawn from 12 procedural generators.

## The Grid

| Cell Type | Description |
|---|---|
| EMPTY | Passable, no contents |
| WALL | Impassable |
| FOOD | 1–8 units per cell |
| NEST | Delivery point (scores when food dropped here) |

Directions: N (1), E (2), S (3), W (4). RANDOM = random cardinal direction.

## Ants

- 200 ants, all running the same program
- Each ant has 8 registers (r0–r7), a program counter, and a carry slot (0 or 1 food)
- Multiple ants can share a cell (no collisions)
- Each ant carries at most 1 food unit

## Tick Model

Each game tick:
1. All 200 ants execute in sequence
2. Each ant runs instructions until an action (MOVE/PICKUP/DROP) or 64-op limit
3. After all ants have acted, pheromones decay by 1 on every channel on every cell

## Pheromones

4 independent channels: CH_RED, CH_BLUE, CH_GREEN, CH_YELLOW.

- Intensity per cell per channel: 0–255
- MARK is additive, capped at 255
- Decay: -1 per tick per channel per cell (floors at 0)
- Pheromones are the **only** communication mechanism between ants
- SMELL returns the direction of the strongest adjacent pheromone (ties broken randomly)
- SNIFF reads the exact intensity at a specific direction

## Scoring

- Each map: `food_delivered / total_food_available`
- Final score: `mean(ratios across 120 maps) * 1000`
- Score range: 0–1000
- Deterministic: same code always produces the same score

## Map Types

120 maps drawn from 12 procedural generators (10 maps each), seeded deterministically.

| Type | Description |
|---|---|
| **open** | No internal walls. Random food clusters scattered around the nest. |
| **maze** | Wide-corridor maze. 2-wide passages, 2-wide walls. |
| **spiral** | Concentric wavy ring walls with wide random gaps. |
| **field** | Nearly open, a few lazy curvy walls. |
| **bridge** | Vertical wall splits the map with 2–4 narrow crossings. All food on the far side from the nest. |
| **gauntlet** | Nest far left, food far right. Staggered vertical walls with gaps. |
| **pockets** | Circular walled cells with narrow entrances and food inside. |
| **fortress** | Nest cornered behind wavy concentric walls with gates. Food deep inside. |
| **islands** | Rooms separated by walls with one doorway between adjacent rooms. |
| **chambers** | Rooms carved in rock connected by narrow corridors. |
| **prairie** | Food everywhere at varying density, no blobs. |
| **brush** | Dense random wall clutter throughout. Food in medium clusters. |

## Strategy Considerations

- **Exploration**: Ants start at the nest and must find food. Random walk is slow; momentum, outward bias, and wall-following help coverage.
- **Trail marking**: Mark pheromone on the return trip (near food = high intensity, decaying toward nest) so other ants can follow the gradient to food.
- **Homing**: Dead-reckoning (tracking dx/dy from nest) enables beeline navigation. Pheromone trails from outbound ants provide a fallback.
- **Role specialization**: `ID` + `MOD` can assign ants to different roles (e.g., scouts vs. foragers) or fan them in different initial directions.
- **Map adaptation**: Different map types reward different strategies. Open maps favor fast spreading; mazes need wall-following; bridge maps need bottleneck navigation.
