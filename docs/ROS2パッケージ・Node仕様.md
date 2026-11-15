# ROS 2 パッケージ・Node仕様

2026-10-30整理。ローカルの実装ソースに基づく。2026-10-28にPiへ配置・ビルド・模擬動作検証済み。今回の整理で実機への再接続や再テストは行っていない。

## 1. 構成概要

独自に作成したROSパッケージは`pi4_motor_control`と、2026-11-02追加の`pi4_camera_vision`。
通常のモーター用PC操作セッションでは、Pi上で`pc_bridge`と`motor_controller`の2つのNodeが動作する。
カメラは別起動で、`camera_capture`・`object_recognition`と任意の`camera_http_bridge`が動作する。
カメラの詳細は[カメラ・認識ノード仕様](../ros2_ws/src/pi4_camera_vision/README.md)を参照。以下の既存表はモーター制御の仕様。

|項目|仕様|
|---|---|
|実行環境|Raspberry Pi 4 / Ubuntu 22.04 arm64 / ROS 2 Humble|
|独自パッケージ|`pi4_motor_control`、バージョン0.1.0|
|言語・ビルド|Python 3、ament_python、colcon|
|Pi上のソース|`/home/mk/ros2-rove-one/ros2_ws/src/pi4_motor_control`|
|Windows上のソース|`C:\_Project\_RaspPi4_ROS\ros2-rove-one\ros2_ws\src\pi4_motor_control`|
|登録されたROS実行ファイル|`motor_controller` → `pi4_motor_control.node:main`|
|Launch|`motors.launch.py`、引数`config`でパラメーターファイルを指定|
|既定設定ファイル|`config/motors.yaml`|
|想定車体|左右各2輪の4モータースキッドステア、L298N ×2|
|現在の運用|GPIOに触れないdry-run。実配線・実車走行は未検証|

WindowsのGUIはROS Nodeではない。PCにROS 2は導入せず、OpenSSHとJSONでPi上のブリッジに接続する。

## 2. パッケージ内部

|ファイル・クラス|役割|独立したROS Nodeか|
|---|---|---|
|`pi4_motor_control/node.py` / `MotorNode`|ROS入出力・パラメーター・定期制御|はい：`motor_controller`|
|`pi4_motor_control/control.py` / `Controller`, `Limits`|有効/無効、速度変換、制限、指令期限の処理|いいえ：制御Node内で使用|
|`pi4_motor_control/backends.py` / `DryRunBackend`|4モーターの符号付き仮想PWMを保持|いいえ|
|同 / `GpioBackend`|RPi.GPIOによる方向・PWM出力|いいえ：実出力未検証|
|`scripts/pc_bridge.py`|SSH JSONとROSの相互変換、制御Nodeの起動・終了|はい：`pc_bridge`|
|`launch/motors.launch.py`|設定ファイルを読み込み制御Nodeを起動|いいえ：Launch定義|

`pc_bridge.py`はソースファイルをPythonで起動する構成であり、`ros2 run`の実行ファイルとしては登録していない。

## 3. Nodeの名前と接続関係

|起動方法|Node名|Namespace / ROS_DOMAIN_ID|
|---|---|---|
|Piで単独Launch|`/motor_controller`|ルートnamespace、ドメインはシェルの設定に従う|
|PCからSSH接続|`/pc_trial_<PID>/pc_bridge`|接続ごとの固有namespace、ドメイン88が既定|
|PCから自動起動される制御Node|`/pc_trial_<PID>/motor_controller`|ブリッジと同じnamespace・ドメイン|

`<PID>`はPi上のブリッジのプロセスID。以降の表は単独起動時の名前を示す。PC操作時はすべてのトピック・サービス名の先頭に`/pc_trial_<PID>`が付く。

```text
Windows GUI（ROS Nodeではない）
  ⇅ SSH / JSON
pc_bridge Node
  ├─ cmd_velを配信 → motor_controller Node
  ├─ enable / emergency_stopサービスを呼出
  └─ statusを購読 ← motor_controller Node
                           └─ DryRunBackend（4輪の仮想出力）
```

## 4. motor_controller Node

### 4.1 ROSインターフェース

|区分|名前|型|用途|
|---|---|---|---|
|購読|`/cmd_vel`|`geometry_msgs/msg/Twist`|走行指令。履歴深さ1|
|配信|`/motor_controller/status`|`std_msgs/msg/String`|JSON形式の状態、10 Hz、履歴深さ1|
|提供サービス|`/motor_controller/enable`|`std_srvs/srv/SetBool`|true：有効化要求、false：停止・無効化|
|提供サービス|`/motor_controller/emergency_stop`|`std_srvs/srv/SetBool`|true：停止ラッチ、false：解除して無効状態を維持|

