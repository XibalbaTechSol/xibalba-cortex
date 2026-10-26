// Sign-in, password reset and account administration, against the real API where the fixture can
// answer for real, and with a stubbed response only where it cannot (a working mail server, a
// valid emailed secret). Each stub is named as such in its test.
import { expect, test } from '@playwright/test'
import { openConsole } from './helpers'

const TOKEN = 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v' // 43 URL-safe characters, the shape of a real one

test.describe('forgot password', () => {
  test('an address with no account gets the neutral answer from the real API (no way to probe for accounts)', async ({ page }) => {
    await openConsole(page, { signedOut: true })
    await page.getByRole('button', { name: 'Forgot password?' }).click()
    await expect(page.getByRole('heading', { name: 'Reset your password' })).toBeVisible()
    await page.getByLabel('Email').fill('nobody-has-this@example.com')
    await page.getByRole('button', { name: 'Send reset link' }).click()
    await expect(page.getByRole('status')).toContainText(/If an account exists for that address/)
    await page.getByRole('button', { name: 'Back to sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  })

  test('a server with no mail delivery says so, plainly (stubbed 503: the real server only does this for an existing account)', async ({ page }) => {
    await page.route('**/cortex-api/api/auth/password-reset/request', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"password reset delivery is unavailable"}' }))
    await openConsole(page, { signedOut: true })
    await page.getByRole('button', { name: 'Forgot password?' }).click()
    await page.getByLabel('Email').fill('operator@example.com')
    await page.getByRole('button', { name: 'Send reset link' }).click()
    await expect(page.getByRole('alert')).toContainText(/cannot send email/i)
  })

  test('says the same thing for any address (stubbed 200: needs a working mail server)', async ({ page }) => {
    await page.route('**/cortex-api/api/auth/password-reset/request', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true,"delivery":"email"}' }))
    await openConsole(page, { signedOut: true })
    const texts: string[] = []
    for (const address of ['has-an-account@example.com', 'never-heard-of-you@example.com']) {
      await page.getByRole('button', { name: /Forgot password\?|Back to sign in/ }).first().click().catch(() => {})
      if (!(await page.getByRole('heading', { name: 'Reset your password' }).count())) await page.getByRole('button', { name: 'Forgot password?' }).click()
      await page.getByLabel('Email').fill(address)
      await page.getByRole('button', { name: 'Send reset link' }).click()
      const note = page.getByRole('status').filter({ hasText: /If an account exists/ })
      await expect(note).toBeVisible()
      texts.push((await note.innerText()).trim())
    }
    expect(texts[0]).toBe(texts[1]) // no way to tell which addresses have accounts
  })

  test('asking too often is rate limited and says when to retry (stubbed 429)', async ({ page }) => {
    await page.route('**/cortex-api/api/auth/password-reset/request', (r) => r.fulfill({ status: 429, contentType: 'application/json', body: '{"error":"too many authentication attempts; try again later"}' }))
    await openConsole(page, { signedOut: true })
    await page.getByRole('button', { name: 'Forgot password?' }).click()
    await page.getByLabel('Email').fill('operator@example.com')
    await page.getByRole('button', { name: 'Send reset link' }).click()
    await expect(page.getByRole('alert')).toContainText(/Too many attempts/)
  })
})

test.describe('reset password (the page the emailed link opens)', () => {
  const open = async (page: import('@playwright/test').Page) => {
    await page.addInitScript(() => { try { sessionStorage.removeItem('xibalba-cortex.signed-in') } catch { /* ignore */ } })
    await page.goto(`/?token=${TOKEN}#graph`)
    await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible()
  }

  test('opens the reset form and removes the secret from the address bar', async ({ page }) => {
    await open(page)
    expect(page.url()).not.toContain(TOKEN)
    expect(page.url()).not.toContain('token=')
    await expect(page.getByLabel('New password', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Confirm new password')).toBeVisible()
  })

  test('refuses a mismatch or a short password before sending anything', async ({ page }) => {
    let sent = 0
    await page.route('**/cortex-api/api/auth/password-reset/confirm', (r) => { sent++; return r.abort() })
    await open(page)
    await page.getByLabel('New password', { exact: true }).fill('a-long-enough-one')
    await page.getByLabel('Confirm new password').fill('a-different-one-x')
    await page.getByRole('button', { name: 'Change password' }).click()
    await expect(page.getByRole('alert')).toContainText(/do not match/)
    expect(sent).toBe(0)
  })

  test('a link the server does not recognise is reported as invalid or expired (real API)', async ({ page }) => {
    await open(page)
    await page.getByLabel('New password', { exact: true }).fill('a-long-enough-one')
    await page.getByLabel('Confirm new password').fill('a-long-enough-one')
    await page.getByRole('button', { name: 'Change password' }).click()
    await expect(page.getByRole('alert')).toContainText(/invalid or has expired/)
  })

  test('success returns to sign-in with a plain notice (stubbed 200: needs a valid emailed secret)', async ({ page }) => {
    await page.route('**/cortex-api/api/auth/password-reset/confirm', async (r) => {
      const body = r.request().postDataJSON()
      expect(body).toEqual({ reset_token: TOKEN, new_password: 'a-long-enough-one' }) // what the server is sent
      await r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
    })
    await open(page)
    await page.getByLabel('New password', { exact: true }).fill('a-long-enough-one')
    await page.getByLabel('Confirm new password').fill('a-long-enough-one')
    await page.getByRole('button', { name: 'Change password' }).click()
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
    await expect(page.getByRole('status')).toContainText('Password changed. Sign in with the new password.')
  })
})

// ---------------------------------------------------------------------------------------------
// Settings → Access and Profile run against the real API: the dev proxy's credential is an operator
// token, so token management works for real and approving accounts is (correctly) refused.
const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 28420}`

test.describe('Settings → Access: API tokens', () => {
  test('issue a token, see its secret once, use it, then revoke it and watch it stop working', async ({ page, request }) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Access' }).click()
    const label = `e2e-reader-${Date.now()}`

    // the listing shows the credential in use, with its state in words
    await expect(page.getByRole('region', { name: 'API tokens' }).getByText('viewer-local-dev')).toBeVisible()

    // an empty label is refused before anything is sent
    await page.getByRole('button', { name: 'Issue token' }).click()
    await expect(page.getByRole('alert')).toContainText(/Give the token a label/)

    await page.getByLabel('Label').fill(label)
    await page.getByLabel('Role').selectOption('reader')
    await expect(page.getByText(/Read memories, sessions and the graph\. Cannot write\./)).toBeVisible()
    await page.getByLabel('Lasts').selectOption({ label: '1 day' })
    await page.getByRole('button', { name: 'Issue token' }).click()

    // shown once, in full
    const secret = (await page.getByLabel('Token secret').innerText()).trim()
    expect(secret.length).toBeGreaterThan(30)
    await expect(page.getByText(/cannot be shown again/)).toBeVisible()

    // the secret really is a working credential, and a reader may read but not write
    const read = await request.get(`${API}/api/stats`, { headers: { Authorization: `Bearer ${secret}` } })
    expect(read.status()).toBe(200)
    const write = await request.post(`${API}/api/memory/propositions`, { headers: { Authorization: `Bearer ${secret}` }, data: { content: 'should be refused' } })
    expect(write.status()).toBe(403)

    // closing the callout destroys the only copy the page held
    await page.getByRole('button', { name: 'I have stored it' }).click()
    await expect(page.getByLabel('Token secret')).toHaveCount(0)
    expect(await page.content()).not.toContain(secret)

    // revoke is a two-step action and takes effect at once
    const row = page.getByRole('listitem').filter({ hasText: label })
    await expect(row).toContainText('active')
    await row.getByRole('button', { name: 'Revoke' }).click()
    await row.getByRole('button', { name: 'Confirm revoke' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Token revoked' })).toBeVisible()
    await expect(page.getByRole('listitem').filter({ hasText: label })).toContainText('revoked')
    expect((await request.get(`${API}/api/stats`, { headers: { Authorization: `Bearer ${secret}` } })).status()).toBe(401)
  })

  test('refuses to revoke the credential the console is using, and says why', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Access' }).click()
    const row = page.getByRole('listitem').filter({ hasText: 'viewer-local-dev' })
    await row.getByRole('button', { name: 'Revoke' }).click()
    await row.getByRole('button', { name: 'Confirm revoke' }).click()
    await expect(page.getByRole('alert')).toContainText(/using right now/)
    await expect(row).toContainText('active') // still there, still working
  })

  test('an operator is not offered the admin role', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Access' }).click()
    await expect(page.getByLabel('Role').locator('option')).toHaveCount(4) // after the list has loaded
    const options = await page.getByLabel('Role').locator('option').allInnerTexts()
    expect(options).toEqual(['reader', 'writer', 'reviewer', 'operator'])
  })

  test('accounts waiting for approval are for administrators; anyone else is told so (real API)', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Access' }).click()
    await expect(page.getByRole('region', { name: 'Accounts waiting for approval' })).toContainText('Only an administrator can see and approve accounts waiting for approval.')
  })

  test('an administrator sees waiting accounts and approves one (stubbed: the dev credential is an operator)', async ({ page }) => {
    let approved = ''
    await page.route('**/cortex-api/api/auth/admin/pending', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ accounts: approved ? [] : [{ id: 'a1', email: 'new.operator@organization.com', display_name: 'New Operator', profile_id: 'default', role: 'operator', email_verified: false, approval_status: 'pending', created_at: '2026-10-10T09:00:00+00:00' }] }) }))
    await page.route('**/cortex-api/api/auth/admin/approve', async (r) => { approved = r.request().postDataJSON().email; await r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }) })
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Access' }).click()
    const region = page.getByRole('region', { name: 'Accounts waiting for approval' })
    await expect(region).toContainText('New Operator')
    await expect(region).toContainText('email not verified')
    await region.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'new.operator@organization.com can now sign in.' })).toBeVisible()
    expect(approved).toBe('new.operator@organization.com')
    await expect(region).toContainText('No accounts are waiting.')
  })
})

test.describe('Settings → Profile', () => {
  test('shows the configuration read-only, with no path and no secret', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Profile' }).click()
    await expect(page.getByRole('note').filter({ hasText: 'Read only.' })).toContainText(/restart/)
    await expect(page.getByRole('region', { name: 'Profile' })).toContainText('pseudonymous')
    const places = page.getByRole('region', { name: 'Where the server writes and reads' })
    for (const label of ['Backup destination', 'Trust vault', 'Integrity DAG', 'Anchor service', 'Integrity oracle']) await expect(places).toContainText(label)
    // nothing on this tab is editable
    await expect(page.getByRole('region', { name: 'Profile' }).locator('input, select, textarea')).toHaveCount(0)
    const text = await page.getByRole('tabpanel').innerText()
    expect(text).not.toMatch(/\/tmp\/|\/home\/|\.sqlite|https?:\/\//)
  })
})
