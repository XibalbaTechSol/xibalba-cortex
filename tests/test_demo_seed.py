from xibalba_cortex.demo_seed import seed_demo
from xibalba_cortex.store import GraphStore


def test_seed_demo_creates_showcase_profile(tmp_path):
    store = GraphStore(tmp_path / "graph")
    result = seed_demo(store)

    assert result["session_id"] == "mvp-demo-session"
    assert result["root"]["valid"] is True
    assert result["root"]["exchange_count"] == 1
    assert len(store.session_exchanges("mvp-demo-session")) == 1
    assert len(store.list_inference_tasks()) == 1
    assert store.search("Temporary demo note") == []
    assert store.neighbors("Xibalba Cortex")["edges"]
    store.close()