ROSが標準で生成するパラメーター等の管理インターフェースは上表から省略。

### 4.2 指令と出力

- 使用するTwistの軸は`linear.x`（m/s）と`angular.z`（rad/s）。正値は前進・左旋回。
- `linear.y`, `linear.z`, `angular.x`, `angular.y`は0でなければならない。NaN/Infを含む指令も拒否し、停止・無効化する。
- 指令の並進・旋回をそれぞれ上限内に制限した後、次の変換を行う。

```text
left  = linear.x - angular.z × track_width / 2
right = linear.x + angular.z × track_width / 2
scale = max(max_wheel_speed, abs(left), abs(right))
left_duty  = max_duty × left  / scale
right_duty = max_duty × right / scale
```

左前・左後にはleft_duty、右前・右後にはright_dutyを割り当て、各モーターのinvert設定を適用する。符号が回転方向、絶対値がPWMデューティー比。既定の最大絶対値は0.35（35%）。

これはエンコーダーなしの開ループ制御であり、実速度計測、PID、オドメトリ、TF、SLAM、Nav2は実装していない。車体寸法・速度換算値は未校正。

### 4.2.1 PC Controllerの走行・前輪旋回仕様（2026-11-02改訂）

以下はPC Controllerの専用`steer`指令に適用する。前節の`cmd_vel`による差動制御は従来どおりとする。2026-11-02にPiへ反映・再ビルド済み。単体試験21件、SSH経由の停止旋回・走行中の130%/70%補正、GUI操作・停止・再接続のドライラン試験が合格。実車での新しい旋回仕様の確認は未実施。

**走行中の旋回では、左右の後輪は走行時のDutyを維持する。前輪は走行時のDutyを基準に30%を加減算し、右旋回では左前輪を130%、右前輪を70%とする。左旋回では左右を逆にする。補正後のDutyが最大Dutyを超える場合は、その輪だけを最大Dutyで頭打ちとする。**

`D`を速度パラメーターから算出した符号付き走行Duty、`M`を最大Dutyとする。前進ではDは正、後退では負。`clip(x)`はxを−M〜＋Mに制限する操作とする。

|操作|左前輪|右前輪|左後輪・右後輪|
|---|---|---|---|
|前後進のみ|D|D|D|
|前後進＋右旋回|clip(1.3 × D)|clip(0.7 × D)|D|
|前後進＋左旋回|clip(0.7 × D)|clip(1.3 × D)|D|
|停止中の右旋回|＋A|−A|0|
|停止中の左旋回|−A|＋A|0|
|操作なし|0|0|0|

停止中の旋回に用いるAは、速度パラメーターによる前後進時のDutyの絶対値とする。後輪はPWM出力0とし、前輪だけを左右逆方向に回す。走行中の30%補正は停止中の旋回には適用しない。

後退中も右旋回入力は左前輪130%・右前輪70%、左旋回入力はその逆とし、全輪の後退方向を維持する。この左右倍率の指定では、同じ左右入力でも車体の向きの変化は前進時と後退時で逆になる。

走行Dutyの算出式は `D = M × clip(speed / max_wheel_speed, −1, 1)`。speedは±max_linearに制限する。旋回入力の正負で左右を選び、走行中の補正率は固定30%とする。最大Dutyで頭打ちになっても後輪や反対側の前輪は比例縮小しない。

実機設定（M=80%、max_wheel_speed=0.40）で速度0.1の場合、D=20%。前進＋右旋回は左前26%・右前14%・後輪各20%、後退＋右旋回は左前−26%・右前−14%・後輪各−20%となる。D=70%なら右旋回の左前輪は91%の計算結果を80%で頭打ちにし、右前輪49%・後輪各70%を維持する。

キー操作は↑または↓の一方と、←または→の一方の同時押しに対応する。一方を離すと残った操作を継続する。↑↓同時、←→同時を含む組み合わせでは全輪出力0とする。全キー解放、停止・無効化、緊急停止、フォーカス喪失、指令期限切れでは既存の停止処理を適用する。

通信はPC→SSH JSONの`{"op":"steer","speed":0.1,"turn":-0.1}`を、ROSの`wheel_command`（std_msgs/msg/String）の`{"mode":"steer","speed":0.1,"turn":-0.1}`へ変換する。turnは正が左入力、負が右入力、0が旋回なし。PC画面ではturnの絶対値に速度パラメーターを設定する。

