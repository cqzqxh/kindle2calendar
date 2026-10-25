# Kindle 家庭日历

**公司 1024 Hackathon 项目：让家庭安排随时可见，让闲置 Kindle 重新发挥价值。**

家庭活动容易忘记，安排变更也缺少统一更新的地方。项目把家中闲置的 Kindle PW3 改造成共享日历屏：家人在手机上维护活动，家中公共区域持续展示共同安排，减少反复提醒和确认。

## 项目方案

**腾讯日历（CalDAV） → GitHub Actions 定时调度 → 七牛 Runner 生成 PNG → Kodo 发布 → Kindle 下载展示。**

首版先接腾讯日历 CalDAV，后续适配飞书。腾讯日历承担日程编辑与保存，七牛 Runner 按需执行图片生成，Kodo 在任务结束后持续提供图片，Kindle 专注展示。无需新增常驻云主机、自建管理后台或业务数据库。按项目约定，小规模 Runner / Sandbox 与 Kodo 资源费用基本可忽略。

- 日历图片：1072 × 1448、16 级灰度 PNG，月历星期一开头，展示尚未过期的前十项安排和三天天气。CalDAV 事项保留到结束，旧 JSON 定时事项按开始时间过滤，全天事项保留到当天结束，不显示剩余数量或手机端查看提示。
- 日常更新：生成任务和设备下载各为 30 分钟周期，修改到显示可能接近一小时，另加排队与执行时间。
- 天气地区：在 GitHub Actions 配置；完整有效的经纬度优先，否则按城市名称查询。天气失败不影响日历生成。
- 设备访问：目标为 Kodo 私有 HTTPS 下载，设备不保存云端上传密钥；首版签名链接需定期手动续期。
- 设备运行：先按 Wi-Fi 与 USB 供电验证；下载失败保留上一张图，续航和实际显示效果待实测。

## 当前状态

**基础渲染、离线预览和设备下载脚本已具备；完整云端链路仍待实现与实机联调。**

| 能力 | 当前代码与目标差异 |
| --- | --- |
| 日历图片、天气图标 | 已有 Pillow 实现，可复用；CalDAV 已适配全天、跨天、时区、重复实例和取消日程 |
| 天气 | 已支持城市查询、有效坐标优先、非法坐标回退及三天预报；待接入云端发布任务 |
| 日历来源 | 已实现只读 CalDAV 接入；2026-10-25 实测发现 4 个日历、读取 1 条展示项并生成 PNG；多人共享编辑及增删改传播仍待验收 |
| 定时计算与发布 | GitHub 工作流、批处理入口、Runner 接入和 Kodo 发布尚待实现 |
| Kindle | 脚本已支持 Kodo 私有签名 URL；固定 PNG 与分钟时钟已在 PW3 验证绘制和自动更新，云端下载仍待联调 |

以下本机操作用于预览已有图片效果，不会启动完整的七牛 Runner 发布链路。

## 文档导航

| 文档 | 主要内容 |
| --- | --- |
| [PRODUCT.md](PRODUCT.md) | 项目背景、核心价值、交付成果和实施计划 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 一张架构图、任务流程、Actions 配置、发布和鉴权协议 |
| [DESIGN.md](DESIGN.md) | 墨水屏布局、天气展示、空状态与失败状态 |
| [AGENTS.md](AGENTS.md) | 开发约定、已确认决策和验证要求 |

## 本机预览

建议使用 Python 3.14。macOS 使用系统中文字体；Linux 安装 `fonts-noto-cjk`，或通过 `FONT_PATH` 指定字体。以下命令在仓库根目录执行：

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

