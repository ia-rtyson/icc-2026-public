# Alarm Flood line — SVG animation brief

Source of truth for everything below:

- `ignition/projects/icc-2026/ignition/script-python/exchange/alarmFlood/model/code.py` — tag list, units, ranges, normal-operation model, alarm setpoints
- `ignition/projects/icc-2026/ignition/script-python/exchange/alarmFlood/sim/code.py` — the phase machine and every fault curve

If a number here disagrees with those files, the files win.

---

## 1. What the process is

A five-station production line, ordered upstream → downstream:

```
 [Kitting] --conv--> [Mixing] --discharge--> [Forming] --conv--> [Cooking] --oven belt--> [Packaging] --> out
    bin                tank                   buffer              exit buffer             infeed buffer
```

Each station is an Ignition UDT instance under a line folder. There are 5 identical
lines; **only one is the fault target at a time** (default `Site1/Area1/Line1`).

Tag path shape:

```
[default]Exchange/Alarm Flood/<Site>/<Area>/<Line>/<Station>/<Tag>
e.g. [default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/MotorTorque
```

Lines: `Site1/Area1/Line1`, `Site1/Area1/Line2`, `Site1/Area2/Line3`, `Site1/Area2/Line4`, `Site1/Area2/Line5`.

**32 tags and 31 alarms per line.** Nothing is ever pinned at a constant during
normal operation — every analog is a slow sine swing plus Gaussian noise, clamped to
instrument range and rounded to instrument resolution, updated at **1 Hz**.

---

## 2. Complete tag inventory

Columns: tag · unit · display range · normal baseline (`base ± amp`, swing period) · alarms (setpoint, priority).

### Kitting — station 0, head of line

| Tag | Unit | Range | Normal | Alarms |
|---|---|---|---|---|
| `Status` | string | — | `"Running"` | — |
| `BinLevel` | % | 0–100 | 40 ± 7, 190 s | Kitting Bin Level High **> 90** (High) |
| `ConveyorSpeed` | ft/min | 0–30 | 18 ± 0.9, 95 s | Kitting Conveyor Speed Low **< 4** (Medium) |
| `PickRate` | picks/min | 0–90 | 62 ± 3.5, 130 s | Kitting Pick Rate Low **< 30** (Medium) |
| `ComponentShortage` | bool | — | `False` | Kitting Component Shortage (Low) |

### Mixing — station 1

| Tag | Unit | Range | Normal | Alarms |
|---|---|---|---|---|
| `Status` | string | — | `"Running"` | — |
| `TankLevel` | % | 0–100 | 50 ± 6, 210 s | Mixing Tank Level High **> 92** (High) |
| `MixTimeElapsed` | min | 0–60 | **sawtooth** 0.5 → 18 over a 240 s batch | Mixing Time Exceeded **> 25** (Medium) |
| `MixerMotorCurrent` | A | 0–60 | 34 ± 1.8, 85 s | Mixer Motor Current High **> 48** (High) |
| `SlurryTemp` | °F | 40–140 | 96 ± 1.6, 260 s | Slurry Temp High **> 115** (Medium); Slurry Temp Low **< 80** (Low) |
| `MotorOverload` | bool | — | `False` | Mixer Motor Overload (Medium) |

### Forming — station 2

| Tag | Unit | Range | Normal | Alarms |
|---|---|---|---|---|
| `Status` | string | — | `"Running"` | — |
| `BufferLevel` | % | 0–100 | 45 ± 7, 175 s | Forming Buffer Level High **> 90** (High) |
| `FormerPressure` | psi | 0–250 | 120 ± 7, 70 s | Former Pressure High **> 180** (Medium) |
| `FormerCycleRate` | cyc/min | 0–80 | 58 ± 2.2, 110 s | Former Cycle Rate Low **< 25** (Medium) |
| `DieTemp` | °F | 60–400 | 265 ± 4.5, 240 s | Former Die Temperature High **> 320** (Medium) |
| `ConveyorJam` | bool | — | `False` | Forming Conveyor Jam (**High**) |

### Cooking — station 3

