# Render 免费部署：执行步骤

状态：本地适配完成，尚未上传仓库或创建云服务。此文件不代表线上验收通过。

## 第一步：上传专用私有仓库

解压 apx240-render-upload.zip。登录GitHub创建一个新的Private仓库（例如apx240-agent-demo），将解压后的内容上传到仓库根目录。打开仓库应直接看到render.yaml、.python-version、apx240、web和knowledge_mounts，而不是再套一层文件夹。

上传包已排除本机会话、实际环境文件、旧联调文件和外部候选模板。不要额外上传deploy.env、runtime或任何API密钥。无需在GitHub配置密钥，密钥只填Render。

## 第二步：创建免费服务

登录 https://dashboard.render.com/ ，使用GitHub连接此私有仓库。选择 New → Blueprint，选中仓库，使用根目录render.yaml。

创建页面必须显示一个Web Service、Free计划、无付费磁盘或数据库。若显示付费资源，停止创建并核对，不要接受升级。配置中的plan: free已显式指定，避免平台默认选择付费计划。自动部署关闭，以免提交文档就重启演示。

如果使用 New → Web Service 手动创建：Runtime选Python；Build Command填 python -m unittest discover -s tests -q；Start Command填 python -m apx240.public_server；Instance Type选Free；Health Check Path填 /ready。按render.yaml设置环境变量。

## 第三步：填写三个项目值

| Render字段 | 填什么 |
| --- | --- |
| APX_LLM_MODEL | 你本机真实联调已通过的模型名；当前本机启动脚本配置为gpt-5.6-terra，云端需重新验证可用性 |
| APX_LLM_KEY | 你的OpenAI API Key |
| APX_EMBEDDING_KEY | 用于embedding的OpenAI API Key，可与上项相同 |

其余接口由配置提供。APX_ACCESS_PASSWORD由Render生成随机访问口令，部署后在服务Environment中查看并安全保存，账号为reviewer。这是给面试官的访问口令，绝不是API密钥，不需要发给开发助手。

平台自动提供RENDER_EXTERNAL_URL和PORT，本程序会读取；使用默认onrender.com地址时无需自己猜域名。自定义域名不在本次免费部署范围。

## 第四步：线上验收

等服务显示Live后，从另一台设备打开平台给出的HTTPS地址。浏览器会要求演示账号和口令。Live和/ready仅表示进程及基本配置可用，不证明OpenAI联调通过。

1. 输入“A203，设定165°C，实际128°C，加热电流0A，没有烟雾和焦味。”检查六项输出，在完整报告中核对model_review.status=applied和retrieval.semantic_channel=embedding；若fallback不能算真实模型通过。
2. 继续补充“已完成预热”，检查旧读数保留。模型可能选择转专家，应核对原因，而不是只看页面有文字。
3. 新建会话输入“A520，有金属摩擦声”，应立即停机，模型与向量都跳过安全门调用。
4. 输入“A999”，应提示无覆盖、停止进一步操作和专家升级。
5. 下载输入输出，保存真实测试日期和正式链接到SUBMISSION.md，再用于作业提交。

## 免费方案的实际限制

- 免费Web服务闲置15分钟会休眠，首次访问可能等待唤醒；面试前提前打开并执行真实请求。
- 文件系统不持久，休眠/重启/部署可能清空SQLite会话和调用计数。旧会话丢失时导出的报告仍可人工查阅；新建会话不等于设备获准复机。
- 平台免费额度有上限，按账号页面核对资源与计费设置。OpenAI API调用仍计费；应用请求上限不是供应商账单硬上限。
- 当前为受共享口令保护的单评审演示，不具备多用户权限隔离。

官方依据：[免费服务限制](https://render.com/docs/free)、[Blueprint配置](https://render.com/docs/blueprint-spec)、[自动域名与端口变量](https://render.com/docs/environment-variables)、[Python版本](https://render.com/docs/python-version)。
