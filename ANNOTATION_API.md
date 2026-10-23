# 注释证据接口接入说明

CellWiki 侧提供只读的**注释证据接口**：把工作区里已经提交、已经人工审批通过的
知识，按细胞簇的 Marker 与背景投影成候选类型和可追溯的文献证据。调用方（注释
Agent）拿这些证据做最终判断。

这份接口**不负责**最终标签、最终置信度、聚类验收，也不代表生物学准确率保证。
分工是固定的：CellWiki 供证，调用方定夺。

接口标识：`algorithm_version = annotation-v1`。

## 1. 前置条件

| 条件 | 说明 |
| --- | --- |
| 部署方配置令牌 | 环境变量 `CELLWIKI_ANNOTATION_API_TOKEN`；未配置时接口返回 `503 SERVICE_DISABLED`（默认禁用） |
| 以 daemon 形态运行 | `cellwiki serve --workspace <工作区> --detach`；端口由发现文件给出 |
| 同机 loopback | 接口只监听 `127.0.0.1`，只经 HTTP，不提供 TLS，不要暴露到局域网 |
| 知识已提交且已审批 | 接口只读已提交内容；未审批的改动会被门禁挡住 |

令牌是独立的：桌面 bearer token 与模型 API Key 都不能用于本接口。

## 2. 快速开始

```powershell
# 1) 部署方配好令牌并启动 daemon
$env:CELLWIKI_ANNOTATION_API_TOKEN = "<长随机串>"
cellwiki serve --workspace D:\kb --detach

# 2) 问端口
cellwiki daemon status --workspace D:\kb     # 输出 JSON 里的 port

# 3) 自检是否接通（PASS/FAIL 清单）
python scripts\annotation_smoke.py --workspace D:\kb
```

```bash
# 1) 部署方配好令牌并启动 daemon
export CELLWIKI_ANNOTATION_API_TOKEN="<长随机串>"
cellwiki serve --workspace /srv/kb --detach

# 2) 问端口
cellwiki daemon status --workspace /srv/kb     # 输出 JSON 里的 port

# 3) 自检是否接通（PASS/FAIL 清单）
python3 scripts/annotation_smoke.py --workspace /srv/kb
```

令牌也可以写进工作区根目录的 `.env`（`CELLWIKI_ANNOTATION_API_TOKEN=<长随机串>`，该文件
已被 `.gitignore` 排除），daemon 会以工作区为工作目录读取它；改完后用
`cellwiki daemon restart --workspace <工作区>` 让新令牌生效。

端口也可以直接从发现文件读：`%XDG_RUNTIME_DIR%\cellwiki\daemon\<workspace-hash>\daemon.json`
（Windows 上通常回退到 `~\.cellwiki\daemon\<workspace-hash>\daemon.json`），其中
`port` 字段是监听端口。打包桌面形态的 sidecar 使用随机端口且不写发现文件，这时
请让部署方直接提供地址。

## 3. 接口合同

