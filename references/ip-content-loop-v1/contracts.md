# 候选机器合同

`editorial-envelope.schema.json` 是设计期 Draft 2020-12 结构合同，不是当前
Director 已启用的验证器。所有产物使用同一封装并引用已有权威；禁止产生第二套
字幕时间或渲染时间轴。事实/推断分类按字段表达，不能一个总 `approved=true` 覆盖全部。

## 文件与字段语义

| kind / 文件 | 核心 payload | 消费方 |
| --- | --- | --- |
| strategy / strategy-snapshot.json | audience、promise、pillars、tone、boundaries、series_id | 单集编辑，只读共享来源 |
| episode / episode-brief.json | viewer_job、thesis、takeaway、proof_ids、cta、series_id | editorial_intent 投影 |
| readiness / content-readiness.json | recommendation、reasons、missing_evidence、automatic_mutation=false | 对话建议，不是渲染批准 |
| proof / proof-map.json | claim_id、claim、word_ids、event_ids、evidence、support | 现有语义/承诺验证 |
| platform / platform-package.json | platform、promise_ref、title、description、cover_copy、cta、master_ref | 发布材料，不调用平台 |
| learning / learning-candidates.json | observations、hypotheses、next_experiment、automatic_apply=false | 待用户选择，不修改 profile |

字符串事实用 `{value, basis, evidence_ids}`，basis 是 user_confirmed /
source_observed / editorial_inference / unknown；unknown 的 value 必须为 null。
user_confirmed 要引用当前用户记录，source_observed 要引用实际源证据，
editorial_inference 标清推断，不因通过结构校验升级事实。

## 跨合同校验（JSON Schema 之外必须实现）

1. 所有绑定路径是项目内文件或显式只读授权来源；重新计算 SHA-256，拒绝 stale。
2. episode 的 proof_ids 在 proof map 存在；proof word_ids/event_ids 在当前
   transcript/semantic brief 存在，word 顺序和窗口一致。
3. 生成图像不能作产品结果/真实 UI 操作/个人经历的 proof；缺证据时 support=missing。
4. 策略第三方身份不得引用 HongRun 私人第一人称证明或身份素材。
5. 将 audience/viewer_job/promise/proof/CTA/tone/prohibited_claims 映射到已有
   `editorial_intent`，由 `editorial_promise.py` 校验；不另造模糊匹配批准器。
6. platform 的 master_ref 指向同一已交付字节；platform 可以是不同文案，
   不能把同一个 MP4 复制成多个“不同版本”。包装不具备发布授权。
7. observations 每个 publication_id/platform/version/window 组合唯一，
   多快照归并为一次发布；记录 metric_definition、denominator、traffic_source。
   未知来源/口径/窗口的不做严格跨视频比较，只保留事实描述和缺口。
8. 测试一次变量，实验建议记录控制项和需要的观察；小样本标 insufficient，
   不以固定“播放量门槛”断言商业效果或因果。前版单发布规则保留兼容。
9. 无 observations 可返回 no_observations；不制造零数据当成实测 0。
10. 所有候选都不能写样片批准、生产默认、个人审美或自动偏好批准。

## 时间与修改

word_id 是语义身份，不以秒数匹配同名词。跨 source/output 通过 EDL 唯一投影；
同一句重复出现时需具体 word IDs。成片字幕和效果时间仍遵循现有帧/毫秒合同。
既有变更账本负责微调的 before/after 和批准。新侧层只关联，不发明另一套校正机制。

## 状态

draft → validated → pending_user_review（需要定位/主观选择时）；绑定变化 → stale。
learning 另有 no_observations / insufficient_evidence。validated 只说明结构和
事实引用可校验，不等于定位、审美、真实平台或转化效果被确认。
