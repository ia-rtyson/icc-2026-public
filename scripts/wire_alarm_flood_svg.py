# -*- coding: utf-8 -*-
"""Wire the automated-food-line mimic on the Alarm Flood Event view to live tags.

Four jobs:

1. Add the four buffer level gauges the generated SVG's own binding map
   advertised but never actually drew (only ``mixing-tank-fill`` existed).
2. Inline the ``<use>`` instances that need to animate independently, and put
   ids on the elements CSS has to target.
3. Add ``view.custom`` indirect tag bindings (scoped to ``Simulator/TargetLine``),
   the expression bindings on the SVG elements, and the CSS custom properties
   that drive animation rate / play-state.
4. Regenerate the motion block in the project's advanced stylesheet.

Idempotent: re-running replaces what it made rather than stacking.

Run from the project root::

    python scripts/wire_alarm_flood_svg.py

then rescan the gateway (``shared/gateway-api/scan.sh projects .``).
"""
import collections
import copy
import io
import json
import math

VIEW = ('ignition/projects/icc-2026/com.inductiveautomation.perspective/'
        'views/Exchange/Alarm Flood Agent/Alarm Flood Event/view.json')

STYLESHEET = ('ignition/projects/icc-2026/com.inductiveautomation.perspective/'
              'stylesheet/stylesheet.css')

GAUGE_IDS = frozenset(['kitting-bin-fill', 'forming-buffer-fill',
                       'cooking-exitbuffer-fill', 'packaging-infeed-fill'])


def _is_gauge(node):
    """True for a gauge group this script previously appended.

    Identified by the id of the fill group it wraps rather than by a marker
    key, so nothing non-SVG ends up in the shipped resource.
    """
    if not isinstance(node, dict):
        return False
    return any(isinstance(c, dict) and c.get('id') in GAUGE_IDS
               for c in node.get('elements') or [])


# station id -> (fill element id, caption)
GAUGES = [
    ('station-kitting', 'kitting-bin-fill', 'BIN'),
    ('station-forming', 'forming-buffer-fill', 'BUF'),
    ('station-cooking', 'cooking-exitbuffer-fill', 'EXIT'),
    ('station-packaging', 'packaging-infeed-fill', 'INFD'),
]


def gauge_group(fill_id, caption):
    """A level gauge appended to a station group, drawn beside the station label.

    Origin sits at the BOTTOM of the column so a bound ``scale(1, k)`` on the
    fill group shrinks it downward -- the standard tank-fill trick, and the one
    the SVG's own defs comment describes.
    """
    return {
        'type': 'group',
        'name': 'group',
        'transform': 'translate(186, 732)',
        'elements': [
            {'type': 'use', 'name': 'use', 'href': '#levelGaugeFrame',
             'x': '0', 'y': '0'},
            {'type': 'text', 'name': 'text', 'x': '12', 'y': '-92',
             'text': caption, 'fontSize': '9', 'textAnchor': 'middle',
             'fill': {'paint': '#8ca0ba'}},
            {'type': 'group', 'name': fill_id, 'id': fill_id,
             'transform': 'scale(1, 0.4)',
             'elements': [
                 {'type': 'rect', 'name': 'rect', 'x': '0', 'y': '-82',
                  'width': '24', 'height': '82', 'rx': '3',
                  'fill': {'paint': '#00d2ff'}, 'opacity': '0.85'},
             ]},
        ],
    }


# --------------------------------------------------------------------------
# view.custom -- one indirect tag binding per value, scoped to the target line
# --------------------------------------------------------------------------

# custom prop name -> (station-relative tag path, seed value)
CUSTOM_TAGS = collections.OrderedDict([
    ('kStatus',  ('Kitting/Status', 'Running')),
    ('kBin',     ('Kitting/BinLevel', 40.0)),
    ('mStatus',  ('Mixing/Status', 'Running')),
    ('mTank',    ('Mixing/TankLevel', 50.0)),
    ('fStatus',  ('Forming/Status', 'Running')),
    ('fBuffer',  ('Forming/BufferLevel', 45.0)),
    ('cStatus',  ('Cooking/Status', 'Running')),
    ('cExit',    ('Cooking/ExitBufferLevel', 40.0)),
    ('cOven',    ('Cooking/OvenTemperature', 350.0)),
    ('pStatus',  ('Packaging/Status', 'Running')),
    ('pInfeed',  ('Packaging/InfeedBufferLevel', 35.0)),
    ('pGearbox', ('Packaging/GearboxTemp', 142.0)),
    ('pVib',     ('Packaging/DriveVibration', 2.4)),
    ('pBroken',  ('Packaging/ConveyorBeltStatus', False)),
    # Speeds -- these drive the CSS animation rates, see MOTION below.
    ('kConv',    ('Kitting/ConveyorSpeed', 18.0)),
    ('mCurrent', ('Mixing/MixerMotorCurrent', 34.0)),
    ('fCycle',   ('Forming/FormerCycleRate', 58.0)),
    ('cBelt',    ('Cooking/OvenBeltSpeed', 14.0)),
    ('pBelt',    ('Packaging/BeltSpeed', 95.0)),
])

TARGET_LINE_TAG = '[default]Exchange/Alarm Flood/Simulator/TargetLine'


def tag_binding(path, mode='direct', refs=None):
    cfg = {'fallbackDelay': 2.5, 'mode': mode, 'tagPath': path}
    if refs:
        cfg['references'] = refs
    return {'binding': {'config': cfg, 'type': 'tag'}}


def private(config):
    """Mark a propConfig entry PRIVATE: gateway-side only, never synced to the
    browser. Right for a value that only other bindings read."""
    config['access'] = 'PRIVATE'
    return config


def expr_binding(expression):
    return {'binding': {'config': {'expression': expression}, 'type': 'expr'}}


# --------------------------------------------------------------------------
# Expressions -- element appearance
# --------------------------------------------------------------------------

def status_colour(prop):
    return ('case({view.custom.%s},\n'
            '  "Running",    "#00ff66",\n'
            '  "Warning",    "#ffaa00",\n'
            '  "Fault",      "#ff2222",\n'
            '  "Blocked",    "#ff8800",\n'
            '  "Holding",    "#ffe066",\n'
            '  "Stopped",    "#8a94a6",\n'
            '  "Recovering", "#3aa6ff",\n'
            '  "#666666")' % prop)


def level_scale(prop):
    """scale(1, k) with k clamped to 0..1 -- k is the level percentage / 100."""
    return ('"scale(1, " + numberFormat(max(0, min(1, '
            'toDouble({view.custom.%s}) / 100.0)), "0.000") + ")"' % prop)


def level_colour(prop, setpoint):
    """Cyan while normal, amber approaching the High setpoint, red once over it."""
    return ('if(toDouble({view.custom.%s}) >= %s, "#ff2222",\n'
            '  if(toDouble({view.custom.%s}) >= %s, "#ffaa00", "#00d2ff"))'
            % (prop, setpoint, prop, setpoint - 10))


OVEN_COLOUR = (
    'if(toDouble({view.custom.cOven}) >= 420, "#ff2200",\n'
    '  if(toDouble({view.custom.cOven}) >= 390, "#ff6a00",\n'
    '    if(toDouble({view.custom.cOven}) >= 360, "#ffa733",\n'
    '      if(toDouble({view.custom.cOven}) >= 300, "#ff8c1a", "#5a3b1a"))))'
)

GEARBOX_COLOUR = (
    'if(toDouble({view.custom.pGearbox}) >= 190, "#ff2222",\n'
    '  if(toDouble({view.custom.pGearbox}) >= 170, "#d98c1e",\n'
    '    if(toDouble({view.custom.pGearbox}) >= 155, "#8a6a2a", "#3a4757")))'
)

# Vibration Elevated = 4.5 mm/s, Vibration High = 7.1 mm/s (exchange.alarmFlood.model).
VIB_OPACITY = (
    'if(toDouble({view.custom.pVib}) >= 7.1, 0.95,\n'
    '  if(toDouble({view.custom.pVib}) >= 4.5, 0.5, 0))'
)

# ConveyorBeltStatus is inverted-sense: True means the belt is BROKEN.
BELT_INTACT = 'if({view.custom.pBroken}, 0, 1)'
BELT_BROKEN = 'if({view.custom.pBroken}, 1, 0)'

