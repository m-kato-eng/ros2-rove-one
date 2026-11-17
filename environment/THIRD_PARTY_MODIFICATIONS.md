# 採取設定の上流との差分・変更注記

注記追加日：2026-11-17。これは、この日に実機設定を変更したという記録ではありません。原本採取は2026-11-01、今回の注記追加では保存済み設定・JSONのバイト列を変更していません。

| 採取元パス | 確認した上流との差分 | 比較元 |
| --- | --- | --- |
| `/etc/gdm3/custom.conf` | 自動ログイン項目が有効。上流のコメント付きサンプル2行を除去 | 採取版gdm3 `42.0-1ubuntu7.22.04.4` の配布設定 |
| `/etc/default/grub` | タイムアウト等の値・項目、インストール時に置換される既定値が異なる | Ubuntu grub2 `2.06-2ubuntu7.2` の `debian/default/grub` |
| `/etc/modules` と `/etc/modules-load.d/modules.conf` | kmodの生成テンプレートの説明1行がない。リンク先の内容を重複保存 | kmod `29-1ubuntu1.1` の `postinst` |
| `/etc/systemd/system/snap.mesa-2404.component-monitor.service` | Snap名・リビジョン・実行コマンド等が生成時に埋め込まれる | Snapd上流 `2.77.1` の `wrappers/internal/service_unit_gen.go` |
| `/etc/udev/rules.d/70-snap.*.rules` 4件 | 接続インターフェイス・アプリ名・デバイス用ルールが展開される | Snapd上流 `2.77.1` の `interfaces/udev` と `interfaces/builtin` |

GDM・GRUBのobservedコピーとsnapshotコピーには、対象ファイルとそのSHA-256を明記する `.license` 注記を隣接して配置しています。同じ注記はJSON内の同一内容と、履歴中の同素材にも対応します。元の設定を変更した正確な日付・作業者は確認できていません。採取日をその代用にはしていません。

Snapdは採取時の上流版と同じ2.77.1を確認しましたが、Ubuntuパッケージ改訂 `2.77.1+ubuntu22.04.1` のソースは現在の公式poolから取得できていません。上流のテンプレートと、現行Ubuntuソースの双方を参照しています。生成器がGPLという理由だけで出力全体のライセンスを自動決定していません。

別の改訂版のdebで同一内容を確認したのは、GNOME Shellの移行用desktopとSnap自動起動desktopの2件です。同じバイト列であることと、採取時のパッケージそのものを取得できたことは区別します。

Piの `/boot/firmware/config.txt` にも上流からの変更がありますが、説明文の許諾条件自体が未解決のため、GPL等を割り当てていません。

ライセンス・著作権表示の対応は [一覧](THIRD_PARTY_FILES.csv)、配布元の版と公式URLは [取得元情報](../LICENSES/third-party/SOURCES.json) を参照してください。