| Tag | Unit | Range | Normal | Alarms |
|---|---|---|---|---|
| `Status` | string | — | `"Running"` | — |
| `CookTimeElapsed` | min | 0–60 | 12 ± 0.7, 150 s | Cook Time Exceeded – Overcook Risk **> 35** (**Critical**) |
| `OvenTemperature` | °F | 60–500 | 350 ± 4.5, 120 s | Oven Temp High **> 420** (**Critical**); Oven Temp Low **< 300** (Medium) |
| `OvenBeltSpeed` | ft/min | 0–25 | 14 ± 0.5, 100 s | Oven Belt Speed Low **< 5** (High) |
| `BurnerOutput` | % | 0–100 | 62 ± 6, 90 s | Oven Burner Output High **> 95** (Medium) |
| `ExitBufferLevel` | % | 0–100 | 40 ± 7, 200 s | Cooking Exit Buffer Level High **> 90** (High) |

### Packaging — station 4, tail of line, **where the fault originates**

| Tag | Unit | Range | Normal | Alarms |
|---|---|---|---|---|
| `Status` | string | — | `"Running"` | — |
| `InfeedBufferLevel` | % | 0–100 | 35 ± 7, 165 s | Packaging Infeed Buffer Level High **> 90** (High) |
| `PackagesPerMinute` | pkg/min | 0–80 | 42 ± 2.5, 100 s | Packaging Throughput Low **< 5** (Medium) |
| `MotorTorque` | % | 0–120 | 52 ± 3, 75 s | Torque Elevated **> 70** (Medium); Torque High **> 85** (High) |
| `MotorCurrent` | A | 0–60 | 22 ± 1.2, 65 s | Drive Current High **> 38** (High) |
| `DriveVibration` | mm/s | 0–20 | 2.4 ± 0.35, 55 s | Vibration Elevated **> 4.5** (Medium); Vibration High **> 7.1** (High) |
| `GearboxTemp` | °F | 60–260 | 142 ± 3.5, 230 s | Gearbox Temp High **> 190** (High) |
| `BeltSpeed` | ft/min | 0–130 | 95 ± 2.2, 85 s | Packaging Belt Speed Low **< 60** (Medium) |
| `ConveyorBeltStatus` | bool | — | `False` | **Packaging Conveyor Belt Break (Critical)** — `True` = belt is broken |

> `ConveyorBeltStatus` is an inverted-sense name: **`True` means BROKEN.** The alarm
> is "active while the boolean is True".

### Simulator control/status — `[default]Exchange/Alarm Flood/Simulator/*`

Bind these directly for the SVG's global state; they are memory tags, updated 1 Hz.

| Tag | Type | Meaning |
|---|---|---|
| `Phase` | String | `NORMAL` / `DEGRADING` / `FAULT` / `CASCADE` / `HOLD` / `RECOVERY` |
| `StageName` | String | Human-readable banner, e.g. `"Drive torque climbing - jam building"` |
| `StageIndex` | Int | Index into the current phase's stage list |
| `PhaseElapsed` | Int | Seconds into the current phase |
| `Progress` | Float | 0..1 through the current phase |
| `TargetLine` | String | Which line the scenario is running on |
| `Scenario` / `ScenarioLabel` | String | `PackagingConveyorJam` + its label |
| `HoldSecs` | Int | Default 60 |
| `DegradeSecs` | Int | Default 10 — **the ramp-length knob** |
| `Enabled` | Bool | False freezes every value |
| `NuisanceEnabled` | Bool | Random low-priority alarms on non-target lines |
| `TickCount` | Int8 | Increments every second — a free animation heartbeat |
| `LastError` | String | Sim exception text |

---

## 3. Mapping the tags onto conveyors and buffers in the SVG

**There is no dedicated tag per inter-machine conveyor segment.** Motion has to be
derived. Recommended mapping — this is the part that makes the animation line up:

