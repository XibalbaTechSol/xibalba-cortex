// Super-Cortex Chrome Extension: Background Service Worker (Manifest V3)

const DEFAULT_SERVER = "http://127.0.0.1:4174";

// Setup context menus and default storage on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["serverUrl", "defaultScope"], (items) => {
    if (!items.serverUrl) {
      chrome.storage.local.set({
        serverUrl: DEFAULT_SERVER,
        defaultScope: "shared",
        agentId: "agent:chrome-extension"
      });
    }
  });

  chrome.contextMenus.create({
    id: "clip_selection_to_super_cortex",
    title: "⚡ Clip Selection to Super-Cortex",
    contexts: ["selection"]
  });

  chrome.contextMenus.create({
    id: "clip_page_to_super_cortex",
    title: "🌐 Ingest Full Page URL into Super-Cortex",
    contexts: ["page"]
  });
});

// Helper: send notification to active tab
async function notifyTab(tabId, data) {
  try {
    await chrome.tabs.sendMessage(tabId, {
      action: "SHOW_CLIP_NOTIFICATION",
      data: data
    });
  } catch (err) {
    console.warn("Could not send toast to tab:", err);
  }
}

// Helper: get server URL from storage
function getServerUrl() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["serverUrl"], (res) => {
      resolve(res.serverUrl || DEFAULT_SERVER);
    });
  });
}

// Helper: get default scope
function getDefaultScope() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["defaultScope"], (res) => {
      resolve(res.defaultScope || "shared");
    });
  });
}

// Handle Context Menu Actions
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const serverUrl = await getServerUrl();
  const scope = await getDefaultScope();

  if (info.menuItemId === "clip_selection_to_super_cortex") {
    const text = info.selectionText ? info.selectionText.trim() : "";
    if (!text) return;

    try {
      const response = await fetch(`${serverUrl}/api/remember`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          scope: scope,
          agent_id: "agent:chrome-clipper",
          metadata: {
            source: "chrome_selection",
            url: tab?.url || info.pageUrl,
            title: tab?.title || "Web Snippet",
            timestamp: new Date().toISOString()
          }
        })
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (tab?.id) {
        notifyTab(tab.id, {
          success: true,
          memory_id: data.memory_id || data.id,
          epistemic_class: data.epistemic_class || "fact",
          scope: scope,
          message: "Selected text anchored into Super-Cortex cryptographic provenance ledger."
        });
      }
    } catch (err) {
      if (tab?.id) {
        notifyTab(tab.id, {
          success: false,
          message: `Ingestion failed: ${err.message}`
        });
      }
    }
  } else if (info.menuItemId === "clip_page_to_super_cortex") {
    const targetUrl = tab?.url || info.pageUrl;
    if (!targetUrl) return;

    try {
      const response = await fetch(`${serverUrl}/api/connectors/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: targetUrl,
          scope: scope,
          agent_id: "agent:chrome-clipper",
          tags: ["chrome-extension", "web-clipper"]
        })
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (tab?.id) {
        notifyTab(tab.id, {
          success: true,
          url: targetUrl,
          scope: scope,
          message: `Ingested ${data.total_chunks || 1} cognitive chunks from ${new URL(targetUrl).hostname}.`
        });
      }
    } catch (err) {
      if (tab?.id) {
        notifyTab(tab.id, {
          success: false,
          message: `URL crawler failed: ${err.message}`
        });
      }
    }
  }
});

// Handle Keyboard Shortcut Commands (Alt+Shift+C)
chrome.commands.onCommand.addListener(async (command) => {
  if (command === "clip_current_tab") {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return;

    const serverUrl = await getServerUrl();
    const scope = await getDefaultScope();

    try {
      // Ask content script for selection if any
      let selection = "";
      try {
        const pageData = await chrome.tabs.sendMessage(tab.id, { action: "GET_PAGE_DATA" });
        if (pageData && pageData.selection) selection = pageData.selection;
      } catch (e) {
        // Content script might not be injected on special pages
      }

      const text = selection || `[Bookmark] ${tab.title}\nURL: ${tab.url}`;

      const response = await fetch(`${serverUrl}/api/remember`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          scope: scope,
          agent_id: "agent:chrome-clipper",
          metadata: {
            source: "chrome_hotkey",
            url: tab.url,
            title: tab.title,
            timestamp: new Date().toISOString()
          }
        })
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      notifyTab(tab.id, {
        success: true,
        memory_id: data.memory_id || data.id,
        epistemic_class: data.epistemic_class || "fact",
        scope: scope,
        message: "Quick-clipped tab to Super-Cortex ledger via shortcut."
      });
    } catch (err) {
      notifyTab(tab.id, {
        success: false,
        message: `Clip failed: ${err.message}`
      });
    }
  }
});

// Relay API requests from popup if needed
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "CLIP_TO_CORTEX") {
    (async () => {
      const serverUrl = await getServerUrl();
      try {
        const resp = await fetch(`${serverUrl}/api/remember`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request.payload)
        });
        const data = await resp.json();
        sendResponse({ success: resp.ok, data });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    })();
    return true; // async response
  }
});
