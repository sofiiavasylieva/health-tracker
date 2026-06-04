import matplotlib
matplotlib.use('Agg')
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import io
import base64
import matplotlib.pyplot as plt
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import os
from datetime import datetime
from recommenders.ml_recommender import MLRecommender
from recommenders.ai_recommender import AIRecommender
from dotenv import load_dotenv
load_dotenv()

class Calculator(ABC):
    @abstractmethod
    def calculate(self, data: Dict[str, Any]) -> float:
        pass

class BMICalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        if not data.get('weight') or not data.get('height'):
            raise ValueError("Вага та зріст обов'язкові.")
        try:
            weight = float(data.get('weight'))
            height = float(data.get('height'))
        except (ValueError, TypeError):
            raise ValueError("Вага та зріст повинні бути числами.")
        if weight <= 0 or height <= 0:
            raise ValueError("Вага та зріст повинні бути додатними.")
        return round(weight / ((height / 100) ** 2), 2)

class BodyFatCalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        required_fields = ['gender', 'age', 'chest', 'abdomen', 'thigh']
        if not all(data.get(field) for field in required_fields):
            raise ValueError("Всі поля вимірів обов'язкові.")
        gender = data.get('gender').lower()
        if gender not in ['male', 'female']:
            raise ValueError("Стать має бути 'male' або 'female'.")
        try:
            age = int(data.get('age'))
            chest = float(data.get('chest'))
            abdomen = float(data.get('abdomen'))
            thigh = float(data.get('thigh'))
        except (ValueError, TypeError):
            raise ValueError("Дані повинні бути числовими.")
        if chest <= 0 or abdomen <= 0 or thigh <= 0 or age <= 0:
            raise ValueError("Значення мають бути додатними.")
        fat_result = 1.097 - (0.00046971 * (chest + abdomen + thigh)) + \
                     (0.00000056 * (chest + abdomen + thigh) ** 2) - \
                     (0.00012828 * age) - (5.4 if gender == 'female' else 0)
        return max(0, round(fat_result, 2))

class CalorieCalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        required_fields = ['gender', 'weight', 'height', 'age', 'activity_level']
        if not all(data.get(field) for field in required_fields):
            raise ValueError("Всі поля обов'язкові.")
        gender = data.get('gender').lower()
        if gender not in ['male', 'female']:
            raise ValueError("Стать має бути 'male' або 'female'.")
        try:
            weight = float(data.get('weight'))
            height = float(data.get('height'))
            age = int(data.get('age'))
            activity_level = float(data.get('activity_level'))
        except (ValueError, TypeError):
            raise ValueError("Дані повинні бути числовими.")
        if weight <= 0 or height <= 0 or age <= 0:
            raise ValueError("Значення мають бути додатними.")
        bmr = (88.36 + (13.4 * weight) + (4.8 * height) - (5.7 * age) if gender == 'male'
               else 447.6 + (9.2 * weight) + (3.1 * height) - (4.3 * age))
        return round(bmr * activity_level, 2)


