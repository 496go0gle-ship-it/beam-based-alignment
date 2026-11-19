# ブランチ `atf2-ext-orbit-analysis` の変更内容（beam-based-alignment）

ベース：`flight-simulator-framework/beam-based-alignment` の `master`（`04cbf5c`）
英語版：[CHANGES_atf2-ext-orbit-analysis.en.md](CHANGES_atf2-ext-orbit-analysis.en.md)

| コミット | 概要 |
|---|---|
| `b643faf` | BBA 画面の配色をテーマに合わせる（手元の変更を引き継ぎ） |
| `5487617` | 補正電磁石と四極ムーバーを一緒に使って軌道を補正する BBA を追加 |
| `9b66f50` | 統合版 BBA：ムーバーの扱いの修正、応答行列の確認画面、選択ファイルの読み込み、A / µm のログ |
| （このコミット） | 実機データで見つかった問題：応答の無い BPM を外す、向きが逆のエンコーダに対応 |

新しいファイル：`BBA_corrector_and_mover_GUI.py`。`BBA_GUI.py` と `BBA_QM_GUI.py` は変更していません。

## なぜ作ったか
`SysID_corrector_and_mover_GUI.py`（system-identification、同じブランチ）で、補正電磁石とムーバーの応答を1つのフォルダに測れるようになりました。研究の補正は両方を同時に使います（BPM より操作量が多い劣決定系で、最小ノルム解を求める）。ところが BBA は、補正電磁石（`BBA_GUI.py`）とムーバー（`BBA_QM_GUI.py`）のどちらか一方しか使えませんでした。

## 何をするか
- **アクチュエータ：** 補正電磁石すべてと、最終収束系の四極ムーバー22台（`QM16FF`〜`QD0FF`、統合版 SysID と同じ一覧）を1つの一覧に並べます。
- **応答行列：** 軌道データのフォルダから、補正電磁石の行列（`BBA_GUI.py` と同じ方法）とムーバーの行列（`BBA_QM_GUI.py` と同じ方法）を作ります。両方に共通する BPM にそろえて横に並べます。列は H 補正電磁石、V 補正電磁石、ムーバー x、ムーバー y の順、行は各 BPM の x、続いて y です。
- **単位をそろえる：** 各列をそのアクチュエータの最大値（Corrector max strength H/V、Mover max range X/Y [um]）で割ってから解き、解を元の単位に戻します。そろえないと、補正電磁石の列（T·mm や A）とムーバーの列（µm）で桁が大きく違い、特異値の打ち切りが意味を持ちません。最大値が 0 のときは「制限なし」として、その列はそろえずに警告をログに出します。
- **目標**（QM 版 BBA と同じ）：初期軌道の維持、BPM を0に、特定の BPM を0に。DFS と WFS は使いません。
- **解き方：** `BBA_GUI.py` の `_solve_correction()` を使います（rcond による打ち切り、または beta による正則化、最大値からの上下限、アクチュエータごとの重み）。
- **適用：** 補正電磁石は `set_correctors()`、ムーバーは `apply_qmag_xyroll()` で動かします。透過率がしきい値を下回ったら、両方を1つ前の回の値に戻します。
- **セッションごとに保存するもの：** `BBA_states/ITER_*_nominal.pkl`、`kicks.txt`（全アクチュエータの補正前・変化量・補正後）、`machine_status_after_correction.pkl`、`combined_bba_settings.json`。

## 確認結果（RF-Track シミュレーション、`ATF2_Ext_RFT`）
- 補正電磁石6台（`ZH9X`、`ZV10X`、`ZH10X`、`ZV11X`、`ZH1FF`、`ZV1FF`）とムーバー5台（`QM15FF`、`QM13FF`、`QF9AFF`、`QD4BFF`、`QD0FF`）を統合版 SysID で測りました。`ZH7X`・`ZV8X` と `QD8FF` のずれで軌道を乱し、「BPM を0に」で4回補正した結果：

  | 使ったアクチュエータ | BPM の読みの RMS（補正前 → 補正後） |
  |---|---|
  | 補正電磁石のみ | 22.3 → 15.0 |
  | 補正電磁石＋ムーバー | 22.3 → 14.2 |

  ムーバーは ±1000 µm の範囲内に収まりました。シミュレーションの BPM は µm 単位で読んでいます。シミュレーションの初期軌道がもともと0ではないため、補正後も0にはなりません。
- 画面は51項目の一覧、Mover max range の行、Corrector max strength の枠で開きます。
- 実機での動作と、START ボタンからの実行は確認していません。

