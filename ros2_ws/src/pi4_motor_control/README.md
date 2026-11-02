# Pi 4 / ROS 2 Humble / L298N ×2・4モーター

左右それぞれ2輪を動かすスキッドステア方式を仮定した、PythonのROS 2パッケージです。前輪操舵式やメカナム車輪の場合は制御方式を変更してください。

既定は **GPIOに触れないdry-run・起動時無効** です。配線番号はすべて未設定。実車は未検証です。

## ビルドと起動（PiのBash）

```bash
source /opt/ros/humble/setup.bash
cd ~/ros2-rove-one/ros2_ws
colcon build --packages-select pi4_motor_control
source install/setup.bash
ros2 launch pi4_motor_control motors.launch.py
```

別ターミナルでも`source ~/ros2-rove-one/ros2_ws/install/setup.bash`を実行してください。新しいSSHセッションでは基本のHumble環境のみ自動で読み込まれます。

## 模擬走行

既定設定のままで実行します。指令が0.5秒途絶えると無効化されるため、先に指令の継続送信を開始してから有効化してください。

```bash
# ターミナル2：前進指令を10 Hzで送信（Ctrl+Cで停止→0.5秒で自動無効化）
ros2 topic pub --rate 10 /cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.1}, angular: {z: 0.0}}'
# ターミナル3：有効化
ros2 service call /motor_controller/enable std_srvs/srv/SetBool '{data: true}'
# ターミナル4：状態を見る
ros2 topic echo /motor_controller/status
```

この手順では仮想PWM値だけが変化します。`dry_run: true`を確認してください。

```bash
# 通常停止（無効化）
ros2 service call /motor_controller/enable std_srvs/srv/SetBool '{data: false}'
# ソフトウェア緊急停止をラッチ
ros2 service call /motor_controller/emergency_stop std_srvs/srv/SetBool '{data: true}'
# ラッチ解除：この操作だけでは再走行しない
ros2 service call /motor_controller/emergency_stop std_srvs/srv/SetBool '{data: false}'
```

停止後は必要に応じてenableを再度呼びます。起動前・無効中に受信した指令は保持しません。NaN/Infまたは非対応軸の指令でも無効化します。正の`linear.x`が前進、正の`angular.z`が左旋回です。

## インターフェース

|種類|名前|型・内容|
|---|---|---|
|購読|`/cmd_vel`|`geometry_msgs/msg/Twist`、linear.x [m/s]・angular.z [rad/s]のみ|
|配信|`/motor_controller/status`|`std_msgs/msg/String`、JSON、10 Hz。dry_run / enabled / emergency_stop / reason / duties|
|サービス|`/motor_controller/enable`|`std_srvs/srv/SetBool`|
|サービス|`/motor_controller/emergency_stop`|`std_srvs/srv/SetBool`、trueでラッチ、falseで解除して無効のまま|

指令は深さ1・volatileで受信します。Twistには送信時刻がないため、受信時刻で期限を判定します。ネットワークから来た古い指令そのものを判別する機能はありません。

`v_left = linear.x - angular.z * track_width / 2`、`v_right = linear.x + angular.z * track_width / 2`を上限内へ比例縮小し、PWMへ変換します。エンコーダーなしの開ループです。m/sは目標値であり、実速度保証・オドメトリ・PID制御はありません。寸法・速度とPWMの対応は未計測の仮値です。

## 実配線へ移る前に記入する項目

`config/motors.yaml`を別ファイルへコピーし、実物を確認して設定します。**BCM番号**で`[IN1, IN2, EN]`を指定し、全12本を重複させないでください。配線番号の推測値は用意していません。

|モーター|基板/チャンネル|IN1 BCM|IN2 BCM|EN BCM|invert|
|---|---|---|---|---|---|
|left_front|要確認|未設定|未設定|未設定|要確認|
|left_rear|要確認|未設定|未設定|未設定|要確認|
|right_front|要確認|未設定|未設定|未設定|要確認|
|right_rear|要確認|未設定|未設定|未設定|要確認|

- 実際のL298N基板、モーターの定格/ストール電流、モーター電源、GND共通化を確認する。モーターはGPIOから給電しない。GPIOは3.3 V系で、5 Vを入力しない。
- ENA/ENBをPWM制御するため、対応する常時有効ジャンパーを外す。基板の5V-ENレギュレータージャンパーとは区別する。基板ごとの説明書を確認する。
- ENには外付けプルダウンを用意し、Pi起動前やプロセス強制終了時にモーターが有効にならない回路にする。モーター電源を切る物理スイッチを用意する。
- 車輪を浮かせ、モーター電源を切った状態で配線と設定を確認する。最初は`max_duty`を小さく設定し、実測の車輪間隔と速度校正値へ変更する。
- GPIOの利用権限は現在未付与。確認後に`mk`へ適切なアクセス権を設定し、SSHへ再ログインする。本パッケージをsudoで起動する運用にはしない。

実機を使うには`dry_run: false`、`hardware_confirmed: true`、有効な12ピン設定がすべて必要です。いずれか不足するとGPIOアクセス前に拒否します。起動してもenableするまでは停止状態です。

```bash
ros2 launch pi4_motor_control motors.launch.py config:=/home/mk/motors-hardware.yaml
```

## GPIOのテスター確認（モーター電源なし）

`config/motors.yaml`には確定したBCM割り当てを記入済みですが、通常設定は`dry_run: true`のままです。GPIOを一時的に出力して測るには、Pi上で全モーター用電池を外したうえで、次を実行します。指定した1本だけが約3.3Vになり、数秒後LOWへ戻ります。

```bash
cd ~/ros2-rove-one/ros2_ws
python3 src/pi4_motor_control/scripts/gpio_probe.py 17
```

`17`を確認したいBCM番号（4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22）に置き換えます。テスターの黒リードをPiのGND、赤リードを対象GPIOへ当てます。GPIO信号は3.3Vです。5V端子へは当てず、GPIOへ5Vを加えないでください。各ピンを個別に実行してください。この確認スクリプトはROSノードやdry-run設定を変更しません。

PWMはRPi.GPIOのソフトウェアPWMです。Linux負荷でジッターがあり、実時間保証はありません。通常終了時は停止処理を行いますが、SIGKILL・OS停止・電源異常ではソフトウェア停止を保証できません。ソフトウェア緊急停止サービスは物理非常停止の代わりにはなりません。現在は自動起動登録やGPIOの実出力を行っていません。

## 検証

```bash
cd ~/ros2-rove-one/ros2_ws
colcon test --packages-select pi4_motor_control --event-handlers console_direct+
colcon test-result --verbose
# インストール済みlaunch・topic・serviceを実際に検証（GPIOなし）
source install/setup.bash
ROS_DOMAIN_ID=87 python3 src/pi4_motor_control/scripts/smoke_test.py
```

単体テストは速度制限、タイムアウト、緊急停止、無効値、ピン検証、模擬GPIOの方向変更・終了処理を確認します。ROS統合テストは別ドメイン87でdry-runのみを使用します。実車の方向や電気的停止性能の検証にはなりません。

## 参照

- [ROS 2 Humble Pythonパッケージ構成](https://github.com/ros2/ros2_documentation/blob/humble/source/Tutorials/Beginner-Client-Libraries/Creating-Your-First-ROS2-Package.rst)
- [RPi.GPIO PWM](https://sourceforge.net/p/raspberry-gpio-python/wiki/PWM/)
- [Raspberry Pi GPIO・モーター接続](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
