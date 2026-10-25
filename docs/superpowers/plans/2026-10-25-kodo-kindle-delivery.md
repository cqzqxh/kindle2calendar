# Kodo 发布与 Kindle 轮询实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 实现可测试、可手动运行的 Kodo 图片发布、私有链接签发及 Kindle 定时下载，保留旧图并准确报告失败。

**Architecture:** Pillow 图片通过共享的发布元数据和验证层进入发布状态机；Kodo 适配层执行精确 key 上传和私有读回。设备沿用 POSIX Shell、curl、FBInk，增加单次模式、内容校验和进程管理。

**Tech Stack:** Python 3.12+、Pillow 13.0.0、qiniu 7.18.0、requests、unittest、POSIX sh。参考规格：[详细设计](../specs/2026-10-25-kodo-kindle-delivery-design.md)。

## 范围与开发条件

- 基线提交 `1632f89`，已有 15 项测试通过。分支 `codex/kodo-kindle-delivery`。
- 本次实现上传与设备端；钉钉接入和自动天气查询继续保留独立待办，不把缺失来源替换为空日历。
- 提供手动演示发布工作流，要求显式确认演示空日历且仅向 `demo-` 前缀屏幕发布。不启用生产定时任务。
- 实机、真实 Bucket 和 Runner 授权未提供；本地使用存储替身和模拟设备命令验证，文档明确外部验收状态。
- 为兑现整个 HTTP 请求的硬超时，增加受控子进程 `storage/http_worker.py`，通过 stdin 传参数，stdout 只返回结构化响应，捕获异常不泄露 URL。父进程超时杀死并回收子进程；不能用 requests 的 read timeout 冒充总超时。
- 使用显式 `KODO_UPLOAD_HOST` 配置 Bucket 所属区域的 HTTPS 上传入口，避免 SDK 自动发现及内部重试绕过总预算。官方 SDK 用于凭证和 Kodo ETag 算法；HTTP 由单次请求适配器执行。

## 文件边界

| 文件 | 工作 |
| --- | --- |
| `publication.py` | 元数据、图像校验、key、发布和恢复协议 |
| `storage/kodo.py`、`storage/http_worker.py`、`storage/__init__.py` | 配置、签名、有限重试、HTTP 硬超时 |
| `scripts/publish_calendar.py`、`scripts/sign_download_url.py`、`scripts/__init__.py` | CLI、脱敏 JSON、退出码、受限签名文件 |
| `preview.py` | 生成图片时附加可追踪元数据 |
| `kindle/run.sh`、`kindle/control.sh`、`kindle/common.sh`、`kindle/config.example.sh` | 循环/单次同步、校验、状态、进程身份和日志 |
| `tests/test_publication.py`、`tests/test_kodo.py`、`tests/test_cli.py` | 发布、HTTP、签名和 CLI 测试 |
| `tests/test_device.py`、`tests/test_preview.py` | 真 PNG 夹具、故障恢复、元数据回归 |
| `.github/workflows/calendar.yml` | 显式手动演示，完整校验后发布，无 schedule |
| README、ARCHITECTURE、PRODUCT、AGENTS、详细设计 | 更新实际状态、配置和操作命令 |

## 任务 1：图片协议与预览

- [x] 在 `tests/test_publication.py` 写真实灰度 PNG 夹具和失败测试；先运行并确认缺失发布模块。
- [x] 实现不可变 `GenerationContext` / `Artifact`；严格限制 screen/run ID、时区、attempt、2 MiB、单帧、1072×1448、L 模式、16 灰阶。
- [x] 两次打开图片分别 verify/load，校验必需 PNG 文本元数据，计算最终 SHA-256；历史 key 的日期使用 UTC。
- [x] 在 preview 增加 `--screen-id`，默认 `preview`，使用本地 UUID；Actions 环境保留真实 run-id/attempt；同一个 now 同时用于渲染与元数据。
- [x] 增加坏 PNG、错误模式/尺寸/灰度、元数据缺失/非法、未来时间、屏幕不匹配测试。

核心验收测试：

```python
def test_roundtrip(self):
    context = GenerationContext(self.now, "demo-screen", "local-test", 1)
    artifact = build_artifact(self.png, context)
    loaded = validate_artifact(artifact.png_bytes, expected_screen="demo-screen", now=self.now)
    self.assertEqual(loaded.sha256, artifact.sha256)
    self.assertEqual(loaded.generated_at, self.now)
    self.assertTrue(loaded.history_key.endswith("/local-test-1.png"))
```

