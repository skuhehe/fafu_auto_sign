# FAFU Auto Sign - 核心代码

**位置**: `src/fafu_auto_sign/`  
**职责**: HTTP客户端、签名算法、业务服务、配置管理

---

## 模块关系

```
main.py
  ├─ config.py (AppConfig)
  ├─ logging_config.py
  ├─ client.py (FAFUClient)
  │   └─ crypto.py (generate_headers)
  ├─ state.py (StateStore, BackoffState)   # 失败退避持久化
  ├─ timeutil.py (now, now_ms, format_timestamp)  # 业务时区 UTC+8
  ├─ services/
  │   ├─ task_service.py (TaskService, TaskDetails)
  │   ├─ sign_service.py (SignService)
  │   ├─ upload_service.py (UploadService)
  │   └─ notification_service.py (NotificationService)  # 新增
  └─ graceful_shutdown.py (GracefulShutdown)
```

---

## 核心类速查

| 类 | 文件 | 职责 |
|----|------|------|
| `AppConfig` | `config.py` | Pydantic配置，验证token格式(2_开头)、抖动范围(0-0.001)、请求间隔、时区偏移、状态文件路径、成功判定字段 |
| `FAFUClient` | `client.py` | HTTP客户端，请求节流 + 指数退避重试（429 用 30/60/120 阶梯），401/408直接exit |
| `TaskService` | `services/task_service.py` | 获取任务列表，过滤"晚归"关键词，时间窗口判断，按 `signState` 跳过已签 |
| `SignService` | `services/sign_service.py` | GPS抖动提交签到，坐标格式化为6位小数，按响应体字段判定成功 |
| `UploadService` | `services/upload_service.py` | 上传图片到七牛云，支持从目录随机选择，使用`with open()`确保关闭 |
| `StateStore` | `state.py` | JSON 状态仓库：原子写(`os.replace`)、跨进程锁(`O_CREAT\|O_EXCL`)、增量合并、`chmod 600` |
| `BackoffState` | `state.py` | 失败退避阶梯 `60/300/1800/7200` 秒，成功清零；持久化后跨进程共享 |
| `GracefulShutdown` | `graceful_shutdown.py` | SIGINT/SIGTERM处理，15分钟wait或立即退出 |
| `NotificationService` | `services/notification_service.py` | 微信推送通知，5分钟去重，非阻塞发送 |

---

## 关键函数

### crypto.py
```python
generate_auth_header(url: str, user_token: str) -> str
# Sign = MD5(SECRET_KEY + CleanURL + Timestamp + Nonce)
# Auth = Base64(Timestamp:Nonce:Sign:UserToken)
```

### client.py
```python
FAFUClient.request()  # 最大3次重试
# 429 -> RATE_LIMIT_BACKOFF = (30, 60, 120) 阶梯退避
# 500/502/503/504 -> 指数退避 1, 2, 4 秒
# 401 -> sys.exit(1) "Token过期"
# 408 -> sys.exit(1) "时间不同步"

FAFUClient._throttle()  # 每次请求（含重试）前保持 min_request_interval 秒间隔
# _last_request_at 是类属性 -> 同进程多客户端共享节流窗口

response_contains_field(response, field) -> bool
# 优先 response.json() 判断 dict 是否含该字段；
# 非 JSON（如 WAF 的 HTML 拦截页）时回退子串匹配 f'"{field}"' in response.text
```

### state.py
```python
StateStore(path="state.json")
# load() -> dict          # 缺失/损坏/非 dict 一律返回 {}
# get(key, default=None)
# update(**values) -> dict  # None 表示删键；跨进程锁 + 增量合并 + 原子写

BackoffState(store)
# remaining_wait() -> float  # <=0 表示可以尝试
# record_failure() -> float  # 失败计数+1（上限 4），返回本次退避秒数
# record_success()           # 清零计数与退避
# 键名：delay_failures / delay_next_attempt_at / delay_last_success_at / delay_last_failure_at
```

### timeutil.py
```python
CN_TZ_OFFSET = 8
now(offset_hours=8) -> datetime   # 带时区信息的当前时间
now_ms() -> int                   # Unix 毫秒时间戳（替代裸 time.time()）
format_timestamp(ts, offset_hours=8) -> str  # "YYYY-MM-DD HH:MM:SS"，非法值返回其字符串
local_timezone_offset() -> Optional[float]   # 宿主机时区偏移，取不到返回 None
```

### task_service.py
```python
task_service.get_pending_tasks()  # 返回 list[str]，最多 10 个
# 匹配条件：beginTime <= now <= endTime AND "晚归" in name
# 且 signInStudent.signState 为 0 或缺失（非 0 视为已签到，跳过）

task_service.get_pending_task()  # 向后兼容：返回第一个匹配 ID 或 None

task_service._extract_sign_state(task) -> Optional[int]
# 读 task["signInStudent"]["signState"]；缺失/非 dict/不可转 int 时返回 None

task_service.get_task_details(task_id)  # 返回TaskDetails或None
# 提取signInPositions[0]的坐标和位置名称
```

### sign_service.py
```python
DEFAULT_SUCCESS_FIELD = "timestamp"  # 配置项 sign_success_field 的默认值

SignService(client, config)  # self.success_field 从 config.sign_success_field 读取
# 非字符串/空值自动回退到 DEFAULT_SUCCESS_FIELD

SignService.submit_sign(task_id, position_id, base_lng, base_lat, image_url=None) -> bool
# 判定：2xx 且响应体含 success_field 才算成功（见 probe_sign_response）

SignService.probe_sign_response(response) -> bool
# submit_sign 内部复用它；状态码不可转 int 时返回 False 而非抛异常
#
# ⚠️ timestamp 这一判据来自跨项目逆向记录，未在本项目用真实响应验证；
#    服务端结构不同时改配置，不要改回硬编码。
```

