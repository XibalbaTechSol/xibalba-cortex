// Super-Cortex Chrome Extension: Popup Controller

let currentServerUrl = "http://127.0.0.1:4174";
let currentAgentId = "agent:chrome-extension";
let activeTabInfo = null;

// Storage abstraction for both Chrome Extension and browser testing environments
const storageHelper = {
  get: (keys, callback) => {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      chrome.storage.local.get(keys, callback);
    } else {
      const items = {};
      keys.forEach(k => {
        const v = localStorage.getItem(`sc_${k}`);
        if (v !== null) items[k] = v;
      });
      callback(items);
    }
  },
  set: (obj, callback) => {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      chrome.storage.local.set(obj, callback);
    } else {
      Object.entries(obj).forEach(([k, v]) => localStorage.setItem(`sc_${k}`, v));
      if (callback) callback();
    }
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  // Load configuration
  storageHelper.get(["serverUrl", "agentId", "defaultScope"], (items) => {
    if (items.serverUrl) {
      currentServerUrl = items.serverUrl;
      document.getElementById("cfg-server-url").value = items.serverUrl;
      document.getElementById("link-studio").href = items.serverUrl;
    }
    if (items.agentId) {
      currentAgentId = items.agentId;
      document.getElementById("cfg-agent-id").value = items.agentId;
    }
    if (items.defaultScope) {
      const scopeSelect = document.getElementById("clip-scope");
      if (scopeSelect) scopeSelect.value = items.defaultScope;
    }
    checkServerStatus();
  });

  // Setup tab switcher
  setupTabs();

  // Populate active tab data
  await initActiveTabContext();

  // Bind event listeners
  document.getElementById("clip-text").addEventListener("input", debounce(analyzeInputText, 250));
  document.getElementById("btn-clip").addEventListener("click", handleClipMemory);
  document.getElementById("btn-ingest-url").addEventListener("click", handleIngestUrl);
  document.getElementById("btn-recall-search").addEventListener("click", handleRecallSearch);
  document.getElementById("recall-query").addEventListener("keypress", (e) => {
    if (e.key === "Enter") handleRecallSearch();
  });
  document.getElementById("btn-save-settings").addEventListener("click", handleSaveSettings);
});

// Setup tab navigation
function setupTabs() {
  const tabs = [
    { btn: "tab-clip", view: "view-clip" },
    { btn: "tab-recall", view: "view-recall" },
    { btn: "tab-settings", view: "view-settings" }
  ];

  tabs.forEach(({ btn, view }) => {
    document.getElementById(btn).addEventListener("click", () => {
      tabs.forEach(t => {
        document.getElementById(t.btn).classList.remove("active");
        document.getElementById(t.view).style.display = "none";
      });
      document.getElementById(btn).classList.add("active");
      document.getElementById(view).style.display = "block";
    });
  });
}

// Ping server status and populate scopes
async function checkServerStatus() {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");

  try {
    const res = await fetch(`${currentServerUrl}/api/status`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    dot.classList.add("online");
    const validStr = data.chain_valid ? "VALID" : "UNVERIFIED";
    text.textContent = `ONLINE [${data.event_count || 0} EVTS]`;
    text.title = `Merkle Chain: ${validStr} | Local Daemon: ${data.supermemory_local_alive ? "Connected" : "Disconnected"}`;

    // Populate scopes if available
    if (data.scopes && Array.isArray(data.scopes)) {
      const scopeSelect = document.getElementById("clip-scope");
      const currentVal = scopeSelect.value;
      scopeSelect.innerHTML = "";
      data.scopes.forEach(sc => {
        const opt = document.createElement("option");
        opt.value = sc;
        opt.textContent = sc;
        scopeSelect.appendChild(opt);
      });
      if (currentVal && data.scopes.includes(currentVal)) {
        scopeSelect.value = currentVal;
      }
    }
  } catch (err) {
    dot.classList.remove("online");
    text.textContent = "OFFLINE";
    text.title = "Ensure super-cortex studio is running at " + currentServerUrl;
  }
}

// Extract context from current browser tab
async function initActiveTabContext() {
  if (typeof chrome === "undefined" || !chrome.tabs || !chrome.tabs.query) {
    document.getElementById("clip-title").value = "Super-Cortex // Neural Memory Extension";
    document.getElementById("clip-url").value = "https://github.com/super-cortex/supermemory";
    document.getElementById("clip-text").value = "Super-Cortex anchors agent memories with zero-inference epistemic graph parsing and local vector search.";
    analyzeInputText();
    return;
  }

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    activeTabInfo = tab;

    document.getElementById("clip-title").value = tab.title || "";
    document.getElementById("clip-url").value = tab.url || "";

    // Try to get selection from content script
    if (tab.id && !tab.url.startsWith("chrome://") && !tab.url.startsWith("edge://")) {
      try {
        const pageData = await chrome.tabs.sendMessage(tab.id, { action: "GET_PAGE_DATA" });
        if (pageData) {
          if (pageData.selection) {
            document.getElementById("clip-text").value = pageData.selection;
          } else if (pageData.description) {
            document.getElementById("clip-text").value = `${pageData.title}\n\n${pageData.description}`;
          } else {
            document.getElementById("clip-text").value = `${pageData.title}\nURL: ${pageData.url}`;
          }
          analyzeInputText();
        }
      } catch (e) {
        // Fallback to tab title if content script message fails
        document.getElementById("clip-text").value = `${tab.title}\nURL: ${tab.url}`;
        analyzeInputText();
      }
    } else {
      document.getElementById("clip-text").value = `${tab.title}\nURL: ${tab.url}`;
      analyzeInputText();
    }
  } catch (err) {
    console.warn("Failed to get active tab:", err);
  }
}

