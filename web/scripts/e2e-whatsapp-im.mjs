#!/usr/bin/env node
/**
 * Real-browser E2E for the three-platform IM forensics page.
 *
 * Verifies WhatsApp is a first-class platform alongside WeChat and QQ:
 * switch to it, open the import dialog, import a real iOS WhatsApp store,
 * then check every tab renders parsed data.
 *
 * Requires E2E_WHATSAPP_DIR pointing at a directory holding
 * ChatStorage.sqlite (and optionally ContactsV2/CallHistory).
 */

import puppeteer from 'puppeteer'
import fs from 'node:fs'
import path from 'node:path'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 1) {
  if (process.argv[i].startsWith('--')) {
    const key = process.argv[i].slice(2)
    const next = process.argv[i + 1]
    args.set(key, next && !next.startsWith('--') ? next : 'true')
  }
}

const BASE = process.env.E2E_BASE_URL || args.get('base') || 'http://127.0.0.1:4173'
const WA_DIR = process.env.E2E_WHATSAPP_DIR || args.get('dir') || ''
const OUTPUT = args.get('output') || '/tmp/tracelens-whatsapp-e2e.json'

const results = { base: BASE, whatsapp_dir: WA_DIR, steps: [], failures: [], created_import_id: null }

function record(name, ok, detail) {
  results.steps.push({ name, ok, detail })
  if (!ok) results.failures.push(`${name}: ${detail}`)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function bodyText(page) {
  return page.evaluate(() => (document.body ? document.body.innerText : ''))
}

async function waitForText(page, needle, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if ((await bodyText(page)).includes(needle)) return true
    await sleep(200)
  }
  return false
}

async function clickByText(page, text, { exact = false } = {}) {
  const box = await page.evaluate((needle, isExact) => {
    const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],label,option'))
    const target = nodes.find((el) => {
      const label = (el.innerText || el.textContent || '').trim()
      if (isExact ? label !== needle : !label.includes(needle)) return false
      const style = window.getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden') return false
      const rect = el.getBoundingClientRect()
      return rect.width > 0 && rect.height > 0
    })
    if (!target) return null
    const rect = target.getBoundingClientRect()
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }
  }, text, exact)
  if (!box) return false
  await page.mouse.click(box.x, box.y)
  return true
}

async function typeInto(page, selectorHint, value) {
  const point = await page.evaluate((hint) => {
    const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
      .filter((el) => !el.disabled && !el.readOnly && (el.offsetWidth || el.offsetHeight))
    const target = inputs.find((el) => (el.placeholder || '').includes(hint)) || inputs[0]
    if (!target) return null
    target.scrollIntoView({ block: 'center' })
    const rect = target.getBoundingClientRect()
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }
  }, selectorHint)
  if (!point) return false
  await page.mouse.click(point.x, point.y)
  // React controlled inputs drop characters typed in a tight loop; set the
  // value through the native setter and dispatch the events React listens to.
  const applied = await page.evaluate((hint, nextValue) => {
    const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
      .filter((el) => !el.disabled && !el.readOnly && (el.offsetWidth || el.offsetHeight))
    const target = inputs.find((el) => (el.placeholder || '').includes(hint)) || inputs[0]
    if (!target) return false
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(target, nextValue)
    target.dispatchEvent(new Event('input', { bubbles: true }))
    target.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }, selectorHint, value)
  if (!applied) return false
  // Verify the controlled state actually took the value.
  const readBack = await page.evaluate((hint) => {
    const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
      .filter((el) => !el.disabled && !el.readOnly && (el.offsetWidth || el.offsetHeight))
    const target = inputs.find((el) => (el.placeholder || '').includes(hint)) || inputs[0]
    return target ? target.value : ''
  }, selectorHint)
  return readBack === value
}

