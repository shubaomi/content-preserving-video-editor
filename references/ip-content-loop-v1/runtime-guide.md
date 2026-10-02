# 个人 IP 内容经营闭环 v1：使用与运行边界

冻结候选已由用户于 2026-10-02 批准，见 `design-freeze-approval.json`。
冻结 README/合同中的“待批准”是当时的历史状态，保留原字节以供哈希核验；
本文件说明实际运行方式。设计批准不代表具体人设、审美、商业效果或发布获批。

## 普通剪辑不增加填表负担

缺省配置为 `editorial_loop: {enabled: false, strategy_path: null}`。
关闭时不读取策略、不创建侧层文件、不增加阶段。旧 v1–v13 项目只在内存迁移
到 v14，不重写 YAML。只有用户选择内容经营闭环时，才配置 `enabled: true`。
日常/重点只影响可选实验，不减少现有质量门。

升级前已完成的 v13 生产合同含旧配置指纹，恢复时从 production_contract 起
重新验证合同及下游；已有分析、转录、EDL、语义阶段保持。既有样片/渲染批准
不会伪装成新合同批准，也不会因此自动渲染完整视频。这是一次版本迁移，
不是启用经营功能；旧 master 与可编辑交接包不会被删改。

Agent 复用已有受众、主题和目的。确实缺少关键信息时，在同一轮 intake 里问：
“主要想让谁看，看完记住什么或采取什么行动？也可以让我先提出建议。”
未知个人信息保持 unknown，不要求用户自己编 JSON，也不把编辑推断称为事实。

## 素材到单集的证据链

在 `work/director/semantic-brief.json` 已存在且证据通过后，Agent 阅读实际
逐词转录、EDL 和源帧，在项目的 `work/director/editorial-loop/` 编写：

| 文件 | 作用 |
| --- | --- |
| strategy-snapshot.json | 当前策略及身份；unknown 可以存在；不自动读取个人 Profile |
| episode-brief.json | 本期观点、观众任务、收获、唯一主要 CTA 和 proof IDs |
| content-readiness.json | 建议样片/继续/补录/拆分/暂缓，绝不自动删改素材或授权渲染 |
| proof-map.json | 主张对应的真实 word IDs、事件 IDs 和来源绑定 |

结构使用冻结的 `editorial-envelope.schema.json`。通过结构及引用校验后可将
status 写为 validated，但它不代表人工批准。缺失或不合法时，Director 输出
`editorial-request.json` 和现有 `action_required`，由 Agent 修正；只在需要
用户真实决策时询问用户。十九阶段不变，语义阶段不是另一个剪辑时间轴。

每份 binding 含 id、path、sha256、role。整个四文件包必须绑定当前 source、
transcript、edl、semantic_brief。帧只接受当前 evidence bundle 已登记且哈希
匹配的真实来源帧，不把生成插图当真实效果证明。事实 evidence_ids 必须在
该文件 bindings 中存在；user_confirmed 只可引用本目录 `user-record.json`：

```json
{"source":"explicit_user_message","message":"这里保存用户实际说过的确认，不能编造"}
```

不要直接保存上面占位示例。没有实际确认时使用 editorial_inference 或 unknown。
strategy_path 指向的共享策略只读；快照 payload 必须相同并绑定其哈希。
外部文件只允许显式指定的原视频及策略原件，不能凭策略内的路径递归获得读取权限。
外部额外证据须经授权放入本项目；不会遍历共享 Profile 或私人资产。
third_party/generic 的 strategy identity 必须与项目一致，不能借用 self 策略。

本期 thesis 必须对应已有 supported claim。每个 claim 绑定实际词序、事件和
源窗口；同词重复出现只能使用选定的词 ID。未提供受众/语气时使用中性表达，
不写入长期身份。与用户确认的策略承诺冲突时，需要用户实际确认新的单集主张。
确定性校验只能证明引用关系，主张是否真的被素材支持仍需要读听看审核。

## 包装、缓存与可编辑兜底

投影继续由 `editorial_promise.py` 管理，生产合同绑定四侧层及 promise ledger。
平台包复用现有 `publish-metadata.json`、封面计划和最终母版：
`editorial-loop/douyin/platform-package.json` 与
`editorial-loop/wechat_channels/platform-package.json`。
两份元数据引用同一 master 路径和哈希；不复制 MP4，不增加上传接口。
需要现有发布文案已生成/编辑并符合 promise；关闭 publishing 自动能力时，
Agent 可按现有文案合同提供文件，不能以默认临时标题通过检查。

策略、brief、proof、源词、EDL、帧或实现字节变化后，语义阶段及下游重验；
未变的转录/EDL不重跑。平台包及其输入属于交付阶段依赖。修改参与 promise
和批准绑定的文案，仍沿现有门重新验证。仅改配色沿现有缓存策略处理；本实现
不额外保证事件级局部渲染。发布后观察文件不属于视频生产缓存，不失效母版。

SRT、ASS、无新增烧录字幕候选、HyperFrames 源及现有 NLE 修复包继续交付。
此功能没有把烧录字幕变回可编辑字幕，也没有证明剪映真实可编辑性。

## 发布之后：可选离线复盘

先用已有 `post_publish_metrics.py` 导入用户提供的指标并绑定发布版本。
新模块复用 `feedback_loop` 的快照校验，不登录、抓取、发布或修改共享偏好。
在项目内创建 `learning-input.json`，例如未发布时：

```json
{"observations": []}
```

有数据时，每项填写 `snapshot`（项目内已导入快照路径）、`window_hours`
（实际发布时间到观察时间的小时数）、`metric_definition`（指标及口径版本）、
`denominator`（观察到的 views，未知用 null）、`traffic_source`（未知用 null）。
不能把未知窗口写成零；缺发布时间/观察时间的原始数据先补证，不进入比较。
可选 `comments` 仅接受用户提供的脱敏类别计数 JSON：
`{"categories":{"questions":3,"objections":1,"purchase_intent":0,"next_topics":2}}`。
原文、昵称、账号、联系方式字段被拒绝，不进入产物。

```powershell
python scripts/editorial_loop.py --project-root 'E:\项目目录' --learning-input learning-input.json
```

结果固定写入项目 `work/director/editorial-loop/learning-candidates.json`。
无快照为 no_observations；单条/小样本/不同口径窗口流量来源为
insufficient_evidence。同一发布多个时间点不算多个视频，同母版重复发布也不当作
独立视频。至少两次独立发布且不同视频字节、同平台/口径/窗口/流量来源，并满足
原有最低观察要求（200 views、24 小时），才生成 pending_user_review 的实验建议。
门槛仅控制是否值得人工检查，不能证明商业效果。实验只改开场表达，控制主题、
时长、来源、窗口；不自动执行，任何建议都不是因果结论。

## 回滚与未验证范围

关闭模块不会删除新侧层；保留它们用于诊断，受影响合同需沿现有门重验。
代码回滚使用升级前配置/状态副本或新项目，不覆盖用户后续编辑。
Hypit 仍是独立工具，未接入 Director；无新付费调用、完整视频渲染、发布、
production_default 提升。真实短片审美、剪映人工验收和商业效果仍单独待验证。