## 同じブランチの response-matrix の修正が必要
response-matrix の三角化（`_compute_qm_response_matrix`）を直すまで、ATF2 のデータではムーバーの行列がすべて0になっていました。ムーバーを `QM15FF` という名前で並びの中から探していましたが、記録された並びにはその名前が無いためです。詳しくは response-matrix の変更ログを参照してください。

## 統合版 BBA の修正と確認画面（`9b66f50`）
使い方の詳細：[USAGE_corrector_and_mover_BBA.ja.md](USAGE_corrector_and_mover_BBA.ja.md)

- **ムーバーのデータが無いと補正全体が止まっていた：** ムーバーを1台でも選ぶと（何も選ばない＝全部も含む）、ムーバーの測定が無いフォルダでは `need at least one array to concatenate` で止まり、補正電磁石だけ選んだときしか動きませんでした。データの無いアクチュエータは外して続け、理由をログに出します。
- **Restore がムーバーを戻していなかった：** 「Restore initial settings」と履歴の Restore は補正電磁石しか戻していませんでした。開始時から動いたムーバーも戻します。DFS/WFS を使わないので、エネルギー・強度のリセットはしません。
- **データの有無を一覧に表示：** Trajectory data を選ぶと、各項目の右に `data` / `mover · data x,y` / `x only` / `no data` を表示し、フォルダに何が測られているかを知らせます。
- **応答行列の確認画面：** 「Check response matrix」（元の Compute response matrix）で、使った・使わなかったアクチュエータとその理由、行列（最大値まで動かしたときの軌道変化）、列ごとの強さ、特異値と rcond、最初の1回の予測（BPM を読むだけで機械は動かさない）を表示します。CSV / NPZ に保存できます。
- **選択ファイルの読み込み：** 補正電磁石とムーバーを1つのファイルで読み込めます（SysID 統合版と同じ規則）。区切りは改行・空白・カンマ、`#` はコメント。ムーバーは `QM15FF`、`qm15ff`、`QM15FF:x`、`MQM15FF` のどれでも可。選ばれなかった名前は理由とともに表示します。
- **ログ：** 毎回、補正電磁石は強度の単位（実機 A）、ムーバーは µm で、補正前→後と変化量を1行ずつ出します。ムーバーは読み戻した位置も出し、15 µm 以上ずれると `WARNING` を出します。`kicks.txt` に単位と読み戻し値の列を追加し、補正に使った行列を `combined_response_matrix.csv` / `.npz` に保存します。
- 新しいファイル：`beam_based_alignment/BBA_helpers/combined_actuators.py`、`beam_based_alignment/BBA_helpers/CombinedResponseDialog.py`、`USAGE_corrector_and_mover_BBA.ja.md`。

確認（RF-Track、`ATF2_Ext_RFT`）：補正電磁石6台＋ムーバー5台を統合版 SysID で測り、選択ファイルを読み込んで4回補正。行列は 76行×16列、ムーバーは毎回 µm で動き読み戻しも一致、軌道の指標 269 → 112、Restore でムーバーが 0 µm に戻ることを確認。補正電磁石だけのデータでムーバーを選んだ場合も止まらず、理由が表示されることを確認。START ボタンからの実行も確認。実機では未確認です。

## 実機データで見つかった問題（このコミット）
2026-11-19 16:54 の実機 SysID（補正電磁石20台、ムーバー21台）で確かめて見つかったものです。詳しくは [USAGE_corrector_and_mover_BBA.ja.md](USAGE_corrector_and_mover_BBA.ja.md) の最後の節。
- **応答の無い BPM を外す：** どのアクチュエータにも応答しない BPM（`MFB2FF`・`MIPA`・`MIPB` は 9.9999 mm 一定、FF の BPM 12台は NaN など）は、補正と RMS の指標から外し、`BPMs left out` として表示します。これらが「BPM→0」の残差の大半を占め、補正が効いていないように見えていました（RMS 2.8 mm → 外すと 0.44 / 0.61 mm）。
- **向きが逆のエンコーダ：** `QF1FF`・`QD0FF` の x エンコーダは設定値と逆向きに数えます。SysID のデータから向きを判定してデータ読み込み時と確認画面に表示し、補正後の確認では符号を直して移動量を比べます（以前は毎回誤った警告になるところでした）。応答行列そのものは response-matrix 側で設定値基準にしました。
- ログのムーバーの行は「setpoint（読み戻した設定値）, encoder moved（エンコーダの移動量）」の形にしました。`kicks.txt` の最後の列は読み戻した設定値です。
