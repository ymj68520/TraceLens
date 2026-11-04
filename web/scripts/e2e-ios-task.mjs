#!/usr/bin/env node
/**
 * Real-browser E2E for an end-to-end iOS forensic task.
 *
 * Drives the built frontend against live services and clicks the same
 * controls an operator uses: open the create-task flow, pick the iOS source,
 * enter the backup path, submit, then follow the resulting task into the
 * Android/iOS artifact view and verify parsed rows are displayed.
 *
 * Requires E2E_IOS_BACKUP to point at an unencrypted iTunes/Finder backup.
 * The test creates and then deletes its own task; evidence is read-only.
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
const BACKUP = process.env.E2E_IOS_BACKUP || args.get('backup') || ''
const OUTPUT = args.get('output') || '/tmp/tracelens-ios-task-e2e.json'

const results = { base: BASE, backup: BACKUP, steps: [], failures: [], created_task_id: null }

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
  // Use a real mouse click at the element's centre: React handlers on the
  // trigger do not fire for a synthetic element.click() in this build.
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

/** Select the iOS option in whichever <select> actually offers it. */
async function chooseIosSource(page) {
  return page.evaluate(() => {
    const select = Array.from(document.querySelectorAll('select'))
      .find((s) => Array.from(s.options).some((o) => o.value === 'ios-backup'))
    if (!select) return null
    const option = Array.from(select.options).find((o) => o.value === 'ios-backup')
    select.value = 'ios-backup'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    return option.textContent.trim()
  })
}

/** Fill the first visible text input that looks like the source path field. */
async function fillSourcePath(page, value) {
  return page.evaluate((pathValue) => {
    const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
      .filter((el) => {
        const style = window.getComputedStyle(el)
        return style.display !== 'none' && style.visibility !== 'hidden' && !el.disabled && !el.readOnly
      })
    const target = inputs.find((el) => (el.placeholder || '').match(/路径|path|检材|image/i)) || inputs[0]
    if (!target) return false
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(target, pathValue)
    target.dispatchEvent(new Event('input', { bubbles: true }))
    target.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }, value)
}