PHASE_COLOUR = (
    'case({[default]Exchange/Alarm Flood/Simulator/Phase},\n'
    '  "NORMAL",    "#28A745",\n'
    '  "DEGRADING", "#E08A1E",\n'
    '  "FAULT",     "#D9202A",\n'
    '  "CASCADE",   "#B02020",\n'
    '  "HOLD",      "#7D3C98",\n'
    '  "RECOVERY",  "#2E86C1",\n'
    '  "#6C757D")'
)

# element id -> list of (sub-property path, binding)
ELEMENT_BINDINGS = {
    'kitting-bin-fill':        [('transform', expr_binding(level_scale('kBin')))],
    'mixing-tank-fill':        [('transform', expr_binding(level_scale('mTank')))],
    'forming-buffer-fill':     [('transform', expr_binding(level_scale('fBuffer')))],
    'cooking-exitbuffer-fill': [('transform', expr_binding(level_scale('cExit')))],
    'packaging-infeed-fill':   [('transform', expr_binding(level_scale('pInfeed')))],

    'kitting-status-lamp':     [('fill.paint', expr_binding(status_colour('kStatus')))],
    'mixing-status-lamp':      [('fill.paint', expr_binding(status_colour('mStatus')))],
    'forming-status-lamp':     [('fill.paint', expr_binding(status_colour('fStatus')))],
    'cooking-status-lamp':     [('fill.paint', expr_binding(status_colour('cStatus')))],
    'packaging-status-lamp':   [('fill.paint', expr_binding(status_colour('pStatus')))],

    'cooking-oven-glow':       [('fill.paint', expr_binding(OVEN_COLOUR))],
    'packaging-gearbox-heat':  [('fill.paint', expr_binding(GEARBOX_COLOUR))],
    # NOTE: packaging-vibration-alarm (the ring around the sprocket) is
    # deliberately absent. Its opacity used to be bound to pVib, which is why it
    # vanished the instant the belt parted -- vibration collapses with the load.
    # It is now the drive alarm indicator, flashed by CSS off the alarm mask.
    'packaging-belt-intact':   [('opacity', expr_binding(BELT_INTACT))],
    'packaging-belt-broken':   [('opacity', expr_binding(BELT_BROKEN))],
    # Deliberately NOT binding line-flow-indicator's opacity. Hiding the
    # travelling product on a belt break was the stand-in from before there was
    # any motion; now the markers are paused in place by --pkg-play, which is
    # the behaviour actually wanted -- product sitting stranded on a dead belt.
    # Binding opacity as well just deletes it from the screen.

    # No sim-phase-* / sim-stage-* here: that readout is removed from the SVG,
    # the page already carries the phase chip and stage banner above the mimic.
}

# fill group id -> (custom prop, High setpoint from exchange.alarmFlood.model)
GAUGE_SETPOINTS = {
    'kitting-bin-fill': ('kBin', 90),
    'mixing-tank-fill': ('mTank', 92),
    'forming-buffer-fill': ('fBuffer', 90),
    'cooking-exitbuffer-fill': ('cExit', 90),
    'packaging-infeed-fill': ('pInfeed', 90),
}


# --------------------------------------------------------------------------
# Motion
# --------------------------------------------------------------------------
# The SVG importer discards every <animateTransform>, and an ia.shapes.svg
# element accepts no style/class key, so motion is done with CSS keyframes in
# the project's advanced stylesheet instead. Two facts make that work, both
# verified in a browser against this gateway:
#
#   * Perspective passes a `--custom-prop` in props.style straight through to
#     the container's inline style, and custom properties inherit into the SVG.
#     So bound expressions on the parent flex container reach every element.
#   * animation-play-state: paused freezes an animation IN PLACE, which is
#     exactly the "product stops where it is" behaviour the mimic needs. A
#     changing animation-duration would restart it from zero instead.
#
# Perspective prefixes every SVG id with a per-component-instance string
# (`C-0-1-0-0-0-kitting-bin-fill`), so the stylesheet matches on [id$="-name"]
# rather than #name. That prefix changes if the component moves in the tree.

# <use> instances that must be inlined. A <use> renders into a shadow tree CSS
# cannot reach per-instance: rules match the symbol in <defs>, so every instance
# shares one animation and a per-station var() never resolves against the call
# site. Verified -- three <use href="#miniBelt"> produced exactly three
# animations, all on the defs symbol, all at the fallback duration. Inlining the
# symbol at each call site is what makes per-station speed possible at all.
# (anchor id or None for top level, symbol href, x to disambiguate, new id)
INLINE_USES = [
    (None, '#conveyorSegment', '540',  'conv-b'),          # Mixing -> Forming
    (None, '#conveyorSegment', '860',  'conv-c'),          # Forming -> Cooking
    (None, '#conveyorSegment', '1180', 'conv-d'),          # Cooking -> Packaging
    ('station-mixing',        '#miniBelt', None, 'belt-mixing'),
    ('station-forming',       '#miniBelt', None, 'belt-forming'),
    ('station-cooking',       '#miniBelt', None, 'belt-cooking'),
    ('packaging-belt-intact', '#miniBelt', None, 'belt-packaging'),
]

# --------------------------------------------------------------------------
# Alarm indicators
# --------------------------------------------------------------------------
# Every part of the line that can raise an alarm gets an indicator that flashes
# while that alarm is standing: a halo around each station, plus the ring around
# the packaging sprocket for the drive alarms specifically.
#
# Driven by REAL alarm state (exchange.alarmFlood.control.stationAlarmMask, one runScript poll)
# rather than by tag values. That distinction is the whole point: after the belt
# parts, torque, current and vibration all *collapse* because the load is gone,
# so the old value-threshold binding on the ring dropped back under its setpoint
# and the ring vanished at the exact moment the failure happened. Alarm state
# stays latched until the alarm actually clears, which is what an operator sees.
#
# The flash is a CSS animation whose *name* comes from a custom property --
# `animation-name: var(--pkg-alarm, none)`. Two reasons it is done that way and
# not by binding fill/opacity:
#   * a bound value arrives as a presentation attribute, and per the note in
#     build_css() anything easing that same property pins it forever;
#   * `animation-name: none` falls cleanly back to the element's base style, so
#     there is no "frozen mid-flash" state to clean up the way there would be
#     with animation-play-state: paused.
# So CSS owns opacity/stroke on these elements outright and no binding touches
# them.

ALARM_MASK_POLL_MS = 1000
ALARM_MASK_PROP = 'alarmMask'

# mask key -> (station group id, halo element id)
ALARM_HALOS = [
    ('kit',  'station-kitting',   'kitting-alarm-halo'),
    ('mix',  'station-mixing',    'mixing-alarm-halo'),
    ('form', 'station-forming',   'forming-alarm-halo'),
    ('cook', 'station-cooking',   'cooking-alarm-halo'),
    ('pkg',  'station-packaging', 'packaging-alarm-halo'),
]

# Every station is drawn in the same 320-unit slot with its body spanning local
# x 15..185, y 260..620, so one halo box suits all five.
HALO_BOX = (6, 246, 188, 388, 12)   # x, y, width, height, corner radius

# The ring already in the generated SVG around the packaging sprocket. Kept as
# the drive-specific indicator and driven by the "pdrv" mask key.
DRIVE_RING_ID = 'packaging-vibration-alarm'
DRIVE_RING_KEY = 'pdrv'

ALARM_KEYS = [key for key, _s, _h in ALARM_HALOS] + [DRIVE_RING_KEY]


def halo_element(element_id):
    """Outline halo for a station. Stroke and opacity are left to CSS."""
    x, y, w, h, r = HALO_BOX
    return {
        'type': 'rect', 'id': element_id, 'name': element_id,
        'x': '%g' % x, 'y': '%g' % y, 'width': '%g' % w, 'height': '%g' % h,
        'rx': '%g' % r, 'ry': '%g' % r,
        'fill': {'paint': 'none'},
        'stroke': {'paint': '#ff2222', 'width': '4'},
        'filter': 'url(#neonGlow)',
    }


