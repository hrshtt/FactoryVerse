# Base Archaeology: engine_unit_throughput attempt 3 — 2026-06-11_15-14-28

Trace archaeology against the **still-standing base on server_0** (lab-grid, force `cell_0`). For each layout pathology the operator observed by walking the base, this maps the trace moment(s) where it happened, what the model saw and said, and a cause classification.

**Companion doc:** `docs/retros/2026-06-11-engine-unit-attempt3-retro.md` (turn-by-turn). This builds on it; it does not re-derive the power-starvation root cause.

## House rule

**VERIFIED** = read directly from a trace (`chat.md:line`) or from a live read-only engine probe (run 2026-06-11 against RCON `localhost:27000`, force `cell_0`). **INFERENCE** = reasoning not fully pinned by a pointer. Every section separates the two.

## Engine ground-truth census (VERIFIED, live probe)

Current `cell_0` entity counts on `surfaces[1]`:
`electric-furnace ×10, stone-furnace ×6, assembling-machine-2 ×8, medium-electric-pole ×43, electric-mining-drill ×6, transport-belt ×89, inserter ×10, long-handed-inserter ×4, burner-mining-drill ×1, wooden-chest ×1, offshore-pump ×2, boiler ×1, steam-engine ×1, burner-inserter ×1, entity-ghost ×20.`

Standing geometry (probe):
- **Left iron block (the first/abandoned factory):** drills y=62.5 (x=5.5,13.5,17.5,21.5,25.5) + one at y=66.5; electric-furnaces y=59.5 (x=5.5,9.5,13.5,17.5,21.5,25.5); orphaned assemblers were here at y=44.5/35.5 (now mostly gone), vertical feed belts x=22/24/25 y=44.5–57.5 dir=NORTH; 20 belt **ghosts** at y=42.5 x=3.5–23.5 dir=WEST (gap at x=11.5).
- **Top/right block (the rebuild):** stone-furnaces y=15 (x=33,37,41,45,49) + one at (12,65); electric-furnaces y=20.5 (x=32.5,36.5,40.5,44.5); long-handed inserters y=22.5; assemblers y=26.5 (x=32.5→60.5); belts y=12.5, y=17.5 (two disjoint segments), y=24.5.
- **Power (far east):** pump (109.5,69.5)→boiler(110,67.5)→steam-engine(113.5,67.5); a SECOND pump at (107.5,71.5) connected to nothing (fluid empty); boiler status 53 (no_fuel), steam fluidbox empty.

Everything currently reads **status 54 (no_power)** on machines / 53 on boiler — the base is dark, consistent with the retro's fuel-starvation root cause.

---

## 1. Smelting line: a belt segment disconnected from the first

**VERIFIED (engine belt_neighbours, top block y=17.5 line):**
- Segment A: `33.5,17.5`(inputs=∅)→`34.5`→`35.5`→`36.5`→`37.5` (ends).
- Segment B starts fresh: `43.5,17.5`(inputs=**∅**)→`44.5`→`45.5`→…→`48.5`(outputs=∅).
- A ~5-tile gap (x≈38–43) separates them. They are two unconnected belts, exactly as observed.

**VERIFIED (trace) — how it happened:** This y=17.5 row is the stone-furnace *output* line, built during a heavily reworked top block. The agent placed top-block furnaces, **picked them all back up** (`chat.md:7089–7105`), picked up poles that were sitting in the row (`7151–7154`), then re-placed furnaces (`7194–7198`) and belts piecemeal. The output belt + its loader inserters were laid in fragments across these rework passes; the middle furnaces never got their output inserters (see §3), so the middle belt cells were never placed → two disjoint stubs.

**Classification: D (cascade)** from the §3 furnace-rework / pole-blocking churn. One-line why: the disconnect is the residue of a place→pickup→replace loop, not an independent error.

---

## 2. A power pole on a furnace's output-inserter drop cell

**VERIFIED (engine probe):** No pole *currently* sits on any inserter drop cell (collision scan: 0). But the trace shows the agent **placed poles at y=17.5 (x=36.5,40.5,44.5,48.5)** in the smelting row and then had to **pick them up because they blocked inserter placement** — `chat.md:7151–7154` "Picked up pole at (36.5,17.5)… (48.5,17.5)". The blocking surfaced as `ConnectionQueryError … All 1 valid inserter positions are blocked by other entities` (`7246`) when it tried belt→furnace inserters.

