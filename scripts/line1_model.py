"""Line 1 coffee roasting line - the single source of truth for the PLC exports.

This module declares the controller program behind the Tag Import Agent demo: a
ControlLogix processor running one MainProgram with a routine per machine. It
holds the controller-scoped tag database (117 tags) and the ladder logic those
tags appear in.

Two consumers read it, both through ``scripts/generate_line1_export.py``:

  1. ``reference/line1/Line1_ControllerTags_Export.CSV``  - Studio 5000 tag export
  2. ``reference/line1/Line1_MainProgram_Logic_Export.CSV`` - rung export

Change a member here and both follow. Never hand-edit the generated CSVs.

Naming is flat, which is what a real Logix controller tag database usually looks
like when the program predates UDTs::

    Line1_<Machine>_<Member>     per-machine tags
    Line1_<Name>                 line-wide tags

That flatness is the point of the demo: the repetition is there in the names and
datatypes, and the agent has to find it.

Scope matters and is not a detail. The tag export is **controller scope**. The
timers, counters, oneshots and raw analog words the rungs also reference are
**program scope** (MainProgram), so they are deliberately absent from the tag
export - exactly as they would be in a real controller-scope export. They are
listed in PROGRAM_SCOPE_NOTE so the generated files can say so out loud.
"""

LINE = "Line1"
CONTROLLER = "Line1_Roasting"
PROCESSOR = "1756-L83E/B ControlLogix 5580"
SOFTWARE_VERSION = "Studio 5000 Logix Designer v36.00"
EXPORT_DATE = "Thu Sep 10 07:41:12 2026"
OWNER = "Controls Engineering - Roasting"

MACHINES = ["Feeder", "Roaster", "Cooling", "Destoner", "Bagger"]

MACHINE_FUNCTION = {
    "Feeder": "Vibratory feeder meters green beans out of the hopper at a controlled kg/h",
    "Roaster": "Gas-fired rotating drum brings the bean mass up to profile temperature",
    "Cooling": "Forced-air cooling tray drops bean temperature to near ambient",
    "Destoner": "Gravity/air separation pulls stones and foreign material out of the stream",
    "Bagger": "Net-weigh filler and heat sealer produce finished 22.7 kg bags",
}

# ---------------------------------------------------------------------------
# 17 members that repeat identically on every machine. This repetition is the
# signal the Tag Import Agent is meant to detect and turn into a UDT.
#
# Datatypes are Logix atomic types: BOOL, SINT, INT, DINT, REAL, plus the STRING
# structure. RADIX is what Studio 5000 writes in the ATTRIBUTES column.
# ---------------------------------------------------------------------------
COMMON_MEMBERS = [
    # (member,          datatype, description)
    ("Running",         "BOOL",   "Machine is running in production"),
    ("Ready",           "BOOL",   "Machine ready to start"),
    ("Faulted",         "BOOL",   "Machine fault latched"),
    ("AutoMode",        "BOOL",   "Auto (true) or manual (false) mode"),
    ("EStopActive",     "BOOL",   "Emergency stop circuit tripped"),
    ("StartCmd",        "BOOL",   "Operator start command bit"),
    ("StopCmd",         "BOOL",   "Operator stop command bit"),
    ("DowntimeActive",  "BOOL",   "Machine is accruing downtime"),
    ("StateCode",       "INT",    "Machine state (0=Idle 1=Ready 2=Run 3=Fault 4=Down)"),
    ("FaultCode",       "INT",    "Active fault code, 0 when healthy"),
    ("DowntimeCode",    "INT",    "Downtime reason code, 0 when running"),
    ("PartCount",       "DINT",   "Total parts processed since last reset"),
    ("RejectCount",     "DINT",   "Total parts rejected since last reset"),
    ("CycleTime",       "REAL",   "Last completed cycle time (s)"),
    ("MotorSpeed",      "REAL",   "Main drive speed (RPM)"),
    ("MotorCurrent",    "REAL",   "Main drive current (A)"),
    ("StatusMessage",   "STRING", "Human-readable machine status"),
]

