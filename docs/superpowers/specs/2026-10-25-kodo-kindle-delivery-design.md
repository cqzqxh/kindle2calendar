# Kodo 图片发布与 Kindle 定时拉取详细设计

更新日期：2026-10-25。用户已确认采用每日目录和秒级时间戳图片，demo 阶段允许设备本地保存 AK/SK，禁止提交真实凭据。发布和设备代码已调整，Shell 列表与签名已在 PW3 验证，真实 list 和授权 HTTP 单次下载 / 绘屏调用通过；HTTPS 图片、Runner 与长期链路未完成验收。

业务与主流程见 [ARCHITECTURE.md](../../../ARCHITECTURE.md)，显示规则见 [DESIGN.md](../../../DESIGN.md)，部署见 [使用说明](../../USAGE.md)。

## 对象与图片

```text
family-calendar/<screen-id>/YYYYMMDD/YYYYMMDDHHmmss.png
family-calendar/kindle-pw3/20261026/20261026212259.png
```

日期目录与文件名使用 PNG 生成时间转换至 TIMEZONE 后的值，默认 Asia/Shanghai。日期与文件名前八位一致，不混用机器时区或上传时间。screen-id 为 1–64 位小写字母、数字或连字符，首尾为字母或数字。

输出必须是 1072 × 1448、8-bit 灰度、16 级灰阶 PNG，最大 2 MiB。完整检查 PNG 结构、CRC、IEND、实际解码像素及元数据。元数据保留 calendar_schema、screen_id、UTC generated_at、run_id 和 run_attempt。屏幕和生成身份校验沿用 publication.py；未来超过 5 分钟的生成时间拒绝发布。

## 上传协议

1. 先校验候选图片和配置，按 TIMEZONE 得到唯一时间戳 key。
2. 使用精确 bucket:key 上传凭证，insertOnly=true。上传前不 GET 不存在的 key，避免 CDN 缓存 404。
3. 上传响应必须包含匹配的 key 和官方 Kodo ETag。
4. 上传成功、结果不确定或对象已存在时读回同一 key，完整校验并比较 SHA-256。相同内容幂等成功，不同内容为同秒冲突，不能覆盖。
5. 普通临时上传失败有限重试；写入不确定且读回无法确认则失败退出，等待下一轮重新生成。原有对象从不删除或恢复覆盖。

对象按时间排序决定最新版本，迟到的旧图不会覆盖较新对象。每秒最多一个不同内容版本；重跑应重新生成图片，不能用覆盖方式解决碰撞。建议对象生命周期 7 天。

发布结果为脱敏 JSON：status、object_key、sha256、generated_at、exit_code 和 error_code。退出码 0 成功或幂等，2 输入 / 配置错误，3 同秒冲突，5 上传失败或读回未确认。

Kodo SDK 用于上传 / 下载签名和 ETag。上传 host 明确配置；HTTP 工作进程每次一个请求，敏感参数通过 stdin，保持 TLS 校验、不重定向。父进程上传 60 秒、下载 30 秒硬超时，所有重试共享总预算，内部最多 540 秒，工作流最多 10 分钟。

上传完成即可被 list 发现，发布者读回与设备发现不是事务。设备必须独立校验图片和绘屏；发布成功不能代表 Kindle 已显示。

## Kindle 列表与签名

设备运行 POSIX sh + curl + OpenSSL + jq + FBInk + lipc，复用实机现有工具，不安装 Python。TIMEZONE 经 shell 导出 TZ，Asia/Shanghai 在无 IANA 数据库时使用 CST-8；其他时区必须有对应数据库。

每轮处理：

1. 以目标 screen-id 和当天 YYYYMMDD 为 prefix 调用 HTTPS `rsf.qiniuapi.com/list`，使用官方 Qiniu 管理凭证签名。
2. 每页最多 1000 项，完整处理 marker 分页，空字符串或省略 marker 表示结束；重复 marker、错误响应、损坏 JSON 或网络失败中止本轮。不能用 items 数量判断分页结束。
3. 验证对象路径，只接受同一屏幕、同一天、有效且不晚于当前时间的秒级 PNG 文件名；全部分页结束后取最大文件名。
4. 当天没有候选才查询前一天，最多查询当天及之前 6 天；不假设每个小时都有图片，不把 list 最后一项当最新。
5. 选中图片后生成 300 秒 Kodo 私有签名，写入私有 curl 配置。凭据及完整 URL 不出现在进程参数、日志或状态中。
6. curl 下载临时文件，只接受 200；网络和服务端临时错误有限重试，大小上限 2 MiB。检查 PNG IHDR、1072 × 1448、8-bit 灰度；FBInk 解码显示成功后才保存新图。相同内容在显示状态已确认时跳过重绘。
7. 下载、校验、绘屏或保存失败保留旧图；绘屏 / 保存失败尝试恢复本地缓存，不声称没有旧图时已恢复。

