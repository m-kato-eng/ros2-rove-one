# Git作業コピーへの移行・復旧

2026-11-01の移行構成。実モーターを動かさないdry-run設定を維持する。

## 配置

|用途|配置|
|---|---|
|Windowsの新しいGit作業コピー|`C:\_Project\_RaspPi4_ROS\ros2-rove-one`|
|PiのGit作業コピー|`/home/mk/ros2-rove-one`|
|Piの新しいROSワークスペース|`/home/mk/ros2-rove-one/ros2_ws`|
|Piの旧ワークスペース|`/home/mk/ros2_ws`（変更せず保持）|
|Pi上の別保存|`/home/mk/backups/ros2_ws_before_git_20261101_141035`|
|旧PC作業コピー|`C:\_Project\_RaspPi4_ROS\managed`（削除せず保持）|

バックアップは旧ワークスペース全体を`cp -a`でコピーし、通常ファイルのSHA-256とシンボリックリンク先の全138件が一致することを確認した。新しいビルドでは旧install/buildを流用しない。

## PiのGit認証

この非公開リポジトリ専用の読み取り専用Deploy keyを使用する。秘密鍵はPiのSSH領域に保存し、Git管理しない。WindowsのGitHub資格情報や秘密鍵をPiへコピーしていない。

```bash
git -C ~/ros2-rove-one remote -v
git -C ~/ros2-rove-one pull --ff-only
```

SSHのHost別名`github-rove-one`と専用known_hostsを使う。GitHubホスト公開鍵はHTTPSの公式APIから取得し、StrictHostKeyCheckingを有効にした。

## 更新と再構築

テスト用PCセッションを切断してから実施する。

```bash
git -C ~/ros2-rove-one status --short
git -C ~/ros2-rove-one pull --ff-only
source /opt/ros/humble/setup.bash
cd ~/ros2-rove-one/ros2_ws
colcon build --packages-select pi4_motor_control
source install/setup.bash
colcon test --packages-select pi4_motor_control --event-handlers console_direct+
colcon test-result --verbose
ROS_DOMAIN_ID=87 python3 src/pi4_motor_control/scripts/smoke_test.py
```

build/install/logはGit管理対象外。PCからは`pc_controller/connection.json`のremote_workspaceでこのワークスペースを参照する。

## PCの起動

```powershell
cd C:\_Project\_RaspPi4_ROS\ros2-rove-one\pc_controller
.\start.ps1
# 再検証
.\validate.ps1
```

鍵と実行ログは新旧のPC作業コピーの外側に置くため、Gitで取得されない。別PCで使う場合はconnection.jsonの鍵・known_hosts・ログ・接続先をそのPCに合わせる。

## 旧版へ戻す

1. PCの操作画面を切断して閉じる。
2. PCのconnection.jsonでremote_workspaceを`/home/mk/ros2_ws`へ戻す。
3. 旧ワークスペースを使って模擬動作を確認する。旧ワークスペースを直接変更していないため、通常はバックアップからの上書き復元は不要。
4. 旧ワークスペースも壊れた場合は、別保存先を別名の復旧ディレクトリへコピーし、そこにあるソースから再ビルドする。installには絶対パスが含まれ得るので、コピー先のinstallをそのまま流用しない。

managedは旧PC作業コピーとして保持している。新構成での合格結果、未コミット変更、外部ファイルの参照を確認後に削除できるが、この移行作業では削除しない。

## 移行後の検証結果

2026-11-01、新配置でのビルド、単体16件、ROS統合、PC実接続往復、GUI操作経路が合格。PCソフトは新しいPiワークスペースを参照する。実GPIO出力は行っていない。

初回ROS統合試験ではパラメーター設定用のROS CLIでNode発見に失敗した。統合試験をrclpyのSetParametersサービスへ直接接続する方式へ修正し、再ビルド・全検証が成功した。制御ロジックは変更していない。

Windows側の詳細な失敗・再試行と結果はリポジトリ外の`work_data/migration/2026-11-01`、PCの最終検証結果は`work_data/pc_controller/logs/validation.txt`に保存する。
