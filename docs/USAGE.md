# 使用与部署

[返回项目首页](../README.md)

## 本机预览

使用 Python 3.12+，当前本机与工作流选定版本为 3.12.15。macOS 使用系统中文字体；Linux 安装 `fonts-noto-cjk`，或通过 `FONT_PATH` 指定字体。以下命令在仓库根目录执行：

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

2026-10-25 已实测 CalDAV 连接、发现、读取和本地渲染；Kodo 发布、Kindle 下载与工作流入口已有本地回归，真实云端调度和设备自动更新仍待联调。重复、取消、全天、跨天及读取失败通过模拟数据测试，尚未逐项进行服务端实测。发现及查询接口依据 [python-caldav 官方文档](https://caldav.readthedocs.io/stable/tutorial.html)。

## 发布到 Kodo

2026-10-25 使用真实私有 Bucket，在独立 `demo-kodo-smoke` 历史路径上传 4169 字节测试 PNG，再经默认源站 HTTPS 下载，文件字节及 SHA-256 完全一致，未覆盖 `latest.png`。实测默认源站的 60 秒、300 秒签名返回 200，600 秒与 30 天签名返回 403；当前代码读回默认签名 600 秒，不能直接用于该入口。Bucket 的临时测试域名 HTTPS 证书校验失败。完整发布与设备长期链接仍需配置可用的长期 HTTPS 域名并验收，不能将本次短期下载视为完整链路通过。

准备专用私有 Bucket、对应区域的 HTTPS 上传入口和长期 HTTPS 下载域名。发布身份须支持上传、覆盖和私有读回；历史对象建议在 Kodo 控制台设置 7 天生命周期。若使用 CDN，先验证固定 URL 覆盖后能在约定缓存窗口内取到新内容。

| 环境变量 | 配置 |
| --- | --- |
| `QINIU_ACCESS_KEY` / `QINIU_SECRET_KEY` | 通过安全环境或 Actions Secrets 注入，禁止写入仓库 |
| `KODO_BUCKET` | 私有 Bucket 名称 |
| `KODO_DOMAIN` | 下载 HTTPS 域名，不带路径、查询串或凭据 |
| `KODO_UPLOAD_HOST` | 该 Bucket 所属区域的 HTTPS 上传入口，按七牛控制台核实 |
| `KODO_INSECURE_TLS` | 默认 `0`；仅临时联调设为 `1`，跳过 Kodo 下载的证书校验；上传和 CalDAV 仍校验证书 |
| `SCREEN_ID` | 固定屏幕标识，例如 `demo-screen`，必须与 PNG 元数据一致 |
| `TIMEZONE` | 图片时区，默认 `Asia/Shanghai` |

手动工作流可通过 `kodo_domain`、`kodo_upload_host` 指定本次测试地址。先保持 `insecure_kodo_tls=false` 验证正常 HTTPS；若确认失败原因为 `tls_error`，可勾选该开关临时复测。开关默认关闭，定时任务也保持证书校验。开启后无法验证下载服务器的身份，不用于长期运行；测试域名还受有效期、访问权限和缓存限制，跳过证书校验不代表发布链路可用。

环境配置完成后，先生成并检查图片，再执行发布。以下空日历命令只用于专用演示屏幕；发布真实日程时给 preview 提供 `--events` 输入：

```sh
python preview.py --screen-id "$SCREEN_ID" --output artifacts/calendar.png
python -m scripts.publish_calendar --image artifacts/calendar.png
```

发布先保存 `family-calendar/<screen-id>/history/<UTC日期>/<run-id>-<attempt>.png`，确认读回后更新 `latest.png` 并再次验证。图片限制为 2 MiB、1072 × 1448、8-bit 灰度 PNG，像素仅使用 16 级灰阶；旧版、冲突版本和元数据不完整的图片会被拒绝。不能直接把任意外部 PNG 当作发布文件。

命令输出脱敏 JSON。退出码 `0` 表示发布或相同内容幂等成功，`2` 表示输入/配置错误，`3` 表示旧版本或身份冲突，`4` 表示失败且已保留/恢复旧图，`5` 表示首次失败或最终结果未确认。首次发布无旧版时不会报告回滚成功。程序设有共享总预算和 HTTP 子进程硬超时。

仓库中的 [发布工作流](../.github/workflows/calendar.yml) 使用 GitHub 托管的 `ubuntu-24.04`。Secrets 使用 `QINIU_AK`、`QINIU_SK`、`TECENT_CalDAV_UID` 和 `TECENT_CalDAV_PASSWD`；Variables 使用 `QINIU_BUCKET`、`TECENT_CalDAV_ADDR`、`KODO_DOMAIN` 和 `KODO_UPLOAD_HOST`。手动测试可通过输入项指定本次下载域名和上传入口。工作流读取真实 CalDAV 日程后生成并串行发布，默认 `SCREEN_ID=pw3`，不上传私密 PNG 附件；手动验收完成后再合入默认分支启用 `7,37 * * * *` 定时任务，定时任务使用仓库 Variables 中的域名和上传入口。

GitHub Free 组织的私有仓库共享每月 2,000 分钟标准 Runner 额度，实际剩余额度以组织账单页面为准。按每天 48 次调度、30 天计算为每月 1,440 次任务，还需考虑每次执行时间及其他工作流的用量；不能保证始终处于免费额度内。见 [GitHub 官方额度说明](https://docs.github.com/en/billing/reference/product-usage-included)。

## 签发设备下载链接

在可信机器注入发布凭据和下载配置后执行（此命令不需要 `KODO_UPLOAD_HOST`）：

```sh
python -m scripts.sign_download_url --output artifacts/device-url.txt --expires-days 30
```

签名链接写入权限 `0600` 的新文件，拒绝覆盖已有文件，终端只显示文件路径和到期时间。通过可信通道把完整链接写入设备配置，禁止贴进日志或提交 Git。默认 30 天、手动续期；实际有效期和固定链接读取新版本的行为仍需真实域名验证。

## Kindle 下载配置

### 设备实时时钟实验

当前默认使用静态日历屏保，暂不启用实时时钟，以减少耗电。2026-10-25 已停止设备时钟与轮播，恢复原生状态栏、解除屏保抑制；最新安装的是十月「桂香」月历常规字重版 `preview_202610252057.png`，包含本次读取的 9 条日程展示项与上海三天天气，为唯一屏保图片。安装时备份上一版，核对本地图片、设备副本与屏保入口 SHA-256 一致，确认设备进入 `screenSaver` 状态，并读取设备截图核对布局完整；实际屏幕清晰度仍需用户确认。休眠时实测前光硬件亮度降为 0；用户确认保留休眠省电、靠室内灯光查看。休眠期间的定时唤醒下载尚未接入，不会自动获取下一张日历。以下命令仅保留作实验记录。

`kindle/clock-demo.sh` 在固定预览图右上角叠加北京时间，每到整分钟通过 FBInk 局部刷新。默认使用设备 `/mnt/us/family-calendar/preview_202610241720.png`、`/mnt/us/usbnet/bin/fbink` 和设备自带 Amazon Ember 字体，可用 `IMAGE`、`FBINK`、`FONT` 覆盖。运行前停止其他绘屏程序；在脚本所在目录执行 `nohup sh clock-demo.sh >clock-demo.log 2>&1 </dev/null &`，执行 `sh clock-demo.sh stop` 停止并恢复底图及原屏保抑制状态。不会自动恢复先前的轮播进程，也未设置开机自启。

此实验独立于 `run.sh`，不修改原 PNG 或设备系统时区，不负责网络校时、跨天日历更新与云端图片切换。时钟持续运行需要设备保持唤醒，目前按 USB 供电验证。帧缓冲截图能验证绘制内容；实屏残影、闪烁与长期稳定性仍需观察。

实验保持 `Xorg` 运行，通过 `/usr/sbin/eips` 加载整张底图，FBInk 只负责时钟文字与局部刷新。运行时临时暂停 `JunoStatusBarDriver`，避免原生状态栏覆盖日历，正常停止后恢复；停止可能需要等当前一分钟等待结束。实验期间原生状态栏更新暂停，异常强杀后可通过 SSH 执行 `kill -CONT $(pidof JunoStatusBarDriver)` 恢复。可用 `EIPS` 覆盖原生图片显示命令路径。

2026-10-25 在 PW3 验证 `preview_202610241720.png` 上的时钟从 08:49 自动切换至 08:50；帧缓冲截图像素对比确认变化仅在右上角时钟框内。实屏残影与长时间运行尚未验收。

同日换图后用户发现底部棋盘格，截图无法反映该实屏异常，全屏与黑白清屏未解决。恢复 Xorg、改用原生 `eips` 加载底图后重新叠加时钟，用户确认整张日历及底部天气完整清晰。具体底层原因未单独确定；不再使用暂停 Xorg 的实验方式，长时间运行仍需验收。

将 `kindle/config.example.sh` 复制为设备目录下的 `config.sh`，填写 Kodo `latest.png` 的完整私有 HTTPS 签名 URL、对应域名的可信 CA bundle 路径以及 FBInk 路径。配置文件仅设备用户可读，并记录签名链接到期日。

设备需具备 POSIX sh、支持 HTTPS/TLS 及下载大小限制的 curl、FBInk、lipc 和标准 Unix 工具。复制 `kindle/run.sh`、`kindle/common.sh`、`kindle/control.sh`、私有 `config.sh`、CA bundle 和 FBInk 到 `/mnt/us/family-calendar`。设备时钟必须正确，`URL_EXPIRES_AT` 与链接 `e` 参数一致（也可省略，由脚本读取 `e`）。安装目录仅设备用户可访问，配置权限设为 `0600`。

在设备目录执行：

```sh
sh run.sh --once       # 单次同步；先停止已有后台实例
sh control.sh start    # 后台运行，默认每 1800 秒同步一次
sh control.sh status  # 进程身份、同步状态、失败数和签名到期日
sh control.sh stop    # 验证身份后 TERM 停止，不盲目 kill PID
```

循环启动会先重绘缓存，再立即下载。只接受 HTTPS 的 HTTP 200，验证 PNG 头和尺寸，FBInk 成功后才原子替换 `calendar.png`；失败保留或恢复旧图。URL 通过私有 curl 配置传递，不出现在进程参数中。`state` 保存最近结果，`run.log` 达 128 KiB 轮转并仅保留一份旧日志。不自动配置开机启动。

后台模式明确忽略 INT/HUP，用 `control.sh stop` 发送 TERM 完成清理。退出时屏保恢复失败会非零返回，保留 `.running/powerd.previous` 和失败标记，并通过状态提示人工恢复；恢复成功后才可清理残留锁。

残留 `.running` 锁不会自动清除。强杀或断电后，先核实原进程及 curl 子进程已退出、检查屏保恢复记录，再人工处理锁；不要在进程身份未确认时删除锁或发送信号。真实 PW3 的 `/proc`、curl/TLS、FBInk 和文件系统行为仍需验证。

## 验证

在仓库根目录、已激活 `.venv` 的终端中执行：

```sh
python -m unittest discover -s tests -v
sh -n kindle/run.sh
sh -n kindle/common.sh
sh -n kindle/control.sh
sh -n kindle/config.example.sh
```

回归覆盖图片灰度与日期边界、天气地区解析与回退、CalDAV 读取、PNG 编码与元数据、发布时序与恢复、Kodo 凭证和 HTTP 超时、CLI 文件权限，以及模拟 curl / FBInk 的设备下载与失败恢复。HTTP 测试需本地监听端口，设备测试需读取进程信息。通过测试不等于 Runner、Kodo 云端链路或实机已可用；上线前仍须完成 [实施与验收](../ARCHITECTURE.md#验收与实施顺序)。

[Mock 端到端测试](../tests/test_e2e.py) 在本机模拟腾讯 CalDAV 的 PROPFIND / REPORT / GET，以及 Kodo 上传和私有下载，校验鉴权、上传策略、ETag、PNG 内容与设备缓存。测试依次执行真实 `preview.py --caldav`、`scripts.publish_calendar` 和 Kindle `run.sh --once`；使用实际 CalDAV 客户端、Pillow、HTTP worker 和 curl，仅替换外部服务和 FBInk / lipc 硬件边界。覆盖成功、天气失败继续、空日历、来源失败、历史上传或读回失败、固定入口上传失败、重复发布幂等，以及设备下载 / 绘屏失败保留旧图。

仅运行端到端测试：`python -m unittest discover -s tests -p test_e2e.py -v`。需要已有中文字体、curl、jq 和 OpenSSL，不需要真实账号或云端权限。测试专用 `PYTHONPATH` 将外部请求路由到 loopback，并阻止 Python 测试子进程访问非本机地址；生产代码不增加 mock 开关。图片、配置和虚构凭据均在临时目录中，结束后清理。该测试不验证真实 HTTPS/TLS、服务端兼容性、IAM 或墨水屏硬件。

[GitHub Actions 测试工作流](../.github/workflows/tests.yml) 在 push、pull request 和手动触发时，使用 GitHub 托管 Ubuntu 检查 Python 依赖一致性（`python -m pip check`）、全部 Kindle Shell 语法，并执行 `python -m unittest discover -s tests -v`，自动发现项目现有和新增测试。任一步骤失败都会使 CI 失败。测试工作流无需 Secrets，不发布图片；日历发布由独立的 `calendar.yml` 工作流执行。

2026-10-25 排查发现腾讯 CalDAV REPORT 对三个不同记录地址返回相同日程正文。逐条 GET 已验证能取回不同记录，接入层现按地址读取完整数据后再展开与去重；回归覆盖摘要重复及单条 GET 失败时停止生成。
