# Changes on branch `atf2-ext-orbit-analysis` (beam-based-alignment)

Base: `flight-simulator-framework/beam-based-alignment` `master` at `04cbf5c`.
Japanese version: [CHANGES_atf2-ext-orbit-analysis.ja.md](CHANGES_atf2-ext-orbit-analysis.ja.md)

| Commit | Summary |
|---|---|
| `b643faf` | Use palette colours in the BBA window (carried over from the working copy) |
| `5487617` | Add a BBA that corrects the orbit with correctors and quadrupole movers together |
| `9b66f50` | Combined BBA: mover fixes, response-matrix check window, selection files, logs in A / um |
| `d9b7acb` | Issues found on machine data: leave out BPMs without response, handle reversed encoders |
| `6a4b21f` | Max \|BPM\| orbit metric; select the SysID BPMs when none is selected |
| `4e2350c` | BBA stopped on the corrector readback check on the machine: round to 1 mA, wait a little before judging |
| `d5259a7` | Record settings and log; restore a session's settings |
| `927be5f` | When the code commit cannot be read, record git's reason |
| (this commit) | Stop the correction when the orbit metric is at or below a threshold |

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

## Combined BBA fixes and check window (`9b66f50`)
How to use it (Japanese): [USAGE_corrector_and_mover_BBA.ja.md](USAGE_corrector_and_mover_BBA.ja.md)