```http
POST /api/v1/annotation-support
Authorization: Bearer <CELLWIKI_ANNOTATION_API_TOKEN>
Content-Type: application/json
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `request_id` | string | 是 | 1–128 字符追踪编号，原样回显 |
| `species` | string | 是 | 物种，建议学名 |
| `tissue` | string | 是 | 当前样本组织 |
| `disease` | string \| null | 否 | 疾病背景；正常样本传 `null` |
| `cluster` | object | 是 | `id` 必填；可选 `n_cells`、`fraction_in_dataset`、`parent_cell_type`、`current_cell_type`、`current_confidence` |
| `top_markers` | array\<string\> | 是 | 1–50 个阳性 Marker，大小写不敏感去重 |
| `low_or_absent_markers` | array\<string\> | 否 | 最多 30 个**经表达量确认**低表达或未表达的鉴别 Marker；与 `top_markers` 不可重叠 |
| `max_candidates` | integer | 否 | 1–5，默认 3 |

未知字段、类型或范围错误一律返回 `400 INVALID_REQUEST`；第一版不接受表达矩阵、
单细胞记录、患者信息与作者真实标签。

### 响应字段

| 字段 | 说明 |
| --- | --- |
| `status` | `matched` / `ambiguous` / `no_match` |
| `recommendation` | 首选候选；`ambiguous` 与 `no_match` 时为 `null` |
| `alternative_candidates` | 其余候选（含并列候选） |
| `evidence` | 文献证据数组：`paper_id`、`title`、`doi`、`url`、`page_path`、`locator`（形如 `wiki/...md:L25`）、`evidence_tier` |
| `warnings` | 跨背景、证据不足等显式提示 |
| `knowledge_version` | 查询钉住的 Git 提交 SHA |
| `algorithm_version` | 合同版本，当前 `annotation-v1` |

候选对象含 `candidate_id`、`standard_name`、`display_name`、`aliases`、`parent_type`、
`ontology_id`、`support_level`（`strong`/`moderate`/`weak`，未校准启发式）、
`supporting_markers`、`expected_absent_markers`、`contradictory_markers`、
`context_match`（`species`/`tissue`/`disease`）、`rationale`、`evidence_ids`。
`support_score` 恒为 `null`：接口不提供概率，`support_level` 也不是置信度。

## 4. 响应怎么用

- `matched` → `recommendation` 是首选，`supporting_markers` 是支持它的输入 Marker，
  `evidence_ids` 指向 `evidence`。把这些证据交给 Validator 判断是否采纳。
- `ambiguous` → `recommendation` 为 `null`，并列候选在 `alternative_candidates`；
  **不要自动取第一个**，按证据与背景权衡，或补充证据后再问。
- `no_match` → 知识库里没有匹配证据。这不等于「该类型不存在」，更不能用先验硬编；
  走检索通道时仍要求 DOI 与行锚点。
- `context_match` 出现 `mismatched` / `cross_context` → 该候选的证据来自别的背景，
  `warnings` 会同步提示，需要降权而不是直接采信。
- `evidence_tier` 是知识库原始证据等级（Tier 1–5），不是注释置信度。
- `knowledge_version` 可当缓存键与复现键：同一 SHA 下同输入结果一致。

## 5. 错误与重试

| 状态 | 错误码 | 调用方动作 |
| --- | --- | --- |
| 200 | — | 正常处理（含 `no_match`） |
| 400 | `INVALID_REQUEST` | 修请求，不重试 |
| 401 | `UNAUTHORIZED` | 修令牌配置，不重试 |
| 503 | `SERVICE_DISABLED` | 部署方未启用接口，不重试 |
| 503 | `KNOWLEDGE_BUSY` | 按 `Retry-After: 5` 退避重试（知识正在更新或有未审批改动） |
| 503 | `KNOWLEDGE_UNAVAILABLE` | 退避重试；长期失败则降级 |
| 500 | `INTERNAL_ERROR` | 有限次重试 |

**不要把 5xx 当成 `no_match`**：那会把「服务此刻不可用」静默解释成「知识库里没有
这个亚型」，这种错误在结果里看不出来。

## 6. 调用纪律

- 接口无状态、不落库、不去重；`request_id` 只作追踪，重复查询请自己按
  (knowledge_version, payload) 缓存。
- 捕获阶段持有运行库写锁，查询会串行化；建议并发不超过 4，不要用几百并发打。
- 超时建议连接 10 秒、读取 60 秒；单次查询实测在亚秒级。
- 只传 Marker 与必要背景，不传表达矩阵、患者信息与作者标签。

## 7. 参考客户端

`scripts/annotation_client.py` 只用标准库，可直接拷进自己的项目。它负责取端口、
带令牌发请求、按错误语义重试与分类异常。

作为命令行：

```powershell
python scripts\annotation_client.py --workspace D:\kb `
  --species "Homo sapiens" --tissue colorectal_tumor `
  --markers GPR183,CD4,IL7R --absent FOXP3 --parent-cell-type cd4_pos_t_cell
```

作为库：

```python
from annotation_client import cellwiki_query, AnnotationBusyError

try:
    result = cellwiki_query(
        workspace=r"D:\kb",
        species="Homo sapiens",
        tissue="colorectal_tumor",
        top_markers=["GPR183", "CD4", "IL7R"],
        low_or_absent_markers=["FOXP3"],
    )
except AnnotationBusyError:
    ...  # 退避后重试
```

异常分类：`AnnotationRequestError`（400）、`AnnotationUnauthorizedError`（401）、
`AnnotationServiceDisabledError`、`AnnotationBusyError`、
`AnnotationUnavailableError`、`AnnotationUnreachableError`，都继承自
`AnnotationError`，带 `code` / `message` / `status` / `retryable`。

## 8. 联调自检

`scripts/annotation_smoke.py` 会启动 daemon（若未运行）、发一条真实查询、校验响应
合同并给出 PASS/FAIL 清单，随后关掉它自己启动的 daemon：

```powershell
python scripts\annotation_smoke.py --workspace D:\kb
```

校验项：状态取值合法、`recommendation` 只在 `matched` 时出现、候选的
`evidence_ids` 都能在 `evidence` 里找到、每条证据带论文与页面行号、证据等级在
Tier 1–5、`support_score` 恒为 `null`、`knowledge_version` 是提交 SHA、
`warnings` 是字符串数组。退出码 0 表示接通。

## 9. 已知边界

- 端口发现只覆盖 daemon 形态；打包桌面形态的 sidecar 是随机端口，需要部署方
  直接给地址。
- 覆盖范围就是知识库已经收录并批准的内容；未收录的类型只会返回 `no_match`。
- 接口不联网、不检索文献、不做知识更新；它是只读投影。
- 没有请求级幂等与限流；限流要由调用方自己做。
- 本接口不承诺注释准确率；准确率评估属于独立的评测流程。

## 10. 版本与变更

请求与响应的形状由 `algorithm_version` 标识（当前 `annotation-v1`）。字段语义或
错误码集合发生不兼容变化时会提升该版本，届时调用方应在解析处按版本分支。
