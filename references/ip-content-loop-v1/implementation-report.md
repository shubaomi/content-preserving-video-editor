# WP0–WP5 实施与证据

批准：`design-freeze-approval.json` 记录用户原文及候选 SHA-256。
九份冻结文档保持原字节；没有回写候选的历史 pending 状态。
实现基线为 `ddf70b0d0aff5f8627c25b2d451f121e07d57670`，交付分支 `main`。

## 需求到实现

| 工作包 / 需求 | 实现及验证 |
| --- | --- |
| WP0 / IPC-03 | `editorial_loop.py` 使用冻结 schema，额外验证来源角色、路径/链接边界、哈希、重复 IDs、未知字段与非有限数；单独保存批准收据 |
| WP1 / IPC-04/05/11 | `project_config.py` v14 内存迁移，默认关闭；guided intake 同批询问；身份一致性、unknown、advisory readiness；不修改用户 YAML/Profile |
| WP2 / IPC-06/07/08 | `director.py` 在现有语义/生产阶段接入；word/event/source 窗口映射到既有 promise ledger；生产阶段拒绝不同 ledger；十九阶段不变 |
| WP3 / IPC-09 | 两个平台包装引用同一最终母版和既有 promise；验证标题/说明/封面，复用 CTA；无发布 API、无重复 MP4 |
| WP4 / IPC-10 | 发布后独立离线命令，复用已有快照校验；相同发布去重、不同视频字节、窗口/口径/流量/样本量检查；只给假设和单变量实验，不改偏好 |
| WP5 / IPC-08/11 | 端到端语义阶段夹具、生产合同、源文件保持、恢复/失效、旧版本迁移、字幕历史问题、文档/示例、六类型及 Current Golden 回归 |
| 前轮已完成 / IPC-01/02/12 | 源码/全局 junction 恢复及独立 Hypit 安装保留；本轮没有加入 Hypit renderer |

模块级测试见 `tests/test_editorial_loop.py`（21 项）。包括真实调用 Director
语义阶段和生产阶段的合成夹具，不只是单独 schema 检查。其余回归见正式
`references/validation/test-suite-report.json` 与脱敏 `test-suite.log`。

## 实施中的边界修正

1. 不能用 sidecar 静默覆盖项目已有 explicit editorial_intent；冲突转 action_required。
2. 已完成的旧 schema 生产合同会在恢复时重开生产及下游，不重跑上游分析。
3. 生产/交付阶段重新验证 ledger 等于当前 sidecar 投影，不能接受手改后的另一份承诺。
4. 跨视频学习不把同母版重复发布当独立视频；同一版本的发布绑定冲突、累计
   views 下降、重复观察或伪造观察窗口均被拒绝。实测 0 与未知分开。
5. WP5 回归暴露两个测试文件把“有效供应商证据”日期写死在 8 月。只把有效
   测试夹具改为当次时间；过期测试及生产环境的时效门完全保留。
6. 基础测试收据无效时，`capability_registry.py` 不再启动不能用于升级等级的
   实际渲染检查，仍保守返回 director_integrated。先加入复现失败测试再修正，
   没有将过期证据或真实环境结果改为通过。

## 验证边界

已通过的分项：21 项新功能测试；116 项 Director 非 inspect 回归；866 项广泛
回归；14 项 capability registry；14 项 portrait golden；六类型结构 6/6；
Current Golden 生成与复验；compileall；Skill quick_validate；git diff --check。
这些分项有重叠，不能直接相加当作全量测试数。

最终完整套件 **1037 项通过，0 失败，0 跳过**，耗时 340.604 秒；正式收据
复验返回零错误，source tree SHA-256 为
`2b5722e71985fb4df9084c3854d0efd324715a4b64820a00edcce3ccfec32fff`。
本轮早期曾中断
在编辑期间运行的全量尝试和耗时的历史真实检查，未把中断结果记为通过。
正式最终运行启用 npm offline/no-install，防止测试隐式下载工具；没有削弱测试断言。

代码及安全评审为作者自审，不冒充独立专家评审。重点检查默认关闭零侧层访问、
链接越界、命令字段、资料身份、只读共享策略、hash-cache 恢复、发布权限和评论隐私。
确定性检查证明结构与引用关系，不能证明台词理解、品牌定位或商业因果。

## 保留的人工门与未执行项

- 本轮没有为新 IP loop 渲染或审美批准两条真实 30–60 秒 canary；需下一次
  用户选择的授权样片任务验证观点清晰、解释帮助、字幕和发布意愿。
- 未做剪映 Desktop 五项人工可编辑性验收，仍保持 pending。
- 未渲染用户完整视频，未付费生成、发布、改人设、自动学习偏好或开放 production_default。
- Hypit 仍未接入 Director，独立安装成功不等于其生成效果或 Studio 交付已验收。
- 不因本轮代码测试通过而刷新旧样片的人类批准，或将其改称新功能真实验证。

源码在 `E:\Projects\Skills\content-preserving-video-editor`；Codex 全局路径是
指向它的 junction。交付时核对同一 SKILL SHA-256，不维护两份容易漂移的源码。
回滚按冻结实施文档操作；保留新侧层及旧 master，不覆盖用户后续修改。
