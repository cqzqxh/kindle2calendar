# Kindle 家庭日历

**公司 1024 Hackathon 项目：让家庭安排随时可见，让闲置 Kindle 重新发挥价值。**

家庭活动容易忘记，安排变更也缺少统一更新的地方。项目把家中闲置的 Kindle PW3 改造成共享日历屏：家人在手机上维护活动，家中公共区域持续展示共同安排，减少反复提醒和确认。

## 项目方案

**飞书共享日历 → GitHub Actions 定时调度 → 七牛 Runner 生成 PNG → Kodo 发布 → Kindle 下载展示。**

首版先接飞书，后续适配钉钉。飞书承担日程编辑与保存，七牛 Runner 按需执行图片生成，Kodo 在任务结束后持续提供图片，Kindle 专注展示。无需新增常驻云主机、自建管理后台或业务数据库。按项目约定，小规模 Runner / Sandbox 与 Kodo 资源费用基本可忽略。

- 日历图片：1072 × 1448、16 级灰度 PNG，月历星期一开头，展示近期安排和三天天气。
- 日常更新：生成任务和设备下载各为 30 分钟周期，修改到显示可能接近一小时，另加排队与执行时间。
- 天气地区：在 GitHub Actions 配置；完整有效的经纬度优先，否则按城市名称查询。天气失败不影响日历生成。
- 设备访问：目标为 Kodo 私有 HTTPS 下载，设备不保存云端上传密钥；首版签名链接需定期手动续期。
- 设备运行：先按 Wi-Fi 与 USB 供电验证；下载失败保留上一张图，续航和实际显示效果待实测。

## 当前状态

**基础渲染、离线预览和设备下载脚本已具备；完整云端链路仍待实现与实机联调。**

| 能力 | 当前代码与目标差异 |
| --- | --- |
| 日历图片、天气图标 | 已有 Pillow 实现，可复用；外部日历的全天、跨天及重复实例需适配 |
| 天气 | 已有预报数据解析；Actions 配置、城市查询和自动获取预报尚待实现 |
| 日历来源 | 飞书共享日历的读取、权限和事件适配尚待实现 |
| 定时计算与发布 | GitHub 工作流、批处理入口、Runner 接入和 Kodo 发布尚待实现 |
| Kindle | 脚本已支持 Kodo 私有签名 URL，云端下载与实机显示仍待验证 |

以下本机操作用于预览已有图片效果，不会启动完整的七牛 Runner 发布链路。

## 文档导航

| 文档 | 阅读目的 |
| --- | --- |
| [PRODUCT.md](PRODUCT.md) | 面向老板和评委：背景、价值、交付成果和实施计划 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 一张架构图、任务流程、Actions 配置、发布和鉴权协议 |
| [DESIGN.md](DESIGN.md) | 墨水屏布局、天气展示、空状态与失败状态 |
| [AGENTS.md](AGENTS.md) | 开发约定、已确认决策和验证要求 |

## 本机预览

建议使用 Python 3.14。macOS 使用系统中文字体；Linux 安装 `fonts-noto-cjk`，或通过 `FONT_PATH` 指定字体。以下命令在仓库根目录执行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python preview.py
```

默认直接生成带时间戳的图片，例如 `artifacts/preview_202610241137.png`，便于保留 Hackathon 展示素材。同一分钟重复生成时追加 `_2`、`_3` 等序号，避免覆盖已有图片。不启动服务、不访问网络、不发布到云端；没有输入日程时显示空日历，没有输入天气时显示“天气暂不可用”。

可使用 `--events /path/to/events.json` 读取已规范化的日程数组，字段为 `title`、`day`（YYYY-MM-DD）、可选 `time`（HH:mm，空字符串表示全天）及可选 `member`。跨天和重复事件需由日历接入层先展开，预览脚本不会代替来源适配器。

`--weather /path/to/weather.json` 接受 Open-Meteo 的 `daily` JSON，包含 `time`、`weather_code`、`temperature_2m_min` 和 `temperature_2m_max` 数组。通过 `--city` 设置地区标题，`--now` 指定 ISO 8601 预览时间，`--timezone` 指定时区。默认文件名使用与图片一致的预览时间和时区，显式设置 `--now` 也会影响文件名。指定 `--output` 则使用该路径并允许覆盖已有输出文件。完整选项可用 `python preview.py --help` 查看。

本地脚本仅预览已提供的数据；自动天气地区解析和网络查询仍待接入。目标方案的变量及回退规则见 [天气配置](ARCHITECTURE.md#天气地区配置)。

## Kindle 下载配置

将 `kindle/config.example.sh` 复制为设备目录下的 `config.sh`，填写 Kodo `latest.png` 的完整私有 HTTPS 签名 URL、对应域名的可信 CA bundle 路径以及 FBInk 路径。配置文件仅设备用户可读，并记录签名链接到期日。

设备需具备脚本运行环境、支持 TLS 的 curl、FBInk 和 lipc。在 `/mnt/us/family-calendar` 放置 `run.sh`、`config.sh`、CA bundle 和 FBInk 后，通过设备 Shell 执行 `sh run.sh`。脚本通过私有 curl 配置传递 URL，不把签名链接放在进程参数中；失败保留或恢复上一张成功图片。不自动配置开机启动或设备系统组件。

## 验证

在仓库根目录、已激活 `.venv` 的终端中执行：

```sh
python -m unittest discover -s tests -v
sh -n kindle/run.sh
```

当前回归覆盖图片灰度与日期边界、天气数据校验、离线 PNG 预览，以及使用模拟 curl / FBInk 的设备下载与失败恢复。通过测试不等于飞书、Runner、Kodo 云端链路或实机已可用；上线前仍须完成 [实施与验收](ARCHITECTURE.md#验收与实施顺序)。