def alarm_anim_expr(key):
    """Animation name for one part: red if High/Critical, amber if lower, else none.

    Delimiters on both sides of the key make the membership test exact -- without
    them "form" would also match a hypothetical "forming".
    """
    return ('if(indexOf({view.custom.%s}, "|%s:h|") >= 0, "af-alarm-red",\n'
            '  if(indexOf({view.custom.%s}, "|%s:m|") >= 0, "af-alarm-amber", "none"))'
            % (ALARM_MASK_PROP, key, ALARM_MASK_PROP, key))


# --------------------------------------------------------------------------
# Packaging drive sprocket
# --------------------------------------------------------------------------
# The generated SVG drew the packaging motor as three concentric circles in two
# near-identical shades of silver. Rotating that is a no-op: a circle is
# rotationally symmetric, so `af-spin` was running the whole time and there was
# nothing on screen to show it. Replaced with a real toothed sprocket -- teeth
# and spokes break the symmetry, and a single off-centre timing mark in the
# project's accent colour makes direction and speed readable at a glance.
#
# Kept symmetric about (ROTOR_CX, ROTOR_CY) on purpose: the CSS spins it with
# transform-box: fill-box and transform-origin: 50% 50%, so the group's bounding
# box centre has to stay the true axis or the gear would visibly orbit.

ROTOR_CX, ROTOR_CY = 100.0, 200.0
GEAR_TEETH = 12
GEAR_TIP_R = 52.0     # outside diameter of the teeth
GEAR_ROOT_R = 38.0    # base circle the teeth stand on
GEAR_WEB_R = 30.0     # dark web inside the rim
GEAR_HUB_R = 12.0
GEAR_SPOKES = 5
GEAR_MARK_R = 5.0     # timing mark
GEAR_MARK_OFFSET = 21.0


def _pt(radius, degrees):
    """Point on a circle about the rotor centre, degrees clockwise from 12 o'clock."""
    a = math.radians(degrees - 90.0)
    return (ROTOR_CX + radius * math.cos(a), ROTOR_CY + radius * math.sin(a))


def gear_path():
    """Trapezoidal-tooth sprocket outline as a single closed path."""
    step = 360.0 / GEAR_TEETH
    d = []
    for i in range(GEAR_TEETH):
        a0 = i * step
        for radius, frac in ((GEAR_ROOT_R, 0.00), (GEAR_TIP_R, 0.16),
                             (GEAR_TIP_R, 0.44), (GEAR_ROOT_R, 0.60)):
            x, y = _pt(radius, a0 + step * frac)
            d.append('%s%.2f %.2f' % ('M' if not d else 'L', x, y))
    d.append('Z')
    return ' '.join(d)


def spoke_path():
    """GEAR_SPOKES tapered spokes from the hub out to the rim, as one path."""
    step = 360.0 / GEAR_SPOKES
    d = []
    for i in range(GEAR_SPOKES):
        a = i * step
        x1, y1 = _pt(GEAR_HUB_R - 1.0, a - 5.0)
        x2, y2 = _pt(GEAR_ROOT_R + 1.0, a - 3.0)
        x3, y3 = _pt(GEAR_ROOT_R + 1.0, a + 3.0)
        x4, y4 = _pt(GEAR_HUB_R - 1.0, a + 5.0)
        d.append('M%.2f %.2f L%.2f %.2f L%.2f %.2f L%.2f %.2f Z'
                 % (x1, y1, x2, y2, x3, y3, x4, y4))
    return ' '.join(d)


def rotor_elements():
    """Full element list for the pkg-rotor group, outermost first."""
    return [
        {'type': 'path', 'name': 'gear-teeth', 'd': gear_path(),
         'fill': {'url': 'url(#metalLight)'}},
        {'type': 'circle', 'name': 'gear-web', 'cx': '%g' % ROTOR_CX,
         'cy': '%g' % ROTOR_CY, 'r': '%g' % GEAR_WEB_R,
         'fill': {'paint': '#151921'}},
        {'type': 'path', 'name': 'gear-spokes', 'd': spoke_path(),
         'fill': {'url': 'url(#metalLight)'}},
        {'type': 'circle', 'name': 'gear-hub', 'cx': '%g' % ROTOR_CX,
         'cy': '%g' % ROTOR_CY, 'r': '%g' % GEAR_HUB_R,
         'fill': {'url': 'url(#metalLight)'}},
        # Off-centre and brightly coloured: this is the part that actually makes
        # the rotation legible, and it also shows the direction.
        {'type': 'circle', 'name': 'gear-mark',
         'cx': '%g' % ROTOR_CX, 'cy': '%g' % (ROTOR_CY - GEAR_MARK_OFFSET),
         'r': '%g' % GEAR_MARK_R, 'fill': {'paint': '#00d2ff'}},
    ]


# --------------------------------------------------------------------------
# Packaging cam drive -- crank + scotch yoke
# --------------------------------------------------------------------------
# The generated SVG hung a single bent yellow stroke off the sprocket
# ("M 135 200 L 145 320 L 120 320"). It read as a wire, not as a mechanism, and
# it explained nothing: the sprocket spun, the sealer bobbed, and there was no
# visible connection between the two.
#
# Replaced with a scotch yoke, which is the one crank mechanism that can be
# animated honestly in CSS. A connecting rod on a crank slider has to *swing*,
# and there is no way to drive a swing and a translation from one keyframe
# without baking the rod length into the maths. A scotch yoke's rod only ever
# translates vertically: the crank pin rides a horizontal slot, so the rod is
# pure translateY and the pin is pure rotation.
#
# For the pin to stay in the slot the two must agree exactly, which forces three
# things that are non-negotiable:
#
#   * The rod's travel must be SINUSOIDAL, not the linear ramp af-bob-30 gives.
#     A crank turning at constant speed drives its yoke as 15*(1 - cos), and a
#     triangle wave of the same amplitude departs from that by ~5 px -- enough
#     for the pin to visibly leave the slot. Hence af-cam-30.
#   * The sprocket must turn once per stroke, at the press cadence, with the
#     same animation-delay. It used to spin on its own SPIN(5.0) clock, which is
#     2.4x slower and unrelated in phase.
#   * Everything on the shaft -- sprocket, crank, rod, sealer -- must share one
#     play variable, or half the assembly freezes while the rest keeps moving.
#     They are all on seg3 (the segment feeding packaging), which is what the
#     sealer already used to keep press and product in phase.
#
# The crank group is kept symmetric about the shaft axis for the same reason the
# sprocket is: CSS spins it with transform-box: fill-box and
# transform-origin: 50% 50%, so the bounding-box centre has to be the true axis.
# The counterweight opposite the pin is what buys that symmetry -- it is load
# bearing, not decoration. cam_self_check() asserts it.

LEGACY_HANGER_D = 'M 135 200 L 145 320 L 120 320'
"""The bent yellow stroke the generated SVG hung off the sprocket.

Removed by the cam-drive step. Kept as a named constant so a re-run of the
generator that reintroduces it is still cleaned up."""

CAM_THROW = 15.0        # crank radius; stroke is twice this, matching af-cam-30
CAM_PIN_R = 5.5
CAM_ROD_W = 12.0
CAM_ROD_BOTTOM = 472.0  # ends inside the sealer bar (y 460..480 at rest)
CAM_YOKE_W = 56.0
CAM_YOKE_H = 24.0
CAM_SLOT_H = 14.0


