import { useMemo, useState } from 'react'

const SAMPLE = {
  allowed: '256, 257, 260, 512, 513',
  forbidden: '258, 259, 261, 768',
  limit: 4,
}

/** Parse free-form integer lists ("1, 2 3\n0x10") preserving tokens. */
function parseIdList(text) {
  const tokens = text.split(/[\s,，、;；]+/).filter(Boolean)
  const values = []
  const bad = []
  for (const tok of tokens) {
    const v = tok.toLowerCase().startsWith('0x')
      ? Number.parseInt(tok, 16)
      : Number(tok)
    if (!Number.isInteger(v)) bad.push(tok)
    else values.push(v)
  }
  return { values, bad, tokens }
}

function clientValidate(allowedText, forbiddenText, limitText) {
  const errors = {}
  const a = parseIdList(allowedText)
  const f = parseIdList(forbiddenText)
  const limit = Number(limitText)

  if (a.bad.length) errors.allowed = `无法解析：${a.bad.join('、')}`
  else if (a.values.some((v) => v < 0 || v > 2047))
    errors.allowed = '标识必须在 0 至 2047（0x7FF）之间。'
  else if (a.values.length < 2 || a.values.length > 20)
    errors.allowed = `允许标识须为 2 至 20 个互异整数（当前 ${a.values.length} 个）。`
  else if (new Set(a.values).size !== a.values.length) {
    const dup = a.values.filter((v, i) => a.values.indexOf(v) !== i)
    errors.allowed = `允许标识必须互异，重复：${[...new Set(dup)].join('、')}。`
  }

  if (f.bad.length) errors.forbidden = `无法解析：${f.bad.join('、')}`
  else if (f.values.some((v) => v < 0 || v > 2047))
    errors.forbidden = '标识必须在 0 至 2047（0x7FF）之间。'
  else if (f.values.length > 128)
    errors.forbidden = `禁用标识须为 0 至 128 个（当前 ${f.values.length} 个）。`

  if (!Number.isInteger(limit) || /^\s*$/.test(limitText))
    errors.limit = '上限必须是整数。'
  else if (limit < 1 || limit > 8) errors.limit = '上限必须为 1 至 8。'

  if (!errors.allowed && !errors.forbidden) {
    const overlap = a.values.filter((v) => new Set(f.values).has(v))
    if (overlap.length)
      errors.forbidden = `禁用标识不得与允许标识重叠，冲突：${[
        ...new Set(overlap),
      ].join('、')}。`
  }
  return errors
}

function BitPattern({ bits, highlight }) {
  return (
    <span className="bits">
      {bits.split('').map((ch, i) => (
        <span
          key={i}
          className={
            highlight
              ? ch === 'x'
                ? 'bit bit-x'
                : 'bit bit-fixed'
              : 'bit'
          }
        >
          {ch}
        </span>
      ))}
    </span>
  )
}

function FilterCard({ filter, allowed }) {
  return (
    <div className="filter-card">
      <header>
        <span className="filter-index">过滤器 #{filter.index + 1}</span>
        <span className="mono">
          mask={filter.mask_hex} code={filter.code_hex}
        </span>
      </header>
      <div className="pattern-grid">
        <div>
          <label>mask 位</label>
          <BitPattern bits={filter.mask_bin} />
        </div>
        <div>
          <label>code 位</label>
          <BitPattern bits={filter.code_bin} />
        </div>
        <div>
          <label>匹配模式（x = 不比较）</label>
          <BitPattern bits={filter.pattern} highlight />
        </div>
      </div>
      <div className="exposure">
        单项暴露数（可接受标识总数）：
        <strong>{filter.accepted_count}</strong>
        <span className="muted">
          {' '}
          = 2^{11 - filter.mask_bin.replaceAll('0', '').length}
        </span>
      </div>
      <div className="hits">
        命中允许项：
        {filter.hits.map((x) => (
          <span key={x} className="tag tag-hit">
            0x{x.toString(16).toUpperCase().padStart(3, '0')}
          </span>
        ))}
      </div>
    </div>
  )
}

