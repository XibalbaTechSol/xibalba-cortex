from xibalba_cortex.demo_seed import seed_demo
from xibalba_cortex.store import GraphStore


def test_seed_demo_creates_showcase_profile(tmp_path):
    store = GraphStore(tmp_path / "graph")
    result = seed_demo(store)

    assert result["session_id"] == "mvp-demo-session"
    assert result["root"]["valid"] is True
    assert result["root"]["exchange_count"] == 1
    assert len(store.session_exchanges("mvp-demo-session")) == 1
    # Storing active memories also auto-enqueues one `auto-classify:` classify_para task
    # each (7cfdf67); the seed itself requests exactly one inference task.
    seeded = [t for t in store.list_inference_tasks() if not t["id"].startswith("auto-classify:")]
    assert len(seeded) == 1
    assert store.search("Temporary demo note") == []
    assert store.neighbors("Xibalba Cortex")["edges"]
    store.close()