| SVG element | Drive it from | Nominal | Stopped when |
|---|---|---|---|
| Raw-component bin at head of line | `Kitting/BinLevel` (fill %) | 40 % | — |
| **Conveyor A: Kitting → Mixing** | `Kitting/ConveyorSpeed` ÷ 18 | 18 ft/min | `< 4` (alarm) or `Kitting/Status != Running` |
| Mix tank fill | `Mixing/TankLevel` (fill %) | 50 % | — |
| Mixer agitator spin | `Mixing/MixerMotorCurrent` ÷ 34 | 34 A | `Mixing/Status` is `Holding` / `Stopped` |
| **Conveyor B: Mixing → Forming** (discharge) | no tag — use `Mixing/Status == "Running"`, gate on `Forming/BufferLevel < 90` | — | `Mixing/Status == "Holding"` |
| Buffer accumulator before Forming | `Forming/BufferLevel` (fill %) | 45 % | — |
| Press / former stroke rate | `Forming/FormerCycleRate` ÷ 58 | 58 cyc/min | `< 25`, or `Forming/ConveyorJam == True` |
| **Conveyor C: Forming → Cooking** | `Forming/FormerCycleRate` ÷ 58 | — | `Forming/ConveyorJam == True` → jam icon + halt |
| **Oven belt (inside Cooking)** | `Cooking/OvenBeltSpeed` ÷ 14 | 14 ft/min | `< 5` (alarm) |
| Burner flame intensity | `Cooking/BurnerOutput` % | 62 % | 0 when Blocked |
| Oven glow / heat colour | `Cooking/OvenTemperature` 300→440 °F | 350 °F | — |
| Exit buffer after Cooking | `Cooking/ExitBufferLevel` (fill %) | 40 % | — |
| **Conveyor D: Cooking → Packaging** | `Cooking/OvenBeltSpeed` ÷ 14 | — | same as oven belt |
| Infeed accumulator before Packaging | `Packaging/InfeedBufferLevel` (fill %) | 35 % | — |
| **Conveyor E: Packaging belt** ← *the one that breaks* | `Packaging/BeltSpeed` ÷ 95 | 95 ft/min | `ConveyorBeltStatus == True` → **draw the belt severed**, product stops dead |
| Packaging drive motor | `MotorTorque`, `MotorCurrent`, `DriveVibration`, `GearboxTemp` | 52 % / 22 A / 2.4 mm/s / 142 °F | — |
| Output / carton rate | `Packaging/PackagesPerMinute` ÷ 42 | 42 pkg/min | 0 during fault |

### Suggested animation rules

- **Product motion rate** on any conveyor = `currentSpeed / nominalSpeed`. At 1.0 use
  the nominal dash/translate duration; scale linearly. **At 0, pause the animation in
  place — do not reset it to the start.** Frozen product on a stopped belt is the
  visual point.
- **Belt break** (`Packaging/ConveyorBeltStatus == True`): stop motion instantly (not a
  decel), draw the belt parted/slack, product piling at the infeed. This is the only
  *hard* stop in the whole run; everything else decelerates.
- **Buffer fill is the backpressure story.** Animate levels filling bottom-up; flash
  them red at their High setpoint (90 / 92 %). The order in which they fill *is* the
  cascade — see §4.
- **Station colour from the `Status` string**, which is authoritative and cheap to bind:

  | Status | Meaning | Suggested |
  |---|---|---|
  | `Running` | normal | green / neutral |
  | `Warning` | degrading (Packaging only, at ≥45 % of the ramp) | amber, pulsing |
  | `Fault` | broken (Packaging) | red, strobe |
  | `Blocked` | can't discharge downstream (Cooking, Forming) | orange |
  | `Holding` | product held in vessel (Mixing) | yellow |
  | `Stopped` | starved / halted (Kitting) | grey |
  | `Recovering` | restarting | blue, animating back up |

- **Drive vibration** → shake amplitude on the Packaging motor group. 2.4 mm/s = still,
  7.1 = visibly shaking, 12.5 = the spike at the moment the belt parts.
- **Gearbox temp** → heat colour on the gearbox body, 142 °F cool → 190 °F red.
- `Simulator/TickCount` is a free 1 Hz heartbeat if you need something to key off.

---

## 4. The fault scenario — `PackagingConveyorJam`

`exchange.alarmFlood.control.simulateFlood()` writes **no alarm directly.** It advances a phase machine
and the process physics trip the alarms. Total run with defaults (`degradeSecs=10`,
`holdSecs=60`): **244 s ≈ 4 min.**

