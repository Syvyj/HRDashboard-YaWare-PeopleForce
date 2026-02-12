#!/bin/bash
# Full deployment: code + configs (WITHOUT database)
# Usage: ./scripts/deploy_full.sh

set -e  # Exit on error

HOST="${DEPLOY_HOST:-deploy@your-server.com}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/deploy/www/YaWare_Bot}"

echo "========================================="
echo "FULL DEPLOYMENT to Production Server"
echo "Code + Configs (WITHOUT Database)"
echo "========================================="
echo ""
echo "⚠️  This will deploy code and config files"
echo "   Database will NOT be changed!"
echo ""
read -p "Continue with deployment? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 1
fi

echo ""
echo "🛑 Stopping gunicorn on server..."
ssh "$HOST" "cd $REMOTE_DIR && pkill -f 'gunicorn.*web_dashboard'"
sleep 2

echo ""
echo "📦 Creating full backup on server..."
ssh "$HOST" "cd $REMOTE_DIR && \
    timestamp=\$(date +%Y%m%d_%H%M%S) && \
    backup_dir=\"backups/server_backup_\${timestamp}\" && \
    echo \"Creating backup: \$backup_dir\" && \
    mkdir -p \$backup_dir && \
    cp -r instance/ \$backup_dir/ 2>/dev/null || true && \
    cp -r config/ \$backup_dir/ 2>/dev/null || true && \
    tar -czf \$backup_dir/code.tar.gz \
        dashboard_app/ \
        tasks/ \
        tracker_alert/ \
        templates/ \
        static/ \
        web_dashboard.py \
        requirements.txt \
        2>/dev/null || true && \
    echo \"✓ Backup created in \$backup_dir\""

echo ""
echo "📤 Uploading ALL files..."

# Upload code (same as deploy_code.sh)
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

echo "  → templates/"
rsync -av --delete templates/ "$HOST:$REMOTE_DIR/templates/"

echo "  → static/"
rsync -av --delete static/ "$HOST:$REMOTE_DIR/static/"

echo "  → web_dashboard.py"
scp web_dashboard.py "$HOST:$REMOTE_DIR/"

echo "  → requirements.txt"
scp requirements.txt "$HOST:$REMOTE_DIR/"

# Upload database and configs
echo ""
echo "� Uploading config files..."
echo "  → instance/monthly_notes.json"
scp instance/monthly_notes.json "$HOST:$REMOTE_DIR/instance/" 2>/dev/null || echo "    (file not found, skipping)"

echo "  → instance/week_notes.json"
scp instance/week_notes.json "$HOST:$REMOTE_DIR/instance/" 2>/dev/null || echo "    (file not found, skipping)"

echo "  → instance/monthly_adjustments.json"
scp instance/monthly_adjustments.json "$HOST:$REMOTE_DIR/instance/" 2>/dev/null || echo "    (file not found, skipping)"

echo "  → config/user_schedules.json"
scp config/user_schedules.json "$HOST:$REMOTE_DIR/config/"

echo "  → config/work_schedules.json"
scp config/work_schedules.json "$HOST:$REMOTE_DIR/config/" 2>/dev/null || echo "    (file not found, skipping)"

echo ""
echo "🔧 Setting permissions..."
ssh "$HOST" "cd $REMOTE_DIR && \
    chmod 644 instance/*.json 2>/dev/null || true && \
    chmod 644 config/*.json"

echo ""
echo "🔄 Starting gunicorn..."
ssh "$HOST" "cd $REMOTE_DIR && .venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 web_dashboard:app --timeout 120 --daemon"

echo ""
echo "⏳ Waiting for service to start..."
sleep 5

echo ""
echo "📊 Service status:"
ssh "$HOST" "ps aux | grep -i 'gunicorn.*web_dashboard' | grep -v grep"

echo ""
echo "✅ Full deployment completed!"
echo ""
echo "📋 Summary:"
echo "  • Code: ✓ deployed"
echo "  • Configs: ✓ deployed (user_schedules, notes)"
echo "  • Database: ✗ not changed (safe!)"
echo "  • Service: ✓ restarted"
echo ""
echo "📝 To check logs: ssh $HOST 'tail -f ~/www/YaWare_Bot/logs/*.log'"
echo "🌐 Dashboard: http://your-server.com:5000 (через nginx)"
