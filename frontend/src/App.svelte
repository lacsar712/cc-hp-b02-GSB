<script>
  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let view = 'batches'
  let rows = []
  let herb = '白芍'
  let month = ''
  let tempC = 110
  let minutes = 10
  let error = ''
  let zones = []
  let ledger = []
  let zMonth = 1
  let zLow = 80
  let zHigh = 150
  let seasonError = ''
  let seasonMsg = ''

  const months = Array.from({ length: 12 }, (_, i) => i + 1)

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function loadSeasons() {
    zones = await api('/api/season-zones')
    ledger = await api('/api/season-ledger')
  }

  async function show(v) {
    view = v
    seasonError = ''
    seasonMsg = ''
    if (v === 'seasons') {
      try {
        await loadSeasons()
      } catch (err) {
        seasonError = err.message
      }
    }
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          month: month === '' ? null : Number(month),
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function saveZone() {
    seasonError = ''
    seasonMsg = ''
    try {
      await api('/api/season-zones', {
        method: 'POST',
        body: JSON.stringify({ month: Number(zMonth), low_c: Number(zLow), high_c: Number(zHigh) }),
      })
      seasonMsg = `已追加 ${zMonth} 月温区流水，新线只约束之后的提交`
      await loadSeasons()
    } catch (err) {
      seasonError = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
  }

  function fmtTime(s) {
    return new Date(s).toLocaleString()
  }

  if (token) load()
</script>

<main>
  <h1>饮片炮制记录台</h1>
  {#if !token}
    <p>炮制记录整包保存，写入必须声明月份。清炒温度按当月季节温区判定（默认 80 到 150），时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <a href="/" class:active={view === 'batches'} on:click|preventDefault={() => show('batches')}>炮制记录</a>
      <a href="/seasons" class:active={view === 'seasons'} on:click|preventDefault={() => show('seasons')}>季节温区</a>
      <span class="who">{role === 'writer' ? '炮制员' : '质检员'} {username}</span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if view === 'batches'}
      {#if role === 'writer'}
        <p>
          <input bind:value={herb} placeholder="饮片" />
          <select bind:value={month}>
            <option value="">声明月份</option>
            {#each months as m}
              <option value={m}>{m} 月</option>
            {/each}
          </select>
          <input type="number" bind:value={tempC} />
          <input type="number" bind:value={minutes} />
          <button on:click={save}>写入清炒记录</button>
        </p>
        {#if error}<p class="err">{error}</p>{/if}
      {/if}
      <ul>
        {#each rows as row}
          <li>
            {row.herb} · {row.doc.month ? `${row.doc.month} 月 · ` : ''}{row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}
          </li>
        {/each}
      </ul>
    {:else}
      <h2>十二月温区表</h2>
      <table>
        <thead>
          <tr><th>月份</th><th>清炒温度下限 ℃</th><th>清炒温度上限 ℃</th></tr>
        </thead>
        <tbody>
          {#each zones as z}
            <tr><td>{z.month} 月</td><td>{z.low_c}</td><td>{z.high_c}</td></tr>
          {/each}
        </tbody>
      </table>

      <h2>改线区</h2>
      {#if role === 'writer'}
        <p>
          <select bind:value={zMonth}>
            {#each months as m}
              <option value={m}>{m} 月</option>
            {/each}
          </select>
          <input type="number" bind:value={zLow} placeholder="下限" />
          <input type="number" bind:value={zHigh} placeholder="上限" />
          <button on:click={saveZone}>改线并追加季节流水</button>
        </p>
      {:else}
        <p>质检员只读各月温区与流水，不能改线。</p>
      {/if}
      {#if seasonError}<p class="err">{seasonError}</p>{/if}
      {#if seasonMsg}<p class="ok">{seasonMsg}</p>{/if}

      <h2>季节流水</h2>
      <ul>
        {#each ledger as row}
          <li>#{row.id} · {row.month} 月 · {row.low_c} ~ {row.high_c} ℃ · {row.created_by} · {fmtTime(row.created_at)}</li>
        {/each}
      </ul>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 720px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  h2 { color: #7c2d12; font-size: 18px; margin-top: 28px; }
  input, select { margin-right: 8px; padding: 6px; }
  .topbar { display: flex; align-items: center; gap: 16px; padding: 10px 0; border-bottom: 2px solid #7c2d12; margin-bottom: 16px; }
  .topbar a { color: #7c2d12; text-decoration: none; padding-bottom: 2px; }
  .topbar a.active { font-weight: bold; border-bottom: 2px solid #7c2d12; }
  .topbar .who { margin-left: auto; color: #8a6d4b; }
  table { border-collapse: collapse; }
  th, td { border: 1px solid #d6c3ae; padding: 6px 14px; text-align: left; }
  th { background: #f5ead9; }
  .err { color: #b91c1c; }
  .ok { color: #15803d; }
</style>
