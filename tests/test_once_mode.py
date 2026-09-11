"""单次运行模式测试。"""

import json
from unittest.mock import MagicMock, patch

from fafu_auto_sign.main import run
from fafu_auto_sign.services.task_service import TaskDetails


def test_once_mode_exits_after_one_scan_without_waiting(tmp_path):
    """--once 模式没有任务时应在第一次扫描后退出。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "user_token": "2_test_token",
                "sign_delay_min": 900,
                "sign_delay_max": 2700,
            }
        ),
        encoding="utf-8",
    )

    mock_client = MagicMock()
    mock_shutdown = MagicMock()
    mock_shutdown.is_stopped.return_value = False
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
        client_class.return_value.__enter__.return_value = mock_client
        client_class.return_value.__exit__.return_value = False

        run(str(config_path), once=True)

    mock_task_service.get_pending_tasks.assert_called_once_with()
    mock_shutdown.wait.assert_not_called()


def test_once_mode_skips_delay_and_processes_only_first_task(tmp_path):
    """--once 模式应跳过签到延迟，并且最多处理一个任务。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "user_token": "2_test_token",
                "image_upload_enabled": False,
                "sign_delay_min": 900,
                "sign_delay_max": 2700,
            }
        ),
        encoding="utf-8",
    )

    mock_client = MagicMock()
    mock_shutdown = MagicMock()
    mock_shutdown.is_stopped.return_value = False
    mock_task_service = MagicMock()
    mock_task_service.get_pending_tasks.return_value = ["123", "456"]
    mock_task_service.get_task_details.return_value = TaskDetails(
        task_id=123,
        position_id=516208,
        base_lng=118.237686,
        base_lat=25.077727,
        position_name="测试位置",
    )
    mock_sign_service = MagicMock()
    mock_sign_service.submit_sign.return_value = True

    with (
        patch("fafu_auto_sign.main.FAFUClient") as client_class,
        patch("fafu_auto_sign.main.GracefulShutdown", return_value=mock_shutdown),
        patch("fafu_auto_sign.main.TaskService", return_value=mock_task_service),
        patch("fafu_auto_sign.main.UploadService"),
        patch("fafu_auto_sign.main.SignService", return_value=mock_sign_service),
        patch("fafu_auto_sign.main.setup_logging"),
        patch("fafu_auto_sign.main.wait_random_sign_delay") as wait_delay,
    ):
        client_class.return_value.__enter__.return_value = mock_client
        client_class.return_value.__exit__.return_value = False

        run(str(config_path), once=True)

    wait_delay.assert_not_called()
    mock_task_service.get_task_details.assert_called_once_with(123)
    mock_sign_service.submit_sign.assert_called_once()
