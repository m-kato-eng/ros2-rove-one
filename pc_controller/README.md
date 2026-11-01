# PC Controller（Windows PC側）

Windowsの操作画面からSSH経由でPi上のROS 2へ指令を送り、4モーターの仮想PWM値を確認するテストプログラムです。**この版はdry-run専用で実モーターを回しません。** WindowsへのROSインストールやPython追加パッケージは不要です。

## 起動

PowerShellで次を実行します。

```powershell
cd C:\_Project\_RaspPi4_ROS\managed\pc_controller
.\start.ps1
```

Codex同梱Pythonがあれば自動使用します。別環境ではTkinter付きのPython 3.10以上とOpenSSHクライアントが必要です。スクリプト実行ポリシーで起動できない場合は、Pythonで`controller.py`を直接起動できます。

1. Piを起動し、有線接続する。
2. 「SSH接続」を押し、接続済みの表示を待つ。
3. 方向ボタンを離した状態で「有効化」を押す。
4. 前進・後退・旋回ボタンを押し続けると指令を送信する。離すと速度0。
5. 「停止/無効化」またはSpaceで無効化。Esc/緊急停止でラッチ停止。
6. 緊急停止後は「ラッチ解除」、続いて「有効化」が必要。
7. 終了時は「切断」またはウィンドウを閉じる。

フォーカスを別アプリへ移すと無効化します。速度の数値は目標値で、実測速度ではありません。

## 接続設定

`connection.json`で接続先・既存SSH鍵・known_hosts・Pi上のワークスペースを設定します。鍵パスはこのJSONからの相対パスです。秘密鍵は既存のものを参照し、コピー・表示しません。パスワードは保存せず、鍵認証だけを使用します。ホスト鍵が不一致の場合は接続を拒否します。

`log_directory`もJSONからの相対パスで指定し、現在は管理対象の外側にある`../../work_data/pc_controller/logs`へ記録します。省略時はプログラムと同じ場所の`logs/`を使用します。

Pi上には`pi4_motor_control`がビルド済みで、`~/ros2_ws/src/pi4_motor_control/scripts/pc_bridge.py`が必要です。接続時に自動でブリッジと専用のモーター制御ノードを起動し、切断時に終了します。

## 構成と停止動作

```text
Windows Tk画面
  → OpenSSH stdinのJSON指令（100 msごと）
  → Pi pc_bridge.py（rclpy、GPIOなし）
  → cmd_vel / enable / emergency_stop
  → pi4_motor_control（dry_run固定）
  → status JSON
  → SSH stdout → Windows画面・管理対象外のログ保存先
```

- ROS_DOMAIN_IDは既定88。さらに接続ごとに固有namespaceを作り、通常の`/cmd_vel`や別セッションから分離する。
- ブリッジはdry_run=trueを強制し、実出力への切り替え機能を持たない。
- PCの指令ハートビートが350 ms途絶えるとブリッジが速度0・無効化する。
- ブリッジ自体が停止した場合も、モーター制御ノードの500 ms watchdogで無効化する。
- GUIの停止・フォーカス喪失・接続途絶時に指令保持を解除する。復帰後の再走行には有効化が必要。
- これはSSHと一般OS上のソフトウェア検証で、停止時間の実時間保証や実機の電気的安全性を確認するものではない。

## 自動試験

```powershell
$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\controller.py --gui-check
& $py .\smoke_test.py
# 上記に加えGUI操作経路・停止・切断も確認し、結果を設定済みログ保存先へ保存
.\validate.ps1
```

PC→SSH→ROS→仮想モーター→PCの往復で、前進/後退/旋回、ボタン解放相当の0指令、緊急停止、ラッチ解除、指令途絶、再有効化、切断、再接続を検証します。テストはGPIOにアクセスしません。

## ファイル

|ファイル|用途|
|---|---|
|`start.ps1`|Windows起動用|
|`controller.py`|Tk操作画面|
|`transport.py`|SSHとJSON通信|
|`connection.json`|接続先・鍵ファイルの参照|
|`smoke_test.py`|実際のPiへ接続する往復自動テスト|
|`gui_test.py`|Tkイベント処理・実接続・操作・フォーカス喪失・GUI停止・切断の試験|
|`validate.ps1`|PC側の全検証を順次実行して結果を保存|
|`../../work_data/pc_controller/logs/`|状態・要求・エラー・検証の詳細ログ（管理対象外）|

Pi側の制御・ブリッジのソースは`../ros2_ws/src/pi4_motor_control/`にあります。初期実装の履歴は`../../前回の作業ログ/2026-10-28_モーター制御開発.md`、配置変更の記録は`../../前回の作業ログ/2026-10-31_構成管理対象の分離.md`を参照してください。