# ---------------------------------------------------------------------------
# 4 members unique to each machine. These are the tags that must NOT be forced
# into the shared UDT - the agent should keep them standalone beside the
# instance, or justify extending the UDT.
# ---------------------------------------------------------------------------
MACHINE_MEMBERS = {
    "Feeder": [
        ("HopperLevel",       "REAL", "Green bean hopper level (%)"),
        ("FeedRate",          "REAL", "Bean feed rate (kg/h)"),
        ("VibratorAmplitude", "REAL", "Vibratory feeder amplitude (mm)"),
        ("HopperLowLevel",    "BOOL", "Hopper below low-level switch"),
    ],
    "Roaster": [
        ("BeanTemp",     "REAL", "Bean mass temperature (degF)"),
        ("DrumRPM",      "REAL", "Roast drum rotation speed (RPM)"),
        ("BurnerOutput", "REAL", "Gas burner modulation (%)"),
        ("ExhaustTemp",  "REAL", "Roaster exhaust stack temperature (degF)"),
    ],
    "Cooling": [
        ("AirFlow",         "REAL", "Cooling air flow (CFM)"),
        ("OutletTemp",      "REAL", "Bean temperature leaving cooler (degF)"),
        ("FanRPM",          "REAL", "Cooling fan speed (RPM)"),
        ("CoolingComplete", "BOOL", "Cooling cycle complete for current batch"),
    ],
    "Destoner": [
        ("AirPressure",      "REAL", "Destoner air pressure (inH2O)"),
        ("StoneRejectCount", "DINT", "Stones and foreign material rejected"),
        ("ScreenVibration",  "REAL", "Separation screen vibration (mm/s)"),
        ("ScreenBlocked",    "BOOL", "Separation screen blockage detected"),
    ],
    "Bagger": [
        ("BagWeight",     "REAL", "Weight of bag currently filling (kg)"),
        ("BagCount",      "DINT", "Bags completed since last reset"),
        ("SealTemp",      "REAL", "Heat sealer jaw temperature (degF)"),
        ("FillValveOpen", "BOOL", "Fill valve commanded open"),
    ],
}

# ---------------------------------------------------------------------------
# 12 line-wide tags. Deliberately the four categories that must stay OUT of a
# per-machine UDT: ambient conditions, utility metering, order/shift identifiers,
# and line-level aggregates.
# ---------------------------------------------------------------------------
LINE_TAGS = [
    ("LineRunning",       "BOOL",   "Line 1 running in production"),
    ("LineState",         "INT",    "Line state (0=Down 1=Idle 2=Running 3=Changeover)"),
    ("ProductionOrder",   "STRING", "Active production order number"),
    ("ProductCode",       "STRING", "Active product / roast profile code"),
    ("ShiftNumber",       "INT",    "Current shift (1, 2 or 3)"),
    ("ShiftTargetCount",  "DINT",   "Good-bag target for the current shift"),
    ("LineGoodCount",     "DINT",   "Good bags produced on the line this shift"),
    ("LineRejectCount",   "DINT",   "Bags rejected on the line this shift"),
    ("LineSpeedSetpoint", "REAL",   "Line speed setpoint (bags/min)"),
    ("AmbientTemp",       "REAL",   "Plant floor ambient temperature (degF)"),
    ("AmbientHumidity",   "REAL",   "Plant floor relative humidity (%)"),
    ("PlantAirPressure",  "REAL",   "Compressed air header pressure (PSI)"),
]

# Studio 5000 writes a RADIX into ATTRIBUTES that depends on the datatype.
RADIX = {
    "BOOL": "Decimal",
    "SINT": "Decimal",
    "INT": "Decimal",
    "DINT": "Decimal",
    "REAL": "Float",
}

PROGRAM_SCOPE_NOTE = (
    "Program-scoped tags are not in this export. The rungs also reference "
    "MainProgram-scope TIMER, COUNTER, ONS storage bits and raw analog input "
    "words (names ending _Raw, _Tmr, _Ons, and the drive I/O aliases). Those "
    "live in the program tag database and are not part of a controller-scope "
    "export."
)