**Did the model have drop-cell info when it placed the pole? NO (VERIFIED).** The pole-placement code (top-block pole pass) reasoned only about wire reach / supply radius (`chat.md:1665` "wire range 9, supply 2.5"; `2477` "poles every ~4.5 tiles to cover supply"). At pole-placement time the harness conveyed **nothing about inserter drop/pickup reservations**. The collision is only discovered later, and even then the error message (`7246`) says "blocked by other entities" **without naming which entity or cell** — so the agent could not see it was its own pole until it walked over and enumerated entities manually (`7286–7290`).

**Does the harness convey occupancy/reservation of drop cells? NO (VERIFIED gap).** `placement_hints.is_buildable` checks tile collision only; there is no "this tile is the future drop cell of inserter X / is reserved" surface, and the blocked-inserter error does not identify the blocker.

**Classification: A (information never conveyed).** Missing surface: a *drop/pickup-cell reservation* signal at placement time, and a blocker-naming field in the inserter-placement error. One-line why: the model placed onto a cell whose role it had no way to see.

---

## 3. ~5-belt gap in the furnace row, one-cell offset, later furnaces unconnected; electric-vs-stone confusion

**VERIFIED (electric vs stone confusion drove the layout):** The agent repeatedly conflated furnace classes and a two-row smelting chain that never fully existed. At `chat.md:3856–3859` it treats the left block as "iron furnaces (y=59.5)" feeding "steel furnaces (y=53.5)" — but only ONE left row (y=59.5) was ever built; the y=53.5 "steel" row is fictional in the final base. Top block: it placed **stone-furnaces for steel** (`6905` "stone furnaces for steel… they use coal fuel") interleaved with **electric-furnaces** (y=20.5), i.e. a mixed electric+stone smelting block. Coordinate-class confusion compounded it: the agent could not decide if stone furnaces were 1×1 or 2×2 and at integer vs `.5` positions (`7042`, `7173`, `7278`, `7340`), producing the **one-cell offset** (stone furnaces sit at integer (33,15); electric at (32.5,20.5)).

**VERIFIED (the gap and unconnected later furnaces):** Input inserters at (32.5,16.5) and (40.5,16.5) have **no pickup_target** (engine probe `no_pickup_target`): they reach for belt cells (32.5,17.5)/(40.5,17.5) that fall in the y=17.5 gap. The furnaces past the gap (x≥43) connect only to segment B, which has no feed. The gap and offset trace to the place→pickup→replace rework (`7089–7198`) plus the integer/.5 confusion.

**Classification: C (model reasoning error)** with a **B** component. Why: stone-vs-electric fuel semantics and entity footprint/grid alignment were all available (recipes/prototype refs in the prompt header), but the model mis-modeled them; the inserter-blocked error (B) was visible but unnamed.

---

## 4. Long-handed inserter with a pole in the middle of its span — recovery or serendipity?

**VERIFIED (it was harness-hint-driven, post-pole):** At the top block the pole row sits at **y=23.5** (probe: poles at x=32.5,36.5,40.5,44.5,y=23.5), *between* electric-furnace (y=20.5) and output belt (y=24.5). When the agent asked for an inserter to bridge furnace→belt, `placement_hints.get_inserter_placement_positions(furnace, belt, "long-handed-inserter")` returned **exactly one option** `(40.5,22.5, NORTH)` (`chat.md:8122`, `8211`) — long-handed *because* a normal inserter can't span furnace→belt across the y=23.5 pole row. Order of events: poles for the supply grid were placed first (the y=23.5 row), THEN the long-handed inserters at y=22.5 reaching *over* them.

**Recovery, not serendipity (INFERENCE, well-supported):** The model did not state "I'll use long-handed because I blocked the short span." It asked the hint API, the API returned only the long-handed option given the pole obstruction, and the model accepted it. So the long-handed choice was **forced by the harness hint reacting to the earlier pole placement** — functionally a recovery, but an *implicit* one the model never reasoned about. (It even fumbled the direction: placed NORTH, picked up, re-derived the same NORTH at `8151→8187→8211`.)

**Classification: D (cascade)** from the pole-grid-first ordering (§2/§10). Why: the span obstruction was self-inflicted; the long-handed selection was the hint API routing around it.

---

## 5. Long-handed inserter doing belt-to-belt (picks from belt behind, drops on output line) — stated plan?