### upload_service.py

```python
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}  # 支持的图片格式

UploadService._get_image_files(image_dir: str) -> list[str]  # 扫描目录获取图片列表
# 过滤隐藏文件，按扩展名筛选，返回排序后的完整路径列表

UploadService._select_random_image(image_files: list[str]) -> Optional[str]  # 随机选择
# 使用 random.choice，空列表返回 None

UploadService.upload_image(image_path: str) -> Optional[str]  # 上传图片
# 优先检查 image_dir 配置，存在则从目录随机选择，否则使用 image_path（向后兼容）
```

### notification_service.py

```python
NotificationService(config: AppConfig)  # 初始化，验证 SendKey
# notify(title, content, task_id, success) -> bool  # 发送通知（非阻塞）
# _should_notify(task_id, success) -> bool  # 5分钟去重检查
# _cleanup_expired()  # 清理过期去重记录

# 使用 serverchan_sdk.sc_send() 发送消息
# 自动检测 SendKey 格式（SC3 vs SCT）
# 失败只记录日志，不抛出异常
```
---

## 多图片随机选择机制

新增功能：支持从指定目录随机选择图片，避免长期使用同一张照片被识别。

### 配置方式
```python
# config.py - AppConfig 新增字段
image_dir: Optional[str] = None  # 图片目录路径
# 优先级：image_dir > image_path（向后兼容）
```

### 环境变量支持
```bash
export FAFU_IMAGE_DIR="./photos/"  # 图片目录路径
```

### 图片选择流程
1. `upload_image()` 检查 `self.client.config.image_dir`
2. 如果配置存在：调用 `_get_image_files()` 扫描目录
3. 调用 `_select_random_image()` 从列表中随机选择
4. 如果未配置 `image_dir`：使用原有的 `image_path`（向后兼容）

---



## 签名算法详情

```python
# crypto.py 第12行 - 切勿修改
SECRET_KEY = "AtPs2O1xEnhwkKDV"  # 逆向自APP

# 算法步骤：
# 1. 清理URL（去掉查询参数）
# 2. 生成16位随机nonce
# 3. 获取Unix时间戳（秒）
# 4. raw = SECRET_KEY + clean_url + timestamp + nonce
# 5. sign = MD5(raw).hexdigest()
# 6. auth = f"{timestamp}:{nonce}:{sign}:{user_token}"
# 7. 返回 Base64(auth)
```

---

## GPS抖动机制

```python
# sign_service.py 第55-58行
jitter = config.jitter  # 默认0.00005 (~5米)
lng = base_lng + random.uniform(-jitter, jitter)
lat = base_lat + random.uniform(-jitter, jitter)
# 最终格式化: f"{lng:.6f}"  # 6位小数
```

---

## 错误处理约定

| 层级 | 处理方式 | 示例 |
|------|----------|------|
| client.py | 重试后仍失败则抛出 | `raise RequestException` |
| services | 捕获记录，返回None/False | `return None` |
| main.py | 记录异常并置 `had_error=True`，本轮结束后推进退避，继续下一轮 | `had_error = True` |
| 致命错误 | 立即exit | `sys.exit(1)` |

> 注意：`main.py` 的失败退避只对**请求级失败**生效；「没有待办任务」是正常情况，
> **不会**推进退避（否则安静时段会被锁进长退避而漏签）。

---

## 日志标记约定

```python
self.logger.info("[*] 操作: ...")    # 关键步骤
self.logger.info("✅ 成功: ...")     # 操作成功
self.logger.info("❌ 失败: ...")     # 操作失败
self.logger.warning("[!] 警告: ...")  # 需要注意
self.logger.error("[x] 错误: ...")    # 错误信息
```

---

## 修改注意事项

1. **修改签名算法**: 确保与APP前端保持一致，否则401错误
2. **修改重试次数**: 修改 `client.py` 的 `MAX_RETRIES`
3. **修改心跳间隔**: 修改 `config.py` 的 `heartbeat_interval` 或环境变量
4. **添加新服务**: 继承模式参考现有服务类，注入FAFUClient
5. **添加通知功能**: 参考 `notification_service.py` 模式，使用局部导入避免循环依赖
6. **修改通知配置**: 在 `config.py` 的 `AppConfig` 中添加字段，使用 `Field(default=False)`
7. **集成通知到流程**: 在 `main.py` 初始化，在 `client.py` 致命错误前发送通知
8. **修改成功判定字段**: 改配置项 `sign_success_field`（或 `FAFU_SIGN_SUCCESS_FIELD`），**不要**硬编码回代码
9. **调整退避阶梯**: 改 `state.py` 的 `BACKOFF_SCHEDULE`；改 `client.py` 的 `RATE_LIMIT_BACKOFF`（仅 429）
10. **改动时间判断**: 一律用 `fafu_auto_sign.timeutil`，不要引入裸 `time.time()`/`datetime.now()`
11. **写涉及 `run()` 的测试**: 显式传 `state_path`（用 `tmp_path`），否则会读写项目根目录的真实 `state.json`
12. **写涉及 `FAFUClient` 的测试**: 设 `client.min_request_interval = 0.0`，否则触发真实 sleep
