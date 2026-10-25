# Kindle 家庭日历

**旧 Kindle，新日常。**

把闲置的 Kindle PW3 改造成家里的共享日历。孩子的课程、图书归还、周末安排和天气，放在家里，一抬头就能看见。

## 演示视频

[![Kindle 家庭日历 · 90 秒 Demo](docs/media/kindle-calendar-demo-cover.jpg)](docs/media/kindle-calendar-demo.mp4)

**[观看 90 秒 Demo](docs/media/kindle-calendar-demo.mp4)** · 从“盖泡面”到家庭日历，看看这台旧 Kindle 的改造故事。

## 能做什么

- **旧物再利用**：用已有的 Kindle 做日历屏，无需另买显示设备。
- **全家都看得见**：月历、近期安排、三天天气，集中显示在一块墨水屏上。
- **每个月换个样子**：已提供十月「桂香」、十一月「暖食」两套插画主题。

## 本机预览

先在电脑上生成一张日历图，无需准备 Kindle 或配置云服务。需要 Python 3.12+：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python preview.py --city 上海
```

图片会保存到 `artifacts/`。城市可以换成你所在的地方；未接入日程时先显示空月历。想离线看看排版，可运行 `python preview.py --offline`。

接入自己的日历、切换主题和 Linux 字体设置，见 [使用说明](docs/USAGE.md#本机预览)。

## 怎么更新

目标是：**手机上改日程，Kindle 定时更新。**

腾讯日历保存安排，GitHub Actions 定时触发七牛 Runner 生成图片，Kodo 存图，Kindle 下载展示。任务按需运行，无需常驻云主机。

## 当前状态

CalDAV、天气、日历渲染和 Kodo 时间戳图片发布已接通。本机每 5 分钟生成并上传；Kindle 曾以每轮完成后等待 300 秒的持续唤醒模式验证连续两轮换图，摘要与最新发布一致。该设备测试现已停止，恢复正常电源管理，不再自动拉取。设备复用 Shell、curl、OpenSSL 和 jq，无需 Python，日历运行时可隐藏原生状态栏时钟，停止后恢复。

已验证的测试使用持续唤醒模式及用户允许的 HTTP 图片下载，list 仍走 HTTPS；真实 AK/SK 只存设备私有配置，禁止提交。未设置设备开机自启，未替换原静态屏保入口。操作与停止方法见 [当前测试实例](docs/USAGE.md#当前测试实例)。

七牛 Runner 仅提供手动空日历 demo 工作流，尚未验收真实运行或启用生产 schedule。默认 RTC 昼夜调度已有代码，HTTPS 图片、最小权限边界、休眠唤醒及 48–72 小时稳定运行仍待完成，详见 [验证记录](docs/superpowers/plans/2026-10-25-kodo-kindle-delivery.md#完成记录)。

## 自动化测试

激活 `.venv` 后运行 `python -m unittest discover -s tests -v`，执行项目全部测试。Mock 端到端测试覆盖 CalDAV 读取、PNG 渲染、Kodo 上传读回与分页 list，以及 Kindle 下载和模拟绘屏，使用虚构数据和本机服务，无需真实凭据。push、PR 和手动触发会运行 [测试工作流](.github/workflows/tests.yml)，包括依赖一致性、Shell 语法与全量测试检查。运行条件与边界见 [验证说明](docs/USAGE.md#验证)。

## 接下来

- **语音记日程**：计划接入七牛灵矽，用说话的方式管理家庭安排。
- **个性化日历**：自选插画风格与短句，探索定制生成和主题订阅。

## 更多说明

[使用与部署](docs/USAGE.md) · [产品方案](PRODUCT.md) · [技术架构](ARCHITECTURE.md) · [视觉规范](DESIGN.md)

1024 Hackathon · 李正乾 / 蒋潇涵 / 陈潜
