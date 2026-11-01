# 今回構築したROS 2環境

2026-10-28に構築・検証した構成。図の実線は実装・模擬動作検証済み、点線は実配線確認後に進める部分です。

```mermaid
flowchart TB
    subgraph PC[Windows PC：ROSのインストール不要]
        GUI["操作画面：controller.py<br/>前進・後退・旋回・有効化・停止"]
        SSH["通信処理：transport.py<br/>OpenSSH・JSON通信"]
        GUI --> SSH
    end

    subgraph PI[Raspberry Pi 4：Ubuntu 22.04 / ROS 2 Humble]
        BRIDGE["pc_bridge.py<br/>SSH指令をROSへ変換<br/>指令途絶350 msで無効化"]
        NODE["motor_controller<br/>pi4_motor_controlパッケージ<br/>速度制限・左右輪への変換<br/>指令途絶500 msで無効化"]
        SIM["DryRunBackend<br/>左前・左後・右前・右後<br/>4モーターの仮想PWM出力"]
        BRIDGE -->|"cmd_vel：速度・旋回指令<br/>enable / emergency_stop：サービス"| NODE
        NODE --> SIM
        NODE -->|"status：状態・4輪の出力値"| BRIDGE
    end

    SSH -->|"有線LAN / SSH<br/>指令を100 msごとに送信"| BRIDGE
    BRIDGE -->|"SSHで状態を返送"| SSH
    SSH -->|"状態表示・ログ保存"| GUI

    subgraph FUTURE[今後：実機の配線・動作確認]
        GPIO["GpioBackend / RPi.GPIO<br/>GPIO・PWM"]
        DRIVER["L298N ×2"]
        MOTOR["実モーター ×4"]
        GPIO -.-> DRIVER -.-> MOTOR
    end
    NODE -.->|"実機用の別起動構成<br/>配線・権限・設定の確認後"| GPIO

    classDef current fill:#e8f4ff,stroke:#2878b5,color:#123;
    classDef simulated fill:#e8f6eb,stroke:#38834b,color:#123;
    classDef future fill:#f5f5f5,stroke:#888,color:#555,stroke-dasharray:5 5;
    class GUI,SSH,BRIDGE,NODE current;
    class SIM simulated;
    class GPIO,DRIVER,MOTOR future;
```

- ROS 2はPi上で動作します。WindowsはPython/Tkの操作画面とSSHクライアントを使用します。
- PC操作は専用のROS_DOMAIN_ID=88と接続ごとの固有namespaceで動きます。
- PC用ブリッジはdry-run固定です。現在の画面から実モーター出力へ切り替える機能はありません。
- 起動時は無効。緊急停止解除や通信復旧だけでは再走行せず、再有効化が必要です。
- 350 ms / 500 msはソフトウェアの監視設定値であり、実際の停止時間の実時間保証ではありません。
- 状態として返す値は仮想PWM値で、エンコーダー等で計測した実速度ではありません。
- 単体16件、ROS統合、PC往復、GUI操作経路を検証済み。実GPIO出力・実車走行は未検証です。

関連資料：

- [PC起動・操作方法](../pc_controller/README.md)
- [ROSノード・実配線の準備](../ros2_ws/src/pi4_motor_control/README.md)
- [作業・デバッグ記録](../../前回の作業ログ/2026-10-28_モーター制御開発.md)
