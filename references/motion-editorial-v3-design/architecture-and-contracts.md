# 架构、机器合同、状态与回滚

## A. 边界与兼容

仍为 19 阶段。新功能在 `semantic_brief` 中提出 hook/shot 意图，在 `production_contract` 与后续步骤绑定投影；不增加另一个自由剪辑器。

新项目 schema 15 的候选配置（正式实施时添加，当前不写入用户 YAML）：

```yaml
motion_editorial:
  enabled: false
  version: 1
  direction: null  # authentic_product_editorial | professional_software_demo
  opening: propose_only  # propose_only | approved_duplicate
  design_approval_path: null
  hook_approval_path: null
```

关闭时不读取新 sidecars，不产生新文件，不改变旧品牌或开场；旧 v1–v14 仅内存迁移为 disabled。启用必须 motion_quality.enabled=true，版本/字段严格封闭。`authentic_product_editorial` 在本轮只允许 self+真人实物；`professional_software_demo` 允许有权利依据的 screen/product-demo，第三方不使用 HongRun 身份资产。

同一项目不能同时启用旧 `portrait_brand` 生成和新组件生成，避免两套覆盖；旧方向和合同只读保存用于 baseline，颜色可通过明确快照沿用，不能自动继承旧审美批准。关闭 `motion_editorial` 恢复旧配置快照是回滚，不删除新产物。普通 v14 项目在功能关闭时输出保持兼容。

不替换 video-use、HyperFrames、字幕桥和 NLE 的既有专业归属。不安装 Lottie/Motion Canvas/Remotion 新版本；先用已可用 HyperFrames 的确定性 2D 时间驱动实现，真正缺能力再作为独立变更申请。

## B. 钩子闭环与有限状态

1. 复用源文件/逐词转录/初始 EDL/帧证据；完整理解源内容，补读候选前后语境。
2. `hook-plan` 状态：`unassessed → proposed | not_selected`。候选只能是真实源片段，默认 2–6 秒且独立完整；不强切长句凑时长。不适合则保留原开头并给具体证据，不自动补录或配音。
3. 记录候选引用、短引文、上下文、承诺、兑现点、原画动作和拒绝原因。编辑分数若保留仅作标为推断的排序，不能成为硬质量通过值。
4. `proposed → approved` 必须当前精确方案的用户确认收据；本轮方向确认不满足。审批人/来源/批准对象哈希由现有审查机制验证，普通 JSON 布尔不授予权限。
5. video-use 按批准方案创建候选 EDL。只有复制预告，正文每个基线片段保持原次序、源区间和语速；移动/删减/变速走新设计和授权，不能借本功能自动执行。
6. 候选 EDL 校验通过才建立 `timeline-projection`；进入 `applied`。成片首段与接点实际检查通过后单独 `verified`。媒体变化为 stale，错误保留原件。

不能在 `semantic_brief` 内偷偷重写当前 video_use_timeline。实现使用隔离 variant 项目：parent refs 指向只读初始工程，hook 请求绑定初始 EDL 与精确批准；一次性派发 video-use 工件请求，执行后显式重新进入该 variant 的 video_use_timeline。旧项目状态不修改。variant 的语义阶段检测当前 request/EDL 哈希已处理后不再重复请求；EDL 不匹配时 action_required。由同一个输入版本触发的重建最多一次，防止 hook↔semantic 循环。

## C. 权威时间轴

保留三个不同坐标：`source time`、`baseline output time`、`variant output time`。所有时间为秒且有限非负；输出映射同时记录从真实媒体测得的有理数 fps。边界帧由统一 round-half-up 规则计算，字幕毫秒直接从词时间映射，不用整数帧反推词时间。

- 区间均半开 `[start,end)`，end>start；时间不得从文件名推断。
- 每个 EDL 段有稳定 `segment_id`。source word ID 不变；每次显示 ID 为 `segment_id:source_word_id`，不把重复词视为重复错误。
- 1x 映射公式：`output = segment.output_start + source - segment.source_start`。词跨新边界时拒绝候选，不能裁掉半字。
- 初始 EDL 自带合法间隙保留；新正文输出为初始输出+钩子插入总时长，不能错误压缩间隙。
- 正文实例数/源区间与基线一致；钩子新增实例显式 role=hook。钩子可跨多个原片片段仅在未来设计，本轮仅一个连续源片段。
- 新钩子→正文为硬切图像、30 ms 内边缘音频淡变；不重叠两句话，不黑屏凑时长，不变速。J/L-cut 和 shader 重叠不进入本轮运行时，以免引入第二种时长算法。
- EDL 是唯一权威。projection 无权改剪辑；它由 EDL、原词和批准生成，逐项重算。候选视频的总时长误差最多 1 输出帧，声音/字幕接点按既有严格规则复核。

源语义 brief 继续按源顺序不变。新 output semantic schema v4 在本功能内消费投影：输出事件为 `source_semantic_id@segment_id`，关联 source semantic ID、word occurrence IDs、原证据和新的输出窗口；按输出顺序排序，source time 允许在 hook→main 跳回。不修改旧 v1–v3 的单调/唯一性验证。字幕、SFX、目标状态、Promise 和 NLE 都引用明确实例；尚未支持实例映射的可选适配器标为 unavailable，不猜一个匹配。

