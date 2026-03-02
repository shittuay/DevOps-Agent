---
name: run-app
description: Start the DevOps Agent Flask app (app.py) on port 5000. Kills any existing Python processes first to avoid port conflicts.
---

# Run App

Start the DevOps Agent Flask application at http://localhost:5000.

## Steps

1. **Kill any existing Python processes** to free port 5000:
   ```bash
   taskkill //F //IM python.exe 2>/dev/null
   ```

2. **Wait 1 second** for the port to be released.

3. **Start the app in the background**:
   ```bash
   cd C:\Users\shitt\Downloads\devops-agent
   python app.py
   ```
   Run this as a background task with a long timeout (600000ms).

4. **Wait ~8 seconds** for startup, then **health check**:
   ```bash
   curl -s http://localhost:5000/health
   ```

5. **Report result** to the user:
   - If health check returns `"status":"healthy"`, confirm the app is running
   - If it fails, read the background task output to diagnose the error
