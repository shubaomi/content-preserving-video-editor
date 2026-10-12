# 目标、非目标和需求追踪

## 唯一目标

在保留 content-preserving-video-editor 已有来源、逐词转录、EDL、语义证据、字幕、品牌/身份、权利、安全、可编辑交接及人工批准门的前提下，建立镜头优先的两类动效语言和真实高光前置闭环。先在现有真人耳机演示与第三方 BI 演示上以短片证明方向，再决定正式集成。解决装饰模板化、动作/证据不突出、开场仅有声明没有成片证据的问题。

质量目标是自然、清晰、有层次、有信息增益并值得继续看；不承诺留存、播放量、成交提升。没有发布数据时经营闭环保持 `no_observations`。

## 事实和裁决

- 基线 `main@0af6aa20ef664a20ffa3b886d3834af06394e971`；全局 Skill 为源码目录 Junction。
- 当前 project schema 14，19 阶段；video-use 拥有转录/剪切/时间轴，HyperFrames 拥有动效和全片合成，FFmpeg 只负责字幕/混音/编码等机械工作。
- `video_use_bridge.map_words_to_output` 当前保留 `source_word_id`，不输出段落实例 ID。复制同一原话时不能假设 source word ID 唯一等于一次显示。
- semantic schema v3 的 source/output 单调顺序和唯一事件语义不能直接承载前置重复：必须另建输出实例投影，不能默默放宽旧校验。
- 现有 hook audit 只读 segments；words-only 空测量缺陷已复现。关键词分值不是视觉观察。
- 两条旧样片起点分别为原片 33.52 秒和 20.92 秒；不能作为新成片开头证明。
- 新方向优先于旧样片的审美偏好，但旧文件/批准记录原样保留。第三方身份限制继续有效，不等于禁止所有有授权的编辑建议。
- 裁决顺序：本轮明确要求/之后明确批准 > 本轮已批准设计 > 未被替代的现有合同 > 当前源码/真实媒体 > 历史和外部参考。相冲突时暂停受影响动作，而不是猜测授权。

## 范围

在范围：钩子事实测量修复、证据候选、输出实例映射、镜头计划、两类非装饰型组件、同素材对照、样片用途区分、编辑交接和失效依赖。复用源转录，不重做 ASR，不生成虚假产品细节，不新增声音/人像克隆。

不在范围：第三套 C 动态排版默认风格、全面换渲染引擎、Hypit 自动适配器、Lottie/WebGL/3D 新运行时安装、付费/云模型、长视频、自动发布、剪映 APP 操作、Production Default 提升、商业效果实验。

## 追踪表

| ID | 原始问题/约束 | 设计决策 | 计划模块（现有/新增） | 测试/证据 |
| --- | --- | --- | --- | --- |
| ME-01 | 钩子检查与真实画面脱节 | words 为事实优先；无视觉证据为 unknown，不以关键词给视觉分 | audit_hook_pacing.py；hook_editorial.py（新增） | T01–T03；hook-plan/source refs |
| ME-02 | 高光没有进入开头 | 复制短预告、正文保留；精确窗口批准；video-use 写隔离 EDL | director.py、video_use_bridge.py；editorial_projection.py（新增） | T04–T08；首帧/切点/输出映射 |
| ME-03 | 动效未辅助真实演示 | 原画动作和镜头为先；每个处理有 viewer task、焦点、信息增益 | semantic/production_contract；shot_plan.py（新增） | T09/T10；真实动作/目标连续帧 |
| ME-04 | 圆环/光束/标签同质化 | 两类结构独立；内容、构图、动作分开；禁止默认装饰 | 新 versioned components/recipe registry，现有 MQE 适配 | T11/T12；对齐旧/新短片和四阶段图 |
| ME-05 | 中段样片冒充开头验证 | 区分 motion_style、opening_edit、delivery_sample | Director/sample review/QA | T13；opening_edit 从候选输出 0 秒开始 |
| ME-06 | 修一次又全重做 | 内容哈希缓存与明确失效矩阵；旧项目不改 | project_config、director_adapters | T14/T15；缓存执行日志 |
| ME-07 | 烧录后难改 | SRT/ASS/无新增字幕底片/源工程保留，NLE 降级说明 | editable_delivery、现有 NLE 模块 | T16；交接清单+哈希 |
| ME-08 | 测试通过不等于好看 | 方向、技术、具体剪辑、审美、发布分开批准 | preview/Golden/receipt | T17/T18；用户真实决定 |
| ME-09 | AI 和重渲染成本 | 两个 10–15 秒新方向先验证；不装新引擎不付费 | provider/budget与短片计划 | T19；秒数/次数/执行收据 |
| ME-10 | 多个新时间轴互相漂移 | 投影仅由当前 EDL 生成；源语义不改，实例克隆可审计 | projection/semantic schema v4 分支 | T06/T07/T20；无歧义 occurrence IDs |

没有追踪键的新增功能不得在实施时顺便加入。