class DatabaseRepository:
    def __init__(self, db_name: str):
        self.db_name = db_name

    def execute_query(self, query: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False) -> Optional[Any]:
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute(query, params)
            result = cursor.fetchone() if fetchone else cursor.fetchall() if fetchall else None
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            result = None
        finally:
            conn.close()
        return result

    def initialize_db(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        tables = [
            '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                age INTEGER,
                gender TEXT,
                height REAL,
                initial_weight REAL,
                goal TEXT,
                activity_level REAL DEFAULT 1.2,
                onboarding_complete INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0
            )''',
            '''CREATE TABLE IF NOT EXISTS basic_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                weight REAL,
                steps INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS health_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                pulse INTEGER,
                blood_pressure TEXT,
                duration_sleep REAL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS activity_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                activity_type TEXT,
                duration INTEGER,
                water_intake REAL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS calculator_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                calculator_type TEXT NOT NULL,
                result REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                approach TEXT NOT NULL,
                category TEXT,
                recommendation TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )'''
        ]
        for table_query in tables:
            cursor.execute(table_query)
        conn.commit()
        conn.close()


class UserRepository:
    def __init__(self, db_repo: DatabaseRepository):
        self.db_repo = db_repo

    def get_user_by_email(self, email: str) -> Optional[tuple]:
        return self.db_repo.execute_query(
            "SELECT * FROM users WHERE email = ?", (email,), fetchone=True
        )

    def get_user_by_id(self, user_id: int) -> Optional[tuple]:
        return self.db_repo.execute_query(
            "SELECT * FROM users WHERE id = ?", (user_id,), fetchone=True
        )

    def register_user(self, username: str, email: str, password: str) -> bool:
        try:
            self.db_repo.execute_query(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            return True
        except Exception:
            return False

    def complete_onboarding(self, user_id: int, data: dict) -> bool:
        try:
            self.db_repo.execute_query(
                '''UPDATE users SET age=?, gender=?, height=?, initial_weight=?,
                   goal=?, activity_level=?, onboarding_complete=1 WHERE id=?''',
                (data['age'], data['gender'], data['height'],
                 data['initial_weight'], data['goal'],
                 data['activity_level'], user_id)
            )
            return True
        except Exception:
            return False


class HealthTrackerApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.secret_key = os.environ.get('SECRET_KEY', 'health-tracker-secret-key-2026')
        self.db_repo = DatabaseRepository('health_tracker.db')
        self.user_repo = UserRepository(self.db_repo)
        self.calculators = {
            'bmi': BMICalculator(),
            'body_fat': BodyFatCalculator(),
            'calories': CalorieCalculator(),
        }
        self.db_repo.initialize_db()
        # Міграція: додаємо is_admin якщо колонки ще немає
        try:
            self.db_repo.execute_query("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except Exception:
            pass  # Колонка вже існує
        csv_path = os.path.join(os.path.dirname(__file__), "personalised_dataset_clean.csv")
        self.ml = MLRecommender(csv_path)
        self.ai = AIRecommender()
        self.setup_routes()
        self.setup_chat_route()

    def get_current_user(self):
        if 'user_id' not in session:
            return None
        return self.user_repo.get_user_by_id(session['user_id'])

    def setup_routes(self):

        @self.app.route('/')
        @self.app.route('/dashboard')
        def dashboard():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = self.get_current_user()
            if not user or not user[10]:  # onboarding_complete
                return redirect(url_for('onboarding'))

            chart_data = {}
            metrics = [
                {'id': 'weight', 'label': 'Вага (кг)', 'color': '#6366f1'},
                {'id': 'pulse', 'label': 'Пульс (уд/хв)', 'color': '#ef4444'},
                {'id': 'sleep', 'label': 'Сон (год)', 'color': '#8b5cf6'},
                {'id': 'water_intake', 'label': 'Вода (л)', 'color': '#06b6d4'},
                {'id': 'steps', 'label': 'Кроки', 'color': '#10b981'},
            ]
            for metric in metrics:
                chart_data[metric['id']] = self.plot_metric_chart(
                    metric['id'], metric['label'], metric['color']
                )

            # Latest rule-based recommendation
            rule_recs = self.db_repo.execute_query(
                "SELECT category, recommendation FROM recommendations WHERE user_id=? AND approach='rule_based' ORDER BY date DESC",
                (session['user_id'],), fetchall=True
            )
            ml_recs = self.db_repo.execute_query(
                "SELECT category, recommendation FROM recommendations WHERE user_id=? AND approach='ml' ORDER BY date DESC",
                (session['user_id'],), fetchall=True
            )
            ai_recs = self.db_repo.execute_query(
                "SELECT category, recommendation FROM recommendations WHERE user_id=? AND approach='ai' ORDER BY date DESC",
                (session['user_id'],), fetchall=True
            )

            uid = session['user_id']
            # Stat cards: latest values + trend vs previous
            def get_stat(table, col):
                rows = self.db_repo.execute_query(
                    f"SELECT {col} FROM {table} WHERE user_id=? AND {col} IS NOT NULL ORDER BY date DESC LIMIT 2",
                    (uid,), fetchall=True
                )
                if not rows: return None, None
                cur = float(rows[0][0])
                prev = float(rows[1][0]) if len(rows) > 1 else None
                if prev and prev != 0:
                    diff = round(((cur - prev) / prev) * 100, 1)
                else:
                    diff = None
                return cur, diff

            w_val, w_diff   = get_stat('basic_data', 'weight')
            s_val, s_diff   = get_stat('basic_data', 'steps')
            p_val, p_diff   = get_stat('health_data', 'pulse')
            bp_row = self.db_repo.execute_query(
                "SELECT blood_pressure FROM health_data WHERE user_id=? AND blood_pressure IS NOT NULL ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            bp_val = bp_row[0] if bp_row else None
            sl_val, sl_diff = get_stat('health_data', 'duration_sleep')

            stat_cards = [
                {'label': 'Вага', 'value': f'{w_val} кг' if w_val else '—', 'diff': w_diff, 'icon': 'fa-weight', 'color': 'blue'},
                {'label': 'Кроки', 'value': f'{int(s_val):,}'.replace(',', ' ') if s_val else '—', 'diff': s_diff, 'icon': 'fa-shoe-prints', 'color': 'green'},
                {'label': 'Пульс', 'value': f'{int(p_val)} уд/хв' if p_val else '—', 'diff': p_diff, 'icon': 'fa-heartbeat', 'color': 'red'},
                {'label': 'Тиск', 'value': bp_val or '—', 'diff': None, 'icon': 'fa-stethoscope', 'color': 'violet'},
                {'label': 'Сон', 'value': f'{sl_val} год' if sl_val else '—', 'diff': sl_diff, 'icon': 'fa-moon', 'color': 'teal'},
            ]

            return render_template('dashboard.html',
                                   username=user[1],
                                   user=user,
                                   chart_data=chart_data,
                                   rule_recs=rule_recs or [],
                                   ml_recs=ml_recs or [],
                                   ai_recs=ai_recs or [],
                                   stat_cards=stat_cards,
                                   page='dashboard')

        @self.app.route('/onboarding', methods=['GET', 'POST'])
        def onboarding():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if request.method == 'POST':
                step = request.form.get('step')
                if step == '1':
                    session['ob_gender'] = request.form.get('gender')
                    session['ob_age'] = request.form.get('age')
                    return render_template('onboarding.html', step=2)
                elif step == '2':
                    session['ob_height'] = request.form.get('height')
                    session['ob_weight'] = request.form.get('weight')
                    return render_template('onboarding.html', step=3)
                elif step == '3':
                    data = {
                        'age': session.get('ob_age'),
                        'gender': session.get('ob_gender'),
                        'height': session.get('ob_height'),
                        'initial_weight': session.get('ob_weight'),
                        'goal': request.form.get('goal'),
                        'activity_level': request.form.get('activity_level'),
                    }
                    self.user_repo.complete_onboarding(session['user_id'], data)
                    # Save initial weight to basic_data
                    if data['initial_weight']:
                        self.db_repo.execute_query(
                            "INSERT INTO basic_data (user_id, date, weight) VALUES (?, ?, ?)",
                            (session['user_id'], datetime.now().strftime('%Y-%m-%d'), float(data['initial_weight']))
                        )
                    return redirect(url_for('dashboard'))
            return render_template('onboarding.html', step=1)

        @self.app.route('/tracker', methods=['GET', 'POST'])
        def tracker():
            if 'user_id' not in session:
                return redirect(url_for('login'))

            bmi_result, fat_result, calorie_result = None, None, None

            if request.method == 'POST':
                form_type = request.form.get('form_type')

                if form_type == 'all_data':
                    # Unified tracker form — saves all three data types at once
                    self.save_all_data(request)
                    self.generate_rule_based_recommendation('daily_data')
                    self.generate_rule_based_recommendation('health_data')
                    self.generate_rule_based_recommendation('activity_data')
                    self.generate_ml_recommendation()
                    self.generate_ai_recommendation('daily_data')
                    self.generate_ai_recommendation('health_data')
                    self.generate_ai_recommendation('activity_data')
                    flash('Дані збережено.', 'success')
                    return redirect(url_for('dashboard'))
                elif form_type == 'combined':
                    self.save_combined_data(request)
                    self.generate_rule_based_recommendation('daily_data')
                    self.generate_rule_based_recommendation('health_data')
                    self.generate_rule_based_recommendation('activity_data')
                    self.generate_ml_recommendation()
                    self.generate_ai_recommendation('daily_data')
                    self.generate_ai_recommendation('health_data')
                    self.generate_ai_recommendation('activity_data')
                    return redirect(url_for('dashboard'))
                elif form_type == 'daily_data':
                    self.save_daily_data(request)
                    self.generate_rule_based_recommendation('daily_data')
                    self.generate_ml_recommendation()
                    self.generate_ai_recommendation('daily_data')
                    return redirect(url_for('dashboard'))
                elif form_type == 'health_data':
                    self.save_health_data(request)
                    self.generate_rule_based_recommendation('health_data')
                    self.generate_ml_recommendation()
                    self.generate_ai_recommendation('health_data')
                    return redirect(url_for('dashboard'))
                elif form_type == 'activity_data':
                    self.save_activity_data(request)
                    self.generate_rule_based_recommendation('activity_data')
                    self.generate_ml_recommendation()
                    self.generate_ai_recommendation('activity_data')
                    return redirect(url_for('dashboard'))
                elif form_type == 'calculator':
                    calc_type = request.form.get('calculator_type')
                    if calc_type in self.calculators:
                        try:
                            calculator = self.calculators[calc_type]
                            result = calculator.calculate(request.form)
                            self.db_repo.execute_query(
                                "INSERT INTO calculator_results (user_id, date, calculator_type, result) VALUES (?, ?, ?, ?)",
                                (session['user_id'], datetime.now().strftime('%Y-%m-%d'), calc_type, result)
                            )
                            if calc_type == 'bmi':
                                bmi_result = result
                            elif calc_type == 'body_fat':
                                fat_result = result
                            elif calc_type == 'calories':
                                calorie_result = result
                            flash(f'Результат: {result}', 'success')
                        except ValueError as e:
                            flash(str(e), 'error')

            user = self.get_current_user()
            return render_template('tracker.html',
                                   page='tracker',
                                   user=user,
                                   bmi_result=bmi_result,
                                   fat_result=fat_result,
                                   calorie_result=calorie_result)

        @self.app.route('/ai-agent', methods=['GET', 'POST'])
        def ai_agent():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = self.get_current_user()
            return render_template('ai_agent.html', page='ai_agent', user=user)

        @self.app.route('/research')
        def research():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            # Перевірка адміна
            try:
                user_row = self.db_repo.execute_query(
                    "SELECT is_admin FROM users WHERE id=?",
                    (session['user_id'],), fetchone=True
                )
                if user_row and user_row[0] == 0:
                    flash('Доступ заборонено. Ця сторінка тільки для адміністраторів.', 'error')
                    return redirect(url_for('dashboard'))
            except Exception:
                pass  # Якщо колонки ще немає — дозволяємо доступ

            import re

            APPROACHES  = ['rule_based', 'ml', 'ai']
            CATEGORIES  = ['weight', 'sleep', 'pulse', 'pressure', 'hydration', 'insights']
            TEST_EMAILS = [
                'andrii@test.com', 'olena@test.com', 'vasyl@test.com', 'solomiia@test.com',
                'mykola@test.com', 'iryna@test.com', 'taras@test.com', 'halyna@test.com',
            ]

            def classify(text):
                if not text: return None
                t = text.lower()
                for kw in ['критично','тахікардія','брадикардія','консультація лікаря','ожиріння','зверніться']:
                    if kw in t: return 'critical'
                for kw in ['норма','нормі','відповідає','стабільн','позитивн','добре']:
                    if kw in t: return 'norm'
                return 'deviation'

            def has_numbers(text):
                return bool(re.search(r'\d+[.,]?\d*', text or ''))

            # ── Таблиця 1: рекомендації по юзерах ──
            # Беремо всіх юзерів у яких є хоча б одна рекомендація
            all_users = self.db_repo.execute_query(
                "SELECT DISTINCT u.id, u.username, u.email FROM users u "
                "INNER JOIN recommendations r ON r.user_id = u.id "
                "ORDER BY u.username",
                fetchall=True
            ) or []

            users_table = []
            for uid, uname, uemail in all_users:
                rows = []
                for cat in CATEGORIES:
                    row = {'cat': cat}
                    has_any = False
                    for ap in APPROACHES:
                        rec = self.db_repo.execute_query(
                            "SELECT recommendation FROM recommendations WHERE user_id=? AND approach=? AND category=? ORDER BY date DESC LIMIT 1",
                            (uid, ap, cat), fetchone=True
                        )
                        row[ap] = rec[0] if rec else None
                        if rec: has_any = True
                    if has_any:
                        row['cls'] = classify(row.get('ml') or row.get('rule_based') or '')
                        rows.append(row)
                if rows:
                    users_table.append({'email': uemail, 'name': uname, 'rows': rows})

            # ── Таблиця 2: розподіл типів ──
            dist = {}
            for ap in APPROACHES:
                recs = self.db_repo.execute_query(
                    "SELECT recommendation FROM recommendations WHERE approach=?", (ap,), fetchall=True
                )
                counts = {'norm': 0, 'deviation': 0, 'critical': 0}
                with_num = 0
                for (t,) in (recs or []):
                    c = classify(t)
                    if c: counts[c] += 1
                    if has_numbers(t): with_num += 1
                total = len(recs) if recs else 0
                dist[ap] = {**counts, 'total': total, 'with_num': with_num,
                            'pct_norm': round(counts['norm']*100/total) if total else 0,
                            'pct_dev':  round(counts['deviation']*100/total) if total else 0,
                            'pct_crit': round(counts['critical']*100/total) if total else 0,
                            'pct_num':  round(with_num*100/total) if total else 0}

            # ── Таблиця 3: специфічність по категоріях ──
            specificity = []
            for cat in CATEGORIES:
                row = {'cat': cat}
                for ap in APPROACHES:
                    recs = self.db_repo.execute_query(
                        "SELECT recommendation FROM recommendations WHERE approach=? AND category=?",
                        (ap, cat), fetchall=True
                    )
                    if recs:
                        n = sum(1 for (t,) in recs if has_numbers(t))
                        row[ap] = round(n*100/len(recs))
                    else:
                        row[ap] = None
                specificity.append(row)

            # ── Таблиця 4: покриття ──
            coverage = []
            for email in TEST_EMAILS:
                u = self.db_repo.execute_query(
                    "SELECT id, username FROM users WHERE email=?", (email,), fetchone=True
                )
                if not u: continue
                uid, uname = u
                row = {'name': uname, 'cats': {}}
                for cat in CATEGORIES:
                    row['cats'][cat] = {}
                    for ap in APPROACHES:
                        r = self.db_repo.execute_query(
                            "SELECT 1 FROM recommendations WHERE user_id=? AND approach=? AND category=?",
                            (uid, ap, cat), fetchone=True
                        )
                        row['cats'][cat][ap] = bool(r)
                coverage.append(row)

            # ── Генерація діаграм ──
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import io, base64

            def fig_to_b64(fig):
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight',
                           facecolor='white', dpi=150)
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode('utf-8')
                plt.close(fig)
                return b64

            GREEN='#2ecc71'; AMBER='#f39c12'; RED='#e74c3c'
            BLUE='#2563eb'; TEAL='#00a693'; VIOLET='#7c3aed'
            TXTC='#1a1f36'; TXT2='#64748b'

            plt.rcParams.update({'font.family':'DejaVu Sans'})

            import numpy as np

            # Покращений класифікатор типу рекомендації
            def classify_rec(text):
                if not text: return None
                t = text.lower()
                # Критично — медичні терміни
                for kw in ['критично','тахікардія','брадикардія',
                           'консультація лікаря','зверніться до лікаря',
                           'підвищений тиск','ожиріння']:
                    if kw in t: return 'Критично'
                # Норма — явні ключові слова норми
                for kw in ['— норма','в нормі','у нормі','відповідає нормі',
                           'норма.','продовжуйте підтримувати',
                           'позитивна динаміка','добре']:
                    if kw in t: return 'Норма'
                return 'Відхилення'

            # Рівень персоналізації
            def person_level(text):
                if not text: return 'Загальна'
                t = text.lower()
                has_personal = any(kw in t for kw in [
                    'вашої норми','вашого звичного','вашої звичайн',
                    'нижче вашої','вище вашої','ваш звичний'])
                has_cluster = any(kw in t for kw in [
                    'вашого профілю','людей вашого','вашої групи',
                    'вашого віку','норми групи'])
                has_forecast = any(kw in t for kw in [
                    'прогноз','через 7 днів','через тиждень'])
                if has_forecast: return 'Висока'
                if has_cluster:  return 'Висока'
                if has_personal: return 'Середня'
                if re.search(r'\d+[.,]?\d*', t): return 'Базова'
                return 'Загальна'

            ap_labels = {'rule_based':'Rule-Based','ml':'ML','ai':'AI'}

            # ── Кругові діаграми ──
            fig_dist, axes = plt.subplots(1, 3, figsize=(13, 5.2))
            fig_dist.patch.set_facecolor('white')
            pie_cols  = [GREEN, AMBER, RED]
            pie_names = ['Норма','Відхилення','Критично']

            for ax, ap in zip(axes, APPROACHES):
                d = dist[ap]
                recs_all = self.db_repo.execute_query(
                    "SELECT recommendation FROM recommendations WHERE approach=?",
                    (ap,), fetchall=True) or []
                # Перекласифіковуємо з покращеним класифікатором
                real = {'Норма':0,'Відхилення':0,'Критично':0}
                for (t,) in recs_all:
                    c = classify_rec(t)
                    if c: real[c] += 1
                total = sum(real.values())
                n_users_with = len(set(
                    r[0] for r in (self.db_repo.execute_query(
                        "SELECT DISTINCT user_id FROM recommendations WHERE approach=?",
                        (ap,), fetchall=True) or [])))

                ax.set_facecolor('white')
                if total == 0:
                    ax.text(0.5,0.5,'Немає даних\nЗапусти seed_db.py',
                            ha='center',va='center',transform=ax.transAxes,
                            color=TXT2,fontsize=11)
                else:
                    vals_f = [real[k] for k in pie_names if real[k]>0]
                    cols_f = [pie_cols[i] for i,k in enumerate(pie_names) if real[k]>0]
                    labs_f = [pie_names[i] for i,k in enumerate(pie_names) if real[k]>0]
                    w, ts, auts = ax.pie(
                        vals_f, labels=labs_f, colors=cols_f,
                        autopct='%1.0f%%', startangle=90,
                        explode=[0.03]*len(vals_f), pctdistance=0.68,
                        wedgeprops=dict(edgecolor='white',linewidth=2))
                    for t in ts:  t.set_fontsize(11); t.set_color(TXT2)
                    for a in auts: a.set_fontsize(11); a.set_fontweight('700'); a.set_color('white')
                ax.set_title(
                    f"{ap_labels[ap]}\n"
                    f"{total} рекомендацій по {n_users_with} профілях",
                    fontsize=11, fontweight='bold', color=TXTC, pad=10)

            fig_dist.suptitle('Розподіл типів рекомендацій по підходах\n'
                '(класифікація по ключових словах у тексті рекомендації)',
                fontsize=12, fontweight='bold', color=TXTC, y=1.04)
            chart_dist = fig_to_b64(fig_dist)

            # ── Накопичена стовпчаста (stacked) — персоналізація ──
            levels = ['Загальна','Базова','Середня','Висока']
            lcols  = ['#e2e8f0','#94a3b8','#3b82f6','#1e40af']
            llabs  = [
                'Загальна — загальна фраза без порівнянь',
                'Базова — є конкретне число',
                'Середня — порівняння з особистою нормою',
                'Висока — прогноз або кластерне порівняння']

            pdata = {}
            for ap in APPROACHES:
                recs = self.db_repo.execute_query(
                    "SELECT recommendation FROM recommendations WHERE approach=?",
                    (ap,), fetchall=True) or []
                cnt = {l:0 for l in levels}
                for (t,) in recs:
                    cnt[person_level(t)] += 1
                tot = len(recs) or 1
                pdata[ap] = {l: round(v*100/tot) for l,v in cnt.items()}

            fig_pers, ax2 = plt.subplots(figsize=(9, 5.5))
            fig_pers.patch.set_facecolor('white')
            ax2.set_facecolor('#f8f9fc')

            ap_names = ['Rule-Based','ML','AI']
            x = np.arange(3)
            bottoms = np.zeros(3)

            for lev, col, lab in zip(levels, lcols, llabs):
                vals = np.array([pdata[ap][lev] for ap in APPROACHES], dtype=float)
                bars = ax2.bar(x, vals, 0.5, bottom=bottoms,
                               label=lab, color=col, edgecolor='white', linewidth=1.2, zorder=3)
                for i,(bar,v) in enumerate(zip(bars,vals)):
                    if v >= 8:
                        ax2.text(bar.get_x()+bar.get_width()/2,
                                 bottoms[i]+v/2,
                                 f'{int(v)}%', ha='center', va='center',
                                 fontsize=9.5, fontweight='700',
                                 color='white' if col in ['#3b82f6','#1e40af'] else TXTC)
                bottoms += vals

            ax2.set_xticks(x)
            ax2.set_xticklabels(ap_names, fontsize=13, fontweight='700', color=TXTC)
            ax2.set_ylabel('% рекомендацій', fontsize=10, color=TXT2)
            ax2.set_ylim(0, 115)
            ax2.set_title(
                'Рівень персоналізації рекомендацій\n'
                'Кожен стовпчик = 100% рекомендацій підходу, поділених за рівнем персоналізації',
                fontsize=11, fontweight='bold', color=TXTC, pad=12)
            ax2.spines['top'].set_visible(False)
            ax2.spines['right'].set_visible(False)
            ax2.spines['left'].set_color('#e2e8f0')
            ax2.spines['bottom'].set_color('#e2e8f0')
            ax2.grid(axis='y', color='#e2e8f0', linewidth=0.8, linestyle='--', zorder=0)
            ax2.set_axisbelow(True)
            legend = ax2.legend(fontsize=9, framealpha=0.95, edgecolor='#e2e8f0',
                                fancybox=True, loc='upper right',
                                title='Рівень персоналізації', title_fontsize=9.5,
                                bbox_to_anchor=(1.0, 1.0))
            legend.get_title().set_fontweight('700')
            chart_pers = fig_to_b64(fig_pers)

            return render_template('research.html',
                page='research',
                users_table=users_table,
                dist=dist,
                specificity=specificity,
                coverage=coverage,
                categories=CATEGORIES,
                approaches=APPROACHES,
                chart_dist=chart_dist,
                chart_pers=chart_pers)

        @self.app.route('/profile', methods=['GET', 'POST'])
        def profile():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = self.get_current_user()
            if request.method == 'POST':
                data = {
                    'age': request.form.get('age'),
                    'gender': request.form.get('gender'),
                    'height': request.form.get('height'),
                    'initial_weight': request.form.get('initial_weight'),
                    'goal': request.form.get('goal'),
                    'activity_level': request.form.get('activity_level'),
                }
                self.user_repo.complete_onboarding(session['user_id'], data)
                flash('Профіль оновлено!', 'success')
                return redirect(url_for('profile'))
            return render_template('profile.html', page='profile', user=user)

        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            error_email, error_password = None, None
            if request.method == 'POST':
                email = request.form['email']
                password = request.form['password']
                user = self.user_repo.get_user_by_email(email)
                if user is None:
                    error_email = "Користувач не існує. Зареєструйтеся."
                else:
                    pwd_ok = False
                    try:
                        pwd_ok = check_password_hash(user[3], password)
                    except Exception:
                        pass
                    if not pwd_ok:
                        pwd_ok = (user[3] == password)
                    if not pwd_ok:
                        error_password = "Невірний пароль."
                    else:
                        session['user_id'] = user[0]
                        if not user[10]:  # onboarding_complete
                            return redirect(url_for('onboarding'))
                        return redirect(url_for('dashboard'))
            return render_template('login.html', error_email=error_email, error_password=error_password)

        @self.app.route('/register', methods=['GET', 'POST'])
        def register():
            if request.method == 'POST':
                username = request.form['username']
                email = request.form['email']
                password = request.form['password']
                if not all([username, email, password]):
                    flash('Усі поля обовʼязкові!', 'error')
                    return redirect(url_for('register'))
                if len(password) < 8:
                    flash('Пароль має бути довшим за 8 символів!', 'error')
                    return redirect(url_for('register'))
                hashed_pw = generate_password_hash(password)
                if self.user_repo.register_user(username, email, hashed_pw):
                    user = self.user_repo.get_user_by_email(email)
                    if user:
                        session['user_id'] = user[0]
                        return redirect(url_for('onboarding'))
                    flash('Помилка реєстрації. Спробуйте ще раз.', 'error')
                    return redirect(url_for('register'))
                flash('Користувач із таким email або іменем вже існує!', 'error')
            return render_template('register.html')

        @self.app.route('/save-ai-rec', methods=['POST'])
        def save_ai_rec():
            if 'user_id' not in session:
                return {'ok': False}, 401
            from flask import jsonify
            import json as _json
            data = request.get_json()
            rec = data.get('recommendation', '')
            if rec:
                self.db_repo.execute_query(
                    "INSERT INTO recommendations (user_id, date, approach, category, recommendation) VALUES (?, ?, ?, ?, ?)",
                    (session['user_id'], datetime.now().strftime('%Y-%m-%d'), 'ai', 'general', rec[:500])
                )
            return {'ok': True}

        @self.app.route('/logout')
        def logout():
            session.clear()
            return redirect(url_for('login'))


    def save_all_data(self, request):
        """Зберігає всі дані з єдиної форми трекера (all_data form_type)"""
        uid  = session['user_id']
        date = request.form.get('date')
        if not date:
            from datetime import datetime
            date = datetime.now().strftime('%Y-%m-%d')

        # weight: пріоритет — текстове поле, fallback — слайдер
        weight_text   = request.form.get('weight', '').strip()
        weight_slider = request.form.get('weight_range', '').strip()
        weight = weight_text or weight_slider

        steps_text    = request.form.get('steps', '').strip()
        steps_slider  = request.form.get('steps_range', '').strip()
        steps = steps_text or steps_slider

        sleep  = request.form.get('duration_sleep', '').strip()
        pulse  = request.form.get('pulse', '').strip()
        bp     = request.form.get('blood_pressure', '').strip()
        act    = request.form.get('activity_type', '').strip()
        dur    = request.form.get('duration', '').strip()
        water  = request.form.get('water_intake', '').strip()

        # Ігноруємо мінімальні значення слайдерів (означає "не введено")
        if weight == '40': weight = ''   # мін слайдера ваги
        if steps  == '0':  steps  = ''   # мін слайдера кроків
        if sleep  == '0':  sleep  = ''
        if pulse  == '40': pulse  = ''
        if water  == '0':  water  = ''

        if weight or steps:
            self.db_repo.execute_query(
                "INSERT INTO basic_data (user_id, date, weight, steps) VALUES (?,?,?,?)",
                (uid, date,
                 float(weight) if weight else None,
                 int(steps)    if steps  else None)
            )

        if sleep or pulse or bp:
            self.db_repo.execute_query(
                "INSERT INTO health_data (user_id, date, duration_sleep, pulse, blood_pressure) VALUES (?,?,?,?,?)",
                (uid, date,
                 float(sleep) if sleep else None,
                 int(pulse)   if pulse else None,
                 bp           if bp    else None)
            )

        if act or dur or water:
            self.db_repo.execute_query(
                "INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake) VALUES (?,?,?,?,?)",
                (uid, date,
                 act          if act   else None,
                 int(dur)     if dur   else None,
                 float(water) if water else None)
            )

    def save_combined_data(self, request):
        """Зберігає всі дані з єдиної форми трекера"""
        uid   = session['user_id']
        date  = request.form.get('date')
        if not date:
            from datetime import datetime
            date = datetime.now().strftime('%Y-%m-%d')

        weight = request.form.get('weight')
        steps  = request.form.get('steps')
        sleep  = request.form.get('duration_sleep')
        pulse  = request.form.get('pulse')
        bp     = request.form.get('blood_pressure')
        act    = request.form.get('activity_type')
        dur    = request.form.get('duration')
        water  = request.form.get('water_intake')

        # Зберігаємо тільки ті поля що заповнені
        if weight or steps:
            self.db_repo.execute_query(
                "INSERT INTO basic_data (user_id, date, weight, steps) VALUES (?,?,?,?)",
                (uid, date,
                 float(weight) if weight else None,
                 int(steps) if steps else None)
            )

        if sleep or pulse or bp:
            self.db_repo.execute_query(
                "INSERT INTO health_data (user_id, date, duration_sleep, pulse, blood_pressure) VALUES (?,?,?,?,?)",
                (uid, date,
                 float(sleep) if sleep else None,
                 int(pulse) if pulse else None,
                 bp if bp else None)
            )

        if act or dur or water:
            self.db_repo.execute_query(
                "INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake) VALUES (?,?,?,?,?)",
                (uid, date,
                 act if act else None,
                 int(dur) if dur else None,
                 float(water) if water else None)
            )

        flash('Дані збережено.', 'success')

    def save_daily_data(self, request):
        date = request.form.get('date')
        weight = request.form.get('weight')
        steps = request.form.get('steps')
        if not date:
            flash('Дата обовʼязкова!', 'error')
            return
        try:
            datetime.strptime(date, '%Y-%m-%d')
            weight = float(weight) if weight else None
            steps = int(steps) if steps else None
        except ValueError:
            flash('Невірні дані.', 'error')
            return
        self.db_repo.execute_query(
            "INSERT INTO basic_data (user_id, date, weight, steps) VALUES (?, ?, ?, ?)",
            (session['user_id'], date, weight, steps)
        )
        flash('Дані збережено.', 'success')

    def save_health_data(self, request):
        date = request.form.get('date')
        pulse = request.form.get('pulse')
        blood_pressure = request.form.get('blood_pressure')
        duration_sleep = request.form.get('duration_sleep')
        if not date:
            flash('Дата обовʼязкова!', 'error')
            return
        try:
            datetime.strptime(date, '%Y-%m-%d')
            pulse = int(pulse) if pulse else None
            duration_sleep = float(duration_sleep) if duration_sleep else None
        except ValueError:
            flash('Невірні дані.', 'error')
            return
        self.db_repo.execute_query(
            "INSERT INTO health_data (user_id, date, pulse, blood_pressure, duration_sleep) VALUES (?, ?, ?, ?, ?)",
            (session['user_id'], date, pulse, blood_pressure, duration_sleep)
        )
        flash('Показники здоровʼя збережено.', 'success')

    def save_activity_data(self, request):
        date = request.form.get('date')
        activity_type = request.form.get('activity_type')
        duration = request.form.get('duration')
        water_intake = request.form.get('water_intake')
        if not date:
            flash('Дата обовʼязкова!', 'error')
            return
        try:
            datetime.strptime(date, '%Y-%m-%d')
            duration = int(duration) if duration else None
            water_intake = float(water_intake) if water_intake else None
        except ValueError:
            flash('Невірні дані.', 'error')
            return
        self.db_repo.execute_query(
            "INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake) VALUES (?, ?, ?, ?, ?)",
            (session['user_id'], date, activity_type, duration, water_intake)
        )
        flash('Активність збережено.', 'success')


    def generate_rule_based_recommendation(self, form_type='daily_data'):
        uid = session.get('user_id')
        if not uid:
            print("[WARN] rule_based: немає user_id в сесії")
            return
        user = self.get_current_user()
        if not user:
            print(f"[WARN] rule_based: юзера {uid} не знайдено в БД")
            return

        height = user[6]
        if not height:
            print(f"[WARN] rule_based: у юзера {uid} не заповнено зріст — онбординг не завершено")

        recs = []

        if form_type == 'daily_data':
            last_weight = self.db_repo.execute_query(
                "SELECT weight FROM basic_data WHERE user_id=? AND weight IS NOT NULL ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            if last_weight and height:
                bmi = round(last_weight[0] / ((height / 100) ** 2), 2)
                if bmi < 18.5:
                    recs.append(('weight', f'ІМТ {bmi} — недостатня вага. Рекомендується збільшити калорійність раціону та додати силові тренування.'))
                elif bmi < 25:
                    recs.append(('weight', f'ІМТ {bmi} — норма. Продовжуйте підтримувати поточний режим харчування та активності.'))
                elif bmi < 30:
                    recs.append(('weight', f'ІМТ {bmi} — надмірна вага. Рекомендується помірний дефіцит калорій та 150+ хв кардіо на тиждень.'))
                else:
                    recs.append(('weight', f'ІМТ {bmi} — ожиріння. Рекомендується консультація з лікарем та поступове зниження ваги.'))

        elif form_type == 'health_data':
            last_sleep = self.db_repo.execute_query(
                "SELECT duration_sleep FROM health_data WHERE user_id=? AND duration_sleep IS NOT NULL ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            last_pulse = self.db_repo.execute_query(
                "SELECT pulse FROM health_data WHERE user_id=? AND pulse IS NOT NULL ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            last_bp = self.db_repo.execute_query(
                "SELECT blood_pressure FROM health_data WHERE user_id=? AND blood_pressure IS NOT NULL ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            if last_sleep:
                s = last_sleep[0]
                if s < 6:
                    recs.append(('sleep', f'Сон {s} год — критично мало. Намагайтесь лягати до 23:00 та прибрати екрани за годину до сну.'))
                elif s < 7:
                    recs.append(('sleep', f'Сон {s} год — недостатньо. Рекомендується 7–9 годин для відновлення.'))
                elif s <= 9:
                    recs.append(('sleep', f'Сон {s} год — норма. Підтримуйте стабільний режим сну.'))
                else:
                    recs.append(('sleep', f'Сон {s} год — забагато. Надмірний сон може свідчити про втому.'))
            if last_pulse:
                p = last_pulse[0]
                if p < 50:
                    recs.append(('pulse', f'Пульс {p} уд/хв — нижче норми. Зверніться до лікаря якщо відчуваєте слабкість.'))
                elif p > 100:
                    recs.append(('pulse', f'Пульс {p} уд/хв — підвищений. Уникайте кофеїну та стресу.'))
                else:
                    recs.append(('pulse', f'Пульс {p} уд/хв — норма.'))
            if last_bp:
                try:
                    sys_v = int(last_bp[0].split('/')[0])
                    if sys_v >= 140:
                        recs.append(('pressure', f'Тиск {last_bp[0]} — підвищений. Рекомендується консультація лікаря.'))
                    elif sys_v >= 130:
                        recs.append(('pressure', f'Тиск {last_bp[0]} — помірно підвищений. Обмежте сіль і додайте кардіо.'))
                    else:
                        recs.append(('pressure', f'Тиск {last_bp[0]} — норма.'))
                except Exception:
                    pass

        elif form_type == 'activity_data':
            last_water = self.db_repo.execute_query(
                "SELECT water_intake FROM activity_data WHERE user_id=? AND water_intake IS NOT NULL ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            last_activity = self.db_repo.execute_query(
                "SELECT activity_type, duration FROM activity_data WHERE user_id=? ORDER BY date DESC LIMIT 1",
                (uid,), fetchone=True
            )
            if last_water:
                w = last_water[0]
                if w < 1.5:
                    recs.append(('hydration', f'Вода {w} л — недостатньо. Норма: 2–2.5 л на день.'))
                elif w < 2.0:
                    recs.append(('hydration', f'Вода {w} л — прийнятно. Намагайтесь досягти 2 л.'))
                else:
                    recs.append(('hydration', f'Вода {w} л — добре! Підтримуйте водний баланс.'))
            if last_activity:
                act_type, duration = last_activity
                if duration and duration < 20:
                    recs.append(('activity', f'Тривалість активності {duration} хв — мало. Рекомендується мінімум 30 хв на день.'))
                elif duration and duration >= 30:
                    recs.append(('activity', f'Активність {duration} хв — добрий результат!'))

        print(f"[DEBUG] rule_based form_type={form_type}, recs={len(recs)}, uid={uid}")
        for category, text in recs:
            if isinstance(text, str) and text.strip():
                self._save_recommendation(uid, 'rule_based', category, text)
                print(f"[DEBUG] rule_based збережено: {category}")
            else:
                print(f"[WARN] rule_based text має тип {type(text)}: {text}")


    def plot_metric_chart(self, metric_name: str, ylabel: str, color: str = '#6366f1') -> Optional[str]:
        metric_to_table = {
            'weight': 'basic_data',
            'steps': 'basic_data',
            'pulse': 'health_data',
            'pressure': 'health_data',
            'sleep': 'health_data',
            'water_intake': 'activity_data'
        }
        column_map = {
            'weight': 'weight',
            'steps': 'steps',
            'pulse': 'pulse',
            'pressure': 'blood_pressure',
            'sleep': 'duration_sleep',
            'water_intake': 'water_intake'
        }
        table = metric_to_table.get(metric_name)
        column = column_map.get(metric_name)
        if not table or not column:
            return None

        data = self.db_repo.execute_query(
            f"SELECT date, {column} FROM {table} WHERE user_id = ? ORDER BY date DESC LIMIT 14",
            (session['user_id'],), fetchall=True
        )
        if not data or all(row[1] is None for row in data):
            return None

        data.reverse()
        dates, values = [], []
        for row in data:
            date_str, value = row[0], row[1]
            if value is None:
                continue
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                val = float(value.split('/')[0]) if metric_name == 'pressure' else float(value)
                if val <= 0:
                    continue
                dates.append(dt)
                values.append(val)
            except (ValueError, AttributeError):
                continue

        if not values or not dates:
            return None

        fig, ax = plt.subplots(figsize=(8, 3.5))
        fig.patch.set_alpha(0)
        ax.set_facecolor('none')

        ax.plot(dates, values, color=color, linewidth=2.5, marker='o',
                markersize=6, markerfacecolor='white', markeredgewidth=2, zorder=3)
        ax.fill_between(dates, values, alpha=0.08, color=color)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_color('#e2e8f0')
        ax.grid(axis='y', linestyle='--', alpha=0.2, color='#94a3b8')
        ax.grid(axis='x', visible=False)
        ax.tick_params(axis='both', which='both', length=0)

        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
        plt.xticks(fontsize=9, color='#94a3b8')
        plt.yticks(fontsize=9, color='#94a3b8')

        buf = io.BytesIO()
        plt.tight_layout(pad=1.0)
        plt.savefig(buf, format='png', transparent=True, dpi=110)
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()
        buf.close()
        return img_base64

    def _save_recommendation(self, uid, approach, category, text):
        if not isinstance(text, str) or not text.strip():
            print(f"[WARN] _save_recommendation: text має тип {type(text)}, пропускаємо")
            return
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            self.db_repo.execute_query(
                "DELETE FROM recommendations WHERE user_id=? AND approach=? AND category=?",
                (uid, approach, category)
            )
            self.db_repo.execute_query(
                "INSERT INTO recommendations (user_id, date, approach, category, recommendation) VALUES (?,?,?,?,?)",
                (uid, today, approach, category, text)
            )
            print(f"[DEBUG] _save_recommendation OK: {approach}/{category}")
        except Exception as e:
            print(f"[ERROR] _save_recommendation {approach}/{category}: {e}")

    def generate_ml_recommendation(self):
        uid = session.get('user_id')
        if not uid:
            return
        try:
            recs = self.ml.generate(uid, self.db_repo)
            print(f"[DEBUG] ML generate повернув {len(recs)} категорій: {list(recs.keys())}")
            for category, text in recs.items():
                if text and isinstance(text, str):
                    self._save_recommendation(uid, 'ml', category, text)
                    print(f"[DEBUG] ML збережено: {category}")
        except Exception as e:
            import traceback
            print(f"[ERROR] generate_ml_recommendation: {e}")
            traceback.print_exc()

    def generate_ai_recommendation(self, form_type='daily_data'):
        uid = session.get('user_id')
        print(f"[DEBUG] AI: form_type={form_type}, uid={uid}")
        if not uid:
            return
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')

        needed = {
            'daily_data':    ['weight'],
            'health_data':   ['sleep', 'pulse', 'pressure'],
            'activity_data': ['hydration'],
        }.get(form_type, [])

        print(f"[DEBUG] AI: needed={needed}")
        if not needed:
            return

        existing = self.db_repo.execute_query(
            "SELECT category FROM recommendations WHERE user_id=? AND approach='ai' AND date=?",
            (uid, today), fetchall=True
        )
        existing_cats = {r[0] for r in existing} if existing else set()
        to_generate = [c for c in needed if c not in existing_cats]

        print(f"[DEBUG] AI: to_generate={to_generate}, existing={existing_cats}")
        if not to_generate:
            print(f"[DEBUG] AI: всі категорії вже є сьогодні — пропускаємо")
            return

        print(f"[DEBUG] AI: запускаємо generate для {to_generate}")
        try:
            recs = self.ai.generate(uid, self.db_repo, categories=to_generate)
            print(f"[DEBUG] AI: отримано {len(recs)} рекомендацій: {list(recs.keys())}")
            for category, text in recs.items():
                if text and isinstance(text, str):
                    self._save_recommendation(uid, 'ai', category, text)
                    print(f"[DEBUG] AI збережено: {category}")
        except Exception as e:
            import traceback
            print(f"[ERROR] generate_ai_recommendation: {e}")
            traceback.print_exc()


    def setup_chat_route(self):
        @self.app.route('/api/chat', methods=['POST'])
        def api_chat():
            if 'user_id' not in session:
                return {'error': 'unauthorized'}, 401
            data = request.get_json()
            user_message = data.get('message', '').strip()
            if not user_message:
                return {'error': 'empty'}, 400

            uid = session['user_id']
            user = self.db_repo.execute_query(
                "SELECT username, age, gender, height, goal, activity_level FROM users WHERE id=?",
                (uid,), fetchone=True
            )
            profile = ''
            if user:
                profile = f"Ім'я: {user[0]}, вік: {user[1]}, стать: {user[2]}, зріст: {user[3]} см, ціль: {user[4]}"

            try:
                from groq import Groq
                import os
                client = Groq(api_key=os.getenv('GROQ_API_KEY'))
                response = client.chat.completions.create(
                    model='llama-3.3-70b-versatile',
                    messages=[
                        {"role": "system", "content": f"Ти — AI помічник у Health Tracker. Профіль користувача: {profile}. Відповідай українською мовою, коротко і практично, 2-4 речення."},
                        {"role": "user", "content": user_message}
                    ],
                    max_tokens=300,
                    temperature=0.5,
                )
                reply = response.choices[0].message.content.strip()
                return {'reply': reply}
            except Exception as e:
                return {'reply': f'Помилка: {str(e)}'}

    def run(self):
        self.app.run(debug=True, port=5003)


if __name__ == "__main__":
    app = HealthTrackerApp()
    app.run()