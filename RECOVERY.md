# Recovery Runbook

These commands are intended for the Oracle VM. Replace paths only if the deployment location differs.

## Restore the latest backup

1. Stop writes before restoring:

```bash
sudo systemctl stop swbot swbot-dashboard
```

2. List backups and test the archive first:

```bash
ls -lt /var/backups/swbot/swbot-*.tar.gz
cd /home/ubuntu/sw_announcement_bot
./ops/restore-test.sh /var/backups/swbot/swbot-YYYYMMDDTHHMMSSZ.tar.gz
```

3. Preserve the current runtime data, then extract the selected backup:

```bash
sudo mv /home/ubuntu/sw_announcement_bot/economy/economy.db \
  /home/ubuntu/sw_announcement_bot/economy/economy.db.before-restore
sudo tar -xzf /var/backups/swbot/swbot-YYYYMMDDTHHMMSSZ.tar.gz \
  -C /home/ubuntu/sw_announcement_bot
sudo chown -R ubuntu:ubuntu /home/ubuntu/sw_announcement_bot/economy \
  /home/ubuntu/sw_announcement_bot/guild_data
```

4. Start services and verify:

```bash
sudo systemctl start swbot swbot-dashboard
sudo systemctl status swbot swbot-dashboard --no-pager
curl --fail http://127.0.0.1:5000/health
```

Never restore `.env` from a backup. Recreate it from your secret manager and rotate credentials if compromise is suspected.

## Reset services

```bash
sudo systemctl daemon-reload
sudo systemctl restart swbot swbot-dashboard
sudo systemctl status swbot swbot-dashboard --no-pager
```

## Disable the dashboard temporarily

This leaves the bot running while removing the public dashboard service:

```bash
sudo systemctl stop swbot-dashboard
sudo systemctl disable swbot-dashboard
sudo systemctl disable nginx
sudo systemctl stop nginx
```

Re-enable it after the issue is understood:

```bash
sudo systemctl enable --now nginx
sudo systemctl enable --now swbot-dashboard
```

## Roll back the last deployment

```bash
cd /home/ubuntu/sw_announcement_bot
git log --oneline -5
git reset --hard KNOWN_GOOD_COMMIT
sudo systemctl restart swbot swbot-dashboard
curl --fail http://127.0.0.1:5000/health
```

Keep the last known-good commit in the deployment notes before each update. Do not use `git reset --hard` if you have uncommitted production changes you need to preserve.

## Gunicorn and Nginx installation

```bash
cd /home/ubuntu/sw_announcement_bot
./venv/bin/pip install -r requirements.txt
sudo cp dashboard/swbot-dashboard.service /etc/systemd/system/swbot-dashboard.service
sudo cp ops/swbot-nginx.conf /etc/nginx/sites-available/swbot-dashboard
sudo ln -sf /etc/nginx/sites-available/swbot-dashboard /etc/nginx/sites-enabled/swbot-dashboard
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now nginx swbot-dashboard
```

Obtain the certificate with Certbot, then set:

```env
DASHBOARD_PUBLIC_URL=https://swbotdashboard.duckdns.org
DISCORD_REDIRECT_URI=https://swbotdashboard.duckdns.org/callback
DASHBOARD_COOKIE_SECURE=1
```

Add the exact redirect URI to the main Discord application's OAuth2 settings and restart the dashboard.

## Monitoring tests

These simulate alerts without stopping production services. Run as root or with access to `/var/lib/swbot-monitor`:

```bash
sudo MONITOR_OUTPUT_ONLY=1 FORCE_BOT_OFFLINE=1 ./ops/monitor.sh
sudo MONITOR_OUTPUT_ONLY=1 FORCE_DASHBOARD_OFFLINE=1 ./ops/monitor.sh
sudo MONITOR_OUTPUT_ONLY=1 FORCE_HEALTH_FAILURE=1 ./ops/monitor.sh
sudo MONITOR_OUTPUT_ONLY=1 FORCE_RESTARTS=4 ./ops/monitor.sh
sudo MONITOR_OUTPUT_ONLY=1 FORCE_MEMORY_ALERT=1 ./ops/monitor.sh
sudo MONITOR_OUTPUT_ONLY=1 FORCE_OAUTH_FAILURES=6 ./ops/monitor.sh
```

For a real alert test, set `ALERT_WEBHOOK_URL` in the VM environment and inspect the private alert channel.
