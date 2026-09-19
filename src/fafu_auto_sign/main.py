"""FAFU Auto Sign 应用程序的主入口点。

本模块为自动签到守护进程提供主入口点，
集成所有模块：配置、日志、客户端、服务和优雅退出。
"""

import logging
import random
from typing import Optional

from requests.exceptions import ConnectionError, RequestException

from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.config import AppConfig, load_config
from fafu_auto_sign.graceful_shutdown import GracefulShutdown
from fafu_auto_sign.logging_config import setup_logging
from fafu_auto_sign.services import SignService, TaskService
from fafu_auto_sign.services.notification_service import NotificationService
from fafu_auto_sign.services.upload_service import UploadService
from fafu_auto_sign.state import BackoffState, StateStore
from fafu_auto_sign.timeutil import format_timestamp, local_timezone_offset, now


def warn_timezone_mismatch(config: AppConfig, logger: logging.Logger) -> None:
    """系统时区与业务时区不一致时给出提示。

    服务端按配置的业务时区（默认北京时间 UTC+8）判定签到窗口，并对签名中的
    时间戳做新鲜度校验。本程序的窗口判断与时间展示均使用
    ``config.timezone_offset``，**不受宿主机时区影响**；但时区不一致会让日志
    里的时间难以与校方口径对照，因此启动时提示一次。

    参数:
        config: 应用配置。
        logger: 日志记录器。
    """
    local_offset = local_timezone_offset()
    if local_offset is None:
        return
    if abs(local_offset - config.timezone_offset) > 1e-6:
        logger.warning(
            f"系统时区偏移为 UTC{local_offset:+g}，业务时区为 "
            f"UTC{config.timezone_offset:+d}；程序按业务时区计算签到窗口"
            f"（如需本地时间一致可设置 TZ=Asia/Shanghai）"
        )


def wait_random_sign_delay(
    shutdown: GracefulShutdown,
    min_seconds: int,
    max_seconds: int,
    logger: logging.Logger,
) -> bool:
    """在签到前随机等待，并允许通过退出信号提前结束等待。

    返回:
        如果等待期间收到退出信号则返回 True，否则返回 False。
    """
    delay_seconds = random.randint(min_seconds, max_seconds)
    logger.info(
        f"签到前随机等待 {delay_seconds} 秒（范围 {min_seconds}-{max_seconds} 秒）"
    )
    return shutdown.wait(delay_seconds)