def cam_rod_elements():
    """Yoke plate + slot + rod, as one vertically-translating assembly.

    At rest (translateY 0) the slot centres on the crank pin at top dead centre,
    y = ROTOR_CY - CAM_THROW. af-cam-30 then carries it down 2 * CAM_THROW and
    back, which is exactly where the pin goes.
    """
    slot_cy = ROTOR_CY - CAM_THROW
    rod_top = slot_cy + CAM_YOKE_H / 2 - 2
    return [
        {'type': 'rect', 'name': 'cam-yoke',
         'x': '%g' % (ROTOR_CX - CAM_YOKE_W / 2),
         'y': '%g' % (slot_cy - CAM_YOKE_H / 2),
         'width': '%g' % CAM_YOKE_W, 'height': '%g' % CAM_YOKE_H, 'rx': '4',
         'fill': {'url': 'url(#metalLight)'}},
        {'type': 'rect', 'name': 'cam-slot',
         'x': '%g' % (ROTOR_CX - CAM_YOKE_W / 2 + 5),
         'y': '%g' % (slot_cy - CAM_SLOT_H / 2),
         'width': '%g' % (CAM_YOKE_W - 10), 'height': '%g' % CAM_SLOT_H,
         'rx': '%g' % (CAM_SLOT_H / 2), 'fill': {'paint': '#0f141d'}},
        {'type': 'rect', 'name': 'cam-rod',
         'x': '%g' % (ROTOR_CX - CAM_ROD_W / 2), 'y': '%g' % rod_top,
         'width': '%g' % CAM_ROD_W,
         'height': '%g' % (CAM_ROD_BOTTOM - rod_top),
         'rx': '3', 'fill': {'url': 'url(#metalLight)'}},
        # Clevis where the rod picks up the sealer bar.
        {'type': 'circle', 'name': 'cam-clevis', 'cx': '%g' % ROTOR_CX,
         'cy': '%g' % (CAM_ROD_BOTTOM - 6), 'r': '4.5',
         'fill': {'paint': '#0f141d'}},
    ]


def cam_crank_elements():
    """Crank throw: pin at top dead centre, counterweight opposite.

    Both ends are the same radius on purpose -- that is what keeps the group's
    bounding box centred on (ROTOR_CX, ROTOR_CY) so fill-box 50% 50% spins it
    about the real shaft rather than orbiting it.
    """
    return [
        {'type': 'rect', 'name': 'crank-web',
         'x': '%g' % (ROTOR_CX - CAM_ROD_W / 2),
         'y': '%g' % (ROTOR_CY - CAM_THROW),
         'width': '%g' % CAM_ROD_W, 'height': '%g' % (2 * CAM_THROW),
         'rx': '%g' % (CAM_ROD_W / 2), 'fill': {'url': 'url(#metalLight)'}},
        {'type': 'circle', 'name': 'crank-balance', 'cx': '%g' % ROTOR_CX,
         'cy': '%g' % (ROTOR_CY + CAM_THROW), 'r': '%g' % CAM_PIN_R,
         'fill': {'url': 'url(#metalLight)'}},
        {'type': 'circle', 'name': 'crank-pin', 'cx': '%g' % ROTOR_CX,
         'cy': '%g' % (ROTOR_CY - CAM_THROW), 'r': '%g' % CAM_PIN_R,
         'fill': {'paint': '#00d2ff'}},
    ]


def cam_body(stroke, steps=20):
    """Cosine translateY keyframe stops: y = (stroke/2) * (1 - cos(2*pi*t)).

    A linear @keyframes with a single 50% stop is a triangle wave; a crank drives
    its yoke on a cosine. The pin leaves the slot if these disagree.
    """
    stops = []
    for i in range(steps + 1):
        pct = 100.0 * i / steps
        y = (stroke / 2.0) * (1.0 - math.cos(2.0 * math.pi * i / steps))
        stops.append('%g%% { transform: translateY(%.3fpx); }' % (pct, y))
    return ' '.join(stops)


def cam_keyframes(name, stroke, steps=20):
    return '@keyframes %s { %s }' % (name, cam_body(stroke, steps))


def cam_self_check():
    """Bounding-box centre of the crank group; must be the shaft axis."""
    xs, ys = [], []
    for e in cam_crank_elements():
        if e['type'] == 'rect':
            x, y = float(e['x']), float(e['y'])
            xs += [x, x + float(e['width'])]
            ys += [y, y + float(e['height'])]
        else:
            cx, cy, r = float(e['cx']), float(e['cy']), float(e['r'])
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


# Elements that already exist but need an id so CSS can target them.
# (anchor id, child index path below it, new id)
ASSIGN_IDS = [
    ('station-kitting',       (5,),  'flow-chute-1'),  # dry component chute
    ('station-kitting',       (7,),  'flow-chute-2'),  # liquid binder chute
    ('station-kitting',       (9,),  'kit-arm-1'),     # pick & place gantry
    ('station-kitting',       (10,), 'kit-arm-2'),
    ('station-forming',       (6,),  'form-piston'),
    ('station-forming',       (8,),  'form-press'),
    ('station-packaging',     (3,),  'pkg-rotor'),     # film / box roll drive
    ('packaging-belt-intact', (0,),  'pkg-sealer'),    # heated sealer bar
    ('mixing-tank-fill',      (1,),  'mix-wave'),      # slurry surface
]

# --------------------------------------------------------------------------
# Product flow
# --------------------------------------------------------------------------
# The generated SVG modelled product as six markers that each ran the whole line
# and cross-faded between four shapes via SMIL <animate> on opacity. That cannot
# survive here for two reasons: the importer drops each <animate>'s `begin`, so
# all six markers changed shape *in unison*, and SMIL ignores
# animation-play-state, so a marker frozen by CSS kept changing product type.
#
# Rebuilt as one stream per conveyor segment instead. A segment carries a single
# product shape -- the shape it has after the machine upstream of it -- so the
# product changes state simply by crossing from one segment into the next, which
# happens at the middle of each machine. No cross-fade, nothing to keep in sync.
#
# Each segment also has a queue of stationary items at its downstream end whose
# opacity is driven by that end's buffer level, so product visibly accumulates
# where it has nowhere to go, and a segment stops when its downstream buffer is
# full as well as when its machine stalls.

FLOW_Y = 515
LINE_SPEEDUP = 3.0
"""Global multiplier on how fast the line *runs* at rate 1.0.

The cascade was compressed from 82 s to 18 s (``exchange.alarmFlood.sim.CASCADE_SECS``), so
the line has to run proportionally faster or the backup no longer reads as a
backup -- at the old speed only a handful of products would cross a segment in the
whole 18 s, and buffers would appear to fill with nothing going into them. At 3x
product still visibly flows, queues visibly build, and each conveyor visibly stops
in cascade order, just very fast.

This scales product travel, the press cadence locked to it, and every roller/arm
base duration together. It deliberately does *not* touch the per-station rate
variables: those are ratios of live tag value to nominal, so they stay 1.0 during
normal operation at any line speed."""

FLOW_SPEED = 52.0 * LINE_SPEEDUP   # user units/s at rate 1.0 (base: 1045px/20s)


def SPIN(secs):
    """Base animation duration for a moving part, scaled by LINE_SPEEDUP.

    CSS then divides this again by the station's --<station>-rate at runtime."""
    return '%.4fs' % (float(secs) / LINE_SPEEDUP)

QUEUE_SLOTS = 6
QUEUE_PITCH = 52
# Buffers idle in the 35-53 % band, so a queue must not start forming until well
# clear of that or product piles up during normal operation.
QUEUE_THRESHOLDS = [60, 68, 76, 84, 92, 97]
FULL_BUFFER = 95    # at this level the feeding conveyor has nowhere to discharge

# The four product shapes, lifted from the generated SVG's own marker states.
PRODUCT_STATES = [
    # 0 -- dough ball, out of Mixing
    [{'type': 'circle', 'name': 'circle', 'r': '12', 'fill': {'url': 'url(#doughGrad)'}}],
    # 1 -- pressed disc, out of Forming
    [{'type': 'ellipse', 'name': 'ellipse', 'rx': '16', 'ry': '6',
      'fill': {'url': 'url(#doughGrad)'}}],
    # 2 -- baked pieces on a tray, out of Cooking
    [{'type': 'group', 'name': 'group', 'elements': [
        {'type': 'rect', 'name': 'rect', 'x': '-18', 'y': '-8', 'width': '36',
         'height': '16', 'rx': '3', 'fill': {'paint': '#cccccc'}},
        {'type': 'circle', 'name': 'circle', 'cx': '-8', 'cy': '0', 'r': '5',
         'fill': {'url': 'url(#cookedGrad)'}},
        {'type': 'circle', 'name': 'circle', 'cx': '8', 'cy': '0', 'r': '5',
         'fill': {'paint': '#276e18'}}]}],
    # 3 -- sealed carton, out of Packaging
    [{'type': 'group', 'name': 'group', 'elements': [
        {'type': 'rect', 'name': 'rect', 'x': '-25', 'y': '-17', 'width': '50',
         'height': '35', 'rx': '3', 'fill': {'paint': '#c29b38'},
         'stroke': {'paint': '#8d6e1e', 'width': '2'}},
        {'type': 'path', 'name': 'path', 'd': 'M -25 -7 L 25 -7 M 0 -7 L 0 18',
         'stroke': {'paint': '#8d6e1e', 'width': '1.5'}},
        {'type': 'circle', 'name': 'circle', 'cx': '13', 'cy': '5', 'r': '7',
         'fill': {'paint': '#00ff66'}},
        {'type': 'path', 'name': 'path', 'd': 'M 9 5 L 12 8 L 17 2',
         'fill': {'paint': 'transparent'},
         'stroke': {'paint': '#151921', 'width': '2'}}]}],
]

