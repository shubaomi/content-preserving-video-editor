# HongRun 个人 IP 内容经营闭环 v1 — 设计候选

状态：`pending_user_approval`。2026-10-02 基于恢复后的正式源码设计。
本轮已经落地的是源码恢复、独立 Hypit 安装、编辑工作指引与文档纠错。
本目录描述的自动运行时能力尚未实现，也未获得品牌定位或生产默认批准。

## 本轮设计决定

保留现有十九阶段 Director、video-use 时间轴、HyperFrames 全片渲染、
FFmpeg 合成、SRT/ASS/可编辑交接和全部人工门。新增可选的经营信息侧层，
连接已有 `editorial_intent`、promise ledger 和反馈模块。

Hypit 独立安装供显式调用；v1 只设计参考分析/隔离实验，不把它自动接成
替代全片 renderer。生成式人物、台词、声音和批量变体留待独立设计。

阅读顺序：

1. [需求与基线](requirements.md)
2. [架构与工具边界](architecture.md)
3. [机器合同](contracts.md)及[候选 JSON Schema](editorial-envelope.schema.json)
4. [实施、验收与回滚](implementation-and-acceptance.md)
5. [设计复审](review.md)
6. `design-freeze-candidate.json`：精确文档哈希与批准状态

恢复任务、上下文压缩或模型切换后，先完整读取本 README、需求、架构、
合同、实施验收文档和 candidate；按清单重新核对哈希，再继续。
批准仅覆盖 candidate 绑定的版本。任何方向/所有权/付费/默认行为变化需重新评审。

## 请求用户最终决定的事项

是否批准本候选，使下面五项进入实现：IP 策略侧层、单集内容判断、证据绑定、
平台包装连接、跨视频复盘候选。默认关闭、普通剪辑仍可直接使用。
批准设计不等于批准任何具体 IP 定位、样片审美、收费模型调用或发布行为。
Hypit 运行时接管全片不在这次批准范围内。
