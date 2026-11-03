# RAG 知识库系统

企业内部知识库问答系统。技术栈：FastAPI + LangChain/LangGraph + Milvus + MySQL + Vue3。

**当前进度**
- ✅ P0 骨架：配置中心、结构化日志（trace_id 贯穿）、统一错误码、17 张 ORM 表、健康检查、容器编排
- ✅ P0.5 认证：JWT 双 Token + 刷新轮换 + 登出黑名单 + 表驱动 RBAC + 冒烟测试（17 项全通过）
- ✅ P0.6 向量链路：切片 → 百炼向量化 → Milvus 入库 → 检索 → rerank 全链路实测通过
- ✅ P1 知识库：CRUD + 成员管理 + 流式上传 + 解析（PDF/Word/MD/TXT/Excel）+ 结构化切片 + 入库任务 + 检索预览（16 项冒烟全通过）
- ✅ P2 问答：LangGraph 检索图（意图路由/改写/召回/精排/质量重试）+ 引用标注 + SSE 流式 + 多轮上下文 + 反馈（25 项冒烟全通过，MiMo 实测）
- ✅ P1.5 混合检索：Milvus 内置 BM25（chinese analyzer）+ RRF 融合精排。**实测在 20~23 条规模下与纯向量无差异**，保留作下限保护，详见 docs §6.1
- ✅ P3 后端配置：用户/角色权限/模型配置（密钥加密+脱敏+连通性测试+切换默认）/审计日志/用量统计（31 项冒烟全通过）
- ✅ P4 前端：Vue3 + TS + Element Plus 全量页面（登录/工作台/知识库/文档管理/流式对话/后台四项），`vue-tsc` 零错误
- ✅ P5 提示词管理：模板表 + 版本快照 + 变量校验 + 渲染预览 + 试跑 + 回滚 + 恢复默认 + 按知识库覆盖（36 项冒烟全通过）
- ✅ 前端补全：Markdown 渲染（marked + DOMPurify + 按需代码高亮）、知识库参数设置、前台对话页无 Element 重写
- ✅ 示例知识库：Vue3 基础 9 篇（95 切片，块级保护切片器），检索 9/9 首位命中
- ✅ P6 智能体：后台配置（模型/知识库/提示词覆盖/检索参数）→ 发布 → 前台选用；
  会话绑定智能体，知识库访问权经智能体间接授予（33 项冒烟全通过）
- ⬜ 待补：移动端适配、回答导出、知识库级检索参数按会话覆盖

**已实现接口**

