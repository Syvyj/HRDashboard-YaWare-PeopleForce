# Security Guidelines

## 🔒 Sensitive Data Protection

This project handles employee data and API credentials. Follow these security guidelines:

### Files to NEVER Commit

The following files contain sensitive data and are excluded via `.gitignore`:

- `.env` and `.env.*` - Environment variables with API keys, tokens, passwords
- `gcp-sa.json` - Google Cloud Service Account credentials
- `config/user_schedules.json` - Employee database with emails, names, IDs
- `config/work_schedules.json` - Work schedule configurations
- `instance/*.db` - Database files with attendance records
- `instance/week_notes.json`, `instance/monthly_notes.json` - Employee notes
- `backups/` - Backup directories

### Use Example Files

Instead of committing real data, use example files:

- `.env.example` - Template for environment variables
- `config/user_schedules.json.example` - Template for user schedules
- `instance/monthly_notes.json.example` - Template for monthly notes
- `instance/week_notes.json.example` - Template for weekly notes

### Before Publishing

1. **Check for sensitive data:**
   ```bash
   # Search for email domains
   grep -r "@yourcompany.com" --exclude-dir=.git .
   
   # Search for IP addresses
   grep -rE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" --exclude-dir=.git .
   
   # Search for API keys/tokens
   grep -riE "(api_key|token|secret|password)\s*=\s*['\"][^'\"]+['\"]" --exclude-dir=.git .
   ```

2. **Verify .gitignore:**
   - Ensure all sensitive files are listed
   - Check that example files (`.example`) are NOT ignored

3. **Review documentation:**
   - Replace real names/emails with examples
   - Remove server IPs and credentials
   - Use placeholder values

### Environment Variables

All sensitive configuration should be in environment variables:

- API keys and tokens
- Database URLs
- Server addresses
- Email addresses (if needed)

See `.env.example` for the complete list.

### Deployment Scripts

Deployment scripts use environment variables instead of hardcoded values:

```bash
# Set before running deploy scripts
export DEPLOY_HOST="user@your-server.com"
export DEPLOY_REMOTE_DIR="/path/to/project"
```

### Database Security

- Use strong `DASHBOARD_SECRET_KEY` for Flask sessions
- Use PostgreSQL in production (not SQLite)
- Restrict database access to application user only
- Enable SSL/TLS for database connections

### API Security

- Rotate API keys regularly
- Use read-only API keys when possible
- Monitor API usage for anomalies
- Store API credentials securely (environment variables, secret managers)

## 🛡️ Best Practices

1. **Never commit credentials** - Use environment variables or secret managers
2. **Use example files** - Provide templates without real data
3. **Review before commit** - Check `git status` and `git diff` before committing
4. **Use .gitignore** - Keep sensitive files out of version control
5. **Rotate credentials** - Change passwords/keys periodically
6. **Limit access** - Grant access only to necessary team members
7. **Monitor logs** - Check for suspicious activity

## 📝 Reporting Security Issues

If you discover a security vulnerability, please report it privately to the project maintainers rather than opening a public issue.
