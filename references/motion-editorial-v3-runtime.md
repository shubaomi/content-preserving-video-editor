# 镜头优先动效 v3：正式集成合同

事实来源：冻结目录 `motion-editorial-v3-design/` 原字节、独立 WP3 审美/实施批准收据、
`motion-editorial-v3-validation/20261012-wp3/amendment-approval-receipt.json`。
本文件解释运行时适配，不改写历史候选状态或把测试当作真人验收。

## 开关与边界

project schema 15，默认 `motion_editorial.enabled=false`，仍为 19 阶段。
v1–v14 只在内存补 disabled；若旧版本显式请求新功能则要求先明确升级为15。
不覆盖旧 YAML，不读取关闭功能的 sidecar。

```yaml
motion_editorial:
  enabled: true
  version: 1
  direction: professional_software_demo
  opening: propose_only
  design_approval_path: E:/Projects/Skills/content-preserving-video-editor/references/motion-editorial-v3-validation/20261012-wp3/approval-receipt.json
  hook_approval_path: null
```

A=`authentic_product_editorial` 仅本人真人口播，实物动作必须有当前语义帧证据；
B=`professional_software_demo` 为软件录屏。沿用权利、第三方身份、保护区和品牌门。
必须开 motion_quality，不能同时开旧 portrait_brand。不新增外部运行时、付费调用或密钥。
风格批准收据绑定这一次真实批准的精确哈希；新风格不能用任意 `approved:true` 代替。

## ME-AMEND-01：不前置和实际前置是两条路径

`opening: propose_only` → `preserve_order`：从当前 EDL 派生，段落、空隙、速度、
字幕词和正文不变；不需要 hook plan/approval，不制造高光批准。

`opening: approved_duplicate` → `approved_duplicate`：只有明确批准的连续2–6秒真实
源片段可以复制到前面。精确批准绑定源文件、转录、基线 EDL、hook plan、候选ID，
授权仅 `short_preview`。正文原序、区间、速度、间隙整体平移，禁止吞半字。
修改任何事实输入后原批准不能复用。风格通过不等于高光窗口批准。

明确人工回应后才可运行 `scripts/motion_editorial_review.py` 的记录命令，参数为
parent-root/source/transcript/base-edl/hook-plan/candidate-id/operator/user-message/fps。
不得替用户编造回应。SHA 是完整性检查，不是身份认证。
记录器只生成收据及幂等 video-use 请求，不生成 EDL、不渲染。

video-use owner 用 `motion_editorial_variant.initialize_variant(request_path)` 初始化
请求精确指定的新目录。已有无关目录、Junction、输入漂移均拒绝；同请求恢复只读验证。
生成物仅初始化收据及 `work/director/motion-editorial/variant-authority.json`。
随后由 video-use 创建该 variant 的配置、转录缓存引用/同字节副本和候选 EDL，显式重新进入
video_use_timeline。不得改父工程。Director 每次重验精确请求根、初始化、收据及事实输入。
没有请求时不能在旧工程里自行前插；配置为 hook 但缺工件会 action_required。

## 时间与语义合同

`timeline-projection.json` 是当前 EDL 的派生视图，不是第二份可自由修改的时间轴。
v2 projection 明确 preserve_order / approved_duplicate；有理 fps、半开区间和 half-up 帧取整。
事件 `sourceID@segmentID`，词 `segmentID:wordID`。相同源词的 hook/body 是不同实例。
源 semantic v1–v3 校验不放宽；新输出语义 v4 内嵌原 brief/projection 并逐项重算。
目标、证明、封面证据均映射到明确实例；无法确定的跨段引用拒绝，不猜测。

纯镜头适配：新作者输入可在 schema3 render 事件明确设
`editorial_copy_policy: source_only`。源 `approved_visible_copy` 仍是既有真实语义标签，
仍必须通过旧校验；v4 保留 `source_approved_visible_copy`，派生显示清单为空。
仅 A01 或无字 B01 可消费；其他配方、未知策略、伪造派生字段拒绝。
这不修改字幕、原词、时间或已有源 brief；未声明时完全不变。

现有 Motion Quality 的1.0机器合同原样保留，显式1.1适配只允许输出实例ID中的 `@`。
必须同时通过 v4重算、当前文件、事件窗口、目标绑定和 renderer 检查，不能单凭版本号通关。

## 镜头计划与 HyperFrames