```
POST   /api/v1/auth/login | refresh | logout | change-password
GET    /api/v1/auth/me
POST   /api/v1/kb                          创建知识库
GET    /api/v1/kb                          列表（按权限过滤）
GET    /api/v1/kb/{id}  PATCH  DELETE      详情 / 改配置 / 软删
GET    /api/v1/kb/{id}/members  POST  DELETE
POST   /api/v1/kb/{id}/search              检索预览（召回+rerank，不生成）
POST   /api/v1/kb/{id}/documents           上传（流式落 MinIO）
GET    /api/v1/kb/{id}/documents           文档列表
GET    /api/v1/kb/documents/{id}  DELETE
POST   /api/v1/kb/documents/{id}/reindex   重建向量
GET    /api/v1/kb/tasks/{id}               任务进度
GET    /api/v1/kb/{id}/chunks/{doc_id}     切片预览（调试）
POST   /api/v1/chat/sessions               创建会话（绑定知识库）
GET    /api/v1/chat/sessions               会话列表
GET    /api/v1/chat/sessions/{id}/messages 历史消息（含引用与检索快照）
POST   /api/v1/chat/sessions/{id}/ask      提问（非流式）
POST   /api/v1/chat/sessions/{id}/stream   提问（SSE：retrieval → delta×N → done）
POST   /api/v1/chat/messages/{id}/feedback 点赞/点踩
GET    /api/v1/users | POST                 用户列表（管理）/ 创建用户
GET    /api/v1/users/{id} | PATCH | DELETE  用户详情 / 启用禁用改角色 / 软删
POST   /api/v1/users/{id}/reset-password    重置密码（踢掉该用户所有登录）
POST   /api/v1/users/{id}/unlock            解除登录锁定
GET    /api/v1/users/{id}/effective-permissions  查看实际权限
GET    /api/v1/roles | PATCH /roles/{id}    角色列表 / 改角色权限（覆盖式）
GET    /api/v1/permissions                  全部权限码（前端渲染勾选框）
GET    /api/v1/admin/models | POST          模型配置列表（密钥脱敏）/ 新增
PATCH  /api/v1/admin/models/{id} | DELETE
POST   /api/v1/admin/models/{id}/set-default  切换默认模型（立即生效）
POST   /api/v1/admin/models/{id}/test         连通性测试（真实调用一次）
GET    /api/v1/admin/audit-logs             审计日志（谁在何时改了什么）
GET    /api/v1/admin/usage | /usage/daily   Token 用量（按场景/模型、按天）
GET    /api/v1/agents                       前台：我可用的已发布智能体
GET    /api/v1/admin/agents | POST          智能体列表（含草稿/用量）/ 创建
GET|PATCH|DELETE /api/v1/admin/agents/{id}  详情 / 修改（立即生效）/ 软删
POST   /api/v1/admin/agents/{id}/publish    发布 / 下线（?published=）
POST   /api/v1/admin/agents/{id}/test       按完整配置试跑
GET    /api/v1/admin/settings | PUT /{key}  系统参数 KV（预留）
GET    /api/v1/admin/prompts                提示词列表（含是否已自定义）
GET    /api/v1/admin/prompts/variables      可用变量清单
GET    /api/v1/admin/prompts/{code}         详情（?kb_id= 取知识库覆盖）
PUT    /api/v1/admin/prompts/{code}         保存（版本 +1，写版本快照）
POST   /api/v1/admin/prompts/{code}/reset   恢复出厂默认
GET    /api/v1/admin/prompts/{code}/versions  版本历史
POST   /api/v1/admin/prompts/{code}/rollback/{v}  回滚（生成新版本，不覆盖历史）
POST   /api/v1/admin/prompts/{code}/preview 渲染预览（不调模型，不花钱）
POST   /api/v1/admin/prompts/{code}/test    试跑（用编辑中内容，可带知识库检索）
GET    /health | /health/deep
```

**SSE 事件约定**

| event | 时机 | data |
|---|---|---|
| `retrieval` | 检索完成、生成开始前 | `{need_retrieve, reason, hits[]}` |
| `delta` | 每个 token 片段 | `{text}` |
| `done` | 生成结束 | `{message_id, citations[], usage, ttft_ms, latency_ms}` |
| `error` | 任何环节失败 | `{code, message}` |

---

## 目录

```
RAG/
├── docs/01-技术选型清单.md      # 完整技术决策记录
├── knowledge/vue3/              # 示例语料：Vue3 基础 9 篇（可直接导入）
├── backend/
│   ├── app/
│   │   ├── core/                # 配置、日志、错误、安全、RBAC、依赖注入
│   │   ├── db/                  # 会话与 ORM 模型（19 张表）
│   │   ├── api/v1/              # 路由（auth、kb、documents、chat、users、admin、prompts）
│   │   ├── services/            # 业务逻辑（含 prompt_service 提示词管理）
│   │   └── workers/             # Celery
│   ├── alembic/                 # 数据库迁移
│   ├── scripts/                 # init_data / seed_kb / smoke_* / probe_*
│   └── .env.example
├── frontend/                    # Vue3 + TS + Element Plus
│   ├── src/
│   │   ├── api/                 # request(拦截器/静默刷新) · auth · kb · chat(SSE) · admin
│   │   ├── stores/user.ts       # token + 权限
│   │   ├── router/index.ts      # 路由表 + 权限守卫
│   │   ├── layouts/             # PortalLayout（前台）/ BasicLayout（后台）
│   │   └── views/               # login / chat / dashboard / kb / system
│   └── vite.config.ts           # /api 代理到 8000
└── deploy/
    ├── docker-compose.yml
    └── minio-build/             # 自建 MinIO 镜像（见下方说明）
```

