"""FAFU 自动签到的签到服务模块。

本模块提供带 GPS 抖动的签到提交功能，
以防止被检测到是自动签到。
"""

import logging
import random
from typing import Any, Optional

from fafu_auto_sign.client import FAFUClient, response_contains_field
from fafu_auto_sign.config import AppConfig

#: 默认的签到成功响应体标志字段。
#: 服务端成功响应中带有该字段（见跨项目逆向记录：成功判定用「响应体含 timestamp」
#: 而非仅看 HTTP 状态码）。失败/被风控拦截时响应体是错误信息或 WAF 的 HTML。
#:
#: ⚠️ 该判据来自跨项目逆向记录，**未在本项目用真实响应验证**。若服务端返回结构
#: 不同，请调整配置项 ``sign_success_field`` / 环境变量 ``FAFU_SIGN_SUCCESS_FIELD``。
DEFAULT_SUCCESS_FIELD = "timestamp"


class SignService:
    """带 GPS 抖动的签到提交服务。

    本服务处理以下功能：
    - 提交带随机 GPS 坐标的签到请求
    - 将坐标格式化为 6 位小数
    - 处理 API 响应并记录结果

    属性:
        client: 用于发起 HTTP 请求的 FAFUClient 实例
        config: 包含抖动设置的 AppConfig 实例
        logger: 本服务的日志记录器实例
    """

    def __init__(self, client: FAFUClient, config: AppConfig):
        """初始化签到服务。

        参数:
            client: 用于发起 HTTP 请求的 FAFUClient 实例。
            config: 包含位置和设置的 AppConfig 实例。
        """
        self.client = client
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        # 成功判定字段可由配置覆盖；配置缺失或类型异常时回退到默认值，
        # 保证判定不会因为一个坏配置项而退化成「永远成功」。
        configured_field = getattr(config, "sign_success_field", DEFAULT_SUCCESS_FIELD)
        self.success_field = (
            configured_field
            if isinstance(configured_field, str) and configured_field.strip()
            else DEFAULT_SUCCESS_FIELD
        )

    def submit_sign(
        self,
        task_id: int,
        position_id: int,
        base_lng: float,
        base_lat: float,
        image_url: Optional[str] = None,
    ) -> bool:
        """提交带 GPS 抖动的签到请求。

        本方法通过为基础坐标添加小的随机偏移量来生成随机 GPS 坐标，
        然后向 API 提交签到请求。

        参数:
            task_id: 要签到的任务 ID。
            position_id: 来自任务详情的签到位置 ID。
            base_lng: 来自任务详情的基础经度坐标。
            base_lat: 来自任务详情的基础纬度坐标。
            image_url: 上传的签到图片 URL。为 None 或空字符串时不提交图片字段。

        返回:
            签到成功返回 True，否则返回 False。

        判定依据:
            **不能只看 HTTP 状态码**。服务端可能返回 200 但业务上失败
            （被风控拦截、任务已过期等），此时只看状态码会把失败误报为成功。
            因此以「状态码正常 **且** 响应体含成功标志字段」为准，
            具体字段名由配置项 ``sign_success_field`` 决定。
        """
        # 使用抖动生成随机化的 GPS 坐标
        jitter = self.config.jitter
        lng = base_lng + random.uniform(-jitter, jitter)
        lat = base_lat + random.uniform(-jitter, jitter)

        # 构建 API 端点 URL（干净的基 URL，无查询参数）
        url = f"/health-api/sign_in/{task_id}/student/sign"

        # 准备查询参数（必须是 URL 查询参数，不能是 JSON 请求体）
        params = {
            "lng": f"{lng:.6f}",
            "lat": f"{lat:.6f}",
            "signInPositionId": position_id,
        }
        if image_url:
            params["signImg"] = image_url

        self.logger.debug(f"正在为任务 {task_id} 提交签到，坐标 [{lng:.6f}, {lat:.6f}]")

        try:
            # 使用查询参数发起 POST 请求
            response = self.client.post(url, params=params)

            if not self.probe_sign_response(response):
                # 失败原因分两类，日志要能区分，否则排查时无法判断是
                # 「请求链路/风控问题」还是「业务上没签上」。
                status = response.status_code
                if not 200 <= status < 300:
                    self.logger.error(f"❌ 签到失败，状态码: {status}, 返回: {response.text}")
                else:
                    self.logger.error(
                        f"❌ 签到未被服务端确认（响应体缺少 {self.success_field} 字段），"
                        f"状态码: {status}, 返回: {response.text}"
                    )
                return False

            self.logger.info(f"✅ 签到成功！当前提交坐标：[{lng:.6f}, {lat:.6f}]")
            return True

        except Exception as e:
            self.logger.error(f"❌ 签到请求发生异常: {e}")
            return False

    def probe_sign_response(self, response: Any) -> bool:
        """判断一个签到响应是否代表成功（供外部/测试复用）。

        参数:
            response: ``requests`` 的响应对象。

        返回:
            状态码正常且响应体含成功标志字段时返回 True。
        """
        try:
            status = int(getattr(response, "status_code", 0))
        except (TypeError, ValueError):
            return False
        if not 200 <= status < 300:
            return False
        return response_contains_field(response, self.success_field)

    def _calculate_jittered_coordinates(
        self, base_lng: float, base_lat: float
    ) -> tuple[float, float]:
        """计算带随机抖动的 GPS 坐标。

        这是一个辅助方法，可用于测试或
        当你只需要坐标而不需要提交时。

        参数:
            base_lng: 基础经度坐标。
            base_lat: 基础纬度坐标。

        返回:
            应用抖动后的（经度，纬度）元组。
        """
        jitter = self.config.jitter

        lng = base_lng + random.uniform(-jitter, jitter)
        lat = base_lat + random.uniform(-jitter, jitter)

        return lng, lat