# ---------------------------------------------------------------------------
# Ladder logic. One routine per machine plus a line supervisor, called from
# MainRoutine. Rung text is Logix neutral text - the same thing you get by
# copying a rung out of the editor - so every instruction is a real mnemonic
# with its real operand order.
#
# {M} is substituted with the machine name.
# ---------------------------------------------------------------------------
COMMON_RUNGS = [
    ("Permissive. The machine is Ready when it is in Auto, the E-Stop circuit is "
     "healthy and no fault is latched.",
     "XIC(Line1_{M}_AutoMode)XIO(Line1_{M}_EStopActive)XIO(Line1_{M}_Faulted)"
     "OTE(Line1_{M}_Ready);"),

    ("Start/stop seal-in. StartCmd is a momentary HMI bit; Running seals itself "
     "in until StopCmd, loss of the permissive, or the line stops.",
     "[XIC(Line1_{M}_StartCmd),XIC(Line1_{M}_Running)]XIC(Line1_{M}_Ready)"
     "XIO(Line1_{M}_StopCmd)XIC(Line1_LineRunning)OTE(Line1_{M}_Running);"),

    ("Any non-zero fault code latches the machine faulted. FaultCode is written "
     "by the drive and safety fault handlers.",
     "NEQ(Line1_{M}_FaultCode,0)OTL(Line1_{M}_Faulted);"),

    ("Operator reset. Stop pressed with the fault condition already cleared "
     "unlatches, one shot so a held button cannot chatter the latch.",
     "XIC(Line1_{M}_StopCmd)EQU(Line1_{M}_FaultCode,0)ONS({M}_ResetOns)"
     "OTU(Line1_{M}_Faulted);"),

    ("Downtime accrues whenever the line is scheduled to run and this machine "
     "is not.",
     "XIC(Line1_LineRunning)XIO(Line1_{M}_Running)OTE(Line1_{M}_DowntimeActive);"),

    ("DowntimeCode is only meaningful while DowntimeActive. Force it to zero "
     "otherwise so the historian never stores a stale reason.",
     "XIO(Line1_{M}_DowntimeActive)MOV(0,Line1_{M}_DowntimeCode);"),

    ("HMI state code. 0=Idle 1=Ready 2=Run 3=Fault 4=Down, evaluated in "
     "ascending priority so the last match wins.",
     "XIO(Line1_{M}_Running)MOV(0,Line1_{M}_StateCode);"),

    ("",
     "[XIC(Line1_{M}_Ready),XIC(Line1_{M}_Running)]"
     "MOV(1,Line1_{M}_StateCode);"),

    ("",
     "XIC(Line1_{M}_Running)MOV(2,Line1_{M}_StateCode);"),

    ("",
     "XIC(Line1_{M}_Faulted)MOV(3,Line1_{M}_StateCode);"),

    ("",
     "XIC(Line1_{M}_DowntimeActive)MOV(4,Line1_{M}_StateCode);"),

    ("Cycle timer. Runs while the machine is producing; the done bit is the "
     "part complete pulse.",
     "XIC(Line1_{M}_Running)TON({M}_CycleTmr,?,?);"),

    ("Part complete: bump the retentive part counter and publish the measured "
     "cycle time in seconds.",
     "XIC({M}_CycleTmr.DN)ONS({M}_CycleOns)"
     "ADD(Line1_{M}_PartCount,1,Line1_{M}_PartCount)"
     "CPT(Line1_{M}_CycleTime,{M}_CycleTmr.ACC / 1000.0);"),

    ("Quality reject from the downstream inspection gate.",
     "XIC({M}_RejectGate)ONS({M}_RejectOns)"
     "ADD(Line1_{M}_RejectCount,1,Line1_{M}_RejectCount);"),

    ("Main drive telemetry off the PowerFlex 525 on the device network.",
     "SCP({M}_DriveSpeed_Raw,0,32767,0.0,1800.0,Line1_{M}_MotorSpeed);"),

    ("",
     "SCP({M}_DriveCurr_Raw,0,32767,0.0,30.0,Line1_{M}_MotorCurrent);"),

    ("Status string for the HMI banner. STRING is a structure, so it is copied "
     "rather than moved.",
     "XIC(Line1_{M}_Faulted)COP({M}_Msg_Faulted,Line1_{M}_StatusMessage,1);"),

    ("",
     "XIC(Line1_{M}_Running)COP({M}_Msg_Running,Line1_{M}_StatusMessage,1);"),
]