---

## 前端启动

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```

开发时 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，所以**后端必须先启动**。

```bash
npm run build        # 生产构建（含 vue-tsc 类型检查）
```

前端要点：
- **前台 / 后台分离**：
  - 前台 `/chat`（PortalLayout）：全屏对话，左侧历史会话，业务用户登录即进
  - 后台 `/admin/*`（BasicLayout）：工作台、知识库、用户、角色、模型、审计
  - 登录后按权限落地：有任一后台权限 → `/admin/dashboard`，否则 → `/chat`
  - 后台路由统一校验 `meta.admin`，无权限直接 403，不渲染空菜单
- 路由守卫按 `meta.perm` 拦截，权限不足跳 403；菜单也按权限过滤，但**真正的拦截在后端**
- axios 拦截器做了 401 静默刷新（并发单飞），刷新失败才跳登录
- 流式问答用 `fetch` + `ReadableStream` 手写 SSE 解析（axios 拿不到增量响应体）
- **Markdown 渲染顺序**：`marked` → `DOMPurify.sanitize` → 插入引用角标 span → 代码高亮。
  必须先消毒再插入自己生成的 HTML；顺序反了会被清洗掉，不做消毒就直接 `v-html` 则是 XSS 入口
- 引用角标只在**文本节点**里替换，跳过 `<code>`/`<pre>`，否则代码里的 `[1, 2]` 会被误变成引用标记
- 流式渲染按 60ms 节流，否则每个 token 都跑一次 markdown 解析 + 高亮，长回答会卡
- 新建对话默认沿用上次会话的知识库；无知识库时给出明确引导而不是空下拉框

---

## 首次启动（三步）

### 1. 配置镜像源（**必须，否则镜像拉不下来**）

Docker Hub 在境内无法直连。本机已在 `~/.docker/daemon.json` 配好加速源：

```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.net"
  ]
}
```

> ⚠️ 改完后必须重启 Docker Desktop 才生效。
> ⚠️ 已知限制：`minio/minio` 在上面所有源都拉不到，故改为**自建镜像**（见 `deploy/minio-build/Dockerfile`）。

### 2. 启动基础设施

```bash
cd backend
cp .env.example .env        # 首次；然后填入 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY

cd ../deploy
docker compose up -d mysql redis minio-docs minio-milvus etcd milvus
docker compose ps           # 等到 6 个容器全部 (healthy)
```

### 3. 建表 + 初始化数据

```bash
cd backend
alembic upgrade head
python -m scripts.init_data     # 创建权限、3 个角色、admin 账号
```

`admin` 初始密码在初始化时**只打印一次**，请立即保存。也可自己指定：

```bash
ADMIN_INIT_PASSWORD='YourPass123' python -m scripts.init_data
```

### 4. 启动 API 并冒烟测试

```bash
uvicorn app.main:app --reload --port 8000

# 另一个终端
python -m scripts.smoke_test '你的admin密码'
```

期望输出：`结果: 17 通过, 0 失败`

接口文档：http://localhost:8000/docs

---

## 关于 MinIO 镜像（重要）

`minio/minio` 在 Docker Hub 无法直连，且在所有国内加速源上均不可用；MinIO 官方也已停止
`dl.min.io` 的二进制分发（返回 410）。

**解决办法**：从国内镜像站下载 linux-amd64 二进制，用 alpine 自建镜像。

```bash
cd deploy/minio-build
curl -L -o minio https://dl.minio.org.cn/server/minio/release/linux-amd64/minio
curl -L -o mc    https://dl.minio.org.cn/client/mc/release/linux-amd64/mc
docker build -t minio/minio:local .
```

升级 MinIO 时重新下载二进制再 rebuild 即可。二进制已加入 `.gitignore`。

---

## 权限模型

**角色**：`super_admin` / `admin` / `user`（全局，控制后台准入）
**库级成员**：`owner`（可上传/删除文档、触发重建）/ `viewer`（只读问答）

判定顺序：`superuser` 直通 → 全局角色权限 → 库成员身份 → 默认拒绝。

> 说明：未引入 Casbin。本项目是"3 个角色 + 库级成员"的简单 RBAC，
> Casbin 的 adapter 会额外建 `casbin_rule` 表，与 `roles`/`permissions` 功能重叠，
> 两套数据同步是 bug 源。`app/core/rbac.py` 保持了 Casbin 风格的调用形态，
> 将来要做多租户域隔离或 ABAC，替换该模块实现即可，业务层无感。

权限码在 `app/core/rbac.py` 的 `PERMISSIONS` 登记，新增后重跑 `init_data` 即可同步。

---

## 关键约定

| 事项 | 约定 |
|---|---|
| 错误响应 | 统一 `{code, message, trace_id}`，业务异常继承 `AppError` |
| 日志 | 结构化，每条带 `trace_id`；前端报错可凭它定位 |
| 时区 | Asia/Shanghai |
| 队列 | `parse`（解析，并发1）/ `embed`（向量化，并发2）/ `default` |
| 向量维度 | 1024，存 `knowledge_bases.embedding_dim`，**上线后禁止修改** |
| Embedding | `qwen3.7-text-embedding-flash`（1024 维）。注意 flash 的 tokenizer 比 v4 粗，同句中文约 3~4 倍 token |
| Rerank | `gte-rerank-v2`，走 DashScope 原生接口（非 OpenAI 兼容）。**输入是 query×候选数，召回别贪多** |
| 检索 | 混合检索（dense + Milvus 内置 BM25 + RRF）。**RRF 分只有 0.01~0.05，不能用余弦阈值过滤**，相关性判断交给 rerank |
| MiMo | 推理模型，会先产生 `reasoning_content` 再输出正文，首 token 通常 1~3s；`astream` 只透传 content |
| 入库模式 | `INGEST_MODE=inline` 本地进程内执行（重启丢任务）；生产改 `celery` |
| 切片 | `chunk_size` 单位是**字符**不是 token。`min_chunk_size` 只合并碎片，设大会吞掉正常小节并丢失章节归属 |
| 切片器 | 块级保护：代码/表格/列表/引用是原子块。**超长代码每片补回围栏**、**超长表格每片重复表头**（没有表头的数据行模型读不懂）、硬切对齐句末标点。切片质量用 `python -m scripts.diagnose_chunks <目录> <size> <overlap>` 验证 |
| 切片器 | 标题行/加粗伪标题落在块尾会移到下一块开头，否则"有标题没内容"+"有内容没标题"两块都废 |
| 自定义标记 | `strategy=delimiter` + `delimiter`，**按行首锚定**：`## ` 不会误切 `### `。标记之间不做语义合并（用户给的边界就是边界），只有孤立的标题行会附着到下一块 |
| 智能体 | 会话必绑智能体（前台），配置优先级 **agent 覆盖 → 知识库覆盖 → 全局**。知识库访问权经智能体间接授予（建会话时不再校验 kb_members）；已发布的修改**立即生效**（审计留痕）。改后端代码后必须重启 uvicorn，否则重建/问答仍走旧逻辑 |
| 改代码后 | **必须重启 uvicorn 才生效**——reindex 走的是服务进程里已加载的模块，改了 chunker 不重启，重建出来的还是旧结果（本次踩坑：重建后指标纹丝不动才发现） |
| 上传 | 边接边落临时文件，内存恒定 1MB；同库内 sha256 去重，避免重复付费向量化 |
| 删库 | 必须同时删 Milvus 向量（`delete_by_kb`），否则留下永远查不到的孤儿数据 |
| 生成 | 不进 LangGraph 节点：节点跑完才拿到整段，流式就没意义了。图只到"可用上下文"，生成在 service 层流式 |
| 流式 DB | SSE 生成器里必须自建 `SessionLocal`，请求依赖的 session 在 `StreamingResponse` 返回后已被关闭 |
| 引用 | 模型输出 `[1][2]`，正则提取后映射到 hits，**越界编号直接丢弃**（防模型编造引用） |
| 提示词变量 | 用 `{{name}}` 双花括号，**不用 Python 的 `{name}`**：提示词里常有 JSON 示例，单花括号会让 `format` 抛 KeyError 且报错看不出位置 |
| 提示词校验 | 保存时校验变量白名单，`{{contxt}}` 这类拼错直接 400。不校验则会静默把字面量发给模型，表现为"效果莫名变差" |
| 提示词覆盖 | 按 `(code, kb_id)` 唯一，`kb_id=0` 表示全局。**用 0 而不是 NULL**：MySQL 唯一索引不去重 NULL，会出现多条"全局"且不报错 |
| 提示词版本 | 回滚是"旧内容作为新版本提交"，不覆盖历史；版本号取模板行与历史表的 max+1，否则删过行再保存会撞唯一键 |
| 提示词缓存 | 进程内 30s TTL，写操作按 code 整体失效。不按 kb 精细清理——漏清一条会出现"改完没生效"这种极难自证的问题 |
| 提示词兜底 | 读表失败（DB 抖动/未迁移）一律回退内置默认，问答不能因提示词表故障而不可用 |
| 模型配置 | 优先读 `model_configs` 表，查不到回退 `.env`。改后台配置**立即生效，无需重启** |
| API Key | Fernet 加密存 `api_key_enc`，密钥由 `SECRET_KEY` 派生。**换 SECRET_KEY 会导致旧密钥无法解密**，必须在后台重新录入 |
| 防呆 | 超管权限不可改、默认模型不可禁用/删除、不能禁用或删除自己、删用户会踢掉其所有会话 |
| 敏感库 | `sensitivity=confidential` 不应发送到公有云模型 |
| alembic.ini | **只允许 ASCII**，Windows 下 configparser 按 GBK 读取，中文会崩 |

---

## 常用命令

```bash
# 迁移
alembic revision --autogenerate -m "描述" && alembic upgrade head

# 代码检查
ruff check app

# 冒烟测试（认证链路 17 项）
python -m scripts.smoke_test <password>

# 知识库全链路冒烟（建库→上传→解析→切片→向量化→检索，16 项）
python -m scripts.smoke_kb <password>

# 问答全链路冒烟（会话→检索→生成→引用→流式→多轮，25 项）
python -m scripts.smoke_chat <password>

# 混合检索对比（纯向量 vs dense+BM25，约 1200 token）
python -m scripts.test_hybrid --drop

# 后台接口冒烟（用户/角色/模型配置/审计/用量/权限隔离，31 项）
python -m scripts.smoke_admin <password>

# 提示词管理冒烟（校验/版本/预览/试跑/回滚/生效/权限，36 项）
python -m scripts.smoke_prompt <password>

# 切片器单元测试（20 项）
python -m pytest tests/test_chunker.py -q

# 切片质量诊断（代码块闭合率/句子截断/伪标题）
python -m scripts.diagnose_chunks ../knowledge/vue3 400 60
python -m scripts.diagnose_chunks <目录> <size> <overlap> --strategy delimiter --delimiter "## "

# 批量导入语料（新建知识库；加 --kb-id 则追加到已有库）
python -m scripts.seed_kb "Vue3 基础知识" ../knowledge/vue3 --password <password>

# 模型能力探测（对话/流式/JSON）
python -m scripts.probe_chat

# 向量链路端到端测试（切片→向量化→Milvus→检索→rerank，约 2000 token）
python -m scripts.test_vector_pipeline --drop

# 探测模型可用性（几乎零成本）
python -m scripts.probe_embedding
python -m scripts.probe_rerank

# 容器状态
cd deploy && docker compose ps && docker compose logs -f --tail=50 milvus
```

---

## 环境要求

- Python 3.11 ~ 3.13
- Docker Desktop（Windows 下 CLI 可能不在 PATH：`%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`）
- 出网：`dashscope.aliyuncs.com`（Embedding/Rerank）、`api.deepseek.com`（对话）、`dl.minio.org.cn`（MinIO 二进制）
