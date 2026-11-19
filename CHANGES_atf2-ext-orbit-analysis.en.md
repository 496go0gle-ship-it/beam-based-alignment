# Changes on branch `atf2-ext-orbit-analysis` (beam-based-alignment)

Base: `flight-simulator-framework/beam-based-alignment` `master` at `04cbf5c`.
Japanese version: [CHANGES_atf2-ext-orbit-analysis.ja.md](CHANGES_atf2-ext-orbit-analysis.ja.md)

| Commit | Summary |
|---|---|
| `b643faf` | Use palette colours in the BBA window (carried over from the working copy) |
| (this commit) | Add a BBA that corrects the orbit with correctors and quadrupole movers together |

New file: `BBA_corrector_and_mover_GUI.py`. `BBA_GUI.py` and `BBA_QM_GUI.py` are unchanged.

## Why
`SysID_corrector_and_mover_GUI.py` (system-identification, same branch) measures corrector and mover responses into one folder. The research correction uses both kinds of actuator at once (an under-determined system: more actuators than BPMs, minimum-norm solution), but BBA could use either correctors (`BBA_GUI.py`) or movers (`BBA_QM_GUI.py`), never both.

## What it does
- **Actuators:** one list with every corrector and the 22 final-focus quadrupole movers (`QM16FF` ... `QD0FF`, the same list as the combined SysID).
- **Response matrix:** from the trajectory data folder, the corrector matrix (as `BBA_GUI.py`) and the mover matrix (as `BBA_QM_GUI.py`) are computed, restricted to the BPMs they share and placed side by side: columns H correctors, V correctors, movers in x, movers in y; rows x then y at each BPM.
- **Units:** each column is divided by the actuator's maximum (Corrector max strength H/V, Mover max range X/Y in um) before solving, and the solution is scaled back. Without this, a corrector column (T*mm or A) and a mover column (um) differ by orders of magnitude and the SVD cut-off is meaningless. A maximum of 0 means "no limit": that column is not scaled and a warning is logged.
- **Objectives** (as the QM BBA): trajectory hold weight, BPMs to zero, one specific BPM to zero. DFS and WFS are not used.
- **Solver:** `_solve_correction()` of `BBA_GUI.py` (rcond cut-off or beta Tikhonov regularisation, bounds from the maxima, actuator weights).
- **Applying:** correctors with `set_correctors()`, movers with `apply_qmag_xyroll()`. If the transmission falls below the threshold, both are set back to the previous iteration.
- **Saved per session:** `BBA_states/ITER_*_nominal.pkl`, `kicks.txt` (every actuator, before / step / after), `machine_status_after_correction.pkl`, `combined_bba_settings.json`.

## Verification (RF-Track simulation, `ATF2_Ext_RFT`)
- Combined SysID of 6 correctors (`ZH9X`, `ZV10X`, `ZH10X`, `ZV11X`, `ZH1FF`, `ZV1FF`) and 5 movers (`QM15FF`, `QM13FF`, `QF9AFF`, `QD4BFF`, `QD0FF`), then the orbit distorted with `ZH7X` / `ZV8X` and a `QD8FF` offset, and 4 iterations with "BPMs to zero":

  | Actuators | BPM reading RMS, before → after |
  |---|---|
  | correctors only | 22.3 → 15.0 |
  | correctors + movers | 22.3 → 14.2 |

  Movers stayed within +/-1000 um. The simulated BPMs read in um; the nominal simulated orbit is not zero, so the residual does not reach zero.
- The window opens with 51 actuators, the Mover max range row and the Corrector max strength box.
- Not checked on the real machine or by pressing START.

## Needs the response-matrix fix of the same branch
The mover matrix was all zeros with ATF2 data until the triangular cut was fixed in response-matrix (`_compute_qm_response_matrix`): the mover was looked up as `QM15FF`, which the recorded sequence does not contain. See the response-matrix change log.
