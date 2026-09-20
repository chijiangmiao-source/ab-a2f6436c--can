import { useMemo, useState } from 'react'

const ID_MAX = 2047

function parseIds(text) {
  const tokens = text.split(/[\s,，、;；]+/).filter(Boolean)
  const ids = []
  for (const t of tokens) {
    if (!/^-?\d+$/.test(t)) return { error: `无法解析的标识: “${t}”`, ids: [] }
    ids.push(parseInt(t, 10))
  }
  return { ids }
}

const EXAMPLES = [
  {
    name: '邻近遥测（可合并）',
    allowed: '256, 257, 258, 259',
    forbidden: '260, 261',
    limit: 4,
  },
  {
    name: '禁用报文阻隔（无解上限 1）',
    allowed: '256, 259',
    forbidden: '257, 258',
    limit: 1,
  },
  {
    name: '分散遥测 + 密集禁用',
    allowed: '100, 320, 640, 960, 1280, 1600',
    forbidden: '101, 321, 641, 961, 1281, 1601, 777',
    limit: 8,
  },
]

function FieldError({ children }) {
  if (!children) return null
  return <div className="field-error">{children}</div>
}

function BitPattern({ codeBin, maskBin }) {
  // Render 11 bit columns: mask bits show code value 0/1, wildcard shows x.
  return (
    <div className="bits">
      {maskBin.split('').map((m, i) => {
        const compared = m === '1'
        return (
          <span key={i} className={`bit ${compared ? 'bit-cmp' : 'bit-wild'}`}>
            {compared ? codeBin[i] : 'x'}
          </span>
        )
      })}
    </div>
  )
}

function FilterCard({ f }) {
  return (
    <div className="filter-card">
      <div className="filter-head">
        <span className="filter-index">#{f.index}</span>
        <span className="filter-hx">
          mask <code>{f.mask_hex}</code> / code <code>{f.code_hex}</code>
        </span>
      </div>
      <div className="filter-rows">
        <div className="frow">
          <span className="flabel">mask</span>
          <BitPattern codeBin={f.mask_bin} maskBin={f.mask_bin} />
          <span className="fval">0x{f.mask.toString(16).toUpperCase().padStart(3, '0')}</span>
        </div>
        <div className="frow">
          <span className="flabel">code</span>
          <BitPattern codeBin={f.code_bin} maskBin={f.mask_bin} />
          <span className="fval">0x{f.code.toString(16).toUpperCase().padStart(3, '0')}</span>
        </div>
        <div className="frow">
          <span className="flabel">模式</span>
          <div className="bits">
            {f.pattern.split('').map((ch, i) => (
              <span
                key={i}
                className={`bit ${ch === 'x' ? 'bit-wild' : 'bit-fixed'}`}
                title={ch === 'x' ? `第 ${10 - i} 位不比较` : `第 ${10 - i} 位 = ${ch}`}
              >
                {ch}
              </span>
            ))}
          </div>
        </div>
      </div>
      <div className="filter-stats">
        <span>
          可接受标识数：<strong>{f.accepted_count}</strong> / 2048
        </span>
        <span className={f.exposure_count === 0 ? 'ok' : 'bad'}>
          命中禁用项：<strong>{f.exposure_count}</strong>
        </span>
        <span>
          命中允许项：<strong>{f.matched_allowed_count}</strong> 个 →{' '}
          {f.matched_allowed.map((x) => x.toString(10)).join(', ')}
        </span>
      </div>
    </div>
  )
}

