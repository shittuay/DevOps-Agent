# ✅ Deployment Verification Checklist

Run these commands on your EC2 instance to verify everything is working correctly.

---

## 🔍 Step-by-Step Verification

### 1. Check Application Service Status
```bash
sudo systemctl status devops-agent
```

**✅ What to look for:**
- Status: `active (running)` in green
- No error messages
- Should see: "Started DevOps Agent Gunicorn Service"

**❌ If failed:**
```bash
# View detailed error logs
sudo journalctl -u devops-agent -n 50 --no-pager
```

---

### 2. Check Gunicorn Process
```bash
ps aux | grep gunicorn
```

**✅ What to look for:**
- Should see 5 processes (1 master + 4 workers)
- Binding to `127.0.0.1:8000`

**Example good output:**
```
ubuntu    1234  gunicorn: master [app:app]
ubuntu    1235  gunicorn: worker [app:app]
ubuntu    1236  gunicorn: worker [app:app]
ubuntu    1237  gunicorn: worker [app:app]
ubuntu    1238  gunicorn: worker [app:app]
```

---

### 3. Check Application Logs
```bash
sudo journalctl -u devops-agent -n 30 --no-pager
```

**✅ What to look for:**
- No Python tracebacks/errors
- Should see: "Database initialized"
- Should see: "Agent initialized with 48 tools"
- Should see: "Booting worker with pid"

**❌ Common errors to watch for:**
- Database connection errors
- Missing environment variables
- Import errors
- Permission errors

---

### 4. Test Application Port
```bash
curl http://127.0.0.1:8000
```

**✅ What to look for:**
- Should return HTML content
- No "Connection refused" error
- Should see `<!DOCTYPE html>` in response

**Alternative test:**
```bash
curl -I http://127.0.0.1:8000
```
Should show: `HTTP/1.1 200 OK` or `HTTP/1.1 302 FOUND`

---

### 5. Check Nginx Status
```bash
sudo systemctl status nginx
```

**✅ What to look for:**
- Status: `active (running)` in green
- No error messages

---

### 6. Check Nginx Configuration
```bash
sudo nginx -t
```

**✅ What to look for:**
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

### 7. Test Public Access
```bash
# Get your public IP
curl http://169.254.169.254/latest/meta-data/public-ipv4

# Test external access
curl -I http://YOUR_PUBLIC_IP
```

**✅ What to look for:**
- `HTTP/1.1 200 OK` or `HTTP/1.1 302 FOUND`
- No connection timeout

---

### 8. Check Database Connection
```bash
cd /var/www/devops-agent
source venv/bin/activate
python3 << 'EOF'
from app import app, db, User
try:
    with app.app_context():
        # Try to query database
        count = User.query.count()
        print(f"✅ Database connected! Users in DB: {count}")
except Exception as e:
    print(f"❌ Database error: {e}")
EOF
```

**✅ What to look for:**
- "✅ Database connected!"
- No connection errors

---

### 9. Check PostgreSQL Status
```bash
sudo systemctl status postgresql
```

**✅ What to look for:**
- Status: `active (running)`
- Should show port 5432 listening

---

### 10. Check Database Tables
```bash
sudo -u postgres psql devops_agent -c "\dt"
```

**✅ What to look for:**
Should list these tables:
- users
- conversations
- chat_messages
- usage_logs
- user_preferences
- notification_settings

---

### 11. Check Ports Are Open
```bash
sudo netstat -tlnp | grep -E ':(80|8000|5432)'
```

**✅ What to look for:**
```
tcp  0.0.0.0:80     LISTEN  nginx
tcp  127.0.0.1:8000 LISTEN  gunicorn
tcp  127.0.0.1:5432 LISTEN  postgres
```

---

### 12. Check Disk Space
```bash
df -h
```

**✅ What to look for:**
- Root volume usage < 80%
- At least 2GB free space

---

### 13. Check Memory Usage
```bash
free -h
```

**✅ What to look for:**
- Available memory > 200MB
- Not swapping heavily

---

### 14. Test Browser Access
Open your browser and go to:
```
http://YOUR_EC2_PUBLIC_IP
```

**✅ What to look for:**
- Login page loads
- No 502/503 errors
- Page loads in < 5 seconds

---

### 15. Check Environment Variables
```bash
cat /var/www/devops-agent/.env | grep -v "SECRET\|PASSWORD\|KEY"
```

**✅ Verify file exists and has:**
- FLASK_ENV=production
- DATABASE_URL is set
- (Keys are present but values hidden for security)

---

### 16. View Live Logs
```bash
# Terminal 1: Application logs
sudo journalctl -u devops-agent -f

# Terminal 2: Nginx access logs
sudo tail -f /var/log/nginx/access.log

# Terminal 3: Nginx error logs
sudo tail -f /var/log/nginx/error.log
```

Then visit your site in browser and watch logs scroll.

---

## 🧪 Functional Tests