function CoverageMatrix({ result }) {
  const allowed = result.coverage.map((c) => c.identifier)
  return (
    <div className="matrix-wrap">
      <h3>覆盖矩阵</h3>
      <p className="muted">
        行 = 过滤器，列 = 允许标识；● 表示该过滤器命中此允许项。
      </p>
      <table className="matrix">
        <thead>
          <tr>
            <th></th>
            {allowed.map((x) => (
              <th key={x} title={`十进制 ${x}`}>
                0x{x.toString(16).toUpperCase().padStart(3, '0')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.filters.map((f) => (
            <tr key={f.index}>
              <td className="row-head mono">
                #{f.index + 1} ({f.mask_hex},{f.code_hex})
              </td>
              {allowed.map((x) => {
                const hit = f.hits.includes(x)
                return (
                  <td key={x} className={hit ? 'cell-hit' : 'cell-miss'}>
                    {hit ? '●' : ''}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Evidence({ result }) {
  return (
    <details className="evidence">
      <summary>完整覆盖证据（每个允许标识至少被一个过滤器接收）</summary>
      <table className="evidence-table">
        <thead>
          <tr>
            <th>允许标识</th>
            <th>二进制</th>
            <th>被哪些过滤器接收</th>
          </tr>
        </thead>
        <tbody>
          {result.coverage.map((e) => (
            <tr key={e.identifier}>
              <td className="mono">
                {e.hex} <span className="muted">({e.identifier})</span>
              </td>
              <td className="mono">{e.bin}</td>
              <td>
                {e.accepted_by.map((i) => (
                  <span key={i} className="tag tag-hit">
                    #{i + 1}
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

export default function App() {
  const [allowedText, setAllowedText] = useState(SAMPLE.allowed)
  const [forbiddenText, setForbiddenText] = useState(SAMPLE.forbidden)
  const [limitText, setLimitText] = useState(String(SAMPLE.limit))
  const [errors, setErrors] = useState({})
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [networkError, setNetworkError] = useState(null)

  const clientErrors = useMemo(
    () => clientValidate(allowedText, forbiddenText, limitText),
    [allowedText, forbiddenText, limitText],
  )

  async function submit() {
    setNetworkError(null)
    const ce = clientValidate(allowedText, forbiddenText, limitText)
    setErrors(ce)
    if (Object.keys(ce).length) {
      setResult(null)
      return
    }
    const payload = {
      allowed: parseIdList(allowedText).values,
      forbidden: parseIdList(forbiddenText).values,
      limit: Number(limitText),
    }
    setLoading(true)
    try {
      const resp = await fetch('/api/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = await resp.json()
      if (!body.ok) setErrors(body.errors || {})
      setResult(body)
    } catch (e) {
      setNetworkError(`无法连接求解服务：${e.message}`)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const fieldError = (name) => errors[name] || clientErrors[name]

  return (
    <div className="page">
      <header className="page-header">
        <h1>CAN 验收过滤器审计台</h1>
        <p className="subtitle">
          11 位 CAN ID · 精确集合覆盖：先最少过滤器数，再最小可接受标识数之和，
          再取排序后 (mask, code) 字典序最小解
        </p>
      </header>

      <section className="panel">
        <h2>输入</h2>
        <div className="form-grid">
          <div className={fieldError('allowed') ? 'field invalid' : 'field'}>
            <label>
              允许标识（2–20 个互异整数，可用十进制或 0x 十六进制）
            </label>
            <textarea
              rows={2}
              value={allowedText}
              onChange={(e) => setAllowedText(e.target.value)}
              spellCheck={false}
            />
            {fieldError('allowed') && (
              <div className="error">{fieldError('allowed')}</div>
            )}
          </div>
          <div className={fieldError('forbidden') ? 'field invalid' : 'field'}>
            <label>禁用标识（0–128 个，不得与允许标识重叠）</label>
            <textarea
              rows={3}
              value={forbiddenText}
              onChange={(e) => setForbiddenText(e.target.value)}
              spellCheck={false}
            />
            {fieldError('forbidden') && (
              <div className="error">{fieldError('forbidden')}</div>
            )}
          </div>
          <div className={fieldError('limit') ? 'field invalid' : 'field'}>
            <label>过滤器上限（1–8）</label>
            <input
              type="number"
              min={1}
              max={8}
              value={limitText}
              onChange={(e) => setLimitText(e.target.value)}
            />
            {fieldError('limit') && (
              <div className="error">{fieldError('limit')}</div>
            )}
          </div>
        </div>
        <div className="actions">
          <button onClick={submit} disabled={loading}>
            {loading ? '求解中…' : '计算最优过滤器'}
          </button>
          <button
            className="secondary"
            onClick={() => {
              setAllowedText('')
              setForbiddenText('')
              setLimitText('4')
              setErrors({})
              setResult(null)
            }}
          >
            清空
          </button>
        </div>
        {networkError && <div className="error">{networkError}</div>}
      </section>

      {result?.ok && !result.feasible && (
        <section className="panel verdict verdict-exhausted">
          <h2>已穷尽：上限内无解</h2>
          <p>{result.message}</p>
          <p className="muted">
            求解器已枚举上限 {result.limit} 个过滤器内的全部可行组合并完成证否；
            输入已保留，可调整上限或禁用标识后重新计算。
          </p>
        </section>
      )}

      {result?.ok && result.feasible && (
        <>
          <section className="panel verdict verdict-ok">
            <h2>求解成功</h2>
            <div className="summary">
              <div>
                过滤器数：<strong>{result.filter_count}</strong>
                <span className="muted"> / 上限 {result.limit}</span>
              </div>
              <div>
                各过滤器可接受标识数之和：
                <strong>{result.total_accepted_count}</strong>
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>过滤器明细与二进制模式</h2>
            <div className="filters">
              {result.filters.map((f) => (
                <FilterCard key={f.index} filter={f} />
              ))}
            </div>
          </section>

          <section className="panel">
            <CoverageMatrix result={result} />
          </section>

          <section className="panel">
            <Evidence result={result} />
          </section>
        </>
      )}
    </div>
  )
}
