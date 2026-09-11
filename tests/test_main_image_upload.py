"""主流程图片上传开关测试。"""

import json
from unittest.mock import MagicMock, patch

from fafu_auto_sign.main import run
from fafu_auto_sign.services.task_service import TaskDetails


def _write_config(tmp_path, image_upload_enabled: bool):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "user_token": "2_test_token",
                "image_path": "dorm.jpg",
                "image_upload_enabled": image_upload_enabled,
                "sign_delay_min": 0,
                "sign_delay_max": 0,
            }
        ),
        encoding="utf-8",
    )
    return config_path


def _run_with_mocked_services(tmp_path, image_upload_enabled: bool):
    config_path = _write_config(tmp_path, image_upload_enabled)

    mock_client = MagicMock()
    mock_shutdown = MagicMock()
    mock_shutdown.is_stopped.side_effect = [False, False, True]
    mock_shutdown.wait.return_value = False

    mock_task_service = MagicMock()
    mock_task_service.get_pending_tasks.return_value = ["123"]
    mock_task_service.get_task_details.return_value = TaskDetails(
        task_id=123,
        position_id=516208,
        base_lng=118.237686,
        base_lat=25.077727,
        position_name="测试位置",
    )

    mock_upload_service = MagicMock()
    mock_upload_service.upload_image.return_value = "https://example.com/image.jpg"
    mock_sign_service = MagicMock()

    with (
        patch("fafu_auto_sign.main.FAFUClient") as client_class,
        patch("fafu_auto_sign.main.GracefulShutdown", return_value=mock_shutdown),
        patch("fafu_auto_sign.main.TaskService", return_value=mock_task_service),
        patch("fafu_auto_sign.main.UploadService", return_value=mock_upload_service),
        patch("fafu_auto_sign.main.SignService", return_value=mock_sign_service),
        patch("fafu_auto_sign.main.setup_logging"),
    ):
        client_class.return_value.__enter__.return_value = mock_client
        client_class.return_value.__exit__.return_value = False
        run(str(config_path))

    return mock_upload_service, mock_sign_service


def test_image_upload_is_skipped_by_default(tmp_path):
    """默认关闭时不应调用上传服务，也不应提交图片 URL。"""
    upload_service, sign_service = _run_with_mocked_services(tmp_path, False)

    upload_service.upload_image.assert_not_called()
    assert sign_service.submit_sign.call_args.kwargs["image_url"] is None


def test_image_upload_can_be_enabled(tmp_path):
    """开启开关后应上传图片并把返回 URL 传给签到服务。"""
    upload_service, sign_service = _run_with_mocked_services(tmp_path, True)

    upload_service.upload_image.assert_called_once_with("dorm.jpg")
    assert sign_service.submit_sign.call_args.kwargs["image_url"] == (
        "https://example.com/image.jpg"
    )
