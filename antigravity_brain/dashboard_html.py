# Dashboard HTML Generator for Antigravity Brain Ingress UI v3.1.2

def get_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="el">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Brain v3.1.2</title>
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
    .container { max-width: 950px; margin: 0 auto; }
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

    .section-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
    .card-title { font-size: 16px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
    .meta-item { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; }
    .meta-label { color: var(--text-muted); }
    .meta-val { font-weight: 500; }

    /* Buttons */
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 9px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; text-decoration: none; border: none; transition: 0.2s ease; }
    .btn-primary { background: var(--primary); color: white; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-warning { background: var(--warning); color: #000; font-weight: 700; }
    .btn-warning:hover { background: #d97706; }
    .btn-success { background: var(--success); color: white; }
    .btn-success:hover { background: #059669; }
    .btn-outline { background: transparent; border: 1px solid var(--card-border); color: var(--text); }
    .btn-outline:hover { background: rgba(255,255,255,0.05); }

    /* CLI Auth Boxes */
    .cli-auth-box { background: rgba(15, 23, 42, 0.6); border: 1px solid var(--card-border); border-radius: 10px; padding: 14px; margin-top: 14px; }
    .code-display { font-family: monospace; font-size: 24px; font-weight: 700; background: var(--code-bg); padding: 10px 18px; border-radius: 8px; border: 1px dashed var(--warning); letter-spacing: 2px; color: #fbbf24; text-align: center; }
    .input-field { width: 100%; padding: 10px 14px; background: var(--code-bg); border: 1px solid var(--card-border); color: white; border-radius: 8px; font-family: monospace; font-size: 13px; margin: 8px 0; }
    .input-field:focus { outline: none; border-color: var(--primary); }

    .tasks-section { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; }
    .task-item { border-bottom: 1px solid var(--card-border); padding: 12px 0; }
    .task-item:last-child { border-bottom: none; }
    .task-header { display: flex; justify-content: space-between; font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }
    .task-text { font-size: 14px; margin-bottom: 6px; font-weight: 500; }
    .task-response { font-size: 13px; color: #cbd5e1; background: var(--code-bg); padding: 10px; border-radius: 6px; margin-top: 6px; white-space: pre-wrap; }
    
    .copy-toast { position: fixed; bottom: 20px; right: 20px; background: var(--success); color: white; padding: 10px 16px; border-radius: 8px; font-size: 14px; font-weight: 600; opacity: 0; transition: opacity 0.3s ease; pointer-events: none; z-index: 100; }
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
        <span>Online v3.1.2</span>
      </div>
    </header>

    <!-- SECTION: CLI MANAGEMENT / AUTHENTICATION CONTROLS -->
    <div style="margin-bottom: 24px;">
      <div class="section-title">
        <span>🎮 Κέντρο Ελέγχου Συνδέσεων CLI (CLI Management)</span>
        <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">Πατήστε το αντίστοιχο κουμπί για εκκίνηση αυθεντικοποίησης</span>
      </div>
      <div class="grid">
        
        <!-- CARD 1: OPENAI CODEX CLI -->
        <div class="card" id="codex-card">
          <div class="card-title">
            <span>🔑 OpenAI Codex CLI</span>
            <span id="codex-badge" class="badge badge-error">Μη Συνδεδεμένο</span>
          </div>
          <p id="codex-desc" style="font-size: 13px; color: var(--text-muted); margin-bottom: 14px;">
            Μοντέλο <strong>GPT-5.6 Sol</strong> για αυτόνομη σύνταξη κώδικα, SQL αναλύσεις και διερεύνηση βάσης.
          </p>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button id="btn-codex-trigger" class="btn btn-warning" onclick="triggerCodexAuth()">
              🔑 Σύνδεση / Νέος Κωδικός
            </button>
          </div>

          <!-- Pending Box for Codex -->
          <div id="codex-pending-box" class="cli-auth-box" style="display: none;">
            <div style="font-size: 12px; color: var(--warning); font-weight: 600; margin-bottom: 8px;">
              Απαιτείται Έγκριση Συσκευής OpenAI:
            </div>
            <div id="codex-code-display" class="code-display">----</div>
            <div style="display: flex; gap: 8px; margin-top: 10px;">
              <button class="btn btn-outline" style="flex: 1;" onclick="copyCodexCode()">📋 Αντιγραφή</button>
              <a id="codex-auth-link" href="https://auth.openai.com/codex/device" target="_blank" class="btn btn-warning" style="flex: 1;">🚀 Άνοιγμα Σελίδας</a>
            </div>
            <div style="margin-top: 8px; display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted);">
              <span>⏳ Υπολειπόμενος χρόνος:</span>
              <span id="codex-timer" style="font-family: monospace; font-weight: 700; color: #fbbf24;">15:00</span>
            </div>
          </div>
        </div>

        <!-- CARD 2: GOOGLE ANTIGRAVITY CLI -->
        <div class="card" id="agy-card">
          <div class="card-title">
            <span>🌐 Google Antigravity CLI</span>
            <span id="agy-badge" class="badge badge-error">Μη Συνδεδεμένο</span>
          </div>
          <p id="agy-desc" style="font-size: 13px; color: var(--text-muted); margin-bottom: 14px;">
            Μοντέλα <strong>Gemini 3.8 / Pro High</strong> με αυτόνομη εκτέλεση εντολών τερματικού.
          </p>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button id="btn-agy-trigger" class="btn btn-primary" onclick="triggerAgyAuth()">
              🔑 Σύνδεση με Google
            </button>
          </div>

          <!-- Pending Box for Antigravity -->
          <div id="agy-pending-box" class="cli-auth-box" style="display: none;">
            <div style="font-size: 12px; color: var(--primary); font-weight: 600; margin-bottom: 8px;">
              Βήμα 1: Συνδεθείτε με τον λογαριασμό Google
            </div>
            <a id="agy-auth-link" href="#" target="_blank" class="btn btn-warning" style="width: 100%; margin-bottom: 8px;">
              🚀 Άνοιγμα Σελίδας Σύνδεσης Google
            </a>
            <div style="margin-bottom: 12px; display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted);">
              <span>⏳ Χρονικό όριο Google:</span>
              <span id="agy-timer" style="font-family: monospace; font-weight: 700; color: #fbbf24;">01:05</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">
              Βήμα 2: Επικολλήστε τον Κωδικό Εξουσιοδότησης (Authorization Code) ή το URL επιστροφής:
            </div>
            <input type="text" id="agy-code-input" class="input-field" placeholder="π.χ. 4/0A... ή επικολλήστε όλο το URL">
            <button id="btn-agy-submit" class="btn btn-success" style="width: 100%; margin-top: 4px;" onclick="submitAgyCode()">
              ✅ Υποβολή Κωδικού &amp; Ολοκλήρωση
            </button>
            <div id="agy-feedback" style="font-size: 12px; margin-top: 6px; text-align: center;"></div>
          </div>
        </div>

      </div>
    </div>

    <!-- Agent Cards (Phase 1 & Phase 2) -->
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
          <span id="fast-model" class="meta-val">gemini-3.8-flash</span>
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
          <span class="meta-label">Δευτερεύουσα Μηχανή:</span>
          <span class="meta-val">Antigravity CLI (Gemini Pro)</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Εφεδρική Μηχανή:</span>
          <span class="meta-val">Gemini 3.1 Pro Preview</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Έξοδος Αποτελεσμάτων:</span>
          <span class="meta-val" style="color: var(--text-muted); font-size: 12px;">Persistent Notif &amp; HD TTS Speak</span>
        </div>
      </div>
    </div>

    <!-- SECTION: TTS VOICE OUTPUT SETTINGS -->
    <div style="margin-bottom: 24px;">
      <div class="section-title">
        <span>🔊 Ρυθμίσεις Φωνητικών Απαντήσεων (TTS Engine &amp; Voice)</span>
        <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">Επιλέξτε τη μηχανή Text-to-Speech και τη φωνή για τις εκφωνήσεις του Heavy Agent</span>
      </div>
      <div class="card">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; align-items: end;">
          <div>
            <label style="display: block; font-size: 13px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">Μηχανή Text-to-Speech (TTS Engine):</label>
            <select id="tts-engine-select" class="input-field" style="margin: 0;" onchange="onTtsEngineChange()">
              <option value="tts.google_cloud">Google Cloud TTS (Chirp3 HD &amp; WaveNet)</option>
              <option value="tts.edge_tts_2">Microsoft Edge TTS (Nestoras &amp; Athina Neural)</option>
              <option value="tts.openai_tts_openai">OpenAI TTS (Nova, Alloy, Onyx, Shimmer)</option>
              <option value="tts.piper">Piper Local TTS (Offline Wyoming)</option>
              <option value="tts.google_ai_tts">Google AI TTS (Gemini Speech)</option>
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 13px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">Φωνή (Dynamic Voice Dropdown):</label>
            <select id="tts-voice-select" class="input-field" style="margin: 0;" onchange="onTtsVoiceChange()">
              <!-- Dynamically populated based on selected TTS engine -->
            </select>
            <input type="text" id="tts-voice-custom" class="input-field" style="margin-top: 6px; display: none;" placeholder="Πληκτρολογήστε προσαρμοσμένο όνομα φωνής (custom voice)">
          </div>
          <div>
            <button class="btn btn-primary" style="width: 100%; height: 42px;" onclick="saveTtsSettings()">💾 Αποθήκευση Ρυθμίσεων TTS</button>
          </div>
        </div>
        <p id="tts-save-msg" style="font-size: 12px; color: var(--success); margin-top: 10px; display: none;">✅ Οι ρυθμίσεις TTS αποθηκεύτηκαν επιτυχώς!</p>
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
    let currentCodexCode = "";
    let codexRemainingSec = 0;
    let agyRemainingSec = 0;
    let ttsLoaded = false;

    async function fetchStatus() {
      if (document.hidden) return;
      try {
        const res = await fetch("api/status");
        if (!res.ok) return;
        const data = await res.json();
        
        // TTS Settings UI prefill
        if (data.tts && !ttsLoaded) {
          if (data.tts.engine) document.getElementById("tts-engine-select").value = data.tts.engine;
          populateVoices(data.tts.engine || "tts.google_cloud", data.tts.voice || "");
          ttsLoaded = true;
        }

        // Fast Agent UI
        document.getElementById("fast-engine").textContent = data.fast_agent.engine;
        document.getElementById("fast-model").textContent = data.fast_agent.model;

        // 1. Codex CLI UI
        const codex = data.heavy_agent.codex || {};
        const codexBadge = document.getElementById("codex-badge");
        const codexDesc = document.getElementById("codex-desc");
        const codexPendingBox = document.getElementById("codex-pending-box");
        const codexCodeDisplay = document.getElementById("codex-code-display");
        const codexAuthLink = document.getElementById("codex-auth-link");

        if (codex.auth_state === "pending" || (codex.auth_pending && codex.device_code)) {
          codexBadge.className = "badge badge-warning";
          codexBadge.textContent = "Εκκρεμεί Έγκριση";
          codexDesc.textContent = "Απαιτείται έγκριση μέσω OpenAI Device Auth. Εισάγετε τον κωδικό παρακάτω:";
          codexPendingBox.style.display = "block";
          codexCodeDisplay.textContent = codex.device_code || "----";
          currentCodexCode = codex.device_code;
          if (codex.auth_url) codexAuthLink.href = codex.auth_url;
          codexRemainingSec = codex.remaining_seconds || 0;
          updateCodexTimerDisplay();
        } else if (codex.auth_state === "expired") {
          codexBadge.className = "badge badge-warning";
          codexBadge.textContent = "Κωδικός Έληξε";
          codexDesc.textContent = "⚠️ Ο προηγούμενος κωδικός έληξε (15 λεπτά). Πατήστε το κουμπί για νέο κωδικό.";
          codexPendingBox.style.display = "none";
        } else if (codex.authenticated || codex.auth_state === "authenticated") {
          codexBadge.className = "badge badge-success";
          codexBadge.textContent = "Συνδεδεμένο";
          codexDesc.textContent = "✅ Συνδεδεμένο επιτυχώς με OpenAI ChatGPT (gpt-5.6-sol).";
          codexPendingBox.style.display = "none";
        } else {
          codexBadge.className = "badge badge-error";
          codexBadge.textContent = "Μη Συνδεδεμένο";
          codexDesc.textContent = "Αποσυνδεδεμένο. Πατήστε το κουμπί για έναρξη διαδικασίας σύνδεσης.";
          codexPendingBox.style.display = "none";
        }

        // 2. Antigravity CLI UI
        const agy = data.heavy_agent.antigravity || {};
        const agyBadge = document.getElementById("agy-badge");
        const agyDesc = document.getElementById("agy-desc");
        const agyPendingBox = document.getElementById("agy-pending-box");
        const agyAuthLink = document.getElementById("agy-auth-link");

        if (agy.auth_state === "pending") {
          agyBadge.className = "badge badge-warning";
          agyBadge.textContent = "Εκκρεμεί Σύνδεση";
          agyPendingBox.style.display = "block";
          if (agy.auth_url) {
            agyDesc.textContent = "Απαιτείται σύνδεση Google. Ανοίξτε τη σελίδα έγκρισης και επικολλήστε τον κωδικό:";
            agyAuthLink.href = agy.auth_url;
            agyAuthLink.style.display = "inline-block";
          } else {
            agyDesc.textContent = "⏳ Δημιουργία συνδέσμου Google OAuth... Παρακαλώ περιμένετε 2 δευτερόλεπτα.";
            agyAuthLink.style.display = "none";
          }
          agyRemainingSec = agy.remaining_seconds || 65;
          updateAgyTimerDisplay();
          const btnAgy = document.getElementById("btn-agy-trigger");
          if (btnAgy) {
            btnAgy.className = "btn btn-outline";
            btnAgy.textContent = "🔄 Επανεκκίνηση Συνεδρίας";
          }
        } else if (agy.auth_state === "expired") {
          agyBadge.className = "badge badge-warning";
          agyBadge.textContent = "Σύνδεση Έληξε";
          agyDesc.textContent = "⚠️ Η προηγούμενη σύνδεση έληξε (όριο 60 δευτερολέπτων). Πατήστε το παρακάτω κουμπί για άμεση έναρξη νέας σύνδεσης:";
          agyPendingBox.style.display = "none";
          const btnAgy = document.getElementById("btn-agy-trigger");
          if (btnAgy) {
            btnAgy.className = "btn btn-warning";
            btnAgy.textContent = "🔄 Έναρξη Νέας Σύνδεσης Google";
          }
        } else if (agy.authenticated || agy.auth_state === "authenticated") {
          agyBadge.className = "badge badge-success";
          agyBadge.textContent = "Συνδεδεμένο";
          agyDesc.textContent = "✅ Συνδεδεμένο επιτυχώς με Google Account (Gemini 3.8 / Pro).";
          agyPendingBox.style.display = "none";
          const btnAgy = document.getElementById("btn-agy-trigger");
          if (btnAgy) {
            btnAgy.className = "btn btn-outline";
            btnAgy.textContent = "🔑 Επανασύνδεση με Google";
          }
        } else {
          agyBadge.className = "badge badge-error";
          agyBadge.textContent = "Μη Συνδεδεμένο";
          agyDesc.textContent = "Αποσυνδεδεμένο. Πατήστε το κουμπί για έναρξη διαδικασίας σύνδεσης με Google.";
          agyPendingBox.style.display = "none";
          const btnAgy = document.getElementById("btn-agy-trigger");
          if (btnAgy) {
            btnAgy.className = "btn btn-primary";
            btnAgy.textContent = "🔑 Σύνδεση με Google";
          }
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

    function updateCodexTimerDisplay() {
      const mins = Math.floor(codexRemainingSec / 60).toString().padStart(2, '0');
      const secs = (codexRemainingSec % 60).toString().padStart(2, '0');
      const el = document.getElementById("codex-timer");
      if (el) el.textContent = `${mins}:${secs}`;
    }

    function updateAgyTimerDisplay() {
      const mins = Math.floor(agyRemainingSec / 60).toString().padStart(2, '0');
      const secs = (agyRemainingSec % 60).toString().padStart(2, '0');
      const el = document.getElementById("agy-timer");
      if (el) el.textContent = `${mins}:${secs}`;
    }

    function copyCodexCode() {
      if (!currentCodexCode) return;
      navigator.clipboard.writeText(currentCodexCode).then(() => {
        showToast("Ο κωδικός Codex αντιγράφηκε!");
      });
    }

    function showToast(msg) {
      const toast = document.getElementById("toast");
      toast.textContent = msg;
      toast.className = "copy-toast show";
      setTimeout(() => { toast.className = "copy-toast"; }, 2500);
    }

    async function triggerCodexAuth() {
      try {
        const btn = document.getElementById("btn-codex-trigger");
        if (btn) { btn.disabled = true; btn.textContent = "⏳ Παραγωγή..."; }
        await fetch("api/auth/codex/start", { method: "POST" });
        await fetchStatus();
      } catch (e) {
        alert("Σφάλμα έναρξης σύνδεσης Codex: " + e);
      } finally {
        const btn = document.getElementById("btn-codex-trigger");
        if (btn) { btn.disabled = false; btn.textContent = "🔑 Σύνδεση / Νέος Κωδικός"; }
      }
    }

    async function triggerAgyAuth() {
      try {
        const btn = document.getElementById("btn-agy-trigger");
        if (btn) { btn.disabled = true; btn.textContent = "⏳ Εκκίνηση..."; }
        await fetch("api/auth/antigravity/start", { method: "POST" });
        showToast("Εκκινήθηκε η σύνδεση Google Antigravity!");
        for (let i = 0; i < 4; i++) {
          await new Promise(r => setTimeout(r, 800));
          await fetchStatus();
        }
      } catch (e) {
        alert("Σφάλμα έναρξης σύνδεσης Antigravity: " + e);
      } finally {
        const btn = document.getElementById("btn-agy-trigger");
        if (btn) { btn.disabled = false; }
      }
    }

    async function submitAgyCode() {
      const input = document.getElementById("agy-code-input");
      const feedback = document.getElementById("agy-feedback");
      const btn = document.getElementById("btn-agy-submit");
      let codeVal = input.value.trim();
      if (!codeVal) {
        alert("Παρακαλώ εισάγετε τον κωδικό εξουσιοδότησης.");
        return;
      }

      // If user pasted full callback URL, extract code param
      if (codeVal.includes("code=")) {
        try {
          const urlObj = new URL(codeVal);
          const extracted = urlObj.searchParams.get("code");
          if (extracted) codeVal = extracted;
        } catch (e) {
          const match = codeVal.match(/[?&]code=([^&]+)/);
          if (match) codeVal = decodeURIComponent(match[1]);
        }
      }

      try {
        btn.disabled = true;
        btn.textContent = "⏳ Επιβεβαίωση...";
        feedback.style.color = "var(--text-muted)";
        feedback.textContent = "Υποβολή κωδικού και έλεγχος σύνδεσης...";

        const res = await fetch("api/auth/antigravity/submit-code", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: codeVal })
        });
        const data = await res.json();
        if (data.status === "success" || data.status === "authenticated") {
          feedback.style.color = "var(--success)";
          feedback.textContent = "🎉 Επιτυχής σύνδεση!";
          input.value = "";
          showToast("Το Antigravity CLI συνδέθηκε επιτυχώς!");
          setTimeout(fetchStatus, 1500);
        } else {
          feedback.style.color = "var(--warning)";
          feedback.textContent = data.message || "Ο κωδικός υποβλήθηκε. Ελέγχεται η κατάσταση...";
          setTimeout(fetchStatus, 2000);
        }
      } catch (e) {
        feedback.style.color = "var(--error)";
        feedback.textContent = "Σφάλμα υποβολής: " + e;
      } finally {
        btn.disabled = false;
        btn.textContent = "✅ Υποβολή Κωδικού & Ολοκλήρωση";
      }
    }

    // Local countdown ticker for Codex & Antigravity
    setInterval(() => {
      if (codexRemainingSec > 0) {
        codexRemainingSec--;
        updateCodexTimerDisplay();
      }
      if (agyRemainingSec > 0) {
        agyRemainingSec--;
        updateAgyTimerDisplay();
      }
    }, 1000);

    // TTS Controls: Dynamic Voice Mapping
    const TTS_VOICE_MAP = {
      "tts.google_cloud": [
        { id: "el-GR-Chirp3-HD-Laomedeia", name: "✨ Chirp3 HD Laomedeia (Προτεινόμενη HD Φυσική)" },
        { id: "el-GR-Chirp3-HD-Fenrir", name: "Chirp3 HD Fenrir (Ανδρική HD)" },
        { id: "el-GR-Chirp3-HD-Puck", name: "Chirp3 HD Puck (Ανδρική HD)" },
        { id: "el-GR-Chirp3-HD-Charon", name: "Chirp3 HD Charon (Ανδρική HD)" },
        { id: "el-GR-Chirp3-HD-Aoede", name: "Chirp3 HD Aoede (Γυναικεία HD)" },
        { id: "el-GR-Wavenet-A", name: "WaveNet A (Γυναικεία)" },
        { id: "el-GR-Wavenet-B", name: "WaveNet B (Ανδρική)" },
        { id: "el-GR-Wavenet-C", name: "WaveNet C (Γυναικεία)" },
        { id: "el-GR-Standard-A", name: "Standard A (Γυναικεία)" },
        { id: "el-GR-Standard-B", name: "Standard B (Ανδρική)" }
      ],
      "tts.edge_tts_2": [
        { id: "el-GR-NestorasNeural", name: "✨ Νέστορας (el-GR-NestorasNeural - Ανδρική)" },
        { id: "el-GR-AthinaNeural", name: "Αθηνά (el-GR-AthinaNeural - Γυναικεία)" }
      ],
      "tts.openai_tts_openai": [
        { id: "nova", name: "✨ Nova (Προτεινόμενη Φυσική & Εκφραστική)" },
        { id: "alloy", name: "Alloy (Ουδέτερη / Ευέλικτη)" },
        { id: "echo", name: "Echo (Ανδρική)" },
        { id: "fable", name: "Fable (Εκφραστική)" },
        { id: "onyx", name: "Onyx (Βαθιά Ανδρική)" },
        { id: "shimmer", name: "Shimmer (Καθαρή Γυναικεία)" }
      ],
      "tts.google_ai_tts": [
        { id: "kore", name: "✨ Kore (Gemini Speech)" },
        { id: "laomedeia", name: "Laomedeia (Gemini Speech)" },
        { id: "zephyr", name: "Zephyr (Gemini Speech)" },
        { id: "aoede", name: "Aoede (Gemini Speech)" },
        { id: "puck", name: "Puck (Gemini Speech)" },
        { id: "fenrir", name: "Fenrir (Gemini Speech)" }
      ],
      "tts.piper": [
        { id: "el_GR-rapunzelina-low", name: "Ραπουνζελίνα Low (Offline)" },
        { id: "el_GR-rapunzelina-medium", name: "Ραπουνζελίνα Medium (Offline)" },
        { id: "en_US-amy-low", name: "Amy (en_US-amy-low)" },
        { id: "en_US-lessac-medium", name: "Lessac (en_US-lessac-medium)" }
      ]
    };

    function populateVoices(engine, selectedVoice = "") {
      const voiceSelect = document.getElementById("tts-voice-select");
      const customInput = document.getElementById("tts-voice-custom");
      voiceSelect.innerHTML = "";

      const voices = TTS_VOICE_MAP[engine] || [];
      let found = false;

      voices.forEach(v => {
        const opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = v.name;
        if (selectedVoice && v.id === selectedVoice) {
          opt.selected = true;
          found = true;
        }
        voiceSelect.appendChild(opt);
      });

      // Add custom manual option
      const customOpt = document.createElement("option");
      customOpt.value = "__custom__";
      customOpt.textContent = "✏️ Άλλη φωνή (Χειροκίνητη πληκτρολόγηση)...";
      voiceSelect.appendChild(customOpt);

      if (selectedVoice && !found) {
        customOpt.selected = true;
        customInput.value = selectedVoice;
        customInput.style.display = "block";
      } else {
        customInput.style.display = "none";
        customInput.value = "";
      }
    }

    function onTtsEngineChange() {
      const eng = document.getElementById("tts-engine-select").value;
      populateVoices(eng);
    }

    function onTtsVoiceChange() {
      const voiceSelect = document.getElementById("tts-voice-select");
      const customInput = document.getElementById("tts-voice-custom");
      if (voiceSelect.value === "__custom__") {
        customInput.style.display = "block";
        customInput.focus();
      } else {
        customInput.style.display = "none";
      }
    }

    function getSelectedVoice() {
      const voiceSelect = document.getElementById("tts-voice-select");
      if (voiceSelect.value === "__custom__") {
        return document.getElementById("tts-voice-custom").value.trim();
      }
      return voiceSelect.value;
    }

    async function saveTtsSettings() {
      const engine = document.getElementById("tts-engine-select").value;
      const voice = getSelectedVoice();
      try {
        const res = await fetch("api/settings/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ engine, voice })
        });
        if (res.ok) {
          showToast("Οι ρυθμίσεις TTS αποθηκεύτηκαν!");
          const msg = document.getElementById("tts-save-msg");
          msg.style.display = "block";
          setTimeout(() => { msg.style.display = "none"; }, 3500);
        }
      } catch (e) {
        alert("Σφάλμα: " + e);
      }
    }

    // Initial fetch and auto-refresh loop
    fetchStatus();
    setInterval(fetchStatus, 4000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) fetchStatus();
    });
  </script>
</body>
</html>"""
