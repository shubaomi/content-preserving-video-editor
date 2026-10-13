# FIX03 — 软件原区注意力移交合同

状态：按 `execution-decision-package.md` 已批准的 FIX03 实施；不修改软件演示视觉方向。

## 问题与范围

旧 B02 只能顺序显示标签，不能兑现 B08 的指标板到趋势图区明暗引导、B10 的真实图例到真实曲线注意力移交。禁止以旧标签或 B01 替代后声称完成。新能力只在 B02 显式提供 `source_attention` 时启用，旧 `steps` payload 行为不变。

## 机器合同

- `source_attention.schema_version = 1`，`mode = dim_outside`，`dim_opacity` 在 (0, 0.24]。不改视频像素内容，只在真实区域外围画最多四块无文字、无边框、无发光的黑色透明遮罩。
- `source_box` 是未裁切源画面在输出中的实际矩形；`source_crop` 和 `overlay_box` 必须为 null，`approved_visible_copy` 必须为空，不允许同时携带旧 `steps`。
- `source_attention.steps` 至少两项，时间为事件局部秒数，顺序且不重叠，全部位于四阶段有效窗口内。每步指定 `binding_id`、`target_id`、`source_state_sha256`、归一化 `source_region` 与 `frame_ref`。区域必须等于真实绑定观测的 bbox，不允许凭效果设计扩大到其他 UI。
- 编译器校验当前语义实例的目标 ID 清单，调用既有 target-binding 校验，要求 resolved、当前证据哈希、精确实例/输出窗口、exit 策略、active window 覆盖每步。观测必须在源时间两端覆盖该步，并保持同一可见目标、状态与几何；状态变化或丢失不得跨越。每步帧必须是该绑定的真实观测且属于当前语义帧清单。
- schema 采用关闭字段合同；未知字段、混合旧/新模式、stale hash、错误实例、越界、跨状态、无源端覆盖均 fail closed。无新文案、数值、数据线或额外主题色。
- 最小语义合同补充：已有 `editorial_copy_policy=source_only` 投影规则不变，仍明确产生空 copy 清单；仅将 shot compiler 的 source_only 配方白名单扩展到携带有效 source_attention 的 B02。普通 B02 仍不能使用 source_only。storyboard 的 visible_copy_manifest 必须精确等于投影清单，不隐藏文字、不丢弃非空 approved copy，不修改 v4 投影代码。

## 绘制和证据

组件将归一化目标通过 `source_box` 映射到输出，生成 `data-source-attention-step` 和 `data-source-attention-mask` 标记的实际 painted DOM。清晰区域本身不绘制，外围遮罩限制在源画面内，字幕区不会被跨画面遮罩覆盖。以 GSAP 明确初末值和独立顺序步骤实现，结束与任意倒序 seek 后均回到无遮罩状态。不依赖回调或墙钟时间。

测试必须覆盖编译器实际输出到真实 Chromium/本地 GSAP 的 painted DOM、输出区域尺寸、文本为空、source transform 不变、前后/非单调 seek 一致、状态边界后无残留；此证据只称 synthetic_browser_real_gsap，不冒称真实样片审美通过。B 实际样片仍需 HyperFrames renderer evidence 和逐事件源帧/候选帧复核。

## 验证、迁移与回滚

先新增失败测试复现旧组件/编译器拒绝新模式，然后实现并回归旧 B01/B02/B03、shot compiler 与 Director integration。schema 文件是新合同定义，正式生产默认不变。回滚只移除本次新字段能力；不修改旧工程、字幕、EDL、已通过收据。B 样片使用已批准 `[1646,3070)/24` 源窗；Excel/Web 仅使用本次用户明确更正。不安装、不重跑 ASR、不长片、不发布。媒体工作不提交私有素材；代码交付遵循当前用户全局聚焦 Git 规则。

## 无新增文字的对比度适用性

真实采集发现：采集器只测 DOM 文字，有文字时返回实际对比度，无文字时返回 0；原校验把这类 0 当作文字对比不足。现在保留实际值 0，仅当批准 copy 为空、renderer 总文字与全部四相位文字均为空，并显式记录 `text_contrast_applicability={status:not_applicable,reason:no_added_text,non_text_readability:requires_separate_visual_review}` 时判为文字指标不适用。缺字段、任一相位有字、非零低对比仍沿用 4.5:1 门槛。截图、保护区、裁切、对位和原 UI/图形可读性均不豁免；不伪造对比度，也不冒充视觉审美通过。