def run(
    config_path: str = "config.json",
    once: bool = False,
    state_path: Optional[str] = None,
    ignore_backoff: bool = False,
) -> None:
    """运行自动签到守护进程。

    本函数初始化所有组件并运行主循环，执行以下操作：
    1. 获取待处理任务
    2. 获取签到位置（必要时上传图片）
    3. 提交签到请求
    4. 等待下一个心跳间隔

    守护进程可通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅停止。
    网络错误会被优雅处理，不会导致守护进程崩溃。

    失败退避:
        请求级失败（网络错误、请求异常）会写入**持久化**的退避状态，
        后续循环在退避期内不再发起请求。这样即使服务端开始限流，也不会
        被持续重试加压；退避状态与常驻进程、``--once`` 手动运行共享。

    参数:
        config_path: JSON 配置文件的路径。
        once: 只扫描一次并最多处理一个匹配任务，然后退出。
        state_path: 运行期状态文件路径。为 ``None`` 时使用
            ``config.state_path``（默认 ``state.json``）。
        ignore_backoff: 忽略持久化的失败退避并立即尝试（排查问题时使用）。
    """
    # 1. 加载配置
    config = load_config(config_path)

    # 2. 初始化通知服务（如果启用）
    notification_service = None
    if config.notification_enabled:
        notification_service = NotificationService(config)

    # 3. 设置日志
    setup_logging(config.log_level, notification_service=notification_service)
    logger = logging.getLogger(__name__)

    # 4. 时区提示（窗口与时间展示均按业务时区，不依赖宿主机时区）
    warn_timezone_mismatch(config, logger)

    # 5. 持久化的失败退避（跨进程共享）
    #    调用方未显式指定路径时以配置为准，便于在不同部署目录间迁移。
    resolved_state_path = state_path if state_path is not None else config.state_path
    backoff = BackoffState(StateStore(resolved_state_path))

    # 6. 创建客户端和服务
    with FAFUClient(config) as client:
        task_service = TaskService(client, config)
        sign_service = SignService(client, config)
        # 图片上传默认关闭；仅在开关打开时才构造上传服务，
        # 避免为一个从不使用的服务付出初始化开销与额外的失败面。
        upload_service = UploadService(client) if config.image_upload_enabled else None

        # 7. 创建优雅退出处理器
        shutdown = GracefulShutdown()
        shutdown.register_cleanup(client.close)

        logger.info("启动自动保活与签到守护进程...")

        # 8. 主循环
        while not shutdown.is_stopped():
            had_error = False
            try:
                if backoff.is_blocked() and not ignore_backoff:
                    remaining = int(backoff.remaining_wait())
                    logger.warning(
                        f"处于失败退避期，{remaining} 秒后重试"
                        f"（忽略退避请使用 --ignore-backoff）"
                    )
                else:
                    # 获取所有待处理任务
                    task_ids = task_service.get_pending_tasks()

                    if task_ids:
                        if once:
                            task_ids = task_ids[:1]
                        logger.info(f"发现 {len(task_ids)} 个待签到任务")

                        for task_id in task_ids:
                            if shutdown.is_stopped():
                                break
                            try:
                                logger.info(f"开始处理任务 {task_id}")
                                # 获取任务详情（包含位置信息）
                                task_details = task_service.get_task_details(int(task_id))
                                if task_details is None:
                                    logger.warning(f"任务 {task_id} 无地理位置限制，跳过签到")
                                    continue

                                logger.info(f"获取到签到位置：{task_details.position_name}")

                                # 常驻模式在签到前随机等待；--once 模式跳过等待。
                                if not once and wait_random_sign_delay(
                                    shutdown,
                                    config.sign_delay_min,
                                    config.sign_delay_max,
                                    logger,
                                ):
                                    break

                                img_url = None
                                if upload_service is not None:
                                    # 图片上传开关开启时才上传图片。
                                    img_url = upload_service.upload_image(config.image_path)
                                    if not img_url:
                                        logger.warning(f"任务 {task_id} 图片上传失败，跳过签到")
                                        continue
                                else:
                                    logger.info("图片上传已关闭，跳过图片上传")

                                # 提交签到（使用动态位置参数）
                                success = sign_service.submit_sign(
                                    task_id=int(task_id),
                                    position_id=task_details.position_id,
                                    base_lng=task_details.base_lng,
                                    base_lat=task_details.base_lat,
                                    image_url=img_url,
                                )

                                if success:
                                    logger.info(f"✅ 签到成功！位置：{task_details.position_name}")
                                    backoff.record_success()
                                else:
                                    logger.error(f"❌ 签到失败！位置：{task_details.position_name}")
                            except Exception as e:
                                logger.error(f"处理任务 {task_id} 时发生异常: {e}")
                                had_error = True
                    else:
                        if once:
                            logger.info("单次运行未发现任务，程序退出。")
                        else:
                            next_at = format_timestamp(
                                int(now(config.timezone_offset).timestamp())
                                + config.heartbeat_interval,
                                config.timezone_offset,
                            )
                            logger.info(
                                f"心跳保活成功，未发现任务。下次检查约在 {next_at}"
                            )

            except ConnectionError as e:
                logger.error(f"网络连接错误: {e}")
                had_error = True
            except RequestException as e:
                logger.error(f"请求错误: {e}")
                had_error = True
            except Exception as e:
                logger.error(f"发生异常: {e}")
                had_error = True

            # 仅请求级失败才推进退避：没有任务属于正常情况，不应触发退避
            if had_error:
                backoff.record_failure()

            if once:
                break

            # 等待心跳间隔（默认15分钟）或直到收到退出信号
            if shutdown.wait(config.heartbeat_interval):
                break

        logger.info("守护进程已停止")


if __name__ == "__main__":
    run()
