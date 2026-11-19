"""BBA application that corrects the orbit with correctors and quadrupole movers together.

The trajectory data folder is a SysID folder holding corrector pairs
(DATA_<corrector>_<p|m>...) and quadrupole-mover pairs (DATA_<quad>_<x|y>_<p|m>...), as
written by SysID_corrector_and_mover_GUI.py. Both response matrices are computed from it
(the corrector one as in BBA_GUI.py, the mover one as in BBA_QM_GUI.py), restricted to the
BPMs they share and placed side by side:

    columns: H correctors | V correctors | movers in x | movers in y
    rows:    x at each BPM, then y at each BPM

Correctors and movers have different units (corrector strength vs um), so each column is
divided by the actuator's maximum (Max strength for correctors, Max mover range for
movers) before solving, and the solution is scaled back. The objectives are those of the
QM BBA: hold the initial trajectory, BPMs to zero, and one specific BPM to zero. DFS and
WFS are not used. BBA_GUI.py and BBA_QM_GUI.py are unchanged.

Checking what was computed:
- after a trajectory folder is chosen, every actuator in the list shows whether the folder
  has data for it ("data", "data x,y", "no data", "x only");
- "Compute response matrix" opens a window with the actuators used (and why others are
  not), the combined matrix, its singular values, and the first step predicted from the
  current orbit without moving anything;
- every iteration prints each corrector change in its unit and each mover change in um,
  with the mover position read back after the move.
"""

import json
import os
import sys
from datetime import datetime
from traceback import print_exception

import numpy as np

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                                 QMessageBox, QWidget)
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                                 QMessageBox, QWidget)

from BBA_GUI import BpmWeightsDelegate
from BBA_QM_GUI import MainWindow as QMBBAWindow
from beam_based_alignment.BBA_helpers.combined_actuators import (data_inventory, data_status, encoder_signs,
                                                                 ignored_text, match_selection,
                                                                 read_selection_file, selection_report)
from machine_interfaces.Backend.State import State

# Same list as SysID_corrector_and_mover_GUI.py: the final-focus quadrupoles of the ATF2
# extraction line, the ones whose mover read-backs are present in the 2026-11-19 machine
# data. The extraction-line quadrupoles QF1X ... QF21X have no mover.
ATF2_EXT_MOVERS = (
    "QM16FF", "QM15FF", "QM14FF", "QM13FF", "QM12FF", "QM11FF",
    "QD10BFF", "QD10AFF", "QF9BFF", "QF9AFF", "QD8FF", "QF7FF", "QD6FF",
    "QF5BFF", "QF5AFF", "QD4BFF", "QD4AFF", "QF3FF", "QD2BFF", "QD2AFF",
    "QF1FF", "QD0FF",
)
USABLE_MOVERS = {"ATF2_Ext": ATF2_EXT_MOVERS, "ATF2_Ext_RFT": ATF2_EXT_MOVERS}
DEFAULT_MOVER_RANGE_UM = 1000.0
MOVER_TOLERANCE_UM = 15.0  # same tolerance as apply_qmag_xyroll in the ATF2 interfaces
# How the orbit is judged in the plot, the log and the predicted step (the solver itself is unchanged).
ORBIT_METRICS = (("max", "Max |BPM|"), ("rms", "RMS"), ("norm", "Norm (as BBA_GUI)"))


def clean(value, digits=9):
    """Round away numerical noise (1e-17 steps) and -0 before printing."""
    value = float(value)
    return round(value, digits) + 0.0 if np.isfinite(value) else value


def fmt(value, unit):
    """Mover positions in um with 0.1 um, corrector strengths with 6 significant digits."""
    return f"{clean(value, 1):+.1f}" if unit == "um" else f"{clean(value):+.6g}"


def usable_movers(interface):
    """Quadrupole movers this interface can drive, in the interface's beamline order."""
    if not hasattr(interface, "apply_qmag_xyroll") or not hasattr(interface, "get_quadrupole_movers_names"):
        return []
    names = [str(name) for name in interface.get_quadrupole_movers_names()]
    allowed = USABLE_MOVERS.get(interface.get_name())
    return [name for name in names if allowed is None or name in allowed]


