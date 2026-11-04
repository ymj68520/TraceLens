#!/usr/bin/env node
/**
 * Real-browser E2E for the iOS evidence path.
 *
 * Unlike scripts/browser_e2e.py this does NOT mock the API: it drives the
 * built frontend against a live Python service and a live C++ service, and it
 * clicks the same controls an operator would. Evidence stays read-only; the
 * test only ever submits preflight jobs against the configured inbox.
 *
 * Usage:
 *   node web/scripts/e2e-ios-evidence.mjs --stage preflight
 *   node web/scripts/e2e-ios-evidence.mjs --stage all
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
const STAGE = args.get('stage') || 'preflight'
const OUTPUT = args.get('output') || '/tmp/tracelens-ios-e2e.json'

const results = { stage: STAGE, base: BASE, steps: [], failures: [], console_errors: [] }

function record(name, ok, detail) {
  results.steps.push({ name, ok, detail })
  if (!ok) results.failures.push(`${name}: ${detail}`)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Click the first visible button/link whose text contains `text`. */
async function clickByText(page, text, { exact = false } = {}) {
  const handle = await page.evaluateHandle((needle, isExact) => {
    const candidates = Array.from(document.querySelectorAll('button,a,[role="button"],option'))
    return candidates.find((el) => {
      const label = (el.innerText || el.textContent || '').trim()
      if (isExact ? label !== needle : !label.includes(needle)) return false
      const style = window.getComputedStyle(el)
      return style.display !== 'none' && style.visibility !== 'hidden'
    }) || null
  }, text, exact)
  const element = handle.asElement()
  if (!element) return false
  await element.click()
  return true
}

async function textOf(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel)
    return el ? (el.innerText || el.textContent || '').trim() : null
  }, selector)
}

async function waitForText(page, text, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const body = await page.evaluate(() => document.body ? document.body.innerText : '')
    if (body.includes(text)) return true
    await sleep(150)
  }
  return false
}

async function main() {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })
  page.on('console', (msg) => {
    if (msg.type() === 'error') results.console_errors.push(msg.text())
  })
  page.on('pageerror', (err) => results.console_errors.push(`pageerror: ${err.message}`))

  try {
    // ---------- Preflight stage ----------
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle2', timeout: 45000 })
    record('tasks page loads', true, BASE + '/tasks')

    const panelPresent = await page.evaluate(() =>
      Boolean(document.querySelector('[data-testid="evidence-preflight-panel"]')))
    if (!panelPresent) {
      // The preflight panel opens from the "检材预检" toggle on the task list.
      const opened = await clickByText(page, '检材预检')
      record('open preflight panel', opened, opened ? '' : 'button not found')
      await sleep(1500)
    }

    const hasPanel = await page.evaluate(() =>
      Boolean(document.querySelector('[data-testid="evidence-preflight-panel"]')))
    record('preflight panel visible', hasPanel)
    if (!hasPanel) throw new Error('preflight panel never appeared')

    // The candidate <select> is populated from the live inbox.
    const options = await page.evaluate(() => {
      const select = document.querySelector('[data-testid="evidence-preflight-panel"] select[aria-label="候选检材"]')
      if (!select) return null
      return Array.from(select.options).map((o) => ({ value: o.value, label: o.textContent.trim() }))
    })
    record('candidate list loaded', Array.isArray(options) && options.length > 0,
      options ? `${options.length} option(s)` : 'select missing')

    const iosOption = (options || []).find((o) => o.label.includes('iOS'))
    record('iOS candidate recognised in UI', Boolean(iosOption),
      iosOption ? iosOption.label : 'no option labelled iOS')
    if (!iosOption) throw new Error('iOS candidate not offered by the UI')

    await page.select(
      '[data-testid="evidence-preflight-panel"] select[aria-label="候选检材"]',
      iosOption.value,
    )
    await sleep(300)

    const quickClicked = await clickByText(page, '快速识别')
    record('click 快速识别', quickClicked)
    // A directory preflight walks the tree, so wait for the terminal state
    // rather than a fixed delay; the summary only renders once detected lands.
    const quickDone = await waitForText(page, '预检完成', 60000)
    record('quick preflight completes', quickDone)

    const summaryText = await (async () => {
      const deadline = Date.now() + 20000
      while (Date.now() < deadline) {
        const text = await textOf(page, '[data-testid="ios-backup-summary"]')
        if (text) return text
        await sleep(200)
      }
      return null
    })()
    record('iOS summary block rendered', Boolean(summaryText),
      summaryText ? summaryText.split('\n')[0] : 'missing [data-testid=ios-backup-summary]')

    if (summaryText) {
      for (const [label, needle] of [
        ['device model shown', 'iPhone'],
        ['UDID shown', 'UDID'],
        ['artifact section shown', '可解析关键工件'],
      ]) {
        record(label, summaryText.includes(needle), needle)
      }
      const present = /可解析关键工件：([0-9]+) 类/.exec(summaryText)
      record('at least one artifact found', Boolean(present) && Number(present[1]) > 0,
        present ? `${present[1]} 类` : 'count not parsable')
    }

    // Full hash runs the manifest over the real backup.
    const fullClicked = await clickByText(page, '后台计算完整 SHA-256')
    record('click 后台计算完整 SHA-256', fullClicked)
    const hashDeadline = Date.now() + 240000
    let manifestShown = false
    while (Date.now() < hashDeadline) {
      const body = await page.evaluate(() => document.body.innerText)
      if (body.includes('目录文件清单摘要') || body.includes('逐文件哈希已计算')) {
        manifestShown = true
        break
      }
      await sleep(1000)
    }
    record('full-hash preflight reports manifest digest', manifestShown)

    const manifestText = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="evidence-preflight-panel"]')
      if (!panel) return ''
      const match = /目录文件清单摘要：([0-9a-f]{64})/.exec(panel.innerText)
      return match ? match[1] : ''
    })
    record('manifest digest is a 64-hex SHA-256', /^[0-9a-f]{64}$/.test(manifestText),
      manifestText || 'not rendered')

    // An empty error region is part of the pass condition.
    const alertText = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="evidence-preflight-panel"] [role="alert"]')
      return el ? el.innerText.trim() : ''
    })
    record('no preflight error alert', alertText === '', alertText)
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
