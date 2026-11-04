### Task 4: The grammar sweep covers `/managed`, and is proved red first

**Files:**
- Modify: `viewer/e2e/design-system.spec.ts`

**Interfaces:**
- Consumes: `grammarSweep(page)` at `design-system.spec.ts:266`, and the signed-in
  managed fixture from `viewer/e2e/managed.spec.ts`.
- Produces: nothing other tasks consume.

This task's test is **expected to fail on completion** and is the gate Task 5 must turn
green. Do not weaken it to make it pass here.

- [ ] **Step 1: Write the test**

Follow the shape of `the public landing keeps its grammar at ${width}px`
(`design-system.spec.ts:680`), which sweeps a path rather than a hash route:

```ts
for (const width of [390, 1280, 1600]) {
  test(`the hosted workspace keeps its grammar at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await managedFixture(page, { signedIn: true })
    await page.goto('/managed')
    await expect(page.locator('.xc')).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    const problems = await grammarSweep(page)
    expect(problems, problems.join('\n')).toEqual([])
  })
}
```

- [ ] **Step 2: Run it and record the failure**

Run: `cd viewer && npx playwright test e2e/design-system.spec.ts -g "hosted workspace" --project=desktop`
Expected: FAIL. Record the violation list in the commit message — it is the evidence the
check can fail, and the baseline Task 5 is measured against.

- [ ] **Step 3: Commit the red test**

```bash
git add viewer/e2e/design-system.spec.ts
git commit -m "test(e2e): sweep the hosted workspace for Industry grammar

Red on purpose: /managed has never been swept, so grammarSweep appears 5 times
across the suite and /managed 0 times. Recorded violations: <paste list>."
```

---

