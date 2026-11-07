# Pi 4 カメラの自動起動設定

## 記録の状態

2026-11-06の会話で、ユーザーから「Pi 4のカメラを自動起動設定にした」と報告を受けた。
自動起動は設定済みとして記録する。ただし、今回の確認では無線192.168.1.21・有線192.168.50.2へのSSH接続がともにタイムアウトしたため、サービス定義・有効化状態・再起動後の動作は未確認。

**実際に登録した設定原本はまだ保存できていない。この文書だけでは、その設定を完全には再現できない。**
サービス名、system/userの区別、起動引数、実行ユーザー、再起動ポリシー、依存関係は、実機から採取後に追記する。

## 既存プログラムで確認できる起動方法

Piのワークスペース：`/home/mk/ros2-rove-one/ros2_ws`

起動スクリプト：`src/pi4_camera_vision/scripts/start_camera.sh`

このスクリプトはROS 2 Humbleとワークスペースの環境を読み込み、ROS_DOMAIN_IDの未指定時は88を設定して、camera_vision.launch.pyを実行する。

既存のPC映像表示向けの起動例（実際の自動起動設定に使われているかは未確認）：

```bash
bash /home/mk/ros2-rove-one/ros2_ws/src/pi4_camera_vision/scripts/start_camera.sh http_preview:=true local_preview:=false
```

- USBカメラ取得・画像認識・HTTPプレビューの構成。
- HTTPプレビューはPiの127.0.0.1:8765で待ち受け、PCはSSHトンネル経由で使用する。
- local_preview=falseならPiのデスクトップ表示は不要。
- カメラ設定は`src/pi4_camera_vision/config/camera.yaml`。
- カメラの二重起動は避ける。自動起動中は手動起動しない。
- カメラ起動の記録は、モーターの自動起動・有効化を意味しない。

## 実機接続後に保存する設定

systemdで登録した場合は、Piで候補を調べる。

```bash
systemctl list-unit-files --no-pager | grep -Ei 'camera|vision'
systemctl --user list-unit-files --no-pager | grep -Ei 'camera|vision'
```

見つかったサービス名を、以下の`実際のサービス名.service`へ置き換える。
システムサービスの場合：

```bash
systemctl cat 実際のサービス名.service
systemctl is-enabled 実際のサービス名.service
systemctl status 実際のサービス名.service --no-pager
journalctl -u 実際のサービス名.service -b -n 100 --no-pager
```

ユーザーサービスの場合はsystemctlとjournalctlに`--user`を付ける。
ユーザーサービスをログイン前から起動する構成では、`loginctl show-user mk -p Linger`も確認する。
systemd以外で設定した場合は、実際に使用したcron・デスクトップ自動起動・起動スクリプト等の原本を保存する。

採取した定義と関連スクリプトをこの文書と同じ管理対象へ保存し、その内容に合わせて登録・有効化・停止・解除コマンドを追記する。今回、実機の変更やサービスの新規登録は行っていない。
