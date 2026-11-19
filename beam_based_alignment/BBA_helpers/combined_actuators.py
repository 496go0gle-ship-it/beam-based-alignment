"""Helpers of the corrector + quadrupole-mover BBA that do not need a window.

- selection files: read them, and match the names to the actuator list (the same rules as
  SysID_corrector_and_mover_GUI.py, so one file works in both applications);
- data inventory: which correctors and movers a SysID folder holds measurements for.
"""

import os
import re

MOVER_TAG = re.compile(r"^(.+)_([xy])$")


def read_selection_file(path):
    """Names in a selection file: one or more per line, separated by commas/spaces; '#' starts a comment."""
    names = []
    with open(path) as file:
        for line in file:
            names += [token for token in re.split(r"[,;\s]+", line.split("#", 1)[0]) if token]
    return names


def match_selection(requested, offered, movers, quadrupoles=()):
    """Match names from a selection file to the actuators offered in the list.

    Accepted spellings for a mover: QM15FF, qm15ff, QM15FF:x, QM15FF_y, and MQM15FF (the BPM on it).
    Returns (found, ignored): found in the order requested, ignored as {name: reason}.
    """
    offered = [str(name) for name in offered]
    by_key = {name.upper(): name for name in offered}
    mover_keys = {str(name).upper() for name in movers}
    quad_keys = {str(name).upper() for name in quadrupoles}
    found, ignored = [], {}
    for raw in requested:
        key = str(raw).strip().upper()
        candidates = [key]
        plane = re.match(r"^(.+?)[:_]([XY])$", key)
        if plane:
            candidates.append(plane.group(1))
        candidates += [candidate[1:] for candidate in list(candidates) if candidate.startswith("M")]
        match = next((by_key[c] for c in candidates if c in by_key and (c == key or c in mover_keys)), None)
        if match is not None:
            if match not in found:
                found.append(match)
        elif any(c in quad_keys for c in candidates):
            ignored[raw] = "quadrupole without a usable mover in this interface"
        else:
            ignored[raw] = "not in this window's list"
    return found, ignored


def ignored_text(ignored):
    if not ignored:
        return ""
    return "Not selected:\n" + "\n".join(f"  {name}: {reason}" for name, reason in ignored.items())


def selection_report(filename, found, ignored, movers):
    """Text shown (and printed) after loading a selection file."""
    mover_set = set(movers)
    correctors = [name for name in found if name not in mover_set]
    chosen_movers = [name for name in found if name in mover_set]
    lines = [f"Loaded {os.path.basename(filename)}:",
             f"  correctors ({len(correctors)}): {', '.join(correctors) or 'none'}",
             f"  quadrupole movers ({len(chosen_movers)}): {', '.join(chosen_movers) or 'none'}"]
    if ignored:
        lines.append(ignored_text(ignored))
        if any("mover" in reason for reason in ignored.values()) and movers:
            lines.append(f"  Movers offered here: {', '.join(movers)}")
    return "\n".join(lines)


def data_inventory(pairs):
    """Measured excitations in a SysID folder.

    Returns (correctors, movers): correctors as {name: number of +/- pairs},
    movers as {name: {"x": pairs, "y": pairs}}.
    """
    correctors, movers = {}, {}
    for pair in pairs:
        tag = str(pair[2]) if len(pair) > 2 else ""
        match = MOVER_TAG.match(tag)
        if match:
            planes = movers.setdefault(match.group(1), {"x": 0, "y": 0})
            planes[match.group(2)] += 1
        elif tag:
            correctors[tag] = correctors.get(tag, 0) + 1
    return correctors, movers


def data_status(name, is_mover, inventory):
    """(usable, short text) for one actuator, given data_inventory(); inventory None = no folder loaded."""
    if inventory is None:
        return None, ""
    correctors, movers = inventory
    if is_mover:
        planes = movers.get(name)
        if not planes:
            return False, "no data"
        measured = [plane for plane in ("x", "y") if planes[plane]]
        if len(measured) == 2:
            return True, "data x,y"
        return False, f"{measured[0]} only" if measured else "no data"
    return (True, "data") if correctors.get(name) else (False, "no data")


def encoder_signs(pairs):
    """Encoder change / setpoint change of every measured mover plane, from its first +/- pair.

    Returns {(name, "x"|"y"): ratio}; about +1 normally, about -1 where the encoder (xact/yact)
    counts opposite to the setpoint (ATF2: QF1FF and QD0FF in x on 2026-11-19).
    """
    import numpy as np
    from machine_interfaces.Backend.State import State

    ratios = {}
    for pair in pairs:
        tag = str(pair[2]) if len(pair) > 2 else ""
        match = MOVER_TAG.match(tag)
        if not match or (match.group(1), match.group(2)) in ratios:
            continue
        name, axis = match.groups()
        try:
            values = []
            for filename in pair[:2]:
                q = State(filename=filename).get_quadrupoles([name])
                values.append([float(np.asarray(q.get(f"{axis}{kind}", [np.nan]), dtype=float).ravel()[0]) for kind in ("des", "act")])
            (des_p, act_p), (des_m, act_m) = values
        except Exception:
            continue
        if np.isfinite(des_p - des_m) and des_p != des_m and np.isfinite(act_p - act_m):
            ratios[(name, axis)] = (act_p - act_m) / (des_p - des_m)
    return ratios
