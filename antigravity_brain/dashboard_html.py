# Dashboard HTML Generator for Antigravity Brain Ingress UI

def get_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="el">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Brain v3.1</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --success: #10b981;
      --warning: #f59e0b;
      --error: #ef4444;
      --code-bg: #090d16;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg); color: var(--text); padding: 20px; line-height: 1.5; }
    .container { max-width: 900px; margin: 0 auto; }
    header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--card-border); }
    .logo-area { display: flex; align-items: center; gap: 12px; }
    .logo-icon { font-size: 32px; }
    h1 { font-size: 22px; font-weight: 700; }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
    .badge-success { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-error { background: rgba(239, 68, 68, 0.15); color: var(--error); border: 1px solid rgba(239, 68, 68, 0.3); }
    .pulse { width: 8px; height: 8px; border-radius: 50%; background: currentColor; animation: pulse 2s infinite; }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }

    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
    .card-title { font-size: 16px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
    .meta-item { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; }
    .meta-label { color: var(--text-muted); }
    .meta-val { font-weight: 500; }

    /* Auth Box */
    .auth-banner { background: rgba(245, 158, 11, 0.08); border: 1px solid var(--warning); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
    .auth-title { font-size: 18px; font-weight: 700; color: var(--warning); margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
    .code-container { display: flex; align-items: center; gap: 12px; margin: 16px 0; }
    .code-display { font-family: monospace; font-size: 28px; font-weight: 700; background: var(--code-bg); padding: 12px 24px; border-radius: 8px; border: 1px dashed var(--warning); letter-spacing: 3px; color: #fbbf24; }
    
    .btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; text-decoration: none; border: none; transition: 0.2s ease; }
    .btn-primary { background: var(--primary); color: white; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-warning { background: var(--warning); color: #000; font-weight: 700; }
    .btn-warning:hover { background: #d97706; }
    .btn-outline { background: transparent; border: 1px solid var(--card-border); color: var(--text); }
    .btn-outline:hover { background: rgba(255,255,255,0.05); }

    .tasks-section { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; }
    .task-item { border-bottom: 1px solid var(--card-border); padding: 12px 0; }
    .task-item:last-child { border-bottom: none; }
    .task-header { display: flex; justify-content: space-between; font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }
    .task-text { font-size: 14px; margin-bottom: 6px; font-weight: 500; }
    .task-response { font-size: 13px; color: #cbd5e1; background: var(--code-bg); padding: 10px; border-radius: 6px; margin-top: 6px; white-space: pre-wrap; }
    
    .copy-toast { position: fixed; bottom: 20px; right: 20px; background: var(--success); color: white; padding: 10px 16px; border-radius: 8px; font-size: 14px; font-weight: 600; opacity: 0; transition: opacity 0.3s ease; pointer-events: none; }
    .copy-toast.show { opacity: 1; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-area">
        <span class="logo-icon">🧠</span>
        <div>
          <h1>Antigravity Brain</h1>
          <p style="font-size: 12px; color: var(--text-muted);">Διφασικός Εγκέφαλος Φωνητικού Βοηθού Home Assistant</p>
        </div>
      </div>
      <div id="system-badge" class="badge badge-success">
        <span class="pulse"></span>
        <span>Online v3.1</span>
      </div>
    </header>

    <!-- Codex Auth Alert Banner (Shown dynamically when auth is pending) -->
    <div id="auth-box" class="auth-banner" style="display: none;">
      <div class="auth-title">
        <span>🔑</span>
        <span>Απαιτείται Σύνδεση Codex CLI (OpenAI)</span>
      </div>
      <p style="color: var(--text-muted); font-size: 14px; margin-bottom: 12px;">
        Για να εκτελούνται οι αναλύσεις του Heavy Agent με το μοντέλο <strong>GPT-5.6 Sol</strong>, εγκρίνετε τη σύνδεση μέσω OpenAI Device Authorization:
      </p>
      <div class="code-container">
        <div id="auth-code" class="code-display">----</div>
        <button class="btn btn-outline" onclick="copyCode()">📋 Αντιγραφή</button>
        <a id="auth-link" href="https://auth.openai.com/codex/device" target="_blank" class="btn btn-warning">🚀 Άνοιγμα Σελίδας Έγκρισης</a>
      </div>
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 13px; color: var(--text-muted);">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="pulse" style="background: var(--warning);"></span>
          <span>Αναμονή για έγκριση στον περιηγητή...</span>
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
          <span>⏳ Υπολειπόμενος χρόνος:</span>
          <span id="auth-countdown" style="font-family: monospace; font-size: 14px; font-weight: 700; color: #fbbf24; background: rgba(251, 191, 36, 0.12); padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(251, 191, 36, 0.3);">15:00</span>
        </div>
      </div>
    </div>

    <!-- Codex Auth Expired Alert Banner (Shown dynamically when auth is expired) -->
    <div id="expired-box" class="auth-banner" style="display: none; background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.4);">
      <div class="auth-title" style="color: var(--error);">
        <span>⚠️</span>
        <span>Ο Κωδικός Codex Έληξε (15 λεπτά)</span>
      </div>
      <p style="color: var(--text-muted); font-size: 14px; margin-bottom: 14px;">
        Ο προηγούμενος κωδικός συσκευής OpenAI έχει υπερβεί το όριο των 15 λεπτών. Πατήστε το κουμπί για άμεση παραγωγή νέου κωδικού:
      </p>
      <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
        <button id="btn-regen" class="btn btn-warning" onclick="triggerAuth()">🔄 Παραγωγή Νέου Κωδικού</button>
        <span style="font-size: 13px; color: var(--text-muted);">💡 Η ανανέωση ξεκινά αυτόματα και με οποιοδήποτε φωνητικό αίτημα στον Assist.</span>
      </div>
    </div>

    <!-- Agent Cards -->
    <div class="grid">
      <!-- Fast Agent -->
      <div class="card">
        <div class="card-title">
          <span>⚡ Phase 1: Fast Agent</span>
          <span id="fast-status" class="badge badge-success">Ενεργός</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Μηχανή:</span>
          <span id="fast-engine" class="meta-val">Gemini API</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Μοντέλο:</span>
          <span id="fast-model" class="meta-val">3.8 flash high</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Χρόνος Απόκρισης:</span>
          <span class="meta-val">&lt; 3.5 δευτερόλεπτα</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Ρόλος:</span>
          <span class="meta-val" style="color: var(--text-muted); font-size: 12px;">Έλεγχος συσκευών &amp; άμεση επιβεβαίωση</span>
        </div>
      </div>

      <!-- Heavy Agent -->
      <div class="card">
        <div class="card-title">
          <span>🔬 Phase 2: Heavy Agent</span>
          <span id="heavy-status" class="badge badge-success">Έτοιμο</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Κύρια Μηχανή:</span>
          <span class="meta-val">Codex CLI (gpt-5.6-sol)</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Κατάσταση Σύνδεσης:</span>
          <span id="codex-auth-label" class="meta-val" style="color: var(--success);">Συνδεδεμένο</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Εφεδρικές Μηχανές:</span>
          <span class="meta-val">Antigravity &rarr; Gemini 3.1 Pro</span>
        </div>
        <div style="margin-top: 14px; display: flex; gap: 8px;">
          <button id="btn-reauth" class="btn btn-outline" style="font-size: 12px; padding: 6px 12px;" onclick="triggerAuth()">🔄 Επανασύνδεση Codex</button>
        </div>
      </div>
    </div>

    <!-- Recent Tasks Section -->
    <div class="tasks-section">
      <div class="card-title">
        <span>📋 Πρόσφατες Βαριές Εργασίες (Heavy Tasks)</span>
        <button class="btn btn-outline" style="font-size: 12px; padding: 4px 10px;" onclick="fetchStatus()">Ανανέωση</button>
      </div>
      <div id="tasks-list">
        <p style="color: var(--text-muted); font-size: 14px;">Δεν υπάρχουν πρόσφατες εργασίες.</p>
      </div>
    </div>
  </div>

  <div id="toast" class="copy-toast">Ο κωδικός αντιγράφηκε!</div>

  <script>
    let currentCode = "";
    let remainingSec = 0;

    async function fetchStatus() {
      try {
        const res = await fetch("api/status");
        if (!res.ok) return;
        const data = await res.json();
        
        // Fast Agent UI
        document.getElementById("fast-engine").textContent = data.fast_agent.engine;
        document.getElementById("fast-model").textContent = data.fast_agent.model;

        // Codex Auth Status
        const codex = data.heavy_agent.codex;
        const authBox = document.getElementById("auth-box");
        const expiredBox = document.getElementById("expired-box");
        const heavyStatus = document.getElementById("heavy-status");
        const authLabel = document.getElementById("codex-auth-label");

        if (codex.auth_state === "pending" || (codex.auth_pending && codex.device_code)) {
          authBox.style.display = "block";
          expiredBox.style.display = "none";
          document.getElementById("auth-code").textContent = codex.device_code || "----";
          currentCode = codex.device_code;
          if (codex.auth_url) {
            document.getElementById("auth-link").href = codex.auth_url;
          }
          remainingSec = codex.remaining_seconds || 0;
          updateTimerDisplay();

          heavyStatus.className = "badge badge-warning";
          heavyStatus.textContent = "Απαιτείται Σύνδεση";
          authLabel.textContent = "Εκκρεμεί Έγκριση";
          authLabel.style.color = "var(--warning)";
        } else if (codex.auth_state === "expired") {
          authBox.style.display = "none";
          expiredBox.style.display = "block";
          heavyStatus.className = "badge badge-warning";
          heavyStatus.textContent = "Κωδικός Έληξε";
          authLabel.textContent = "Έληξε (15 λεπτά)";
          authLabel.style.color = "var(--warning)";
        } else if (codex.authenticated || codex.auth_state === "authenticated") {
          authBox.style.display = "none";
          expiredBox.style.display = "none";
          heavyStatus.className = "badge badge-success";
          heavyStatus.textContent = "Συνδεδεμένο";
          authLabel.textContent = "Ενεργό (ChatGPT)";
          authLabel.style.color = "var(--success)";
        } else {
          authBox.style.display = "none";
          expiredBox.style.display = "none";
          heavyStatus.className = "badge badge-error";
          heavyStatus.textContent = "Μη Συνδεδεμένο";
          authLabel.textContent = "Αποσυνδεδεμένο";
          authLabel.style.color = "var(--error)";
        }

        // Recent Tasks
        const tasksList = document.getElementById("tasks-list");
        if (data.recent_tasks && data.recent_tasks.length > 0) {
          tasksList.innerHTML = data.recent_tasks.map(t => `
            <div class="task-item">
              <div class="task-header">
                <span>${t.timestamp || ""}</span>
                <span class="badge ${t.status === 'completed' ? 'badge-success' : 'badge-warning'}">${t.status} (${t.duration || 0}s)</span>
              </div>
              <div class="task-text">${t.task || ""}</div>
              ${t.spoken ? `<div class="task-response"><strong>Εκφώνηση:</strong> ${t.spoken}</div>` : ""}
            </div>
          `).join("");
        }
      } catch (e) {
        console.error("fetchStatus error:", e);
      }
    }

    function updateTimerDisplay() {
      const mins = Math.floor(remainingSec / 60).toString().padStart(2, '0');
      const secs = (remainingSec % 60).toString().padStart(2, '0');
      const el = document.getElementById("auth-countdown");
      if (el) el.textContent = `${mins}:${secs}`;
    }

    function copyCode() {
      if (!currentCode) return;
      navigator.clipboard.writeText(currentCode).then(() => {
        const toast = document.getElementById("toast");
        toast.className = "copy-toast show";
        setTimeout(() => { toast.className = "copy-toast"; }, 2500);
      });
    }

    async function triggerAuth() {
      try {
        const btnRegen = document.getElementById("btn-regen");
        const btnReauth = document.getElementById("btn-reauth");
        if (btnRegen) { btnRegen.disabled = true; btnRegen.textContent = "⏳ Παραγωγή..."; }
        if (btnReauth) { btnReauth.disabled = true; }
        
        await fetch("api/auth/codex/start", { method: "POST" });
        await fetchStatus();
      } catch (e) {
        alert("Σφάλμα έναρξης σύνδεσης: " + e);
      } finally {
        const btnRegen = document.getElementById("btn-regen");
        const btnReauth = document.getElementById("btn-reauth");
        if (btnRegen) { btnRegen.disabled = false; btnRegen.textContent = "🔄 Παραγωγή Νέου Κωδικού"; }
        if (btnReauth) { btnReauth.disabled = false; }
      }
    }

    // Local countdown ticker
    setInterval(() => {
      if (remainingSec > 0) {
        remainingSec--;
        updateTimerDisplay();
      }
    }, 1000);

    // Initial fetch and auto-refresh loop
    fetchStatus();
    setInterval(fetchStatus, 3000);
  </script>
</body>
</html>"""
