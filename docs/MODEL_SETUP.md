# 第二阶段：模型与向量接入

## 当前状态

适配代码、结构化 schema、模型输出验证、风险二次升级、双通道检索和离线故障回退已实现。2026-09-07 已通过本机隐藏输入完成 OpenAI 单轮和多轮真实调用；模型、embedding、读数保留、工单稳定、刷新恢复和安全锁定均通过。密钥未写入项目。

支持 OpenAI 兼容 Chat Completions 和 embeddings HTTPS 接口。模型与向量服务可以不同。只从环境变量读取配置，不自动加载 `.env.example`，不复用其他工具的密钥。页面与报告不会展示密钥。

## 配置

在资源管理器中双击项目根目录的 `start-openai.cmd`，按提示粘贴 API Key 并回车。密钥不会显示，也不会写入项目文件。脚本使用 OpenAI 官方地址，模型为 `gpt-5.6-terra`，向量模型为 `text-embedding-3-small`；同一密钥用于两者。模型权限是否可用由实际 API 项目决定。

脚本会发送两组考试样例到 OpenAI，另验证一组停机规则；检查通过才启动网页服务。启动后保持窗口开启，关闭即停止服务。若原本有离线服务占用 8765 端口，先在原服务窗口按 Ctrl+C 停止。脚本只设置当前进程环境，结束时清除密钥变量。重新运行需再次输入。

当前本机脚本配置 `gpt-5.6-terra` 与 `text-embedding-3-small`；该组合已于 2026-09-07 完成真实联调。部署到其他账户或环境时仍需重新验证模型权限和可用性。

以下为自定义服务时的手动配置方式：

在启动项目的同一个 PowerShell 终端设置：

```powershell
$env:APX_LLM_URL = 'https://你的服务地址/v1/chat/completions'
$env:APX_LLM_MODEL = '你的模型名'
$modelSecret = Read-Host '模型 API 密钥' -AsSecureString
$env:APX_LLM_KEY = [System.Net.NetworkCredential]::new('', $modelSecret).Password

$env:APX_EMBEDDING_URL = 'https://你的服务地址/v1/embeddings'
$env:APX_EMBEDDING_MODEL = '你的向量模型名'
$embeddingSecret = Read-Host '向量 API 密钥' -AsSecureString
$env:APX_EMBEDDING_KEY = [System.Net.NetworkCredential]::new('', $embeddingSecret).Password

python -m apx240 --serve
```

变量仅对当前终端及其启动的进程有效；修改后重启服务。密钥最终会位于本进程环境中，不写入项目文件。不要将密钥放进 URL。启用后，现场输入和相关手册片段会发送到指定模型/向量服务。

默认 `APX_LLM_FORMAT=json_schema`，请求 strict JSON Schema。若兼容供应商仅支持 JSON object，可以显式设置为 `json_object`；本地验证仍严格执行。程序不会自动放宽输出格式。接口必须返回 `choices[0].message.content` JSON 字符串且 finish_reason 为 stop；拒答、截断、非法 JSON、引用错误或候选缺失均回退。

`APX_EMBEDDING_MIN_SCORE` 默认 0.35，范围 -1 到 1，须用选定模型及标注数据标定。文档向量按知识版本、接口、模型、凭据指纹与文本隔离缓存；查询向量不缓存。接口单次超时 20 秒，无自动重试。一次普通首请求最多进行文档向量、查询向量和模型审阅三个请求。

## 真实验收

配置后执行：

```powershell
python -m apx240.check_live
```

该命令会向配置的外部服务发送两组普通样例，并执行一组高风险样例。缺少配置时不发请求并返回退出码 2。成功时前两组应显示 model_status=applied、retrieval=embedding，第三组应为 SAFE_BLOCKED；失败或回退退出码为 1。输出不包含凭据或完整供应商错误。

真实服务通过后还应人工检查候选排序、费用、延迟和模型稳定性，并对 tests/golden_cases.json 的 36 条初始标注样例做真实模型评估。这些标注由项目实现阶段整理，尚未经过维修专家签署。

## 模型边界

- 仅返回已有 cause_id 的完整排列，不新增原因；引用必须保持对应原因的原引用集合。
- 提取的测量 quote 必须来自现场原文，且能被单位/数值解析器再次验证。模型提取不会覆盖确定性读数。
- no_additional_risk 不等于安全确认，不能取消追问或放行设备。
- uncertain/escalate 需给出现场原句；程序按 SAFE-05 将报告和工单同步转专家，并替换全部排查步骤。
- 不接受模型自由生成的动作、根因确认、复机许可或额外字段。

## 接口参考

实现核对了官方 [Chat API](https://developers.openai.com/api/reference/resources/chat)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) 和 [Embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)。第三方兼容服务是否支持同样字段仍需实际测试；未默认指定模型名或声称任何账户可用。
