# FIX-01：保护证据采纳与源帧缓存

依据：两条短样片 execution-decision-package.md FIX-01 及用户明确修正批准。只修证据接缝；不改变镜头方向、样片窗口、人工审美门或旧默认。

## 合同

- 新显式 schema2 `protected_region_evidence` 允许真实 manual_visual_review 或 detector_observation；人工审核身份与方法必须保留，不能标成 MediaPipe。旧 schema1 observed_absent 入口不改。
- 绑定当前源文件绝对路径与 SHA-256、display 的宽高/旋转及 normalized_display_v1 坐标系。每项观察有 region_id、source_start/end、present/absent/unknown/lost、来源帧绝对路径/哈希/源时刻；手的左右身份不能合并以减少保护计数。
- present 只接受有限且合法的矩形和明确 bounded_review_envelope。该框是审核区间后给出的保守包络，不宣称自动连续追踪。证据至少首/中/末三个不同真实图片，时间覆盖整个声明窗；不能用单静帧宣称长时跟踪。detector 输入必须明确 detector 名称，不改写其丢失状态。
- absent 不得含框，unknown/lost 不含框且永不插值。未声明区间为 unknown。required_window 有缺口、unknown 或 lost 时返回 action_required；后续只能具体缩短事件/补证/停住，不能以别处存在一个框代替全窗有效。
- 文件限制在当前 project_root，验证真实图片、文件哈希、有限时间、当前 display。帧本身证明是图片及哈希绑定，不假称自动证明 frame 的源视频归属；源时刻是有 provenance 的审核声明，最终仍须实际四相位检查。

## 缓存

`acquire(..., reuse_existing=False)` 保持旧默认。显式 true 时检查当前源 SHA、时长/display、采样策略和精确时间列表、所有帧的当前哈希、可解码性及对应覆盖区间。全部匹配才复用源帧；任一不符按正常 acquisition 重取。不复用旧保护/审美结论，重新从当前转录、配置和原帧建立 bundle；因此转录改变不需要重取视觉帧，但必须重建词证据。记录 source_frames_reused 真值与原因。

## 接口、集成与验收

`load_protected_region_evidence(manifest_path, *, project_root, source_path, display, required_window=None)` 返回 `(protected_payload, artifact_paths)`。Director 负责显式启用、逐 EDL 窗验证、采纳/哈希、布局门和状态机，不手写 stage 状态。框只在自己的源窗适用。

测试：manual provenance 保真；合法 present/absent；源/帧漂移、越界/NaN、重复ID/重叠观察拒绝；unknown/lost/间隙不升级；旋转/坐标失配拒绝；缓存完整复用、任意帧/源/采样漂移重取、转录变化只重建元数据、关闭缓存旧行为不变。

迁移/回滚：旧 schema1 和 disabled 项目不变；删除新项目的显式配置即可停用。失败保留工件和报错，不更改父工程，不降低主观验收标准。

## 2026-10-12 实现验证记录

- 新模块 `scripts/protected_region_evidence.py`；源帧复用接入 `scripts/evidence_acquisition.py`，默认参数仍为 false；Director 显式接入由主代理负责。
- 红测试：新保护模块不存在导致 ModuleNotFoundError；缓存入口无 reuse_existing 参数导致 4 个 TypeError。随后实现通过。
- 针对测试：`test_protected_region_evidence_v2.py` 10 项、`test_evidence_frame_cache.py` 5 项、`test_protected_region_director.py` 4 项通过；既有 `test_evidence_acquisition.py` 17 项通过。这里是合同与隔离测试，不是实际字幕/动效审美通过。
- 真人实际素材补证：仅已批准 33.52–88.97 样片窗，112 个真实源帧（2 fps 加末帧）已做多模态观察；真实人工保守保护包络保留 provenance，不称自动跟踪。发现双手确实触及原图底边，需完整源画 fit 和独立字幕区，不得宣称原图底部恒安全。
- 真人 Director 的 evidence_acquisition 真实完成；源帧缓存按当前源/采样/每帧哈希验证复用。semantic_brief 仍为下一 owner 工件门，未绕过状态或启动昂贵渲染。
# 真实工程接线补充（2026-10-13）

两条真实短样片均复现：保护审阅中的真实帧已验证，但语义白名单只读取稀疏 representative_frames。FIX-01 将 v2 审阅帧按原路径、哈希、源时间和审阅来源暴露为独立 supplemental_frames，语义请求与绑定验证共同读取。它们仅证明离散帧，coverage 明确 unknown；不修改代表采样计数、缓存身份或覆盖结论，不冒充连续追踪。相同路径声明冲突时间直接拒绝。无 v2 审阅时旧行为不变。回归先复现 KeyError，再验证可引用和实际像素漂移拒绝。
