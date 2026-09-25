import paramiko
import sys
import os

# Load variables from .env
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

command = sys.argv[1] if len(sys.argv) > 1 else 'echo "No command provided"'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(host, port=port, username=user, password=password, timeout=10)
    stdin, stdout, stderr = client.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
        
    sys.exit(exit_status)
finally:
    client.close()
