# ブランチ `atf2-ext-orbit-analysis` の変更内容（beam-based-alignment）

ベース：`flight-simulator-framework/beam-based-alignment` の `master`（`04cbf5c`）
英語版：[CHANGES_atf2-ext-orbit-analysis.en.md](CHANGES_atf2-ext-orbit-analysis.en.md)

| コミット | 概要 |
|---|---|
| `b643faf` | BBA 画面の配色をテーマに合わせる（手元の変更を引き継ぎ） |
| （このコミット） | 補正電磁石と四極ムーバーを一緒に使って軌道を補正する BBA を追加 |

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
