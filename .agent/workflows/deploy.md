---
description: Deploy the application to the production server and restart Gunicorn
---

# Deployment Workflow

This workflow documents the process of deploying changes to the production server and restarting the Gunicorn web server.

## Prerequisites
- SSH access to `user@your-server.com`
- Subproject path: `~/www/YaWare_Bot`

## Steps

### 1. Upload Files
Copy the modified files to the server using `scp`.
Example for `dashboard_app/api.py`:
// turbo
```bash
scp /path/to/YaWare_Bot/dashboard_app/api/employees.py user@your-server.com:/path/to/YaWare_Bot/dashboard_app/api/
```
> [!NOTE]
> Adjust the path for other files as needed.

### 2. Restart Gunicorn
Restart the server to apply changes.
// turbo
```bash
ssh user@your-server.com 'pkill -f gunicorn && sleep 2 && cd /path/to/YaWare_Bot && source .venv/bin/activate && gunicorn -w 4 -b 127.0.0.1:8000 --daemon web_dashboard:app'
```

### 3. Verify Status
Check if Gunicorn is running (should be 5 processes: 1 master + 4 workers).
// turbo
```bash
ssh user@your-server.com 'ps aux | grep gunicorn | grep -v grep'
```

### 4. Check Logs
Monitor for any errors after restart.
// turbo
```bash
ssh user@your-server.com 'tail -50 /path/to/YaWare_Bot/logs/gunicorn-error.log'
```

### 5. Connection Test
Verify the app is responding correctly on the server.
// turbo
```bash
ssh user@your-server.com 'curl -I http://127.0.0.1:8000/login'
```
