import { chromium } from 'playwright'

const surfaces = [
  { name: 'Cortex', url: process.env.CORTEX_UI_URL || 'http://127.0.0.1:4179/', api: process.env.CORTEX_API_URL, auth: /Create account|Sign in/ },
  { name: 'Shield', url: process.env.SHIELD_UI_URL || 'http://127.0.0.1:4178/', api: process.env.SHIELD_API_URL, auth: /Create account|Sign in/ },
]

const failures = []
for (const surface of surfaces) {
  console.log('starting ' + surface.name)
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  try {
    await page.goto(surface.url, { waitUntil: 'domcontentloaded', timeout: 5000 })
    const landing = await page.locator('body').innerText()
    if (!landing.includes(surface.name)) throw new Error('landing brand is missing')
    const open = page.getByRole('button', { name: /sign in|open (workspace|console)/i }).first()
    await open.click()
    await page.getByText(surface.auth).first().waitFor({ state: 'visible', timeout: 5000 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)
    if (overflow) throw new Error('mobile layout overflows horizontally')
    const endpoint = page.locator('input[name=endpoint], input[name=baseUrl]').first()
    await endpoint.fill('http://127.0.0.1:9')
    await page.locator('input[type=email]').fill('invalid@example.com')
    await page.locator('input[type=password]').fill('not-a-real-password')
    await page.getByRole('button', { name: /enter workspace|continue to console/i }).click()
    await page.locator('.auth-error').waitFor({ state: 'visible', timeout: 5000 })
    await page.getByRole('button', { name: /forgot password/i }).click()
    if (!(await page.locator('.auth-error').innerText()).toLowerCase().includes('password reset')) throw new Error('password-reset placeholder missing')
    const signupEmail = process.env[`${surface.name.toUpperCase()}_SIGNUP_EMAIL`]
    const signupPassword = process.env[`${surface.name.toUpperCase()}_SIGNUP_PASSWORD`]
    if (surface.api && signupEmail && signupPassword) {
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: /sign in|open (workspace|console)/i }).first().click()
      await page.getByRole('button', { name: /create account/i }).click()
      await page.locator('input[name=endpoint], input[name=baseUrl]').first().fill(surface.api)
      await page.locator('input[type=email]').fill(signupEmail)
      await page.locator('input[type=password]').fill(signupPassword)
      const display = page.locator('input[name=displayName]').first()
      if (await display.count()) await display.fill('Browser Test Operator')
      const tenant = page.locator('input[name=tenant]').first()
      if (await tenant.count()) await tenant.fill(process.env[`${surface.name.toUpperCase()}_SIGNUP_TENANT`] || 'browser-test-tenant')
      await page.getByRole('button', { name: /create account/i }).last().click()
      await page.waitForTimeout(700)
      if ((await page.locator('.auth-error').count()) > 0) throw new Error('sign-up credentials were rejected')
      console.log(`${surface.name}: sign-up flow OK`)
      await page.evaluate(() => sessionStorage.clear())
    }
    if (surface.api && process.env[`${surface.name.toUpperCase()}_EMAIL`] && process.env[`${surface.name.toUpperCase()}_PASSWORD`]) {
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: /sign in|open (workspace|console)/i }).first().click()
      await page.locator('input[name=endpoint], input[name=baseUrl]').first().fill(surface.api)
      await page.locator('input[type=email]').fill(process.env[`${surface.name.toUpperCase()}_EMAIL`])
      await page.locator('input[type=password]').fill(process.env[`${surface.name.toUpperCase()}_PASSWORD`])
      await page.getByRole('button', { name: /enter workspace|continue to console/i }).click()
      await page.waitForTimeout(700)
      if ((await page.locator('.auth-error').count()) > 0) throw new Error('valid account credentials were rejected')
      const workspace = await page.locator('body').innerText()
      if (!/dashboard|workspace|control plane|overview/i.test(workspace)) throw new Error('authenticated workspace did not render')
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(400)
      if ((await page.locator('input[type=email]').count()) > 0) throw new Error('refresh lost the authenticated session')
      const settings = page.getByRole('button', { name: /^settings$/i }).first()
      if (await settings.count()) {
        await settings.click()
        await page.waitForTimeout(250)
        const settingsText = await page.locator('body').innerText()
        if (!/account|session|control plane|profile/i.test(settingsText)) throw new Error('Settings did not render account/session details')
        const avatar = page.locator('input[type=file]').first()
        if (await avatar.count()) {
          await avatar.setInputFiles({ name: 'avatar.png', mimeType: 'image/png', buffer: Buffer.from('89504e470d0a1a0a', 'hex') })
          const remove = page.getByRole('button', { name: /remove/i }).first()
          if (await remove.count()) await remove.click()
        }
      }
      const signOut = page.getByRole('button', { name: /sign out/i }).last()
      if (await signOut.count()) {
        await signOut.click()
        await page.waitForTimeout(250)
        if ((await page.locator('input[type=email]').count()) === 0) throw new Error('sign out did not return to authentication')
      }
      await page.evaluate(() => sessionStorage.clear())
      await page.reload({ waitUntil: 'domcontentloaded' })
      if ((await page.locator('input[type=email]').count()) === 0 && (await page.getByRole('button', { name: /sign in/i }).count()) === 0) throw new Error('session recovery did not return to sign in')
      console.log(`${surface.name}: valid login -> refresh -> settings/avatar -> sign out/session recovery OK`)
    }
    console.log(`${surface.name}: landing -> auth -> mobile -> unavailable-backend UX OK`)
  } catch (error) { failures.push(`${surface.name}: ${error.message}`) }
  finally { await browser.close() }
}
if (failures.length) { console.error(failures.join('\n')); process.exit(1) }
