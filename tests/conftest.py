"""
Pytest fixtures for characterization tests.
"""

from unittest.mock import MagicMock, patch

import pytest

from fafu_auto_sign.client import FAFUClient


@pytest.fixture(autouse=True)
def _reset_request_throttle():
    """每个测试前后重置客户端的节流计时器。

    ``FAFUClient._last_request_at`` 是类属性（让同进程内的多个客户端共享同一
    节流窗口），若不重置会跨测试互相影响，让用例执行顺序决定结果。

    注意：这里**不**尝试去改 ``AppConfig`` 的字段默认值——Pydantic v2 的模型
    字段并非类属性，``setattr(AppConfig, ...)`` 之后读取仍会走
    ``__getattr__`` 拿到字段定义，等于没改。需要关闭节流的用例请直接设置
    客户端实例的 ``min_request_interval``（实例属性优先）。
    """
    FAFUClient._last_request_at = 0.0
    yield
    FAFUClient._last_request_at = 0.0


@pytest.fixture
def throttled_config():
    """开启请求节流的配置，供节流相关用例使用。

    实例属性优先于配置默认值，因此显式构造的间隔不受其他用例影响。
    """
    from fafu_auto_sign.config import AppConfig

    return AppConfig(user_token="2_TEST_TOKEN", min_request_interval=2.0)


@pytest.fixture
def sample_token():
    """测试用的固定 token"""
    return "2_test_token_for_testing_only"


@pytest.fixture
def mock_time():
    """
    返回固定的 Unix 时间戳
    """
    frozen_time = 1234567890.0  # 2009-02-13 23:31:30 UTC
    return frozen_time


@pytest.fixture
def sample_tasks():
    """
    示例任务列表数据，用于测试任务识别逻辑
    """
    return {
        "records": [
            {
                "id": 1001,
                "name": "晚归签到任务 - A10号楼",
                "beginTime": 1234567800000,  # 比当前时间早 100 秒
                "endTime": 1234567980000,  # 比当前时间晚 90 秒
            },
            {
                "id": 1002,
                "name": "晚归签到任务 - B5号楼",
                "beginTime": 1234567700000,  # 比当前时间早 190 秒
                "endTime": 1234567950000,  # 比当前时间晚 60 秒
            },
            {
                "id": 1003,
                "name": "晨跑签到任务",
                "beginTime": 1234567800000,
                "endTime": 1234567980000,
            },
            {
                "id": 1004,
                "name": "晚归签到任务 - 已过期",
                "beginTime": 1234567000000,  # 很久以前
                "endTime": 1234567500000,  # 已过期
            },
            {
                "id": 1005,
                "name": "晚归签到任务 - 未开始",
                "beginTime": 1234568000000,  # 将来
                "endTime": 1234568500000,
            },
        ]
    }


@pytest.fixture
def empty_tasks():
    """空任务列表"""
    return {"records": []}


@pytest.fixture
def mock_response_success():
    """Mock 成功的 HTTP 响应"""
    mock = MagicMock()
    mock.status_code = 200
    mock.text = '{"records": []}'
    mock.json.return_value = {"records": []}
    return mock


@pytest.fixture
def mock_response_with_tasks(sample_tasks):
    """Mock 包含任务列表的 HTTP 响应"""
    mock = MagicMock()
    mock.status_code = 200
    mock.text = '{"records": [...]}'
    mock.json.return_value = sample_tasks
    return mock
