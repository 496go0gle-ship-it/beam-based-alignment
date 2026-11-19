# 補正電磁石＋ムーバーの BBA：使い方と確認方法

ブランチ：`atf2-ext-orbit-analysis`（beam-based-alignment と system-identification の両方）
対象：`SysID_corrector_and_mover_GUI.py` → `BBA_corrector_and_mover_GUI.py`

## 全体の流れ

```
1. SysID（統合版）   補正電磁石とムーバーを ± に振って軌道を記録する      → DATA_*.pkl のフォルダ
2. BBA（統合版）     そのフォルダを読み、応答行列を作る                   → 「Check response matrix」で確認
3. BBA（統合版）     START：補正電磁石とムーバーを同時に動かして補正する   → ログに A / µm で毎回表示
```

**ムーバーを BBA で使うには、手順1でムーバーも測っておく必要があります。** 応答行列は SysID のデータからしか作れないため、SysID で測っていないムーバーは BBA で選んでも使えません。

2026-11-19 のデータ（`ATF2_Ext_RFT_20261119_161430_KickerQM_Orbit`）は、`actuators.txt` に補正電磁石7台（ZV1X, ZX1X, ZV2X, ZH1X, ZV3X, ZH2X, ZV4X）しかなく、ムーバーの測定ファイル（`DATA_<四極>_x_p0000.pkl` など）がありません。そのため BBA ではムーバーを選ぶと補正が止まり（以前のエラー：`need at least one array to concatenate`）、補正電磁石だけ選んだときしか動きませんでした。

## 1. SysID（`SysID_corrector_and_mover_GUI.py`）

1. インターフェースを選びます（実機 `ATF2_Ext`、シミュレーション `ATF2_Ext_RFT`）。
2. 一覧から補正電磁石とムーバーを選びます。ムーバーは一覧の最後に並びます（`QM16FF` … `QD0FF` の22台）。
   - **組み合わせファイルを使う場合**：「Load actuators」で読み込みます。読み込み後に、選ばれた補正電磁石とムーバー、選ばれなかった名前とその理由が表示されます（ターミナルにも出ます）。
3. Mover initial X/Y [µm]（最初の振り幅、既定 100 µm）と Max mover range [µm]（上限、既定 1000 µm）を確認します。
4. START。終わるとフォルダに次のファイルができます。
   - 補正電磁石：`DATA_ZH9X_p0000.pkl` / `DATA_ZH9X_m0000.pkl`
   - ムーバー：`DATA_QM15FF_x_p0000.pkl`、`..._x_m0000.pkl`、`..._y_p0000.pkl`、`..._y_m0000.pkl`（x と y の両方が必要）
   - 選択：`actuators.txt`（全部）、`correctors.txt`、`quadrupole_movers.txt`

### 組み合わせファイルの書き方

1行に1つでも、空白やカンマで区切って複数でも構いません。`#` 以降はコメントです。

```text
# 上流の補正電磁石と最終収束系のムーバー
ZH9X, ZV10X, ZH10X, ZV11X
QM15FF QM13FF QD0FF
```

ムーバーは `QM15FF`、`qm15ff`、`QM15FF:x`、`QM15FF_y`、`MQM15FF`（四極に付いた BPM の名前）のどれで書いても `QM15FF` として選ばれます。

**選ばれない名前とその理由：**

| 表示 | 意味 |
|---|---|
| `quadrupole without a usable mover in this interface` | 四極ですが、このインターフェースではムーバーが使えません。ATF2 Ext では最終収束系の22台だけ（`QF1X`〜`QF21X` にはムーバーがありません）。シミュレーション（`ATF2_Ext_RFT`）も実機に合わせて同じ22台です。 |
| `not in this window's list` | 一覧にない名前です（綴り違いなど）。 |

### ターミナルの表示（SysID）

（シミュレーション `ATF2_Ext_RFT` での実際の出力。実機 `ATF2_Ext` では補正電磁石の単位が A になります。）

```
SysID correctors + movers: 6 correctors [gauss*m] (ZV10X, ZH9X, ...), 5 quadrupole movers [um] (QM15FF, ...), 1 iteration(s), 16 excitation(s) to measure
Corrector ZH9X '+' excitation: +0 -> +0.01 gauss*m (step +0.01 gauss*m)
  ZH9X: max|orbit change| in x = 0.02916 mm for +/-0.01 gauss*m; next excitation 0.018 gauss*m
Quadrupole mover QM15FF x '+' excitation: x +0.0 -> +100.0 um (step +100.0 um)
  QD0FF x: setpoint read back +100.0 um, encoder moved -99.9 um (encoder counts opposite to the setpoint)
  QM15FF:x: max|orbit change| x = 2.619, y = 0.002919 mm for +/-100.0 um; next excitation 84.0 um
```

