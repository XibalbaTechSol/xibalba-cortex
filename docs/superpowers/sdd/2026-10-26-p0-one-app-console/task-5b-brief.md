# Task 5b — One app root, and the landing knows its edition

Derived from the plan's Task 5, which I split. 5a re-homed API keys and bulk export.
5b boots one app and makes the hosted landing correct. 5c deletes the second UI.

## Files
- Modify: `viewer/src/main.tsx` — delete the `managed` constant and the conditional import; always render `ConsoleApp`.
- Modify: `viewer/src/console/ConsoleApp.tsx` — read `destinations` from the session payload, resolve with `destinationsFrom`, and pass that list to `destinationsIn`, `primaryDestinations` and `tabsFor`, and `builtFrom(list)` to `parseRoute`.
- Modify: `viewer/src/console/pages/PageHost.tsx` — `PageTabs` must use the narrowed list, not the default.
- Modify: `viewer/src/console/Landing.tsx` — keep the `managed` prop as a configuration input; re-home the hosted pricing/signup children.
- Test: `viewer/src/console/nav.test.ts`, any new unit test for the landing/edition resolution.

## Do NOT
- Do not delete `ManagedApp.tsx`, `ManagedLenses.tsx` or `managed.css`. That is 5c.
- Do not add a new gating concept or a second app root.
- Do not touch Python.

## Interfaces consumed
- `destinationsFrom(ids)`, `builtFrom(list)`, `tabsFor(page, list = DESTINATIONS)` from `nav.ts`.
- `GET /api/managed/me` -> `destinations: string[]` (7 ids, hosted edition).
- `BillingPage` from Task 3; the keys/export controls from 5a.

## Rulings that bind this task
1. `Landing`'s `managed` prop SURVIVES as an edition configuration input, not a component fork. Dropping it (as the plan's text says) would show self-hosted copy — "A local-first memory server..." — to hosted visitors. Branches at Landing.tsx lines 39, 44, 73, 76, 79, 102, 114, 116.
2. The hosted landing's CHILDREN (pricing section, plan cards, auth messages, the `Paid subscriptions are not available yet.` note, passed from `ManagedApp.tsx:141`) are re-homed, not deleted. Losing them removes the hosted signed-out pricing and plan-choice surface.
3. `PageTabs` (`PageHost.tsx:17`) currently calls `tabsFor(page)` with the default list. Review Focus item 5 — "a tab strip whose peers are partly undeclared must not render a tab that goes nowhere" — is satisfied only when the narrowed list reaches it. Thread it through console state; do not duplicate the list.
4. Self-hosted behaviour must not change: no declaration means every `BUILT` destination, exactly as today.

## Review Focus items this task owns
- Item 4: a hash route for an undeclared destination (`#operations` on hosted) must resolve to a defined surface, via `parseRoute(hash, builtFrom(list))`.
- Item 5: see ruling 3.
