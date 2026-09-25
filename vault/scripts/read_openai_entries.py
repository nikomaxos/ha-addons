"""Read openai-related config entries from HA via SSH."""
import paramiko
import os
import sys
import json
import base64

# Load .env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
env_vars = {}
with open(env_path) as f:
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val.strip('"')

host = env_vars.get('SSH_HOST', '192.168.50.10')
user = env_vars.get('SSH_USER', 'hassio')
password = env_vars.get('SSH_PASS', '')
port = int(env_vars.get('SSH_PORT', 22))

# Python script to run on the HA server
remote_script = '''
import json
with open("/config/.storage/core.config_entries") as f:
    data = json.load(f)
for e in data["data"]["entries"]:
    domain = e.get("domain", "")
    if "openai" in domain or "extended_openai" in domain:
        print("=== ENTRY ===")
        print(json.dumps(e, indent=2))
'''

# Base64 encode the script
encoded = base64.b64encode(remote_script.encode()).decode()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(host, port=port, username=user, password=password, timeout=10)
    cmd = f'echo "{encoded}" | base64 -d | python3'
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print("STDERR:", err, file=sys.stderr)
    sys.exit(exit_status)
finally:
    client.close()
