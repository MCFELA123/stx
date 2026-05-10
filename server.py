#!/usr/bin/env python3
"""
SentinelVault Fleet Management Backend

This FastAPI server coordinates between the admin Mac and client Macs.
It handles device enrollment, encrypted snapshot uploads, and fleet management.
"""

from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import sqlite3
import hmac
import hashlib
import json
import time
import base64
import os
from datetime import datetime, timezone
from contextlib import contextmanager
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="SentinelVault Fleet Backend",
    description="Fleet management server for SentinelVault security monitoring",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment configuration
DATABASE = os.getenv("DATABASE", "sentinel_fleet.db")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
PORT = int(os.getenv("PORT", 8000))

def init_database():
    """Initialize SQLite database with required tables"""
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        
        # Device registry table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            device_type TEXT NOT NULL,
            enrollment_date TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            admin_public_key TEXT,
            device_secret TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
        """)
        
        # Snapshots table for encrypted data uploads
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            upload_date TEXT NOT NULL,
            data_type TEXT NOT NULL,
            encrypted_payload TEXT NOT NULL,
            signature TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
        """)
        
        # Admin sessions table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_sessions (
            session_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            admin_key_fingerprint TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
        """)

        # Commands table — admin posts a command, client consumes it
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            command TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed INTEGER DEFAULT 0,
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
        """)

        conn.commit()

@contextmanager
def get_db():
    """Database context manager"""
    conn = sqlite3.connect(DATABASE)
    try:
        yield conn
    finally:
        conn.close()

# Pydantic models
class DeviceEnrollment(BaseModel):
    device_name: str = Field(..., description="Human readable device name")
    device_type: str = Field(..., description="Type: admin or client")
    admin_public_key: Optional[str] = Field(None, description="Admin's public key for E2E encryption")

class SnapshotUpload(BaseModel):
    device_id: str
    data_type: str = Field(..., description="Type of scanned data")
    encrypted_payload: str = Field(..., description="Base64 encrypted data")
    
