// Super-Cortex Chrome Extension: Content Script
// Extracts page context and renders high-tech cryptographic toast HUD

(function() {
  // Listen for messages from background or popup
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "GET_PAGE_DATA") {
      const selection = window.getSelection() ? window.getSelection().toString().trim() : "";
      const metaDesc = document.querySelector('meta[name="description"]')?.getAttribute("content") || "";
      
      sendResponse({
        title: document.title || window.location.hostname,
        url: window.location.href,
        selection: selection,
        description: metaDesc
      });
      return true;
    }

    if (request.action === "SHOW_CLIP_NOTIFICATION") {
      showCortexToast(request.data);
      sendResponse({ status: "displayed" });
      return true;
    }
  });

  function showCortexToast(data) {
    const existing = document.getElementById("super-cortex-hud-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "super-cortex-hud-toast";
    
    const isSuccess = data?.success !== false;
    const accentColor = isSuccess ? "#00ffcc" : "#ef4444";
    const titleText = isSuccess ? "⚡ SUPER-CORTEX // MEMORY ANCHORED" : "⚠ SUPER-CORTEX // CLIP FAILED";
    const memoryId = data?.memory_id ? `ID: ${data.memory_id.substring(0, 16)}...` : (data?.url ? `URL: ${data.url}` : "");
    const epClass = data?.epistemic_class ? `CLASS: [${data.epistemic_class.toUpperCase()}]` : "CLASS: [FACT]";
    const scope = data?.scope ? `SCOPE: ${data.scope}` : "SCOPE: shared";
    const msg = data?.message || (isSuccess ? "Cryptographic ledger hash registered with zero-inference epistemic parser." : "Could not reach local daemon at 127.0.0.1:4174");

    toast.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div style="width: 8px; height: 8px; border-radius: 50%; background: ${accentColor}; box-shadow: 0 0 8px ${accentColor};"></div>
          <span style="font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: ${accentColor};">${titleText}</span>
        </div>
        <span id="super-cortex-toast-close" style="cursor: pointer; color: #64748b; font-size: 14px; line-height: 1;">&times;</span>
      </div>
      <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; color: #e2e8f0; margin-bottom: 8px; line-height: 1.4;">
        ${msg}
      </div>
      <div style="display: flex; gap: 10px; font-family: monospace; font-size: 10px; color: #94a3b8; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 6px;">
        <span>${epClass}</span>
        <span>•</span>
        <span>${scope}</span>
        ${memoryId ? `<span>•</span><span>${memoryId}</span>` : ""}
      </div>
    `;

    Object.assign(toast.style, {
      position: "fixed",
      top: "24px",
      right: "24px",
      width: "360px",
      backgroundColor: "rgba(10, 15, 29, 0.96)",
      backdropFilter: "blur(12px)",
      border: `1px solid ${accentColor}`,
      borderRadius: "10px",
      padding: "14px 16px",
      boxShadow: `0 12px 36px rgba(0, 0, 0, 0.6), 0 0 16px ${accentColor}33`,
      zIndex: "2147483647",
      color: "#f8fafc",
      boxSizing: "border-box",
      transition: "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
      animation: "superCortexFadeIn 0.3s ease-out"
    });

    // Style animation
    if (!document.getElementById("super-cortex-keyframes")) {
      const style = document.createElement("style");
      style.id = "super-cortex-keyframes";
      style.textContent = `
        @keyframes superCortexFadeIn {
          from { opacity: 0; transform: translateY(-12px) scale(0.97); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `;
      document.head.appendChild(style);
    }

    document.body.appendChild(toast);

    toast.querySelector("#super-cortex-toast-close").addEventListener("click", () => {
      toast.remove();
    });

    setTimeout(() => {
      if (document.body.contains(toast)) {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-8px) scale(0.98)";
        setTimeout(() => toast.remove(), 300);
      }
    }, 4500);
  }
})();
