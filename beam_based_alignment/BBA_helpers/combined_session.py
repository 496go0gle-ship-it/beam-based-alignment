"""Record and restore the settings of the corrector + quadrupole-mover BBA (BBA_corrector_and_mover_GUI.py).

Each START gets its own session folder (BBA_<interface><time>_session_settings). In it:
  combined_bba_settings.json  every option of the window, written when START is pressed (before anything
                              moves) and completed at the end with what was used and how the run ended
                              ("running" left in the file means the program did not reach the end)
  bba_log.txt                 every line of the log window, as it is written

"Restore desired session's settings" reads combined_bba_settings.json back into the window.
"""

import json
import os
import subprocess
from datetime import datetime

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QFileDialog, QMessageBox

SETTINGS_FILE = "combined_bba_settings.json"
LOG_FILE = "bba_log.txt"
SETTINGS_VERSION = 2


def _package_folder(module_name):
    import importlib
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    if getattr(module, "__file__", None):
        return os.path.dirname(os.path.abspath(module.__file__))
    paths = list(getattr(module, "__path__", []))  # namespace package: no __file__
    return os.path.abspath(paths[0]) if paths else None


def code_versions():
    """{repository: "<commit> (<branch>)", with " + local changes" if files differ from it} for the code BBA runs on."""
    folders = {"beam-based-alignment": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
               "response-matrix": _package_folder("response_matrix"),
               "machine-interfaces": _package_folder("machine_interfaces"),
               "machine-interfaces (ATF2 backend)": _package_folder("machine_interfaces_atf2")}
    out = {}
    for name, folder in folders.items():
        if not folder:
            continue
        try:
            def git(*args):
                return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=5).stdout.strip()
            commit = git("rev-parse", "--short", "HEAD")
            if not commit:
                out[name] = "not a git checkout"
                continue
            branch = git("rev-parse", "--abbrev-ref", "HEAD")
            dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
            out[name] = f"{commit} ({branch})" + (" + local changes" if dirty else "")
        except Exception as exc:
            out[name] = f"unknown ({exc})"
    return out


