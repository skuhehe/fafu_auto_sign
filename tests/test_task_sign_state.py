"""``TaskService`` 按 ``signState`` 跳过已签到任务的测试。

服务端在任务列表里通过 ``signInStudent.signState`` 表示本人是否已签到。
重复提交签到既无意义，也可能触发风控，因此这里要保证：

- 已签到任务被跳过；
- 字段缺失时按「未知」处理并**保守地继续尝试**（不因为字段缺失而漏签）。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path before importing package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.services.task_service import TaskService

#: 与 frozen_time fixture 对应的毫秒时间戳（2009-02-13 23:31:30 UTC）
FROZEN_TIME = 1234567890.0
ACTIVE_BEGIN_MS = 1234567800000
ACTIVE_END_MS = 1234567980000


@pytest.fixture
def task_service():
    """使用固定配置的 TaskService 实例。"""
    config = AppConfig(
        user_token="2_TEST_TOKEN",
        base_url="http://stuhtapi.fafu.edu.cn",
        task_keywords=["晚归"],
    )
    return TaskService(FAFUClient(config), config)


def _task(task_id: int, sign_state=None, name: str = "晚归签到任务") -> dict:
    """构造一条活跃任务记录；``sign_state`` 为 None 时不下发该字段。"""
    task = {
        "id": task_id,
        "name": name,
        "beginTime": ACTIVE_BEGIN_MS,
        "endTime": ACTIVE_END_MS,
    }
    if sign_state is not None:
        task["signInStudent"] = {"signState": sign_state}
    return task


def _response(records: list[dict]) -> MagicMock:
    """把任务记录包成 mock HTTP 响应。"""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"records": records}
    return mock


class TestExtractSignState:
    """``_extract_sign_state`` 的解析契约。"""

    def test_reads_integer_state(self):
        """正常情况返回整数。"""
        assert TaskService._extract_sign_state({"signInStudent": {"signState": 1}}) == 1

    def test_zero_state_means_not_signed(self):
        """0 表示未签到。"""
        assert TaskService._extract_sign_state({"signInStudent": {"signState": 0}}) == 0

    def test_numeric_string_is_coerced(self):
        """字符串数字应被转成整数（服务端可能返回字符串）。"""
        assert TaskService._extract_sign_state({"signInStudent": {"signState": "1"}}) == 1

    def test_missing_sign_in_student_returns_none(self):
        """缺 signInStudent 视为未知。"""
        assert TaskService._extract_sign_state({"id": 1}) is None

    def test_missing_sign_state_returns_none(self):
        """缺 signState 视为未知。"""
        assert TaskService._extract_sign_state({"signInStudent": {}}) is None

    def test_sign_in_student_not_dict_returns_none(self):
        """signInStudent 不是字典时视为未知。"""
        assert TaskService._extract_sign_state({"signInStudent": "oops"}) is None

    def test_non_numeric_sign_state_returns_none(self):
        """signState 不可转 int 时视为未知。"""
        assert TaskService._extract_sign_state({"signInStudent": {"signState": "abc"}}) is None

    def test_none_sign_state_returns_none(self):
        """signState 显式为 None 时视为未知。"""
        assert TaskService._extract_sign_state({"signInStudent": {"signState": None}}) is None


class TestGetPendingTasksSkipsSigned:
    """``get_pending_tasks`` 的跳过行为（集成）。"""

    def test_only_unsigned_task_is_returned(self, task_service):
        """已签到任务被跳过，只返回未签到的。"""
        response = _response(
            [
                _task(1001, sign_state=1, name="晚归签到任务 - 已签"),
                _task(1002, sign_state=0, name="晚归签到任务 - 未签"),
            ]
        )

        with patch.object(task_service.client, "post", return_value=response):
            with patch("time.time", return_value=FROZEN_TIME):
                assert task_service.get_pending_tasks() == ["1002"]

    def test_nonzero_non_one_state_is_also_skipped(self, task_service):
        """非 0 的任意状态都视为已签到。"""
        response = _response([_task(1003, sign_state=2)])

        with patch.object(task_service.client, "post", return_value=response):
            with patch("time.time", return_value=FROZEN_TIME):
                assert task_service.get_pending_tasks() == []

    def test_missing_sign_state_is_attempted(self, task_service):
        """signState 缺失时保守尝试，不漏签。"""
        response = _response([_task(1004)])

        with patch.object(task_service.client, "post", return_value=response):
            with patch("time.time", return_value=FROZEN_TIME):
                assert task_service.get_pending_tasks() == ["1004"]

    def test_unparseable_sign_state_is_attempted(self, task_service):
        """signState 无法解析时同样保守尝试。"""
        task = _task(1005)
        task["signInStudent"] = {"signState": "abc"}
        response = _response([task])

        with patch.object(task_service.client, "post", return_value=response):
            with patch("time.time", return_value=FROZEN_TIME):
                assert task_service.get_pending_tasks() == ["1005"]

    def test_mixed_list_keeps_only_unsigned_and_unknown(self, task_service):
        """混合场景：已签跳过、未签与未知保留，且顺序不变。"""
        response = _response(
            [
                _task(1001, sign_state=1),
                _task(1002, sign_state=0),
                _task(1003),
                _task(1004, sign_state="9"),
            ]
        )

        with patch.object(task_service.client, "post", return_value=response):
            with patch("time.time", return_value=FROZEN_TIME):
                assert task_service.get_pending_tasks() == ["1002", "1003"]

    def test_skip_is_logged(self, task_service, caplog):
        """跳过已签任务时必须留下日志，便于确认不是漏扫。"""
        import logging

        caplog.set_level(logging.INFO)
        response = _response([_task(1001, sign_state=1, name="晚归签到任务 - 已签")])

        with patch.object(task_service.client, "post", return_value=response):
            with patch("time.time", return_value=FROZEN_TIME):
                task_service.get_pending_tasks()

        assert "已在有效时间内且本人已签到" in caplog.text
