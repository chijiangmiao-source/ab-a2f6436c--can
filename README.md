# 11 位 CAN 验收过滤器审计台

无人机试验场用一组硬件 CAN 验收过滤器（`code/mask`）隔离飞控遥测：手工配置
掩码容易误收禁用报文，或投入并非最少的过滤器组。本项目提供一个**全栈审计台**：
React 页面编辑允许标识、禁用标识与过滤器上限，经真实 FastAPI 接口**精确求解**，
并以覆盖矩阵展示每个过滤器命中的允许项。

## 判定与优化规则

- CAN 标识为 11 位整数（0–2047）。
- 过滤器 `(code, mask)` 仅比较 mask 为 1 的位：命中条件 `(id & mask) == code`。
- code 未比较位（mask 为 0 的位）必须清零，服务端输出均为规范形式 `code & mask`。
- 每批允许标识 2–20 个互异整数；禁用标识 0–128 个；二者不得重叠；上限 1–8。
- 方案必须：覆盖全部允许标识，且不命中任何禁用标识。
- 优化目标（严格顺序）：
  1. 过滤器数量最少；
  2. 各过滤器可接受标识数之和最小（`Σ 2^(11−popcount(mask))`，mask 越具体越优）；
  3. 排序后的 `(mask, code)` 序列字典序最小。
- 若上限内无解，返回 `feasible=false, exhausted=true`，页面明确提示已穷尽并**保留输入**。
- 非法数据按字段反馈（`fields: {allowed|forbidden|limit: 消息}`）。

## 目录结构

```
backend/          FastAPI + 精确求解器（纯 Python，无第三方算法依赖）
  app/solver.py   候选枚举 + MRV 分支定界 DFS（可容许下界）
  app/main.py     /health、/api/info、/api/solve
  tests/          346 项测试，含 3–6 位空间对暴力穷举的随机对拍
frontend/         React 18 + Vite 构建，nginx 提供静态页并反代 API
verify/           compose 内的可执行验收服务 verify
docker-compose.yml
```

## 快速启动

```bash
cp .env.example .env          # 可选：调整宿主端口、健康检查参数
docker compose up --build
# Web 审计台:  http://localhost:8080   (WEB_PORT 可配)
# API:         http://localhost:8000   (API_PORT 可配)
```

停止：`docker compose down`。

### 可配置项（`.env`）

| 变量 | 默认 | 含义 |
|---|---|---|
| `WEB_PORT` | 8080 | Web 容器宿主机端口 |
| `API_PORT` | 8000 | API 容器宿主机端口 |
| `HEALTH_INTERVAL` | 10s | 健康检查间隔 |
| `HEALTH_TIMEOUT` | 3s | 健康检查超时 |
| `HEALTH_RETRIES` | 5 | 健康检查重试次数 |
| `HEALTH_START_PERIOD` | 5s | 健康检查启动宽限期 |
| `CORS_ORIGINS` | * | 允许跨域来源（api 服务环境变量） |

## 验收服务

```bash
docker compose run --rm verify
```

该服务等待 web/api 健康后：

1. 对**真实 HTTP 端点**做端到端检查（健康检查、SPA、可行/无解/字段校验）；
2. 运行后端全部 pytest 套件，其中包括在缩小的 3–6 位标识空间上与独立暴力
   穷举器逐案对拍（300+ 随机实例），验证「过滤器数 → 代价和 → 字典序」三级
   最优解完全一致。

## 本地开发（不使用 Docker）

```bash
# API
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Web（另开终端，/api 与 /health 已在 vite.config.js 代理到 :8000）
cd frontend
npm install
npm run dev
```

## 接口

### `POST /api/solve`

请求：

```json
{ "allowed": [256, 257, 258, 259], "forbidden": [260, 261], "limit": 4 }
```

成功响应（节选）：

```json
{
  "feasible": true,
  "exhausted": true,
  "candidate_count": 12,
  "filter_count": 1,
  "total_accepted": 4,
  "filters": [
    {
      "code": 256, "mask": 2044,
      "code_hex": "0x100", "mask_hex": "0x7FC",
      "code_bin": "00100000000", "mask_bin": "11111111100",
      "pattern": "001000000xx",
      "accepted_count": 4,
      "exposure_count": 0,
      "exposed_forbidden": [],
      "matched_allowed": [256, 257, 258, 259],
      "matched_allowed_count": 4
    }
  ],
  "coverage": [[true, true, true, true]],
  "allowed": [256, 257, 258, 259],
  "forbidden": [260, 261]
}
```

无解时 `feasible=false`、`filters=[]`，且回显 `allowed/forbidden/limit` 供页面
保留输入。非法输入返回 422：

```json
{ "detail": "输入数据非法", "fields": { "forbidden": "与允许标识重叠，同一标识不得禁用: [259]" } }
```

## 算法说明

1. **候选枚举**：遍历全部 2048 个 mask；对每个 mask，允许标识按投影 `id & mask`
   分组，code 即该投影（天然清零未比较位）；若任一禁用标识投影到同一 code，
   该候选非法。按代价（只取决于 mask 中 1 的个数，共 12 档）分桶，用极大覆盖
   反链做安全支配剪枝（只删除被**严格更便宜**候选覆盖超集的项；同价严格超集
   保留，以免破坏字典序最优）。
2. **精确搜索**：覆盖状态用单个机器字（≤20 位）。DFS 采用 MRV 分支——选取可选
   覆盖过滤器最少的未覆盖允许位，并以「解中覆盖该位的最小序号过滤器」做典范化
   分支，分支互斥、完备且不产生排列重复。下界使用「k 个过滤器新覆盖位并集 ≤
   各自贡献位数之和」的可容许界；单过滤器可终结时立即收束。
3. **最优性**：穷尽搜索完整维护现任最优 `(数量, 代价和, 排序键序列)`，保证三级
   目标序全局最优。20 允许 / 128 禁用的完整 11 位输入通常在数十毫秒内完成。
