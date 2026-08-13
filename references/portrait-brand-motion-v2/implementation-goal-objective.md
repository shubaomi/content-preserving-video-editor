# HongRun 个人口播品牌动效语言 v2：实施 Goal

## 权威输入

- 设计目标：`E:\Projects\Skills\content-preserving-video-editor\references\portrait-brand-motion-v2\goal-objective.md`
- 设计候选：`E:\Projects\Skills\content-preserving-video-editor\references\portrait-brand-motion-v2\design-freeze-candidate.json`
- 批准收据：`E:\Projects\Skills\content-preserving-video-editor\references\portrait-brand-motion-v2\design-freeze-approval.json`
- 实施计划：`E:\Projects\Skills\content-preserving-video-editor\references\portrait-brand-motion-v2\implementation-plan.md`

设计目标 SHA-256：
`593da5b11bc07c5188b24fd9e0a2e010472ec60c21677efb94c60a14674407d6`

设计候选 SHA-256：
`6ec215c87ae9b9b049f901429b09e92e774ab7ba692558eac7d79d85d91e657e`

## 用户批准

HongRun 于 `2026-08-12T05:26:09-07:00` 明确批准：

> 批准 portrait-brand-motion-v2 design-freeze-candidate，按照实施计划进入下一阶段实现

## 实施目标

严格按 `WP0 -> WP9` 的依赖门禁实施已冻结设计：

1. 项目 Schema v11、六类机器合同、迁移与默认关闭隔离；
2. HongRun 品牌 Profile v2、portrait eligibility 与能量图编译器；
3. PBM-01 至 PBM-08 原创 HyperFrames 个人口播配方及运行证据；
4. PBM-S01 至 PBM-S05 声音语言与现有音频生产/QA 集成；
5. 三方向同源 Style Reel 计划、评审面与用户专属品牌审美门；
6. 夹具、短合成媒体、回归、迁移、失败和安全验证；
7. 用户确认精确窗口后，生成三版 30–45 秒真实 Style Reel；
8. 用户选定后建立临时 Golden，再以第二个不同主题验证；
9. 依据真实证据更新文档、成熟度、全套收据、全局 Skill 同步和 Git 交付。

## 恢复规则

每次任务恢复、上下文压缩或模型切换后，必须先完整读取：

1. `goal-objective.md`
2. `design-freeze-candidate.json`
3. `design-freeze-approval.json`
4. `implementation-plan.md`
5. 本文件

随后读取最新实现 checkpoint、Git 状态和当前测试证据，从最后一个已通过的工作包门禁继续，禁止重做已经通过且输入哈希未变化的高成本步骤。

## 硬边界

- 不改变 video-use、HyperFrames、Remotion、OpenCut 或剪映上游源码，除非有独立最小复现并另获授权。
- 不用固定时间间隔、最低事件数、随机模板或 SFX 可用性创作语义事件。
- 不把产品卡片作为个人口播默认或静默回退。
- 不在精确 Style Reel 片段获用户确认前启动三版真实短渲染。
- 不在 Style Reel 品牌审美获用户明确批准前渲染完整视频。
- 不用自动测试、多模态建议或技术可发布性替代 HongRun 的品牌审美批准。
- 不上传、发布、部署或发起付费/云端调用，除非另有明确授权和现有治理收据。

## 当前起点

- Repository: `E:\Projects\Skills\content-preserving-video-editor`
- Branch: `main`
- HEAD at implementation approval: `1b74d8370d1fb985f21c7e8b6e5dfbb3aa5a42b4`
- Initial worktree: only `references/portrait-brand-motion-v2/` untracked
- First executable package: WP0 contracts, configuration, migration, and fail-closed tests
