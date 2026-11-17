# ros2-rove-one

> 個人の学習・実験を目的としたプロジェクトです。AIコーディングツールを活用して実装しており、設計や実装の検証を進めています。

2026-11-10：追尾対象の既定を床の赤色レーザー光点（red_laser_spot）へ変更。
旧ライト照射版もconfig/camera-light.yamlで保存。自動走行の目標有効期限は300ms。

Raspberry Pi 4とROS 2 Humbleによる4モーター制御・PC操作プロジェクト。

このフォルダーをGitリポジトリのルートとする。Windowsでは`C:\_Project\_RaspPi4_ROS\ros2-rove-one`、Piでは`/home/mk/ros2-rove-one`へcloneして使用する。GitHub上のリポジトリ名は`ros2-rove-one`。

```text
ros2-rove-one/
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
- [Piカメラ・画像認識ノード](ros2_ws/src/pi4_camera_vision/README.md)
- [地面上の明部追従・画像認識仕様案](docs/地面上の明部追従・画像認識仕様.md)
- [床の赤色レーザー光点・検出追跡仕様](docs/床の赤色レーザー光点・検出追跡仕様.md)
- [Linux環境の構成管理](environment/README.md)
- [Git作業コピーへの移行・復旧手順](docs/Git作業コピーへの移行.md)

Windowsの作業履歴とSSH鍵は親の`前回の作業ログ/`、PC実行ログ・検証結果は親の`work_data/`に置く。Piの稼働ワークスペースは`/home/mk/ros2-rove-one/ros2_ws`。Piはsparse checkoutでros2_wsとルートファイルのみを展開し、PCソフト・環境記録・docsは展開しない。移行後、ユーザーの依頼により旧Piワークスペースと移行用バックアップ、PCのSDカードバックアップは削除済み。

Linux環境の記録は`environment/`へ追加済み。保存履歴に加え、2026-11-01に実機から採取した設定原本と構成一覧を含む。クリーン環境からの再構築はまだ未検証。SDカードイメージ等の大容量バックアップは管理対象外に保管する。

2026-11-02、`pi4_camera_vision`を追加。カメラ取得・認識器の差し替え口・結果JSON・SSH経由の画像提供をPiで検証。
続いて画像下半分の明部・ライト照射点の認識と、pc_controller内の映像・赤い水平線・目標表示を追加した。
地面は平坦・水平、画像中央が水平線という前提で、カメラは手動調整する。
認識から自動で走行する接続と実距離の算出は未実装。起動手順・結果形式は上記カメラREADMEを参照。

## 自動走行

`autonomous_driving` が目標座標から操舵・相対距離・速度を計算します。PCで手動／自動を選択でき、自動走行中も停止できます。[設定と停止条件](docs/自動走行ノード仕様.md)。

## ライセンス

自作ROSパッケージ `pi4_motor_control` と `pi4_camera_vision` は、既存の宣言に従いApache-2.0です。各パッケージにライセンス本文を同梱しています。

採取したOS・第三者ソフトウェアの設定ファイルには、それぞれの配布条件が適用されます。リポジトリ全体を一律にApache-2.0とするものではありません。[第三者ファイルと確認状況](THIRD_PARTY_NOTICES.md)、[ライセンス本文と取得元](LICENSES/README.md)を参照してください。表示のない採取ファイルの配布条件には未確認事項が残っています。
