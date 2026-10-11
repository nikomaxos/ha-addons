import os
import re
import time
import subprocess
import threading
import requests as http_requests

class CodexAuthManager:
    """Manages the autonomous lifecycle of OpenAI Codex CLI authorization."""

    def __init__(self, supervisor_url: str = "http://supervisor/core/api", get_supervisor_token_fn = None):
        self.supervisor_url = supervisor_url
        self.get_supervisor_token = get_supervisor_token_fn or (lambda: os.environ.get("SUPERVISOR_TOKEN", ""))
        self.lock = threading.Lock()
        self.codex_bin = None
        self.is_authenticated = False
        self.auth_pending = False
        self.auth_url = "https://auth.openai.com/codex/device"
        self.device_code = ""
        self.expires_at = 0.0
        self.proc = None
        self.worker_thread = None

        self._find_binary()
        self._ensure_storage_symlink()

    def _find_binary(self):
        import shutil
        for cand in ["./codex", "/usr/src/app/codex", "codex", "codex.exe"]:
            if os.path.exists(cand) or shutil.which(cand):
                self.codex_bin = cand
                return
        self.codex_bin = None

    def _ensure_storage_symlink(self):
        try:
            os.makedirs("/data/.codex", exist_ok=True)
            if not os.path.exists("/root/.codex"):
                os.symlink("/data/.codex", "/root/.codex")
            elif not os.path.islink("/root/.codex"):
                import shutil
                for item in os.listdir("/root/.codex"):
                    src = os.path.join("/root/.codex", item)
                    dst = os.path.join("/data/.codex", item)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                shutil.rmtree("/root/.codex")
                os.symlink("/data/.codex", "/root/.codex")
        except Exception as e:
            print(f"[CodexAuthManager] Symlink check note: {e}", flush=True)

    def _headers(self):
        token = self.get_supervisor_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def check_status(self) -> bool:
        """Check if Codex CLI is currently authenticated with ChatGPT."""
        if not self.codex_bin:
            self._find_binary()
        if not self.codex_bin:
            self.is_authenticated = False
            return False

        try:
            res = subprocess.run([self.codex_bin, "login", "status"], capture_output=True, text=True, timeout=8)
            combined = (res.stdout + res.stderr).lower()
            if "logged in" in combined and "not logged in" not in combined:
                if not self.is_authenticated or self.auth_pending:
                    print("[CodexAuthManager] Authenticated status confirmed!", flush=True)
                self.is_authenticated = True
                if self.auth_pending:
                    self._on_auth_success()
                return True
            else:
                self.is_authenticated = False
                return False
        except Exception as e:
            print(f"[CodexAuthManager] check_status error: {e}", flush=True)
            return False

    def start_auth_flow(self, force=False) -> dict:
        """Start the device auth flow non-interactively in a background worker."""
        with self.lock:
            if not force and self.check_status():
                return {"status": "already_authenticated"}

            if self.auth_pending and self.proc and self.proc.poll() is None:
                return {
                    "status": "pending",
                    "auth_url": self.auth_url,
                    "device_code": self.device_code
                }

            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except Exception:
                    pass

            self.auth_pending = True
            self.auth_url = "https://auth.openai.com/codex/device"
            self.device_code = ""
            self.expires_at = time.time() + 900

            self.worker_thread = threading.Thread(target=self._auth_worker, daemon=True)
            self.worker_thread.start()

            return {"status": "starting"}

    def _auth_worker(self):
        print("\n" + "=" * 60, flush=True)
        print("🔑 [CodexAuthManager] Starting Autonomous Device Auth Flow...", flush=True)
        print("=" * 60 + "\n", flush=True)

        try:
            self.proc = subprocess.Popen(
                [self.codex_bin, "login", "--device-auth"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            code_notified = False

            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break

                line_str = line.strip()
                if line_str:
                    print(f"[Codex Auth] {line_str}", flush=True)

                url_match = re.search(r'(https://auth\.openai\.com/codex/device[^\s]*)', line_str)
                if url_match:
                    self.auth_url = url_match.group(1)

                code_match = re.search(r'\b([A-Z0-9]{4,5}-[A-Z0-9]{4,5})\b', line_str)
                if code_match and not code_notified:
                    self.device_code = code_match.group(1)
                    code_notified = True
                    print(f"[CodexAuthManager] Device Code: {self.device_code}, URL: {self.auth_url}", flush=True)
                    self._notify_ha_device_code()

            self.proc.wait()
            ret = self.proc.returncode
            print(f"[CodexAuthManager] Process exited (code {ret})", flush=True)

            time.sleep(2)
            if self.check_status():
                self._on_auth_success()
            else:
                self.auth_pending = False

        except Exception as e:
            print(f"[CodexAuthManager] Worker exception: {e}", flush=True)
            self.auth_pending = False

    def _notify_ha_device_code(self):
        token = self.get_supervisor_token()
        if not token:
            return

        msg_markdown = (
            f"### 🔑 Απαιτείται Σύνδεση Codex CLI (OpenAI)\n\n"
            f"Για να ενεργοποιηθεί η εκτέλεση σύνθετων εργασιών μέσω του μοντέλου **Codex (ChatGPT)**, ακολουθήστε τα παρακάτω βήματα:\n\n"
            f"1. Ανοίξτε τη σελίδα: **[{self.auth_url}]({self.auth_url})**\n"
            f"2. Εισάγετε τον κωδικό:\n"
            f"## `{self.device_code}`\n\n"
            f"*(Ισχύει για 15 λεπτά)*\n\n"
            f"💡 *Μόλις εγκρίνετε τη σύνδεση στον περιηγητή, η ειδοποίηση αυτή θα κλείσει αυτόματα και το Antigravity Brain θα είναι έτοιμο!*"
        )

        # 1. Create Persistent Notification
        try:
            url = f"{self.supervisor_url}/services/persistent_notification/create"
            payload = {
                "notification_id": "antigravity_codex_auth",
                "title": f"🔑 Σύνδεση Codex CLI ({self.device_code})",
                "message": msg_markdown
            }
            http_requests.post(url, headers=self._headers(), json=payload, timeout=5)
            print("[CodexAuthManager] Created Home Assistant Persistent Notification.", flush=True)
        except Exception as e:
            print(f"[CodexAuthManager] Failed persistent notification: {e}", flush=True)

        # 2. Send Mobile Push Notification
        try:
            url = f"{self.supervisor_url}/services/notify/notify"
            payload = {
                "title": f"🔑 Σύνδεση Codex CLI: {self.device_code}",
                "message": f"Κωδικός: {self.device_code}. Πατήστε για άνοιγμα του {self.auth_url}",
                "data": {
                    "url": self.auth_url,
                    "clickAction": self.auth_url
                }
            }
            http_requests.post(url, headers=self._headers(), json=payload, timeout=5)
            print("[CodexAuthManager] Sent Home Assistant Push Notification.", flush=True)
        except Exception as e:
            print(f"[CodexAuthManager] Failed push notification: {e}", flush=True)

        # 3. Fire custom event
        try:
            url = f"{self.supervisor_url}/events/antigravity_auth_required"
            payload = {
                "engine": "codex",
                "auth_url": self.auth_url,
                "device_code": self.device_code
            }
            http_requests.post(url, headers=self._headers(), json=payload, timeout=5)
        except Exception:
            pass

    def _on_auth_success(self):
        self.is_authenticated = True
        self.auth_pending = False
        self.device_code = ""

        print("\n" + "=" * 60, flush=True)
        print("🎉 [CodexAuthManager] CODEX CLI AUTHENTICATED SUCCESSFULLY! 🎉", flush=True)
        print("=" * 60 + "\n", flush=True)

        token = self.get_supervisor_token()
        if not token:
            return

        # 1. Dismiss Persistent Notification
        try:
            url = f"{self.supervisor_url}/services/persistent_notification/dismiss"
            http_requests.post(url, headers=self._headers(), json={"notification_id": "antigravity_codex_auth"}, timeout=5)
            print("[CodexAuthManager] Dismissed HA Persistent Notification.", flush=True)
        except Exception as e:
            print(f"[CodexAuthManager] Failed to dismiss notification: {e}", flush=True)

        # 2. Send Success Push Notification
        try:
            url = f"{self.supervisor_url}/services/notify/notify"
            payload = {
                "title": "✅ Codex CLI Συνδέθηκε!",
                "message": "Το Codex CLI συνδέθηκε επιτυχώς. Το Antigravity Brain είναι πλέον 100% έτοιμο για σύνθετες εργασίες.",
                "data": {
                    "url": "/notifications",
                    "clickAction": "/notifications"
                }
            }
            http_requests.post(url, headers=self._headers(), json=payload, timeout=5)
        except Exception as e:
            print(f"[CodexAuthManager] Failed success push: {e}", flush=True)

        # 3. Fire completion event
        try:
            url = f"{self.supervisor_url}/events/antigravity_auth_completed"
            http_requests.post(url, headers=self._headers(), json={"engine": "codex", "status": "authenticated"}, timeout=5)
        except Exception:
            pass

        # 4. Announce via TTS outside DND hours (08:00-14:00, 17:30-22:00)
        try:
            import datetime
            now_hour = datetime.datetime.now().hour
            if (8 <= now_hour < 14) or (17 <= now_hour < 22):
                tts_url = f"{self.supervisor_url}/services/tts/google_cloud_say"
                payload = {
                    "entity_id": "media_player.antigravity_satellites",
                    "message": "Η σύνδεση του Codex ολοκληρώθηκε επιτυχώς."
                }
                http_requests.post(tts_url, headers=self._headers(), json=payload, timeout=5)
        except Exception as e:
            print(f"[CodexAuthManager] TTS announcement note: {e}", flush=True)
