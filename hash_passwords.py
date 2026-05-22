import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DB = 'health_tracker.db'

conn = sqlite3.connect(DB)
cur = conn.cursor()

users = cur.execute("SELECT id, email, password FROM users").fetchall()

updated = 0
skipped = 0

for uid, email, password in users:
    # Перевіряємо чи пароль вже хешований
    if password and password.startswith('pbkdf2:') or (password and password.startswith('scrypt:')):
        print(f"  [skip] {email} — вже хешований")
        skipped += 1
        continue

    # Хешуємо plain text пароль
    hashed = generate_password_hash(password)
    cur.execute("UPDATE users SET password=? WHERE id=?", (hashed, uid))
    print(f"  [hash] {email} — хешовано")
    updated += 1

conn.commit()
conn.close()

print(f"\nГотово: {updated} хешовано, {skipped} вже були хешовані.")