# 镜头优先的动效与真实开场 v3

状态：设计冻结候选，等待用户批准此文件集；方向已确认，具体效果尚未批准。

## 已确认

- 真人实物采用 `authentic_product_editorial`（真人产品编辑感）。
- 软件介绍采用 `professional_software_demo`（专业软件演示）。
- 加入真实高光前置方案，优先复制预告、正文保持。
- 先验证短片，不渲染完整视频。

用户原文与授权分层见 `direction-confirmation.json`。本轮没有创建长期 Goal、实现正式代码、制作新视频、安装依赖、提交或推送。生成冻结候选不是自行批准冻结。

## 阅读顺序

1. `objective-and-requirements.md`：目标、约束和需求追踪。
2. `architecture-and-contracts.md`：时间权威、状态、数据合同、版本、回滚。
3. `visual-and-audio-spec.md`：两类镜头/动效/声音的具体表达。
4. `implementation-and-acceptance.md`：依赖、短片计划、验收与成本门。
5. `design-review.md`：自审结论和仍未验证事项。
6. `schemas/editorial-motion.schema.json`、`examples/contracts.json`：机器合同草案与合成例子。
7. `design-freeze-candidate.json`：批准对象及文件哈希。

`research-and-redesign-proposal.md` 保持历史字节不变；其中“方向待定”描述研究时状态，现由确认记录与本文件集取代。外部技术研究仍可参考，但不因本设计而授权接入新运行时。

任务恢复、上下文压缩或模型切换后，先完整读取本 README、目标、架构、视觉规范、实施验收和候选清单，重新验证清单 SHA-256，再继续；摘要不能代替合同。

## 下一门

建议批准语：`批准 motion-editorial-v3-20261012 design-freeze-candidate，执行 WP0–WP2 的隔离短片验证，不进入正式集成或完整视频渲染。`

该批准只允许合同/缺陷测试与隔离原型和两类 10–15 秒对照，不能跳过短片审美门进入 WP3。具体高光 in/out 尚待听看证据后提出，不把方向批准当作精确剪辑批准。
