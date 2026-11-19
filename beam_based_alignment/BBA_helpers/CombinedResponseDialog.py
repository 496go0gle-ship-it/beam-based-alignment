"""Window that shows what the corrector + quadrupole-mover BBA computed from the SysID data.

Tabs:
  Actuators       which selected actuators have data and which are used in the matrix (and why not)
  Matrix          the combined response matrix (orbit change for each actuator at its max range)
  Singular values the singular values of the scaled matrix and the rcond cut
  Predicted step  the first correction step from the current orbit (reads BPMs, moves nothing)
"""

import numpy as np

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                                 QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                                 QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

CORRECTOR_COLOUR = "#2a78c6"
MOVER_COLOUR = "#d9822b"


def _table(headers, rows):
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            numeric = not isinstance(value, str) or value[:1] in "+-"
            item = QTableWidgetItem(value if isinstance(value, str) else f"{value:+.5g}")
            if numeric:
                item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            table.setItem(r, c, item)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _canvas(height=5.0):
    figure = Figure(figsize=(9, height), tight_layout=True)
    return figure, FigureCanvas(figure)


class CombinedResponseDialog(QDialog):
    def __init__(self, model, predict, save, parent=None):
        super().__init__(parent)
        self.model, self._predict, self._save = model, predict, save
        self.setWindowTitle("Correctors + QM: response matrix check")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(self._summary()))
        tabs = QTabWidget(self)
        tabs.addTab(self._actuators_tab(), "Actuators")
        tabs.addTab(self._matrix_tab(), "Matrix")
        tabs.addTab(self._singular_values_tab(), "Singular values")
        tabs.addTab(self._prediction_tab(), "Predicted step")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        save_button = QPushButton("Save matrix (CSV + NPZ)")
        save_button.clicked.connect(self._save_clicked)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(save_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    # --- tabs ------------------------------------------------------------------------------
    def _summary(self):
        m = self.model
        n_corr = sum(kind == "corr" for kind, _n, _p in m["columns"])
        n_mover = sum(kind == "mover" for kind, _n, _p in m["columns"])
        used_movers = sorted({name for kind, name, _p in m["columns"] if kind == "mover"})
        text = (f"Data: {m['folder']}\n"
                f"Matrix: {2 * len(m['bpms'])} rows ({len(m['bpms'])} BPMs, x and y) x {len(m['columns'])} columns "
                f"({n_corr} corrector, {n_mover} mover = {len(used_movers)} movers in x and y).  "
                f"Rank kept with rcond={m['rcond']:g}: {m['kept']}/{len(m['singular'])}.")
        if not n_mover:
            text += "\nNo mover is in the matrix: see the Actuators tab for the reason."
        return text

    def _actuators_tab(self):
        rows = [(name, kind, data, "yes" if used else "no", note) for name, kind, data, used, note in self.model["actuator_rows"]]
        return _table(["Actuator", "Type", "Data in folder", "Used", "Note"], rows)

    def _matrix_tab(self):
        m = self.model
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(
            "Orbit change at every BPM for each actuator moved by its maximum (Corrector max strength / Mover max range), "
            f"in {m['bpm_unit']}. Columns are solved in these units, so correctors and movers are compared fairly.\n"
            "A column that is all zero cannot correct anything (no BPM downstream of it, or no usable data)."))
        figure, canvas = _canvas(6.5)
        matrix = np.vstack([m["Rx"], m["Ry"]]) * m["scale"]
        labels = m["labels"]
        ax = figure.add_subplot(2, 1, 1)
        limit = float(np.nanmax(np.abs(matrix))) if matrix.size and np.isfinite(matrix).any() else 1.0
        image = ax.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-limit, vmax=limit, interpolation="nearest")
        figure.colorbar(image, ax=ax, label=m["bpm_unit"])
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=90, fontsize=7)
        nb = len(m["bpms"])
        ax.axhline(nb - 0.5, color="k", lw=0.8)
        ax.set_yticks([nb / 2 - 0.5, 1.5 * nb - 0.5])
        ax.set_yticklabels(["BPM x", "BPM y"])
        ax.set_title("Combined response matrix (scaled)")

        ax = figure.add_subplot(2, 1, 2)
        norms = np.sqrt(np.nansum(matrix ** 2, axis=0))
        colours = [CORRECTOR_COLOUR if kind == "corr" else MOVER_COLOUR for kind, _n, _p in m["columns"]]
        ax.bar(range(len(labels)), norms, color=colours)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=90, fontsize=7)
        ax.set_ylabel(f"|column| [{m['bpm_unit']}]")
        ax.set_title("Strength of each column (blue: corrector, orange: mover)")
        layout.addWidget(canvas)
        return widget

    def _singular_values_tab(self):
        m = self.model
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Singular values of the scaled matrix. Directions below the line (rcond x largest) are not "
                                "used by the correction when beta = 0."))
        figure, canvas = _canvas()
        ax = figure.add_subplot(1, 1, 1)
        s = np.asarray(m["singular"], dtype=float)
        if s.size:
            ax.semilogy(range(1, s.size + 1), np.where(s > 0, s, np.nan), "o-")
            ax.axhline(m["rcond"] * s.max(), color="r", ls="--", label=f"rcond = {m['rcond']:g}")
            ax.legend()
        ax.set_xlabel("index")
        ax.set_ylabel("singular value")
        layout.addWidget(canvas)
        return widget

    def _prediction_tab(self):
        widget = QWidget()
        self._prediction_layout = QVBoxLayout(widget)
        button = QPushButton("Compute the first step from the current orbit (reads the BPMs once, moves nothing)")
        button.clicked.connect(self._predict_clicked)
        self._prediction_layout.addWidget(button)
        self._prediction_label = QLabel("Uses the weights, gain, rcond/beta and limits set in the main window.")
        self._prediction_layout.addWidget(self._prediction_label)
        self._prediction_table = None
        self._prediction_figure, self._prediction_canvas = _canvas(3.5)
        self._prediction_layout.addWidget(self._prediction_canvas)
        return widget

    # --- actions ---------------------------------------------------------------------------
    def _predict_clicked(self):
        try:
            result = self._predict()
        except Exception as exc:
            QMessageBox.critical(self, "Predicted step", str(exc))
            return
        unit = self.model["bpm_unit"]
        (bx, by), (ax_, ay) = result["rms_before"], result["rms_after"]
        self._prediction_label.setText(
            f"Orbit RMS to the objective now: x {bx:.4g}, y {by:.4g} {unit}  ->  predicted after one step: "
            f"x {ax_:.4g}, y {ay:.4g} {unit}  (gain {result['gain']:g}).  "
            f"Actuators at their limit: {result['at_limit'] or 'none'}.")
        if self._prediction_table is not None:
            self._prediction_layout.removeWidget(self._prediction_table)
            self._prediction_table.deleteLater()
        self._prediction_table = _table(["Actuator", "Unit", "Now", "Step", "Target", "Limit (+/-)", "Note"], result["rows"])
        self._prediction_layout.insertWidget(2, self._prediction_table)

        figure = self._prediction_figure
        figure.clear()
        positions = np.arange(len(result["bpms"]))
        for i, (plane, now, after) in enumerate((("x", *result["orbit_x"]), ("y", *result["orbit_y"]))):
            ax = figure.add_subplot(1, 2, i + 1)
            ax.plot(positions, now, "o-", ms=3, label="now")
            ax.plot(positions, after, "s-", ms=3, label="predicted")
            ax.set_title(f"{plane} [{unit}]")
            ax.set_xticks(positions)
            ax.set_xticklabels(result["bpms"], rotation=90, fontsize=6)
            ax.legend(fontsize=8)
        self._prediction_canvas.draw_idle()

    def _save_clicked(self):
        try:
            path = self._save()
        except Exception as exc:
            QMessageBox.critical(self, "Save matrix", str(exc))
            return
        QMessageBox.information(self, "Save matrix", f"Saved to\n{path}")