### 4.3 状態JSON

```json
{
  "dry_run": true,
  "enabled": false,
  "emergency_stop": false,
  "reason": "startup",
  "duties": {
    "left_front": 0.0,
    "left_rear": 0.0,
    "right_front": 0.0,
    "right_rear": 0.0
  }
}
```

|フィールド|意味|
|---|---|
|`dry_run`|GPIOを使わない模擬出力か|
|`enabled`|指令を出力へ反映できる状態か|
|`emergency_stop`|緊急停止がラッチされているか|
|`reason`|直近の制御状態の理由|
|`duties`|invert適用後の4輪の符号付き出力値。実測速度ではない|

reasonの値：`startup`, `disabled`, `awaiting_command`, `command`, `command_timeout`, `invalid_command`, `emergency_stop`, `estop_cleared_reenable_required`, `shutdown`。reasonだけで状態を判断せず、enabledとemergency_stopを併せて参照する。終了時のshutdownは内部設定されるが、終了前の状態配信は保証しない。

### 4.4 パラメーター

次は独自に宣言するパラメーター。すべて読み取り専用で、起動時に指定する。

|名前|型|既定値|意味・制約|
|---|---|---|---|
|`dry_run`|bool|true|trueでGPIO未使用|
|`hardware_confirmed`|bool|false|実GPIO使用時はtrueが必要|
|`track_width`|double|0.20|左右車輪間隔 [m]、有限・正|
|`max_linear`|double|0.30|並進速度指令の絶対値上限 [m/s]、有限・正|
|`max_angular`|double|1.0|角速度指令の絶対値上限 [rad/s]、有限・正|
|`max_wheel_speed`|double|0.40|PWM換算・左右出力の比例縮小基準 [m/s]、有限・正|
|`max_duty`|double|0.35|デューティー絶対値上限、0より大きく1以下|
|`command_timeout`|double|0.5|指令期限 [s]、有限・正|
|`control_rate`|double|50.0|定期制御 [Hz]、10〜100|
|`pwm_frequency`|double|100.0|ソフトウェアPWM [Hz]、実GPIO時10〜2000|
|`<motor>.pins`|integer array|[-1,-1,-1]|BCM番号の[IN1, IN2, EN]|
|`<motor>.invert`|bool|false|回転方向反転|

`<motor>`はleft_front / left_rear / right_front / right_rearの4種類。ピンは各2〜27、全12本の重複なしが実GPIOの起動条件。既定は未割当。dry-runではピンを使用しない。

### 4.5 停止・再開

|条件|動作|復帰方法|
|---|---|---|
|起動直後|無効・出力0|enable=trueを要求|
|enable=true|出力を一度0にし、有効化。指令待ちを開始|期限内に新しい指令を受信|
|enable=false|即座に停止・無効化|再有効化が必要|
|有効中に0.5秒指令なし|停止・無効化|指令再送だけでは復帰せず再有効化|
|異常指令|停止・無効化|正常指令と再有効化|
|emergency_stop=true|停止・無効化・ラッチ|enable=trueで解除・再有効化。またはfalseで解除のみ|
|ラッチ中のenable=true|旧指令を破棄し、ラッチ解除・有効化|新しい指令から走行可能|
|通常終了|バックエンド停止・リソース解放|再起動後も無効開始|

無効中の指令は保存・再生しない。有効化した時点から指令期限を計測するため、単独操作では先に10 Hz等で指令を送信してから有効化するとよい。

期限判定はmonotonic時刻、定期制御はSTEADY_TIMEを使い、ROS時刻停止の影響を受けない。受信時刻で判断し、Twistに送信時刻がないため送信元で古くなった指令を識別する機能はない。監視設定値は実時間の停止保証ではない。

## 5. pc_bridge Node

|項目|仕様|
|---|---|
|起動元|Windowsのtransport.pyがSSH経由でPythonスクリプトを実行|
|Node名|`pc_bridge`|
|名前空間|`/pc_trial_<PID>`|
|制御Node|子プロセスとしてmotor_controllerを起動|
|実GPIO|dry_run=true / hardware_confirmed=falseを強制。切替機能なし|
|ROS配信|cmd_vel、最大おおむね10 Hz|
|ROS購読|motor_controller/status|
|ROSサービスクライアント|enable / emergency_stop|
|PC入力|標準入力のJSON Lines|
|PC出力|標準出力のJSON Lines（ready / status / response / event）|
|ハートビート期限|drive受信から350 ms。途絶時に0指令・無効化要求|
|待機期限|起動時のROS発見20秒、サービス応答待ち3秒|
|終了|標準入力終了またはshutdownで停止処理後に子Node終了|

