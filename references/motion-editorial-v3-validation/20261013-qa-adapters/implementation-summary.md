# QA-A / QA-B / QA-C 短样片技术收尾

授权以 `user-approval.json` 和 `implementation-contract.md` 为准。保持原方案、原窗口、原素材、EDL、字幕及声音，不渲染完整视频。私有媒体/工程/截图留在原项目，不提交到 Skill 仓库。

## 实现与追踪

| 需求 | 实现 | 验证 |
| --- | --- | --- |
| QA-A 源取景与新增图形裁切分开 | source_reframe_evidence、实际 DOM/源矩阵采集、keyframe 消费端；保护证据 products 显式支持 | 16 单测；真人 9 个原 clipped 相位保持原值，专用验证实际通过 |
| QA-B 动态 GSAP 第二来源 | runtime_animation_evidence；保留真实 CLI keyframes 空结果，回执明确第二来源 | 24 单测、真实嵌套 timeline/timeScale 夹具；真人 8、软件 14 个实际拥有目标的正时长 tween |
| QA-C 非整帧起点源时钟 | shared_media_clock；精确意图、完整当前输入、逐 seek 状态和唯一告警适配 | 11 单测、真人 3348 次正反帧/边界；原 strict exit=1 保留，独立适配通过后 guarded 一次短片渲染 |
| 同帧成片证明 | rendered_phase_parity 显式像素路线；当前合同确定阈值族，调用端固定真实 raw 候选，实际 ffmpeg 重解码 | 21 单测；两条各 4 份 canonical keyframe receipt / 16 相位实际一致性通过 |

配套：保留旧默认分支，固定已安装 CLI 的真实命令可记录；工程清单仅排除明确的工具自产状态文件；媒体 seek 修正最后合法帧边界。scikit-image 显式固定为本机已验证的 0.26.0，无依赖安装或升级。

独立只读代码复核已关闭所报 HIGH：错帧尾部 clamp、弱产品证据、字幕安全区绑定、动态属性假挑战、媒体瞬时身份、依赖遗漏、待验报告自选更宽阈值及 raw 候选缺绑定。复核不代表人工审美或听审。

## 真实短片

### 真人

根目录 A：`E:/Projects/IP/HongRun/validation/content-preserving-video-editor-p0/canaries/portrait-product-intro-wp8/hongrun-physical-product-intro-p0-portrait/work/motion-editorial-v3/20261012-full-plan-sample`。

- 原源窗 33.52–88.97 秒；540×960 / 30 fps / 1664 帧，实际 55.466667 秒。没有改变已批准取景、标签、字幕或配音。
- 新 raw `A/v2.mp4`：`ad9e5af69774358fb76422a1b578f35fe2e1b6783e319e3b9ffb24b9926ea846`。
- 字幕版 `A/work/director/review-media/candidate-captioned.mp4`：`d818cf0e29abaa15ae6e66bad73cde513167436e79dad0b0061e64b993ba5bbf`。
- canonical 16 相位最低实际 FFmpeg SSIM All=0.966325；原 22 点回归最低 0.970864，均保留原 0.95 门槛。原故障第 410 帧由旧 0.914039 提升至 0.983610，最后合法第 1663 帧为 0.984355；无偏移择优。
- 21 屏最终字幕截图已逐屏目检单行，9 组重点词保留，原 ASS/SRT 哈希不变。raw/字幕版/基线三文件严格全解码通过；音频信号对齐 lag=0、相关性 0.999821，不是人工听审或主观口型同步批准。
- 证据：`A/qa/20261013-adapters/{source-reframe-phase-validation.json,runtime-animation.json,keyframe-receipts/,canonical-pixel-parity.json,qa-c-run2/}`，`A/qa/final-sample-clock-fix/report.json` 及 `audio-alignment.json`。
- 旧 `v.mp4`、失败证据及恢复快照保留。**`A/hyperframes/sample-preview.mp4` 仍是旧版本，不是本次交付**；使用上述新字幕版。

### 软件

根目录 B：`E:/Projects/IP/HongRun/videos/data-report-current/work/motion-editorial-v3/20261012-full-plan-sample`。

- 原源窗 [1646,3070)/24 fps；1280×720 / 1424 帧 / 59.333333 秒，软件文件完全复用，无重渲染。
- 字幕版 `B/exports/software-sample-candidate.mp4`：`baca5aafad5a78a288d5cfea4b6e0ccccd6d5d40ab7d5abbae4b53bf7eba3a4f`。
- raw `B/hyperframes/sample-preview.mp4`：`c8d9fc659747e7a6aeb48012881ea619451b4cdec5ad0290370fc4d5b20150a7`。
- 当前 16 同帧像素最大 ROI MAE=2.356490，任一通道差值>20的比例最大 0.002026576；原 3 / 0.035 阈值不变。退出无新增图形残留。Excel/Web 用户更正和 24 条单行字幕不改。
- 证据：`B/qa/20261013-canonical-software/{renderer-export.json,runtime-animation-evidence.json,keyframe-receipts/,canonical-pixel-parity.json,visual-review.md}`。

两份 canonical 像素报告均经新 `preview_render_parity.validate` 分支重验返回空错误；expected raw 路径来自已知实际候选，不从待验报告倒填。

## 保留的门禁与回滚

当前完成的是获批两条短 canary 的代码、真实 runtime/关键帧及成片技术验证；不等于人工听审、审美、发布意愿、剪映实际可编辑性或 production_default。

未手改 Director 阶段状态。旧 Director 消费端未提供新像素法所需的确切 raw-render 绑定，仍按设计 fail closed，不宣称它已经自动通关；本次独立 owner 验收明确提供实际候选路径。后续如需将此新路线作为通用生产编排，须单独处理权威候选映射和迁移，不能以本次短片技术通过自动升级默认。

没有重跑 ASR、改父级 EDL、云付费调用、新声效/BGM、剪映 APP 操作或外部发布。全局 Skill 是指向本仓库的 junction，无第二份源码复制。无关 `.serena/` 保留且不入提交。

回滚可关闭显式证据适配回到旧拒绝行为，复用旧短片及保留的工程输入；不删除历史、不 hard reset。自动回归的当前数量与源树绑定以同目录 `test-suite.json` / `test-suite.log` 为准。

## 最终验证

当前冻结源树全套 1253 项通过，0 失败、0 跳过，310.123 秒；原始日志和源码哈希收据同步到
`references/validation/test-suite-report.json` / `test-suite.log`，重新验证返回空错误。
六类型结构夹具与 current Golden 由实际工具刷新并重验；compileall、UTF-8 Skill 验证与
git diff --check 通过。独立复审单独执行 122 项定向测试，无未关闭 HIGH/CRITICAL。
这些本机结果不冒充尚未观察的 GitHub Actions 结果。