# Segment boundaries sit at the centre of each machine -- the same x positions
# the original marker used to swap shape (keyTimes 0.2962 / 0.6024 / 0.9087 of
# 1045px from x=480 land on 790, 1110, 1430).
#
# A handoff between segments is only seamless if a traveller reaches the end of
# one exactly as a traveller leaves the start of the next -- i.e. every segment
# must deliver product at the SAME interval, length / travellers / speed. The
# first version used 310 for segment 1 and 320 for the rest, so product vanished
# for a moment entering Forming while Forming -> Cooking (320 -> 320) looked
# fine. Every segment now delivers one item every FLOW_INTERVAL seconds.
#
# n, x0, length, product state, rate var, buffer at its downstream end, travellers
FLOW_SEGMENTS = [
    (1, 480,  320.0,   0, 'form', 'fBuffer', 3),   # Mixing   -> Forming
    (2, 800,  320.0,   1, 'cook', 'cExit',   3),   # Forming  -> Cooking
    (3, 1120, 320.0,   2, 'pkg',  'pInfeed', 3),   # Cooking  -> Packaging
    (4, 1440, 106.667, 3, 'pkg',  None,      1),   # out of Packaging, off frame
]

# Boundaries now land on the true machine centres. Each station group is
# translated to a multiple of 320 and its body spans local x 20..180, so the
# centres are 800 (Forming), 1120 (Cooking), 1440 (Packaging) -- the original
# marker's shape-swap points of 790/1110/1430 were approximations of these.

SEG_LEN = 320.0
FLOW_INTERVAL = SEG_LEN / 3 / FLOW_SPEED
"""Seconds between one product and the next passing any fixed point (~2.05 s).

Everything that has to look like it is acting *on* the product is timed off
this, not off its own arbitrary period."""
# Segment 2 is driven by Cooking/ExitBufferLevel because the model has no
# cooking-infeed tag. It is a proxy, but the right one: it is the tag that fills
# when Cooking cannot discharge, and it fills second in the cascade, between
# Packaging's infeed and Forming's buffer -- which is the order the backup
# actually walks upstream.


def build_flow_elements():
    """Per-segment product streams plus their accumulation queues."""
    segments = []
    for n, x0, length, state, _var, acc, travellers in FLOW_SEGMENTS:
        children = []
        for i in range(travellers):
            # No transform attribute on a travelling item: a CSS transform would
            # replace it and the keyframe would interpolate the offset away.
            children.append({
                'type': 'group', 'name': 'flow-%d-%d' % (n, i),
                'id': 'flow-%d-%d' % (n, i),
                'elements': copy.deepcopy(PRODUCT_STATES[state]),
            })
        if acc:
            for k in range(QUEUE_SLOTS):
                children.append({
                    'type': 'group', 'name': 'queue-%d-%d' % (n, k),
                    'id': 'queue-%d-%d' % (n, k),
                    'transform': 'translate(%d, 0)' % (length - 26 - k * QUEUE_PITCH),
                    'opacity': '0',
                    'elements': copy.deepcopy(PRODUCT_STATES[state]),
                })
        segments.append({
            'type': 'group', 'name': 'flow-seg-%d' % n, 'id': 'flow-seg-%d' % n,
            'transform': 'translate(%d, %d)' % (x0, FLOW_Y),
            'elements': children,
        })
    return segments


def flow_bindings():
    """Queue-item opacity, one binding per slot."""
    out = {}
    for n, _x0, _length, _state, _var, acc, _travellers in FLOW_SEGMENTS:
        if not acc:
            continue
        for k, threshold in enumerate(QUEUE_THRESHOLDS):
            out['queue-%d-%d' % (n, k)] = [('opacity', expr_binding(
                'if(toDouble({view.custom.%s}) >= %s, 1, 0)' % (acc, threshold)))]
    return out


def segment_play_expr(n):
    """A segment runs only if its machine is turning AND it has somewhere to put
    product. Either condition alone leaves product moving into a full buffer."""
    for num, _x0, _len, _state, var, acc, _t in FLOW_SEGMENTS:
        if num != n:
            continue
        prop, nominal, extra = dict(
            (p, (c, nom, ex)) for p, c, nom, ex in MOTION)[var]
        conds = ['toDouble({view.custom.%s}) / %s < %s' % (prop, nominal, STALL_FRACTION)]
        if extra:
            conds.insert(0, extra)
        if acc:
            conds.append('toDouble({view.custom.%s}) >= %s' % (acc, FULL_BUFFER))
        return 'if(%s, "paused", "running")' % ' || '.join(conds)
    raise KeyError(n)

# var prefix -> (custom prop, nominal value, extra pause condition or None)
MOTION = [
    ('kit',  'kConv',    18.0, None),
    ('mix',  'mCurrent', 34.0, None),
    ('form', 'fCycle',   58.0, None),
    ('cook', 'cBelt',    14.0, None),
    ('pkg',  'pBelt',    95.0, '{view.custom.pBroken}'),
]

# Below this fraction of nominal the station reads as stopped, not merely slow.
# During HOLD the stalled stations sit at 0.08-0.17 of nominal (oven belt and
# kitting conveyor both drop to 1.5), so this freezes the whole line rather than
# leaving it twitching, which is what "line down" should look like.
STALL_FRACTION = 0.20

# Animation rate is quantised to steps of this size. Changing animation-duration
# on a running CSS animation makes it JUMP -- currentTime is preserved but the
# progress fraction is not -- and these rates are recomputed at 1 Hz off a noisy
# sine, so an unquantised rate re-times every animation every second and the
# whole mimic visibly stutters. Quantised, normal operation holds a rock-steady
# 1.00 and the rate only moves when the process genuinely changes speed.
RATE_STEP = 0.25


def rate_expr(prop, nominal):
    """Animation rate as a multiple of nominal, quantised and clamped.

    CSS divides each element's own base duration by this, so one variable per
    station drives every animation on that station whatever its base duration.
    """
    steps = 1.0 / RATE_STEP
    return ('numberFormat(max(%s, min(2.0, '
            'round(toDouble({view.custom.%s}) / %s * %s, 0) / %s)), "0.00")'
            % (RATE_STEP, prop, nominal, steps, steps))


def play_expr(prop, nominal, extra):
    stalled = 'toDouble({view.custom.%s}) / %s < %s' % (prop, nominal, STALL_FRACTION)
    if extra:
        stalled = '%s || %s' % (extra, stalled)
    return 'if(%s, "paused", "running")' % stalled


CSS_BEGIN = ('/* >>> alarm-flood mimic motion '
             '(generated by scripts/wire_alarm_flood_svg.py -- do not hand-edit) */')
CSS_END = '/* <<< alarm-flood mimic motion */'

PRESS_PERIOD = '%.4fs' % FLOW_INTERVAL
PRESS_DELAY = '%.4fs' % (-FLOW_INTERVAL / 2.0)
"""A press bottoms out halfway through its cycle (the 50%% keyframe), so running
it at exactly one product-interval and starting it half a cycle early puts the
bottom of the downstroke on the moment a product crosses the machine centre --
which is also the boundary between two flow segments."""

