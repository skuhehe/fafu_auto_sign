"""心跳轮询间隔测试。"""

import json
from unittest.mock import MagicMock, patch

from fafu_auto_sign.main import run


def _build_config(tmp_path, heartbeat_interval: int):
    """写入测试配置并返回路径。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "user_token": "2_test_token",
                "heartbeat_interval": heartbeat_interval,
                "sign_delay_min": 0,
                "sign_delay_max": 0,
            }
        ),
        encoding="utf-8",
    )
    return str(config_path)


def _run_two_rounds(config_path: str, waits: list):
    """运行守护进程并把 shutdown.wait 的调用参数记录到 waits。"""
    mock_shutdown = MagicMock()
    mock_shutdown.is_stopped.return_value = False
    # 心跳等待返回 True，让主循环在处理一轮后退出
    mock_shutdown.wait.side_effect = lambda timeout: waits.append(timeout) or True

    mock_task_service = MagicMock()
    mock_task_service.get_pending_tasks.return_value = []

    with (
        patch("fafu_auto_sign.main.FAFUClient") as client_class,
        patch("fafu_auto_sign.main.GracefulShutdown", return_value=mock_shutdown),
        patch("fafu_auto_sign.main.TaskService", return_value=mock_task_service),
        patch("fafu_auto_sign.main.UploadService"),
        patch("fafu_auto_sign.main.SignService"),
        patch("fafu_auto_sign.main.setup_logging"),
    ):
        client_class.return_value.__enter__.return_value = MagicMock()
        client_class.return_value.__exit__.return_value = False
        run(config_path, once=False)


def test_heartbeat_interval_config_is_used(tmp_path):
    """常驻模式应使用配置的心跳间隔，而不是硬编码的 900 秒。"""
    waits: list = []
    _run_two_rounds(_build_config(tmp_path, 123), waits)

    assert waits == [123]


def test_heartbeat_interval_default_is_900(tmp_path):
    """未配置心跳间隔时回退到默认 900 秒。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"user_token": "2_test_token"}), encoding="utf-8")

    waits: list = []
    _run_two_rounds(str(config_path), waits)

    assert waits == [900]