MACHINE_RUNGS = {
    "Feeder": [
        ("Hopper level transmitter, 4-20 mA into the 1756-IF8 in slot 4.",
         "SCP(Feeder_HopperLvl_Raw,0,32767,0.0,100.0,Line1_Feeder_HopperLevel);"),
        ("Low-level switch is derived rather than wired - below 12% there is not "
         "enough head for a stable feed rate.",
         "LES(Line1_Feeder_HopperLevel,12.0)OTE(Line1_Feeder_HopperLowLevel);"),
        ("Loss-in-weight feed rate, computed by the weigh controller and read "
         "over the network.",
         "SCP(Feeder_FeedRate_Raw,0,32767,0.0,800.0,Line1_Feeder_FeedRate);"),
        ("Vibratory amplitude follows the operator setpoint while running, and "
         "is driven to zero when it is not.",
         "XIC(Line1_Feeder_Running)MOV(Feeder_VibAmp_SP,Line1_Feeder_VibratorAmplitude);"),
    ],
    "Roaster": [
        ("Bean mass thermocouple, 1756-IT6I slot 6 channel 0.",
         "SCP(Roaster_BeanTC_Raw,0,32767,32.0,600.0,Line1_Roaster_BeanTemp);"),
        ("Exhaust stack thermocouple, same card channel 1.",
         "SCP(Roaster_StackTC_Raw,0,32767,32.0,800.0,Line1_Roaster_ExhaustTemp);"),
        ("Drum speed from the encoder on the drum gearbox.",
         "SCP(Roaster_DrumEnc_Raw,0,32767,0.0,80.0,Line1_Roaster_DrumRPM);"),
        ("Burner modulation. Bean temperature is the process variable; the loop "
         "is held in manual until the drum is up to speed.",
         "XIC(Line1_Roaster_Running)GRT(Line1_Roaster_DrumRPM,20.0)"
         "PID(Roaster_BurnerPID,Line1_Roaster_BeanTemp,0,Line1_Roaster_BurnerOutput,0,0,0,0);"),
    ],
    "Cooling": [
        ("Cooling air flow from the venturi transmitter.",
         "SCP(Cooling_Flow_Raw,0,32767,0.0,3000.0,Line1_Cooling_AirFlow);"),
        ("Bean temperature leaving the cooling tray.",
         "SCP(Cooling_OutletTC_Raw,0,32767,32.0,250.0,Line1_Cooling_OutletTemp);"),
        ("Cooling fan speed feedback.",
         "SCP(Cooling_FanEnc_Raw,0,32767,0.0,1200.0,Line1_Cooling_FanRPM);"),
        ("Batch is cool enough to discharge once the outlet is below 100 degF "
         "and has held there for the dwell time.",
         "LES(Line1_Cooling_OutletTemp,100.0)XIC(Line1_Cooling_Running)"
         "TON(Cooling_DwellTmr,?,?);"),
        ("",
         "XIC(Cooling_DwellTmr.DN)OTE(Line1_Cooling_CoolingComplete);"),
    ],
    "Destoner": [
        ("Separation air pressure, inches of water column.",
         "SCP(Destoner_Press_Raw,0,32767,0.0,8.0,Line1_Destoner_AirPressure);"),
        ("Stone reject counter, pulsed by the photo-eye on the reject chute.",
         "XIC(Destoner_StonePE)ONS(Destoner_StoneOns)"
         "ADD(Line1_Destoner_StoneRejectCount,1,Line1_Destoner_StoneRejectCount);"),
        ("Screen vibration from the accelerometer on the deck frame.",
         "SCP(Destoner_VibXmtr_Raw,0,32767,0.0,15.0,Line1_Destoner_ScreenVibration);"),
        ("Sustained high vibration means the deck is blinding over. Filtered "
         "with a timer so a single bounce does not stop the line.",
         "GRT(Line1_Destoner_ScreenVibration,9.0)TON(Destoner_BlockTmr,?,?);"),
        ("",
         "XIC(Destoner_BlockTmr.DN)OTE(Line1_Destoner_ScreenBlocked);"),
    ],
    "Bagger": [
        ("Net-weigh load cell on the fill head.",
         "SCP(Bagger_LoadCell_Raw,0,32767,0.0,30.0,Line1_Bagger_BagWeight);"),
        ("Fill valve stays open until the bag reaches target less the in-flight "
         "allowance.",
         "XIC(Line1_Bagger_Running)LES(Line1_Bagger_BagWeight,22.5)"
         "OTE(Line1_Bagger_FillValveOpen);"),
        ("Completed bag: count it once, on the transition.",
         "GEQ(Line1_Bagger_BagWeight,22.7)ONS(Bagger_BagOns)"
         "ADD(Line1_Bagger_BagCount,1,Line1_Bagger_BagCount);"),
        ("Sealer jaw temperature, RTD into the 1756-IR6I.",
         "SCP(Bagger_SealTC_Raw,0,32767,32.0,400.0,Line1_Bagger_SealTemp);"),
    ],
}