class MainWindow(QMBBAWindow):
    """BBA window offering correctors and quadrupole movers in one list."""

    def __init__(self, interface, dir_name, nominal_state=None, start_state=None):
        self.mover_names = usable_movers(interface)
        self._corrector_max = (0.0, 0.0)
        self._inventory_key = None
        self._inventory = None
        self._encoder_signs = {}
        self._mover_before = {}
        super().__init__(interface, dir_name, nominal_state, start_state)
        self._configure_combined_window()
        # Own handlers: the selection file may hold correctors and movers, and the folder
        # inventory is shown in the actuator list once a trajectory folder is chosen.
        for button, slot in ((self.load_correctors_button, self._load_actuators_clicked),
                             (self.pushButton_8, self._pick_trajectory_data)):
            button.clicked.disconnect()
            button.clicked.connect(slot)

    # --- window ------------------------------------------------------------------------
    def _setup_corrector_controls(self):
        super()._setup_corrector_controls()
        self._corrector_max = (self.max_horizontal_current_spinbox.value(), self.max_vertical_current_spinbox.value())

    def _quadrupole_movers(self):
        # BBA_QM_GUI fills the actuator list with this: correctors first, then the movers.
        correctors = [str(name) for name in self.initial_state.get_correctors()["names"]]
        return correctors + [name for name in self.mover_names if name not in correctors]

    def _configure_combined_window(self):
        self.setWindowTitle(f"BBA Correctors + QM - {self.interface.get_name()}")
        self.groupBox_5.setTitle("Correctors and quadrupole movers")
        self.specific_bpm_label.setText("Specific BPM")
        self.compute_response_matrix_button.setText("Check response matrix")

        # The QM window turned the max-strength fields into mover ranges; give them back to the correctors.
        unit = getattr(self, "corrs_unit", "")
        self.current_groupbox_right.setTitle(f"Corrector max strength ({unit})" if unit else "Corrector max strength")
        self.horizontal_current_label.setText("H:")
        self.vertical_current_label.setText("V:")
        for spinbox, value in zip((self.max_horizontal_current_spinbox, self.max_vertical_current_spinbox), self._corrector_max):
            spinbox.setMaximum(1e6)
            spinbox.setDecimals(4)
            spinbox.setSingleStep(0.01)
            spinbox.setValue(value)

        self.mover_range_row = QWidget(self)
        row = QHBoxLayout(self.mover_range_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.mover_range_x_spinbox = QDoubleSpinBox(self)
        self.mover_range_y_spinbox = QDoubleSpinBox(self)
        row.addWidget(QLabel("Mover max range [um]"))
        for label, spinbox in (("X:", self.mover_range_x_spinbox), ("Y:", self.mover_range_y_spinbox)):
            spinbox.setMaximum(1e6)
            spinbox.setDecimals(0)
            spinbox.setSingleStep(10.0)
            spinbox.setValue(DEFAULT_MOVER_RANGE_UM)
            row.addWidget(QLabel(label))
            row.addWidget(spinbox)
        self.verticalLayout_3.insertWidget(5, self.mover_range_row)
        self.mover_range_row.setVisible(bool(self.mover_names))

        self.metric_row = QWidget(self)
        row = QHBoxLayout(self.metric_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Orbit metric (plot and log)"))
        self.metric_combo = QComboBox(self)
        for key, text in ORBIT_METRICS:
            self.metric_combo.addItem(text, key)
        self.metric_combo.setToolTip("Max |BPM|: largest |orbit - objective| over the BPMs used. RMS: root mean square. "
                                     "Norm: the square root of the sum of squares, as in BBA_GUI.py. "
                                     "The correction itself (least squares) is the same for all three.")
        row.addWidget(self.metric_combo, 1)
        self.verticalLayout_3.insertWidget(6, self.metric_row)

        # The weights' help still described DFS/WFS (BBA_GUI.py); here they are the QM BBA's objectives.
        for button, text in (
                (self.orbit_weight_tooltip, "Trajectory hold weight: keep the orbit at the one measured at START "
                                            "(the first iteration). 0 = not used."),
                (self.dispersion_weight_tooltip, "BPM->0 weight: bring every BPM used to zero."),
                (self.wakefield_weight_tooltip, "Specific BPM->0 weight: bring the BPM chosen in 'Specific BPM' to zero, "
                                                "in addition to the other objectives. 0 = not used."),
                (self.max_strength_tooltip, "Maximum corrector strength (+/-) during the correction. Each corrector column "
                                            "is divided by it before solving, so it also sets how much correctors are used "
                                            "compared with the movers. 0 = no limit and no scaling.")):
            button.setToolTip(text)
        # The trajectory-hold reference is the orbit at START of each run, so this button has no effect here.
        self.pushButton_reset_ref_orbit.setVisible(False)
        self._refresh_metric_plots_for_mode()
        self._refresh_actuator_labels()

    def _refresh_metric_plots_for_mode(self):
        super()._refresh_metric_plots_for_mode()
        self._plot_series(self.traj_ax, self.traj_canvas, [], [], [], title="Correctors + QM - orbit")

    def _is_mover(self, name):
        return name in getattr(self, "mover_names", ())

    def _update_corrector_weights(self, item):
        # Shown right of the name: mover or not, whether the loaded folder has data for it, and the weight.
        name = item.text()
        is_mover = self._is_mover(name)
        _usable, status = data_status(name, is_mover, getattr(self, "_inventory", None))
        parts = (["mover"] if is_mover else []) + ([status] if status else []) + [f"[w = {self.corrector_weights.get(name, 1.0):g}]"]
        item.setData(BpmWeightsDelegate.WEIGHTS_ROLE, " · ".join(parts))

    def _refresh_actuator_labels(self):
        for i in range(self.correctors_list.count()):
            self._update_corrector_weights(self.correctors_list.item(i))
        self.correctors_list.viewport().update()

    # --- orbit metric -------------------------------------------------------------------
    def _metric(self):
        combo = getattr(self, "metric_combo", None)
        return combo.currentData() if combo is not None else "norm"

    def _metric_label(self):
        return dict(ORBIT_METRICS)[self._metric()]

    def _calc_error(self, x_meas, y_meas, ref_x, ref_y, disp_x=None, disp_y=None):
        metric = self._metric()
        if metric == "norm":
            return super()._calc_error(x_meas, y_meas, ref_x, ref_y, disp_x, disp_y)
        x = np.atleast_2d(np.asarray(x_meas, dtype=float)).copy()
        y = np.atleast_2d(np.asarray(y_meas, dtype=float)).copy()
        faulty = (np.nanmean(x, axis=0) == 0.0) & (np.nanmean(y, axis=0) == 0.0)  # as BBA_GUI: a BPM reading exactly 0
        x[:, faulty] = np.nan
        y[:, faulty] = np.nan
        dx = x - np.asarray(ref_x, dtype=float).reshape(1, -1) - np.asarray(0 if disp_x is None else disp_x, dtype=float).reshape(1, -1)
        dy = y - np.asarray(ref_y, dtype=float).reshape(1, -1) - np.asarray(0 if disp_y is None else disp_y, dtype=float).reshape(1, -1)
        fx, fy, fall = (np.array([self._metric_value(*rows) for rows in zip(*args)]) for args in ((dx,), (dy,), (dx, dy)))

        def mean_std(values):
            values = values[np.isfinite(values)]
            if values.size == 0:
                return float("nan"), float("nan")
            return float(np.mean(values)), (float(np.std(values, ddof=1)) if values.size > 1 else 0.0)

        (mx, sx), (my, sy), (ma, sa) = mean_std(fx), mean_std(fy), mean_std(fall)
        return mx, my, sx, sy, ma, sa

    def _metric_value(self, *deviations):
        values = np.concatenate([np.asarray(d, dtype=float).ravel() for d in deviations])
        values = values[np.isfinite(values)]
        if values.size == 0:
            return float("nan")
        if self._metric() == "max":
            return float(np.max(np.abs(values)))
        if self._metric() == "rms":
            return float(np.sqrt(np.mean(values ** 2)))
        return float(np.sqrt(np.sum(values ** 2)))

    def _orbit_summary(self, bpms, dx, dy):
        """'max|x| 0.83 mm at MQF6X, max|y| ... ; RMS x ..., y ...' for the log."""
        unit = getattr(self, "bpm_unit", "mm")
        parts = []
        for plane, d in (("x", np.asarray(dx, dtype=float)), ("y", np.asarray(dy, dtype=float))):
            if np.isfinite(d).any():
                i = int(np.nanargmax(np.abs(d)))
                parts.append(f"max|{plane}| {abs(d[i]):.4g} {unit} at {bpms[i]}")
        rms = [np.sqrt(np.nanmean(np.asarray(d, dtype=float) ** 2)) if np.isfinite(d).any() else np.nan for d in (dx, dy)]
        return ", ".join(parts) + f"; RMS x {rms[0]:.4g}, y {rms[1]:.4g} {unit}"

    # --- trajectory data and its inventory ----------------------------------------------
    def _current_inventory(self):
        info = self._data_dirs.get("traj")
        if not (info and info.get("ok") and info.get("pairs")):
            return None
        key = (info.get("dir"), len(info["pairs"]))
        if key != self._inventory_key:
            self._inventory_key, self._inventory = key, data_inventory(info["pairs"])
            self._encoder_signs = encoder_signs(info["pairs"])
        return self._inventory

    def _flipped_encoders(self):
        return [f"{name}:{axis}" for (name, axis), ratio in sorted(self._encoder_signs.items()) if ratio < 0]

    def _pick_trajectory_data(self):
        self._pick_and_load_traj_data()
        inventory = self._current_inventory()
        self._refresh_actuator_labels()
        if inventory is None:
            return
        message = self._inventory_report(inventory) + "\n" + self._select_sysid_bpms()
        self.log(message.replace("\n", " | "))
        QMessageBox.information(self, "Trajectory data", message)

    def _select_sysid_bpms(self):
        """With no BPM selected (= every BPM), select the BPMs the SysID used (its bpms.txt)."""
        selected = [self.bpms_list.item(i) for i in range(self.bpms_list.count()) if self.bpms_list.item(i).isSelected()]
        if selected:
            return f"BPMs: your selection of {len(selected)} is kept."
        path = os.path.join(self._data_dirs["traj"]["dir"], "bpms.txt")
        if not os.path.isfile(path):
            return "BPMs: none selected, so every BPM is used (the folder has no bpms.txt)."
        names = set(read_selection_file(path))
        items = [self.bpms_list.item(i) for i in range(self.bpms_list.count())]
        chosen = [item for item in items if str(item.data(Qt.ItemDataRole.UserRole)) in names]
        for item in chosen:
            item.setSelected(True)
        return (f"BPMs: none were selected, so the {len(chosen)} BPMs of the SysID (bpms.txt) are now selected. "
                "Change the selection in the BPM list if needed.")

    def _inventory_report(self, inventory):
        correctors, movers = inventory
        complete = [name for name, planes in movers.items() if planes["x"] and planes["y"]]
        partial = [name for name in movers if name not in complete]
        lines = [f"Folder: {self._data_dirs['traj']['dir']}",
                 f"Correctors measured ({len(correctors)}): {', '.join(correctors) or 'none'}",
                 f"Quadrupole movers measured in x and y ({len(complete)}): {', '.join(complete) or 'none'}"]
        if partial:
            lines.append(f"Movers with only one plane (not usable): {', '.join(partial)}")
        flipped = self._flipped_encoders()
        if flipped:
            lines.append(f"Encoder counts opposite to the setpoint (handled, response is per setpoint): {', '.join(flipped)}")
        if not movers:
            lines.append("\nThis folder has no quadrupole-mover measurement, so only correctors can be used. "
                         "Measure the movers with SysID_corrector_and_mover_GUI.py (select them in its list, "
                         "or load a selection file that names them).")
        unknown = [name for name in correctors if name not in self._quadrupole_movers()]
        if unknown:
            lines.append(f"Not in this window's list (ignored): {', '.join(unknown)}")
        return "\n".join(lines)

    # --- loading a selection file -----------------------------------------------------------
    def _load_actuators_clicked(self):
        try:
            info = self._data_dirs.get("traj") or {}
            start_dir = info.get("dir") or self.dir_name or os.path.expanduser("~/CERN-Flight_Simulator-Data")
            filename, _ = QFileDialog.getOpenFileName(self, "Load actuators (correctors and movers)",
                                                      os.path.join(os.path.expanduser(start_dir), "actuators.txt"), "Text (*.txt)")
            if not filename:
                return
            names = read_selection_file(filename)
            if os.path.basename(filename) in ("correctors.txt", "quadrupole_movers.txt"):
                # correctors.txt and quadrupole_movers.txt of one SysID folder are loaded together
                for other in ("correctors.txt", "quadrupole_movers.txt"):
                    path = os.path.join(os.path.dirname(filename), other)
                    if other != os.path.basename(filename) and os.path.isfile(path):
                        names += read_selection_file(path)
            names = list(dict.fromkeys(names))
            items = {self.correctors_list.item(i).text(): self.correctors_list.item(i) for i in range(self.correctors_list.count())}
            quadrupoles = getattr(self.interface, "quadrupoles", None) or getattr(self.interface, "Qmagnames", None) or []
            found, ignored = match_selection(names, items, self.mover_names, quadrupoles)
            report = selection_report(filename, found, ignored, self.mover_names)
            self.log(report.replace("\n", " | "))
            if not found:
                QMessageBox.warning(self, "Load actuators", f"No actuator of this window is listed in\n{filename}\n\n" + ignored_text(ignored))
                return
            self.correctors_list.clearSelection()
            for name in found:
                items[name].setSelected(True)
            QMessageBox.information(self, "Load actuators", report)
        except Exception as exc:
            QMessageBox.critical(self, "Load actuators", f"Could not load the selection:\n{exc}")

    # --- the combined response matrix ---------------------------------------------------
    def _specific_bpm_weight(self):
        try:
            return float(self.lineEdit_3.text().strip())
        except ValueError:
            return 0.0

    def _selected_actuators(self):
        actuators, bpms_selected = self._get_selection()
        return [name for name in actuators if self.corrector_weights.get(name, 1.0) > 0], list(bpms_selected)

    def _unit(self, kind):
        return "um" if kind == "mover" else (getattr(self, "corrs_unit", "") or "")

    def _build_model(self, actuators, bpms_selected, use_jitter=False):
        """Combined response matrix for the selected actuators, with the reason each unused actuator is left out."""
        inventory = self._current_inventory()
        if inventory is None:
            raise RuntimeError("Please select a trajectory data directory (a SysID folder with corrector and/or mover data).")
        if not actuators:
            raise RuntimeError("No actuator selected (or all weights are zero).")

        notes = {}
        usable = []
        for name in actuators:
            ok, status = data_status(name, self._is_mover(name), inventory)
            if ok:
                usable.append(name)
            else:
                notes[name] = f"{status} in the trajectory folder" + (" (a mover needs x and y)" if self._is_mover(name) else "")
        correctors = [name for name in usable if not self._is_mover(name)]
        movers = [name for name in usable if self._is_mover(name)]
        if not usable:
            raise RuntimeError("None of the selected actuators has data in the trajectory folder.\n\n"
                               + self._inventory_report(inventory))

        if use_jitter:
            self._build_jitter_model_for_correction(actuators=usable, bpms=bpms_selected)
        bpms = self._qm_control_bpms(usable, bpms_selected)
        if use_jitter and self.jitter_model is not None:
            refs = set(self.jitter_model["reference_bpms"])
            bpms = [bpm for bpm in bpms if bpm not in refs]
            self.log("Removed jitter reference BPMs from correction targets")
        if not bpms:
            raise RuntimeError("No BPMs selected downstream of the first actuator.")

        pairs = self._data_dirs["traj"]["pairs"]
        parts = []
        if correctors:
            Rxx, Ryy, Rxy, Ryx, _B0x, _B0y, hcorrs, vcorrs, bpms_c = self._compute_response_matrix(
                pairs=pairs, correctors=correctors, bpms=bpms, triangular=self._force_triangular())
            for name in correctors:
                if name not in hcorrs and name not in vcorrs:
                    notes[name] = ("left out by the corrector fit: downstream of the last BPM, not in the recorded "
                                   "sequence, or its excitation was not executed (see the terminal)")
            columns = [("corr", name, "x", Rxx[:, j], Ryx[:, j]) for j, name in enumerate(hcorrs)]
            columns += [("corr", name, "y", Rxy[:, j], Ryy[:, j]) for j, name in enumerate(vcorrs)]
            parts.append((list(bpms_c), columns))
        if movers:
            response = self._creating_qm_response_matrices(selected_corrs=movers, selected_bpms=bpms, triangular=True)
            q = list(response["qcorrs"])
            for name in movers:
                if name not in q:
                    notes[name] = "left out by the mover fit (no valid x and y pair)"
            columns = [("mover", name, "x", response["R_xx"][:, j], response["R_yx"][:, j]) for j, name in enumerate(q)]
            columns += [("mover", name, "y", response["R_xy"][:, j], response["R_yy"][:, j]) for j, name in enumerate(q)]
            parts.append((list(response["bpms"]), columns))

        common = [bpm for bpm in bpms if all(bpm in part_bpms for part_bpms, _ in parts)]
        if not common:
            raise RuntimeError("No BPM is shared by the corrector and quadrupole-mover response matrices.")
        columns = []
        for part_bpms, part_columns in parts:
            rows = [part_bpms.index(bpm) for bpm in common]
            columns += [(kind, name, plane, np.asarray(rx, float)[rows], np.asarray(ry, float)[rows])
                        for kind, name, plane, rx, ry in part_columns]
        if not columns:
            raise RuntimeError("No actuator has measured response data.")

        Rx = np.nan_to_num(np.column_stack([rx for *_, rx, _ry in columns]))
        Ry = np.nan_to_num(np.column_stack([ry for *_, _rx, ry in columns]))
        if self.remove_coupling_checkbox.isChecked():
            # "Remove coupling": an x column moves only x, a y column only y (as Rxy = Ryx = 0 in BBA_GUI.py)
            for j, (_kind, _name, plane, *_rest) in enumerate(columns):
                (Ry if plane == "x" else Rx)[:, j] = 0.0
            columns = [(kind, name, plane, Rx[:, j], Ry[:, j]) for j, (kind, name, plane, *_rest) in enumerate(columns)]
        # A BPM no actuator moves (no beam, saturated or broken reading, e.g. a constant 9.9999 mm)
        # cannot be corrected: it would only add a constant to the objective and the plotted RMS.
        peak = max(float(np.max(np.abs(Rx))), float(np.max(np.abs(Ry))), 0.0)
        live = (np.max(np.abs(Rx), axis=1) > 1e-9 * peak) | (np.max(np.abs(Ry), axis=1) > 1e-9 * peak)
        dead_bpms = [bpm for bpm, ok in zip(common, live) if not ok]
        if dead_bpms and live.any():
            common = [bpm for bpm, ok in zip(common, live) if ok]
            Rx, Ry = Rx[live], Ry[live]
            columns = [(kind, name, plane, rx[live], ry[live]) for kind, name, plane, rx, ry in columns]
        max_h, max_v = self.max_horizontal_current_spinbox.value(), self.max_vertical_current_spinbox.value()
        range_x, range_y = self.mover_range_x_spinbox.value(), self.mover_range_y_spinbox.value()
        limits = np.array([(max_h if plane == "x" else max_v) if kind == "corr" else (range_x if plane == "x" else range_y)
                           for kind, _name, plane, *_ in columns], dtype=float)
        limits = np.where(limits > 0, limits, np.inf)
        scale = np.where(np.isfinite(limits), limits, 1.0)  # column scale: the actuator's practical maximum
        labels = [f"{name}:{plane}" if kind == "mover" else name for kind, name, plane, *_ in columns]
        zero = [label for label, norm in zip(labels, np.linalg.norm(np.vstack([Rx, Ry]), axis=0)) if norm == 0]
        for label in zero:
            notes.setdefault(label.split(":")[0], "")
            notes[label.split(":")[0]] = (notes[label.split(":")[0]] + f" {label}: response is all zero (no selected BPM downstream).").strip()
        scaled = np.vstack([Rx, Ry]) * scale
        singular = np.linalg.svd(scaled, compute_uv=False) if scaled.size else np.zeros(0)
        _w1, _w2, _w3, rcond, *_ = self._read_params()

        used = {name for _kind, name, *_ in columns}
        rows = []
        for name in actuators:
            kind = "mover" if self._is_mover(name) else "corrector"
            note = notes.get(name, "")
            flipped = [axis for axis in "xy" if self._encoder_signs.get((name, axis), 1.0) < 0]
            if flipped:
                note = (note + f" Encoder counts opposite to the setpoint in {','.join(flipped)} (response is per setpoint).").strip()
            rows.append((name, kind, data_status(name, kind == "mover", inventory)[1], name in used, note))
        return {
            "folder": self._data_dirs["traj"]["dir"], "bpms": list(common),
            "columns": [(kind, name, plane) for kind, name, plane, *_ in columns],
            "labels": labels, "units": [self._unit(kind) for kind, *_ in columns],
            "Rx": Rx, "Ry": Ry, "limits": limits, "scale": scale,
            "weights": np.array([self.corrector_weights.get(name, 1.0) for _kind, name, *_ in columns], dtype=float),
            "singular": singular, "rcond": rcond,
            "kept": int(np.sum(singular > rcond * singular.max())) if singular.size else 0,
            "actuator_rows": rows, "notes": notes, "bpm_unit": getattr(self, "bpm_unit", "mm"),
            "zero_columns": zero, "dead_bpms": dead_bpms, "limits_set": {"corrector": (max_h, max_v), "mover_um": (range_x, range_y)},
        }

    def _log_model(self, model):
        n_corr = sum(kind == "corr" for kind, *_ in model["columns"])
        n_mover = sum(kind == "mover" for kind, *_ in model["columns"])
        self.log(f"Combined matrix: {2 * len(model['bpms'])} rows ({len(model['bpms'])} BPMs) x {len(model['columns'])} columns "
                 f"({n_corr} corrector, {n_mover} mover): {', '.join(model['labels'])}")
        for name, note in model["notes"].items():
            self.log(f"  {name}: {note}")
        if model["dead_bpms"]:
            self.log(f"  BPMs left out (no actuator moves them: no beam or a constant reading): {', '.join(model['dead_bpms'])}")
        flipped = self._flipped_encoders()
        if flipped:
            self.log(f"  Encoder counts opposite to the setpoint: {', '.join(flipped)} (the matrix is per setpoint, as the movers are commanded)")
        unscaled = sorted({f"{'corrector' if kind == 'corr' else 'mover'} {plane}"
                           for (kind, _n, plane), lim in zip(model["columns"], model["limits"]) if not np.isfinite(lim)})
        if unscaled:
            self.log(f"WARNING: no maximum set for {', '.join(unscaled)}: those columns are not scaled and not limited. "
                     "Set Corrector max strength / Mover max range so correctors and movers are weighed in comparable units.")
        s = model["singular"]
        if s.size:
            self.log(f"Combined A (scaled): smax={s.max():.6g}, smin={s.min():.6g}, kept={model['kept']}/{s.size} with rcond={model['rcond']:g}")

    def _save_model(self, model, folder=None):
        folder = folder or self._session_dir
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, "combined_response_matrix")
        rows = [f"{bpm}:x" for bpm in model["bpms"]] + [f"{bpm}:y" for bpm in model["bpms"]]
        matrix = np.vstack([model["Rx"], model["Ry"]])
        with open(base + ".csv", "w") as file:
            file.write("# orbit change per unit of each actuator: "
                       f"{model['bpm_unit']} per corrector unit ({self._unit('corr')}) or per um of a mover\n")
            file.write("row," + ",".join(f"{label} [{unit}]" for label, unit in zip(model["labels"], model["units"])) + "\n")
            for name, values in zip(rows, matrix):
                file.write(name + "," + ",".join(f"{v:.9g}" for v in values) + "\n")
        np.savez(base + ".npz", R=matrix, rows=np.array(rows), columns=np.array(model["labels"]), units=np.array(model["units"]),
                 limits=model["limits"], singular_values=model["singular"], bpms=np.array(model["bpms"]))
        return base + ".csv"

    def _display_response_matrix(self):
        from beam_based_alignment.BBA_helpers.CombinedResponseDialog import CombinedResponseDialog

        try:
            actuators, bpms_selected = self._selected_actuators()
            model = self._build_model(actuators, bpms_selected)
        except Exception as exc:
            QMessageBox.critical(self, "Check response matrix", str(exc))
            print_exception(exc)
            return
        self._log_model(model)
        folder = self._data_dirs["traj"]["dir"]
        dialog = CombinedResponseDialog(model, predict=lambda: self._predict_first_step(model),
                                        save=lambda: self._save_model(model, folder=os.path.join(folder, "BBA_combined_check")),
                                        parent=self)
        self._response_dialog = dialog
        dialog.show()

    # --- one correction step ---------------------------------------------------------------
    def _objective(self):
        w1, w2, _w3, rcond, iters, gain, beta, transmission = self._read_params()
        return {"w1": w1, "w2": w2, "w3": self._specific_bpm_weight(), "spec_bpm": self.specific_bpm_combo.currentText().strip(),
                "rcond": rcond, "iters": iters, "gain": gain, "beta": beta, "transmission": transmission}

    def _compute_targets(self, model, objective, O0x, O0y, B0x, B0y, current):
        Rx, Ry, bpms = model["Rx"], model["Ry"], model["bpms"]
        w1, w2, w3, spec_bpm = objective["w1"], objective["w2"], objective["w3"], objective["spec_bpm"]
        blocks_A, blocks_B = [], []
        if w1 > 0:
            blocks_A += [w1 * Rx, w1 * Ry]
            blocks_B += [w1 * (O0x - B0x), w1 * (O0y - B0y)]
        if w2 > 0:
            blocks_A += [w2 * Rx, w2 * Ry]
            blocks_B += [w2 * O0x, w2 * O0y]
        if w3 > 0 and spec_bpm in bpms:
            i = bpms.index(spec_bpm)
            blocks_A += [w3 * Rx[i:i + 1], w3 * Ry[i:i + 1]]
            blocks_B += [w3 * O0x[i:i + 1], w3 * O0y[i:i + 1]]
        if not blocks_A:
            raise RuntimeError("All objective weights are zero.")
        A = np.vstack(blocks_A)
        B = np.concatenate(blocks_B).astype(float)
        missing = ~np.isfinite(B)
        A[missing, :] = 0.0
        B[missing] = 0.0
        limits, scale = model["limits"], model["scale"]
        lower = (-limits - current) / scale
        upper = (limits - current) / scale
        step = self._solve_correction(A * scale, B.reshape(-1, 1), model["weights"], objective["gain"], objective["beta"],
                                      objective["rcond"], lower, upper) * scale
        return np.clip(current + step, -limits, limits), B

    def _centering(self, model, objective):
        return objective["w2"] > 0 or (objective["w3"] > 0 and objective["spec_bpm"] in model["bpms"])

    def _predict_first_step(self, model):
        """First step from the current orbit; reads the BPMs and the actuators, moves nothing."""
        objective = self._objective()
        state = self._apply_jitter_subtraction_to_state(self.interface.get_state())
        orbit = state.get_orbit(model["bpms"])
        O0x = np.asarray(orbit["x"], dtype=float).reshape(-1)
        O0y = np.asarray(orbit["y"], dtype=float).reshape(-1)
        current, _corr_now, _mover_now = self._actuator_settings(model["columns"])
        targets, _B = self._compute_targets(model, objective, O0x, O0y, O0x, O0y, current)
        step = targets - current
        Px = O0x + model["Rx"] @ step
        Py = O0y + model["Ry"] @ step
        reference = (np.zeros_like(O0x), np.zeros_like(O0y)) if self._centering(model, objective) else (O0x, O0y)

        def rms(values):
            values = values[np.isfinite(values)]
            return float(np.sqrt(np.mean(values ** 2))) if values.size else float("nan")

        at_limit = [label for label, target, limit in zip(model["labels"], targets, model["limits"])
                    if np.isfinite(limit) and abs(abs(target) - limit) <= 1e-9 * max(limit, 1.0)]
        rows = [(label, unit, fmt(now, unit), fmt(delta, unit), fmt(target, unit), fmt(limit, unit) if np.isfinite(limit) else "none",
                 "at limit" if label in at_limit else "")
                for label, unit, now, delta, target, limit in zip(model["labels"], model["units"], current, step, targets, model["limits"])]
        def peak(values):
            finite = np.where(np.isfinite(values), np.abs(values), -1.0)
            i = int(np.argmax(finite))
            return (float(finite[i]), model["bpms"][i]) if finite[i] >= 0 else (float("nan"), "-")

        result = {"rows": rows, "gain": objective["gain"], "bpms": model["bpms"], "at_limit": ", ".join(at_limit),
                  "metric": self._metric_label(),
                  "max_before": (peak(O0x - reference[0]), peak(O0y - reference[1])),
                  "max_after": (peak(Px - reference[0]), peak(Py - reference[1])),
                  "rms_before": (rms(O0x - reference[0]), rms(O0y - reference[1])),
                  "rms_after": (rms(Px - reference[0]), rms(Py - reference[1])),
                  "orbit_x": (O0x, Px), "orbit_y": (O0y, Py)}
        self.log("Predicted first step (nothing moved): " + "; ".join(
            f"{label} {fmt(delta, unit)} {unit}" for label, unit, delta in zip(model["labels"], model["units"], step)))
        return result

    # --- reading and setting the actuators ----------------------------------------------
    def _mover_positions(self, names):
        """{name: (x, y, roll, x read back, y read back)}; read back = encoder (xact/yact) if present, else setpoint."""
        if not names:
            return {}
        q = self.interface.get_quadrupoles(list(names))
        out = {}
        for i, name in enumerate(q["names"]):
            def value(key, fallback=np.nan):
                arr = np.asarray(q.get(key, []), dtype=float).ravel()
                return float(arr[i]) if arr.size > i else fallback
            x, y, roll = value("xdes"), value("ydes"), value("rolldes", 0.0)
            xr, yr = value("xact", x), value("yact", y)
            out[str(name)] = (x, y, roll, xr if np.isfinite(xr) else x, yr if np.isfinite(yr) else y)
        return out

    def _actuator_settings(self, columns):
        """Current setting of every column (corrector bdes or mover position in um), and the mover rolls."""
        corr_names = list(dict.fromkeys(name for kind, name, *_ in columns if kind == "corr"))
        mover_names = list(dict.fromkeys(name for kind, name, *_ in columns if kind == "mover"))
        corr_now = {}
        if corr_names:
            bdes, bact = self._corrector_readings(corr_names)
            mismatch = ~np.isclose(bact, bdes, rtol=0.0, atol=0.05)
            if mismatch.any():
                raise RuntimeError("Corrector readback differs from its setpoint before correction: " + ", ".join(
                    f"{n} (bdes={d:.6g}, bact={a:.6g})" for n, d, a, bad in zip(corr_names, bdes, bact, mismatch) if bad))
            corr_now = dict(zip(corr_names, bdes))
        positions = self._mover_positions(mover_names)
        self._mover_before = positions
        mover_now = {name: pos[:3] for name, pos in positions.items()}
        missing = [name for name in mover_names if name not in mover_now or not np.all(np.isfinite(mover_now[name][:2]))]
        if missing:
            raise RuntimeError(f"No mover position read back for: {', '.join(missing)}")
        current = np.array([corr_now[name] if kind == "corr" else mover_now[name][0 if plane == "x" else 1]
                            for kind, name, plane, *_ in columns], dtype=float)
        return current, corr_now, mover_now

    def _apply_settings(self, columns, targets, mover_now):
        corr = {name: value for (kind, name, *_), value in zip(columns, targets) if kind == "corr"}
        if corr and self.interface.set_correctors(list(corr), np.array(list(corr.values()), dtype=float)) is False:
            raise RuntimeError("BBA stopped: correctors did not reach their requested currents (the correction is not reliable).")
        moved = {name: list(mover_now[name]) for kind, name, *_ in columns if kind == "mover"}
        for (kind, name, plane, *_), value in zip(columns, targets):
            if kind == "mover":
                moved[name][0 if plane == "x" else 1] = float(value)
        if moved:
            names = list(moved)
            self.interface.apply_qmag_xyroll(names, np.array([moved[n][0] for n in names]),
                                             np.array([moved[n][1] for n in names]),
                                             np.array([moved[n][2] for n in names]), wait=True)

    def _log_step(self, model, current, targets):
        """One line per actuator: corrector in its unit, mover in um with what the mover reports after the move.

        A mover is flagged when its setpoint read back is not the request, or when its encoder moved by a
        different amount than requested (the encoder sign is taken from the SysID data, so QF1FF/QD0FF in x,
        whose encoders count the other way, are not flagged for that).
        """
        movers = list(dict.fromkeys(name for kind, name, *_ in model["columns"] if kind == "mover"))
        after_pos = self._mover_positions(movers) if movers else {}
        width = max(len(label) for label in model["labels"])
        off = []
        for (kind, name, plane), label, unit, before, after in zip(model["columns"], model["labels"], model["units"], current, targets):
            text = (f"  {label:<{width}}  {'corrector' if kind == 'corr' else 'mover    '}  {fmt(before, unit)} -> {fmt(after, unit)} {unit}"
                    f"  (step {fmt(after - before, unit)} {unit})")
            if kind == "mover" and name in after_pos:
                k = 0 if plane == "x" else 1
                setpoint = after_pos[name][k]
                sign = 1.0 if self._encoder_signs.get((name, plane), 1.0) >= 0 else -1.0
                moved = after_pos[name][3 + k] - self._mover_before.get(name, after_pos[name])[3 + k]
                text += f"  setpoint {fmt(setpoint, 'um')}, encoder moved {fmt(moved, 'um')} um"
                problems = []
                if abs(setpoint - after) > MOVER_TOLERANCE_UM:
                    problems.append(f"setpoint {fmt(setpoint - after, 'um')} um from the request")
                if abs(sign * moved - (after - before)) > MOVER_TOLERANCE_UM:
                    problems.append(f"encoder moved {fmt(sign * moved, 'um')} um instead of {fmt(after - before, 'um')} um"
                                    + (" (sign corrected: encoder counts opposite to the setpoint)" if sign < 0 else ""))
                if problems:
                    text += "  WARNING: " + "; ".join(problems)
                    off.append(label)
            self.log(text)
        if off:
            self.log(f"WARNING: movers not where requested (> {MOVER_TOLERANCE_UM:g} um): {', '.join(off)}. "
                     "Check them on the machine; the next iteration starts from the setpoint read back.")
        return {name: (pos[0], pos[1], pos[2], pos[0], pos[1]) for name, pos in after_pos.items()}

    def _restore_movers(self, state, names):
        q = state.get_quadrupoles()
        index = {str(name): i for i, name in enumerate(q["names"])}
        names = [name for name in names if name in index]
        if not names:
            return
        pick = lambda key: np.array([np.asarray(q[key], dtype=float)[index[n]] for n in names])
        x, y, roll = pick("xdes"), pick("ydes"), pick("rolldes")
        ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(roll)
        now = self._mover_positions(names)
        moved = [n for n, keep, a, b in zip(names, ok, x, y)
                 if keep and (n not in now or abs(now[n][0] - a) > 1.0 or abs(now[n][1] - b) > 1.0)]
        ok = np.array([n in moved for n in names])
        names = moved
        if names:
            self.log(f"Setting movers back: {', '.join(f'{n} x={a:+.1f} y={b:+.1f} um' for n, a, b in zip(names, x[ok], y[ok]))}")
            self.interface.apply_qmag_xyroll(names, x[ok], y[ok], roll[ok], wait=True)

    def _restore_initial_settings(self):
        # Correctors and movers; no energy/intensity reset, since DFS and WFS are not used here.
        self.log("Restoring initial settings (correctors and quadrupole movers)...")
        self._cancel = True
        self._running = False
        if self.interface.restore_correctors_state(self.restore_state) is False:
            self.log("Warning: not every corrector was confirmed back at its saved current.")
            QMessageBox.warning(self, "Restore initial settings",
                                "Some correctors were not confirmed back at their saved current within the "
                                "readback tolerance. Check them on the machine before the next correction.")
        self._restore_movers(self.restore_state, self.mover_names)
        self.reset_ref_orb = True
        self._hist_abs_rms_x.clear(), self._hist_abs_rms_y.clear(), self._hist_abs_rms_xy.clear()
        self._clear_graphs()
        self.log("Machine initial settings restored (correctors and movers).")

    def _restore_history_iteration(self):
        if self._running or not self._history_files:
            return
        index = self.history_iteration_slider.value()
        state = State(filename=self._history_files[index])
        question = (f"Set the correctors and quadrupole movers to iteration {index} "
                    f"({state.get_timestamp():%H:%M:%S}) of {os.path.basename(self._history_folder)}?")
        if QMessageBox.question(self, "Iteration history", question) != QMessageBox.StandardButton.Yes:
            return
        if self.interface.restore_correctors_state(state) is False:
            QMessageBox.warning(self, "Iteration history", "Not every corrector was confirmed at its saved value. Check them on the machine.")
        self._restore_movers(state, self.mover_names)
        self.log(f"Machine set to iteration {index} of {self._history_folder}")

    # --- correction ----------------------------------------------------------------------
    def _start_correction(self, preview=False):
        self.interface.switch_off_sextupoles()
        try:
            self._start_combined_correction()
        except Exception as exc:
            QMessageBox.critical(self, "Correction error", str(exc))
            self.log(f"Correction error: {exc}")
            print_exception(exc)
        finally:
            self.interface.reset_sextupoles()
            self._running = False
            self.beam_change_group.setEnabled(True)
            self.setWindowTitle(f"BBA Correctors + QM - {self.interface.get_name()}")

    def _plot_orbit_history(self, center):
        self._plot_series(ax=self.traj_ax, canvas=self.traj_canvas, values_x=self._hist_orbit_x, values_y=self._hist_orbit_y,
                          vals=self._hist_orbit, error_x=self._hist_orbit_x_err, error_y=self._hist_orbit_y_err,
                          error_all=self._hist_orbit_err,
                          title="Correctors + QM - " + ("orbit (BPMs to zero)" if center else "distance from initial trajectory"))
        self.traj_ax.set_ylabel(f"{self._metric_label()} [{getattr(self, 'bpm_unit', 'mm')}]", fontsize=10)
        self.traj_canvas.draw_idle()

    def _start_combined_correction(self, silent=False):
        self._cancel = False
        objective = self._objective()
        actuators, bpms_selected = self._selected_actuators()
        model = self._build_model(actuators, bpms_selected, use_jitter=True)
        self._log_model(model)
        if not any(kind == "mover" for kind, *_ in model["columns"]) and any(self._is_mover(name) for name in actuators):
            self.log("WARNING: movers are selected but none is in the matrix; only correctors will move (see the reasons above).")
        self._save_model(model)

        bpms, columns, labels = model["bpms"], model["columns"], model["labels"]
        center = self._centering(model, objective)
        samples_dir = os.path.join(self._session_dir, "BBA_states")
        os.makedirs(samples_dir, exist_ok=True)
        for series in (self._hist_orbit_x, self._hist_orbit_y, self._hist_orbit,
                       self._hist_orbit_x_err, self._hist_orbit_y_err, self._hist_orbit_err):
            series.clear()

        B0x = B0y = None
        previous = None  # (columns, settings, mover state) before the last step, to undo it
        iters = objective["iters"]
        for it in range(iters):
            if self._cancel:
                break
            QApplication.processEvents()
            state0 = self._measure_state(os.path.join(samples_dir, f"ITER_{it:04d}_nominal.pkl"))
            if hasattr(self.interface, "chosen_ict"):
                charge = np.asarray(state0.get_icts(self.interface.chosen_ict)["charge"], dtype=float).ravel()
                if charge.size and np.isfinite(charge[0]):
                    if self.initial_charge_value is None:
                        if charge[0] == 0:
                            raise RuntimeError("Cannot establish a transmission reference from zero charge.")
                        self.initial_charge_value = charge[0]
                    self._hist_transmission.append(100.0 * charge[0] / float(self.initial_charge_value))
                    if self._hist_transmission[-1] <= objective["transmission"]:
                        if previous is not None:
                            self._apply_settings(*previous)
                            self.log("Transmission below threshold: correctors and movers set back to the previous iteration.")
                        QMessageBox.warning(self, "Transmission below level!", "Transmission has reached the threshold. Correction stopped.")
                        break

            orbit = state0.get_orbit(bpms)
            O0x = np.asarray(orbit["x"], dtype=float).reshape(-1)
            O0y = np.asarray(orbit["y"], dtype=float).reshape(-1)
            if B0x is None:
                B0x, B0y = O0x.copy(), O0y.copy()
            readings = state0.get_bpms(bpms)
            reference = (np.zeros_like(O0x), np.zeros_like(O0y)) if center else (B0x, B0y)
            self._append_history("orbit", self._calc_error(np.asarray(readings["x"], dtype=float), np.asarray(readings["y"], dtype=float),
                                                           ref_x=reference[0], ref_y=reference[1]))
            self._plot_orbit_history(center)

            current, _corr_now, mover_now = self._actuator_settings(columns)
            targets, B = self._compute_targets(model, objective, O0x, O0y, B0x, B0y, current)
            previous = (columns, current, mover_now)
            self.log(f"Iteration {it + 1}/{iters}: ||B||={np.linalg.norm(B):.6g}; orbit - objective: "
                     + self._orbit_summary(bpms, O0x - reference[0], O0y - reference[1]))
            self._apply_settings(columns, targets, mover_now)
            readback = self._log_step(model, current, targets)
            with open(os.path.join(self._session_dir, "kicks.txt"), "a") as file:
                now = datetime.now().isoformat(timespec="seconds")
                for (kind, name, plane), label, unit, before, after in zip(columns, labels, model["units"], current, targets):
                    back = readback.get(name, (np.nan,) * 5)[3 if plane == "x" else 4] if kind == "mover" else after
                    file.write(f"{now}\t{it + 1}\t{label}\t{clean(before, 12):.12g}\t{clean(after - before, 12):.12g}\t{clean(after, 12):.12g}\t{unit}\t{clean(back, 12):.12g}\n")
            QApplication.processEvents()

        final_state = self.interface.get_state()
        final_state.save(filename=os.path.join(self._session_dir, "machine_status_after_correction.pkl"))
        final = final_state.get_bpms(bpms)
        reference = (np.zeros(len(bpms)), np.zeros(len(bpms))) if center else (B0x, B0y)
        if reference[0] is not None:
            self._append_history("orbit", self._calc_error(np.asarray(final["x"], dtype=float), np.asarray(final["y"], dtype=float),
                                                           ref_x=reference[0], ref_y=reference[1]))
            self._plot_orbit_history(center)
            self.log("After the correction, orbit - objective: " + self._orbit_summary(
                bpms, np.asarray(final_state.get_orbit(bpms)["x"], dtype=float) - reference[0],
                np.asarray(final_state.get_orbit(bpms)["y"], dtype=float) - reference[1]))
        with open(os.path.join(self._session_dir, "combined_bba_settings.json"), "w") as file:
            json.dump({
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "interface_id": f"{type(self.interface).__module__}.{type(self.interface).__name__}",
                "trajectory_data": model["folder"],
                "weights": {"trajectory_hold": objective["w1"], "bpms_to_zero": objective["w2"],
                            "specific_bpm": objective["w3"], "specific_bpm_name": objective["spec_bpm"]},
                "rcond": objective["rcond"], "iterations": iters, "gain": objective["gain"], "beta": objective["beta"],
                "corrector_max_strength": list(model["limits_set"]["corrector"]),
                "mover_max_range_um": list(model["limits_set"]["mover_um"]),
                "columns": labels, "units": model["units"], "bpms": list(bpms), "orbit_metric": self._metric(),
                "bpms_left_out": model["dead_bpms"],
                "not_used": model["notes"],
                "actuator_weights": {name: self.corrector_weights.get(name, 1.0) for name in actuators},
            }, file, indent=2)
        message = ("Correction stopped" if self._cancel else "Correction finished") + (
            " in the simulated interface." if getattr(self.interface, "is_simulation", False) else ".")
        self.log(message)
        if not silent:
            QMessageBox.information(self, "Correction", message)


def main():
    app = QApplication(sys.argv)
    from machine_interfaces.Backend import SelectInterface

    interface = SelectInterface.choose_acc_and_interface()
    if interface is None:
        return 1

    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_name = os.path.expanduser(
        f"~/CERN-Flight_Simulator-Data/BBA_KickerQM_{interface.get_name()}_{time_str}_session_settings")
    window = MainWindow(interface, dir_name, start_state=interface.get_state())
    if hasattr(interface, "log_messages"):
        interface.log_messages(window.log)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
