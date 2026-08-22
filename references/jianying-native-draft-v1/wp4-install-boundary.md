# WP4 隔离测试草稿安装边界

状态：已获 HongRun 的 WP4 单独授权；仅实现和验证安装安全边界，不进入
真实短片 canary。

## 当前能做什么

- 读取一个已经通过完整复验的 `synthetic_fixture_only` 原生草稿包；
- 只在授权项目根目录内、带固定标记的隔离测试目录中创建
  `Codex-WP4-Isolated-Test-Draft`；
- 目标存在时立即拒绝，不提供自定义名称、覆盖、合并或修复模式；
- 不枚举测试目录中的同级项目，不读取任何同级草稿内容；
- 将源包、审批、测试目录身份和全部创建字节写入项目内安装收据；
- 仅当目标身份和全部字节仍与安装收据完全一致时执行受控回滚。

## 当前明确不能做什么

- 不能把测试目录设到授权项目根目录之外，因此不能指向真实剪映草稿库；
- 不能安装真实项目、读取或修改既有剪映草稿；
- 不能启动剪映、打开草稿、操作界面、导出视频或发布；
- 不能声明任何剪映版本兼容，也不能把能力提升为
  `real_project_validated`；
- 不能进入 WP5。真实 45–60 秒短片安装和五项人工编辑仍需新的明确批准。

## 机器入口

```powershell
python scripts/jianying_native_install.py install-test `
  --package-manifest <synthetic-package-manifest> `
  --project-root <authorized-project-root> `
  --test-store-root <project-local-marker-bound-test-store> `
  --receipt <project-local-install-receipt>

python scripts/jianying_native_install.py rollback-test `
  --install-receipt <project-local-install-receipt> `
  --project-root <authorized-project-root> `
  --test-store-root <same-test-store> `
  --rollback-receipt <project-local-rollback-receipt>
```

测试目录必须预先存在，并包含
`.codex-jianying-wp4-test-store.json`，其内容必须精确为：

```json
{
  "schema_version": 1,
  "kind": "jianying_wp4_isolated_test_store",
  "purpose": "wp4_install_boundary_test_only",
  "real_jianying_store": false
}
```

该标记不是把任意目录变成安全草稿库的授权。程序还会强制目录位于项目根
目录内、拒绝符号链接/Junction，并绑定目录文件身份。正常视频剪辑和
Director 流程不会自动调用这个入口，配置中的 `install` 仍必须为 `false`。