作者在 `work/director/motion-editorial/<scope>-shot-motion-plan.json` 写 schema2计划：
kind=shot_motion_plan，direction，projection_sha256、semantic_sha256（规范JSON哈希），
default_decorations=false，events 按 v4 实例次序逐一作决定。
每事件必填 instance_id/decision/recipe_id/viewer_task/information_gain/primary_focus/rationale、
source_crop、approved_visible_copy、phases、evidence、sound、output_start/end。
source/quiet/caption_only 不携带 recipe/crop/phases。shot/overlay 必须匹配语义 render 子集。
拒绝无信息装饰、按数量选配方或复用旧特效冒充新方向。

组件位于 `assets/motion-editorial-v3/`，复制到本次独立 HyperFrames 工程；不修改旧工程。
A01真实细节取景；A02有目标证据的局部标签；A03真实先后状态。
B01定位/操作/结果；B02同容器逐步证明；B03明确顺序原画对比回退。
不伪造同时存在的产品状态、界面数字或第二机位。

四阶段 entrance/explain/hold/exit 均为事件局部秒；退出不得越过 active_end。
crop为源归一化坐标，source_box/overlay_box为实测输出像素；缩放同时受真实源像素上限约束。
证据路径+SHA须当前且属于该语义实例引用的帧，包括每个B02步骤。
A02 target_binding_ref 须解析到该实例和精确窗口；失效则退回作者修正，不静默画框。
声效使用当前授权 asset_ref 或 explicit intentionally_silent+reason。

HyperFrames 消费 `editorial-renderer-payload.json`，覆盖通用视觉编排而非再选旧模板。
每事件 storyboard 声明 editorial_instance_id/editorial_recipe_id/editorial_plan_sha256
及既有 `visible_copy_manifest`（精确字符串数组，可空，不新增第二份文案权威）。模块 mount 返回事件局部暂停GSAP时间轴，
调用者按 output_start 挂载；传独占无既有transform/clip的源容器，不传 video 本体。
保留当前严格检查、关键帧、目标/字幕保护、字体、听审及preview/render parity门。

## 样片用途、缓存与交接

`sample-validation-plan.json` 明确 purpose/output_start/projection_sha256、
storyboard/candidate_media 两个当前文件引用、full_render_authorized=false。
composition.timeline_basis 必须 edl_output，source_start/source_end 表示EDL输出窗口。
实际 ffprobe 时长与窗口差不超过一帧。motion_style 为10–15秒；opening_edit为45–60秒且
必须实际从输出0开始并有 approved_duplicate；delivery_sample为45–90秒，不宣称开头验证。
WP4真实开头样片仍须另获精确窗口和执行批准，WP3不执行它。

只变动效配置或字幕样式时保留源、ASR、EDL及有效证据；已知设置变化从依赖阶段失效。
字幕设置因旧生产合同绑定整份配置，会重建轻量合同和下游QA；不重新执行源分析/ASR，
原画资产保留，渲染缓存仍必须逐项验哈希，不能声称任意字幕修改都免渲染。
不改变provider策略的配置刷新保留全部成本/预留/结果收据，存旧ledger快照及rebind记录，
绝不清零历史花费。未知配置变化保守重验，不扩大调用授权。

sample/full-instance-handoff.json 绑定实际投影/语义/字幕/音频/目标文件。
明确字幕词实例优先；旧字幕无法精确分配词时保留原文/时间，标partial/unavailable。
完整交付继续输出SRT、ASS、无新增字幕候选、HyperFrames工程；标准修复包可附
`editorial/instance-handoff.json`，校验源副本和嵌套依赖。可选NLE不能映射的字段如实说明，
不冒充剪映原生可编辑性验收。此轮不调用剪映APP。

回滚：关闭新开关并用原只读工程/配置；保留新候选，不删除历史或覆盖人工修改。
代码回滚走经授权的聚焦反向提交，不 hard reset。
技术集成、旧短片审美批准、新开场实际验收和 production_default 是独立证据层。

## 三个实现接缝修正（显式输入，旧工程兼容）

- **保护证据**：`analysis.protected_region_review` 的显式 manifest 支持 schema2
  `protected_region_evidence`；绑定源 SHA、display/旋转、normalized_display_v1、真实
  manual_visual_review/detector_observation 来源及首/中/末证据。按 EDL 每个源窗校验
  faces/hands 或 critical_ui 的完整覆盖；unknown/lost/缺口均暂停，不能被其他有效框覆盖。
  矩形是明确时间段的保守审核包络，不宣称连续自动跟踪。旧 schema1 absence 合同不变。
  同目录源帧在源/采样/帧哈希完全有效时可复用；保护结论与词证据重新计算。
  v2 已验证审阅帧可在 bundle.supplemental_frames 中提供离散语义证据；不改变
  representative_frames 采样/缓存/覆盖。语义请求与验证均读取两类帧，同路径时间或
  哈希冲突拒绝，相同重复帧保留原代表帧覆盖；补充帧自身不宣称连续覆盖。