list 每天最多 100 页，所有列表请求共享 90 秒预算，每个 curl 请求硬超时不超过 15 秒。拒绝重定向，使用受信任 CA，不通过代理或 verbose 日志传递凭据。长期域名限制独立于时间戳方案：测试域名的到期、TLS 和私有鉴权仍需实测。

## 配置与凭据

发布侧沿用 QINIU_ACCESS_KEY、QINIU_SECRET_KEY、KODO_BUCKET、KODO_DOMAIN、KODO_UPLOAD_HOST、SCREEN_ID 和 TIMEZONE。

设备 config.sh 配置 RTC_INTERVAL、SCREENSAVER_IMAGE、DISCOVERY_CONFIG、CA_CERT、FBINK、INTERVAL、POWER_MODE、TIMEZONE、HIDE_STATUS_BAR 和 ALLOW_HTTP_DOWNLOAD（默认 0）。用户明确同意的临时 HTTP 图片测试设为 1，list 始终使用 HTTPS。discovery.json 配置 access_key、secret_key、bucket、screen_id 和 domain，保存在 `/var/local/family-calendar/`，文件权限 0600、目录 0700；`/mnt/us` 实机无法落实 Unix 权限，不保存真实密钥。签名材料与 curl 配置使用 `/tmp` 的随机私有目录并在退出时删除。两个真实配置均被 Git 忽略，示例只使用占位符。设备拒绝读取其他用户可访问的 discovery.json。

专用设备身份优先限定目标空间 list 与下载；不得把 S3 action 名当作原生 Kodo IAM 权限。授权以官方接口表及真实调用为准。设备不保存 CalDAV 密码，发布者密钥与设备身份分开管理。demo 已允许设备保存 AK/SK，不表示可以把它们写入仓库或附件。

## 调度与管理

list-demo 曾使用 awake / INTERVAL=300 验证连续两轮，现已停止以恢复正常电源管理；没有开机自启或屏保入口切换。代码RTC_INTERVAL=0 的默认 RTC 模式：06:00–24:00 每半小时，00:00–06:00 每两小时（00、02、04、06），启动立即同步一次。夜间更新延迟相应延长。awake 模式显式按 INTERVAL 轮询。沿用 power.sh 的 Wi-Fi 等待 / 恢复及唤醒逻辑。

control.sh 提供 start/status/stop。锁通过 PID、进程启动标识和脚本路径确认，不删除未经核实的锁。后台忽略 INT/HUP，以 TERM 停止；停止回收子进程、清除私有临时文件并恢复原电源设置。恢复失败保留诊断标记。状态原子写入，日志 128 KiB 轮转，不记录 URL、密钥或日程内容。

工作流仅提供显式确认空日历的 demo- 屏幕手动入口，使用七牛托管 Runner，不新增常驻服务或数据库。生产来源闭环、Runner 权限与实机未完成前不启用 schedule。

## 验收

本地覆盖：跨午夜时区 key、同秒冲突、幂等、上传中断、读回失败、list 乱序与分页、分页失败、跨月回溯、无图片、未来 / 非法 key、签名与官方 SDK 一致、凭据权限、下载 / 绘屏失败保留旧图、RTC 与退出恢复。

已实测真实 list、300 秒签名、HTTP 图片和两轮 5 分钟更新、新图摘要一致性、设备现有工具及状态栏隐藏。外部待完成：最小权限边界、设备 HTTPS 图片、Runner 手动运行、RTC 休眠与屏保联动，以及 48–72 小时跨天和断网连续测试。本地替身测试不代表这些项目已验收。

2026-10-25 核实的官方协议：[list](https://developer.qiniu.com/kodo/1284/list)、[管理凭证](https://developer.qiniu.com/kodo/1201/access-token)、[下载凭证](https://developer.qiniu.com/kodo/1202/download-token)、[IAM 操作](https://developer.qiniu.com/af/12495/kodo-iam-actions)。账号权限与设备能力仍需实测。

原生状态栏：HIDE_STATUS_BAR=1 时暂停当前 JunoStatusBarDriver 并重绘缓存，避免原生时钟覆盖日历；停止时仅恢复本进程暂停且启动身份匹配的进程。原先已暂停的状态栏不改变。强杀后暂停可能残留，按使用说明手动恢复。

RTC 固定周期测试：RTC_INTERVAL 可显式设为 60–86400 秒（默认 0 保留昼夜槽），当前实机测试 300 秒。原生状态栏在每次等待休眠前恢复，唤醒更新时再暂停。该固件无 wakeUp 属性，powerButton 必须按实际状态守卫，active 时不调用。SCREENSAVER_IMAGE 为空时不改变屏保；配置已有绝对 PNG 路径时，在成功保存缓存后通过 .tmp 文件原子替换，失败保留入口。
