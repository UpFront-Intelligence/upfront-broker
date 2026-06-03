"""
ONE-TIME startup script — clears the users table on next deploy.

⚠️  REMOVE THIS FILE and revert render.yaml startCommand after the
    first successful deploy. If left in place it will clear users on
    every restart.
"""
import os
import psycopg2

url = os.getenv("DATABASE_URL", "")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

if not url:
    print("[clear_users] No DATABASE_URL — skipping")
else:
    conn = psycopg2.connect(url)
    cur  = conn.cursor()
    cur.execute("DELETE FROM users")
    conn.commit()
    print(f"[clear_users] Deleted {cur.rowcount} user(s)")
    cur.close()
    conn.close()
