# 2026-11-01 実機採取スナップショット

実機から採取してPCへ保存した出力を、構成管理用の基準データとして取り込んだ。Gitの初期化・コミットは今回行っていない。

## 内容

|ファイル・フォルダー|内容|
|---|---|
|[snapshot.json](snapshot.json)|基本採取結果の全体。設定内容、コマンド結果、失敗情報を含む|
|files/|基本採取で保存した設定原本99件|
|[desktop-supplement.json](desktop-supplement.json)|追加採取したXセッション定義3件と、未存在のユーザー設定の記録|
|[session-supplement.json](session-supplement.json)|systemdリンク139件と、AccountsServiceのXSession照会結果|
|packages.txt等|コマンドごとの採取出力|
|[SHA256SUMS.txt](SHA256SUMS.txt)|コピー元と照合した元出力120ファイルのSHA-256|
|[PROVENANCE.json](PROVENANCE.json)|採取元・取り込み時の確認・使用スクリプトの版情報の制限|

追加採取を合わせた設定原本は102件。読みやすい形に整理した原本とメタデータは[config側](../../config/observed-2026-11-01/README.md)、一覧や要約は[manifests側](../../manifests/current-2026-11-01.md)も参照できる。

## 確認結果

- 元出力120ファイルをコピーし、すべてSHA-256が一致。
- JSONに含まれる設定102件が、整理済み設定原本のハッシュと一致。
- 設定内容の認証情報代入・秘密鍵マーカーを確認。SSH秘密鍵やネットワーク認証ファイルは採取対象外。
- 実機設定の変更、再採取、Git初期化・コミットは今回の取り込みでは行っていない。

## 制限

元出力内の未取得・タイムアウト情報は、採取当時の事実として保持する。補完した項目は追加採取JSONやmanifestsに記録している。採取時はGit未初期化で、使用したスクリプトのコミットIDはない。現行スクリプトがすべての採取・補完処理と完全に同一だったと扱わない。

元の作業データはプロジェクト直下のwork_data/environment/2026-11-01_020523_JSTにも保持した。初回試行の診断データはwork_data側に残している。
