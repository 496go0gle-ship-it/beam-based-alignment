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
"""

import json
import os
import sys
from datetime import datetime
from traceback import print_exception

import numpy as np

try:
    from PyQt6.QtWidgets import QApplication, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox, QWidget
except ImportError:
    from PyQt5.QtWidgets import QApplication, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox, QWidget

from BBA_QM_GUI import MainWindow as QMBBAWindow

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
        super().__init__(interface, dir_name, nominal_state, start_state)
        self._configure_combined_window()

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
        self._refresh_metric_plots_for_mode()

    def _refresh_metric_plots_for_mode(self):
        super()._refresh_metric_plots_for_mode()
        self._plot_series(self.traj_ax, self.traj_canvas, [], [], [], title="Correctors + QM - orbit")

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

    def _specific_bpm_weight(self):
        try:
            return float(self.lineEdit_3.text().strip())
        except ValueError:
            return 0.0

    def _combined_response(self, correctors, movers, bpms):
        """Columns (kind, name, plane, x response, y response) on the BPMs shared by both matrices."""
        info = self._data_dirs.get("traj")
        if not (info and info.get("ok") and info.get("pairs")):
            raise RuntimeError("Please select a trajectory data directory (a SysID folder with corrector and/or mover data).")

        parts = []
        if correctors:
            Rxx, Ryy, Rxy, Ryx, _B0x, _B0y, hcorrs, vcorrs, bpms_c = self._compute_response_matrix(
                pairs=info["pairs"], correctors=correctors, bpms=bpms, triangular=self._force_triangular())
            columns = [("corr", name, "x", Rxx[:, j], Ryx[:, j]) for j, name in enumerate(hcorrs)]
            columns += [("corr", name, "y", Rxy[:, j], Ryy[:, j]) for j, name in enumerate(vcorrs)]
            parts.append((list(bpms_c), columns))
        if movers:
            response = self._creating_qm_response_matrices(selected_corrs=movers, selected_bpms=bpms, triangular=True)
            if response is None:
                raise RuntimeError("No quadrupole-mover data in the trajectory data directory.")
            q = response["qcorrs"]
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
        return common, columns

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
        mover_now = {}
        if mover_names:
            q = self.interface.get_quadrupoles(mover_names)
            for name, x, y, roll in zip(q["names"], q["xdes"], q["ydes"], q["rolldes"]):
                mover_now[str(name)] = (float(x), float(y), float(roll))
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

    def _start_combined_correction(self, silent=False):
        self._cancel = False
        w1, w2, _w3, rcond, iters, gain, beta, transmission_threshold = self._read_params()
        w3 = self._specific_bpm_weight()

        actuators, bpms_selected = self._get_selection()
        actuators = [name for name in actuators if self.corrector_weights.get(name, 1.0) > 0]
        movers = [name for name in actuators if name in self.mover_names]
        correctors = [name for name in actuators if name not in self.mover_names]
        if not actuators:
            raise RuntimeError("No actuator selected (or all weights are zero).")
        self._build_jitter_model_for_correction(actuators=actuators, bpms=bpms_selected)
        bpms = self._qm_control_bpms(actuators, bpms_selected)
        if self.jitter_model is not None:
            refs = set(self.jitter_model["reference_bpms"])
            bpms = [bpm for bpm in bpms if bpm not in refs]
            self.log("Removed jitter reference BPMs from correction targets")
        if not bpms:
            raise RuntimeError("No BPMs selected downstream of the first actuator.")

        bpms, columns = self._combined_response(correctors, movers, bpms)
        Rx = np.nan_to_num(np.column_stack([rx for *_, rx, _ry in columns]))
        Ry = np.nan_to_num(np.column_stack([ry for *_, _rx, ry in columns]))
        max_h, max_v = self.max_horizontal_current_spinbox.value(), self.max_vertical_current_spinbox.value()
        range_x, range_y = self.mover_range_x_spinbox.value(), self.mover_range_y_spinbox.value()
        limits = np.array([(max_h if plane == "x" else max_v) if kind == "corr" else (range_x if plane == "x" else range_y)
                           for kind, _name, plane, *_ in columns], dtype=float)
        limits = np.where(limits > 0, limits, np.inf)
        scale = np.where(np.isfinite(limits), limits, 1.0)  # column scale: the actuator's practical maximum
        unscaled = sorted({("corrector" if kind == "corr" else "mover") + f" {plane}" for (kind, _n, plane, *_), lim in zip(columns, limits) if not np.isfinite(lim)})
        if unscaled:
            self.log(f"WARNING: no maximum set for {', '.join(unscaled)}: those columns are not scaled and not limited. "
                     "Set Corrector max strength / Mover max range so correctors and movers are weighed in comparable units.")
        weights = np.array([self.corrector_weights.get(name, 1.0) for _kind, name, *_ in columns], dtype=float)
        labels = [f"{name}:{plane}" if kind == "mover" else name for kind, name, plane, *_ in columns]
        self.log(f"Combined BBA: {len(bpms)} BPMs, {sum(k == 'corr' for k, *_ in columns)} corrector and "
                 f"{sum(k == 'mover' for k, *_ in columns)} mover columns ({', '.join(labels)})")

        spec_bpm = self.specific_bpm_combo.currentText().strip()
        center = w2 > 0 or (w3 > 0 and spec_bpm in bpms)
        samples_dir = os.path.join(self._session_dir, "BBA_states")
        os.makedirs(samples_dir, exist_ok=True)
        for series in (self._hist_orbit_x, self._hist_orbit_y, self._hist_orbit,
                       self._hist_orbit_x_err, self._hist_orbit_y_err, self._hist_orbit_err):
            series.clear()

        B0x = B0y = None
        previous = None  # (columns, settings, mover state) before the last step, to undo it
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
                    if self._hist_transmission[-1] <= transmission_threshold:
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
            self._plot_series(ax=self.traj_ax, canvas=self.traj_canvas, values_x=self._hist_orbit_x, values_y=self._hist_orbit_y,
                              vals=self._hist_orbit, error_x=self._hist_orbit_x_err, error_y=self._hist_orbit_y_err,
                              error_all=self._hist_orbit_err,
                              title="Correctors + QM - " + ("orbit (BPMs to zero)" if center else "distance from initial trajectory"))

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

            current, corr_now, mover_now = self._actuator_settings(columns)
            lower = (-limits - current) / scale
            upper = (limits - current) / scale
            if it == 0:
                singular_values = np.linalg.svd(A * scale, compute_uv=False)
                kept = int(np.sum(singular_values > rcond * singular_values.max())) if singular_values.size else 0
                self.log(f"Combined A (scaled): shape={A.shape}, smax={singular_values.max():.6g}, "
                         f"smin={singular_values.min():.6g}, kept={kept}/{singular_values.size} with rcond={rcond:g}")
            step = self._solve_correction(A * scale, B.reshape(-1, 1), weights, gain, beta, rcond, lower, upper) * scale
            targets = np.clip(current + step, -limits, limits)
            previous = (columns, current, mover_now)
            self._apply_settings(columns, targets, mover_now)
            self.log(f"Iteration {it + 1}/{iters}: ||B||={np.linalg.norm(B):.6g}; " + ", ".join(
                f"{label} {delta:+.4g}" for label, delta in zip(labels, targets - current)))
            with open(os.path.join(self._session_dir, "kicks.txt"), "a") as file:
                now = datetime.now().isoformat(timespec="seconds")
                for label, before, after in zip(labels, current, targets):
                    file.write(f"{now}\t{it + 1}\t{label}\t{before:.12g}\t{after - before:.12g}\t{after:.12g}\n")
            QApplication.processEvents()

        final_state = self.interface.get_state()
        final_state.save(filename=os.path.join(self._session_dir, "machine_status_after_correction.pkl"))
        final = final_state.get_bpms(bpms)
        reference = (np.zeros(len(bpms)), np.zeros(len(bpms))) if center else (B0x, B0y)
        if reference[0] is not None:
            self._append_history("orbit", self._calc_error(np.asarray(final["x"], dtype=float), np.asarray(final["y"], dtype=float),
                                                           ref_x=reference[0], ref_y=reference[1]))
            self._plot_series(ax=self.traj_ax, canvas=self.traj_canvas, values_x=self._hist_orbit_x, values_y=self._hist_orbit_y,
                              vals=self._hist_orbit, error_x=self._hist_orbit_x_err, error_y=self._hist_orbit_y_err,
                              error_all=self._hist_orbit_err,
                              title="Correctors + QM - " + ("orbit (BPMs to zero)" if center else "distance from initial trajectory"))
        with open(os.path.join(self._session_dir, "combined_bba_settings.json"), "w") as file:
            json.dump({
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "interface_id": f"{type(self.interface).__module__}.{type(self.interface).__name__}",
                "trajectory_data": (self._data_dirs.get("traj") or {}).get("dir"),
                "weights": {"trajectory_hold": w1, "bpms_to_zero": w2, "specific_bpm": w3, "specific_bpm_name": spec_bpm},
                "rcond": rcond, "iterations": iters, "gain": gain, "beta": beta,
                "corrector_max_strength": [max_h, max_v], "mover_max_range_um": [range_x, range_y],
                "columns": labels, "bpms": list(bpms),
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