LINE_RUNGS = [
    ("The line is running only when all five machines are running. This is the "
     "aggregate the whole plant reports on - it belongs to the line, not to any "
     "one machine.",
     "XIC(Line1_Feeder_Running)XIC(Line1_Roaster_Running)XIC(Line1_Cooling_Running)"
     "XIC(Line1_Destoner_Running)XIC(Line1_Bagger_Running)OTE(Line1_LineRunning);"),

    ("Line state for the plant dashboard. 0=Down 1=Idle 2=Running 3=Changeover.",
     "XIO(Line1_LineRunning)MOV(0,Line1_LineState);"),

    ("",
     "XIC(Line_AllReady)XIO(Line1_LineRunning)MOV(1,Line1_LineState);"),

    ("",
     "XIC(Line1_LineRunning)MOV(2,Line1_LineState);"),

    ("",
     "XIC(Line_ChangeoverActive)MOV(3,Line1_LineState);"),

    ("Shift number from the wall clock. GSV reads the controller date and time "
     "into a DINT[7]; element 3 is the hour.",
     "GSV(WALLCLOCKTIME,,DateTime,Line_WallClock[0]);"),

    ("",
     "LIM(6,Line_WallClock[3],13)MOV(1,Line1_ShiftNumber);"),

    ("",
     "LIM(14,Line_WallClock[3],21)MOV(2,Line1_ShiftNumber);"),

    ("",
     "[LIM(22,Line_WallClock[3],23),LIM(0,Line_WallClock[3],5)]"
     "MOV(3,Line1_ShiftNumber);"),

    ("Shift rollover clears the accumulators and reloads the target from the "
     "schedule downloaded by the MES.",
     "XIC(Line_ShiftRollover)ONS(Line_ShiftOns)MOV(0,Line1_LineGoodCount)"
     "MOV(0,Line1_LineRejectCount)MOV(Sched_ShiftTarget,Line1_ShiftTargetCount);"),

    ("Good and reject bag counts for the line. Counted at the bagger discharge, "
     "after the checkweigher.",
     "XIC(Bagger_CheckweighPass)ONS(Line_GoodOns)"
     "ADD(Line1_LineGoodCount,1,Line1_LineGoodCount);"),

    ("",
     "XIC(Bagger_CheckweighFail)ONS(Line_RejectOns)"
     "ADD(Line1_LineRejectCount,1,Line1_LineRejectCount);"),

    ("Active order and product code, copied out of the order structure the MES "
     "writes over the message instruction below.",
     "COP(Order_Active.OrderNumber,Line1_ProductionOrder,1);"),

    ("",
     "COP(Order_Active.ProductCode,Line1_ProductCode,1);"),

    ("Line speed setpoint from the HMI, clamped to the mechanical limits of the "
     "bagger.",
     "LIM(0.5,Line_SpeedSP_HMI,6.0)MOV(Line_SpeedSP_HMI,Line1_LineSpeedSetpoint);"),

    ("Plant ambient and utility instrumentation. These are line-wide facts, "
     "measured once for the whole room - not per machine.",
     "SCP(Ambient_TempXmtr_Raw,0,32767,-40.0,150.0,Line1_AmbientTemp);"),

    ("",
     "SCP(Ambient_RH_Raw,0,32767,0.0,100.0,Line1_AmbientHumidity);"),

    ("",
     "SCP(Utility_AirPress_Raw,0,32767,0.0,150.0,Line1_PlantAirPressure);"),

    ("Order download from the MES, triggered on changeover.",
     "XIC(Line_ChangeoverActive)ONS(Line_OrderOns)MSG(Order_Download);"),
]