- **No mover data stopped the whole correction:** selecting any mover (or nothing, i.e. everything) on a folder without mover data stopped with `need at least one array to concatenate`, so only corrector-only selections ran. Actuators without data are now left out and the reason is logged.
- **Restore did not move the movers back:** "Restore initial settings" and the history Restore only restored correctors. Movers that moved since the start are restored too; no energy/intensity reset, since DFS/WFS are not used.
- **Data shown in the list:** after choosing the trajectory folder each item shows `data` / `mover · data x,y` / `x only` / `no data`, and a summary of the folder is shown.
- **Response-matrix check window:** "Check response matrix" (formerly Compute response matrix) shows the actuators used and not used (with the reason), the matrix (orbit change at each actuator's maximum), column strengths, singular values with rcond, and the first step predicted from the current orbit (reads BPMs, moves nothing). Saves CSV / NPZ.
- **Selection files:** one file with correctors and movers (same rules as the combined SysID): newline/space/comma separated, `#` comments; a mover may be written `QM15FF`, `qm15ff`, `QM15FF:x` or `MQM15FF`. Names not selected are reported with the reason.
- **Logs:** every iteration prints one line per actuator, correctors in their strength unit (A on the machine), movers in um, with the mover position read back (`WARNING` beyond 15 um). `kicks.txt` gains unit and read-back columns; the matrix used is saved as `combined_response_matrix.csv` / `.npz`.
- New files: `beam_based_alignment/BBA_helpers/combined_actuators.py`, `beam_based_alignment/BBA_helpers/CombinedResponseDialog.py`, `USAGE_corrector_and_mover_BBA.ja.md`.

Checked (RF-Track, `ATF2_Ext_RFT`): 6 correctors + 5 movers measured with the combined SysID, selection file loaded, 4 iterations: 76 x 16 matrix, movers moved every iteration in um with matching read-backs, orbit metric 269 -> 112, Restore brought the movers back to 0 um. With corrector-only data and movers selected the correction runs with the correctors and reports why. Run from the START button as well. Not checked on the machine.

## Issues found on machine data (`d9b7acb`)
Found with the 2026-11-19 16:54 machine SysID (20 correctors, 21 movers); details in the last section of [USAGE_corrector_and_mover_BBA.ja.md](USAGE_corrector_and_mover_BBA.ja.md).
- **BPMs without response are left out:** a BPM no actuator moves (`MFB2FF`, `MIPA`, `MIPB` read a constant 9.9999 mm, 12 FF BPMs are NaN, ...) is removed from the correction and the RMS metric and listed as `BPMs left out`. They made up most of the BPM->0 residual, so the correction looked ineffective (RMS 2.8 mm; 0.44 / 0.61 mm without them).
- **Reversed encoders:** the x encoders of `QF1FF` and `QD0FF` count opposite to the setpoint. The sign is taken from the SysID data, shown when the folder is loaded and in the check window, and used when checking the move after each step (it would otherwise warn every time). The matrix itself is now per setpoint (response-matrix).
- Mover log lines now read "setpoint <read back>, encoder moved <change>"; the last `kicks.txt` column is the setpoint read back.

## Orbit metric and BPM selection (`6a4b21f`)
- **Orbit metric (plot and log):** `Max |BPM|` (default), `RMS` or `Norm` (as BBA_GUI.py), used for the plot, the log and the predicted step; the solver is unchanged. Each iteration logs the largest deviation with its BPM, and the RMS.
- **BPM selection:** when the trajectory folder is chosen and no BPM is selected, the BPMs of the SysID (`bpms.txt`) are selected (with none selected, every BPM would be used).
- **Help texts:** the "?" help of the three objective weights and of Corrector max strength still described DFS / WFS (BBA_GUI.py); they now describe what they do here. "Reset reference orbit", which has no effect here (the reference is the orbit at each START), is hidden.
- **Remove coupling:** now applied in the combined BBA too (an x column acts only on x, a y column only on y); it was ignored before.
- The usage guide now explains the BBA flow, the interface calls, why each column is divided by its maximum, and the encoders.

## BBA stopping on the corrector readback check (`4e2350c`)
- **What happened:** on the machine, START stopped while setting the correctors, after `<corrector>:currentRead did not reach target … within 1.00s`. `InterfaceATF2_Ext.set_correctors` wants the readback within 0.1 mA of the written value in 1 s, writes again up to 3 times, then returns `False`, and BBA stops on that.
- **Likely cause:** the supplies seem to read back in 1 mA steps (in the machine SysID data, `ZV9X` was written -0.00804 A and read -0.00800 A). SysID setpoints are almost always whole mA, so they pass; BBA solutions such as 0.123457 A cannot come within 0.1 mA.
- **Change:**
  - Correctors in A are written in whole mA (rounded without passing the limit). The predicted step, the log and `kicks.txt` show the rounded value. The simulation (gauss*m) is not rounded.
  - If the interface still returns `False`, BBA waits up to 10 s and goes on when every readback is within 1 mA of its target (one log line). Otherwise it stops and shows target, setpoint and readback of each corrector that is off.
  - The interface (machine-interfaces) is unchanged.
- **Checked:** with the response matrix from the machine SysID data (62 columns) and a fake interface whose supplies read back in 1 mA steps against a 0.1 mA tolerance:
  - unrounded values are refused (`False`)
  - rounded values pass at once
  - a slow supply passes after 0.9 s
  - a stuck supply stops BBA with its name and values
  - gauss*m values are not rounded
  - Two iterations with 6 correctors and 5 movers and Restore also pass in the RF-Track simulation. Not yet checked on the machine.

## Settings and log record, restoring settings (`d5259a7`)
- **Why:** to know afterwards which settings a correction used, and to run again with the same ones. The settings file was written only at the end of a correction, so nothing was left when it stopped on an error. Some options and the log text were not saved, and "Restore desired session's settings" could not read a combined session.
- **Change** (new file `beam_based_alignment/BBA_helpers/combined_session.py`):
  - `combined_bba_settings.json` is written when START is pressed, then completed after each iteration and at the end.
    - `run`: start and end time, iterations done, and how the run ended (finished / stopped / error, with the reason). If it still says `running`, the program did not reach the end.
    - `settings`: every option of the window. These are now recorded too:
      - transmission threshold
      - Remove coupling, jitter subtraction and triangular check boxes
      - BPM samples
      - selected actuators and BPMs
      - how correctors are written
      - the commit of the code
    - `used`: the columns and BPMs actually used, and more.
  - Every log line is appended to `bba_log.txt`.
  - "Restore desired session's settings" on a combined session puts every setting back in the window. Files in the previous format are read too.
  - A failure to write the record never stops the correction (a warning is logged).
- **Checked (RF-Track, `ATF2_Ext_RFT`):**
  - Two iterations with unusual settings gave a record marked `finished` with 2 iterations, every setting and the commits, and a 39-line log.
  - A corrector write error was recorded as `error` with its reason.
  - Restoring into a new window gave identical settings (no difference when recorded again).
  - The previous-format file reselected its 11 actuators.

## Reason when the code commit cannot be read (`927be5f`)
- On the machine, the record said "not a git checkout" for every repository, most likely because git refused (e.g. the checkout belongs to another user). The record now holds git's own reason, as "unknown: git says '...' (folder)". No git configuration is changed.

## Stop at a threshold (this commit)
- **Why:** the correction stopped only on the iteration count, STOP or the transmission threshold. The simulation studies stopped at "Max |BPM| below 0.1 mm", but BBA kept going after the orbit was small enough and could then move things for nothing (and run away).
- **Change:**
  - "Stop when orbit metric <= [mm]" in the Correction tab (0 = off, the default).
  - It is checked each time the orbit is measured, before a step. When the chosen metric (Max |BPM|, RMS or Norm; x and y together; against the objective) is at or below the threshold, nothing more is moved.
  - The log says "Stop threshold reached: …", and `run.reason` in `combined_bba_settings.json` says "target reached before iteration N: Max |BPM| … <= …" (status finished).
  - The threshold is recorded as `settings.stop_threshold` and restored.
- **Checked (RF-Track, `ATF2_Ext_RFT`, 6 iterations):**
  - Off: all 6 iterations ran.
  - At 60: the run stopped before iteration 3 at Max |BPM| 52.9 ≤ 60, and the record shows 2 iterations with the reason.
  - Restoring brought the threshold back.

---

## Design response matrix (Model response, `BBA_GUI.py`, `BBA_helpers/ModelResponse.py`, this commit)
- **What it does:** the corrector BBA (`BBA_GUI.py`) has a **Model response** button in the Trajectory data row. Instead of measuring the response, it kicks the selected correctors +/- in the RF-Track copy that Preview in simulation uses (the simulation loaded with the connected machine's magnet settings).
- **Saved and loaded:** the result is written in the SysID format (`DATA_<corrector>_p0000.pkl` / `_m0000.pkl`) to `~/CERN-Flight_Simulator-Data/<interface>_<time>_ModelResponse/orbit` and loaded as Trajectory data. When the dispersion weight is above 0, an `energy/` folder with the simulation's energy change is also written and loaded as DFS data (if it cannot be computed, a warning is shown and only the orbit data is used). `README_MODEL.txt` states that the data was computed, with the kick and dP/P. The matrix, the solver and the application of the correction are the same as for measured data.
- **Units:** when connected to the machine, the copy converts the correctors with the magnet calibration (mag_ki), so the matrix is per A like the machine. The kick is the interface's `sysid_corrector_kick` (0.01 for ATF2).
- **Sextupoles:** SysID measures and BBA corrects with the sextupoles off, so the model is computed with them off as well.
- **Nothing is sent to the machine.** Correctors only: the button is hidden in the QM BBA and the correctors + movers BBA.
- **Checked (RF-Track, `ATF2_Ext_RFT`, sextupoles off):**
  - 6 correctors (`ZH9X`, `ZV10X`, `ZH10X`, `ZV11X`, `ZH1FF`, `ZV1FF`): 6 orbit and 6 energy pairs written and both loaded (76x3 matrices with DFS).
  - `ZH7X` and `ZV8X` moved by +0.5 gauss*m, 4 iterations with the model matrix: RMS difference to the reference orbit x 0.417 -> 0.006 mm, y 0.818 -> 0.0007 mm. At +2.0: x 1.668 -> 0.025 mm, y 3.270 -> 0.003 mm.
  - From a saved ATF2 Ext (machine) status the copy works in A: largest `ZH1X` response -158.5 mm/A (MSF1FF). The ratio to plain RF-Track (-12.38 mm/(gauss*m)) is 12.80, close to the ZH calibration of 12.88 gauss*m/A.
  - All three BBA windows open; the button shows only in the corrector BBA.
- **Caution:** the 2026-11-19 measured response of `ZH1X` and `ZV1X` does not match the model (correlation 0.00 and 0.53). Compare with a measured response in the Response Matrix GUI before using it on the machine. Not run on the machine or from the START button.
