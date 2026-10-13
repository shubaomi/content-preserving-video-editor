# 三个实现缺口修正与短样片交付记录

范围：用户批准 FIX-01/FIX-02/FIX-03，验证后继续两条已批准短样片；不改变方案，不渲染完整视频。代码交付按当前全局规则聚焦提交推送；私有媒体与样片工程留在原项目，不入此仓库。

## 已实现

| 追踪键 | 修正 | 实现与验证入口 |
| --- | --- | --- |
| FIX-01 | 显式 schema2 人工/检测保护证据、真实来源与覆盖门、当前哈希源帧缓存、已验证补充帧的语义白名单 | protected_region_evidence.py、evidence_acquisition.py、director.py；protected_region/evidence_frame_cache 回归 |
| FIX-02 | 精确词实例语义分屏、无插值最小词汇更正、sidecar 失效链、投影幂等恢复 | caption_semantic_groups.py、video_use_bridge.py、motion_editorial.py；caption_semantic_groups/motion_editorial_variant 回归 |
| FIX-02 | 已批准单行字幕区的显式像素布局、真实样片画布、caption_only 强调保留 | caption_treatment.py、project_config.py、director.py；caption_treatment、project_config_migration、Director 回归 |
| FIX-03 | B02 source_attention 原区明暗移交，真实目标/状态/窗口绑定，倒序 seek 与干净退出 | motion_editorial.py、professional-software-demo.js；真实 Chromium/本地 GSAP 回归 |
| FIX-03 | 无新增文字的文字对比度显式不适用，保留真实 0 与全部其他视觉门 | capture_hyperframes_runtime_evidence.py、keyframe_receipt.py；keyframe/capture 回归 |

默认旧工程行为保留；无新开关不自动迁移。原词、原时间、原 EDL 和源视频不改。字幕强调只使用已批准且逐字存在于权威字幕中的词。代码审阅含核心 Python、实际 JS/HTML、渲染/最终合成助手；审阅不等于用户审美批准。

## 两条真实短样片

- 真人：源 33.52–88.97 秒；30 fps 取整为 1664 帧/55.466667 秒。镜头推近由真实 HyperFrames 渲染，字幕最后合成。首次动态添加 video 未被编译器注册，实际 parity 失败；保留失败证据后改为静态媒体注册并执行必要技术重渲染，不声称首次成功。
  21 屏字幕实际帧单行，9 组已批准重点词强调。严格完整解码通过，音频信号估计零延迟（非听审）。最终同帧比较仍未通过：两次 20 相位检查最低 SSIM 0.917166 / 0.914039，未调整原阈值；因此真人只是可观看的未完成验收候选，不能称 preview/render parity 通过。
  有限诊断确认动作处实渲染 410 更接近预览 409，而普通画面 1500 同帧正常。隔离共享源时钟方案的 3352 项 DOM 门控/几何检查通过，但 strict 因 duplicate_media_discovery_risk 阻断，未启动新渲染；此方案与旧成片分开保留，不冒称已修复。
- 软件：源 [1646,3070) / 24 fps；1424 帧/59.333333 秒。真实原界面明暗移交；Excel/Web 使用用户明确更正。24 条单行字幕保留文本；ASS 百分秒量化与 SRT 的最大误差为 3 ms。完整解码、62 次运行态观察和 13 个同帧像素比较通过。
- 两条均是正文中段 delivery_sample，不验证全片开头、结尾、高光前置或完整视频。无重新 ASR、云调用、新声效/BGM、安装升级或发布。

## 证据层级与未完成项

自动回归以同目录 test-suite.json / test-suite.log 为准，绑定当前实现树；不能以旧测试计数冒充当前通过。当前 golden 与六类型结构夹具报告由实际评估器刷新，不手填 pass。

2026-10-13 核心冻结后的最后完整运行：1176 项，0 失败、0 跳过，耗时 338.656 秒。真实 Chromium/本地 GSAP 用既有固定二进制与资产，无安装。报告同步到 CI 的 references/validation/test-suite-report.json 及 test-suite.log，重新验证无错误；compileall、Skill UTF-8 验证、current Golden 重验和 git diff --check 通过。早先中间运行遇到旧哈希收据失效，已用实际评估器刷新而非降低门禁；仅此最终冻结运行作为交付测试依据。

真实样片的独立技术证据与可观看成片不等于 canonical sample stage 完成。A 的实际错帧/共享媒体时钟 strict 判定、源取景裁切与新增图形混判，B 的动态 GSAP 静态枚举及 canonical 四相位 parity 仍待适配；见 remaining-qa-decision.md。原始失败结果保留，不修改状态或补造 CLI tween。未作听感通过、用户审美、发布意愿或 production_default 声明。

回滚：关闭显式新输入并复用原工程，保留新候选和证据；代码仅经授权反向提交，不覆盖父 EDL/转录，不删除旧媒体。
