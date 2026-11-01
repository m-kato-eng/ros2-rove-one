# Git作業コピーへの移行・復旧

2026-11-01の移行構成。実モーターを動かさないdry-run設定を維持する。

## 配置

|用途|配置|
|---|---|
|Windowsの新しいGit作業コピー|`C:\_Project\_RaspPi4_ROS\ros2-rove-one`|
|PiのGit作業コピー|`/home/mk/ros2-rove-one`|
|Piの新しいROSワークスペース|`/home/mk/ros2-rove-one/ros2_ws`|
|Piの旧ワークスペース|`/home/mk/ros2_ws`（移行検証後、ユーザー指示で削除済み）|
|Pi上の別保存|`/home/mk/backups/ros2_ws_before_git_20261101_141035`（同じく削除済み）|
|旧PC作業コピー|`C:\_Project\_RaspPi4_ROS\managed`（内容削除済み、空ディレクトリの使用中ロックあり）|

移行時には旧ワークスペース全体を`cp -a`でコピーし、通常ファイルのSHA-256とリンク先の全138件の一致を確認した。その後、新配置での検証完了とユーザーの削除指示を受けて旧環境・別保存を削除した。現在はこれらのバックアップからの復元はできない。新しいビルドでは旧install/buildを流用していない。

## Piの必要ディレクトリだけを展開

```bash
git -C ~/ros2-rove-one sparse-checkout list
# ros2_ws
```

coneモードでros2_wsを選択済み。ルートのREADME・.gitignoreとGitの管理データも残る。pc_controller / environment / docsはPiの作業ツリーには展開されない。これらはGitHubとPC側に保持される。

初回のsparse-checkout init時に一時的にROSワークスペースが除外され、Git管理外のbuild/install等も消えたため、選択設定後に新規ビルド・単体16件・ROS統合を再実行して合格を確認した。今後は必要なくinitをやり直さない。

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

## ソースの版を戻す場合

1. PCの操作画面を切断して閉じる。
2. 現行Git作業コピーに未保存変更がないか確認する。
3. Gitの履歴から対象のコミットを選び、その版のソースから再ビルドする。
4. 同じ版に対応するPCソフトから模擬動作を確認する。旧ワークスペースやSDバックアップは削除済みなので、そのパスへ戻す方法は使用できない。

PCのmanagedはGit履歴への保存・未コミット変更なし・無視ファイルなしを確認して内容を削除した。空フォルダーだけは他プロセスの使用中ロックにより削除できず、ロックを持つ端末やアプリを閉じた後で削除する。SSH鍵と作業ログ、GitHub上のコードは保持している。PCのSDカード全体バックアップzip（約5.8 GB）もユーザーの指示で削除済み。

## 移行後の検証結果

2026-11-01、新配置でのビルド、単体16件、ROS統合、PC実接続往復、GUI操作経路が合格。PCソフトは新しいPiワークスペースを参照する。実GPIO出力は行っていない。

初回ROS統合試験ではパラメーター設定用のROS CLIでNode発見に失敗した。統合試験をrclpyのSetParametersサービスへ直接接続する方式へ修正し、再ビルド・全検証が成功した。制御ロジックは変更していない。

Windows側の詳細な失敗・再試行と結果はリポジトリ外の`work_data/migration/2026-11-01`、PCの最終検証結果は`work_data/pc_controller/logs/validation.txt`に保存する。
