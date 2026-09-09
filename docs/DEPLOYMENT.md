# 部署候选包：尚未上线

本包包含受口令保护的单评审演示服务、容器文件和HTTPS反向代理配置。应用监听0.0.0.0:8765，仅应放在HTTPS平台代理或Caddy后；Compose没有向宿主机开放8765。

## 通用服务器

需要Docker Compose、域名、可接入的HTTPS网络。把deploy.env.example复制为deploy.env，在服务器本地填入域名、随机访问口令、已联调的模型名、API密钥。访问口令至少20字符，禁止使用API密钥。不要将deploy.env加入仓库或交付包。

启动：docker compose --env-file deploy.env up -d --build

反向代理将根据配置的域名处理HTTPS。公网DNS和端口80/443需正确连接服务器，见 [Caddy官方说明](https://caddyserver.com/docs/quick-starts/reverse-proxy)。变量注入方式见 [Docker Compose官方说明](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)。

## Hugging Face Docker Spaces

适合本项目的小规模演示：模型在OpenAI运行，本项目只运行Python应用，不需要GPU或把界面改成Gradio。

先确认账号资格：官方当前说明新建Docker/Gradio Space需要付费计划，CPU Basic无小时费并不等于免费账号可创建，见 [Spaces说明](https://huggingface.co/docs/hub/en/spaces-overview)。不要仅依据旧教程购买硬件。

准备步骤：
1. 创建Docker Space，选择合适可见性。Public会公开源码；Protected可隐藏源码但允许访问应用；Private限制面试官访问，需要相应授权。可见性及资格以创建页面为准。
2. 将deploy/huggingface.README.md的内容作为Space根目录README.md。其中app_port为8765，与应用一致；使用根目录Dockerfile，平台不需要compose.yaml或Caddyfile。
3. 上传应用、web、知识目录、Dockerfile和文档；不要上传runtime、deploy.env、last-live-check.json、缓存或本机会话。
4. 在Space Settings中设置Secrets：APX_LLM_KEY、APX_EMBEDDING_KEY、APX_ACCESS_PASSWORD。设置Variables：APX_LLM_URL、APX_LLM_MODEL、APX_LLM_FORMAT、APX_EMBEDDING_URL、APX_EMBEDDING_MODEL、APX_ACCESS_USER、APX_PUBLIC_ORIGIN。最后一项填写平台提供的完整 https://实际子域名.hf.space，不带末尾斜杠。
5. 使用直接的hf.space应用地址验证浏览器访问口令和诊断，避免嵌入页面的跨站身份验证差异。面试官只需演示账号，不需要OpenAI API密钥。

Docker端口、运行时Secrets和磁盘说明见 [HF官方Docker文档](https://huggingface.co/docs/hub/en/spaces-sdks-docker)。默认磁盘不持久，重建后SQLite会话和限额可能重置；当前包尚未集成HF存储桶或外部数据库。短期演示需导出记录；不能承诺跨重建恢复。CPU Basic可能休眠，验收前应提前打开并完成真实请求测试，见 [硬件与休眠说明](https://huggingface.co/docs/hub/spaces-gpus)。

## 保护范围与限制

- 单独访问口令保护页面、报告和所有API；这是共享演示口令，不是多用户数据隔离或专家身份认证。
- 全局默认30次/小时、100次/UTC日的诊断请求上限；数据库保存计数，普通进程重启保留，前提是存储保留。错误请求和重试也计数。它不是美元费用硬上限，仍需在模型供应商项目中设置预算并监控用量。
- 同时最多8个处理线程；超过返回忙碌。长模型请求仍可能排队。本服务用于有访问口令的小规模作业演示，不承诺高并发生产性能。
- API密钥只留在服务端配置，打包和构建排除实际环境文件及运行数据库。
- 未在云平台部署，未验证TLS、域名访问、容器构建或云端真实模型。本机没有Docker，不能声称“容器构建通过”。

## 上线验收

从另一台设备验证：未登录被拒绝；登录后普通A203可得到六项输出且模型已应用；A520先停机且不调用模型；补充输入更新报告；无覆盖输入升级；刷新恢复；导出样例。实际平台重启后单独检查会话是否保留。保存最终入口、运行日期和真实输入输出后才可提交。