class CombinedSessionRecord:
    """Mixin for the combined BBA window: writes the settings record and the log file, restores settings."""

    # --- the record ---------------------------------------------------------------------
    def _checked(self, name):
        widget = getattr(self, name, None)
        return bool(widget.isChecked()) if widget is not None else None

    def _settings_snapshot(self):
        objective = self._objective()
        info = self._data_dirs.get("traj") or {}
        actuators = [self.correctors_list.item(i).text() for i in range(self.correctors_list.count())
                     if self.correctors_list.item(i).isSelected()]
        bpms = [str(self.bpms_list.item(i).data(Qt.ItemDataRole.UserRole) or self.bpms_list.item(i).text())
                for i in range(self.bpms_list.count()) if self.bpms_list.item(i).isSelected()]
        unit = getattr(self, "corrs_unit", "") or ""
        nsamples = getattr(self.interface, "nsamples", None)
        return {
            "settings_version": SETTINGS_VERSION,
            "interface": self.interface.get_name(),
            "interface_id": f"{type(self.interface).__module__}.{type(self.interface).__name__}",
            "trajectory_data": info.get("dir"),
            "actuators_selected": actuators,
            "bpms_selected": bpms,
            "actuator_weights": {name: float(w) for name, w in self.corrector_weights.items() if float(w) != 1.0},
            "weights": {"trajectory_hold": objective["w1"], "bpms_to_zero": objective["w2"],
                        "specific_bpm": objective["w3"], "specific_bpm_name": objective["spec_bpm"]},
            "rcond": objective["rcond"],
            "beta": objective["beta"],
            "gain": objective["gain"],
            "iterations": objective["iters"],
            "transmission_threshold_percent": objective["transmission"],
            "corrector_unit": unit,
            "corrector_max_strength": [self.max_horizontal_current_spinbox.value(), self.max_vertical_current_spinbox.value()],
            "mover_max_range_um": [self.mover_range_x_spinbox.value(), self.mover_range_y_spinbox.value()],
            "orbit_metric": self._metric(),
            "remove_coupling": self._checked("remove_coupling_checkbox"),
            "jitter_subtraction": self._checked("subtract_jitter_checkbox"),
            "triangular_correctors": self._checked("triangular_checkbox"),
            "bpm_samples": int(nsamples) if nsamples is not None else None,
            "corrector_writing": self._corrector_writing(unit),
            "code": code_versions(),
        }

    def _corrector_writing(self, unit):
        return {}

    def _record_path(self):
        return os.path.join(self._session_dir, SETTINGS_FILE)

    def _write_record(self):
        record = getattr(self, "_run_record", None)
        if record is None or not getattr(self, "_session_dir", None):
            return
        try:
            os.makedirs(self._session_dir, exist_ok=True)
            with open(self._record_path(), "w") as file:
                json.dump(record, file, indent=2, default=str)
        except Exception as exc:
            print(f"WARNING: could not write {self._record_path()}: {exc}")

    def _begin_run_record(self):
        """START pressed: write every option before anything moves."""
        try:
            settings = self._settings_snapshot()
        except Exception as exc:  # the record must never stop the correction
            settings = {"error": f"could not read the settings: {exc}"}
            self.log(f"WARNING: settings not fully recorded ({exc})")
        self._run_record = {"run": {"started_at": datetime.now().isoformat(timespec="seconds"), "status": "running",
                                    "iterations_done": 0},
                            "settings": settings}
        self._write_record()
        self.log(f"Settings recorded in {self._record_path()}")

    def _update_run_record(self, **used):
        if getattr(self, "_run_record", None) is None:
            return
        self._run_record.setdefault("used", {}).update(used)
        self._write_record()

    def _end_run_record(self, status, reason=""):
        if getattr(self, "_run_record", None) is None:
            return
        run = self._run_record["run"]
        run.update({"ended_at": datetime.now().isoformat(timespec="seconds"), "status": status})
        if reason:
            run["reason"] = reason
        self._write_record()
        self._run_record = None

    def _count_iteration(self):
        if getattr(self, "_run_record", None) is not None:
            self._run_record["run"]["iterations_done"] += 1
            self._write_record()

    # --- the log file -------------------------------------------------------------------
    def log(self, text):
        super().log(text)
        folder = getattr(self, "_session_dir", None)
        if folder and os.path.isdir(folder):
            try:
                with open(os.path.join(folder, LOG_FILE), "a", encoding="utf-8") as file:
                    file.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
            except OSError:
                pass

    # --- restoring ----------------------------------------------------------------------
    def load_session_settings(self, folder=None):
        if not isinstance(folder, str) or not folder:
            default_dir = os.path.expanduser("~/CERN-Flight_Simulator-Data/")
            folder = QFileDialog.getExistingDirectory(self, "Select a BBA session folder", default_dir)
            if not folder:
                return
        path = os.path.join(folder, SETTINGS_FILE)
        if not os.path.isfile(path):
            return super().load_session_settings(folder)  # sessions of BBA_GUI.py / BBA_QM_GUI.py
        try:
            with open(path) as file:
                record = json.load(file)
        except Exception as exc:
            QMessageBox.warning(self, "Load session", f"Could not read {path}:\n{exc}")
            return
        settings = record.get("settings", record)  # settings_version 1 (before 2026-11-20) kept them at the top
        notes = self._apply_settings_record(settings)
        if hasattr(self, "session_database_3"):
            self.session_database_3.setText(folder)
        run = record.get("run", {})
        head = [f"Restored the settings of {os.path.basename(os.path.normpath(folder))}"]
        if run:
            head.append(f"Run started {run.get('started_at', '?')}, ended {run.get('ended_at', 'never (program did not finish)')}: "
                        f"{run.get('status', '?')}, {run.get('iterations_done', '?')} iteration(s)"
                        + (f" - {run['reason']}" if run.get("reason") else ""))
        elif record.get("saved_at"):
            head.append(f"Saved at {record['saved_at']}")
        message = "\n".join(head + [""] + notes)
        self.log(message.replace("\n", " | "))
        QMessageBox.information(self, "Load session", message)

    def _apply_settings_record(self, s):
        notes = []
        if s.get("interface") and s["interface"] != self.interface.get_name():
            notes.append(f"Note: recorded on interface {s['interface']}, this window uses {self.interface.get_name()}.")

        folder = s.get("trajectory_data")
        if folder:
            info = self._find_useful_files(os.path.expanduser(folder))
            if info.get("ok"):
                self._data_dirs["traj"] = info
                if hasattr(self, "trajectory_response_3"):
                    self.trajectory_response_3.setText(folder)
                self._current_inventory()
                notes.append(f"Trajectory data: {folder}")
            else:
                notes.append(f"Trajectory data NOT found, choose it again: {folder}")

        weights = s.get("actuator_weights") or {}
        if weights:
            self.corrector_weights.update({str(k): float(v) for k, v in weights.items()})

        names = s.get("actuators_selected")
        if names is None:  # settings_version 1: the columns that were used, e.g. "QM15FF:x"
            names = list(dict.fromkeys(str(label).split(":")[0] for label in s.get("columns", [])))
        items = {self.correctors_list.item(i).text(): self.correctors_list.item(i) for i in range(self.correctors_list.count())}
        self.correctors_list.clearSelection()
        for name in names:
            if name in items:
                items[name].setSelected(True)
        missing = [name for name in names if name not in items]
        notes.append(f"Actuators selected: {sum(name in items for name in names)}"
                     + (f" (not in this window: {', '.join(missing)})" if missing else ""))
        self._refresh_actuator_labels()

        bpm_names = s.get("bpms_selected", s.get("bpms"))
        if bpm_names is not None:
            wanted = set(map(str, bpm_names))
            self.bpms_list.clearSelection()
            found = set()
            for i in range(self.bpms_list.count()):
                item = self.bpms_list.item(i)
                name = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
                if name in wanted or item.text() in wanted:
                    item.setSelected(True)
                    found.add(name)
            notes.append(f"BPMs selected: {len(found)}" + (" (none = every BPM)" if not bpm_names else "")
                         + (f" (not in this window: {', '.join(sorted(wanted - found))})" if wanted - found else ""))

        w = s.get("weights", {})
        for widget, value in ((self.lineEdit, w.get("trajectory_hold")), (self.lineEdit_2, w.get("bpms_to_zero")),
                              (self.lineEdit_3, w.get("specific_bpm")), (self.lineEdit_4, s.get("rcond")),
                              (self.lineEdit_5, s.get("iterations")), (self.lineEdit_6, s.get("gain")),
                              (self.lineEdit_beta, s.get("beta"))):
            if value is not None:
                widget.setText(f"{value:g}" if isinstance(value, float) else str(value))
        if s.get("transmission_threshold_percent") is not None:
            self.transmission_value.setText(f"{float(s['transmission_threshold_percent']) / 100.0:g}")
        if hasattr(self, "_refresh_specific_bpm_candidates"):
            self._refresh_specific_bpm_candidates()
        spec = w.get("specific_bpm_name")
        if spec:
            index = self.specific_bpm_combo.findText(str(spec))
            if index >= 0:
                self.specific_bpm_combo.setCurrentIndex(index)
            else:
                notes.append(f"Specific BPM {spec} is not among the selected BPMs.")

        for spinboxes, values in (((self.max_horizontal_current_spinbox, self.max_vertical_current_spinbox), s.get("corrector_max_strength")),
                                  ((self.mover_range_x_spinbox, self.mover_range_y_spinbox), s.get("mover_max_range_um"))):
            for spinbox, value in zip(spinboxes, values or ()):
                spinbox.setValue(float(value))
        if s.get("orbit_metric"):
            index = self.metric_combo.findData(s["orbit_metric"])
            if index >= 0:
                self.metric_combo.setCurrentIndex(index)
        for name, key in (("remove_coupling_checkbox", "remove_coupling"), ("subtract_jitter_checkbox", "jitter_subtraction"),
                          ("triangular_checkbox", "triangular_correctors")):
            if s.get(key) is not None and getattr(self, name, None) is not None:
                getattr(self, name).setChecked(bool(s[key]))
        if s.get("bpm_samples") and hasattr(self, "nsamples_input"):
            self.nsamples_input.setText(str(int(s["bpm_samples"])))
        notes.append("Weights, rcond, beta, gain, iterations, transmission, limits, orbit metric and options restored.")
        return notes
