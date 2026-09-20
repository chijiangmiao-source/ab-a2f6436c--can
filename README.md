# CAN 验收过滤器审计台

无人机试验场场景：用最少的 11 位 CAN 验收过滤器（`code` / `mask`）隔离飞控
遥测标识，保证**全部允许标识被接收、任何禁用标识都不命中**。本仓库提供
React 编辑台 + FastAPI 精确求解器 + Docker Compose 一键启动 + 可执行验收
服务。

## 过滤规则

过滤器以 11 位 `code` 与 `mask` 表示：标识 `x` 被接收当且仅当
`(x & mask) == (code & mask)`；`code` 中 `mask` 为 0 的位必须清零（输出已
规范化保证）。

求解器在**上限 1–8 个过滤器**内精确搜索，并按以下顺序取最优：

1. 过滤器数量最少；
2. 各过滤器可接受标识数（`2^(11 - popcount(mask))`）之和最小；
3. 再按排序后的 `(mask, code)` 序列取字典序最小。

上限内无解时返回"已穷尽"结论（搜索为带备忘录的精确集合覆盖 DP，含集合打包
下界、可行性备忘录与贪心预算，结论完备）。

## 快速启动

```bash
cp .env.example .env        # 可选：调整宿主端口/健康检查
docker compose up --build
```

- Web 审计台：http://localhost:8080 （`WEB_PORT` 可配置）
- API 文档：http://localhost:8000/docs （`API_PORT` 可配置）
- 健康检查：`GET /health`（Web 经 nginx 反代，API 直连均可）

## 验收服务

```bash
docker compose --profile acceptance run --rm verify
```

该服务等待 web/api 健康后执行：求解器单元测试（含与暴力枚举预言机的等价性）
+ 对运行中栈的黑盒端到端检查（健全性、最优性、逐字段校验、穷尽结论、覆盖
证据、边界规模），任一失败即以非零码退出。

## 本地开发（无 Docker）

```bash
# 后端
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（:5173，自动代理 /api 到 :8000）
cd frontend
npm install
npm run dev
```

后端测试：`cd backend && python -m pytest -q`

## 目录结构

```
backend/            FastAPI 应用与精确求解器
  app/solver.py     候选子立方体枚举 + 两阶段（可行性/最优）记忆化 DP
  app/main.py       /api/solve、/health、逐字段校验、证据构造
  test_*.py         求解器与 API 测试
frontend/           React + Vite 页面（编辑、覆盖矩阵、二进制模式、证据）
  nginx.conf        生产镜像内 /api 与 /health 反代到 api 服务
acceptance/         verify 验收服务（标准库实现的端到端检查）
docker-compose.yml  web / api / verify 三服务
```

## API

`POST /api/solve`

```json
{ "allowed": [256, 257], "forbidden": [258], "limit": 2 }
```

- 非法输入：`{ "ok": false, "errors": { "allowed": "...", ... } }`（按字段反馈）
- 无解：`{ "ok": true, "feasible": false, "message": "已穷尽……" }`
- 成功：过滤器数组（hex/二进制/`x` 通配模式、单项暴露数、命中允许项）、
  过滤器数与暴露数总和、逐允许标识的覆盖证据、逐禁用标识的拒收证据。
