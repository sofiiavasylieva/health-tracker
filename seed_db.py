"""
seed_db.py
==========
Читає personalised_dataset_clean.csv, вибирає 8 різноманітних рядків
і на їх основі генерує 15-денну історію для кожного юзера в БД.

Таким чином дані юзерів у БД і дані для ML — з одного джерела.

Запуск: python seed_db.py
"""

import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

CSV  = 'personalised_dataset_clean.csv'
DB   = 'health_tracker.db'

# ── Читаємо CSV ────────────────────────────────────────────
df = pd.read_csv(CSV)

# Вибираємо 8 різноманітних рядків вручну за індексом
# (перевірено — різні профілі: вік, стать, ризик, активність)
SELECTED_INDICES = {
    'andrii':   df[(df['Gender']==0) & (df['Age'].between(25,30)) & (df['Health_Risk']=='Low')  & (df['Activity_Score']==3)].index[0],
    'olena':    df[(df['Gender']==1) & (df['Age'].between(40,47)) & (df['Health_Risk']=='Moderate') & (df['BMI']>28)].index[0],
    'vasyl':    df[(df['Gender']==0) & (df['Age'].between(58,65)) & (df['Sleep_Hours']<6)].index[0],
    'solomiia': df[(df['Gender']==1) & (df['Age'].between(20,25)) & (df['BMI']<19)].index[0],
    'mykola':   df[(df['Gender']==0) & (df['Age'].between(45,52)) & (df['BMI']>33) & (df['Activity_Score']==1)].index[0],
    'iryna':    df[(df['Gender']==1) & (df['Age'].between(32,38)) & (df['Activity_Score']==4) & (df['Sleep_Hours']<6.5)].index[0],
    'taras':    df[(df['Gender']==0) & (df['Age'].between(35,42)) & (df['Health_Risk']=='Moderate') & (df['Activity_Score']==3)].index[0],
    'halyna':   df[(df['Gender']==1) & (df['Age']>63) & (df['Health_Risk']=='High')].index[0],
}

# Мета-дані юзерів (ім'я, пошта, ціль — цього немає в CSV)
USER_META = {
    'andrii':   ('Андрій Коваль',   'andrii@test.com',   'maintain', 181.0, 'running'),
    'olena':    ('Олена Шевченко',  'olena@test.com',    'lose',     165.0, 'walking'),
    'vasyl':    ('Василь Мороз',    'vasyl@test.com',    'maintain', 174.0, 'walking'),
    'solomiia': ('Соломія Бондар',  'solomiia@test.com', 'gain',     167.0, 'gym'),
    'mykola':   ('Микола Гаврилюк','mykola@test.com',   'lose',     178.0, 'walking'),
    'iryna':    ('Ірина Лисенко',   'iryna@test.com',    'maintain', 169.0, 'running'),
    'taras':    ('Тарас Дяченко',   'taras@test.com',    'maintain', 180.0, 'gym'),
    'halyna':   ('Галина Романець', 'halyna@test.com',   'lose',     160.0, 'walking'),
}

GOAL_TREND = {'lose': -0.08, 'maintain': -0.02, 'gain': 0.08}

ACTIVITY_LEVEL_MAP = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725}

# ── БД ─────────────────────────────────────────────────────
conn = sqlite3.connect(DB)
cur  = conn.cursor()