```
NORMAL → DEGRADING(10s) → FAULT(2s) → CASCADE(82s) → HOLD(60s) → RECOVERY(90s) → NORMAL
t=0        0–10            10–12       12–94          94–154      154–244
```

`DegradeSecs` is the knob. Every degrade curve is a function of **normalised ramp
progress**, so stretching it to 120–180 s stretches the ramp without reordering the
precursor alarms. Two consequences of the short default:

- The Packaging drive alarms carry a **0 s on-delay** (everything else has 2 s) or a
  10 s ramp would swallow the whole precursor chain.
- **Gearbox temperature is a thermal integrator, not a ramp function** — it heats
  `0.36 °F per second of elapsed jam`, capped at +56 °F. On a 10 s snap it barely warms
  and its alarm never trips; it only fires on a slow bind (~130 s+). Don't animate the
  gearbox going red on a short run — it won't.

### Phase 1 — DEGRADING (0–10 s): the drive starts to bind

Only the Packaging station moves. Every other station is still running its normal
model. `value = v0 + delta · progress^exponent` — superlinear, so it creeps then runs
away. Noise grows with progress too: the signal gets rougher as it binds.

| Tag | 0 s | 10 s | Curve |
|---|---|---|---|
| `Packaging/MotorTorque` | 52 % | **94 %** | exp 1.15, noise 0.50 → 3.50 |
| `Packaging/MotorCurrent` | 22 A | **42 A** | exp 1.40 |
| `Packaging/DriveVibration` | 2.4 mm/s | **8.0 mm/s** | exp 2.20 |
| `Packaging/BeltSpeed` | 95 ft/min | **81 ft/min** | exp 2.00 (falling) |
| `Packaging/PackagesPerMinute` | 42 | **33** | exp 2.00 (falling) |
| `Packaging/InfeedBufferLevel` | 35 % | **55 %** | exp 1.50 (rising) |
| `Packaging/GearboxTemp` | 142 °F | 145.6 °F | +0.36 °F per elapsed second |

Plus **intermittent grabs**: past 45 % progress there is a 12 % chance per tick of a
+2.5…5.5 % torque spike. Torque is not a clean curve — it snatches. Worth showing as
jitter on the motor.

`Packaging/Status` → `"Warning"` at ≥45 % progress.

Measured alarm order on a real 10 s run:

| ~t | Alarm | Priority |
|---|---|---|
| 0.0 s | Packaging Drive Torque Elevated | Medium |
| 3.0 s | Packaging Drive Torque High | High |
| 3.0 s | Packaging Drive Vibration Elevated | Medium |
| 4.0 s | Packaging Drive Vibration High | High |
| 5.0 s | Packaging Drive Current High | High |
| 6.0 s | **Packaging Conveyor Belt Break** | **Critical** |

### Phase 2 — FAULT (10–12 s): the belt parts

Held constants: `ConveyorBeltStatus = True`, `BeltSpeed = 0`, `PackagesPerMinute = 0`,
`MotorTorque = 6 %`, `MotorCurrent = 6.5 A`, `Status = "Fault"`.

Torque and current **collapse** — the motor is now free-spinning against nothing, which
is the giveaway that the belt is gone rather than still binding. `DriveVibration`
**spikes to 12.5 mm/s** then falls to 3.0 over the 2 s as the load departs. Infeed
creeps 55 → 57 %.

Visually: belt severs, product on it freezes, motor shudders hard once then goes limp.

### Phase 3 — CASCADE (12–94 s, elapsed 0–82 s): backpressure walks upstream

Nothing leaves the line, so each buffer fills in turn and each station blocks. All
times below are **elapsed within CASCADE** (add 12 s for absolute).

Held constant the whole phase: belt broken, `BeltSpeed = 0`, `PackagesPerMinute = 0`,
`MotorTorque ≈ 5 %`, `MotorCurrent ≈ 6 A`.