async function main() {
  if (!WA_DIR) throw new Error('E2E_WHATSAPP_DIR is required')
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 1000 })
  page.on('pageerror', (error) => results.failures.push(`pageerror: ${error.message}`))

  try {
    await page.goto(`${BASE}/im-forensics`, { waitUntil: 'networkidle2', timeout: 45000 })
    record('IM forensics page loads', true, `${BASE}/im-forensics`)

    const initial = await bodyText(page)
    record('WeChat platform present', initial.includes('微信'))
    record('QQ platform present', initial.includes('QQ'))
    record('WhatsApp platform present', initial.includes('WhatsApp'),
      initial.includes('WhatsApp') ? '' : 'WhatsApp not in the platform switcher')

    const switched = await clickByText(page, 'WhatsApp', { exact: true })
    record('switch to WhatsApp', switched)
    await sleep(2500)
    // Without an import selected the page shows the empty hint; the tab strip
    // appears once data is loaded, so this check only asserts the platform
    // shell and its import entry point.
    const waText = await bodyText(page)
    record('WhatsApp platform shell renders',
      waText.includes('即时通讯取证') && waText.includes('导入数据库'),
      waText.length > 100 ? `${waText.length} chars` : 'page did not render')

    // Open the import dialog and import the real store.
    const opened = await clickByText(page, '导入数据库')
    record('open WhatsApp import dialog', opened)
    await sleep(1500)
    const dialogVisible = await waitForText(page, '导入 WhatsApp 数据库', 8000)
    record('import dialog visible', dialogVisible)

    // The dialog's first field is the import name; the path field's placeholder
    // names the WhatsApp domain container, so match on that.
    const pathTyped = await typeInto(page, 'AppDomainGroup', WA_DIR)
    record('enter ChatStorage path', pathTyped, pathTyped ? WA_DIR : 'path input not found')
    await sleep(300)

    const submitted = await clickByText(page, '开始导入')
    record('submit import', submitted)

    // Success shows up as an import chip ("<name> — N 条消息") plus the tab
    // strip; the toast is transient, so wait on the durable signal instead.
    const imported = await waitForText(page, '条消息', 120000)
    record('import completes', imported)
    if (!imported) {
      // Capture what the browser actually sees so a failure is diagnosable.
      const diagnostic = await page.evaluate(() => ({
        text: document.body.innerText.slice(0, 600),
        dialogOpen: document.body.innerText.includes('导入 WhatsApp 数据库'),
        alerts: Array.from(document.querySelectorAll('[role="alert"]'))
          .map((el) => el.innerText.trim()).filter(Boolean),
      }))
      throw new Error(
        `import did not complete: dialogOpen=${diagnostic.dialogOpen} ` +
        `alerts=${JSON.stringify(diagnostic.alerts)} text=${JSON.stringify(diagnostic.text.slice(0, 300))}`,
      )
    }
    const chip = await page.evaluate(() => {
      const match = /([^\n]+) — ([0-9,]+) 条消息/.exec(document.body.innerText)
      return match ? { name: match[1].trim(), count: match[2] } : null
    })
    record('import chip shows message count', Boolean(chip),
      chip ? `${chip.name} — ${chip.count}` : 'chip text not matched')
    await sleep(2500)

    // The overview tab should show the parsed statistics.
    const overviewText = await bodyText(page)
    record('overview shows message total', /消息总数/.test(overviewText))
    record('overview shows group count', /群聊/.test(overviewText))

    // Sessions tab lists readable group names.
    await clickByText(page, '会话列表')
    await sleep(3000)
    const sessionsText = await bodyText(page)
    record('sessions tab lists conversations',
      sessionsText.includes('消息数') || sessionsText.includes('最后活跃'),
      sessionsText.length > 200 ? '' : 'sessions table missing')

    // Messages tab shows message bodies.
    await clickByText(page, '聊天记录')
    await sleep(4000)
    const messagesText = await bodyText(page)
    record('messages tab renders rows', messagesText.includes('共') || messagesText.includes('搜索'),
      messagesText.length > 200 ? '' : 'messages tab empty')

    // Contacts and chatrooms tabs must both render.
    await clickByText(page, '联系人')
    await sleep(3000)
    const contactsText = await bodyText(page)
    record('contacts tab renders', contactsText.includes('昵称') || contactsText.includes('号码'),
      contactsText.length > 150 ? '' : 'contacts tab empty')

    await clickByText(page, '群聊')
    await sleep(3000)
    const roomsText = await bodyText(page)
    record('chatrooms tab renders', roomsText.includes('群名称') || roomsText.includes('消息数'),
      roomsText.length > 150 ? '' : 'chatrooms tab empty')

    // Confirm through the API that the import really holds parsed rows.
    const imports = await page.evaluate(async () => {
      const response = await fetch('/python/api/whatsapp/forensics/imports')
      if (!response.ok) return null
      return await response.json()
    })
    const items = imports?.imports || []
    const latest = items[0]
    record('API reports a completed import', Boolean(latest) && latest.status === 'ready',
      latest ? `${latest.import_id} ${latest.stats?.total_messages} msgs` : 'no imports')
    if (latest) {
      results.created_import_id = latest.import_id
      record('import holds parsed messages', Number(latest.stats?.total_messages || 0) > 0,
        `total=${latest.stats?.total_messages}`)
      const cleaned = await page.evaluate(async (id) => {
        const response = await fetch(`/python/api/whatsapp/forensics/imports/${id}`, { method: 'DELETE' })
        return response.ok
      }, latest.import_id)
      record('cleanup deletes the test import', cleaned, cleaned ? '' : 'DELETE failed')
      if (cleaned) results.created_import_id = null
    }
  } catch (error) {
    results.failures.push(`exception: ${error.message}`)
    console.error('EXCEPTION', error.stack)
  } finally {
    await browser.close()
  }

  results.status = results.failures.length === 0 ? 'PASS' : 'FAIL'
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true })
  fs.writeFileSync(OUTPUT, JSON.stringify(results, null, 2))
  console.log(`\n${results.status}  (${results.steps.length} steps, ${results.failures.length} failures)`)
  console.log(`report: ${OUTPUT}`)
  process.exit(results.failures.length === 0 ? 0 : 1)
}

main()
