### Task 1: The hosted server declares its destinations

**Files:**
- Modify: `src/xibalba_cortex/managed/api.py` (the `me` handler)
- Test: `tests/test_managed_service.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/managed/me` response gains
  `"destinations": list[str]` — the destination ids this edition can serve. Fixed value
  for the hosted edition:
  `["graph", "timeline", "memories", "recall", "settings", "agents", "billing"]`.
  Chosen because the hosted API serves graph, timeline, memories, keys, plans and
  billing; it has no `entities`, `sessions`, `operations`, `review` or `integrity`
  endpoints.

- [ ] **Step 1: Write the failing test**

```python
def test_me_declares_the_destinations_this_edition_serves(managed_client):
    body = managed_client.get_json("/api/managed/me")
    assert body["destinations"] == [
        "graph", "timeline", "memories", "recall", "settings", "agents", "billing",
    ]
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_managed_service.py -k declares_the_destinations -q`
Expected: FAIL — `KeyError: 'destinations'`.

- [ ] **Step 3: Add the key to the `me` handler in `src/xibalba_cortex/managed/api.py`**

Define the list as a module-level constant beside the route table so it is greppable from
one place.

- [ ] **Step 4: Run it and confirm it passes**

Run: `uv run pytest tests/test_managed_service.py -k declares_the_destinations -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/xibalba_cortex/managed/api.py tests/test_managed_service.py
git commit -m "feat(managed): declare the destinations this edition serves"
```

---