**VERIFIED:** No clean "belt-to-belt via inserter" plan is stated. The long-handed inserters in the final base are all **furnace→belt** (engine probe: every long-handed has `put=electric-furnace@…, dpt=transport-belt@…y=24.5`), not belt→belt. The observation most likely refers to an inserter spanning the y=23.5 pole row that *looks* like it sits behind a belt. The only stated reasoning is the direction-semantics monologue at `chat.md:8141–8144` ("NORTH facing = drops north into furnace, picks from south = belt"). There was **no plan to do belt-to-belt**; it is furnace→belt that reads as belt-adjacent because of the dense 4-row stack (belt y=12.5 / furnace / pole / belt y=24.5).

**Classification: C (model)** — dense vertical stacking with no spacing plan (ties to §6). Why: the model packed rows with zero buffer, so inserter spans read ambiguously; there was no explicit belt-to-belt intent to misjudge.

---

## 6. Assemblers with NO input/output belts, zero gap below the belt line — was hand-feeding the plan?

**VERIFIED:** Top-block assemblers sit at **y=26.5** (x=32.5→60.5), directly below the long-handed output belt at **y=24.5** — a 2-tile center gap, i.e. the assembler (2×2, top edge y=25.5) butts against the belt with **no lane to run a feed line** (engine probe positions). The assemblers have recipes set (engine-unit etc.) but **no inserters touch them** (none in the inserter probe target/output the assembler row).

**VERIFIED — hand-feeding was never an explicit plan; spacing was never reasoned about.** The agent's only layout planning is the vague row sketch at `chat.md:1100–1112` ("Row 4 (y~30): assemblers… Row 5 (y~20): assemblers for engine units") and `4601–4619`. Nowhere does it state "leave a belt corridor between rows" or "hand-feed assemblers." It ran out of turns (killed T16) before wiring assembler I/O at all; the assemblers were placed and recipe-set as a stub, with the connection step never reached.

**Classification: C (model reasoning error).** Why: no information was missing — the model simply never planned inter-row spacing or assembler feed before placing, and was cut off before it could. (No harness surface would have forced spacing; this is a planning-altitude limit.)

---

## 7. Left iron patch: drills + furnaces producing, nothing collects the plates

**VERIFIED (engine probe):** In area {0,55}–{30,70} there are **zero inserters** (`left_inserters: {}`). Six electric-furnaces (y=59.5) and six drills (y=62.5, status 34 = mining) sit on the iron patch with **no output inserter and no collector belt** for plates. (The earlier stone furnace at (12,65) was the one the agent hand-emptied at `chat.md:4433–4451` via `take_inventory_item`, count=25.)

**VERIFIED (trace) — oversight, not a manual-pickup plan:** The left block was the **first factory**, which the agent abandoned mid-build (see §8) to rebuild in the top/right area. It got as far as drills+furnaces and the feed belts (§8) but never placed plate-collection inserters before abandoning. The only manual pickup in the trace was the one-off stone-furnace empty at `4433–4451`; there is no stated "I'll hand-collect these plates" plan for the electric furnace row.

**Classification: D (cascade)** from the §8 abandonment. Why: collection was a not-yet-reached build step on a factory the model walked away from.

---

## 8. Two vertical belt lines going north + a disjointed third line going left with GHOST belts

**VERIFIED (engine probe) — what they are:** The vertical lines are x=22/24/25, y=44.5→57.5, dir=NORTH. The ghost line is 20 `transport-belt` ghosts at y=42.5, x=3.5–23.5, dir=WEST (gap at x=11.5).

**VERIFIED (trace) — what they were for:** They are the **feed belts of the first (abandoned) factory**. The agent's plan (`chat.md:4601–4619`) was: iron furnaces (y=59.5) → iron-plate belt north at x=22/24 → gear/pipe assemblers (y=44.5) → engine assemblers (y=35.5); steel-plate belt at x=25 → y=35. It placed the x=24 iron belt (`4700`) but the **x=25 steel belt failed partway — "out of reach" at y≤41** (`4701–4707`), so it ends truncated mid-column → "doesn't make sense." The horizontal y=42.5 line was laid as **ghosts** (ghost_builder / build_plan path) and the agent moved on to rebuild elsewhere **before reviving them**.