| From → to (s) | Tag | v0 → v1 | Crosses |
|---|---|---|---|
| 0 → 22 | `Packaging/InfeedBufferLevel` | 55 → **99 %** | Infeed Buffer High (90) |
| 0 → 82 | `Packaging/GearboxTemp` | peak → 172 °F | — |
| 0 → 10 | `Packaging/DriveVibration` | 3.0 → 1.2 | — |
| 22 → 40 | `Cooking/ExitBufferLevel` | 42 → **99 %** | Exit Buffer High (90) |
| 22 → 36 | `Cooking/OvenBeltSpeed` | 14 → **1.5** | Oven Belt Speed Low (5) |
| 22 → 38 | `Cooking/CookTimeElapsed` | 12 → **44 min** | **Overcook Risk (35, Critical)** |
| 24 → 40 | `Cooking/OvenTemperature` | 352 → **438 °F** | **Oven Temp High (420, Critical)** |
| 26 → 40 | `Cooking/BurnerOutput` | 62 → 16 % | — (burner backs off) |
| 38 → 54 | `Forming/BufferLevel` | 46 → **98 %** | Buffer High (90) |
| 38 → 53 | `Forming/FormerPressure` | 121 → **205 psi** | Pressure High (180) |
| 38 → 52 | `Forming/FormerCycleRate` | 58 → **10** | Cycle Rate Low (25) |
| 40 → 56 | `Forming/DieTemp` | 266 → **334 °F** | Die Temp High (320) |
| 54 → 68 | `Mixing/TankLevel` | 51 → **99 %** | Tank Level High (92) |
| 54 → 69 | `Mixing/MixTimeElapsed` | 14 → **36 min** | Mix Time Exceeded (25) |
| 54 → 68 | `Mixing/MixerMotorCurrent` | 35 → **53 A** | Motor Current High (48) |
| 54 → 70 | `Mixing/SlurryTemp` | 97 → **120 °F** | Slurry Temp High (115) |
| 68 → 81 | `Kitting/BinLevel` | 42 → **97 %** | Bin Level High (90) |
| 68 → 80 | `Kitting/ConveyorSpeed` | 18 → **1.5** | Conveyor Speed Low (4) |
| 68 → 79 | `Kitting/PickRate` | 62 → **14** | Pick Rate Low (30) |

Booleans latch: `Forming/ConveyorJam = True` at **51 s**, `Mixing/MotorOverload = True`
at **66 s**.

Status transitions — the cleanest thing to drive station colour off:

| elapsed | Station | Status |
|---|---|---|
| 0 s | Packaging | `Fault` |
| 24 s | Cooking | `Blocked` |
| 40 s | Forming | `Blocked` |
| 56 s | Mixing | `Holding` |
| 70 s | Kitting | `Stopped` |

Stage banner (`Simulator/StageName`):

| elapsed | Banner |
|---|---|
| 0 s | Packaging infeed backing up |
| 22 s | Cooking exit blocked - overcook risk |
| 38 s | Forming blocked - press pressure rising |
| 54 s | Mixing batch held in tank |
| 68 s | Kitting starved - line stopped |

**~27 alarms total**, peaking around 11 per 30 s window.

### Phase 4 — HOLD (94–154 s, default 60 s): line down, awaiting belt replacement

Everything pinned at its cascade end value with reduced noise. Two things still move,
because the line being down doesn't stop physics:

- Hot equipment cools: `GearboxTemp` peak → 148 °F (over 200 s), `OvenTemperature`
  438 → 296 °F (240 s), `DieTemp` 334 → 250 °F (starts at 30 s, over 220 s).
- Held product keeps cooking: `CookTimeElapsed` 44 → 72 min, `MixTimeElapsed` 36 → 56 min.

Those ramps are longer than the default 60 s hold, so on a default run they only get
partway — that's intended. Banner: `"Line down - awaiting belt replacement"`.

Visually: everything static, buffers full, red everywhere, oven glow slowly fading.

### Phase 5 — RECOVERY (154–244 s, 90 s): restart downstream → upstream

Recovery blends from a **snapshot taken at the start of RECOVERY** back to each tag's
normal-operation model — so it lands back on the live sine, not on a fixed number.
Times are elapsed within RECOVERY.