補正電磁石はインターフェースの強度単位（実機 ATF2 Ext は A、シミュレーションは gauss*m）、ムーバーは µm で表示します。ムーバーは動かした後に、読み戻した設定値とエンコーダの移動量を表示します。設定値が要求から 15 µm 以上ずれたとき、またはエンコーダの移動量が要求と 15 µm 以上違うときに `WARNING` を出します。エンコーダは移動量の大きさで比べるので、向きが逆のエンコーダ（下記）で誤って警告することはありません。

## 2. BBA：データの読み込みと応答行列の確認（`BBA_corrector_and_mover_GUI.py`）

1. インターフェースを選びます（SysID と同じもの）。
2. **Trajectory data** のボタンで SysID のフォルダを選びます。
   - フォルダに何が測られているかが表示されます（補正電磁石の一覧、x と y の両方があるムーバーの一覧）。ムーバーが1台もなければ、そう書かれます。
   - 一覧の各項目の右側に、データの有無が出ます：
     - `data`：補正電磁石のデータあり
     - `mover · data x,y`：ムーバーの x と y のデータあり（使える）
     - `mover · x only`：片方だけ（使えない）
     - `no data`：データなし（使えない）
3. **Load**（補正器の一覧の Load）で組み合わせファイルを読み込むか、一覧から選びます。SysID と同じファイル・同じ規則で読めます。何も選ばないと、一覧の全部が対象になります（データのないものは自動で外れます）。
4. **Corrector max strength (H/V)** と **Mover max range [µm] (X/Y)** を確認します。応答行列の各列はこの最大値で割ってから解くので、ここの値で補正電磁石とムーバーの使われ方の比重が決まります。
5. **Check response matrix**（元の「Compute response matrix」ボタン）を押すと確認画面が開きます。

### 確認画面のタブ

| タブ | 見るもの |
|---|---|
| 上部の要約 | 行列の大きさ（行 = BPM 数 × 2、列 = 補正電磁石数 + ムーバー数 × 2）と、rcond で残る特異値の数。ムーバーが1台も入っていなければその旨。 |
| Actuators | 選んだアクチュエータごとに、データの有無・行列に入ったか・入らなかった理由。 |
| Matrix | 各アクチュエータを最大値まで動かしたときの各 BPM の軌道変化（mm）と、列ごとの強さ（青：補正電磁石、橙：ムーバー）。0 の列は補正に使えません。 |
| Singular values | 特異値と rcond の線。線より下の方向は beta = 0 のときに使われません。 |
| Predicted step | ボタンを押すと BPM を1回読んで、最初の1回で各アクチュエータをどれだけ動かすか、軌道の RMS がどう変わる予定かを表示します。**機械は動かしません。** 上限に当たったアクチュエータも表示します。 |

「Save matrix (CSV + NPZ)」で、データフォルダの `BBA_combined_check/combined_response_matrix.csv` に保存します（行 = `BPM:x` / `BPM:y`、列 = アクチュエータ、値 = 単位あたりの軌道変化）。

## 3. BBA：補正の実行

1. 目的の重みを設定します（QM 版 BBA と同じ）：Trajectory hold weight（初期軌道を保つ）、BPM->0 weight（BPM を0に）、Specific BPM->0 weight（特定の BPM を0に）。DFS / WFS は使いません。
2. Gain、rcond（または beta）、Iterations を設定して START。
3. ターミナル（とログ画面）に、毎回次のように出ます（シミュレーションでの実際の出力）。

```
Combined matrix: 76 rows (38 BPMs) x 16 columns (6 corrector, 10 mover): ZH9X, ..., QM15FF:x, ..., QD0FF:y
  QD8FF: no data in the trajectory folder (a mover needs x and y)      ← 使わなかったものと理由
Iteration 2/4: ||B||=173.276
  ZH9X      corrector  +0.03 -> -0.03 gauss*m  (step -0.06 gauss*m)
  QM15FF:x  mover      -870.3 -> -1000.0 um  (step -129.7 um)  setpoint -1000.0, encoder moved -129.7 um
  QM15FF:y  mover      +36.8 -> +206.6 um  (step +169.8 um)  setpoint +206.6, encoder moved +169.8 um
```

   - ムーバーは動かした後に、読み戻した設定値とエンコーダの移動量を表示します。エンコーダの向きは SysID のデータから判定し、向きが逆のもの（`QF1FF`・`QD0FF` の x）は符号を直して比べます。15 µm 以上ずれていれば `WARNING` を出します（補正は続けます）。
   - どのアクチュエータにも応答しない BPM（ビームが無い、または一定値を返す）は、補正と RMS の指標から外し、`BPMs left out` として名前を出します。
   - ムーバーを選んだのに1台も行列に入らなかったときは、`WARNING: movers are selected but none is in the matrix; only correctors will move` と出ます。
