"""主循环失败退避（持久化状态）集成测试。

``main.run()`` 的退避语义有两条容易搞错、后果又很直接的规则：

1. **请求级失败**要推进退避并落盘——否则常驻进程会在服务端限流期间继续按
   固定周期重试，把限流窗口越拖越长，甚至正好覆盖签到窗口。
2. **「没有任务」属于正常情况**，绝不能推进退避——否则一个安静的中午就会
   把进程锁进 2 小时退避，直接漏掉晚间的签到窗口。

参考 ``tests/test_once_mode.py`` 的 mock 组合方式：整套链路（客户端、退出处理器、
任务/上传/签到服务、日志）全部替换掉，**不访问真实网络**。
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import RequestException

from fafu_auto_sign.main import run
from fafu_auto_sign.services.task_service import TaskDetails

#: 足以让 BackoffState 判定为「仍处于退避期」的未来时间戳
FUTURE_TS = 4102444800.0  # 2100-01-01 00:00:00 UTC


def _build_config(tmp_path, **overrides):
    """写一份最小可用配置并返回路径。"""
    payload = {
        "user_token": "2_test_token",
        "image_upload_enabled": False,
        "sign_delay_min": 0,
        "sign_delay_max": 0,
    }
    payload.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def harness(tmp_path):
    """搭建 run() 所需的全部 mock 依赖，并给出临时状态文件路径。

    配置里显式写入 ``state_path``：这样「不传 state_path」的用例也不会退回到
    相对路径，从而避免读写项目根目录的真实 ``state.json``。
    """
    configured_state_path = tmp_path / "configured-state.json"
    config_path = _build_config(tmp_path, state_path=str(configured_state_path))
    state_path = tmp_path / "state.json"

    mock_client = MagicMock()
    mock_shutdown = MagicMock()
    mock_shutdown.is_stopped.return_value = False

    mock_task_service = MagicMock()
    mock_task_service.get_pending_tasks.return_value = []
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
    ):
        client_class.return_value.__enter__.return_value = mock_client
        client_class.return_value.__exit__.return_value = False

        yield SimpleNamespace(
            config_path=config_path,
            state_path=state_path,
            configured_state_path=configured_state_path,
            task_service=mock_task_service,
            sign_service=mock_sign_service,
            shutdown=mock_shutdown,
        )


def _read_state(path):
    """读取状态文件；不存在时返回空字典。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class TestBackoffBlocksRequests:
    """退避期内不应发起任何业务请求。"""

    def test_blocked_state_skips_all_business_requests(self, harness, caplog):
        """预写未来退避时间后，run() 不应调用任何业务接口。"""
        import logging

        caplog.set_level(logging.WARNING)
        harness.state_path.write_text(
            json.dumps({"delay_failures": 2, "delay_next_attempt_at": FUTURE_TS}),
            encoding="utf-8",
        )

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        harness.task_service.get_pending_tasks.assert_not_called()
        harness.task_service.get_task_details.assert_not_called()
        harness.sign_service.submit_sign.assert_not_called()
        assert "处于失败退避期" in caplog.text
        # --once 模式不应进入心跳等待
        harness.shutdown.wait.assert_not_called()

    def test_ignore_backoff_bypasses_blocked_state(self, harness):
        """--ignore-backoff 时即使处于退避期也要照常尝试。"""
        harness.state_path.write_text(
            json.dumps({"delay_failures": 2, "delay_next_attempt_at": FUTURE_TS}),
            encoding="utf-8",
        )

        run(
            str(harness.config_path),
            once=True,
            state_path=str(harness.state_path),
            ignore_backoff=True,
        )

        harness.task_service.get_pending_tasks.assert_called_once_with()

    def test_expired_backoff_allows_requests(self, harness):
        """退避时间已过（过去时间戳）时应正常尝试。"""
        harness.state_path.write_text(
            json.dumps({"delay_failures": 1, "delay_next_attempt_at": 1.0}),
            encoding="utf-8",
        )

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        harness.task_service.get_pending_tasks.assert_called_once_with()


