# ros2-rove-one

Raspberry Pi 4とROS 2 Humbleによる4モーター制御・PC操作プロジェクト。

この`managed`フォルダーをGitリポジトリのルートとする。親の`_RaspPi4_ROS`はCodexのプロジェクトルート。GitHub上のリポジトリ名は`ros2-rove-one`。

```text
managed/
├─ ros2_ws/src/pi4_motor_control/  ROSパッケージ・設定・テスト
├─ pc_controller/                 Windows操作プログラム・設定・テスト
├─ docs/                          仕様書・構成図
├─ environment/                   Linux構成・設定・再構築手順・変更履歴
├─ .gitignore
└─ README.md
```

- [PC操作プログラム](pc_controller/README.md)
- [ROSパッケージ](ros2_ws/src/pi4_motor_control/README.md)
- [パッケージ・Node仕様](docs/ROS2パッケージ・Node仕様.md)
- [構成図](docs/ROS2構成図.md)
- [Linux環境の構成管理](environment/README.md)

作業履歴とSSH鍵は親の`前回の作業ログ/`、PC実行ログ・検証結果は親の`work_data/`に置く。PC設定の相対パスはこの配置に合わせて更新済み。Pi側の`/home/mk/ros2_ws`は変更していない。

Linux環境の記録は`environment/`へ追加済み。保存履歴に加え、2026-11-01に実機から採取した設定原本と構成一覧を含む。クリーン環境からの再構築はまだ未検証。SDカードイメージ等の大容量バックアップは管理対象外に保管する。
