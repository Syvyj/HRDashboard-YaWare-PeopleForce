#!/bin/bash
# Deploy only code changes to production server
# Usage: ./scripts/deploy_code.sh

set -e  # Exit on error

HOST="${DEPLOY_HOST:-deploy@your-server.com}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/deploy/www/YaWare_Bot}"

echo "==================================="
echo "Deploying CODE to Production Server"
echo "==================================="
echo ""

# Check if there are uncommitted changes
if [[ -n $(git status -s) ]]; then
    echo "⚠️  Warning: You have uncommitted changes:"
    git status -s
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 1
    fi
fi

echo "📦 Creating backup on server..."
ssh "$HOST" "cd $REMOTE_DIR && \
    mkdir -p backups && \
    timestamp=\$(date +%Y%m%d_%H%M%S) && \
    echo \"Creating backup: backups/code_backup_\${timestamp}.tar.gz\" && \
    tar -czf backups/code_backup_\${timestamp}.tar.gz \
        dashboard_app/ \
        tasks/ \
        tracker_alert/ \
        templates/ \
        static/ \
        web_dashboard.py \
        requirements.txt \
        2>/dev/null || true"

echo ""
echo "📤 Uploading code files..."

# Upload Python code
echo "  → dashboard_app/"
rsync -av \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    dashboard_app/ "$HOST:$REMOTE_DIR/dashboard_app/"

echo "  → tasks/"
rsync -av --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    tasks/ "$HOST:$REMOTE_DIR/tasks/"

echo "  → tracker_alert/"
rsync -av --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    tracker_alert/ "$HOST:$REMOTE_DIR/tracker_alert/"

# Upload templates and static
echo "  → templates/"
rsync -av --delete templates/ "$HOST:$REMOTE_DIR/templates/"

echo "  → static/"
rsync -av --delete static/ "$HOST:$REMOTE_DIR/static/"

# Upload main files
echo "  → web_dashboard.py"
scp web_dashboard.py "$HOST:$REMOTE_DIR/"

echo "  → requirements.txt"
scp requirements.txt "$HOST:$REMOTE_DIR/"

echo ""
echo "🔄 Restarting gunicorn..."
ssh -t "$HOST" "cd $REMOTE_DIR && pkill -f 'gunicorn.*web_dashboard' && sleep 2 && .venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 web_dashboard:app --timeout 120 --daemon"

echo ""
echo "⏳ Waiting for service to start..."
sleep 3

echo ""
echo "📊 Service status:"
ssh "$HOST" "ps aux | grep -i 'gunicorn.*web_dashboard' | grep -v grep"

echo ""
echo "✅ Code deployment completed!"
echo ""
echo "📝 To check logs: ssh $HOST 'tail -f ~/www/YaWare_Bot/logs/*.log'"
echo "🌐 Dashboard: http://your-server.com:5000 (через nginx)"
