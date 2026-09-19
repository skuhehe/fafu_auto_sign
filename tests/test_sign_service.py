"""签到服务测试。

本模块测试SignService类，包括：
- 成功和失败的签到提交
- GPS抖动计算和范围验证
- 正确的参数传递（URL查询参数）
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add src to path before importing package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging

import pytest

from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.services.sign_service import SignService


@pytest.fixture
def mock_config():
    """为测试创建mock配置。"""
    config = MagicMock(spec=AppConfig)
    config.jitter = 0.00005
    # 成功判定字段从配置读取，mock 配置必须显式给出；
    # 否则 MagicMock 会返回一个非字符串属性，判定会退化为「永假」。
    config.sign_success_field = "timestamp"
    return config


@pytest.fixture
def mock_client():
    """为测试创建mock HTTP客户端。"""
    client = MagicMock(spec=FAFUClient)
    return client


@pytest.fixture
def sign_service(mock_client, mock_config):
    """使用mock依赖创建SignService实例。"""
    return SignService(mock_client, mock_config)


class TestSubmitSign:
    """submit_sign方法测试。"""

    def test_submit_sign_success_returns_true(self, sign_service, mock_client):
        """测试成功签到返回True。"""
        # 准备
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122, "code": 200, "message": "success"}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        # 执行
        result = sign_service.submit_sign(
            123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg"
        )

        # 验证
        assert result is True

    def test_submit_sign_failure_returns_false(self, sign_service, mock_client):
        """测试失败签到返回False。"""
        # 准备
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"code": 400, "message": "bad request"}'
        mock_client.post.return_value = mock_response

        # 执行
        result = sign_service.submit_sign(
            123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg"
        )

        # 验证
        assert result is False

    def test_submit_sign_uses_url_query_params(self, sign_service, mock_client):
        """测试参数作为URL查询参数传递，而非JSON body。"""
        # 准备
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        # 执行
        sign_service.submit_sign(123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg")

        # 验证
        call_args = mock_client.post.call_args

        # 检查URL
        assert call_args[0][0] == "/health-api/sign_in/123/student/sign"

        # 检查使用了params kwargs（URL查询参数）
        assert "params" in call_args.kwargs
        params = call_args.kwargs["params"]

        # 验证必需参数存在
        assert "lng" in params
        assert "lat" in params
        assert params["signImg"] == "http://example.com/image.jpg"
        assert params["signInPositionId"] == 516208

    def test_submit_sign_without_image_omits_sign_img(self, sign_service, mock_client):
        """关闭图片上传时，签到请求不应携带 signImg 参数。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        result = sign_service.submit_sign(123, 516208, 118.237686, 25.077727)

        assert result is True
        params = mock_client.post.call_args.kwargs["params"]
        assert "signImg" not in params

    def test_submit_sign_formats_coordinates_to_6_decimal_places(self, sign_service, mock_client):
        """测试坐标格式化为6位小数。"""
        # 准备
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        # 执行
        sign_service.submit_sign(123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg")

        # 验证
        call_args = mock_client.post.call_args
        params = call_args.kwargs["params"]

        # 检查lng和lat格式化为6位小数
        lng_value = params["lng"]
        lat_value = params["lat"]

        # 它们应该是带6位小数的字符串
        assert isinstance(lng_value, str)
        assert isinstance(lat_value, str)

        # 验证小数位数（用小数点分割并检查小数部分）
        lng_decimals = lng_value.split(".")[1] if "." in lng_value else ""
        lat_decimals = lat_value.split(".")[1] if "." in lat_value else ""

        assert len(lng_decimals) == 6
        assert len(lat_decimals) == 6


class TestGPSJitter:
    """GPS坐标抖动功能测试。"""

    def test_gps_jitter_within_range(self, sign_service, mock_client):
        """测试GPS抖动在±0.00005度范围内。"""
        # 准备
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        base_lng = 118.237686
        base_lat = 25.077727
        jitter = 0.00005

        # 执行 - Run multiple times to test randomness
        for _ in range(100):
            mock_client.reset_mock()
            sign_service.submit_sign(
                123, 516208, base_lng, base_lat, "http://example.com/image.jpg"
            )

            call_args = mock_client.post.call_args
            params = call_args.kwargs["params"]

            actual_lng = float(params["lng"])
            actual_lat = float(params["lat"])

            # 验证 - Check jitter is within expected range
            lng_diff = abs(actual_lng - base_lng)
            lat_diff = abs(actual_lat - base_lat)

            assert lng_diff <= jitter * 1.01, f"Longitude jitter {lng_diff} exceeds max {jitter}"
            assert lat_diff <= jitter * 1.01, f"Latitude jitter {lat_diff} exceeds max {jitter}"

    def test_gps_jitter_is_randomized(self, sign_service, mock_client):
        """测试GPS坐标是随机的（不总是相同）。"""
        # 准备
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        coordinates = []

        # 执行 - Collect multiple coordinate pairs
        for _ in range(10):
            mock_client.reset_mock()
            sign_service.submit_sign(
                123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg"
            )

            call_args = mock_client.post.call_args
            params = call_args.kwargs["params"]

            coordinates.append((float(params["lng"]), float(params["lat"])))

        # 验证 - Check that not all coordinates are identical
        unique_coordinates = set(coordinates)
        assert len(unique_coordinates) > 1, "GPS coordinates should be randomized"

    def test_calculate_jittered_coordinates_returns_tuple(self, sign_service):
        """测试辅助方法返回正确的元组格式。"""
        base_lng = 118.237686
        base_lat = 25.077727
        jitter = 0.00005

        # 执行
        lng, lat = sign_service._calculate_jittered_coordinates(base_lng, base_lat)

        # 验证
        assert isinstance(lng, float)
        assert isinstance(lat, float)

        # 检查抖动范围
        assert abs(lng - base_lng) <= jitter
        assert abs(lat - base_lat) <= jitter


class TestSuccessCriterion:
    """签到成功判定：必须看响应体，不能只看 HTTP 状态码。"""

    def test_http_200_with_error_body_is_not_success(self, sign_service, mock_client, caplog):
        """HTTP 200 但业务失败（响应体无 timestamp）必须判为失败。

        这是「只看状态码」的经典误报场景：服务端可能返回 200 而业务上被
        风控拦截或任务已失效，此时若报成功会让使用者以为签到完成。
        """
        caplog.set_level(logging.ERROR)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"errorCode": "41567", "errorMessage": "Get authorization username fail"}'
        mock_response.json.return_value = {
            "errorCode": "41567",
            "errorMessage": "Get authorization username fail",
        }
        mock_client.post.return_value = mock_response

        result = sign_service.submit_sign(123, 516208, 118.237686, 25.077727)

        assert result is False
        assert "未被服务端确认" in caplog.text

    def test_http_200_with_html_body_is_not_success(self, sign_service, mock_client):
        """被 WAF 拦截返回的 HTML 页面不能判为成功。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Request blocked</body></html>"
        mock_response.json.side_effect = ValueError("not json")
        mock_client.post.return_value = mock_response

        assert sign_service.submit_sign(123, 516208, 118.237686, 25.077727) is False

    def test_probe_accepts_2xx_with_timestamp(self, sign_service):
        """2xx 且响应体含 timestamp 视为成功。"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"timestamp": 1789118122}

        assert sign_service.probe_sign_response(mock_response) is True

    def test_probe_rejects_non_2xx(self, sign_service):
        """非 2xx 一律视为失败。"""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.json.return_value = {"timestamp": 1789118122}

        assert sign_service.probe_sign_response(mock_response) is False

    def test_probe_rejects_non_numeric_status(self, sign_service):
        """状态码不是数字时按失败处理，不抛异常。"""
        mock_response = MagicMock()
        mock_response.status_code = "not-a-status"

        assert sign_service.probe_sign_response(mock_response) is False