class DeviceInfo(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    enrollment_date: str
    last_seen: str
    status: str

class SnapshotInfo(BaseModel):
    id: int
    device_id: str
    upload_date: str
    data_type: str

# Utility functions
def generate_device_secret() -> str:
    """Generate a cryptographically secure device secret"""
    import secrets
    return secrets.token_urlsafe(32)

def verify_hmac_signature(message: str, signature: str, secret: str) -> bool:
    """Verify HMAC signature for authenticated requests"""
    expected = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

def get_current_timestamp() -> str:
    """Get current UTC timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()

# Dependency to verify device authentication
async def verify_device_auth(
    x_device_id: str = Header(...),
    x_signature: str = Header(...),
    x_timestamp: str = Header(...)
):
    """Verify device authentication via HMAC signature"""
    
    # Check timestamp (prevent replay attacks)
    try:
        timestamp = datetime.fromisoformat(x_timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        if (now - timestamp).total_seconds() > 300:  # 5 minute window
            raise HTTPException(status_code=401, detail="Request timestamp too old")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")
    
    # Look up device secret
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT device_secret FROM devices WHERE device_id = ?", (x_device_id,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Device not found")
        
        device_secret = result[0]
    
    # Verify HMAC signature
    message = f"{x_device_id}:{x_timestamp}"
    if not verify_hmac_signature(message, x_signature, device_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Update last seen timestamp
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (get_current_timestamp(), x_device_id)
        )
        conn.commit()
    
    return x_device_id

# API Routes

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "SentinelVault Fleet Backend",
        "status": "running",
        "timestamp": get_current_timestamp()
    }

@app.post("/enroll", response_model=Dict[str, str])
async def enroll_device(enrollment: DeviceEnrollment):
    """
    Enroll a new device in the fleet.
    Returns device_id and device_secret for authentication.
    """
    import uuid
    
    device_id = str(uuid.uuid4())
    device_secret = generate_device_secret()
    timestamp = get_current_timestamp()
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO devices (device_id, device_name, device_type, enrollment_date, last_seen, admin_public_key, device_secret)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            device_id,
            enrollment.device_name,
            enrollment.device_type,
            timestamp,
            timestamp,
            enrollment.admin_public_key,
            device_secret
        ))
        conn.commit()
    
    return {
        "device_id": device_id,
        "device_secret": device_secret,
        "enrollment_date": timestamp
    }

@app.post("/snapshot")
async def upload_snapshot(
    snapshot: SnapshotUpload,
    device_id: str = Depends(verify_device_auth)
):
    """
    Upload an encrypted snapshot from a client device.
    Requires valid device authentication.
    """
    
    # Verify device_id matches authenticated device
    if snapshot.device_id != device_id:
        raise HTTPException(status_code=403, detail="Device ID mismatch")
    
    # Generate signature for the uploaded data
    message = f"{device_id}:{snapshot.data_type}:{snapshot.encrypted_payload}"
    
    # Get device secret for signature
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT device_secret FROM devices WHERE device_id = ?", (device_id,))
        device_secret = cursor.fetchone()[0]
    
    signature = hmac.new(
        device_secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Store snapshot — replace any existing one for this device+data_type
    # so only the latest scan is kept (prevents unbounded duplication).
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM snapshots WHERE device_id = ? AND data_type = ?",
            (device_id, snapshot.data_type)
        )
        cursor.execute("""
        INSERT INTO snapshots (device_id, upload_date, data_type, encrypted_payload, signature)
        VALUES (?, ?, ?, ?, ?)
        """, (
            device_id,
            get_current_timestamp(),
            snapshot.data_type,
            snapshot.encrypted_payload,
            signature
        ))
        conn.commit()
    
    return {"status": "success", "message": "Snapshot uploaded successfully"}

@app.get("/admin/devices", response_model=List[DeviceInfo])
async def list_devices():
    """
    List all enrolled devices (admin endpoint).
    TODO: Add admin authentication
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT device_id, device_name, device_type, enrollment_date, last_seen, status FROM devices")
        devices = []
        for row in cursor.fetchall():
            devices.append(DeviceInfo(
                device_id=row[0],
                device_name=row[1],
                device_type=row[2],
                enrollment_date=row[3],
                last_seen=row[4],
                status=row[5]
            ))
    
    return devices

@app.get("/admin/snapshots/{device_id}", response_model=List[SnapshotInfo])
async def get_device_snapshots(device_id: str):
    """
    Get all snapshots for a specific device (admin endpoint).
    TODO: Add admin authentication
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, device_id, upload_date, data_type FROM snapshots WHERE device_id = ? ORDER BY upload_date DESC",
            (device_id,)
        )
        snapshots = []
        for row in cursor.fetchall():
            snapshots.append(SnapshotInfo(
                id=row[0],
                device_id=row[1],
                upload_date=row[2],
                data_type=row[3]
            ))
    
    return snapshots

@app.get("/admin/snapshots/{device_id}/{snapshot_id}/decrypt")
async def get_encrypted_snapshot(device_id: str, snapshot_id: int):
    """
    Get encrypted snapshot data for admin decryption.
    Returns the encrypted payload and signature for verification.
    TODO: Add admin authentication
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT encrypted_payload, signature, data_type, upload_date FROM snapshots WHERE id = ? AND device_id = ?",
            (snapshot_id, device_id)
        )
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        
        return {
            "device_id": device_id,
            "snapshot_id": snapshot_id,
            "encrypted_payload": result[0],
            "signature": result[1],
            "data_type": result[2],
            "upload_date": result[3]
        }

@app.delete("/admin/devices/{device_id}")
async def revoke_device(device_id: str):
    """
    Revoke a device from the fleet (admin endpoint).
    TODO: Add admin authentication
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE devices SET status = 'revoked' WHERE device_id = ?", (device_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
        conn.commit()
    
    return {"status": "success", "message": f"Device {device_id} revoked"}

@app.post("/admin/devices/{device_id}/rescan")
async def request_rescan(device_id: str):
    """
    Admin posts a rescan command for a specific device.
    The client will pick this up on its next poll and immediately re-run a full scan.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        # Remove any unconsumed rescan commands for this device first (dedup).
        cursor.execute(
            "DELETE FROM commands WHERE device_id = ? AND command = 'rescan' AND consumed = 0",
            (device_id,)
        )
        cursor.execute(
            "INSERT INTO commands (device_id, command, created_at) VALUES (?, 'rescan', ?)",
            (device_id, get_current_timestamp())
        )
        conn.commit()
    return {"status": "success", "message": "Rescan command queued"}

@app.get("/command/pending")
async def get_pending_command(device_id: str = Depends(verify_device_auth)):
    """
    Client polls this endpoint to check for a pending command.
    Returns the next unconsumed command and marks it consumed.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, command FROM commands WHERE device_id = ? AND consumed = 0 ORDER BY id LIMIT 1",
            (device_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"command": None}
        cmd_id, command = row
        cursor.execute("UPDATE commands SET consumed = 1 WHERE id = ?", (cmd_id,))
        conn.commit()
    return {"command": command}

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_database()
    print("SentinelVault Fleet Backend started successfully")
    print("Database initialized")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
