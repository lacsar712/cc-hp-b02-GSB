<script>
  const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1)

  let username = localStorage.getItem('herb_user') || 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let me = localStorage.getItem('herb_user') || ''
  let route = location.hash.replace(/^#/, '') || '/'

  let rows = []
  let herb = '白芍'
  let batchMonth = ''
  let tempC = 110
  let minutes = 10
  let error = ''

  let zones = []
  let zoneLog = []
  let zoneMonth = 3
  let zoneLow = 100
  let zoneHigh = 150
  let zoneError = ''
  let zoneMsg = ''

  window.addEventListener('hashchange', () => {
    route = location.hash.replace(/^#/, '') || '/'
    if (token) load()
  })

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      let msg = '请求失败'
      if (typeof data.detail === 'string') msg = data.detail
      else if (Array.isArray(data.detail) && data.detail.length)
        msg = data.detail.map((d) => d.msg || JSON.stringify(d)).join('；')
      throw new Error(msg)
    }
    return data
  }

  async function enter() {
    error = ''
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      token = data.access_token
      role = data.role
      me = data.username
      localStorage.setItem('herb_token', token)
      localStorage.setItem('herb_role', role)
      localStorage.setItem('herb_user', me)
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function load() {
    if (route === '/zones') {
      zones = await api('/api/season-zones')
      zoneLog = await api('/api/season-zones/log')
    } else {
      rows = await api('/api/batches')
    }
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          month: batchMonth === '' ? null : Number(batchMonth),
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function saveZone() {
    zoneError = ''
    zoneMsg = ''
    try {
      await api('/api/season-zones', {
        method: 'POST',
        body: JSON.stringify({ month: Number(zoneMonth), low_c: Number(zoneLow), high_c: Number(zoneHigh) }),
      })
      zoneMsg = `${zoneMonth} 月温区已改为 ${zoneLow}–${zoneHigh}℃，季节流水已追加一行`
      await load()
    } catch (err) {
      zoneError = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
    me = ''
  }

  function fmtTime(t) {
    return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—'
  }

  if (token) load()
</script>

<main>
  {#if !token}
    <h1>饮片炮制记录台</h1>
    <p>炮制记录整包保存，写入必须声明月份。清炒温度须落在当月季节温区内，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} placeholder="用户名" />
    <input type="password" bind:value={password} placeholder="密码" />
    <button on:click={enter}>登录</button>
    {#if error}<p class="err">{error}</p>{/if}
    <p class="hint">processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <span class="brand">饮片炮制记录台</span>
      <a href="#/" class:active={route !== '/zones'}>炮制记录</a>
      <a href="#/zones" class:active={route === '/zones'}>季节温区</a>
      <span class="spacer"></span>
      <span class="who">{me}（{role === 'writer' ? '炮制员' : '质检员'}）</span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if route === '/zones'}
      <h1>季节温区日历</h1>

      <section>
        <h2>十二月温区表</h2>
        <table>
          <thead>
            <tr><th>月份</th><th>温度下限（℃）</th><th>温度上限（℃）</th><th>最近调整人</th><th>调整时间</th></tr>
          </thead>
          <tbody>
            {#each zones as z}
              <tr>
                <td>{z.month} 月</td>
                <td>{z.low_c}</td>
                <td>{z.high_c}</td>
                <td>{z.changed_by || '—'}</td>
                <td>{fmtTime(z.changed_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>

      <section>
        <h2>改线区</h2>
        {#if role === 'writer'}
          <div class="formline">
            <label>月份
              <select bind:value={zoneMonth}>
                {#each MONTHS as m}
                  <option value={m}>{m} 月</option>
                {/each}
              </select>
            </label>
            <label>下限（℃）<input type="number" bind:value={zoneLow} /></label>
            <label>上限（℃）<input type="number" bind:value={zoneHigh} /></label>
            <button on:click={saveZone}>追加改线</button>
          </div>
          <p class="hint">改线只追加季节流水，早先流水行不被改写；新温区只约束改线之后提交的炮制记录。</p>
          {#if zoneMsg}<p class="ok">{zoneMsg}</p>{/if}
          {#if zoneError}<p class="err">{zoneError}</p>{/if}
        {:else}
          <p class="hint">质检员只读各月温区与流水，不能改线。</p>
        {/if}
      </section>

      <section>
        <h2>季节流水</h2>
        <table>
          <thead>
            <tr><th>序号</th><th>时间</th><th>月份</th><th>下限（℃）</th><th>上限（℃）</th><th>操作人</th></tr>
          </thead>
          <tbody>
            {#each zoneLog as row}
              <tr>
                <td>{row.id}</td>
                <td>{fmtTime(row.changed_at)}</td>
                <td>{row.month} 月</td>
                <td>{row.low_c}</td>
                <td>{row.high_c}</td>
                <td>{row.changed_by}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {:else}
      <h1>炮制记录</h1>
      {#if role === 'writer'}
        <div class="formline">
          <input bind:value={herb} placeholder="饮片" />
          <select bind:value={batchMonth}>
            <option value="">选择月份（必填）</option>
            {#each MONTHS as m}
              <option value={m}>{m} 月</option>
            {/each}
          </select>
          <input type="number" bind:value={tempC} placeholder="温度℃" />
          <input type="number" bind:value={minutes} placeholder="分钟" />
          <button on:click={save}>写入清炒记录</button>
        </div>
        {#if error}<p class="err">{error}</p>{/if}
      {/if}
      <ul>
        {#each rows as row}
          <li class={row.verdict === '放行' ? 'pass' : 'fail'}>
            {row.herb} · {row.doc.month ? row.doc.month + ' 月' : '未声明月份'} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}℃
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 860px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  h2 { color: #7c2d12; font-size: 1.1rem; margin-bottom: 8px; }
  input, select { margin-right: 8px; padding: 6px; }
  section { margin-bottom: 28px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #d6c8b8; padding: 6px 10px; text-align: left; }
  th { background: #f5ede2; }
  .topbar { display: flex; align-items: center; gap: 16px; background: #7c2d12; color: #fff; padding: 10px 16px; border-radius: 8px; margin-bottom: 20px; }
  .topbar .brand { font-weight: bold; }
  .topbar a { color: #f5d9c4; text-decoration: none; padding: 4px 8px; border-radius: 4px; }
  .topbar a.active { background: #9a3b17; color: #fff; font-weight: bold; }
  .topbar .spacer { flex: 1; }
  .topbar .who { font-size: 0.9rem; }
  .formline { margin-bottom: 8px; }
  .err { color: #b91c1c; }
  .ok { color: #15803d; }
  .hint { color: #8a7a68; font-size: 0.9rem; }
  li.pass { color: #15803d; }
  li.fail { color: #b91c1c; }
</style>