function CoverageMatrix({ result }) {
  const { filters, coverage, allowed } = result
  return (
    <div className="matrix-wrap">
      <table className="matrix">
        <thead>
          <tr>
            <th>过滤器 ＼ 允许标识</th>
            {allowed.map((id) => (
              <th key={id}>
                <div className="col-id">{id}</div>
                <div className="col-hex">0x{id.toString(16).toUpperCase().padStart(3, 'X')}</div>
              </th>
            ))}
            <th>命中数</th>
          </tr>
        </thead>
        <tbody>
          {filters.map((f, r) => (
            <tr key={r}>
              <td className="row-label">
                #{f.index}{' '}
                <span className="row-mc">
                  {f.mask_hex}/{f.code_hex}
                </span>
              </td>
              {coverage[r].map((hit, c) => (
                <td key={c} className={hit ? 'hit' : 'miss'}>
                  {hit ? '✓' : '·'}
                </td>
              ))}
              <td className="count-cell">{f.matched_allowed_count}</td>
            </tr>
          ))}
          <tr className="evidence-row">
            <td className="row-label">每列覆盖证据</td>
            {allowed.map((_, c) => {
              const hitBy = filters
                .map((f, i) => (coverage[i][c] ? f.index : null))
                .filter((x) => x !== null)
              return (
                <td key={c} className={hitBy.length > 0 ? 'ev-ok' : 'ev-bad'}>
                  {hitBy.length > 0 ? hitBy.map((n) => `#${n}`).join(',') : '未覆盖'}
                </td>
              )
            })}
            <td className="count-cell">—</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default function App() {
  const [allowedText, setAllowedText] = useState('256, 257, 258, 259')
  const [forbiddenText, setForbiddenText] = useState('260, 261')
  const [limitText, setLimitText] = useState('4')
  const [clientErrors, setClientErrors] = useState({})
  const [serverFields, setServerFields] = useState({})
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [requestError, setRequestError] = useState(null)

  const localCounts = useMemo(() => {
    const a = parseIds(allowedText)
    const f = parseIds(forbiddenText)
    return {
      allowedCount: a.ids ? a.ids.length : null,
      forbiddenCount: f.ids ? f.ids.length : null,
    }
  }, [allowedText, forbiddenText])

  function applyExample(ex) {
    setAllowedText(ex.allowed)
    setForbiddenText(ex.forbidden)
    setLimitText(String(ex.limit))
    setClientErrors({})
    setServerFields({})
    setResult(null)
    setRequestError(null)
  }

  function validate(allowed, forbidden, limit) {
    const errs = {}
    if (allowed.error) errs.allowed = allowed.error
    if (forbidden.error) errs.forbidden = forbidden.error

    if (!errs.allowed) {
      if (allowed.ids.length < 2 || allowed.ids.length > 20)
        errs.allowed = `允许标识数量必须为 2 至 20 个（当前 ${allowed.ids.length} 个）`
      else if (new Set(allowed.ids).size !== allowed.ids.length) errs.allowed = '允许标识不得重复'
      else if (allowed.ids.some((x) => x < 0 || x > ID_MAX)) errs.allowed = '标识必须在 0 至 2047 之间'
    }
    if (!errs.forbidden) {
      if (forbidden.ids.length > 128)
        errs.forbidden = `禁用标识数量必须为 0 至 128 个（当前 ${forbidden.ids.length} 个）`
      else if (new Set(forbidden.ids).size !== forbidden.ids.length) errs.forbidden = '禁用标识不得重复'
      else if (forbidden.ids.some((x) => x < 0 || x > ID_MAX)) errs.forbidden = '标识必须在 0 至 2047 之间'
    }
    if (!errs.allowed && !errs.forbidden) {
      const ov = allowed.ids.filter((x) => forbidden.ids.includes(x))
      if (ov.length) errs.forbidden = `与允许标识重叠: ${[...new Set(ov)].join(', ')}`
    }
    if (!/^\d+$/.test(limit.trim())) errs.limit = '上限必须是 1 到 8 之间的整数'
    else {
      const n = parseInt(limit, 10)
      if (n < 1 || n > 8) errs.limit = '上限必须在 1 到 8 之间'
    }
    return errs
  }

  async function onSubmit(e) {
    e.preventDefault()
    setRequestError(null)
    setServerFields({})
    const allowed = parseIds(allowedText)
    const forbidden = parseIds(forbiddenText)
    const errs = validate(allowed, forbidden, limitText)
    setClientErrors(errs)
    if (Object.keys(errs).length) {
      setResult(null)
      return
    }

    setLoading(true)
    try {
      const resp = await fetch('/api/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          allowed: allowed.ids,
          forbidden: forbidden.ids,
          limit: parseInt(limitText, 10),
        }),
      })
      const data = await resp.json()
      if (resp.status === 422) {
        setServerFields(data.fields || {})
        setResult(null)
        return
      }
      if (!resp.ok) {
        setRequestError(data.detail || `服务错误 (${resp.status})`)
        setResult(null)
        return
      }
      setResult(data)
    } catch (err) {
      setRequestError(`无法连接计算服务: ${err.message}`)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const fieldErr = (name) => clientErrors[name] || serverFields[name]

  return (
    <div className="page">
      <header>
        <h1>11 位 CAN 验收过滤器审计台</h1>
        <p className="subtitle">
          精确隔离飞控遥测：仅比较 mask 为 1 的位（<code>(id &amp; mask) == code</code>），
          穷尽搜索过滤器数最少、可接受标识总量最小、(mask, code) 字典序最优的方案。
        </p>
      </header>

      <section className="examples">
        <span>示例：</span>
        {EXAMPLES.map((ex) => (
          <button key={ex.name} type="button" className="example-btn" onClick={() => applyExample(ex)}>
            {ex.name}
          </button>
        ))}
      </section>

      <form onSubmit={onSubmit} className="panel form-panel" noValidate>
        <div className="form-grid">
          <div className={`field ${fieldErr('allowed') ? 'invalid' : ''}`}>
            <label htmlFor="allowed">
              允许标识（2–20 个互异整数，0–2047）
              {localCounts.allowedCount !== null && (
                <span className="counter">{localCounts.allowedCount} 个</span>
              )}
            </label>
            <textarea
              id="allowed"
              rows={3}
              value={allowedText}
              onChange={(e) => setAllowedText(e.target.value)}
              placeholder="例如: 256, 257, 258"
            />
            <FieldError>{fieldErr('allowed')}</FieldError>
          </div>

          <div className={`field ${fieldErr('forbidden') ? 'invalid' : ''}`}>
            <label htmlFor="forbidden">
              禁用标识（0–128 个，不得与允许项重叠）
              {localCounts.forbiddenCount !== null && (
                <span className="counter">{localCounts.forbiddenCount} 个</span>
              )}
            </label>
            <textarea
              id="forbidden"
              rows={3}
              value={forbiddenText}
              onChange={(e) => setForbiddenText(e.target.value)}
              placeholder="例如: 260, 777"
            />
            <FieldError>{fieldErr('forbidden')}</FieldError>
          </div>

          <div className={`field ${fieldErr('limit') ? 'invalid' : ''}`}>
            <label htmlFor="limit">过滤器上限（1–8）</label>
            <input
              id="limit"
              type="number"
              min={1}
              max={8}
              value={limitText}
              onChange={(e) => setLimitText(e.target.value)}
            />
            <FieldError>{fieldErr('limit')}</FieldError>
          </div>
        </div>

        <div className="form-actions">
          <button type="submit" disabled={loading} className="primary-btn">
            {loading ? '计算中…' : '计算最优过滤器配置'}
          </button>
          {requestError && <span className="field-error">{requestError}</span>}
        </div>
      </form>

      {result && (
        <section className="result">
          <div className={`banner ${result.feasible ? 'banner-ok' : 'banner-exhausted'}`}>
            <strong>{result.feasible ? '✓ 找到最优配置' : '⊘ 已穷尽，上限内无解'}</strong>
            <span>{result.message}</span>
          </div>

          {result.feasible ? (
            <>
              <div className="panel summary">
                <div>
                  <div className="metric">{result.filter_count}</div>
                  <div className="metric-label">过滤器数（上限 {result.limit}）</div>
                </div>
                <div>
                  <div className="metric">{result.total_accepted}</div>
                  <div className="metric-label">各过滤器可接受标识数之和</div>
                </div>
                <div>
                  <div className="metric">{result.candidate_count}</div>
                  <div className="metric-label">评估的候选过滤器数</div>
                </div>
                <div>
                  <div className="metric ok">0</div>
                  <div className="metric-label">禁用标识总暴露数</div>
                </div>
              </div>

              <h2>过滤器明细（二进制模式 / 暴露数）</h2>
              <div className="filter-grid">
                {result.filters.map((f) => (
                  <FilterCard key={f.index} f={f} />
                ))}
              </div>

              <h2>覆盖矩阵（每个过滤器命中的允许项）</h2>
              <CoverageMatrix result={result} />
              <p className="evidence-note">
                底部「每列覆盖证据」行列出命中该允许标识的过滤器编号，全部非空即构成完整覆盖；
                每张卡片的「命中禁用项」恒为 0，构成零暴露证据。
              </p>
            </>
          ) : (
            <div className="panel exhausted-detail">
              <p>
                求解器已在过滤器上限 <strong>{result.limit}</strong> 内穷尽全部{' '}
                <strong>{result.candidate_count}</strong> 个不命中禁用项的候选过滤器组合：
                没有任何组合能够同时覆盖全部 {result.allowed.length} 个允许标识。
              </p>
              <p>可尝试：提高过滤器上限，或复核禁用/允许标识集合。输入已保留，可直接修改后重新计算。</p>
              <div className="retained">
                <div>
                  <strong>允许标识：</strong>
                  {result.allowed.join(', ')}
                </div>
                <div>
                  <strong>禁用标识：</strong>
                  {result.forbidden.length ? result.forbidden.join(', ') : '（空）'}
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      <footer>
        目标序：①过滤器数 ②可接受标识数之和（mask 越具体越小）③排序后 (mask, code) 字典序。
        code 未比较位必须为 0，服务端输出均为规范形式。
      </footer>
    </div>
  )
}
