import matplotlib
matplotlib.use('Agg')
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import io
import base64
import matplotlib.pyplot as plt
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import os
from datetime import datetime
from recommenders.ml_recommender import MLRecommender

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
                onboarding_complete INTEGER DEFAULT 0
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
        self.app.secret_key = os.urandom(24)
        self.db_repo = DatabaseRepository('health_tracker.db')
        self.user_repo = UserRepository(self.db_repo)
        self.calculators = {
            'bmi': BMICalculator(),
            'body_fat': BodyFatCalculator(),
            'calories': CalorieCalculator(),
        }
        self.db_repo.initialize_db()
        csv_path = os.path.join(os.path.dirname(__file__), "personalised_dataset_clean.csv")
        self.ml = MLRecommender(csv_path)
        self.setup_routes()

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
            latest_rule = self.db_repo.execute_query(
                "SELECT recommendation FROM recommendations WHERE user_id=? AND approach='rule_based' ORDER BY date DESC LIMIT 1",
                (session['user_id'],), fetchone=True
            )
            latest_ml = self.db_repo.execute_query(
                "SELECT recommendation FROM recommendations WHERE user_id=? AND approach='ml' ORDER BY date DESC LIMIT 1",
                (session['user_id'],), fetchone=True
            )

            return render_template('dashboard.html',
                                   username=user[1],
                                   user=user,
                                   chart_data=chart_data,
                                   latest_rule=latest_rule,
                                   latest_ml=latest_ml,
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

                if form_type == 'daily_data':
                    self.save_daily_data(request)
                    self.generate_rule_based_recommendation('daily_data')
                    self.generate_ml_recommendation()
                    return redirect(url_for('tracker'))
                elif form_type == 'health_data':
                    self.save_health_data(request)
                    self.generate_rule_based_recommendation('health_data')
                    self.generate_ml_recommendation()
                    return redirect(url_for('tracker'))
                elif form_type == 'activity_data':
                    self.save_activity_data(request)
                    self.generate_rule_based_recommendation('activity_data')
                    self.generate_ml_recommendation()
                    return redirect(url_for('tracker'))
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
            recs = self.db_repo.execute_query(
                '''SELECT approach, category, recommendation, date
                   FROM recommendations WHERE user_id=? ORDER BY date DESC LIMIT 30''',
                (session['user_id'],), fetchall=True
            )
            grouped = {'rule_based': [], 'ml': [], 'ai': []}
            for r in (recs or []):
                if r[0] in grouped:
                    grouped[r[0]].append(r)
            return render_template('research.html', page='research', grouped=grouped)

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
                elif user[3] != password:
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
                if self.user_repo.register_user(username, email, password):
                    user = self.user_repo.get_user_by_email(email)
                    session['user_id'] = user[0]
                    return redirect(url_for('onboarding'))
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
        uid = session['user_id']
        user = self.get_current_user()
        if not user:
            return

        height = user[6]
        recs   = []

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

        for category, text in recs:
            self._save_recommendation(uid, 'rule_based', category, text)


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
        today = datetime.now().strftime('%Y-%m-%d')
        self.db_repo.execute_query(
            "INSERT INTO recommendations (user_id, date, approach, category, recommendation) VALUES (?,?,?,?,?)",
            (uid, today, approach, category, text)
        )

    def generate_ml_recommendation(self):
        uid = session.get('user_id')
        if not uid:
            return
        today = datetime.now().strftime('%Y-%m-%d')
        already = self.db_repo.execute_query(
            "SELECT id FROM recommendations WHERE user_id=? AND approach='ml' AND date=?",
            (uid, today), fetchone=True
        )
        if already:
            return
        rec_text = self.ml.generate(uid, self.db_repo)
        if rec_text:
            self._save_recommendation(uid, 'ml', 'general', rec_text)

    def run(self):
        self.app.run(debug=True, port=5001)


if __name__ == "__main__":
    app = HealthTrackerApp()
    app.run()