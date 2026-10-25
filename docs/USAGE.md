# 使用与部署

[返回项目首页](../README.md)

## 本机预览

使用 Python 3.12+，当前本地 .venv 实测为 3.14.5，发布工作流选定 3.12.15，Runner 环境尚未实测。macOS 使用系统中文字体；Linux 安装 `fonts-noto-cjk`，或通过 `FONT_PATH` 指定字体。以下命令在仓库根目录执行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python preview.py --city 上海
```

默认直接生成带时间戳的图片，例如 `artifacts/preview_202610241137.png`，便于保留 Hackathon 展示素材。同一分钟重复生成时追加 `_2`、`_3` 等序号，避免覆盖已有图片。不启动服务、不发布到云端；没有输入日程时显示空日历。

`--city 上海` 会自动查询上海坐标并获取三天天气，也可设置环境变量 `WEATHER_CITY` 后直接运行 `python preview.py`。提供完整有效的 `--latitude` / `--longitude` 或 `WEATHER_LATITUDE` / `WEATHER_LONGITUDE` 时优先使用坐标；坐标缺失、不完整或非法时回退到城市查询。不配置任何地区时不会猜测位置，天气区域显示不可用，终端提示设置城市或坐标。

可使用 `--events /path/to/events.json` 读取已规范化的日程数组，字段为 `title`、`day`（YYYY-MM-DD）、可选 `time`（HH:mm，空字符串表示全天）及可选 `member`。JSON 输入的跨天和重复事件需预先展开；`--caldav` 由来源模块自动展开。

`--weather /path/to/weather.json` 优先读取本地 Open-Meteo `daily` JSON，不请求网络，数组字段为 `time`、`weather_code`、`temperature_2m_min` 和 `temperature_2m_max`。`--offline` 可显式关闭网络查询，没有天气文件时展示天气不可用；天气请求失败同样不会阻断日历生成。

通过 `--now` 指定 ISO 8601 预览时间，`--timezone` 指定日历与天气共同的时区。默认文件名使用与图片一致的预览时间和时区，显式设置 `--now` 也会影响文件名。天气请求使用预览日期起三天的明确起止日期，近期历史日期可在接口支持范围内自动查询；超出范围时可用 `--weather` 提供对应天气 JSON，避免将今天的天气放到历史图片中。指定 `--output` 则使用该路径并允许覆盖已有输出文件。完整选项可用 `python preview.py --help` 查看。

预报来自 [Open-Meteo](https://open-meteo.com/)，城市坐标数据来自 [GeoNames](https://www.geonames.org/)。GitHub Actions 使用同名环境变量，详见 [天气配置](../ARCHITECTURE.md#天气地区配置)；当前工作流仍是空日历手动演示，自动来源接入和生产定时发布待完成。

默认使用紧凑布局：月历日期 32px、格内日程 22px，近期安排正文 36px、日期时间及成员 30px，以 52px 行距最多显示 10 条；底部天气描述 30px、温度 30px。月历区域使用常规字重，顶部、近期安排与天气文字增加 1px 同色描边，改善息屏无前光时的可读性。直接运行 `python preview.py --caldav --city 上海` 即可；`--compact` 仍可显式指定，`--no-compact` 可临时使用旧版三条布局。本地生成不会自动同步 Kindle；本次月历常规字重版本 `preview_202610252057.png` 已安装到 Kindle，并核对设备屏保截图，用户已确认采用此版本。

月度主题默认按图片生成日期切换，目前已配置十月「桂香」和十一月「暖食」，素材位于 `assets/themes/`，文案和月份映射位于 `monthly_themes.py`。可用 `python preview.py --offline --now 2026-11-01T10:00:00` 预览十一月；无需联网生成插画。跨月需重新生成并安装图片，已有静态屏保不会自行换主题。2026-10-25 已将十月「桂香」安装为设备静态屏保。

## 腾讯日历 CalDAV 同步

本地先加载保存凭据的 Shell 配置（本机实际为 `~/.zshrc`；如使用 `~/.zsh_rc` 则加载对应文件），再运行：

```sh
. ~/.zshrc
. .venv/bin/activate
python preview.py --caldav
```

代码兼容本机已有的 `TECENT_CalDAV_ADDR`、`TECENT_CalDAV_UID`、`TECENT_CalDAV_PASSWD` 三个环境变量。也支持标准名称 `CALDAV_URL`、`CALDAV_USERNAME`、`CALDAV_PASSWORD`，同项以标准名称优先；密码使用服务提供的 CalDAV 专用密码。不提交凭据，不把凭据放入命令参数。

默认合并账号下所有可发现日历。设置 `CALDAV_CALENDAR_NAME` 可仅读取一个名称唯一的日历；指定名称不存在或重名时终止。共享日历是否可见取决于服务端授权，仍需实际验收家庭成员编辑。程序只执行发现和查询，不创建、修改或删除远端活动。

读取窗口覆盖当月完整周网格与未来 31 天，按 `TIMEZONE` 转换；浮动时间按该时区解释。REPORT 仅用于发现记录地址，再逐条 GET 原始日程，避免腾讯接口在不同地址返回相同摘要正文而漏项；重复及例外实例由 recurring-ical-events 展开；全天结束日期为排他日期，跨天事件按日期拆分，近期安排保留进行中活动且同一实例只显示一次。未展开的重复规则、解析失败或任一日历读取失败均终止生成，已有图片保持不变；完整成功的空日程正常生成空月历。每次完整重读，不缓存已删除的活动。

`--caldav` 与 `--events`、`--offline` 互斥。可同时使用 `--city` 或天气环境变量；未配置地区时天气不可用。读取请求超时为 15 秒，当前本地入口失败后由操作者重新执行。图片输出遵循上述预览文件规则，真实日程图片仅保留在被 Git 忽略的本地路径，勿作为公开附件。

2026-10-25 已实测 CalDAV 连接、发现、读取和本地渲染；Kodo 发布、Kindle 下载与工作流入口已有本地回归，本机自动生成、Kodo 发布与 Kindle 5 分钟拉取已实测；真实 Runner 调度、HTTPS 图片、RTC 和长期运行仍待验收。重复、取消、全天、跨天及读取失败通过模拟数据测试，尚未逐项进行服务端实测。发现及查询接口依据 [python-caldav 官方文档](https://caldav.readthedocs.io/stable/tutorial.html)。

## 发布到 Kodo

图片路径为 `family-calendar/<screen-id>/YYYYMMDD/YYYYMMDDHHmmss.png`，例如 `family-calendar/kindle-pw3/20261026/20261026212259.png`。日期与文件名由 PNG 生成时间转换到 TIMEZONE 得到；只新增、不覆盖。同秒不同内容报告冲突，相同内容重跑幂等成功。上传后读回校验，不先 GET 尚不存在的 key，避免 CDN 负缓存。建议在控制台设置 7 天生命周期，代码不自动清理云端对象。

图片必须包含发布元数据，限制为 2 MiB、1072 × 1448、8-bit 灰度、16 级灰阶 PNG。源读取或渲染失败不进入发布，失败不删除已有对象。

| 环境变量 | 配置 |
| --- | --- |
| QINIU_ACCESS_KEY / QINIU_SECRET_KEY | 发布身份，通过本机安全环境或 Actions Secrets 注入，禁止提交 |
| KODO_BUCKET | 专用私有 Bucket |
| KODO_DOMAIN | 发布读回使用的 HTTPS 域名，不含路径、查询串或凭据 |
| KODO_UPLOAD_HOST | Bucket 所属区域的 HTTPS 上传入口 |
| KODO_INSECURE_TLS | 默认 0；仅临时联调设为 1，跳过 Kodo 下载证书校验；上传和 CalDAV 仍校验证书 |
| SCREEN_ID | 固定屏幕标识，必须与 PNG 元数据一致 |
| TIMEZONE | 日历、天气和对象日期的共同 IANA 时区，默认 Asia/Shanghai |

先生成再发布；以下例子读取真实 CalDAV：

```sh
python preview.py --caldav --screen-id "$SCREEN_ID" --output artifacts/calendar.png
python -m scripts.publish_calendar --image artifacts/calendar.png
```

发布命令输出脱敏 JSON，包含 status、object_key、sha256、generated_at、exit_code 和 error_code。退出码 0 为发布或幂等成功，2 输入 / 配置错误，3 同秒冲突，5 上传失败或读回未确认。上传和读回通过 HTTP 子进程执行并共享截止时间。

### 本机每 5 分钟同步

本机已加载 LaunchAgent `com.kindle2calendar.local-sync`，每 300 秒调用 `scripts.sync_calendar`：重新读取 CalDAV、生成图片、发布并读回。脚本用文件锁避免重叠，单轮最多 240 秒；来源或生成失败不上传旧文件。图片显示的预计下次生成时间通过 `--interval-minutes` 传给预览，当前为 5 分钟。

配置位于 `~/Library/LaunchAgents/com.kindle2calendar.local-sync.plist`，凭据来自本机安全环境，兼容 QINIU_AK / QINIU_SK / QINIU_BUCKET。状态位于 `artifacts/local-sync/status.json`，生成图片为 `artifacts/local-sync/calendar.png`，均被 Git 忽略。电脑必须保持唤醒并联网；此任务负责生成与发布，设备还需独立运行拉取脚本。

```sh
launchctl print gui/$(id -u)/com.kindle2calendar.local-sync
cat artifacts/local-sync/status.json
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.kindle2calendar.local-sync.plist
# 重新启动：使用 bootstrap 代替 bootout
```

### GitHub Actions 发布

[发布工作流](../.github/workflows/calendar.yml) 使用 GitHub 托管的 `ubuntu-24.04`。Secrets 使用 `QINIU_AK`、`QINIU_SK`、`TECENT_CalDAV_UID` 和 `TECENT_CalDAV_PASSWD`；Variables 使用 `QINIU_BUCKET`、`TECENT_CalDAV_ADDR`、`KODO_DOMAIN` 和 `KODO_UPLOAD_HOST`。工作流读取真实 CalDAV 日程，生成不可变图片并串行发布，默认 `SCREEN_ID=pw3`，不上传私人图片到 GitHub Artifacts。

手动运行可通过 `kodo_domain`、`kodo_upload_host` 指定本次测试地址；先保持 `insecure_kodo_tls=false` 验证正常 HTTPS，确认 `tls_error` 后可显式开启该开关临时复测。开关默认关闭，只影响 Kodo 下载，无法解决访问权限、域名有效期或缓存问题。完成手动发布验收并配置仓库 Variables 后，再合入默认分支启用 `7,37 * * * *`；定时任务保持证书校验。

GitHub Free 组织的私有仓库共享每月 2,000 分钟标准 Runner 额度，实际剩余额度以组织账单页面为准。按每天 48 次调度、30 天计算为每月 1,440 次任务，还需考虑每次执行时间及其他工作流的用量。见 [GitHub 官方额度说明](https://docs.github.com/en/billing/reference/product-usage-included)。

## 设备凭据与列表查询

Kindle 使用现有 POSIX sh、curl、OpenSSL、jq、FBInk、lipc 和标准 Unix 工具，无 Python 依赖。在设备安装任何新软件或依赖前，必须先向用户说明并获确认。

2026-10-25 实机确认系统 curl 7.76.1、OpenSSL 1.0.2q、jq-master-a9f97e9、BusyBox 1.28.3，未找到 Python。已完成假数据分页和签名检查，也已使用真实配置完成 HTTPS list、HTTP 图片下载与自动换图。

将 [discovery.example.json](../kindle/discovery.example.json) 填写为设备的 `/var/local/family-calendar/discovery.json`：

```json
{
  "access_key": "DEDICATED_DEVICE_ACCESS_KEY",
  "secret_key": "DEDICATED_DEVICE_SECRET_KEY",
  "bucket": "YOUR_BUCKET",
  "screen_id": "kindle-pw3",
  "domain": "https://YOUR_DOWNLOAD_HOST"
}
```

目录权限 0700，文件必须为 0600；脚本拒绝读取其他权限的凭据文件。实机 `/mnt/us` 无法落实 Unix 权限，不存放真实 AK/SK。用户允许 demo 保存设备密钥，真实值仍禁止提交、打印或作为附件。仓库的 `kindle/config.sh`、`kindle/discovery.json` 已被 Git 忽略；示例仅保留占位符。

优先为设备建立专用最小权限身份，限定目标空间 list 和图片读取。实际 list 与下载已通过，但最小权限边界没有完成独立验收；依据 [Kodo IAM 接口表](https://developer.qiniu.com/af/12495/kodo-iam-actions) 配置，不把 S3 action 名直接当作原生 Kodo 权限。

`discover.sh` 每轮完整读取当天全部 list 分页，按有效时间戳选最新图片；当天为空才逐日回溯，最多查询当天及前 6 天。列表失败或分页中断保留旧图，不把失败当空目录。每页最多 1000 项、每天最多 100 页，列表请求共享 90 秒预算，每次 curl 硬超时不超过 15 秒。

选中后用设备 AK/SK 签发 300 秒私有链接，交给 curl；不维护 30 天长期链接。签名材料与 curl 配置写入 `/tmp` 随机私有目录，退出删除，不进入命令参数或日志。设备时钟与 TIMEZONE 必须正确。

默认只允许 HTTPS。当前用户已允许临时 HTTP 图片验证：在 config.sh 显式设置 `ALLOW_HTTP_DOWNLOAD=1`，discovery.json 可填 http:// 下载域名；list 与管理凭证仍强制 HTTPS 并校验 CA。HTTP 图片及下载签名可被网络中间节点读取，此开关只用于已同意的 demo。发布者的 KODO_DOMAIN 仍须 HTTPS，可与设备图片域名不同。

在可信电脑调试单张图可执行：

```sh
python -m scripts.sign_download_url --key family-calendar/kindle-pw3/20261026/20261026212259.png --output artifacts/device-url.txt --expires-seconds 300
```

签名写入权限 0600 的新文件，拒绝覆盖，不打印完整链接。此工具不用于配置设备轮询；设备自行逐轮签名。

## Kindle 下载配置

### 当前测试实例

测试目录为 `/mnt/us/family-calendar/list-demo/`，包含 run.sh、common.sh、power.sh、discover.sh、statusbar.sh、control.sh 和不含密钥的 config.sh。RTC 测试配置如下：

```sh
DISCOVERY_CONFIG='/var/local/family-calendar/discovery.json'
CA_CERT='/etc/ssl/certs/ca-certificates.crt'
FBINK='/mnt/us/usbnet/bin/fbink'
TIMEZONE=Asia/Shanghai
POWER_MODE=rtc
INTERVAL=300
RTC_INTERVAL=300
SCREENSAVER_IMAGE=/mnt/us/linkss/screensavers/bg_ss00.png
ALLOW_HTTP_DOWNLOAD=1
HIDE_STATUS_BAR=1
```

此前 awake 测试已因抑制休眠而停止。现按用户要求启动 RTC 验证：RTC_INTERVAL=300，每轮更新后释放唤醒锁、恢复状态栏、更新屏保入口并请求休眠，等待 RTC 下一轮唤醒。当前正在验证完整深度休眠 / 唤醒，不能仅凭 screenSaver 状态认定通过。

本次复用了设备已有证书和 FBInk，没有安装依赖。持续唤醒模式每轮完成后等待 300 秒，实际两次完成间隔包含查询、下载与绘屏耗时。实测 22:06:34 与 22:11:36 两轮均成功，第二轮摘要发生变化且与最新发布一致；该结果属于此前 awake 测试。当前 RTC 实例不自动开机启动，已将原屏保备份到 list-demo/screensaver-before-rtc.png，启用 SCREENSAVER_IMAGE 后每轮把成功缓存图原子复制到原 linkss PNG 入口。

在 Kindle 上管理此实例：

```sh
sh /mnt/us/family-calendar/list-demo/control.sh status
sh /mnt/us/family-calendar/list-demo/control.sh stop
sh /mnt/us/family-calendar/list-demo/control.sh start
# 单次运行前先停止后台实例
sh /mnt/us/family-calendar/list-demo/run.sh --once
```

status 显示进程身份、最近成功时间、失败数和发现模式；RTC 模式等待时另显示 next_sync。时间输出为 UTC，不再显示固定签名链接的到期日。更改 config.sh 后需受控停止并重启；discovery.json 在每轮发现时读取。

### 默认调度与下载行为

[config.example.sh](../kindle/config.example.sh) 为专用日历提供默认配置：POWER_MODE=rtc、INTERVAL=1800、ALLOW_HTTP_DOWNLOAD=0、HIDE_STATUS_BAR=1。加载时 HIDE_STATUS_BAR 缺省为 0，避免未显式配置的实例暂停系统状态栏。

RTC_INTERVAL=0 时，rtc 模式按 TIMEZONE 对齐时间槽：06:00–24:00 每整点与半点，00:00–06:00 在 00、02、04、06 点同步；启动仍立即同步。此模式不使用 INTERVAL；RTC_INTERVAL=0 使用上述昼夜时间槽，显式设置 60–86400 秒可覆盖为固定 RTC 间隔，当前测试为 300。awake 模式启动重绘缓存、立即同步，再在每轮完成后等待 INTERVAL；这是当前已实测的模式。

图片只接受 HTTP 状态 200，curl 单次下载最多 40 秒，临时网络 / 5xx 错误最多重试一次、间隔 5 秒。检查文件大小及 PNG 头、尺寸、位深与颜色类型；FBInk 解码和绘屏成功后才替换 calendar.png。显示状态已确认且字节相同则跳过重绘；下载失败保留旧图，绘屏 / 保存失败尝试恢复缓存。

状态原子写入 state；run.log 达 128 KiB 时轮转并保留一份旧日志。后台忽略 INT/HUP，使用 control.sh stop 发送 TERM 回收 curl / sleep 子进程、清理私有临时目录，并恢复原 Wi-Fi、电源和本进程暂停的状态栏。

### 隐藏原生状态栏时间

HIDE_STATUS_BAR=1 时，statusbar.sh 暂停已有的 JunoStatusBarDriver，再重绘图片，避免原生时间覆盖左上角标题。已在测试中启用并经截图确认时钟消失，停止实例后恢复原生状态栏；RTC 模式在每次休眠前也恢复状态栏，唤醒更新时再暂停。脚本只恢复自身暂停且启动身份仍匹配的驱动；原先已暂停的驱动不改变。

若进程被强杀导致状态栏暂停残留，确认原日历进程已退出后可执行：

```sh
kill -CONT $(pidof JunoStatusBarDriver)
```

### RTC 与休眠展示

power.sh 已实现：每轮后解除屏保抑制，在 active 时请求进入屏保；每 5 秒检查状态，只在 readyToSuspend 窗口设置相对秒数 rtcWakeup。提前唤醒后继续按时钟等待，到点后根据 powerd 状态唤醒（已 active 时不切换，其他已知休眠状态用 powerButton），等待 Wi-Fi（最多 15 次、间隔 2 秒）并恢复原 Wi-Fi 开关状态。调度失败退出并记录 wake_schedule_failed。

这些行为已有本地模拟，目前在 PW3 验证完整的休眠、RTC 唤醒与 Wi-Fi 重连。该固件没有 wakeUp 属性，改用状态守卫的 powerButton；不能对 active 状态盲目触发切换。使用 linkss 时，先把原 PNG 入口备份到屏保目录之外，再设置 SCREENSAVER_IMAGE 为该已有 PNG 的绝对路径。脚本在成功绘屏并保存缓存后，先复制到入口旁的 .tmp 文件，再原子替换入口；写入失败报告 screensaver_save_failed，原入口不会被部分图片覆盖。留空则不更新屏保入口；代码不会安装或重启 linkss，也不停止 Xorg。停止后已设置的 RTC 可能再唤醒一次，但不会继续下载。

屏保恢复失败会非零退出并保留 .running/powerd.previous 及失败标记。残留锁不会自动清除；先确认原进程及子进程退出、检查电源和状态栏恢复，再人工处理。不得在身份未确认时删锁或盲目发送信号。

### 设备实时时钟实验

clock-demo.sh 是独立的分钟级时钟实验，当前未启用，不是自动拉图入口。它使用固定底图、eips 与 FBInk 叠加时间，不负责云端换图，也没有接入 run.sh。曾在 PW3 验证局部时钟刷新，实屏残影与长期运行未验收。不与当前测试实例同时运行。

## 验证

在仓库根目录激活 .venv 后执行：

```sh
python -m unittest discover -s tests -v
sh -n kindle/run.sh
sh -n kindle/common.sh
sh -n kindle/power.sh
sh -n kindle/control.sh
sh -n kindle/config.example.sh
sh -n kindle/discover.sh
sh -n kindle/statusbar.sh
```

回归覆盖日期与灰阶、天气回退、CalDAV 读取、PNG 结构与元数据、不可变上传 / 同秒冲突 / 幂等、Kodo 签名与 HTTP 超时、list 分页与回溯、模拟下载 / 绘屏失败保留旧图、状态栏恢复及 RTC 边界。HTTP 测试需本地监听端口；设备模拟需 curl、OpenSSL、jq 和进程信息。测试通过不等于实机或 Runner 全部验收。

[Mock 端到端测试](../tests/test_e2e.py) 在本机模拟 CalDAV 的 PROPFIND / REPORT / GET、Kodo 上传 / 读回 / 分页 list，执行 sync_calendar、preview、发布 CLI、HTTP worker 和 Kindle run.sh --once。保留实际 CalDAV 客户端、Pillow、curl、OpenSSL 和 jq，只替换外部服务与 FBInk / lipc 硬件边界。覆盖成功、空日历、天气失败继续、来源 / 上传 / 读回 / list / 下载 / 绘屏失败，不代表真实服务权限或设备故障已验收。

仅运行端到端测试：`python -m unittest discover -s tests -p test_e2e.py -v`。需要已有中文字体、curl、jq 和 OpenSSL，不需要真实账号或云端权限。测试专用 `PYTHONPATH` 将外部请求路由到 loopback，并阻止 Python 测试子进程访问非本机地址；生产代码不增加 mock 开关。图片、配置和虚构凭据均在临时目录中，结束后清理。

[GitHub Actions 测试工作流](../.github/workflows/tests.yml) 在 push、pull request 和手动触发时，使用 GitHub 托管 Ubuntu 检查 Python 依赖一致性（`python -m pip check`）、全部 Kindle Shell 语法，并执行全量测试。测试工作流无需 Secrets，不发布图片；日历发布由独立的 `calendar.yml` 工作流执行。

当前实机已验证：真实 HTTPS list、300 秒私有签名、经授权的 HTTP 图片下载、FBInk 绘屏与保存、两轮 5 分钟自动换图、状态栏隐藏。仍需完成最小权限、HTTPS 图片、Runner、RTC 与 48–72 小时跨天断网检查，见 [实施与验收](../ARCHITECTURE.md#验收与实施顺序)。
