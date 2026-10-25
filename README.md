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

腾讯日历保存安排，GitHub Actions 在 GitHub 托管的 Ubuntu Runner 上定时生成图片，Kodo 存图，Kindle 下载展示。任务按需运行，无需常驻云主机。

## 当前状态

已支持腾讯日历读取、天气查询和日历图片生成，并能在 Kindle 上作为静态屏保展示。月度主题和大字排版已接入。

Kodo 发布、签名下载与定时拉取脚本已实现，自动更新的完整链路仍在联调。详细进展见 [验证记录](docs/superpowers/plans/2026-10-25-kodo-kindle-delivery.md#完成记录)。

## 自动化测试

激活 `.venv` 后运行 `python -m unittest discover -s tests -v`，执行项目全部测试。新增 Mock 端到端测试贯穿腾讯 CalDAV 发现与读取、PNG 渲染、Kodo 上传读回以及 Kindle 下载与模拟绘屏，使用虚构数据和本机服务，无需真实凭据。push、PR 和手动触发会运行 [测试工作流](.github/workflows/tests.yml)，包括依赖一致性、Shell 语法与全量测试检查。运行条件与边界见 [验证说明](docs/USAGE.md#验证)。

## 接下来

- **语音记日程**：计划接入七牛灵矽，用说话的方式管理家庭安排。
- **个性化日历**：自选插画风格与短句，探索定制生成和主题订阅。

## 更多说明

[使用与部署](docs/USAGE.md) · [产品方案](PRODUCT.md) · [技术架构](ARCHITECTURE.md) · [视觉规范](DESIGN.md)

1024 Hackathon · 李正乾 / 蒋潇涵 / 陈潜