# (id suffix, duration, keyframe, rate var, play var, delay, rotates about centre)
MOTION_RULES = [
    ('conv-b > g',         SPIN(2.0),   'af-spin',    'form', 'form', None, True),
    ('conv-c > g',         SPIN(2.0),   'af-spin',    'cook', 'cook', None, True),
    ('conv-d > g',         SPIN(2.0),   'af-spin',    'pkg',  'pkg',  None, True),
    ('belt-mixing > g',    SPIN(2.0),   'af-spin',    'mix',  'mix',  None, True),
    ('belt-forming > g',   SPIN(2.0),   'af-spin',    'form', 'form', None, True),
    ('belt-cooking > g',   SPIN(2.0),   'af-spin',    'cook', 'cook', None, True),
    ('belt-packaging > g', SPIN(2.0),   'af-spin',    'pkg',  'pkg',  None, True),
    # Sprocket, crank, rod and sealer are one assembly on one shaft: same
    # period, same delay, same play var. See the cam drive notes above.
    ('pkg-rotor',   PRESS_PERIOD, 'af-spin',   'pkg',  'seg3', PRESS_DELAY, True),
    ('pkg-crank',   PRESS_PERIOD, 'af-spin',   'pkg',  'seg3', PRESS_DELAY, True),
    ('pkg-camrod',  PRESS_PERIOD, 'af-cam-30', 'pkg',  'seg3', PRESS_DELAY, False),
    ('kit-arm-1',          SPIN(2.0),   'af-bob-30',  'kit',  'kit',  None, False),
    ('kit-arm-2',          SPIN(2.4), 'af-bob-20',  'kit',  'kit',  None, False),
    # Presses are locked to the product cadence, and to the play-state of the
    # segment feeding them, so press and product cannot drift out of phase.
    ('form-piston', PRESS_PERIOD, 'af-bob-55', 'form', 'seg1', PRESS_DELAY, False),
    ('form-press',  PRESS_PERIOD, 'af-bob-55', 'form', 'seg1', PRESS_DELAY, False),
    ('pkg-sealer',  PRESS_PERIOD, 'af-cam-30', 'pkg',  'seg3', PRESS_DELAY, False),
    ('flow-chute-1',       SPIN(1.0),   'af-dash-18', 'kit', 'kit',  None, False),
    ('flow-chute-2',       SPIN(1.0),   'af-dash-26', 'kit', 'kit',  None, False),
    ('mix-wave',           SPIN(2.0),   'af-bob-4',   'mix', 'mix',  None, False),
]


# --------------------------------------------------------------------------
# Phase resync
# --------------------------------------------------------------------------
# animation-play-state: paused freezes an animation IN PLACE and keeps its own
# currentTime -- which is exactly what the mimic wants while a station is down,
# and exactly what breaks it afterwards. Each conveyor segment pauses and
# resumes at a different moment (that IS the cascade), so after one flood the
# four segments are permanently at different fractions of their cycle. The
# product handoff at a machine centre is only seamless while every segment is
# at the SAME fraction: a lagging downstream segment shows up as a ball
# reaching the former, a beat of nothing, then a disc appearing. A second run
# widens the gap; a page refresh cures it, because a refresh restarts every
# animation at 0.
#
# Measured on the live page immediately after a refresh: segments 1-3 all read
# progress 0.309 and segment 4 reads 0.919, which is 3 x 0.309 wrapped -- one
# uniform product stream straight through every boundary. Nothing keeps them
# there once they have been paused independently. Rate changes drift the same
# way (changing animation-duration keeps currentTime but not the progress
# fraction), so a run desyncs even without a full stop.
#
# CSS can only restart an animation by changing its animation-name, so every
# animation whose phase has to line up with another one is emitted twice
# (-a / -b) and takes its copy from a custom property keyed on the simulator
# phase. All of those variables live in the single expr-struct binding on
# props.style, so they flip in one style update and the whole group restarts in
# the same frame, back in phase.
#
# This also fires on NORMAL -> DEGRADING. Everything is in phase at that point,
# so it shifts the entire product stream by the same fraction of one interval:
# uniform, no seam. The transition that matters is the return to NORMAL -- end
# of RECOVERY, or a Reset All -- which is where the accumulated drift is thrown
# away.
RESYNC_IDS = frozenset([
    'form-piston', 'form-press',                            # locked to seg 1
    'pkg-rotor', 'pkg-crank', 'pkg-camrod', 'pkg-sealer',   # one shaft, seg 3
])

PHASE_TAG = '[default]Exchange/Alarm Flood/Simulator/Phase'

# Keyframe bodies, kept separate from their names so a resynced one can be
# emitted twice under two names with byte-identical bodies.
KEYFRAME_BODIES = collections.OrderedDict([
    ('af-spin',   'to  { transform: rotate(360deg); }'),
    ('af-bob-30', '50% { transform: translateY(30px); }'),
    ('af-bob-20', '50% { transform: translateY(20px); }'),
    # 55 carries the forming press head down to the belt line rather than
    # stopping 40px short of it, so it reads as pressing the product.
    ('af-bob-55', '50% { transform: translateY(55px); }'),
    ('af-bob-4',  '50% { transform: translateY(4px); }'),
    # Cosine, not a single 50% stop: this one has to track a rotating crank
    # pin, and a triangle wave would throw the pin out of the slot.
    ('af-cam-30', cam_body(2 * CAM_THROW)),
])


def gen_var(keyframe):
    """Custom property that names the live copy of a resynced keyframe."""
    return '--gen-%s' % keyframe[len('af-'):]


def gen_name(keyframe):
    """animation-name for a resynced rule: the -a copy is the seed fallback."""
    return 'var(%s, %s-a)' % (gen_var(keyframe), keyframe)


def gen_expr(keyframe):
    """-a during normal operation, -b in every other phase."""
    return ('case({%s},\n'
            '  "NORMAL", "%s-a",\n'
            '  "%s-b")' % (PHASE_TAG, keyframe, keyframe))


def alarm_rule(element_id, key, period):
    """CSS rule for one alarm indicator: invisible until the mask names it."""
    return (
        '[id$="-%s"] {\n'
        '\topacity: 0;\n'
        '\tanimation: var(--%s-alarm, none) %s ease-in-out infinite;\n'
        '}' % (element_id, key, period))


def resync_keyframes():
    """base keyframe name -> body, for every keyframe that has to stay in phase
    with another one: the product streams and the presses locked to them."""
    out = collections.OrderedDict()
    for suffix, _dur, keyframe, _rate, _play, _delay, _spins in MOTION_RULES:
        if suffix in RESYNC_IDS:
            out[keyframe] = KEYFRAME_BODIES[keyframe]
    for n, _x0, length, _state, _var, _acc, _t in FLOW_SEGMENTS:
        out['af-run-seg%d' % n] = (
            'from { transform: translateX(0); } '
            'to   { transform: translateX(%gpx); }' % length)
    return out


