# 🧠 Antigravity Brain — Τεκμηρίωση & Οδηγός Χρήσης

[![Open Web UI](https://img.shields.io/badge/Open-Web%20UI-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white)](/api/hassio_ingress/3210f28f_antigravity_brain/)
[![Direct Access](https://img.shields.io/badge/Direct_Access-Port_8000-28a745?style=for-the-badge&logo=googlechrome&logoColor=white)](http://192.168.50.10:8000)

---

## 🚀 Πώς να ανοίξετε το Web Portal

Υπάρχουν 3 εύκολοι τρόποι για να συνδεθείτε στο Web UI:

1. **Από το Home Assistant Ingress:**  
   Κάντε κλικ στο **`OPEN WEB UI`** στην κορυφή του add-on ή πατήστε:  
   👉 **[🔗 Άνοιγμα Antigravity Web UI (Ingress)](/api/hassio_ingress/3210f28f_antigravity_brain/)**

2. **Από την Πλευρική Στήλη (Sidebar):**  
   Κάντε κλικ στην επιλογή 🧠 **Antigravity Brain** στο αριστερό μενού του Home Assistant.

3. **Απευθείας από το Τοπικό Δίκτυο (LAN):**  
   Ανοίξτε στον περιηγητή σας τη διεύθυνση:  
   👉 **[http://192.168.50.10:8000](http://192.168.50.10:8000)** *(ή με την IP του δικού σας Home Assistant)*

---

## 🔍 Τι παρέχει το Web Dashboard;

### 1. Ζωντανή Κατάσταση & Health Badges
* **OpenAI Codex CLI:** Πλήρης έλεγχος κατάστασης σύνδεσης και εγκυρότητας του ChatGPT token.
* **Google Antigravity CLI:** Πλήρης έλεγχος της εξουσιοδότησης λογαριασμού Google Cloud / Antigravity.
* **Διαγνωστικά Voice Assistant:** Επιβεβαίωση της σωστής δρομολόγησης ερωτημάτων μεταξύ Fast Agent και Heavy Agent.

### 2. Διαδραστική Σύνδεση & Επανεξουσιοδότηση (Re-Authentication)
* **Google OAuth (Antigravity CLI):**
  * Πατήστε το κουμπί **`🔄 Έναρξη Νέας Σύνδεσης Google`**.
  * Ακολουθήστε το παραγόμενο URL για έγκριση μέσω του Google λογαριασμού σας.
  * Επικολλήστε τον κωδικό εξουσιοδότησης στο πλαίσιο κειμένου και πατήστε **`Υποβολή Κωδικού`**.
* **OpenAI Device Code (Codex CLI):**
  * Πατήστε το κουμπί **`🔄 Έναρξη Νέας Σύνδεσης OpenAI`**.
  * Αντιγράψτε τον 8-ψήφιο κωδικό και μεταβείτε στο [https://auth0.openai.com/activate](https://auth0.openai.com/activate).
  * Παρακολουθήστε την αντίστροφη μέτρηση λήξης σε πραγματικό χρόνο.

### 3. Ρυθμίσεις Μοντέλων AI
* Επισκόπηση του επιλεγμένου κινητήρα 1ης φάσης (Fast Agent) και 2ης φάσης (Heavy Agent).
* Ρυθμίσεις βάθους σκέψης (Thinking levels).

### 4. Καθαρά Logs με Χρονική Σήμανση
* Κάθε εγγραφή περιλαμβάνει χρονοσφραγίδα `[YYYY-MM-DD HH:MM:SS]`.
* Αυτόματη εξοικονόμηση πόρων (παύση polling όταν η καρτέλα είναι στο παρασκήνιο).
