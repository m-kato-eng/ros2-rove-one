# 環境の変更履歴

保存済み記録からの復元。日付不明・会話による二次的な要約・実機確認を区別する。設定例を実施済みとはみなさない。

## 2026-11-02：下半分の明部認識・PC内カメラ表示

- 地面は平坦・水平、画像中央を水平線、下半分を地面と仮定する仕様を確定。
  PC画像中央に赤い線を表示し、カメラ取付を手動で合わせる。
- BrightGroundDetectorを追加。PillowとNumPyはPiに既に導入済みで、APT・pipの追加導入なし。
  既定はlight_spot、最大10fps、結果の有効期限300ms。明部の輝度重心・矩形・左右ずれを提供する。
  上半分・境界・過度な白飛びを除外し、複数候補は曖昧さ、消失時は無効として扱う。
- /vision/ground_target、/vision/debug/image/compressed、HTTPの/target、/debug/frame.jpg、/debug/streamを追加。
  PCに映像を埋め込み、専用のSSHトンネル・受信スレッドで取得。モーター通信とは分離。
- Piで26件の試験、PCで実SSH映像・中央線の位置・停止時の画像消去の試験が合格。
  映像受信中の既存GUI操作・停止・フォーカス喪失・通信断をドライランで確認。
- 実カメラの画像40枚と認識結果39件を受信し、画像10fpsを確認。
  配信タイマーと認識待ちを削減し、JPEG完成時の即時配信と認識入力到着時の処理開始へ変更。
- 修正後80件の参考測定：認識処理の中央値57.67ms・95パーセンタイル60.65ms、
  JPEG受領→結果生成の中央値110.31ms・95パーセンタイル163.67ms・最大167.24ms。
  最終状態はambiguous。場面によって処理負荷が変わる。露光・カメラ内処理・PC描画は含まない。
  実ライトを動かした際の100ms以内の応答は未検証。達成済みとは扱わない。
- 起動切り替えで旧プロセスが残ったためカメラ関連だけ整理し、停止スクリプトstop_camera.pyを追加。
  認識からの自動走行・実距離校正は未接続。カメラ設定やモーターの実出力設定は変更しない。
- PC画面のスクリーンショットによる確認はアプリ承認のタイムアウトで取得できず、
  Tk上の実映像・Canvas座標を使った機能試験で確認。Gitコミット・pushは実施していない。

## 2026-11-02：USBカメラ取得・画像認識基盤の追加（初版の記録）

- 実機でLogitech C310（USB 046d:081b、by-id末尾video-index0）を確認。
  Cheeseではフレーム遅延とUSBリセットがあり、GStreamerによるMJPEG取得へ変更。
- `pi4_camera_vision`をPC作業コピーとPiの`/home/mk/ros2-rove-one/ros2_ws/src/`へ追加し、
  Piでcolcon build --symlink-installを実施。既存のGStreamer・ROS Python・sensor_msgsを利用し、追加APT導入なし。
- `camera_capture`がカメラを単独所有し、`object_recognition`が最新画像を最大2fpsで処理する。
  対象未定のため認識器はnone、結果はrecognition_disabled。モデル・OpenCVは未導入。
- `camera_http_bridge`がROS画像と認識結果をlocalhost:8765で提供。
  以前の単体プレビューを終了し、3ノードをROS_DOMAIN_ID=88、http_preview=true、local_preview=trueで起動。
  SSHトンネル・PCブラウザー・Piローカル表示の経路を継続。pc_controllerのコードは変更なし。
- 新規パッケージの試験19件合格。実カメラでROS画像40枚・結果9件を受信し、実効約9.75fps、
  JPEGサイズ320×240、時刻の単調増加、認識未設定の明示を確認。
  PCからSSH経由で/health・/results・/frame.jpgの取得を確認。
- 取得用GStreamerのSIGSTOPによる停止模擬で、期限切れ時の結果空配列・frame=null、
  スナップショットHTTP 503、自動再接続を確認。画像再開まで約10秒。
  初回起動時も一度フレーム待ちタイムアウトがあり、自動再試行後に配信開始。
- 起動方法・設定・API・制限は[カメラREADME](../ros2_ws/src/pi4_camera_vision/README.md)。
  自動起動サービスは未登録。実物体認識、実空間座標、GUIへの埋め込みは未実装。
- 配置はこの作業中のソース転送であり、Gitコミット・push・Piでのpullは実施していない。