def build_css():
    resync = resync_keyframes()
    # A base keyframe is only worth emitting if some rule still names it
    # directly -- af-spin does (every belt), af-bob-55 and af-cam-30 do not.
    named_directly = set(
        kf for suffix, _d, kf, _r, _p, _dl, _s in MOTION_RULES
        if suffix not in RESYNC_IDS)

    out = [
        CSS_BEGIN,
        '/* Perspective prefixes SVG ids per component instance, hence [id$=]. */',
        '/* Rate and play-state come from --<station>-rate / --<station>-play,   */',
        '/* bound on the SVG\'s parent flex container and inherited into the SVG. */',
        '',
    ]
    for name, body in KEYFRAME_BODIES.items():
        if name in named_directly:
            out.append('@keyframes %-11s { %s }' % (name, body))
    out += [
        '',
        '/* Resynced pairs. Identical bodies under two names: an animation can',
        '   only be restarted from CSS by renaming it, and these have to be put',
        '   back in phase after a flood has paused each of them at a different',
        '   moment. Which copy is live comes from --gen-*, all flipped together',
        '   by one expr-struct binding off the simulator phase. */',
    ]
    for name, body in resync.items():
        out.append('@keyframes %s-a { %s }' % (name, body))
        out.append('@keyframes %s-b { %s }' % (name, body))
    out += [
        '',
        # Alarm flash. Both stroke and opacity are set in every keyframe so the
        # colour is owned entirely by the animation -- these elements carry no
        # bound fill/opacity, so there is nothing for the flash to fight with.
        '@keyframes af-alarm-red   { 0%, 100% { stroke: #ff2222; opacity: 0.10; }',
        '                            50%      { stroke: #ff2222; opacity: 0.95; } }',
        '@keyframes af-alarm-amber { 0%, 100% { stroke: #ffaa00; opacity: 0.08; }',
        '                            50%      { stroke: #ffaa00; opacity: 0.60; } }',
        '@keyframes af-dash-18   { to  { stroke-dashoffset: -18; } }',
        '@keyframes af-dash-26   { to  { stroke-dashoffset: -26; } }',
        # Explicit `from` -- an implicit one would start from whatever transform
        # the element already carries and interpolate that away.
        '@keyframes af-flow      { from { transform: translateX(0); }',
        '                          to   { transform: translateX(1045px); } }',
        '',
        '/* NO transition: on any bound property. Perspective delivers a bound',
        '   value as a presentation ATTRIBUTE, and a CSS transition on such a',
        '   property pins the computed value at its initial value forever -- the',
        '   attribute updates, the screen never does. Measured: a gauge reading',
        '   scale(1, 0.992) still computed as its scale(1, 0.4) seed, and a',
        '   status lamp stayed green through a Fault. Applies to transform, fill',
        '   and opacity alike. Smoothing has to come from quantising the value,',
        '   not from easing between values. */',
        '',
    ]
    for suffix, dur, keyframe, rate_var, play_var, delay, spins in MOTION_RULES:
        if ' > ' in suffix:
            name, child = suffix.split(' > ')
            selector = '[id$="-%s"] > %s' % (name, child)
        else:
            selector = '[id$="-%s"]' % suffix
        # A resynced rule names its keyframe through --gen-*, so a phase change
        # swaps the name and restarts it. See the phase-resync notes.
        anim = gen_name(keyframe) if suffix in RESYNC_IDS else keyframe
        decls = [
            'animation: %s calc(%s / var(--%s-rate, 1)) linear infinite;'
            % (anim, dur, rate_var),
            'animation-play-state: var(--%s-play, running);' % play_var,
        ]
        if delay:
            decls.insert(1, 'animation-delay: calc(%s / var(--%s-rate, 1));'
                         % (delay, rate_var))
        if spins:
            decls += ['transform-box: fill-box;', 'transform-origin: 50% 50%;']
        out.append('%s {\n\t%s\n}' % (selector, '\n\t'.join(decls)))

    # Alarm indicators. animation-name comes from the mask, so `none` falls back
    # to opacity 0 and there is no frozen mid-flash state to clean up.
    out.append('')
    for key, _station_id, halo_id in ALARM_HALOS:
        out.append(alarm_rule(halo_id, key, '1s'))
    out.append(alarm_rule(DRIVE_RING_ID, DRIVE_RING_KEY, '0.7s'))

    # Travelling product, one stream per conveyor segment. Each segment has its
    # own travel distance, so it gets its own keyframe -- emitted as an -a/-b
    # pair with the rest of the resync group above.
    out.append('')
    for n, _x0, length, _state, var, _acc, travellers in FLOW_SEGMENTS:
        duration = length / FLOW_SPEED
        for i in range(travellers):
            out.append(
                '[id$="-flow-%d-%d"] {\n'
                '\tanimation: %s calc(%.4fs / var(--%s-rate, 1)) linear infinite;\n'
                '\tanimation-delay: calc(%.4fs / var(--%s-rate, 1));\n'
                '\tanimation-play-state: var(--seg%d-play, running);\n'
                '}' % (n, i, gen_name('af-run-seg%d' % n), duration, var,
                       -duration * i / travellers, var, n))
    out.append(CSS_END)
    return '\n'.join(out) + '\n'


# --------------------------------------------------------------------------

def dump(obj):
    """Serialize exactly the way the gateway does.

    Ignition writes these resources with Gson's HTML-safe escaping and no
    trailing newline. Matching it keeps the diff to the lines actually changed
    and stops the next gateway save from rewriting the whole file.
    """
    out = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    for ch in u'<>&=\'':
        out = out.replace(ch, u'\\u%04x' % ord(ch))
    return out


def node_at(elements, path):
    node = elements[path[0]]
    for i in path[1:]:
        node = node['elements'][i]
    return node


def find_by_id(elements, element_id):
    """Depth-first search for an element by id.

    Everything below is anchored on ids rather than absolute indices, because
    removing the header and status strip renumbers every top-level element.
    """
    for node in elements:
        if not isinstance(node, dict):
            continue
        if node.get('id') == element_id:
            return node
        found = find_by_id(node.get('elements') or [], element_id)
        if found is not None:
            return found
    return None


def find_use(elements, href, x=None):
    """Depth-first search for a <use> of a given symbol, optionally at an x."""
    for i, node in enumerate(elements):
        if not isinstance(node, dict):
            continue
        if node.get('type') == 'use' and node.get('href') == href \
                and (x is None or node.get('x') == x):
            return elements, i
        found = find_use(node.get('elements') or [], href, x)
        if found is not None:
            return found
    return None


# Chrome that duplicates what the page already shows above the mimic: the
# title block, and the phase/stage readout strip along the bottom.
REMOVED_TEXT = ('AUTOMATED FOOD PROCESSING LINE',
                'CONTINUOUS INDUSTRIAL MANUFACTURING SEQUENCE')
REMOVED_IDS = ('sim-phase-dot', 'sim-phase-text', 'sim-stage-text')


def is_chrome(node):
    if not isinstance(node, dict):
        return False
    if node.get('id') in REMOVED_IDS:
        return True
    text = (node.get('text') or '').strip()
    if any(t in text for t in REMOVED_TEXT):
        return True
    # The pill the status readout sat on.
    return (node.get('type') == 'rect' and node.get('x') == '500'
            and node.get('y') == '800' and node.get('width') == '600')


