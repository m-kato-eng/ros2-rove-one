# 第三者ファイルのライセンスと確認状況

## 適用範囲

自作ROSパッケージのApache-2.0宣言は、採取した第三者ファイルのライセンスを変更しません。設定ファイルを独立した資料として収録しています。元の著作権・ライセンス表示を保持し、今回の整備で採取内容を編集していません。

下表のパスは採取元のLinux上のパスです。各ファイルの保存先・SHA-256・確認状態は [全102ファイルの一覧](environment/THIRD_PARTY_FILES.csv) に記録しています。条件は `environment/config/observed-2026-11-01/files/`、`environment/snapshots/2026-11-01/files/` 内の同内容のコピー、および同スナップショットのJSON内の `content_b64` にも適用します。一部の補足採取ファイルはJSONとobservedコピーにのみ存在します。

## ファイル内の表示で確認したライセンス

| 採取元パス | 出典・採取時のパッケージ版 | ファイル内の指定・今回の扱い |
| --- | --- | --- |
| `/etc/systemd/system/dbus-org.freedesktop.Avahi.service` | Avahi / `avahi-daemon 0.8-5ubuntu5.5` | LGPL v2以降という表示に基づきLGPL-2.1を選択。以降の版を選べる元の表示も保持。 |
| `/etc/systemd/system/dbus-org.freedesktop.oom1.service` | systemd / `249.11-0ubuntu3.23` | LGPL-2.1-or-later |
| `/etc/systemd/system/dbus-org.freedesktop.resolve1.service` | systemd / `249.11-0ubuntu3.23` | LGPL-2.1-or-later |
| `/etc/systemd/system/dbus-org.freedesktop.timesync1.service` | systemd / `249.11-0ubuntu3.23` | LGPL-2.1-or-later |
| `/etc/xdg/autostart/org.gnome.DejaDup.Monitor.desktop` | Deja Dup / `42.9-1ubuntu3` | CC-BY-SA-4.0。原作者表示：Michael Terry。 |

LGPL対象には [LGPL-2.1本文](LICENSES/LGPL-2.1.txt) と、その参照先である [GPL v2本文](LICENSES/GPL-2.0.txt) を同梱しています。元の免責表示も保持しています。

Deja Dupの対象ファイルは [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) に基づいて提供します。[ライセンス全文](LICENSES/CC-BY-SA-4.0.txt)と免責条項を参照してください。既存の作者表示を保持し、今回の整備による内容変更はありません。

上流の参照先：

- [Avahi 0.8のサービス定義](https://github.com/avahi/avahi/blob/v0.8/avahi-daemon/avahi-daemon.service.in)
- [systemd v249のサービス定義](https://github.com/systemd/systemd/tree/v249/units)
- [Deja Dup 42.9](https://gitlab.gnome.org/World/deja-dup/-/tree/42.9)

これらは配布元の参照先であり、Ubuntu側の加工・インストール時の置換を含む採取ファイルが、上流テンプレートと同一であるという主張ではありません。採取後の原本一致については既存の `environment/snapshots/2026-11-01/PROVENANCE.json` とハッシュ記録を参照してください。

## 未確認事項

残る97件は、ファイル内に上記のような明示的なライセンス表示を確認できていません。ライセンスなし・著作権なし・Apache-2.0と推定せず、一覧の `package_provenance_pending` として扱います。これにはOSの設定、udevルール、サービス・自動起動・Xセッション定義、端末固有の設定が含まれます。

収録版に対応するUbuntuパッケージのファイル所有情報と `/usr/share/doc/<package>/copyright`、必要に応じたソースパッケージとの照合は未完了です。完全な権利確認や、リポジトリ全体の配布条件への適合を保証する一覧ではありません。

パッケージ一覧・依存宣言・importだけを根拠に、そこに挙がるソフトウェア全部をこのリポジトリで再配布しているとは扱いません。将来バイナリや依存ソフトそのものを同梱する場合は、その配布物について別途確認してください。

## 更新時の手順

1. 新しい採取内容の出典、パッケージ版、保存先、SHA-256を記録する。
2. ファイル内表示と配布元の条件を確認し、一覧と必要なライセンス本文を更新する。
3. 複製とJSON内のBase64コピーも対象に含め、作者・免責・ライセンス表示を保持する。
4. 第三者ファイルを変更した場合は、変更内容・日付を記録し、変更版の配布条件も確認する。

履歴中のコピーにも元の条件が適用されます。この整備は、過去の配布状況を調査したり、過去の不備の解消を断定したりするものではありません。