// Zero-inference live epistemic & syntactic analyzer
async function analyzeInputText() {
  const text = document.getElementById("clip-text").value.trim();
  const classEl = document.getElementById("detected-class");
  const triplesEl = document.getElementById("detected-triples");

  if (!text) {
    classEl.textContent = "EMPTY";
    triplesEl.textContent = "0 TRIPLES";
    return;
  }

  // Quick heuristic fallback or server /api/extract
  try {
    const res = await fetch(`${currentServerUrl}/api/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: AbortSignal.timeout(1500)
    });
    if (res.ok) {
      const data = await res.json();
      classEl.textContent = (data.epistemic_class || "FACT").toUpperCase();
      const tripleCount = (data.triples && data.triples.length) ? data.triples.length : 0;
      triplesEl.textContent = `${tripleCount} TRIPLES`;
      return;
    }
  } catch (e) {
    // Local fast heuristic
  }

  // Pure deterministic client-side fallback
  const lower = text.toLowerCase();
  let detected = "fact";
  if (lower.includes("if ") || lower.includes("might") || lower.includes("predict")) detected = "hypothesis";
  else if (lower.includes("axiom") || lower.includes("must always") || lower.includes("by definition")) detected = "axiom";
  else if (lower.includes("believe") || lower.includes("prefer") || lower.includes("opinion")) detected = "belief";
  else if (lower.includes("saw") || lower.includes("noticed") || lower.includes("observed")) detected = "observation";

  classEl.textContent = detected.toUpperCase();
  triplesEl.textContent = "AUTO-EXTRACT";
}

// Handle Anchor Memory Action
async function handleClipMemory() {
  const resultAlert = document.getElementById("clip-result");
  const btn = document.getElementById("btn-clip");
  const text = document.getElementById("clip-text").value.trim();
  const title = document.getElementById("clip-title").value.trim();
  const url = document.getElementById("clip-url").value.trim();
  const scope = document.getElementById("clip-scope").value;
  const epistemicChoice = document.getElementById("clip-epistemic").value;

  if (!text) {
    showAlert(resultAlert, "Memory content cannot be empty.", false);
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span>⏳</span> ANCHORING...`;
  resultAlert.style.display = "none";

  try {
    const payload = {
      text: text,
      scope: scope,
      agent_id: currentAgentId,
      metadata: {
        source: "chrome_extension",
        title: title,
        url: url,
        timestamp: new Date().toISOString()
      }
    };

    if (epistemicChoice !== "auto") {
      payload.epistemic_class = epistemicChoice;
    }

    const res = await fetch(`${currentServerUrl}/api/remember`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || `HTTP ${res.status}`);
    }

    const data = await res.json();
    const memId = data.memory_id || data.id || "anchored";
    showAlert(resultAlert, `✓ Anchored [${data.epistemic_class || 'fact'}]: ${memId.substring(0, 18)}...`, true);

    // Notify active tab HUD toast
    if (activeTabInfo?.id) {
      chrome.tabs.sendMessage(activeTabInfo.id, {
        action: "SHOW_CLIP_NOTIFICATION",
        data: {
          success: true,
          memory_id: memId,
          epistemic_class: data.epistemic_class,
          scope: scope,
          message: "Anchored to Super-Cortex ledger with zero-inference epistemic graph extraction."
        }
      }).catch(() => {});
    }

    checkServerStatus();
  } catch (err) {
    showAlert(resultAlert, `Clip failed: ${err.message}`, false);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span>⚡</span> ANCHOR MEMORY TO LEDGER`;
  }
}

// Handle Ingest Full URL Action
async function handleIngestUrl() {
  const resultAlert = document.getElementById("clip-result");
  const btn = document.getElementById("btn-ingest-url");
  const url = document.getElementById("clip-url").value.trim();
  const scope = document.getElementById("clip-scope").value;

  if (!url || !url.startsWith("http")) {
    showAlert(resultAlert, "Valid HTTP/HTTPS URL required for crawler ingestion.", false);
    return;
  }

  btn.disabled = true;
  btn.textContent = "⏳ CRAWLING & INGESTING...";
  resultAlert.style.display = "none";

  try {
    const res = await fetch(`${currentServerUrl}/api/connectors/url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        scope: scope,
        agent_id: currentAgentId,
        tags: ["chrome-extension", "web-clipper"]
      })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || `HTTP ${res.status}`);
    }

    const data = await res.json();
    showAlert(resultAlert, `✓ Ingested ${data.total_chunks || 1} chunks into scope [${scope}].`, true);

    if (activeTabInfo?.id) {
      chrome.tabs.sendMessage(activeTabInfo.id, {
        action: "SHOW_CLIP_NOTIFICATION",
        data: {
          success: true,
          url: url,
          scope: scope,
          message: `Ingested ${data.total_chunks || 1} chunks via Super-Cortex URL connector.`
        }
      }).catch(() => {});
    }

    checkServerStatus();
  } catch (err) {
    showAlert(resultAlert, `Ingestion error: ${err.message}`, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "🌐 INGEST FULL PAGE VIA URL CONNECTOR";
  }
}