预报来自 [Open-Meteo](https://open-meteo.com/)，城市坐标数据来自 [GeoNames](https://www.geonames.org/)。GitHub Actions 使用同名环境变量，详见 [天气配置](ARCHITECTURE.md#天气地区配置)；工作流与云端发布仍待实现。

默认使用已同步到 Kindle 的紧凑布局：顶部日期和月历缩短，近期安排以 52px 行距最多显示 10 条，底部三天天气保留。直接运行 `python preview.py --caldav --city 上海` 即可；`--compact` 仍可显式指定，`--no-compact` 可临时使用旧版三条布局。本地生成不会自动同步 Kindle。

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

2026-10-25 已实测 CalDAV 连接、发现、读取和本地渲染；云端调度、Kodo 发布和 Kindle 自动更新尚未完成。重复、取消、全天、跨天及读取失败通过模拟数据测试，尚未逐项进行服务端实测。发现及查询接口依据 [python-caldav 官方文档](https://caldav.readthedocs.io/stable/tutorial.html)。

## Kindle 下载配置

### 设备实时时钟实验

当前默认使用静态日历屏保，暂不启用实时时钟，以减少耗电。2026-10-25 已停止设备时钟与轮播，恢复原生状态栏、解除屏保抑制，最新已安装紧凑版 `preview_202610251050.png` 为唯一屏保图片，确认设备进入 `screenSaver` 状态。休眠期间的定时唤醒下载尚未接入，不会自动获取下一张日历。以下命令仅保留作实验记录。

`kindle/clock-demo.sh` 在固定预览图右上角叠加北京时间，每到整分钟通过 FBInk 局部刷新。默认使用设备 `/mnt/us/family-calendar/preview_202610241720.png`、`/mnt/us/usbnet/bin/fbink` 和设备自带 Amazon Ember 字体，可用 `IMAGE`、`FBINK`、`FONT` 覆盖。运行前停止其他绘屏程序；在脚本所在目录执行 `nohup sh clock-demo.sh >clock-demo.log 2>&1 </dev/null &`，执行 `sh clock-demo.sh stop` 停止并恢复底图及原屏保抑制状态。不会自动恢复先前的轮播进程，也未设置开机自启。

此实验独立于 `run.sh`，不修改原 PNG 或设备系统时区，不负责网络校时、跨天日历更新与云端图片切换。时钟持续运行需要设备保持唤醒，目前按 USB 供电验证。帧缓冲截图能验证绘制内容；实屏残影、闪烁与长期稳定性仍需观察。

实验保持 `Xorg` 运行，通过 `/usr/sbin/eips` 加载整张底图，FBInk 只负责时钟文字与局部刷新。运行时临时暂停 `JunoStatusBarDriver`，避免原生状态栏覆盖日历，正常停止后恢复；停止可能需要等当前一分钟等待结束。实验期间原生状态栏更新暂停，异常强杀后可通过 SSH 执行 `kill -CONT $(pidof JunoStatusBarDriver)` 恢复。可用 `EIPS` 覆盖原生图片显示命令路径。

2026-10-25 在 PW3 验证 `preview_202610241720.png` 上的时钟从 08:49 自动切换至 08:50；帧缓冲截图像素对比确认变化仅在右上角时钟框内。实屏残影与长时间运行尚未验收。

同日换图后用户发现底部棋盘格，截图无法反映该实屏异常，全屏与黑白清屏未解决。恢复 Xorg、改用原生 `eips` 加载底图后重新叠加时钟，用户确认整张日历及底部天气完整清晰。具体底层原因未单独确定；不再使用暂停 Xorg 的实验方式，长时间运行仍需验收。

将 `kindle/config.example.sh` 复制为设备目录下的 `config.sh`，填写 Kodo `latest.png` 的完整私有 HTTPS 签名 URL、对应域名的可信 CA bundle 路径以及 FBInk 路径。配置文件仅设备用户可读，并记录签名链接到期日。

设备需具备脚本运行环境、支持 TLS 的 curl、FBInk 和 lipc。在 `/mnt/us/family-calendar` 放置 `run.sh`、`config.sh`、CA bundle 和 FBInk 后，通过设备 Shell 执行 `sh run.sh`。脚本通过私有 curl 配置传递 URL，不把签名链接放在进程参数中；失败保留或恢复上一张成功图片。不自动配置开机启动或设备系统组件。

## 验证

在仓库根目录、已激活 `.venv` 的终端中执行：

```sh
python -m unittest discover -s tests -v
sh -n kindle/run.sh
```

当前回归覆盖图片灰度与日期边界、天气地区解析与回退、网络失败降级、PNG 预览，以及使用模拟 curl / FBInk 的设备下载与失败恢复。自动化测试模拟网络请求；通过测试不等于 Runner、Kodo 云端链路或实机已可用，上线前仍须完成 [实施与验收](ARCHITECTURE.md#验收与实施顺序)。

2026-10-25 排查发现腾讯 CalDAV REPORT 对三个不同记录地址返回相同日程正文。逐条 GET 已验证能取回不同记录，接入层现按地址读取完整数据后再展开与去重；回归覆盖摘要重复及单条 GET 失败时停止生成。
