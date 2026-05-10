# SentinelVault Backend Hosting Guide

## Quick Start (Local Development)

### Prerequisites
- Python 3.9+
- pip or poetry

### Setup

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server
python server.py
```

Server runs on `http://localhost:8080`
API docs: `http://localhost:8080/docs`

---

## Docker Deployment

### Build Docker Image

```bash
cd backend
docker build -t sentinelvault-backend:latest .
```

### Run Docker Container Locally

```bash
docker run -d \
  -p 8080:8080 \
  -v $(pwd)/sentinel_fleet.db:/app/sentinel_fleet.db \
  --name sentinelvault-backend \
  sentinelvault-backend:latest
```

### Docker Compose (Recommended for production)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  backend:
    build: .
    ports:
      - "8080:8080"
    environment:
      - HOST=0.0.0.0
      - PORT=8080
      - DEBUG=False
    volumes:
      - ./sentinel_fleet.db:/app/sentinel_fleet.db
    restart: always
```

Run with:
```bash
docker-compose up -d
```

---

## Cloud Hosting Options

### 1. Heroku (Easiest, Free tier available)

```bash
# Install Heroku CLI
brew install heroku/brew/heroku

# Login
heroku login

# Create app
heroku create sentinelvault-backend

# Deploy
git push heroku main

# View logs
heroku logs --tail
```

Requires `Procfile` in root:
```
web: gunicorn -w 4 -b 0.0.0.0:$PORT backend.server:app
```

### 2. Railway.app (Modern, simple, good free tier)

1. Go to https://railway.app
2. Create new project
3. Connect GitHub repo
4. Set environment variables
5. Deploy (automatic on git push)

### 3. Render (Free tier with auto-sleep, paid tiers available)

1. Go to https://render.com
2. Create new "Web Service"
3. Connect GitHub
4. Set build command: `pip install -r backend/requirements.txt`
5. Set start command: `cd backend && python server.py`
6. Deploy

### 4. AWS (Production-grade)

#### Option A: EC2 + Gunicorn + Nginx

```bash
# SSH into EC2 instance
ssh -i your-key.pem ec2-user@your-instance.ip

# Install dependencies
sudo yum install python3 python3-pip nginx
cd /home/ec2-user
git clone your-repo.git
cd your-repo/backend

# Setup virtual env
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn

# Create systemd service file
sudo tee /etc/systemd/system/sentinelvault.service > /dev/null << EOF
[Unit]
Description=SentinelVault Backend
After=network.target

[Service]
Type=notify
User=ec2-user
WorkingDirectory=/home/ec2-user/your-repo/backend
Environment="PATH=/home/ec2-user/your-repo/backend/venv/bin"
ExecStart=/home/ec2-user/your-repo/backend/venv/bin/gunicorn -w 4 -b 127.0.0.1:8080 server:app

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl enable sentinelvault
sudo systemctl start sentinelvault

# Configure Nginx
sudo tee /etc/nginx/conf.d/sentinelvault.conf > /dev/null << EOF
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo systemctl restart nginx
```

#### Option B: AWS Elastic Beanstalk (Easiest AWS option)

```bash
# Install EB CLI
pip install awsebcli

# Initialize
eb init -p python-3.11 sentinelvault-backend

# Create environment
eb create sentinelvault-prod

# Deploy
eb deploy

# Open in browser
eb open
```

### 5. Google Cloud Run (Serverless, pay per request)

```bash
# Build and push image
docker build -t gcr.io/your-project/sentinelvault-backend .
docker push gcr.io/your-project/sentinelvault-backend

# Deploy
gcloud run deploy sentinelvault-backend \
  --image gcr.io/your-project/sentinelvault-backend \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### 6. DigitalOcean App Platform (Recommended value)

1. Go to https://cloud.digitalocean.com/apps
2. Click "Create App"
3. Select your GitHub repo
4. Choose Python runtime
5. Set build: `pip install -r backend/requirements.txt`
6. Set run: `python backend/server.py`
7. Deploy (pay ~$5-12/month)

---

## SSL/HTTPS Setup

### Using Let's Encrypt (Free SSL)

```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal (automatic on Ubuntu)
sudo systemctl enable certbot.timer
```

---

## Monitoring & Logging

### Basic Logging
The server logs to `server.log`. For production, use:

```bash
# Systemd logging
journalctl -u sentinelvault -f

# Or cloud provider logs:
# AWS CloudWatch, Google Cloud Logging, etc.
```

### Health Check Endpoint
Add to server.py if not present:
```python
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

---

## Database Persistence

For production, use managed databases instead of SQLite:

### Option 1: PostgreSQL (Recommended)
```bash
# Install PostgreSQL
brew install postgresql  # macOS
# or use cloud: AWS RDS, Heroku Postgres, etc.

# Update server.py to use PostgreSQL
pip install psycopg2-binary
```

### Option 2: Cloud Database Services
- **AWS RDS** - PostgreSQL/MySQL/MariaDB
- **Google Cloud SQL** - PostgreSQL/MySQL
- **DigitalOcean Managed DB** - PostgreSQL/MySQL/Redis
- **MongoDB Atlas** - NoSQL option

---

## Next Steps

1. **Choose a hosting provider** (Render.app recommended for simplicity)
2. **Set up environment variables** in your host
3. **Configure CORS** if needed (clients from different origin)
4. **Enable SSL/HTTPS**
5. **Set up monitoring and backups**
6. **Test with your SentinelVault clients**

---

## Testing the Backend

```bash
# Check if server is running
curl http://localhost:8080/health

# View API docs
open http://localhost:8080/docs

# Enroll a device (example)
curl -X POST http://localhost:8080/enroll \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "test-device-001",
    "device_name": "Test Mac",
    "device_type": "macOS",
    "device_secret": "test-secret"
  }'
```

---

## Troubleshooting

### Port already in use
```bash
# Kill process on port 8080
lsof -ti:8080 | xargs kill -9

# Or use different port
python server.py --port 8081
```

### Database locked
```bash
# Remove lock file
rm sentinel_fleet.db-wal sentinel_fleet.db-shm

# Or restart the server
systemctl restart sentinelvault
```

### Module not found
```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

---

## Production Checklist

- [ ] Generate strong admin token
- [ ] Enable HTTPS/SSL
- [ ] Set `DEBUG=False`
- [ ] Use managed database (PostgreSQL/MySQL)
- [ ] Enable CORS properly (only allow your domains)
- [ ] Set up monitoring and alerting
- [ ] Configure automated backups
- [ ] Set up CI/CD pipeline
- [ ] Document API endpoints
- [ ] Test disaster recovery