- **字幕分屏**：video-use owner 可提供 `<video_use_dir>/caption-semantic-groups.json`，
  schema1 kind=semantic_caption_groups。每屏仅列词实例ID及语义组，不写第二份文本或时间。
  input_hashes 绑定 edl、transcripts、corrections，mapped_words_sha256 绑定更正前映射词。
  完整有序覆盖恰好一次；同语义组只能连续多屏；屏不得跨EDL段或拆开更正跨度。
  max_chars/max_duration 在此路径为硬上限，超限要求 owner 按语义重新分屏。
  更正文件仍位于 `<edit_dir>/transcripts/caption-corrections-v2.json`；新 schema2
  word_span_corrections 按精确词实例和 from/to/evidence 最小修正，保留原跨度不插值。
  分组路线拒绝旧插值式更正。sidecar新增/改动/删除使字幕及下游失效，ASR继续复用。
  已批准的独立字幕区可显式配置 caption_treatment.layout（font_size_px、margin_x_px、
  margin_bottom_px、single_line）；样片按实际 storyboard 画布生成，未配置保持旧默认。
  单行溢出拒绝而不自动缩字，最终字体/位置仍以真实渲染帧核对。
- **原区阅读动效**：B02 的可选 source_attention v1 是无文字的源区域明暗移交。
  源图不变，只降低焦点外区域的竞争；必须绑定真实target、状态、帧和活动窗，退出后无残留。
  仅有效该模式允许 B02 source_only；普通B02、v4投影权威与visible_copy一致性不放宽。
  旧steps标签payload不变，不得以标签冒充新原区效果。
  无新增文字时只将文字对比度标为显式不适用，须绑定实际四相位空文字测量；原 UI、
  图形及字幕的可读性、保护与对位检查仍保留，不能填造 4.5 数值。

具体合同与测试依据见 `motion-editorial-v3-validation/20261012-three-gap-fix/`。
这些是实现合同；测试通过不代表新短样片的真实动态对位、听感、审美或发布意愿通过。

## 显式短样片验收适配 QA-A QA-B QA-C

授权与回滚依据：`motion-editorial-v3-validation/20261013-qa-adapters/`。
仅补验收接缝；保留旧默认、原 EDL/镜头/字幕/音频，不授权全片或生产默认升级。

- QA-A：`source_reframe_evidence.py` 重新编译当前 A01 计划，绑定批准、源文件、
  投影、语义、真实 DOM 资源/矩阵、画布、字幕方案和保护证据。原 `crop_status=clipped`
  不改；只有批准源画背景取景通过专用检查。新增图形越界仍拒绝。保护证据 v2 可显式
  加入 `products`，默认必需类型不变；真实审核包络不冒充连续跟踪。
- QA-B：`runtime_animation_evidence.py` 在当前浏览器里采集真实 GSAP 动画树；
  要求事件独占 DOM、嵌套全局时间、正反 seek、实际动态属性挑战、四相位及工具哈希。
  `build_keyframe_receipts.py --runtime-animation-evidence` 显式消费；空的 CLI keyframes
  原文保留，运行时结果标为第二来源，不替写 CLI。`--hyperframes-cli` 可指定已安装固定
  Node CLI，回执记录实际命令，不下载、不更新依赖。
- QA-C：`shared_media_clock.py` 只处理已批准的同源静音多实例共享时钟。
  每次 seek 检查媒体身份、时钟、显隐与单路原音；只接受唯一已知重复发现警告。
  原 strict exit=1 和 warning 保留；独立 adaptation 通过不等于原 CLI strict 通过。
  动态依赖、外部样式/模块等不在此窄适配支持范围，不能当作通用依赖安全沙箱。
  `--shared-clock-adaptation` 重验所有引用；任何其他警告、失效证据或媒体变化均阻断。

顺序：实际四相位采集 → canonical keyframe receipts → 实际成片同帧 parity。
`rendered_phase_parity.py` 的显式 `same_frame_pixels_v1` 路线从指定 raw candidate
重新解码相同帧号，不以最佳偏移补偿，不将 Studio DOM 复制成成片测量。
软件保留原 ROI MAE≤3、任一通道差值>20的像素比例≤0.035；真人保留原 FFmpeg
RGB PNG SSIM All≥0.95。阈值方向须来自当前合同，不能由待验报告自行选择。
原几何、对位、保护和裁切验证继续由四相位回执执行；像素法不冒充渲染后 DOM。
消费者须提供当前工程/合同/源及确切 raw render 绑定；旧 Director 未提供该绑定时仍拒绝，
不得手改阶段完成。当前适配证据只证明此次短 canary 的技术结果，人工听审/审美仍待用户。