cur.executescript('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    age INTEGER, gender TEXT, height REAL,
    initial_weight REAL, goal TEXT,
    activity_level REAL DEFAULT 1.2,
    onboarding_complete INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS basic_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, date TEXT, weight REAL, steps INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS health_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, date TEXT, pulse INTEGER,
    blood_pressure TEXT, duration_sleep REAL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS activity_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, date TEXT, activity_type TEXT,
    duration INTEGER, water_intake REAL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS calculator_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, date TEXT,
    calculator_type TEXT NOT NULL, result REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, date TEXT, approach TEXT NOT NULL,
    category TEXT, recommendation TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
''')
conn.commit()

# Додаємо колонки яких може не вистачати у старій БД
def add_col(table, col, typ):
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        print(f"  + додано: {table}.{col}")

add_col('basic_data', 'steps', 'INTEGER')
add_col('calculator_results', 'date', 'TEXT')
conn.commit()

# Очищаємо всі рядки
for t in ['recommendations','calculator_results','activity_data','health_data','basic_data','users']:
    cur.execute(f"DELETE FROM {t}")
cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('users','basic_data','health_data','activity_data','calculator_results','recommendations')")
conn.commit()
print("🗑️  Таблиці очищено")

# ── Заповнення ─────────────────────────────────────────────
today = datetime.now()
print("📥 Заповнення з CSV...")
print("=" * 60)

def n(sd): return float(np.random.normal(0, sd))

for key, idx in SELECTED_INDICES.items():
    row  = df.loc[idx]
    name, email, goal, height, activity_type = USER_META[key]

    # Базові показники — прямо з CSV
    age        = int(row['Age'])
    gender     = 'male' if row['Gender'] == 0 else 'female'
    bmi        = float(row['BMI'])
    weight     = round(bmi * (height / 100) ** 2, 1)
    pulse      = int(row['Resting_Heart_Rate'])
    sleep      = float(row['Sleep_Hours'])
    systolic   = int(row['Systolic_BP'])
    diastolic  = int(row['Diastolic_BP'])
    act_score  = int(row['Activity_Score'])
    act_level  = ACTIVITY_LEVEL_MAP.get(act_score, 1.375)
    trend      = GOAL_TREND[goal]
    steps_base = act_score * 2500

    cur.execute(
        '''INSERT INTO users
           (username, email, password, age, gender, height,
            initial_weight, goal, activity_level, onboarding_complete)
           VALUES (?,?,?,?,?,?,?,?,?,1)''',
        (name, email, 'password123', age, gender, height,
         weight, goal, act_level)
    )
    conn.commit()
    uid = cur.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]

    for day in range(15):
        date = (today - timedelta(days=14 - day)).strftime('%Y-%m-%d')

        # Вага: базова з CSV + тренд + невеликий шум
        w = round(weight + trend * day + n(0.2), 1)
        s = max(1000, int(steps_base + n(500)))
        cur.execute(
            "INSERT INTO basic_data (user_id, date, weight, steps) VALUES (?,?,?,?)",
            (uid, date, w, s)
        )

        # Здоров'я: базові значення з CSV + шум
        p  = max(45, int(pulse + n(3)))
        sl = round(float(np.clip(sleep + n(0.4), 3.0, 11.0)), 1)
        sv = max(70, int(systolic  + n(4)))
        dv = max(50, int(diastolic + n(3)))
        cur.execute(
            "INSERT INTO health_data (user_id, date, pulse, blood_pressure, duration_sleep) VALUES (?,?,?,?,?)",
            (uid, date, p, f"{sv}/{dv}", sl)
        )

        # Активність
        dur   = max(10, int(act_level * 25 + n(8)))
        water = round(float(np.clip(1.5 + act_score * 0.3 + n(0.2), 0.5, 4.5)), 1)
        cur.execute(
            "INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake) VALUES (?,?,?,?,?)",
            (uid, date, activity_type, dur, water)
        )

        # ІМТ тричі
        if day in (0, 7, 14):
            cur_bmi = round(w / (height / 100) ** 2, 2)
            cur.execute(
                "INSERT INTO calculator_results (user_id, date, calculator_type, result) VALUES (?,?,?,?)",
                (uid, date, 'bmi', cur_bmi)
            )

    conn.commit()
    risk = row['Health_Risk']
    print(f"  ✅ {name:<22} ID={uid} | ІМТ {bmi} | Сон {sleep}г | Ризик: {risk}")
    print(f"      Тиск {systolic}/{diastolic} | Пульс {pulse} | Активність {act_score}/4")


# Генерація початкових рекомендацій для тестових юзерів
today_str = datetime.now().strftime('%Y-%m-%d')
print("\n💡 Генерація рекомендацій для тестових юзерів...")

for key, meta in USER_META.items():
    name, email, goal, height, activity_type = meta
    uid = cur.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]

    last_w     = cur.execute("SELECT weight FROM basic_data WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    last_sleep = cur.execute("SELECT duration_sleep FROM health_data WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    last_bp    = cur.execute("SELECT blood_pressure FROM health_data WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    last_water = cur.execute("SELECT water_intake FROM activity_data WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)).fetchone()

    recs = []

    if last_w and height:
        bmi = round(last_w[0] / (height / 100) ** 2, 2)
        if bmi < 18.5:
            recs.append(('weight', f'ІМТ {bmi} — недостатня вага. Рекомендується збільшити калорійність раціону та додати силові тренування.'))
        elif bmi < 25:
            recs.append(('weight', f'ІМТ {bmi} — норма. Продовжуйте підтримувати поточний режим харчування та активності.'))
        elif bmi < 30:
            recs.append(('weight', f'ІМТ {bmi} — надмірна вага. Рекомендується помірний дефіцит калорій та 150+ хв кардіо на тиждень.'))
        else:
            recs.append(('weight', f'ІМТ {bmi} — ожиріння. Рекомендується консультація з лікарем та поступове зниження ваги.'))

    if last_sleep:
        s = last_sleep[0]
        if s < 6:
            recs.append(('sleep', f'Сон {round(s,1)} год — критично мало. Намагайтесь лягати до 23:00.'))
        elif s < 7:
            recs.append(('sleep', f'Сон {round(s,1)} год — недостатньо. Рекомендується 7–9 годин.'))
        else:
            recs.append(('sleep', f'Сон {round(s,1)} год — норма. Підтримуйте стабільний режим.'))

    if last_bp:
        try:
            sys_v = int(last_bp[0].split('/')[0])
            if sys_v >= 140:
                recs.append(('pressure', f'Тиск {last_bp[0]} — підвищений. Рекомендується консультація лікаря.'))
            elif sys_v >= 130:
                recs.append(('pressure', f'Тиск {last_bp[0]} — помірно підвищений. Обмежте сіль.'))
        except Exception:
            pass

    if last_water:
        w = last_water[0]
        if w < 1.5:
            recs.append(('hydration', f'Вода {w} л — недостатньо. Норма: 2–2.5 л на день.'))
        else:
            recs.append(('hydration', f'Вода {w} л — добре!'))

    for category, text in recs:
        cur.execute(
            "INSERT INTO recommendations (user_id, date, approach, category, recommendation) VALUES (?,?,?,?,?)",
            (uid, today_str, 'rule_based', category, text)
        )

conn.commit()
conn.close()
print(f"  ✅ Рекомендації згенеровано")
print()
print("✅ Готово: 8 юзерів × 15 записів (дані з CSV)")
print("🔑 Пароль для всіх: password123")