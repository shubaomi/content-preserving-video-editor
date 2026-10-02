# 开源视频项目研究与借鉴取舍

核查日期：2026-10-02。这是能力与方法研究，不是所有工具的生产验收。
没有复制第三方实现；链接描述的能力与本 Skill 已接入的能力分别记录。

| 项目与一手来源 | 可借鉴能力 | 本项目的选择 | 尚未证明 |
| --- | --- | --- | --- |
| [Hypit](https://github.com/hypit-ai/hypit)，源码 `e8f94006e1eed9b299448fe5bce6afa5646e2ba5`，npm 0.2.17 | 参考拆解、语义锚点、Source/Recipe/Run 分离、接受输出复用、Studio 可编辑参数 | 采用分析方法；独立安装；未来适配器先设计与短片验证 | 未接入 Director，未验证本机端到端生成和 Studio 修改后导出 |
| [FunClip](https://github.com/modelscope/FunClip) | 中文热词、按文字/说话人选段、全片与片段 SRT | 借鉴术语纠错和文字选段交互；继续由 video-use 持有原始词与 EDL | 未安装模型，未在本机做 ASR 准确率比较 |
| [Auto-Editor](https://github.com/WyattBlue/auto-editor) | 音量/运动分析、剪切边缘留量、多种 NLE 导出 | 将自动切点作为建议；原语义与留白策略仍是权威 | 未以它替换 EDL，未验证各编辑器导入 |
| [OpenCut](https://github.com/OpenCut-app/OpenCut) | 多轨时间轴、人机协同修改界面 | 参考操作方式，保留 editor-neutral 包 | 不推断 MCP、自动化 API 或草稿兼容；同名仓库必须按 owner 区分 |
| [OpenTimelineIO](https://opentimelineio.readthedocs.io/en/latest/) | 时间、轨道、片段与媒体引用的交换模型 | 复用现有 OTIO/权威时间轴路径，输出降级说明 | 时间轴交换不保证动效、字体、ASS 或剪映原生语义等价 |

## Hypit 的实际边界

官方源码和 [Quickstart](https://github.com/hypit-ai/hypit/blob/e8f94006e1eed9b299448fe5bce6afa5646e2ba5/docs/quickstart.md)
描述的是 Agent 驱动的可编辑视频生产系统。安装 Skill、安装 executable、
选择 Runtime Profile、准备浏览器/本地模型、连接生成服务是不同步骤。
不调用生成模型的内容编排可以独立存在，生成服务的账户和费用另算。
“一条命令/100 个变体/100M views”是宣传语，不是效果保证。

查阅的源码位置：`skills/hypit/references/creation/reference-video.md`、
`production/timing.md`、`playbooks/craft/captions.md`、
`environment/distribution.md`。关键方法已转化为本项目自己的
`reference-led-ip-direction.md`，没有照搬生成优先、替换表演或字幕双文本策略。

其 [LICENSE](https://github.com/hypit-ai/hypit/blob/e8f94006e1eed9b299448fe5bce6afa5646e2ba5/LICENSE)
是带附加条件的 Apache 2.0，涉及多租户服务、商业再分发和标识保留限制。
本次独立安装用于用户自己的工作；不将其源码、Skill 或依赖打包进本仓库。
未来对外 SaaS/商业打包需要重新核对许可，不能把“GitHub 公开”当作无限制许可。

## 现有能力不能重复建设

基线 `bcb426dac51a07dd94aaeddef7dea969509c2c70` 已有：

- `video_use_bridge.py`：词与 EDL 时间映射；`caption_treatment.py`：强调字幕。
- `editorial_promise.py`：承诺与证据闭合；`production_contract.py`：生产约束。
- `post_publish_metrics.py`：用户导出数据校验；`feedback_loop.py`：同一发布的多时点建议。
- `director_adapters.py`：适配器缓存与执行；现有 event cache 有单独等价性条件。
- `editable_delivery.py`、分层 NLE 与剪映适配器：可编辑兜底，真实剪映人工门仍单独保留。

因此缺口是 IP 策略/单集判断与这些现有模块的绑定、跨视频观察解释，以及
可选外部生产工具的显式接口，不是重新写一个字幕、渲染或数据平台。

## 采用顺序

1. 当前即可使用：参考分析、语义分屏人工审查、证据优先编排、最小变更与复用指引。
2. 待设计批准：IP 档案与单集 brief 合同、价值判断、proof map、平台包装、复盘账本。
3. 单独实验：Hypit 适配器与无付费短片 canary；通过后再讨论生成式改编。
4. 延后：批量变体、自动发布、自动调参、人物/声音替换、商业 SaaS。

优先衡量同一素材的字幕错误、有效解释、修改耗时和复用成本，再评审审美与
发布意愿。不以工具数量、动效数量、仓库 stars 或一次高播放作为验收。