MAIN_RUNGS = [
    ("Scan order follows product flow, so a stop upstream is seen by the "
     "machines downstream of it in the same scan.",
     "JSR(Feeder_Control,0);"),
    ("", "JSR(Roaster_Control,0);"),
    ("", "JSR(Cooling_Control,0);"),
    ("", "JSR(Destoner_Control,0);"),
    ("", "JSR(Bagger_Control,0);"),
    ("Line aggregates and plant instrumentation last, once every machine has "
     "updated.",
     "JSR(Line_Supervisor,0);"),
]


class Tag(object):
    """One controller-scoped tag."""

    def __init__(self, name, datatype, description, machine):
        self.name = name
        self.datatype = datatype
        self.description = description
        self.machine = machine  # "" for line-wide tags

    def __repr__(self):
        return "<Tag %s %s>" % (self.name, self.datatype)


class Rung(object):
    """One rung of ladder, in the routine it belongs to."""

    def __init__(self, program, routine, number, comment, text):
        self.program = program
        self.routine = routine
        self.number = number
        self.comment = comment
        self.text = text


def build_tags():
    """Every controller tag on Line 1, in export order.

    Order is machine-major, which is how Studio 5000 writes an export sorted by
    name for this naming convention, and how a controller export reads: all of
    Feeder, then all of Roaster, and so on, then the line-wide tags.
    """
    tags = []
    for machine in MACHINES:
        for member, dtype, desc in COMMON_MEMBERS:
            tags.append(Tag("%s_%s_%s" % (LINE, machine, member), dtype, desc, machine))
        for member, dtype, desc in MACHINE_MEMBERS[machine]:
            tags.append(Tag("%s_%s_%s" % (LINE, machine, member), dtype, desc, machine))
    for member, dtype, desc in LINE_TAGS:
        tags.append(Tag("%s_%s" % (LINE, member), dtype, desc, ""))
    return tags


def build_rungs():
    """Every rung in MainProgram, routine by routine, in scan order."""
    rungs = []

    def add(routine, entries, machine=None):
        for i, (comment, text) in enumerate(entries):
            if machine:
                comment = comment.replace("{M}", machine)
                text = text.replace("{M}", machine)
            rungs.append(Rung("MainProgram", routine, i, comment, text))

    add("MainRoutine", MAIN_RUNGS)
    for machine in MACHINES:
        add("%s_Control" % machine,
            COMMON_RUNGS + MACHINE_RUNGS[machine], machine)
    add("Line_Supervisor", LINE_RUNGS)
    return rungs


EXPECTED_TAG_COUNT = (
    len(MACHINES) * len(COMMON_MEMBERS)              # 5 x 17 = 85
    + sum(len(v) for v in MACHINE_MEMBERS.values())  # 5 x 4  = 20
    + len(LINE_TAGS)                                 #        = 12
)                                                    # total  = 117


if __name__ == "__main__":
    tags = build_tags()
    rungs = build_rungs()
    assert len(tags) == EXPECTED_TAG_COUNT, (len(tags), EXPECTED_TAG_COUNT)
    print("%d controller tags, %d rungs" % (len(tags), len(rungs)))
    for t in tags:
        print("  %-34s %-6s %s" % (t.name, t.datatype, t.description))