执行：`python -m unittest discover -s tests -p 'test_publication.py' -v` 及 preview 回归；预期全部通过。

## 任务 2：发布状态机

- [x] 编写内存存储替身，保留操作序列并允许注入“已写入但请求抛错”、读回错误和第三方版本变化。
- [x] 先验证首次发布、相同内容幂等、旧版/同时间冲突、同生成身份冲突、历史冲突测试失败。
- [x] 按“读取旧版 → 历史只新增和读回 → latest 二次检查 → 覆盖 → latest 读回”实现，写入候选字节始终相同。
- [x] 写超时确认、失败保留、恢复旧字节、首次无旧图、恢复失败、不覆盖第三个有效版本测试；实现对应结果。
- [x] 设置结果状态和 CLI 退出码映射；存储异常只能包含固定错误类别，不能记录完整异常消息。
- [x] 正常发布和恢复共享总截止时间，覆盖前预留恢复预算；不得通过重试重置截止时间。

发布顺序断言：

```python
result = publish_artifact(candidate, store)
self.assertEqual(result.status, "published")
self.assertEqual(store.objects[candidate.latest_key], candidate.png_bytes)
self.assertEqual(store.objects[candidate.history_key], candidate.png_bytes)
self.assertLess(store.writes.index(candidate.history_key), store.writes.index(candidate.latest_key))
```

执行：`python -m unittest discover -s tests -p 'test_publication.py' -v`；预期全部通过，不访问网络。

## 任务 3：Kodo、签名与 HTTP

- [x] 先测试空配置、非法域名/上传入口、SDK 上传策略、404 与鉴权错误区分、key/hash 返回校验、重试次数、超时预算和脱敏。
- [x] 固定 `qiniu==7.18.0` 及 HTTP 依赖；使用 `Auth.upload_token` 精确 bucket:key，历史 insertOnly，限制 image/png 与 2 MiB。
- [x] `read_image` 生成短期签名 GET，最多读取 2 MiB；只把 404 当不存在，拒绝重定向、非 200 和错误图片。
- [x] HTTP 子进程每次仅一个请求，TLS 校验开启、重定向关闭、连接超时 5 秒，父进程限制下载 30 秒/上传 60 秒及剩余全局预算。
- [x] 对 429/5xx/连接失败最多 3 次尝试（2、5 秒退避）；写入结果不确定由发布层读回确认，不盲目重写。
- [x] 单次上传返回 key 和 Kodo etag 必须匹配，ETag 使用 SDK 的算法，不能和 SHA-256 混用。
- [x] 在测试 HTTP 服务上验证真实 worker 能处理限量响应、错误和超时；生产配置仍只允许 HTTPS。

执行：`python -m unittest discover -s tests -p 'test_kodo.py' -v`。测试签名仅使用显式假凭据。

## 任务 4：CLI 与手动工作流

- [x] 先写参数缺失/输入错误/退出码/不泄露异常内容/签名文件权限与拒绝覆盖测试。
- [x] 发布 CLI 必须传 `--image`，加载图片后校验屏幕与时间，输出单行脱敏 JSON，映射 0/2/3/4/5。
- [x] 签名 CLI 默认 30 天，只允许合理正整数天数，用 `O_EXCL` 和 `0600` 创建文件；终端只显示路径、到期日，不输出链接。
- [x] 创建仅 workflow_dispatch 的演示 workflow：确认参数、demo 屏幕约束、串行 Job、9 分钟内部预算、10 分钟外部超时、完整生成发布。
- [x] 使用经核实的 Actions 固定 commit；Secrets 仅注入需要上传的步骤，不生成公开图片 artifact。

执行：`python -m unittest discover -s tests -p 'test_cli.py' -v`，CLI `--help` 和无配置失败检查，工作流静态检查。

## 任务 5：Kindle 同步与控制

- [x] 用 Pillow 生成真实有效 PNG 替换旧的“文件头+文本”夹具；先为 --once、HTTP 状态、错误尺寸、启动重绘和保存失败增加失败测试。
- [x] 提取设备脚本共用的 `common.sh`：配置、进程身份、状态读取和诊断；PNG 头校验及日志/状态写入保留在 `run.sh`。不引入 Python 或 bash 专用语法。
- [x] `run.sh` 保留默认循环，增加 --once；HTTPS 配置、e/到期日一致性、依赖、空间、锁和原屏保值检查。
- [x] 循环启动先显示缓存，再立即下载；每轮结束 sleep INTERVAL，失败继续循环；只接受 200，有限重试，先显示再 rename，失败恢复。
- [x] 前台处理 INT/TERM/HUP，后台明确仅 TERM 清理并忽略 INT/HUP；清理子进程、恢复旧屏保值。恢复失败保留原值和失败标记、非零退出；强杀残留锁不自动删除，身份不能确认时停止控制操作。
- [x] `control.sh start/status/stop` 验证 PID、启动标识与命令路径；不得用 PID 文件盲目杀进程。
- [x] state 原子写，日志 128 KiB 轮转且保留一份；状态和日志输出不包含 URL 或签名。
- [x] 新增缓存启动、锁竞争、PID 复用、curl 停止、FBInk/rename/日志故障、无旧图和重复刷新测试。

