# WP0–WP2 隔离验证

批准对象为 `motion-editorial-v3-20261012`，原冻结清单保持不变，当前批准见 `approval-receipt.json`。

本目录保存本轮执行记录，不接入 Director、项目 schema、组件注册表或全局默认。正式集成和 Git 交付属于后续 WP3。本轮不渲染完整视频、不实际前插钩子。

执行顺序：隔离合同测试 → 真实帧/词边界与原型检查 → 两条各 10–15 秒 HyperFrames 风格验证 → 用户审美门。

样片位置：

- 真人：`E:/Projects/IP/HongRun/validation/content-preserving-video-editor-p0/canaries/portrait-product-intro-wp8/hongrun-physical-product-intro-p0-portrait/work/motion-editorial-v3/20261012-wp012/`
- 软件：`E:/Projects/IP/HongRun/videos/data-report-current/work/motion-editorial-v3/20261012-wp012/`

状态：两条短片已输出，停在 WP2 人工评审。完整听审和用户审美均待确认；不是 WP2 总验收通过，也没有进入 WP3。

## 直接查看

| 方向 | 新候选 | 同源基线 | 内容 |
| --- | --- | --- | --- |
| 真人产品 | [14 秒候选](E:/Projects/IP/HongRun/validation/content-preserving-video-editor-p0/canaries/portrait-product-intro-wp8/hongrun-physical-product-intro-p0-portrait/work/motion-editorial-v3/20261012-wp012/exports/candidate-captioned.mp4) | [原画基线](E:/Projects/IP/HongRun/validation/content-preserving-video-editor-p0/canaries/portrait-product-intro-wp8/hongrun-physical-product-intro-p0-portrait/work/motion-editorial-v3/20261012-wp012/exports/baseline-captioned.mp4) | 原片 50.05–64.03；真实放入耳机动作，轻微取景与字幕强调 |
| 软件演示 | [10.5 秒修订候选](E:/Projects/IP/HongRun/videos/data-report-current/work/motion-editorial-v3/20261012-wp012/revision-02/exports/landscape-candidate.mp4) | [原画基线](E:/Projects/IP/HongRun/videos/data-report-current/work/motion-editorial-v3/20261012-wp012/revision-02/exports/landscape-baseline.mp4) | 原片 83.70–94.20；入口定位、退出、真实展开和滚动 |

每类均另有未烧本次新增字幕的候选、SRT、ASS 与 HyperFrames 源工程 ZIP。它们不是剪映原生草稿；已经烧入 MP4 的取景/定位线不能变成剪映原生组件。按目录 README 可编辑源工程，或用无新增字幕视频加独立 SRT 微调。

## 自动验证与费用边界

38 项隔离合同测试、63 项既有回归通过。两个原型的 HyperFrames strict check 零错误/警告；实际导出完整解码与字幕抽帧核验已做。同一方向的 A/B 使用相同字幕、相同声音，音频哈希一致。

首次新动效计划共 24.48 秒，实际输出 24.50 秒（真人按帧网格为 14.00 秒）。最终抽帧发现软件弹窗开始后约 0.1–0.2 秒仍有旧定位退场，按已批准修订预算另建 `revision-02`，只提前退出时机。包括修订累计 35 秒、真人 1 次、软件 2 次，未超过 60 秒上限；软件没有剩余自动修订次数。v1 保留为有已知问题的历史候选，不再推荐评审。机械字幕/编码/QA 耗时各自记录，不称零成本。软件 render 日志另有稀疏关键帧警告，实际 252 帧已提取；不把 strict preflight 的零警告说成整个执行没有警告。

没有安装、重新 ASR、云/付费调用、实际高光前置、完整视频渲染、提交或推送。源码生产路径没有修改，全局 Skill 默认运行行为不变。

## 请一次性评审

分别回复 `真人：喜欢/需改/拒绝；软件：喜欢/需改/拒绝`，并给理由。请完整播放，检查自然度、动作是否清楚、质感和声音是否抢话。特别注意真人开头承接上句且没有安全前垫、细节取景时头部贴边；软件原片低清、末尾有很短的“然后”连接词。

这不是开场验证，也不宣称吸引力/留存提高。风格通过后仍需明确批准 WP3；真实高光前置需另行确认具体源窗口并授权 WP4。

详细证据层级见 `acceptance-status.md`、各工程 `technical-qa.json`/`evidence/technical-qa.json` 与 `review-boundaries.md`。冻结候选原状态/哈希不改，本次授权由独立 `approval-receipt.json` 记录。
