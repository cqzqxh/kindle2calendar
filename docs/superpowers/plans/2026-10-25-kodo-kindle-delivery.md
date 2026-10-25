# Kodo 发布与 Kindle 轮询实施计划

更新日期：2026-10-25。当前协议为每日目录 / 秒级时间戳不可变图片，设备完整 list 后选最新，逐轮签发 300 秒下载链接。demo 允许设备本地保存 AK/SK，但真实凭据禁止提交。协议见 [详细设计](../specs/2026-10-25-kodo-kindle-delivery-design.md)，部署见 [使用说明](../../USAGE.md)。

## 已实现

- [x] PNG 结构、CRC、灰阶、尺寸和发布元数据校验。
- [x] TIMEZONE 生成 `family-calendar/<screen-id>/YYYYMMDD/YYYYMMDDHHmmss.png`；insertOnly 上传、同秒冲突拒绝、相同内容幂等、上传后读回校验。
- [x] Kodo SDK 签名与 ETag、HTTP 子进程硬超时、有限重试和共享总预算，不覆盖或删除已有图片。
- [x] 本机 sync_calendar：CalDAV → 天气 / 渲染 → Kodo，文件锁、单轮 240 秒；已配置 LaunchAgent 每 300 秒调用。
- [x] Kindle 使用现有 Shell、curl、OpenSSL、jq：list 完整分页、最多 7 天回溯、选最大合法时间戳、300 秒图片签名，无 Python 依赖。
- [x] 私有配置放在 /var/local/family-calendar/discovery.json（0600），临时签名材料放在 /tmp 随机私有目录；/mnt/us 不存密钥。
- [x] 单次 / 循环下载、PNG 头检查、FBInk 解码显示、成功后保存、失败保留 / 恢复缓存、日志与进程身份管理。
- [x] RTC 昼夜调度、Wi-Fi 等待与恢复代码及本地模拟；尚未完成真实休眠验收。
- [x] 默认只允许 HTTPS，明确开启 ALLOW_HTTP_DOWNLOAD=1 才允许 demo HTTP 图片；管理请求始终 HTTPS。
- [x] HIDE_STATUS_BAR 可暂停原生时钟覆盖；正常停止仅恢复自身暂停且启动身份匹配的驱动。
- [x] 手动空日历 demo 工作流，生产 schedule 保持关闭。

## 完成记录

| 检查 | 已确认结果 |
| --- | --- |
| CalDAV 与渲染 | 本机完成真实发现、逐条读取、天气和图片生成；共享权限及服务端边界场景仍待逐项实测 |
| 本机周期生成 | LaunchAgent 每 300 秒调用 sync_calendar；真实时间戳对象上传和 HTTPS 读回通过 |
| 实机工具 | 系统 curl 7.76.1、OpenSSL 1.0.2q、jq-master-a9f97e9、BusyBox 1.28.3；未找到 Python，未安装新增软件 |
| 实机分页与签名 | 两页假列表、选最新、请求 / 下载签名和私有文件清理通过；随后真实 list 与下载通过 |
| HTTP 单次下载 | 用户明确授权；真实 HTTPS list 后下载 HTTP 图片返回 200，47022 字节、1072 × 1448 灰度头正确；FBInk 成功，脚本退出 0，原电源设置恢复 |
| 5 分钟拉取 | 22:06:34 与 22:11:36 连续两轮成功，间隔 302 秒；第二轮摘要变化且与最新发布一致，failures=0 |
| 原生时钟隐藏 | HIDE_STATUS_BAR=1 后重启实例，截图确认左上角时间消失，后续拉取保持运行 |
| 本地回归 | 先前完整 Shell 回归 114 项通过（93.236 秒）；随后独立验证发现脚本 9 项、状态栏 4 项及设备 HTTP / 停止用例。数字是各次验证记录，不代表当前测试总数 |

设备测试实例位于 `/mnt/us/family-calendar/list-demo/`，配置 POWER_MODE=awake、INTERVAL=300、ALLOW_HTTP_DOWNLOAD=1、HIDE_STATUS_BAR=1。实例现已停止，恢复 preventScreenSaver=0 与原生状态栏，不再自动拉图。运行时每轮完成后等待 300 秒，实际间隔包括查询和绘屏时间；没有开机自启，没有修改原 linkss 静态屏保入口。正常停止使用 `sh /mnt/us/family-calendar/list-demo/control.sh stop`。

本机 .venv 当前实测 Python 3.14.5，发布工作流选定 3.12.15；不将未执行的 Runner 配置写成实测版本。Mock 端到端测试已覆盖外部接口与硬件边界替身，仍不能代替真实权限、网络和设备故障验收。

真实配置由用户写入设备私有目录，未打印 AK/SK 或签名 URL，未提交真实凭据。设备截图只留在设备测试目录及 Git 忽略的 artifacts，不作为公开附件。

## 外部验收待办（未完成）

- [ ] 验证独立设备身份的最小权限边界，仅允许目标空间 list 与图片读取。
- [ ] 验证设备使用可信 HTTPS 下载图片及所用域名的有效期；当前设备仅完成授权 HTTP 图片测试，不能据此宣称 HTTPS 已通过。
- [ ] 确认仓库 Runner readiness、实际标签和授权，真实运行手动 demo 工作流。
- [ ] 把已有 CalDAV / 天气模块接入云端工作流，手动验证后再启用生产 schedule。
- [ ] PW3 实测 RTC 休眠、到点唤醒、Wi-Fi 重连和原生屏保入口联动；当前持续唤醒的结果不作为这些项目的验收。
- [ ] 进行 48–72 小时连续运行，覆盖跨天、真实断网恢复、删除日程和绘屏失败；截图不能替代实屏残影与清晰度观察。

## 已知限制

时间戳命名避免同名覆盖的 CDN 旧缓存，不解决域名到期、TLS 或鉴权。此前默认源站测试中 60 / 300 秒签名成功，600 秒 / 30 天失败；临时测试域名 HTTPS 证书校验失败。这些是当时链路结果，不能推定所有域名具有相同限制。

正常退出会恢复原电源、Wi-Fi 和自身暂停的状态栏；SIGKILL / 断电不能保证清理。若原进程已退出而状态栏仍暂停，可按使用说明发送 CONT 恢复。残留锁须核实身份后手工处理，不自动删锁。

### 电源管理恢复

用户反馈轻按电源键无预期响应且不再休眠。实机确认 awake 验证进程保持 preventScreenSaver=1、状态栏驱动暂停；已通过 control.sh stop 停止，确认 preventScreenSaver=0、状态栏恢复运行。保留测试配置但不自动启动；保持正常休眠并定时拉图须另行完成 RTC 实机验收。