### Test 1: User Registration
```bash
curl -X POST http://localhost:8000/signup \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=test@example.com&password=testpass123&confirm_password=testpass123"
```

**✅ Should redirect (302) or return success**

### Test 2: Database Persistence
```bash
# Restart service
sudo systemctl restart devops-agent

# Check if data persists
cd /var/www/devops-agent
source venv/bin/activate
python3 -c "from app import app, User; app.app_context().push(); print(f'Users: {User.query.count()}')"
```

**✅ User count should remain the same after restart**

---

## 📊 Quick Health Check Script

Run this all-in-one health check:

```bash
#!/bin/bash
echo "=== DevOps Agent Health Check ==="
echo ""

echo "1. Application Service:"
sudo systemctl is-active devops-agent && echo "✅ Running" || echo "❌ Not running"

echo ""
echo "2. Nginx Service:"
sudo systemctl is-active nginx && echo "✅ Running" || echo "❌ Not running"

echo ""
echo "3. PostgreSQL Service:"
sudo systemctl is-active postgresql && echo "✅ Running" || echo "❌ Not running"

echo ""
echo "4. Application Port (8000):"
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000 | grep -E "200|302" > /dev/null && echo "✅ Responding" || echo "❌ Not responding"

echo ""
echo "5. Public Web Access (80):"
curl -s -o /dev/null -w "%{http_code}" http://localhost | grep -E "200|302" > /dev/null && echo "✅ Responding" || echo "❌ Not responding"

echo ""
echo "6. Disk Space:"
df -h / | awk 'NR==2 {if (substr($5,1,length($5)-1) < 80) print "✅ OK ("$5" used)"; else print "❌ Low ("$5" used)"}'

echo ""
echo "7. Memory:"
free -h | awk 'NR==2 {if ($7 ~ /G/) print "✅ OK ("$7" available)"; else if (substr($7,1,length($7)-1) > 200) print "✅ OK ("$7" available)"; else print "❌ Low ("$7" available)"}'

echo ""
echo "8. Recent Errors in App Logs:"
ERROR_COUNT=$(sudo journalctl -u devops-agent --since "5 minutes ago" | grep -i error | wc -l)
if [ $ERROR_COUNT -eq 0 ]; then
    echo "✅ No errors in last 5 minutes"
else
    echo "⚠️  $ERROR_COUNT errors found in last 5 minutes"
fi

echo ""
echo "=== Health Check Complete ==="
```

Save as `health_check.sh` and run:
```bash
chmod +x health_check.sh
./health_check.sh
```

---

## ❌ Common Issues & Fixes

### Issue: 502 Bad Gateway
**Cause:** Gunicorn not running

**Fix:**
```bash
sudo systemctl restart devops-agent
sudo journalctl -u devops-agent -n 50
```

---

### Issue: Database Connection Error
**Cause:** Wrong DATABASE_URL or PostgreSQL not running

**Fix:**
```bash
# Check PostgreSQL
sudo systemctl status postgresql

# Check .env file
cat /var/www/devops-agent/.env | grep DATABASE_URL

# Test connection manually
psql -h localhost -U devopsagent -d devops_agent
```

---

### Issue: Permission Denied
**Cause:** Wrong file ownership

**Fix:**
```bash
sudo chown -R ubuntu:ubuntu /var/www/devops-agent
sudo chmod 600 /var/www/devops-agent/.env
sudo systemctl restart devops-agent
```

---

### Issue: Port Already in Use
**Cause:** Old process still running

**Fix:**
```bash
sudo lsof -i :8000
sudo kill -9 <PID>
sudo systemctl restart devops-agent
```

---

## ✅ Final Checklist

After running all checks, verify:

- [ ] `sudo systemctl status devops-agent` shows **active (running)**
- [ ] `sudo systemctl status nginx` shows **active (running)**
- [ ] `sudo systemctl status postgresql` shows **active (running)**
- [ ] `curl http://127.0.0.1:8000` returns HTML content
- [ ] Browser can access `http://YOUR_PUBLIC_IP`
- [ ] Login page loads correctly
- [ ] No errors in: `sudo journalctl -u devops-agent -n 50`
- [ ] Database tables exist
- [ ] Can register a new user
- [ ] Can login with test user
- [ ] Chat interface loads

---

## 🎉 If All Checks Pass

**Congratulations!** Your DevOps Agent is deployed and running correctly.

**Next steps:**
1. Register your admin account
2. Test the chat functionality
3. Setup SSL certificate: `sudo certbot --nginx -d yourdomain.com`
4. Setup monitoring and backups
5. Configure your custom domain (if needed)

---

## 📞 Still Having Issues?

Run this and share the output:
```bash
sudo journalctl -u devops-agent -n 100 --no-pager > /tmp/app_logs.txt
sudo systemctl status devops-agent --no-pager > /tmp/service_status.txt
cat /tmp/app_logs.txt
cat /tmp/service_status.txt
```
