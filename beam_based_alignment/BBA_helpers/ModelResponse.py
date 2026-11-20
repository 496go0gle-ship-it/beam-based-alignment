"""Design (model) response data for BBA, computed in an RF-Track twin of the connected machine.

The twin is the one "Preview in simulation" uses: an RF-Track interface loaded with the
connected machine's magnet settings. When the connected interface is the real machine, the
twin converts corrector currents with the magnet calibration, so it reads and sets the
correctors in the same unit as the machine (A for ATF2).

Each selected corrector is kicked by +kick and -kick in the twin and the two snapshots are
saved with the SysID file names (DATA_<corrector>_p0000.pkl / DATA_<corrector>_m0000.pkl).
The folder therefore loads into BBA, Orbit Bump and the Response Matrix GUI exactly like a
measured SysID folder. Nothing is sent to the connected machine.
"""

import os
from datetime import datetime

import numpy as np


def _single_value(values):
    return float(np.ravel(np.asarray(values, dtype=float))[0])


def write_model_response(twin, correctors, bpms, directory, kick, log=print, should_stop=lambda: False):
    """Write a SysID-style DATA folder from the twin and return the correctors written.

    The twin's correctors are set back to their starting values after each pair.
    """
    if not kick or not np.isfinite(kick) or kick <= 0:
        raise ValueError(f"The model kick must be a positive number, got {kick!r}.")
    os.makedirs(directory, exist_ok=True)
    # SysID measures, and BBA corrects, with the sextupoles switched off (except where the
    # interface keeps them on, e.g. the damping ring): compute the model in the same optics.
    twin.switch_off_sextupoles()
    try:
        return _write_pairs(twin, correctors, bpms, directory, kick, log, should_stop)
    finally:
        twin.reset_sextupoles()


def _write_pairs(twin, correctors, bpms, directory, kick, log, should_stop):
    twin.get_state().save(filename=os.path.join(directory, "machine_status.pkl"))

    known = {str(name) for name in twin.get_correctors()["names"]}
    missing = [name for name in correctors if name not in known]
    if missing:
        log(f"Model response: the simulation has no corrector {', '.join(missing)}; left out.")

    written = []
    for name in correctors:
        if should_stop():
            log("Model response: stopped.")
            break
        if name not in known:
            continue
        initial = _single_value(twin.get_correctors([name])["bdes"])
        try:
            for sign, tag in ((1.0, "p"), (-1.0, "m")):
                twin.set_correctors([name], [initial + sign * kick])
                twin.get_state().save(filename=os.path.join(directory, f"DATA_{name}_{tag}0000.pkl"))
        finally:
            twin.set_correctors([name], [initial])
        written.append(name)

    recorded_bpms = {str(name) for name in twin.get_bpms()["names"]}
    with open(os.path.join(directory, "correctors.txt"), "w") as file:
        file.writelines(f"{name}\n" for name in written)
    with open(os.path.join(directory, "bpms.txt"), "w") as file:
        file.writelines(f"{name}\n" for name in bpms if name in recorded_bpms)
    with open(os.path.join(directory, "kicks.txt"), "w") as file:
        file.writelines(f"{name} {kick} {kick}\n" for name in written)
    return written


def model_response_folder(base_dir, interface_name, now=None):
    """Folder name next to the SysID folders: <interface>_<time>_ModelResponse."""
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return os.path.join(os.path.expanduser(base_dir), f"{interface_name}_{stamp}_ModelResponse")


def write_readme(directory, interface_name, twin, kick, kick_unit, written, energy_change=None):
    lines = [
        "MODEL RESPONSE - computed in simulation, not measured.",
        f"Connected interface: {interface_name}",
        f"Simulation: {type(twin).__module__}.{type(twin).__name__}",
        f"Created: {datetime.now().isoformat(timespec='seconds')}",
        f"Kick: +/-{kick:g} {kick_unit} per corrector, one pair each, noise as in the simulation",
        f"Correctors: {', '.join(written)}",
        "orbit/  : nominal beam (load as Trajectory data in BBA)",
    ]
    if energy_change is not None:
        lines.append(f"energy/ : simulation energy changed, dP/P = {energy_change:+.4g} (load as DFS data)")
    with open(os.path.join(directory, "README_MODEL.txt"), "w") as file:
        file.write("\n".join(lines) + "\n")
