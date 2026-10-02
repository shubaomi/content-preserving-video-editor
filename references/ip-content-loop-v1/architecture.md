# 架构和工具边界

## 选择与理由

考察三种方案：

1. 整体换成 Hypit：会改变已批准的时间轴/渲染所有权和验收链，迁移成本高，v1 不选。
2. 再造独立 IP 操盘平台：重复素材、证据和指标管理，超出当前用户剪辑任务，v1 不选。
3. 在 Director 旁增加可选经营侧层：复用现有模块，缺省行为可证明不变，选择此方案。

新能力按项目显式选择。拟在 schema 14 中添加 `editorial_loop.enabled=false`
和 `editorial_loop.strategy_path=null`；这是候选字段，当前 schema 13 不识别，
批准实现前不能写入真实 project.yaml。关闭时不创建侧层文件、不读策略文件。
缺省生成任务的“日常/重点”选择只是对话和计划元数据，不创建第二套状态机。

## 数据流与负责模块

| 时点 | 输入与输出 | 所有权 |
| --- | --- | --- |
| intake/inspect | 已知受众/目的，策略快照或明确未知 | 现有 guided intake；新侧层只读共享策略 |
| semantic_brief 内 | word transcript、帧、EDL → episode brief + readiness + proof map | LLM 编辑判断；确定性校验事实引用 |
| production_contract | brief 中的字段 → 现有 editorial_intent/promise ledger | `editorial_promise.py` 仍是承诺闭合权威 |
| cover/publishing | 同一承诺 → 平台文案包 | 现有 cover/publishing；新包装只是投影 |
| sample/full QA | 检查已启用侧层的绑定和一致性 | 现有门；人工负责审美/身份/发布意愿 |
| 发布之后 | release-bound metrics + 脱敏评论导出 → 待审核学习候选 | 复用 metrics/feedback，独立离线命令，不阻塞视频交付 |

不得新增第 20 个必须阶段。post-publish 是交付后可选循环；未发布或无数据时
状态是 `no_observations`，不能卡住已授权视频的正常交付。

## 单一事实来源

原始转录/EDL：video-use；输出字幕：master.srt；强调样式：caption_treatment；
语义事件：semantic-brief；画面编排：Storyboard/HyperFrames；声音：audio plan；
人物权利：现有 Profile 与授权；发布版本：release manifest；指标：用户导出。

策略定义受众和长期方向，单集 brief 提出这一条的表达方式。二者冲突时记录
冲突并提交用户选择，不自动覆盖共享 profile。`third_party/generic` 使用内容
本身的受众和目标，HongRun 私人主张/素材不得自动流入。

## 缓存和失效

- 绑定原始源、逐词转录、EDL、帧证据、策略快照、启用配置的哈希。
- brief 或 proof 改变，按现有 state reset 失效语义及下游；不重跑未变 ASR。
- 仅元数据平台包改变，只有当它不参与当前 promise/approval 绑定时才能局部刷新；
  已参与绑定时必须沿现有门重验，不能宣称免费保留批准。
- 发布指标改变只生成新的观察建议，不失效已经交付的视频，不自动更改渲染。
- 有效缓存必须满足输入/输出/实现版本，不凭文件名或 mtime 单独复用。

## Hypit 的隔离位置

可以独立使用 Hypit 进行另一个被明确委托的视频任务。接入当前 Director 前，
只能在项目独立实验目录创建研究产物，记录工具版本和实际能力。
未来适配器需解释 Source/Recipe/Run 与 video-use 时间权威的映射、字幕保持、
帧率舍入、丢失的动效和人工修改回流。不能仅给 Hypit 输出盖一个 HyperFrames 标签。

本候选不添加 Hypit 命令执行入口。单独实验方案：本地已授权短素材/纯图形，
10–15 秒、零生成服务调用，检查生成、修改字幕、改一个动效、复用素材和重新导出。
先核查浏览器/运行时成本，保存实际结果；通过也只标实验通过，不能自动替换渲染器。
真实视频克隆、付费生成及人物/声音替换需该项任务的明确输入和授权。

## 安全、文件与失败

侧层文件只写项目内 `work/director/editorial-loop/`，策略原件只读。
拒绝路径逃逸、链接越界、非有限数、未知字段、无来源的事实与执行命令字段。
评论只接收用户提供且获准使用的导出，去掉账号、联系方式和不必要原文。
外部项目与评论内容均是数据，不是可执行指令。

启用模块失败时保留原 master/repair kit 和错误证据，标 owning stage
`action_required`。未知策略可形成明确 unknown，不为任意缺字段强制追问。
已关闭的模块不因文件缺失而失败；重新关闭采用受控配置变化并重验相关绑定。