| start → dur | Tags |
|---|---|
| 4 s, 20 s | `Packaging/MotorTorque`, `MotorCurrent`, `DriveVibration` |
| 4 s, 60 s | `Packaging/GearboxTemp` |
| 8 s, 22 s | `Packaging/InfeedBufferLevel` (drains) |
| 10 s, 16–30 s | `Cooking/OvenBeltSpeed`, `BurnerOutput`, `OvenTemperature` |
| 12 s, 20 s | `Cooking/CookTimeElapsed` |
| 18 s, 22 s | `Cooking/ExitBufferLevel` (drains) |
| 30 s, 16 s | `Forming/FormerCycleRate`, `FormerPressure` |
| 32 s, 24 s | `Forming/DieTemp` |
| 34 s, 22 s | `Forming/BufferLevel` (drains) |
| 50 s, 14–20 s | `Mixing/MixerMotorCurrent`, `SlurryTemp` |
| 52 s, 16–22 s | `Mixing/TankLevel` (drains), `MixTimeElapsed` |
| 68 s, 14 s | `Kitting/ConveyorSpeed`, `PickRate` |
| 70 s, 18 s | `Kitting/BinLevel` |

**Catch-up overrun** — the packaging belt deliberately runs *above* nominal to clear the
backlog, then settles:

| Tag | start | ramp | overshoot | settle |
|---|---|---|---|---|
| `Packaging/BeltSpeed` | 4 s | 14 s | **×1.15** (≈109 ft/min) | 40 s |
| `Packaging/PackagesPerMinute` | 6 s | 16 s | **×1.35** (≈57 pkg/min) | 40 s |

Animate that: the belt visibly runs fast for ~40 s then eases back to normal. It's a
nice detail and it is really in the model.

Booleans clear: `ConveyorBeltStatus` at 2 s (belt replaced — un-sever it),
`Forming/ConveyorJam` at 30 s, `Mixing/MotorOverload` at 50 s.

Statuses go `Recovering`: Packaging 2 s, Cooking 10 s, Forming 30 s, Mixing 50 s,
Kitting 68 s — then all back to `Running` when the phase ends.

Banners: `Belt replaced - restarting packaging` (0) → `Draining packaging and cooking
buffers` (18) → `Restarting forming` (34) → `Restarting mixing` (50) → `Restarting
kitting` (68).

---

## 5. Non-target lines

The other four lines keep running their normal model, refreshed every 5th tick instead
of every tick — fine for animation, just don't expect 1 Hz updates. If
`Simulator/NuisanceEnabled` is on they occasionally throw an unrelated low-priority alarm
(1-in-4000 per line per tick, clears after 45 s) so the journal isn't suspiciously
clean. If the SVG shows all five lines, non-target lines should just animate normally.

---

## 6. Control API (for demo buttons on the SVG page)

| Call | Effect |
|---|---|
| `exchange.alarmFlood.control.simulateFlood(linePath, scenario, holdSecs, degradeSecs)` | Start a run. Resets the line first. |
| `exchange.alarmFlood.sim.abortFlood()` | Skip the hold, run recovery now. |
| `exchange.alarmFlood.sim.resetLine(line)` / `resetAll()` | Hard snap back to normal, no ramp. |
| `exchange.alarmFlood.sim.setEnabled(False)` | Freeze every tag at its current value. |
| `exchange.alarmFlood.sim.status()` / `sample(line)` | Current phase/stage/target; every tag value on a line. |

---

## 7. Things that will trip up the SVG if you don't know them

1. **`ConveyorBeltStatus == True` means broken**, not healthy.
2. **On the default 10 s ramp the gearbox alarm never fires** — it's a thermal
   integrator. Use `degradeSecs=150` if the demo needs it.
3. **`MotorTorque` and `MotorCurrent` drop to near zero after the break**, not up. The
   load is gone. A viewer expecting "fault = high torque" will read it backwards, so it
   may be worth labelling.
4. **`Status` strings are the cheapest correct binding** for station state — they're
   written by the same phase machine that drives the analogs, so they can't disagree.
5. **Alarm setpoints shown in the SVG should come from `exchange.alarmFlood.model`**, not be
   hardcoded — the same rule the trend chart follows, so thresholds can never drift
   from the configured alarms.
6. Analogs update at 1 Hz on the target line; booleans and status strings are only
   written **when they change**.
