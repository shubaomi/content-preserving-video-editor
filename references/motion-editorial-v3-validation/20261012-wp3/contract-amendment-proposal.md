# ME-AMEND-01：无高光重排的正式时间轴分支

状态：提案，待用户批准。WP3 授权已经收到；本提案不撤销授权，但不允许实现时静默修改冻结机器合同。

## 已确认事实

1. 用户已批准两个短片方向及 WP3 正式集成，未批准任何具体高光源窗口。
2. 冻结 `architecture-and-contracts.md` 允许 `opening=propose_only`；无合适高光或未获精确批准时保持原时序。
3. 同文件 D 节与冻结 schema 要求 `shot_motion_plan.projection_ref` 指向投影，投影必须有 `approval_ref`、hook plan 和 approval 输入角色。`approval_ref` 明确是精确高光批准，不是风格批准。
4. WP0 `contracts.py` 对投影的 required roles 包含 hook_plan/approval，`validate_hook_authority` 进一步要求 proposed plan 和恰好一个匹配的 hook。
5. WP0 README 已如实记载：WP2 使用非权威 source-window map，未通过正式投影合同。这个隔离例外不能直接用于生产链路。

本轮只读复现：从冻结 timeline_projection 合成例子删除 `approval_ref`，Draft202012Validator 返回 invalid，具体错误为 `'approval_ref' is a required property`。这证明 schema 没有无高光批准分支；不证明实际媒体通过任何门。

## 问题与收益

若原样接入，会让普通“只换动效”的视频也被迫等待高光批准，或诱使调用方制造虚假的批准。需要为原时序定义严格身份映射；它不增加新剪辑能力，只补齐已经承诺的正常使用路径。

## 推荐的最小修正

保持历史冻结文件与哈希不变，新建有版本的运行时合同，显式区分：

- `preserve_order`：读取当前 video-use EDL，投影片段必须逐段与原 EDL 相同（源、范围、语速、顺序、输出位置、间隙和总时长）；所有 role=body，禁止新增/删除/重复/前移；不允许 hook approval 字段，不要求高光批准。词实例仍由 segment_id + source_word_id 唯一派生。风格设计/样片批准仍在各自门检查，不能凭此启用未获批风格。
- `approved_duplicate`：保持原精确高光审批规则；只允许一个连续、完整词边界的真实片段复制到前面，正文和间隙不变；精确 source/transcript/base EDL/plan/候选窗口绑定、用户身份来源和 short_preview 范围校验保持严格。

下游 shot、字幕、SFX、目标、Promise 和 NLE 消费统一的只读输出实例映射，并通过明确 mode 区分。不得把 preserve_order 映射拿去通过 opening_edit 门；opening_edit 必须真实获批前置且输出从 0 秒开始。

`unassessed` / `proposed` / `not_selected` 的高光计划保持编辑建议。没有精确批准时可走 preserve_order，不可复制任何源片段。缺少源/EDL/语义/目标证据仍阻塞相关工作，不因新增分支降低安全门。

## 不改变项

- 两个已批准视觉方向、19 阶段、video-use 时间权威、HyperFrames 动效归属。
- 默认关闭、旧项目只做内存迁移、原工程/历史样片/批准不可覆盖。
- 无具体高光批准不得重排；不进入 WP4，不渲染完整视频，不发布、不提升 production_default。
- 人工审美、完整听审、剪映真实可编辑性不由自动测试替代。
- 本次补充不赋予更大预算、云调用、安装或新工具授权。

## 实施与验收（批准后）

1. 增量合同与正反例；版本化迁移仅在内存，旧冻结对象拒绝缺失批准的规则保持可回放。
2. preserve_order 必须拒绝任何篡改：插入/删除/换序/变速/重复、间隙压缩、时长变化、词跨界、混入 hook/approval。
3. approved_duplicate 必须继续拒绝缺失/伪造/漂移/范围升级的批准；原文/正文保留和重复实例测试继续运行。
4. Director 可独立运行新风格且保持原 EDL；缓存只重建受影响下游；disabled 旧项目行为不变。
5. 样片、可编辑交接与开场门区分；合成链路可测试，但真实开场效果仍留 WP4。
6. 完成 WP3 原计划的组件、投影、Director、输出语义、NLE、缓存、回归、文档与聚焦 Git 交付，不把这个补充单独当作 WP3 完成。

## 替代方案与代价

- 推荐：采用上述严格分支，兑现只改风格也能执行的原需求，增加少量分支合同与负例测试。
- 不推荐：把新动效仅限已获批高光的项目。会缩小原需求、增加每条视频不必要的确认和等待。
- 不接受：用风格批准填充 hook approval，或在运行时跳过 schema。会破坏授权边界及证据可信度。

## 一次性批准语

`批准 ME-AMEND-01：不前置高光时严格复用原时间轴，不要求高光批准；实际前置仍须精确批准。继续完成 WP3，不渲染完整视频。`

## 当前断点

- 仓库 `E:/Projects/Skills/content-preserving-video-editor`，main，HEAD `0af6aa20ef664a20ffa3b886d3834af06394e971`。
- 本轮仅新增授权收据及本补充提案；未修改生产代码、未渲染、未提交、未推送。
- 开始时已有未跟踪 experiments/、motion-editorial-v3-design/、motion-editorial-v3-validation/，均保留。
- 下一步：获得补充批准后按上面验收先写失败测试，再继续原 WP3 实施。无需重做两条风格样片。
