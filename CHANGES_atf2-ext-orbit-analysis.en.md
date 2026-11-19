# Changes on branch `atf2-ext-orbit-analysis` (beam-based-alignment)

Base: `flight-simulator-framework/beam-based-alignment` `master` at `04cbf5c`.
Japanese version: [CHANGES_atf2-ext-orbit-analysis.ja.md](CHANGES_atf2-ext-orbit-analysis.ja.md)

| Commit | Summary |
|---|---|
| `b643faf` | Use palette colours in the BBA window (carried over from the working copy) |
| `5487617` | Add a BBA that corrects the orbit with correctors and quadrupole movers together |
| (this commit) | Combined BBA: mover fixes, response-matrix check window, selection files, logs in A / um |

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

## Combined BBA fixes and check window (this commit)
How to use it (Japanese): [USAGE_corrector_and_mover_BBA.ja.md](USAGE_corrector_and_mover_BBA.ja.md)

- **No mover data stopped the whole correction:** selecting any mover (or nothing, i.e. everything) on a folder without mover data stopped with `need at least one array to concatenate`, so only corrector-only selections ran. Actuators without data are now left out and the reason is logged.
- **Restore did not move the movers back:** "Restore initial settings" and the history Restore only restored correctors. Movers that moved since the start are restored too; no energy/intensity reset, since DFS/WFS are not used.
- **Data shown in the list:** after choosing the trajectory folder each item shows `data` / `mover · data x,y` / `x only` / `no data`, and a summary of the folder is shown.
- **Response-matrix check window:** "Check response matrix" (formerly Compute response matrix) shows the actuators used and not used (with the reason), the matrix (orbit change at each actuator's maximum), column strengths, singular values with rcond, and the first step predicted from the current orbit (reads BPMs, moves nothing). Saves CSV / NPZ.
- **Selection files:** one file with correctors and movers (same rules as the combined SysID): newline/space/comma separated, `#` comments; a mover may be written `QM15FF`, `qm15ff`, `QM15FF:x` or `MQM15FF`. Names not selected are reported with the reason.
- **Logs:** every iteration prints one line per actuator, correctors in their strength unit (A on the machine), movers in um, with the mover position read back (`WARNING` beyond 15 um). `kicks.txt` gains unit and read-back columns; the matrix used is saved as `combined_response_matrix.csv` / `.npz`.
- New files: `beam_based_alignment/BBA_helpers/combined_actuators.py`, `beam_based_alignment/BBA_helpers/CombinedResponseDialog.py`, `USAGE_corrector_and_mover_BBA.ja.md`.

Checked (RF-Track, `ATF2_Ext_RFT`): 6 correctors + 5 movers measured with the combined SysID, selection file loaded, 4 iterations: 76 x 16 matrix, movers moved every iteration in um with matching read-backs, orbit metric 269 -> 112, Restore brought the movers back to 0 um. With corrector-only data and movers selected the correction runs with the correctors and reports why. Run from the START button as well. Not checked on the machine.