## D. 机器合同

`schemas/editorial-motion.schema.json` 为 Draft 2020-12 合同草案；用 kind 区分四种 JSON。examples 仅合成结构测试，不是源证据或授权。所有对象封闭字段；事实文件用 path+SHA-256；运行时只接受绝对、存在、权利允许且位于授权根的本地文件，规范化后防目录穿越/Junction 越界。禁止 NaN/Infinity，严格解析 JSON。Schema 只做结构，以下关联全部需运行时验证。

| kind | 输出位置（variant work/director/motion-editorial/） | 写入者 | 关键约束 |
| --- | --- | --- | --- |
| hook_plan | hook-plan.json | Agent 内容阅读；Director 验证 | proposed 必须有候选；not_selected 必须具体原因；word/frame refs 真实且与窗口重合；正文兑现点保留 |
| timeline_projection | timeline-projection.json | Director 从 video-use EDL 派生 | source/transcript/EDL/approval current；片段和 occurrence 唯一、映射精确、复制与正文覆盖可验证 |
| shot_motion_plan | shot-motion-plan.json | 内容作者→编译器 | 一事件一个主要目的；原画/镜头与解释图形分开；可见文案清单、目标状态、四阶段与图像结构绑定 |
| short_validation_plan | short-validation-plan.json | Director | motion_style 不冒充 opening_edit；opening_edit 必须输出 0；两个样片目的用不同批准对象；无 full_render 权限 |

hook_plan 不装 approval 字段以防自授权。timeline_projection 中 approval_ref 只引用外部经过权威校验的收据。收据授权 sample 范围不授权 full；失效输入包括 source/transcript/base EDL/plan 精确字节。

shot plan 中镜头 crop 用归一化 source frame 坐标，`box` 的 x+w/y+h<=1；overlay 用输出坐标且由现有 layout/target-binding owner 约束。每个事件声明 source/target-free，两者分别验证；target-free 文字不能伪称跟踪产品。阶段时间均 event-local，顺序 entrance≤explain≤hold≤exit≤duration，最终 clean exit。无图形的 source/quiet 决定不要求捏造动画。

`inputs` 中每个 id 唯一；所有 *_ref、target_binding_ids、frame_refs 必须解析到本合同相应角色的输入。`source/quiet/caption_only` 必须 source_crop=null；取景变化属于 shot。素材、字体、声音/目标引用也须当前文件哈希，asset_ref 不能是任意网络地址。各方向 recipe 前缀限定 A 或 B；未知家族、重复 instance ID、混入无关语义/可见文案、缺四阶段或阶段乱序均拒绝。

精确钩子批准复用已有人工决定原则，新增 hook approval 记录至少绑定：kind=hook_excerpt、原用户消息/操作者、hook-plan/source/transcript/base-EDL 哈希、candidate_id、授权 scope=short_preview、时间。记录器由明确用户回应触发；模型不得替用户填写同意。记录不需要用户设置密钥，也不把本地 SHA-256 误称身份认证。相同收据不能升级为 full_render。

当前 schema 草案中 `inputs` 的必需 role 由 kind 的关联验证保证：hook=source/transcript/base_edl/evidence；projection=source/transcript/base_edl/candidate_edl/hook_plan/approval；shot=projection/semantic_brief/evidence/design；validation=plan/source/baseline/shot_plan。任一缺失阻塞；不能靠输入列表里放一份无关文件通过。

## E. 缓存、输出与安全

| 改动 | 保留 | 失效/重建 |
| --- | --- | --- |
| 仅颜色/字重/缓动 | 源/ASR/EDL/词/语义 | 受影响组件、镜头方案哈希、渲染与 QA/批准 |
| 修改字幕分屏 | 源/ASR/EDL/动效原画 | 字幕/最后合成/交接/审核 |
| 修改 hook 时段 | 源/ASR/基础证据 | 精确批准、variant EDL、实例/字幕/事件映射与下游 |
| 原片/词/上下文改变 | 仅未受影响且有当前哈希的资产 | 从最早事实阶段重验；旧批准不能转移 |
| 仅发布后指标 | 母版/工程/字幕 | 新学习候选，不自动改 Profile |

本轮不许用“缓存有效”当作复用已被拒绝的旧装饰效果的理由。旧渲染只作为 baseline。事件级渲染仅用既有等价性合同；不支持时最多重渲染当前短片，不假称局部重建。

新目录为原项目 `work/motion-editorial-v3/<run-id>/`；不覆盖 `ip-content-loop-v1-20261012`、旧 HyperFrames 工程、原视频或剪映草稿。每个文件清单带用途、来源、可编辑等级和 SHA-256。

## F. 回滚和失败

未通过审美：保留旧版和新候选，标 candidate rejected/superseded，不批量扩大组件实现。跟踪失败/低清放大/缺图/字体变更：显式降级为原画/可读字幕，需重验，不静默画框。缺少 precise hook approval：只做原时序风格片，不剪开头。无适合钩子：保留原开头与证据，不强做。

工程回滚选旧只读快照/新 variant，不覆盖后续人工编辑；代码回滚仅后续经授权的聚焦 commit 反向变更，不 hard reset。机器合同不兼容时停在 action_required。全局 Junction 只随正式获批实现同步，设计文档存在不改变当前运行行为。