def main():
    with io.open(VIEW, encoding='utf-8') as fh:
        view = json.load(fh)

    svg = view['root']['children'][1]['children'][0]['children'][0]['children'][0]
    assert svg['type'] == 'ia.shapes.svg', svg['type']
    els = svg['props']['elements']

    symbols = {}
    for node in els[0]['elements']:
        if node.get('id'):
            symbols[node['id']] = node

    # --- 0. strip the duplicated title block and status strip -------------
    els[:] = [e for e in els if not is_chrome(e)]

    # --- 1. gauges -------------------------------------------------------
    for station_id, fill_id, caption in GAUGES:
        station = find_by_id(els, station_id)
        station['elements'] = [e for e in station['elements'] if not _is_gauge(e)]
        station['elements'].append(gauge_group(fill_id, caption))

    # --- 2. ids for the elements CSS targets ------------------------------
    # Before inlining, so anchors like packaging-belt-intact are still intact.
    for anchor_id, path, element_id in ASSIGN_IDS:
        anchor = find_by_id(els, anchor_id)
        if anchor is None:
            raise SystemExit('anchor %r not found' % anchor_id)
        node = node_at(anchor['elements'], path)
        node['id'] = element_id
        node['name'] = element_id

    # --- 2a. alarm halos, one per station --------------------------------
    # Replaced wholesale each run, like the gauges, so this stays idempotent.
    for _key, station_id, halo_id in ALARM_HALOS:
        station = find_by_id(els, station_id)
        if station is None:
            raise SystemExit('station %r not found' % station_id)
        station['elements'] = [e for e in station['elements']
                               if e.get('id') != halo_id]
        station['elements'].append(halo_element(halo_id))

    # --- 2b. rebuild the packaging drive as a toothed sprocket ------------
    # Wholesale replacement of the group's children, so re-running is idempotent.
    rotor = find_by_id(els, 'pkg-rotor')
    if rotor is None:
        raise SystemExit('pkg-rotor not found')
    rotor['elements'] = rotor_elements()

    # --- 2c. cam drive between the sprocket and the sealer ----------------
    # Wholesale replacement again: drop whatever this step produced last run
    # (and the generated SVG's bent yellow stroke, if this is the first run),
    # then rebuild. Order matters -- the yoke has to sit over the sprocket face
    # and the crank pin over the yoke, or the pin looks like it is behind the
    # slot it is supposed to be riding in. Everything after this in the group
    # (the sealer housing, the guide rails, the belt) draws over the rod, which
    # is what makes the rod read as running down inside the machine.
    pkg = find_by_id(els, 'station-packaging')
    if pkg is None:
        raise SystemExit('station-packaging not found')
    cx, cy = cam_self_check()
    if abs(cx - ROTOR_CX) > 0.001 or abs(cy - ROTOR_CY) > 0.001:
        raise SystemExit('crank bbox centre %.3f,%.3f is not the shaft axis'
                         % (cx, cy))
    pkg['elements'] = [
        e for e in pkg['elements']
        if e.get('id') not in ('pkg-camrod', 'pkg-crank')
        and e.get('d') != LEGACY_HANGER_D
    ]
    at = [i for i, e in enumerate(pkg['elements'])
          if e.get('id') == 'pkg-rotor'][0] + 1
    pkg['elements'][at:at] = [
        {'type': 'group', 'name': 'pkg-camrod', 'id': 'pkg-camrod',
         'elements': cam_rod_elements()},
        {'type': 'group', 'name': 'pkg-crank', 'id': 'pkg-crank',
         'elements': cam_crank_elements()},
    ]

    # --- 3. inline the <use> instances that must animate independently ----
    for anchor_id, href, x, group_id in INLINE_USES:
        if find_by_id(els, group_id) is not None:
            continue  # already inlined by a previous run
        scope = els if anchor_id is None else find_by_id(els, anchor_id)['elements']
        found = find_use(scope, href, x)
        if found is None:
            raise SystemExit('no <use %s> for %s' % (href, group_id))
        parent, idx = found
        node = parent[idx]
        parent[idx] = {
            'type': 'group', 'name': group_id, 'id': group_id,
            'transform': 'translate(%s, %s)'
                         % (node.get('x', '0'), node.get('y', '0')),
            'elements': copy.deepcopy(symbols[href.lstrip('#')]['elements']),
        }

    # Rebuild the product flow wholesale -- the original markers and their SMIL
    # cross-fade are replaced entirely (see the Product flow notes above).
    find_by_id(els, 'line-flow-indicator')['elements'] = build_flow_elements()

    # --- 4. locate every bindable id, post-mutation -----------------------
    paths = {}

    def walk(node, path):
        if isinstance(node, dict):
            if node.get('id'):
                paths[node['id']] = path
            for i, child in enumerate(node.get('elements') or []):
                walk(child, '%s.elements[%d]' % (path, i))

    for i, el in enumerate(els):
        walk(el, 'props.elements[%d]' % i)

    bindings = dict(ELEMENT_BINDINGS)
    bindings.update(flow_bindings())

    missing = [k for k in bindings if k not in paths]
    if missing:
        raise SystemExit('ids not found in SVG tree: %s' % missing)

    # --- 5. view.custom ---------------------------------------------------
    custom = view.setdefault('custom', {})
    prop_config = view.setdefault('propConfig', {})
    # Drop the stale placeholder whose aliases pointed at the wrong tags.
    custom.pop('tagPaths', None)
    prop_config.pop('custom.tagPaths', None)

    # Every custom prop here is PRIVATE: it only feeds the element and style
    # bindings below, which evaluate on the gateway, so there is no reason to
    # ship ~20 values a second to the browser as well.
    custom['line'] = 'Site1/Area1/Line1'
    prop_config['custom.line'] = private(tag_binding(TARGET_LINE_TAG))

    # One poll of real alarm state feeds every alarm indicator on the mimic.
    custom[ALARM_MASK_PROP] = ''
    prop_config['custom.' + ALARM_MASK_PROP] = private({
        'binding': {
            'config': {'expression': 'runScript("exchange.alarmFlood.control.stationAlarmMask", %d)'
                                     % ALARM_MASK_POLL_MS},
            'type': 'expr',
        }
    })

    for prop, (rel, seed) in CUSTOM_TAGS.items():
        custom[prop] = seed
        prop_config['custom.' + prop] = private(tag_binding(
            '[default]Exchange/Alarm Flood/{line}/' + rel,
            mode='indirect',
            refs={'line': '{view.custom.line}'},
        ))

    # --- 6. element bindings ---------------------------------------------
    svg_config = svg.setdefault('propConfig', {})
    for key in list(svg_config):
        if key.startswith('props.elements['):
            del svg_config[key]

    def element_at(dotted):
        node = svg['props']
        for part in dotted.split('.')[1:]:
            name, _, idx = part.partition('[')
            node = node[name]
            if idx:
                node = node[int(idx.rstrip(']'))]
        return node

    for el_id, entries in bindings.items():
        base = paths[el_id]
        node = element_at(base)
        for sub, binding in entries:
            if sub == 'fill.paint':
                # An element carrying fill.url ignores fill.paint -- swap it.
                node.setdefault('fill', {}).pop('url', None)
                node['fill'].setdefault('paint', '#666666')
            svg_config['%s.%s' % (base, sub)] = binding

    for fill_id, (prop, setpoint) in GAUGE_SETPOINTS.items():
        rect_path = paths[fill_id] + '.elements[0]'
        svg_config[rect_path + '.fill.paint'] = expr_binding(
            level_colour(prop, setpoint))

    # --- 7. CSS custom properties on the SVG's parent container -----------
    top = view['root']['children'][1]['children'][0]['children'][0]
    assert top['meta']['name'] == 'MimicRow', top['meta']['name']
    style = top['props'].setdefault('style', {})
    for key in list(style):
        if key.startswith('--') or key == '--belt-test':
            del style[key]
    top_config = top.setdefault('propConfig', {})
    for key in list(top_config):
        if key.startswith('props.style.--'):
            del top_config[key]

    # Perspective will not evaluate a binding whose propConfig key contains
    # `--`: the static value passes through to the DOM but the binding never
    # fires, so every variable stays pinned at its seed. Binding props.style as
    # a whole object with one expression-structure binding sidesteps that. The
    # container carries no other styling, so replacing the object is safe.
    top_config.pop('props.style', None)
    struct = {}
    for prefix, prop, nominal, extra in MOTION:
        style['--%s-rate' % prefix] = '1.00'
        style['--%s-play' % prefix] = 'running'
        struct['--%s-rate' % prefix] = rate_expr(prop, nominal)
        struct['--%s-play' % prefix] = play_expr(prop, nominal, extra)
    for key in ALARM_KEYS:
        style['--%s-alarm' % key] = 'none'
        struct['--%s-alarm' % key] = alarm_anim_expr(key)
    # A conveyor also stops when the buffer it discharges into is full, which is
    # what makes the backup walk upstream one segment at a time.
    for n, _x0, _length, _state, _var, _acc, _t in FLOW_SEGMENTS:
        style['--seg%d-play' % n] = 'running'
        struct['--seg%d-play' % n] = segment_play_expr(n)
    # Which copy of each resynced keyframe is live. These all flip on the same
    # style update, which is what puts the product stream back in phase when the
    # line returns to NORMAL. See the phase-resync notes.
    for keyframe in resync_keyframes():
        style[gen_var(keyframe)] = '%s-a' % keyframe
        struct[gen_var(keyframe)] = gen_expr(keyframe)
    top_config['props.style'] = {
        'binding': {'config': {'struct': struct, 'waitOnAll': True},
                    'type': 'expr-struct'}}

    with io.open(VIEW, 'w', encoding='utf-8') as fh:
        fh.write(dump(view))

    # --- 8. stylesheet ----------------------------------------------------
    with io.open(STYLESHEET, encoding='utf-8') as fh:
        css = fh.read()
    block = build_css()
    if CSS_BEGIN in css:
        head, rest = css.split(CSS_BEGIN, 1)
        _, tail = rest.split(CSS_END, 1)
        css = head + block.rstrip('\n') + tail
    else:
        css = css.rstrip('\n') + '\n\n' + block
    with io.open(STYLESHEET, 'w', encoding='utf-8') as fh:
        fh.write(css)

    print('gauges:            %d' % len(GAUGES))
    print('inlined <use>:     %d' % len(INLINE_USES))
    print('ids assigned:      %d' % len(ASSIGN_IDS))
    print('sprocket teeth:    %d' % GEAR_TEETH)
    print('alarm indicators:  %d' % len(ALARM_KEYS))
    print('custom props:      %d' % (len(CUSTOM_TAGS) + 1))
    print('element bindings:  %d' % len(svg_config))
    print('css variables:     %d' % len(top_config))
    print('stylesheet block:  %d lines' % block.count('\n'))


if __name__ == '__main__':
    main()