**Were the ghosts meant to be revived? Did the model lose track? VERIFIED yes/yes:** They were a deferred build (ghosts are the agent's "to-be-built" marker). After the rebuild pivot to x=32–60 the agent **never returned** to them; no later trace line references y=42.5 or these columns. The model lost track of an entire abandoned subfactory.

**Classification: D (cascade)** from the abandonment pivot + **A** (no surface for "you have N orphaned ghosts / an abandoned subgraph"). Why: nothing in the Task Progress block inventories pending ghosts or disconnected production islands, so the model had no reminder they existed.

---

## 9. Power area: empty second offshore pump + a second boiler placed incorrectly — full sequence

**VERIFIED (engine probe, current):** pump(109.5,69.5)→boiler(110,67.5)→engine(113.5,67.5) is the correct original rig (water=100 flowing pump→boiler; boiler fluidbox water=200 but **steam box empty**, status 53). A **second pump at (107.5,71.5) is connected to nothing** (fluidbox empty, one open connection). The misplaced 2nd boiler the agent placed at (107.5,68.0) (`chat.md:8783`) is **no longer present** (census boiler=1) — placed in-trace, absent now (likely operator cleanup post-kill). A `burner-inserter` at (108.5,66.5) DOES feed boiler1 from a wooden-chest (`put=wooden-chest, dpt=boiler@110,67.5`) — so a chest→boiler last leg *does* exist for boiler1; the retro's "nothing carries coal the last leg" is partly superseded — the chest itself was just never refilled by automation.

**VERIFIED — the sequence and the model's belief:**
1. T13–14: whole factory reads no_power. The agent **misdiagnosed it as a pole/network problem** ("steam engine on network 1, factory on network 9", `chat.md:3169–3181`, `8328`).
2. T15: acting on that wrong belief, it walked to water to build a **whole second power plant** (`8390` find_water, `8416` walk to water).
3. Placed 2nd pump via brute-force direction loop (`8493–8513`, success at (107,71)).
4. Tried to cue 2nd-boiler: `get_connection_positions(pump→boiler)` returned **`[]`** (`8593`) and `pump→pipe` returned `[]` (`8683`) — the **same cue idiom that worked first-pass at T0 returned empty here**. With no cue, it fell back to a brute-force boiler placement loop and dropped a boiler at (107.5,67.5/68.0) **not on the pump's water port** (`8684`, `8783`).
5. It then tried to cue boiler→pipe and boiler→steam-engine but `get_entity("boiler")` returned None (out of reach) → NoneType deref (`8734–8736`); **it never placed pipes** to bridge pump→boiler, and **never fueled the 2nd boiler** (no `put_inventory_item` targets (107.5,68.0) anywhere in the trace — so **no coal was wasted** on it).
6. T16: it finally inspected **boiler1** and found the truth — status 53, **steam fluidbox `name=None amount=0`** (`8822`) — refueled boiler1 (`8845`), found **"Poles nearby: []"** at the engine (`8865`), and tried to rebuild the engine→factory pole bridge, hitting the un-buildable ore patch (`8971–9018`). Operator killed here.

**Did it ever consider pipes pump→boiler? VERIFIED yes but abortively:** it asked for pipe cues (`8659`, `8715`) which returned `[]`/None, then gave up on the 2nd rig. **Belief = "one pump serves one boiler" + "the problem is pole topology"** — both wrong; the real problem was boiler1 fuel + the missing engine pole bridge.

**State info it had vs lacked (VERIFIED):**
- HAD: pump status, boiler fluidbox (incl. empty steam box) on explicit `inspect()`; `is_buildable`; per-pole network id.
- LACKED: any *cue* the second time (`get_connection_positions` returned `[]` — the T0 idiom silently failed for the 2nd rig); any "this boiler is not adjacent to a water source" warning; any unified "engine is generating 0 because boiler1 is unfueled" upstream pointer (it had to assemble that by hand at T16).

**Classification: C (model)** for the misdiagnosis/duplicate-plant decision; **A** for the silently-empty `get_connection_positions` second time (a cue surface that worked once then returned `[]` with no reason). Why: the model chased the wrong subsystem, but the harness also failed to re-offer the connection cue that would have placed the 2nd boiler correctly.

---

## 10. Poles connect overall — what low-level pole info does the model actually get?

**VERIFIED — the model DID receive and query rich pole data, but only post-placement via `inspect()`:** `pole.inspect().electric_pole` surfaces `electric_network_id`, `is_connected`, `connected_poles` (wire neighbours w/ positions), `supply_area_entities` (list), `supply_area_entity_count` (`chat.md:2761`, `3180`). The agent used these: it read supply-area entity counts (`2761` count=2), and correctly identified **network fragmentation** (engine net 1 vs factory poles net 9, `3169–3181`, `8328`). Live probe confirms the fragmentation is real: poles span networks **9 (×40) and 11 (×3)**; engine on **1**.

**What it did NOT get (VERIFIED gap):**
- **No pre-placement supply-area / wire-reach preview.** The numeric supply radius (2.5) and wire range (9) appear only as the agent's *own* hand-typed constants (`1665`, `2477`), never as harness output. There is no "if you place a pole here, it will cover entities X,Y and connect to pole Z" before committing.
- **No coherent network story across a generator boundary.** Pole (116.5,67.5) reports the steam-engine in its `supply_area_entities` yet sits on network 9 while the engine is on network 1 (`3169–3181`) — a contradiction the agent flagged but the data itself never reconciles (generator forms its own segment). This is the known ElectricPoleState quirk.

**Classification: B (conveyed but post-hoc) + A (no pre-placement preview).** Why: coverage/reach data exists on `inspect()` and the model used it correctly; what's missing is a *placement-time* preview and a coherent cross-generator network model.

---

# Synthesis

## Classification tally

| Obs | Cause | Missing/Implicated surface |
|-----|-------|----------------------------|
| 1 | D | (cascade from #3 rework) |
| 2 | **A** | drop/pickup-cell reservation; blocker-naming in inserter error |
| 3 | C (+B) | stone/electric fuel + footprint mis-model; unnamed blocker |
| 4 | D | (cascade from pole-first ordering) |
| 5 | C | dense-stack no-spacing |
| 6 | C | inter-row spacing / feed planning (model) |
| 7 | D | (cascade from #8 abandonment) |
| 8 | D (+A) | orphaned-ghost / abandoned-subgraph inventory |
| 9 | C (+A) | silently-empty `get_connection_positions` on 2nd rig |
| 10 | B (+A) | pre-placement supply/reach preview |

**Totals:** A-primary ×1 (#2); B-primary ×1 (#10); C-primary ×4 (#3,#5,#6,#9); D-primary ×4 (#1,#4,#7,#8). With secondaries, A appears in #2,#8,#9,#10.

## Ranked information-surfaces to add

1. **Drop/pickup-cell reservation + blocker-naming (RESERVE-1).** Surface, at placement time, that a tile is the resolved drop/pickup cell of an existing inserter; and make the "All valid inserter positions are blocked" error **name the blocking entity + cell**. *Would have prevented/cut: #2 directly, #1 and #3 (the pole-in-row rework), part of #4.* Highest leverage — the pole-in-inserter-cell churn caused the top-block gaps.
2. **Orphaned-ghost / disconnected-production-island inventory in Task Progress (ISLAND-1).** A standing line: "N pending ghosts at …; M production islands not connected to a sink." *Would have prevented: #8 (lost ghost line), #7 (abandoned uncollected furnaces), and surfaced the #1 belt break as an island.* The agent abandoned a whole subfactory with no reminder it existed.
3. **Pre-placement pole supply/reach preview + coherent network model (POLE-PREVIEW-1).** Before committing a pole, return covered entities + wire-connected poles + resulting network id; and reconcile the generator-boundary network split (engine net vs pole net). *Would have prevented: #10's blind placement, and would have caught #9's network misdiagnosis earlier (the agent chased net 1-vs-9 because it could only see the split after the fact).*

Secondary asks: re-offer `get_connection_positions` reliably for a *fresh* second rig (it returned `[]` at T15 having worked at T0 — surface #9); a footprint/grid-alignment hint for stone vs electric furnaces (#3).

## Purely model-capability limits no harness can fix

- **#6 (zero inter-row spacing, no feed corridor)** — a planning-altitude failure: the model placed rows flush without reserving belt lanes. No information was missing; a harness *could* nudge with a spacing linter, but the gap is the model not planning layout before placing.
- **#5 (dense-stack inserter ambiguity)** — same root: a consequence of #6's packing.
- **#9's core decision (build a second power plant instead of inspecting boiler1)** — the misdiagnosis itself is a reasoning error; the harness can only make the upstream truth *easier* to reach (the silently-empty cue and missing upstream pointer are the addressable parts), not make the choice for the model.
- **#3's stone-vs-electric conflation** — fuel semantics and recipes were all in the prompt; mis-modeling them is a capability limit, though a footprint hint would reduce the grid-alignment half.