PC入力例：

```json
{"op":"drive","linear":0.1,"angular":0.0}
{"op":"enable","value":true,"id":1}
{"op":"estop","value":true,"id":2}
{"op":"shutdown"}
```

- driveの並進値を±0.3、角速度を±1.0へ制限し、Node側でも再度上限処理する。
- enable=true要求には350 ms以内のdrive受信と、並進・旋回がともに0の条件が必要。
- 受信キュー内で350 ms以上経過した要求は期限切れとして拒否し、無効化する。
- PC側のドメイン既定88はconnection.jsonで指定され、ブリッジ起動前の環境変数として設定される。ブリッジのROSパラメーターではない。
- PC接続時はmotors.launch.pyやmotors.yamlを使わず、制御Nodeの既定値と上記のdry-run強制指定で起動する。YAML変更はこのPCセッションへ自動反映されない。

## 6. 実GPIOバックエンドの実装範囲

GpioBackendはL298Nの各モーターにIN1・IN2・ENを割り当てる。起動時は全ENをLOWにしてから方向ピンを設定し、PWMを0で開始する。出力符号の変更時は全PWMを0にして20 ms待ってから方向を変更する。通常終了時はPWM停止・LOW出力・使用ピンのcleanupを試みる。

現在はピン未割当、GPIO権限未付与で実出力未検証。SIGKILLやOS/電源異常で停止処理を保証するものではなく、実車移行には配線・電源・外部停止回路・校正の確認が必要。

## 7. 公式パッケージとの関係

|パッケージ/ツール|用途|
|---|---|
|`rclpy`|PythonのROS Node・通信・タイマー|
|`geometry_msgs`|Twist速度指令|
|`std_msgs`|String状態配信|
|`std_srvs`|SetBoolサービス|
|`rcl_interfaces`|読み取り専用パラメーターの宣言|
|`launch`, `launch_ros`, `ament_index_python`|Launch起動・設定ファイル探索|
|`ament_python`, `colcon`|パッケージビルド・配置・テスト|
|`demo_nodes_cpp`, `demo_nodes_py`|ROS導入時のtalker/listener確認用。通常運用では不要|

公式パッケージの再実装は行っていない。上記は使用関係であり、OSに導入した全パッケージの一覧ではない。

## 8. 起動・確認

Pi単独での模擬起動：

```bash
source /opt/ros/humble/setup.bash
source ~/ros2-rove-one/ros2_ws/install/setup.bash
ros2 launch pi4_motor_control motors.launch.py
```

別ターミナルで同じ環境を読み込み、確認する：

```bash
ros2 pkg executables pi4_motor_control
ros2 node list
ros2 node info /motor_controller
ros2 topic echo /motor_controller/status
ros2 param list /motor_controller
```

PC操作時はWindowsのプロジェクトルートから`ros2-rove-one/pc_controller/start.ps1`を起動しSSH接続する。Piで同じグラフを調べる場合は`export ROS_DOMAIN_ID=88`を設定し、実際のnamespaceを`ros2 node list`で確認してから完全名を指定する。

## 9. 検証・関連資料

2026-10-28の記録：単体16件、ROS統合、PC往復、GUI操作経路が合格。実車・実GPIOの試験ではない。GUIのフォーカス喪失は条件注入によるハンドラー検証。

- [ROS制御パッケージ説明](../ros2_ws/src/pi4_motor_control/README.md)
- [PC操作プログラム説明](../pc_controller/README.md)
- [構成図](ROS2構成図.md)
- [開発・失敗・再試行記録](../../前回の作業ログ/2026-10-28_モーター制御開発.md)

## 自動走行の追加

`object_recognition` → `/vision/ground_target` → `autonomous_driving` → `autonomous/command` → `pc_bridge`（PCで手動／自動を選択）→ `motor_controller`。
PCの停止・緊急停止と通信監視は両モード共通。[自動走行ノード仕様](自動走行ノード仕様.md)を参照。

2026-11-10自動追従更新：wheel_commandのmode=auto_steerは自動走行専用ゲイン2（走行中の前輪±60%、その場旋回は従来出力）。手動mode=steerは±30%を維持。近接目標では前進0で左右へその場旋回する。