// Handle Semantic Recall Search
async function handleRecallSearch() {
  const query = document.getElementById("recall-query").value.trim();
  const container = document.getElementById("recall-results");

  if (!query) return;

  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px 0; font-family: var(--font-mono); font-size: 11px;">RETRIEVING FROM LEDGER...</div>`;

  try {
    const res = await fetch(`${currentServerUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: query })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const results = data.retrieval || [];

    if (!results || results.length === 0) {
      container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px 0; font-family: var(--font-mono); font-size: 11px;">No matching memories found in ledger.</div>`;
      return;
    }

    container.innerHTML = "";
    results.forEach(item => {
      const card = document.createElement("div");
      card.className = "search-result-item";
      const score = item.similarity ? `Score: ${Math.round(item.similarity * 100)}%` : "Anchored";
      const ep = item.epistemic_class || item.metadata?.epistemic_class || "fact";
      card.innerHTML = `
        <div class="meta">
          <span style="color: var(--cyan); text-transform: uppercase;">[${ep}]</span>
          <span>${score}</span>
        </div>
        <div class="text">${escapeHtml(item.content || item.text || "")}</div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div style="color: var(--red); padding: 10px; font-family: var(--font-mono); font-size: 11px;">Recall error: ${err.message}</div>`;
  }
}

// Handle Settings Save
function handleSaveSettings() {
  const newUrl = document.getElementById("cfg-server-url").value.trim();
  const newAgent = document.getElementById("cfg-agent-id").value.trim();
  const resultAlert = document.getElementById("settings-result");

  currentServerUrl = newUrl || "http://127.0.0.1:4174";
  currentAgentId = newAgent || "agent:chrome-extension";

  storageHelper.set({
    serverUrl: currentServerUrl,
    agentId: currentAgentId
  }, () => {
    showAlert(resultAlert, "Configuration saved successfully.", true);
    document.getElementById("link-studio").href = currentServerUrl;
    checkServerStatus();
  });
}

function showAlert(el, msg, isSuccess) {
  el.textContent = msg;
  el.className = `result-alert ${isSuccess ? "success" : "error"}`;
  el.style.display = "block";
}

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

function escapeHtml(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}