4. **Restore initial settings** は、補正電磁石に加えてムーバーも開始時の位置に戻します（以前は補正電磁石だけでした）。開始時から動いたムーバーだけを動かします。履歴（Iteration history）の Restore も同様です。

### セッションフォルダに保存されるもの

| ファイル | 内容 |
|---|---|
| `combined_response_matrix.csv` / `.npz` | 補正に使った応答行列（列ごとの単位つき） |
| `kicks.txt` | 時刻、回、アクチュエータ、補正前、変化量、補正後、単位、読み戻した設定値（タブ区切り） |
| `combined_bba_settings.json` | 設定、使った列、使わなかったアクチュエータとその理由 |
| `BBA_states/ITER_*_nominal.pkl` | 各回の補正前の状態 |

## 確認結果（RF-Track シミュレーション `ATF2_Ext_RFT`）

- 統合 SysID で補正電磁石6台（ZH9X, ZV10X, ZH10X, ZV11X, ZH1FF, ZV1FF）とムーバー5台（QM15FF, QM13FF, QF9AFF, QD4BFF, QD0FF）を測定 → ムーバーの x/y の DATA ファイルができることを確認。
- `QD8FF` のずれ（x +150 µm, y −120 µm）と ZH7X / ZV8X のキックで軌道を乱し、組み合わせファイルを Load、BPM->0 で4回補正：
  - 行列は 76 行 × 16 列（補正電磁石6列、ムーバー10列）。
  - 毎回ムーバーが µm 単位で動き、読み戻しが要求と一致。軌道の指標 269 → 112。
  - Restore initial settings で、動いた5台のムーバーが 0 µm に戻ることを確認。
- 2026-11-19 のデータ（補正電磁石のみ）でムーバーも選んだ場合：補正は止まらず、補正電磁石だけで実行され、ムーバーが使われない理由がログと確認画面に出ることを確認。
- 実機での動作は確認していません。

### 気をつける点

- 補正電磁石の最大値（Corrector max strength）は、起動時の設定値の 1.15 倍が初期値です。設定値がほぼ 0 だと最大値も小さく、補正電磁石はほとんど使われません（確認画面の Matrix タブで補正電磁石の列がほぼ 0 になります）。実際の上限に合わせて入力してください。
- ムーバーの列は、ムーバーより下流の BPM にしか応答がありません。選んだ BPM がすべて上流だと、その列は 0 になり、確認画面に `response is all zero` と出ます。

## 実機データ（2026-11-19 16:54、`ATF2_Ext_20261119_165411_KickerQM_Orbit`）で見つかったこと

このフォルダには、補正電磁石20台とムーバー21台（x と y、2回ずつ）の測定がそろっています。BBA で使えなかったのは、データが無かったからではなく、次の理由です。

1. **`QF1FF` と `QD0FF` の x エンコーダが、設定値と逆向きに数えている。** 設定値 +100 / −100 µm に対し、エンコーダ（`xact`）は −100 / +100 µm でした（他の19台と y はすべて同じ向き、比 1.00 ± 0.01）。応答行列はエンコーダ基準で計算されていた一方、BBA は設定値でムーバーを動かすため、この2列は補正の向きが逆になっていました。→ 応答行列を設定値（`xdes`/`ydes`）あたりで計算するように変更しました（response-matrix、QM 版 BBA にも効きます）。
2. **応答の無い BPM が軌道の指標を占めていた。** `MFB2FF`・`MIPA`・`MIPB` は x・y とも全ファイルで 9.9999 mm 一定、`MSF6FF` も一定、FF の BPM 12台は常に NaN でした。どのアクチュエータでも動かないので、「BPM→0」では毎回 10 mm 近い残差が残り、補正が効いていないように見えていました。→ 補正と指標から自動で外すようにしました。

この実機データを、新しいコードで機械を動かさずに計算した結果（BBA 開始時 18:27 の軌道を使用）：

| | 結果 |
|---|---|
| 応答行列 | 68 行（34 BPM）× 62 列（補正電磁石20列、ムーバー42列） |
| 外した BPM | 16台（上の2.） |
| 目的の RMS（x, y） | 0.44, 0.61 mm |
| 1回目の予測（gain 0.4） | 0.29, 0.38 mm |
| 1回目の予測（gain 1.0） | 0.16, 0.13 mm |

18:27 の BBA セッションは `ITER_0000` の測定のあとに何も残っておらず、ログも無いため、どこで止まったかはファイルからは分かりません。次に実機で実行するときは、ログ（ターミナル）を保存してください。
