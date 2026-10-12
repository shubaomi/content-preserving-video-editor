# WP0 隔离合同实验

WP3 补充：以下说明保留 WP0–WP2 历史范围。生产 words-only 缺陷现已修复，
对应回归从“复现旧缺陷”更新为“生产修复仍有效”。其余隔离合同不参与生产导入。
正式集成与 ME-AMEND-01 见 `references/motion-editorial-v3-runtime.md`。

此目录仅服务 `motion-editorial-v3-20261012` 的 WP0–WP2 前置验证。生产脚本、配置读取、Director、组件注册表均未引用它。不接入正式工作流、不颁发审美或完整渲染授权。

## 运行

使用当前已有 Python + jsonschema，无新增依赖安装：

```powershell
Set-Location E:\Projects\Skills\content-preserving-video-editor
python -m unittest discover -s experiments/motion-editorial-v3 -p test_contracts.py -v
```

截至本次检查：38 tests pass，0 skipped。先建立测试并确认缺少实现会失败；旧 `audit_hook_pacing.audit` 的 words-only 无法测到语音且产生默认视觉分缺陷在测试中真实复现。随后隔离实现支持 words/segments，并将无真实视觉证据明确保持为 unknown，未直接修生产函数。

## 检查层级

- `validate_contract`：冻结 schema、唯一 ID、输入角色与引用、区间、投影公式、单次词实例、裁切边界、四阶段、样片目的和预算等结构/局部关系。返回不代表 runtime readiness。
- `verify_evidence`：绝对路径、存在性、授权根、符号链接/Junction 规范化后范围、当前 SHA-256。此检查不证明角色文件内容真实、不证明授权或许可。
- `validate_hook_bindings`：标准化事实中的 source/词序列/原文短引/完整词边界/源时长/帧来源与时刻/正文兑现点引用。语境自包含、承诺真实性仍需源听看与编辑审核。
- `validate_projection_bindings`：标准化候选 EDL 完全一致、最多一个连续 hook、正文源区间/顺序/语速/原间隙保持、所有词实例从唯一来源推导。此适配器刻意仅支持单 source；多 source 拒绝，不能错误复用同组词。
- `validate_hook_authority`：默认无权威适配器则拒绝；检查短片范围、精确输入哈希、原用户消息/操作者/时间字段、候选 ID 和实际投影片段，并由调用端可信审核适配器裁决。测试 callback 仅合成断言，不是实际用户批准。
- `migrate_fixture`：v1–v14 的深拷贝内存迁移夹具、v15 严格 disabled；不能启用正式 runtime，不读写用户 YAML。

命令行只提供结构和可选文件哈希检查，明确输出 `runtime_authorized=false`、`aesthetic_approved=false`。没有可自授权开关。

## 重要边界与延期项

1. 冻结 `timeline_projection` 的必需字段包含 hook plan/approval；本轮 WP2 没有精确 hook 批准，禁止为无 hook 风格样片伪造这些工件。WP2 使用单独注明 `non-hook style source-window map` 的派生记录，不宣称它通过正式 hook projection 合同。冻结 schema 原样保留。
2. 标准化绑定函数不是生产 EDL/转录/证据格式读取器。调用者必须先核验实际文件与哈希，并正确映射标准化输入。没有声称端到端绑定完成。
3. shot plan 的 schema/输入角色/实例字符串/裁切/阶段检查不等于已核对实际 semantic brief、可见文案语义、目标跟踪或 soft-occlusion 窗口。WP1–WP2 需真实原画/意图板/逐阶段视觉审核；正式内容适配与回归留给 WP3。
4. T01/T02/T04/T05/T06/T11/T13/T17/T19 的部分可重复不变量得到合成单元覆盖，不代表整个 T 编号通过。T03/T08–T12/T16/T18 的真实媒体/审美证据另行记录；T07/T14/T15/T20 的正式输出语义、缓存/恢复、全部下游同 EDL 集成不在此目录完成。
5. 文件 SHA-256 是完整性信息，不是身份认证。正常剪辑不要求用户配置密钥。
6. 不包含源媒体/个人信息；临时测试素材只存在于 Python 临时目录并自动清理。Windows symlink escape 测试本次实际运行无 skip；其他机器不支持创建时会明确 skip，不计作真实通过。

独立代码复核由主任务安排；本 README 不把作者检查称作独立复审。