class TestConfigurableSuccessField:
    """成功判定字段可配置。

    该判据来自跨项目逆向记录、未用真实响应验证，因此必须留出配置逃生口：
    若服务端返回结构不同，改配置即可，不用改代码。
    """

    @staticmethod
    def _response(payload):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = str(payload)
        mock_response.json.return_value = payload
        return mock_response

    def test_custom_field_is_used(self, mock_client, mock_config):
        """配置了自定义字段名后，响应体含该字段即算成功。"""
        mock_config.sign_success_field = "ok"
        mock_client.post.return_value = self._response({"ok": True})
        service = SignService(mock_client, mock_config)

        assert service.success_field == "ok"
        assert service.submit_sign(123, 516208, 118.237686, 25.077727) is True

    def test_default_field_is_rejected_when_custom_configured(self, mock_client, mock_config):
        """配置了自定义字段后，旧的 timestamp 不再被认作成功。"""
        mock_config.sign_success_field = "ok"
        mock_client.post.return_value = self._response({"timestamp": 1789118122})
        service = SignService(mock_client, mock_config)

        assert service.submit_sign(123, 516208, 118.237686, 25.077727) is False

    def test_falls_back_to_default_when_config_lacks_field(self, mock_client):
        """配置对象没有该属性时回退到默认字段，不静默失效。"""
        from types import SimpleNamespace

        service = SignService(mock_client, SimpleNamespace(jitter=0.00005))

        assert service.success_field == "timestamp"

    def test_falls_back_to_default_when_field_is_not_a_string(self, mock_client, mock_config):
        """配置值类型异常时回退到默认字段，避免判定退化为「永假」。"""
        mock_config.sign_success_field = 12345

        service = SignService(mock_client, mock_config)

        assert service.success_field == "timestamp"


class TestErrorHandling:
    """错误处理场景测试。"""

    def test_submit_sign_handles_exception_returns_false(self, sign_service, mock_client):
        """测试异常被捕获并返回False。"""
        # 准备
        mock_client.post.side_effect = Exception("Network error")

        # 执行
        result = sign_service.submit_sign(
            123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg"
        )

        # 验证
        assert result is False

    def test_submit_sign_logs_success_message(self, sign_service, mock_client, caplog):
        """测试成功消息被记录。"""
        # 准备
        caplog.set_level(logging.INFO)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1789118122}'
        mock_response.json.return_value = {"timestamp": 1789118122}
        mock_client.post.return_value = mock_response

        # 执行
        sign_service.submit_sign(123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg")

        # 验证
        assert "✅ 签到成功" in caplog.text

    def test_submit_sign_logs_failure_message(self, sign_service, mock_client, caplog):
        """测试失败消息被记录。"""
        # 准备
        import logging

        caplog.set_level(logging.ERROR)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.post.return_value = mock_response

        # 执行
        sign_service.submit_sign(123, 516208, 118.237686, 25.077727, "http://example.com/image.jpg")

        # 验证
        assert "❌ 签到失败" in caplog.text
        assert "500" in caplog.text