## 2026-11-02：GPIOシャットダウンボタンの修正

- GPIO3（物理5番）とGND（物理9番）のボタンを対象に実機調査。gpio-shutdown overlayと入力デバイス`/dev/input/event0`を確認。11:12:39 JSTのlogindログに`Power key pressed`があり、押下がOSに届くことを確認。
- Xfce Power Manager 4.16が`handle-power-key`の抑止を保持していた。ユーザーmkの`/xfce4-power-manager/logind-handle-power-key`をtrueに設定し、電源キーをlogindへ委譲。
- 修正直後に抑止の解除とlogindの`HandlePowerKey=poweroff`を確認。設定反映のための再起動は実行していない。その後、ユーザーより物理ボタンによるシャットダウン成功の確認報告あり。OS停止後の5 V電源遮断を意味するものではない。
- 変更前XMLはPiの`/home/mk/shutdown-button-backup-20261102/xfce4-power-manager.xml`へ保存。
- 再現コマンド（mkのXfceセッションに接続できる環境で実行）：

  ```bash
  xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/logind-handle-power-key -n -t bool -s true
  systemd-inhibit --list --no-pager
  ```

- [Xfce公式の設定説明](https://docs.xfce.org/xfce/xfce4-power-manager/faq#how_can_i_make_logind_handle_button_events_instead_of_xfce4-power-manager)。

## 2026-08-09以前：初期環境

- Ubuntu 22.04系arm64をRaspberry Pi 4 Model Bへ導入済み。
- SSH Server、XFCE、Python関連ツール、RPi.GPIOを準備。
- WindowsのVS Code Remote SSHで開発。有線SSHとWi-Fiインターネットを使用。
- **初期イメージのファイル名・入手元・ハッシュ・実施順は未確認。** 観測されたUbuntu 22.04.5という版だけから初回イメージを断定しない。

出典：[セットアップ経緯](../../セットアップ経緯.md)、[復元メモ](../../作業履歴_復元.md)。

## 2026-08-09〜10：実機調査

- Ubuntu 22.04.5 LTS / カーネル5.15.0-1093-raspi / arm64を確認。
- XFCE 4.16、コンポジター無効、GDM起動を確認。
- Python 3.10.12、ユーザー領域のRPi.GPIO 0.7.1を確認。
- microSD約32 GB、swapfile 1 GiB、swappiness=60、GPUメモリ256 MB。
- ROS 2は未導入。GPIOデバイスはdialoutグループ、操作ユーザーは未所属。
- SSH接続用の鍵を作成・登録。通常鍵のACL検査失敗後、専用鍵で接続成功。

## 2026-10-23：過去会話の再開

「ラズパイ構築再開」の本文にはUbuntu 22.04 LTS 64-bit導入済みという要約と、セットアップ作業記録Markdownへのリンクがある。「ラズパイ制御相談確認」にも構成の要約がある。

これらは過去の作業を要約した回答で、元のOS導入会話やイメージ名を直接確認できたわけではない。会話中のLED動作確認等も、本書では実機再確認済みとして扱わない。生成されたMarkdown本文は今回取得していない。

## 2026-10-28：ROS 2導入

- 実機OSはUbuntu 22.04.5、カーネルは5.15.0-1110-raspi。8月の記録との差は確認したが、カーネル更新の実施日時・操作は不明。
- Universeを有効化、curlを導入。en_US.UTF-8を生成しLANGを設定。
- ros2-apt-source 1.3.0~jammyを公式配布元から導入。
- ros-humble-ros-base、ros-dev-tools、C++/Pythonデモと依存349パッケージを導入。
- ~/.bashrcへHumble環境読み込みを追加。rosdep初期化・Humble向けキャッシュ更新。
- /home/mk/ros2_wsを準備し、C++ talker→Python listenerの14件受信を確認。
- モーター制御パッケージとPC操作プログラムを作成・配置。dry-runで単体16件、ROS統合、PC往復、GUI操作経路の試験が合格。
- 失敗・修正：初回SSHの実行環境制限、対話sudo切替、単体テスト未収集、終了時の重複SIGINT、GUIフォーカス試験条件を修正して再検証。詳細は元ログに保持。
- GPIOの権限変更、実ピン設定、実モーター駆動、自動起動登録は未実施。

## 2026-10-31：PC側構成の整理

- PCフォルダーを日付付き名称からpc_controllerへ変更。
- コードと仕様書をmanaged、実行ログをwork_dataへ分離。
- 鍵参照・ログ保存先を修正し、ローカルGUI・構文・リンクの確認に成功。
- Pi側のOSやワークスペース配置は変更していない。

## 2026-11-01：バックアップと環境記録

- ユーザーがSDイメージを取得・Windowsで圧縮。元imgと展開後imgのハッシュ比較でTrueを報告。
- ローカル保管先に圧縮ファイルが存在することを確認。復元・起動試験は未確認。
- ユーザーが普段使いのGit for Windowsをインストールし、動作したと報告。
- 本environmentフォルダーを作成。実機の再採取、設定適用、クリーン構築試験は実施していない。
- ユーザーの確認を受け、旧メモと実機調査を再照合。configへデスクトップ変更・コンポジター無効化・自動ログインの詳細を補足した。
- 会話調査の初回呼出しは件数上限により拒否され、上限内で再試行成功。関連2会話の本文・直近一覧・アーカイブ一覧を確認したが、初期イメージの固有名は未特定。全過去会話を網羅した検索ではない。
- 保存APTログから349件の名前・版を抽出し、重複がないこととTSV件数を確認。関連文書リンク19件とシェルのLF改行も確認。
- 採取スクリプトの構文検査は、Windows実行環境の権限制限でBash自体の起動が拒否され未完了。権限拡張やPiでの実行は行っていない。

## 2026-11-01：実機からの設定採取

- ユーザー指示に従い、未適用の起動高速化案を環境管理資料から除外した。過去の元資料は書き換えていない。
- 既存SSH鍵で実機へ接続し、読み取りのみで設定を採取した。実機へのインストール、サービス操作、設定変更は行っていない。
- ブート・GDM・XFCE・自動起動・sysctl等の設定原本102件をconfig/observed-2026-11-01へ保存。
- APT導入済み2,166件、Pythonライブラリ157件、Snap・サービス状態・カーネルモジュール・systemdリンク139件を保存。
- 今回の起動所要時間は49.871秒。過去より短い理由や変更操作は断定しない。
- 通常環境のSSH接続拒否後に許可された実行で接続成功。パッケージ一覧の過剰検出を修正、GUIの版はパッケージ管理情報から再取得。有効サービスの限定照会タイムアウトは、取得済み全サービス状態一覧とリンク情報で補った。
- AccountsServiceのユーザー設定原本は権限不足。D-BusでのXSession値は空文字。Xセッション定義は別途取得した。
- 元データはwork_data/environmentに保持。新規採取用Pythonの構文、設定原本102件のハッシュ、構成一覧の件数、文書リンク34件を照合して成功。採取用SSH接続はすべて終了。

## 2026-11-01：採取出力を構成管理対象へ取り込み

- ユーザー指示により、work_dataの採取出力をsnapshots/2026-11-01へコピーした。
- 基本採取と補足採取の元出力120ファイルすべてについて、コピー前後のSHA-256一致を確認。
- 設定102件は整理済み設定原本のハッシュとも照合。秘密情報の確認を実施した。
- README、SHA256SUMS、PROVENANCEを追加し、採取スクリプトの版が当時Git未記録である点も明記。
- snapshots配下で改行変換を無効化し、取得した出力のバイト列を維持する設定を追加。
- 元の作業データを保持。Git初期化、コミット、GitHub送信は行っていない。

## 出典

以下のローカル資料はGit管理対象の外側にある。重要な構成情報は本environment内にも転記した。

- [セットアップ経緯](../../セットアップ経緯.md)
- [復元メモ](../../作業履歴_復元.md)
- [8月の実機記録](../../前回の作業ログ/_note/2026-08-09_作業記録.md)
- [ROS導入記録](../../前回の作業ログ/2026-10-28_ROS2導入作業.md)
- [制御プログラム開発記録](../../前回の作業ログ/2026-10-28_モーター制御開発.md)
- [管理対象の分離](../../前回の作業ログ/2026-10-31_構成管理対象の分離.md)
- 過去会話：[ラズパイ構築再開](https://chatgpt.com/c/6ada3f35-9c8c-83ec-95b7-8eb3335ef17d)、[ラズパイ制御相談確認](https://chatgpt.com/c/6ada3ad7-aa24-83ee-9c5f-0ae9e43bf4a8)
