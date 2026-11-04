### Task 2: `nav.ts` resolves a server-declared set

**Files:**
- Modify: `viewer/src/console/nav.ts`
- Test: `viewer/src/console/nav.test.ts`

**Interfaces:**
- Consumes: the `destinations` ids from Task 1.
- Produces:
  - `ALL_DESTINATIONS` gains
    `{ id: 'billing', kind: 'page', label: 'Billing', group: 'system', hint: 'Plan, usage and invoices' }`,
    and `PageId` gains `'billing'`.
  - `TAB_LABEL.billing = 'Billing'`; `PAGE_TABS` lists `billing` as a peer of
    `settings` / `operations` / `agents`.
  - `export function destinationsFrom(ids: readonly string[] | null | undefined): readonly Destination[]`
    — `null`/`undefined`/empty returns `DESTINATIONS` unchanged; otherwise
    `ALL_DESTINATIONS` filtered to ids that are both declared and `BUILT`.
  - `tabsFor` **already exists** as `tabsFor(page: PageId): readonly PageId[]`
    (`nav.ts:103`). Widen it to
    `tabsFor(page: PageId, list: readonly Destination[] = DESTINATIONS): readonly PageId[]`,
    filtering `PAGE_TABS[page]` to members present in `list`. Do not add a second
    function.

Two seams already exist and must be reused rather than duplicated:

- `destinationsIn(group, list = DESTINATIONS)` and
  `primaryDestinations(list = DESTINATIONS)` already take the list — unchanged.
- `parseRoute(hash: string, built: ReadonlySet<DestinationId> = BUILT): Route`
  (`nav.ts:128`) already resolves a hash against a set of available destinations. Review
  Focus item 4 is satisfied by passing a **narrowed** set, not by writing a new resolver.
  Add `export function builtFrom(list: readonly Destination[]): ReadonlySet<DestinationId>`
  so callers can hand `parseRoute` the declared set.

- [ ] **Step 1: Write the failing tests**

```ts
test('an empty or absent declaration keeps every built destination', () => {
  expect(destinationsFrom(null)).toEqual(DESTINATIONS)
  expect(destinationsFrom([])).toEqual(DESTINATIONS)
})

test('an unknown declared id is ignored rather than rendered', () => {
  const ids = ['graph', 'wormhole']
  expect(destinationsFrom(ids).map((d) => d.id)).toEqual(['graph'])
})

test('a declaration narrows to the intersection with BUILT, in canonical order', () => {
  const ids = ['settings', 'graph', 'billing']
  expect(destinationsFrom(ids).map((d) => d.id)).toEqual(['graph', 'settings', 'billing'])
})

test('a tab strip drops peers the server did not declare', () => {
  const list = destinationsFrom(['settings', 'billing'])
  expect(tabsFor('settings', list)).toEqual(['settings', 'billing'])
})

test('an undeclared hash route resolves against the narrowed set', () => {
  const list = destinationsFrom(['graph', 'memories'])
  expect(parseRoute('#operations', builtFrom(list)).id).toBe('graph')
})

test('billing is a system destination with a tab label', () => {
  expect(ALL_DESTINATIONS.find((d) => d.id === 'billing')?.group).toBe('system')
  expect(TAB_LABEL.billing).toBe('Billing')
})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd viewer && npx vitest run src/console/nav.test.ts`
Expected: FAIL — `destinationsFrom is not a function`.

- [ ] **Step 3: Implement `destinationsFrom`, `builtFrom`, the widened `tabsFor`, and the `billing` destination in `viewer/src/console/nav.ts`**

Order comes from `ALL_DESTINATIONS`, not from the server's array, so the rail cannot be
reordered by a payload.

- [ ] **Step 4: Run them and confirm they pass**

Run: `cd viewer && npx vitest run src/console/nav.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add viewer/src/console/nav.ts viewer/src/console/nav.test.ts
git commit -m "feat(viewer): resolve destinations from a server declaration"
```

---

