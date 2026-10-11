# 🧠 Antigravity Brain Dashboard & Portal

[![Open Web UI](https://img.shields.io/badge/Open-Web%20UI-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white)](/api/hassio_ingress/3210f28f_antigravity_brain/)
[![Direct Access](https://img.shields.io/badge/Direct_Access-Port_8000-28a745?style=for-the-badge&logo=googlechrome&logoColor=white)](http://192.168.50.10:8000)
[![Version](https://img.shields.io/badge/Version-3.2.2-blue?style=for-the-badge)](#)

---

### 🚀 Γρήγορη Μετάβαση στο Web Portal (Web UI)

Μπορείτε να ανοίξετε το Web Dashboard του **Antigravity Brain** άμεσα με τους παρακάτω τρόπους:

* **Κουμπί Ingress:** Πατήστε το κουμπί **`OPEN WEB UI`** στο επάνω μέρος αυτής της καρτέλας, ή κάντε κλικ εδώ:  
  👉 **[🔗 Άνοιγμα Antigravity Web UI (Ingress)](/api/hassio_ingress/3210f28f_antigravity_brain/)**
* **Πλευρική Στήλη (Sidebar):** Επιλέξτε το εικονίδιο 🧠 **Antigravity Brain** από το αριστερό κεντρικό μενού του Home Assistant.
* **Απευθείας Σύνδεσμος Τοπικού Δικτύου:** Ανοίξτε σε οποιονδήποτε περιηγητή (browser):  
  👉 **[http://192.168.50.10:8000](http://192.168.50.10:8000)** *(ή `http://<IP_HOME_ASSISTANT>:8000`)*

---

### 📍 Πού υπάρχει το Portal;

1. **Στην Πλευρική Στήλη (Sidebar Panel) του Home Assistant:**
   * Το add-on είναι ρυθμισμένο με `ingress_panel: true`. Θα το βρείτε καρφιτσωμένο στην αριστερή στήλη πλοήγησης του Home Assistant με όνομα **Antigravity Brain** και εικονίδιο `mdi:brain`.
2. **Στην Κεφαλίδα του Add-on (Info Tab):**
   * Στην παρούσα καρτέλα ("Info / Πληροφορίες") του add-on υπάρχει το επίσημο κουμπί **`OPEN WEB UI`** (Άνοιγμα Web UI) ακριβώς δίπλα στα κουμπιά ελέγχου λειτουργίας (Start / Stop / Restart).
3. **Αυτόνομο Web Interface στο Port 8000:**
   * Ο ενσωματωμένος FastAPI server εξυπηρετεί πλήρες web portal στην πόρτα `8000` για απευθείας πρόσβαση από υπολογιστή, tablet ή κινητό εντός του τοπικού σας δικτύου (LAN).

---

### 🔍 Τι μπορείτε να δείτε και να κάνετε στο Web Portal;

Το **Antigravity Brain Web Portal** είναι το κεντρικό κέντρο ελέγχου και πιστοποίησης των AI Voice Assistants:

#### 1. 🟢 Ζωντανή Κατάσταση Μηχανών AI (Live Status & Badges)
* **OpenAI Codex CLI:** Ένδειξη σύνδεσης, ενεργή κατάσταση authentication, έλεγχος ισχύος session και refresh tokens.
* **Google Antigravity CLI:** Ένδειξη σύνδεσης Google OAuth, κατάσταση εγκυρότητας token και ενεργού λογαριασμού.
* **Fast Agent & Heavy Agent:** Επισκόπηση της αρχιτεκτονικής 2 φάσεων (Άμεση φωνητική απόκριση <1.5s και παρασκηνιακή βαριά έρευνα).

#### 2. 🔑 Διαδραστική Εξουσιοδότηση (Re-Authentication Controls)
* **Σύνδεση Google (Antigravity CLI):**
  * Κουμπί **`🔄 Έναρξη Νέας Σύνδεσης Google`** για άμεση παραγωγή νέου URL εξουσιοδότησης.
  * Εμφάνιση του συνδέσμου σύνδεσης της Google.
  * Πεδίο επικόλλησης κωδικού εξουσιοδότησης (**Authorization Code Input Box**) με κουμπί **`Υποβολή Κωδικού`** για ολοκλήρωση σε δευτερόλεπτα χωρίς τερματικό.
* **Σύνδεση OpenAI (Codex CLI):**
  * Κουμπί **`🔄 Έναρξη Νέας Σύνδεσης OpenAI`** για άμεση παραγωγή 8-ψήφιου Device Code (π.χ. `WDXX-ABCD`).
  * Άμεσος σύνδεσμος για το [https://auth0.openai.com/activate](https://auth0.openai.com/activate).
  * **Αντίστροφη μέτρηση σε πραγματικό χρόνο (Countdown Timer)** πριν από τη λήξη του κωδικού (15 λεπτά).

#### 3. 🔊 Επιλογή Μηχανής & Φωνής TTS (Text-to-Speech Settings)
* **Δυνατότητα επιλογής TTS Engine & Voice:**
  * Επιλέξτε ανάμεσα σε **Google Cloud TTS**, **Microsoft Edge TTS**, **OpenAI TTS**, **Piper Local**, ή **Google AI TTS**.
  * Ορίστε τη φωνή της αρεσκείας σας (π.χ. `el-GR-Chirp3-HD-Laomedeia`, `el-GR-NestorasNeural`, `nova`, κ.α.).
  * Η επιλεγμένη μηχανή και φωνή χρησιμοποιούνται αυτόματα από τον αυτοματισμό εκφώνησης των απαντήσεων του Heavy Agent (`antigravity_heavy_agent_tts`).

#### 4. ⚙️ Επισκόπηση Ρυθμίσεων & Παραμέτρων
* Προβολή των τρεχόντων επιλεγμένων μοντέλων:
  * **Phase 1 Fast Agent:** Instant model (Gemini 3.8 Flash) & Thinking level.
  * **Phase 2 Heavy Agent:** Deep research engine (Codex Fallback / Antigravity) & Thinking level.

#### 5. 📜 Ζωντανά Logs με Timestamps
* Παρακολούθηση της επικοινωνίας του φωνητικού βοηθού και των εκτελέσεων εργασιών σε πραγματικό χρόνο.
* Κάθε καταγραφή ξεκινά με ακριβές timestamp `[YYYY-MM-DD HH:MM:SS]`.
* Αυτόματη παύση αιτημάτων όταν η καρτέλα είναι στο παρασκήνιο (Page Visibility API) για μηδενική επιβάρυνση του δικτύου.