执行：`python -m unittest discover -s tests -p 'test_device.py' -v`；`sh -n kindle/run.sh`、`sh -n kindle/common.sh`、`sh -n kindle/control.sh`。模拟命令验证文件结果与调用顺序。

## 任务 6：集成、审查与文档

- [x] 运行全套 `python -m unittest discover -s tests -v`，修复所有回归。
- [x] 用 preview 生成实际 PNG，查看尺寸、中文显示和发布元数据；原有显示布局保持一致。
- [x] 独立规格审查：按设计第 9 节逐项对照；再独立质量审查，修复重要问题并重跑受影响检查。
- [x] 同步文档：已实现的本地代码与未验证的真实 Kodo/Runner/PW3 分开描述；记录上传入口、签名维护、运行管理命令、生产调度启用条件。
- [x] 更新本计划勾选和验证结果，检查 Markdown 本地链接、`git diff --check`，创建本地实现提交。
- [x] 真实部署需要 Bucket、发布凭据、HTTPS 域名、Runner readiness 和设备访问；无这些条件时不执行真实发布，不把模拟验证写成实机完成。

## 完成记录

2026-10-25 本地实现完成，分支 `codex/kodo-kindle-delivery`。设计先提交为 `1632f89`，计划和第一阶段图片/发布状态机提交为 `7e4f250`；后续集成实现另作本地提交。用户已授权设计推送 master，但 GitHub 返回 403（无仓库写入权限），因此尚未远端发布。

| 检查 | 实际结果 |
| --- | --- |
| 完整回归 `PYTHONPATH=tests .venv/bin/python -m unittest discover -s tests -v` | 101 项通过，75.769 秒；31 设备、19 发布、16 Kodo/HTTP、8 预览、5 CLI、8 CalDAV、1 日历、3 渲染、13 天气 |
| Shell 语法 | run.sh、common.sh、control.sh、config.example.sh 全部通过 |
| 工作流 | Ruby YAML 静态解析通过；未在真实 Runner 执行 |
| 文档与差异 | 6 份 Markdown 本地链接无缺失，git diff --check 通过 |
| 实际 PNG | 已生成并查看，1072×1448、L 模式、16 灰阶、29154 字节；中文及生成时间正常 |
| 独立评审 | 发布、Kodo/HTTP/CLI/工作流、设备规格与质量复审通过；重要问题均已补回归修复 |

评审修复包含 PNG 实际位深与 IEND CRC、latest 重试前并发复查、不确定写入确认字段、HTTP 中途断流重试、恢复探测时间限制、后台信号约定以及屏保恢复失败持久诊断。恢复探测限 5 秒，上传预留最终读回 30 秒，阶段限制不会延长全局截止时间。

设备后台使用 TERM 停止，明确忽略 INT/HUP；前台仍处理可捕获的 INT/HUP/TERM。屏保恢复失败保留 `.running/powerd.previous` 与失败标记，非零退出且控制命令可诊断；此项是依据 POSIX 行为对初稿信号约定的细化。

## 外部验收待办（未完成）

- [ ] 用有写入权限的 GitHub 身份推送已授权的设计提交；实现分支的远端发布另按用户指示执行。
- [ ] 配置真实私有 Bucket、发布身份、区域上传入口、长期 HTTPS 下载域名及历史生命周期。
- [ ] 验证同一设备签名 URL 连续两次发布的可见性、30 天签名期限和鉴权/缓存行为。
- [ ] 确认七牛 Runner readiness，真实执行手动 demo 工作流并验证读回。
- [ ] PW3 安装与实测：TLS/CA、curl 无 Content-Length 限量、FBInk、进程身份、信号、文件替换、断网和屏保恢复。
- [ ] 接入真实钉钉来源和自动天气后再启用生产 schedule；完成 48–72 小时连续运行验收。

本地测试使用假凭据、内存对象存储、localhost HTTP 及设备命令替身。没有真实发布或硬件验收记录，不将模拟通过写成已上线。
