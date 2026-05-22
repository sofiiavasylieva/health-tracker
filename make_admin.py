"""
Встановлює адміна для існуючого юзера.
Запуск: python3 make_admin.py andrii@test.com
"""
import sqlite3, sys

DB = 'health_tracker.db'
email = sys.argv[1] if len(sys.argv) > 1 else 'andrii@test.com'

conn = sqlite3.connect(DB)
cur  = conn.cursor()

try:
    cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
except: pass

cur.execute("UPDATE users SET is_admin=1 WHERE email=?", (email,))
if cur.rowcount == 0:
    print(f"Юзер {email} не знайдений")
else:
    conn.commit()
    print(f"{email} тепер адмін")
conn.close()