class TestFailureAdvancesBackoff:
    """请求级失败必须落盘推进退避。"""

    def test_request_exception_records_failure(self, harness):
        """get_pending_tasks 抛 RequestException 时失败计数应为 1。"""
        harness.task_service.get_pending_tasks.side_effect = RequestException("boom")

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        state = _read_state(harness.state_path)
        assert state["delay_failures"] == 1
        assert state["delay_next_attempt_at"] > 0

    def test_consecutive_failures_advance_the_schedule(self, harness):
        """连续两轮失败应推进到第二档阶梯。"""
        harness.task_service.get_pending_tasks.side_effect = RequestException("boom")

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))
        run(
            str(harness.config_path),
            once=True,
            state_path=str(harness.state_path),
            ignore_backoff=True,
        )

        assert _read_state(harness.state_path)["delay_failures"] == 2

    def test_task_processing_exception_records_failure(self, harness):
        """处理单个任务时抛异常（非请求级）同样应推进退避。"""
        harness.task_service.get_pending_tasks.return_value = ["123"]
        harness.task_service.get_task_details.side_effect = RuntimeError("unexpected")

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        assert _read_state(harness.state_path)["delay_failures"] == 1


class TestNoFailurePaths:
    """不应推进退避的正常路径。"""

    def test_no_pending_tasks_does_not_trigger_backoff(self, harness):
        """「没有任务」不是失败：不得写入失败计数。

        这是关键语义——否则安静时段会把进程锁进长退避，直接漏签。
        """
        harness.task_service.get_pending_tasks.return_value = []

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        state = _read_state(harness.state_path)
        assert state.get("delay_failures", 0) == 0
        assert state.get("delay_next_attempt_at", 0) in (0, None)

    def test_successful_sign_records_success(self, harness):
        """签到成功后失败计数清零、退避时间归零，并记录成功时间。"""
        harness.state_path.write_text(
            json.dumps({"delay_failures": 3, "delay_next_attempt_at": FUTURE_TS}),
            encoding="utf-8",
        )
        harness.task_service.get_pending_tasks.return_value = ["123"]
        harness.sign_service.submit_sign.return_value = True

        run(
            str(harness.config_path),
            once=True,
            state_path=str(harness.state_path),
            ignore_backoff=True,
        )

        state = _read_state(harness.state_path)
        assert state["delay_failures"] == 0
        assert state["delay_next_attempt_at"] == 0
        assert state["delay_last_success_at"] > 0

    def test_task_without_position_is_not_a_failure(self, harness):
        """任务无地理位置限制时跳过签到，但不计入失败。"""
        harness.task_service.get_pending_tasks.return_value = ["123"]
        harness.task_service.get_task_details.return_value = None

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        harness.sign_service.submit_sign.assert_not_called()
        assert _read_state(harness.state_path).get("delay_failures", 0) == 0

    def test_failed_sign_submission_is_not_a_request_failure(self, harness):
        """提交签到返回 False（业务失败）不推进请求级退避。

        业务失败会由服务端在正常响应中告知，属于「本轮没签上」而非
        「请求链路故障」，不宜叠加长退避。
        """
        harness.task_service.get_pending_tasks.return_value = ["123"]
        harness.sign_service.submit_sign.return_value = False

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        harness.sign_service.submit_sign.assert_called_once()
        assert _read_state(harness.state_path).get("delay_failures", 0) == 0


class TestConfiguredStatePath:
    """状态文件路径可配置（T-A5）。"""

    def test_run_uses_config_state_path_when_not_passed(self, harness):
        """未显式传 state_path 时应落到 config.state_path 指定的文件。"""
        harness.task_service.get_pending_tasks.side_effect = RequestException("boom")

        run(str(harness.config_path), once=True)

        assert _read_state(harness.configured_state_path)["delay_failures"] == 1
        # 不应顺带写出另一个状态文件
        assert not harness.state_path.exists()

    def test_explicit_state_path_wins_over_config(self, harness):
        """显式传参优先于配置项（CLI --state 的语义）。"""
        harness.task_service.get_pending_tasks.side_effect = RequestException("boom")

        run(str(harness.config_path), once=True, state_path=str(harness.state_path))

        assert _read_state(harness.state_path)["delay_failures"] == 1
        assert not harness.configured_state_path.exists()

    def test_backoff_is_read_from_configured_path(self, harness):
        """退避状态也应从 config.state_path 读取，而非只看默认路径。"""
        harness.configured_state_path.write_text(
            json.dumps({"delay_failures": 1, "delay_next_attempt_at": FUTURE_TS}),
            encoding="utf-8",
        )

        run(str(harness.config_path), once=True)

        harness.task_service.get_pending_tasks.assert_not_called()
