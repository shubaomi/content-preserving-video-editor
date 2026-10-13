# FIX-02：保留词级时间的语义分屏接入

授权：用户批准修正三个实现缺口，验证后继续两条既定短样片。方案、词序、EDL、音频与默认安全门不变。

## 最小合同

`edit/video-use/caption-semantic-groups.json` 为可选 video-use owner 输入，不自动推断句意。schema_version=1、kind=semantic_caption_groups、owner=video-use；input_hashes 绑定 edl、transcripts（source→SHA）、corrections（SHA 或 null），mapped_words_sha256 绑定更正前的精确映射词。groups 按完整词序逐屏列 id、semantic_group_id、word_occurrence_ids、rationale。不得携带显示文案或自定义时间。每屏对应一个语义组；同一组可连续多屏。词实例必须恰好覆盖一次，不能越 EDL 段或切开更正词跨度。宽度字符目标与时长上限在此路径为硬检查，不再允许旧启发式多加8字/6秒。

新的 schema_version=2、kind=word_span_corrections、owner=video-use 更正格式按精确 word_occurrence_ids、from、to、evidence 定位；input_hashes 绑定 edl 与 transcripts。仅词汇/拼写修正，由 owner 单独审查依据；不能用它给整句添加标点以操纵分屏。一个替换词保留原跨度首尾时间以及全部原词实例ID，不按替换字数均分时间。未改词逐字段保留。旧更正与旧分屏路线继续兼容，但新语义分组路线拒绝使用旧的插值更正格式。

Director 在 video_use_timeline 自动发现该 owner sidecar，将它传入桥并绑定阶段工件；增加、修改、删除 sidecar 或更正文件均重新验证字幕阶段及其下游，不重跑 ASR。缺失新 sidecar时旧工程保持原行为，不偷偷启用新规则。新映射/更正/分屏哈希不一致、漏词、重复、乱序、跨段、过长均阻断，而非降级旧启发式。

## 验收与回滚

先复现：快语速把“的工艺制作的”和“轻轻一放”合并，以及旧软上限放任过长字幕。回归：精确分屏、无词损失/重排、原时间不变、替换跨度无插值、陈旧哈希拒绝、分组不拆更正词、旧路径兼容、Director新增/修改/删除失效。

之后检查真实A/B字幕文本与实际帧：以单行短屏为主，不能靠缩小字号通过；自动检查不声称语义/听感/审美获用户通过。回滚为保留新候选并恢复原配置/owner输入，不覆盖原转录或父EDL；已有成片与工程不改。

## 真实恢复链修正（2026-10-13）

真人隔离工程复现：时间轴阶段与 HyperFrames 准备阶段调用相同投影生成函数，无条件重写同字节 timeline-projection.json。严格工件回执包含 mtime，因此下一次恢复会从字幕时间轴反复失效、重建证据，再使语义哈希过期。修复只让 prepare_projection 在已完成授权/输入校验并重算结果后，对完全相同的对象不重写；对象改变仍写入。没有放宽哈希或 mtime 门禁，没有手改状态或文件时间。新增回归覆盖相同输入不写且保留字节/mtime、FPS 改变仍写入；真实工程已正常越过循环。

## 已批准字幕区的像素布局接入

真实样片复现：ASS 按源视频分辨率而不是样片画布生成，并固定较大字号和十三字换行，使已批准的独立字幕区失效。sample 现在优先使用 storyboard 的有效整数 width/height；旧无画布字段路径保留源尺寸。显式 `editing.caption_treatment.layout` 必须且仅包含 `font_size_px`、`margin_x_px`、`margin_bottom_px`（整数像素）与 `single_line`（布尔）。不提供时旧默认、旧样式与分行不变；不自动为旧项目启用。

单行模式禁止权威文本换行，采用最大强调缩放和描边余量的保守 em 宽度检查，超界报错，不缩字、不丢字、不改词和时间。ASS 使用 WrapStyle 2；真实字体、最终字幕位置和独立字幕区仍需实际帧检查。此布局兑现已批准样片的字号与留白，不是新的视觉方向。测试先复现失败，再验证显式单行、默认兼容、溢出/非法值拒绝及真实样片画布。

另修复 caption_only 决定被字幕消费者过滤的问题：只让已批准且在权威字幕中逐字出现的强调词进入原有样式；source/quiet 仍排除。采用 Director 原语义 brief，不把动效 source_only 投影的空 copy 当成字幕强调权威。新增先红后绿回归；不改变词、时间、字号上限或文字批准条件。