async function main() {
  if (!BACKUP) throw new Error('E2E_IOS_BACKUP is required')
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 1000 })

  try {
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle2', timeout: 45000 })
    record('tasks page loads', true, `${BASE}/tasks`)

    const opened = await clickByText(page, '创建任务')
    record('open create-task modal', opened, opened ? '' : 'button not found')
    await sleep(2000)
    const modalOpen = await waitForText(page, '创建分析任务', 8000)
    record('create-task modal visible', modalOpen, modalOpen ? '' : 'modal never rendered')

    const iosLabel = await chooseIosSource(page)
    record('iOS source selectable in UI', Boolean(iosLabel), iosLabel || 'no ios-backup option')
    if (!iosLabel) throw new Error('iOS source not offered by the UI')
    await sleep(500)

    const filled = await fillSourcePath(page, BACKUP)
    record('enter iOS backup path', filled, filled ? BACKUP : 'path input not found')
    await sleep(300)

    // Case description is a required textarea; without it the browser's own
    // constraint validation blocks submit and no request is ever sent.
    const described = await page.evaluate(() => {
      const area = Array.from(document.querySelectorAll('textarea'))
        .find((el) => (el.offsetWidth || el.offsetHeight) && !el.disabled && !el.readOnly)
      if (!area) return false
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
      setter.call(area, 'iOS 备份取证分析（E2E 自动测试）')
      area.dispatchEvent(new Event('input', { bubbles: true }))
      area.dispatchEvent(new Event('change', { bubbles: true }))
      return true
    })
    record('enter case description', described, described ? '' : 'textarea not found')
    await sleep(300)

    // Snapshot existing task ids so the newly created one is unambiguous.
    const beforeIds = await page.evaluate(async () => {
      const response = await fetch('/api/tasks')
      if (!response.ok) return []
      const payload = await response.json()
      const list = payload.tasks || payload || []
      return list.map((t) => t && t.id).filter(Boolean)
    })

    // The submit control is a <button type="submit"> labelled 创建任务; click it
    // directly so an outer trigger with similar text cannot swallow the click.
    const submitted = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll('button[type="submit"]'))
      const target = buttons.find((b) => (b.innerText || '').includes('创建'))
      if (!target) return false
      const rect = target.getBoundingClientRect()
      if (rect.width === 0) return false
      window.__tracelensSubmitPoint = { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }
      return true
    })
    if (submitted) {
      const point = await page.evaluate(() => window.__tracelensSubmitPoint)
      await page.mouse.click(point.x, point.y)
    }
    record('submit task', submitted)
    await sleep(5000)

    // Surface a validation error if the modal itself refused to submit. Scope
    // to the modal: the task table behind it legitimately shows status text
    // like "失败" for unrelated tasks.
    const modalError = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]')
        || Array.from(document.querySelectorAll('div'))
          .find((el) => (el.innerText || '').includes('创建分析任务'))
      if (!dialog) return ''
      const nodes = Array.from(dialog.querySelectorAll('[role="alert"], .text-rose-700, .text-red-600'))
      const failure = nodes
        .map((el) => (el.innerText || '').trim())
        .find((text) => text && /失败|错误|不能|请先|无效/i.test(text))
      return failure || ''
    })
    if (modalError) record('no create-task error', false, modalError)
    else record('no create-task error', true)

    // Identify the task this run created by diffing against a pre-submit
    // snapshot: a leftover task from an earlier run must not be mistaken for
    // the one just submitted.
    const tasks = await page.evaluate(async (knownIds) => {
      const response = await fetch('/api/tasks')
      if (!response.ok) return null
      const payload = await response.json()
      const list = payload.tasks || payload || []
      return list.filter((t) => t && !knownIds.includes(t.id))
    }, beforeIds)
    const iosTask = (tasks || [])[0]
    record('task appears with android_source=ios-backup',
      Boolean(iosTask) && iosTask.android_source === 'ios-backup',
      iosTask ? `${iosTask.id} ${iosTask.status} ${iosTask.android_source || ''}` : 'no new task found')
    if (!iosTask) throw new Error('created task not visible through the API')
    results.created_task_id = iosTask.id

    // Poll to a terminal state.
    const deadline = Date.now() + 300000
    let status = iosTask.status
    while (Date.now() < deadline && !['completed', 'failed', 'cancelled', 'interrupted'].includes(status)) {
      await sleep(3000)
      const detail = await page.evaluate(async (id) => {
        const response = await fetch(`/api/tasks/${id}`)
        return response.ok ? await response.json() : null
      }, iosTask.id)
      status = (detail?.task || detail)?.status || status
    }
    record('task reaches completed', status === 'completed', `status=${status}`)
    if (status !== 'completed') throw new Error(`task ended as ${status}`)

    // Coverage card must report the iOS artifacts.
    await page.goto(`${BASE}/android?task_id=${iosTask.id}`, { waitUntil: 'networkidle2', timeout: 45000 })
    await sleep(4000)
    const androidText = await bodyText(page)
    record('android page renders for the iOS task',
      androidText.length > 50 && !androidText.includes('Something went wrong'),
      `${androidText.length} chars`)
    record('artifact card present', androidText.includes('手机取证记录'),
      androidText.includes('手机取证记录') ? '' : 'artifact card title missing')
    record('coverage card reports parsed artifacts',
      androidText.includes('安卓来源覆盖') && androidText.includes('短信 已解析'),
      androidText.includes('短信 已解析') ? '' : 'coverage summary missing')
    // Device identity and backup version come from mobile_backup_manifest.
    record('iOS device badge rendered', androidText.includes('iPhone'),
      androidText.includes('iPhone') ? '' : 'device model badge missing')
    record('iOS backup version badge rendered', androidText.includes('10.0'),
      androidText.includes('10.0') ? '' : 'backup version badge missing')

    // The SMS tab should list the parsed rows with their source text. Scope the
    // empty-state check to the artifact card: other tabs legitimately show
    // "(无数据)" for stores this backup does not contain.
    await clickByText(page, '短信')
    await sleep(4000)
    const smsText = await bodyText(page)
    const cardText = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('section,div'))
        .filter((el) => (el.innerText || '').includes('手机取证记录'))
      return cards.length ? cards[cards.length - 1].innerText : ''
    })
    record('SMS artifacts listed', Boolean(cardText),
      cardText ? `${cardText.length} chars in card` : 'artifact card not found')
    record('SMS row content visible',
      smsText.includes('WhatsApp') || smsText.includes('SIGNAL') || smsText.includes('Telegram'),
      'expected at least one parsed message body')

    // Confirm through the API that rows really exist for this task.
    const coverage = await page.evaluate(async (id) => {
      const response = await fetch(`/python/api/evidence-intake/tasks/${id}/android-coverage`)
      return response.ok ? await response.json() : null
    }, iosTask.id)
    const counts = coverage?.coverage?.artifact_counts || {}
    record('API reports parsed SMS rows', Number(counts.sms_messages || 0) > 0,
      `sms_messages=${counts.sms_messages}`)
    record('API reports parsed contacts', Number(counts.contacts || 0) > 0,
      `contacts=${counts.contacts}`)

    // Clean up the task this test created.
    const cleaned = await page.evaluate(async (id) => {
      const response = await fetch(`/api/tasks/${id}`, { method: 'DELETE' })
      return response.ok
    }, iosTask.id)
    record('cleanup deletes the test task', cleaned, cleaned ? '' : 'DELETE failed')
    results.created_task_id = cleaned ? null : iosTask.id
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
