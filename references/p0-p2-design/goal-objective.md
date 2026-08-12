# Content-Preserving Video Editor P0-P2 Design Freeze Goal

请创建并执行一个长期 Goal：为
`E:\Projects\Skills\content-preserving-video-editor`
完成 P0、P1、P2 优化的设计冻结。

本阶段只允许进行源码审计、需求整理、架构设计、Schema 草案、测试设计和文档编写，不得实现正式功能、不得渲染长视频、不得修改上游 video-use、HyperFrames、Remotion、OpenCut、ChatCut 等项目，也暂不提交和推送 Git。保留所有既有修改，不覆盖无关文件。

目标是先把原始需求、工具边界、技术框架、实施顺序和验收标准固定下来，防止后续实现漂移。设计必须以用户此前发现的真实问题为来源，包括但不限于：

1. 动效语义不相关、关键词随机或重复。
2. 标注框、连接线和画面目标位置不准确。
3. 画面状态变化后动效仍停留在错误位置。
4. 动效数量过少或机械堆叠，不能辅助讲解。
5. 动效缺乏关键帧、速度曲线、层次、镜头感和合成质感。
6. 动效与背景颜色相近，出现可读性问题。
7. 动效音效单一、过小、缺失或被口播覆盖。
8. BGM、字幕、封面、IP 插图等阶段偶尔被旁路遗漏。
9. 默认只需要一个可跨平台发布的 universal MP4。
10. 保留原视频主体内容，不能为了节奏随意删除。
11. 横屏录屏、竖屏真人、本人视频和他人授权视频必须自适应。
12. 非本人视频不得使用 HongRun 真人、个人 IP、第一人称身份或个人片头片尾。
13. ChatCut、剪映、OpenChatCut、OTIO 等只能作为可选生成或人工精修出口，不能成为核心流程必需依赖。
14. 自动测试不能冒充真实审美、真人相似度和可发布性验收。

开始前完整读取并审计：

- 当前 `SKILL.md`。
- `director-architecture.md`。
- `config-schema.md`。
- `quality-gates.md`。
- `capability-roadmap.md`。
- `workflow-optimization-2026-08-08.md`。
- 当前 Director、Storyboard、HyperFrames、字幕、音频、封面、证据、QA、人工交接和测试代码。
- content-preserving-video-editor 实际调用的 video-use、HyperFrames、Remotion 等 Skill 规则。
- 当前 Git 分支、HEAD 和工作区状态。

需要生成以下设计资产，目录位置遵循当前仓库约定，建议集中放在 `references/p0-p2-design/`：

1. `requirements-traceability.md`
   - 给所有原始需求分配稳定的 RQ 编号。
   - 每条需求记录来源问题、目标效果、非目标、优先级、负责模块、配置、测试、样片证据和人工验收。
   - 任何实现项必须能追溯到至少一条真实需求。

2. `motion-quality-engine-v1.md`
   - 定义动效语义角色、目标绑定、画面状态检测、关键帧、速度曲线、运动阶段、镜头语言、遮罩、视差、模糊、光影、景深、动效音频和横竖屏适配。
   - 定义 HyperFrames 能力映射和工具边界。
   - 设计 12–16 个真正有视觉和运动差异的高级动效配方，但不得为了满足数量而制造无意义动效。
   - 明确禁止固定每 N 秒插入动效、随机关键词、字幕复述、无目标框选、未经验证的专有效果复制和随机模板轮换。

3. `p0-p2-implementation-plan.md`
   - 给出 P0、P1、P2 的依赖图、实施顺序、目标文件、测试先行步骤、迁移策略、缓存失效策略、回滚方式和预计验证成本。
   - P0 必须先完成 Motion Quality Engine、目标绑定、关键帧验收、创意审核和真实样片验证。
   - P1 只能建立在 P0 通过后。
   - P2 必须默认关闭并使用 feature flag，不能改变现有一键工作流默认行为。

4. `acceptance-matrix.md`
   - 区分自动验收、多模态审核和必须由用户决定的审美验收。
   - 定义横屏录屏和竖屏真人两个 30–90 秒真实 canary。
   - 定义与上一版并排比较、人工修正时间、语义正确率、几何正确率、字幕同步、音频可闻性和最终发布意愿。
   - Fixture、合成图片和结构化 JSON 不得替代真实视频证据。

5. `machine-contracts.md` 以及 Schema 草案
   至少定义：
   - `motion-design-contract`
   - `motion-recipe`
   - `target-binding`
   - `keyframe-receipt`
   - `creative-review`
   - `motion-audio-decision`
   - `real-project-validation`

6. `architecture-decisions.md`
   明确以下边界：
   - Director 负责决策、证据、治理和门禁。
   - video-use 负责媒体分析、转录和基础时间线。
   - HyperFrames 负责可寻址的高级动效实现和渲染。
   - FFmpeg 负责最终合成和媒体技术验收。
   - ChatCut、OpenChatCut、剪映草稿、OTIO 只作为可选交接。
   - 不复制或修改上游源码，除非存在独立最小复现证明是上游缺陷。

7. `risk-and-cost-ledger.md`
   - 记录技术风险、审美风险、兼容风险、许可证边界、云端隐私、GPU/Token/渲染成本和失败回退。
   - 说明哪些设计可能是伪需求或会造成 Goodhart，例如强制动效密度、每个动效不同音效和自动审美总分。

设计过程中必须：

- 每完成一个可验证文档就报告结果。
- 不长时间只思考而没有读取源码或生成可审查产物。
- 对现有能力区分 `documented`、`director_integrated`、`fixture_validated`、`real_project_validated` 和 `production_default`。
- 不把计划能力描述成已经实现。
- 对冲突需求给出推荐结论，不能把选择留成模糊描述。
- 用正例、反例和边界案例说明每项合同。
- 设计完成后进行一次架构、创意、审美、实用性、易用性和测试可实现性的综合复核。
- 修复设计评审发现的 BLOCKER/HIGH 问题。

本阶段完成条件：

- 所有设计文档相互一致。
- 每条 P0–P2 实现项都能追溯到真实需求。
- 每条需求都有明确验收证据。
- 没有悬空的工具边界和伪完成状态。
- 输出待用户决定的问题清单。
- 生成 `design-freeze-candidate.json`，但在用户明确批准前不得标记为 `approved`。
- 最终只报告设计文件、主要决策、待确认事项和下一阶段实现 Goal 所需输入。
- 不实现正式代码，不提交，不推送。
