import matplotlib
matplotlib.use('Agg')  # Використовуємо неінтерактивний бекенд для серверного рендерингу
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import io
import base64
import matplotlib.pyplot as plt
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import os  # Для генерації випадкового secret_key
from datetime import datetime  # Для валідації дати

# Абстрактний клас для калькуляторів (патерн Стратегія)
class Calculator(ABC):
    @abstractmethod
    def calculate(self, data: Dict[str, Any]) -> float:
        pass

class BMICalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        if not data.get('weight') or not data.get('height'):
            raise ValueError("Weight and height are required.")
        try:
            weight = float(data.get('weight'))
            height = float(data.get('height'))
        except (ValueError, TypeError):
            raise ValueError("Weight and height must be numeric.")
        if weight <= 0 or height <= 0:
            raise ValueError("Weight and height must be positive.")
        return round(weight / ((height / 100) ** 2), 2)

class BodyFatCalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        required_fields = ['gender', 'age', 'chest', 'abdomen', 'thigh']
        if not all(data.get(field) for field in required_fields):
            raise ValueError("All fields (gender, age, chest, abdomen, thigh) are required.")
        gender = data.get('gender').lower()
        if gender not in ['male', 'female']:
            raise ValueError("Gender must be 'male' or 'female'.")
        try:
            age = int(data.get('age'))
            chest = float(data.get('chest'))
            abdomen = float(data.get('abdomen'))
            thigh = float(data.get('thigh'))
        except (ValueError, TypeError):
            raise ValueError("Age, chest, abdomen, and thigh must be numeric.")
        if chest <= 0 or abdomen <= 0 or thigh <= 0 or age <= 0:
            raise ValueError("All measurements and age must be positive.")

        fat_result = 1.097 - (0.00046971 * (chest + abdomen + thigh)) + \
                     (0.00000056 * (chest + abdomen + thigh) ** 2) - \
                     (0.00012828 * age) - (5.4 if gender == 'female' else 0)
        return max(0, round(fat_result, 2))

class CalorieCalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        required_fields = ['gender', 'weight', 'height', 'age', 'activity_level']
        if not all(data.get(field) for field in required_fields):
            raise ValueError("All fields (gender, weight, height, age, activity_level) are required.")
        gender = data.get('gender').lower()
        if gender not in ['male', 'female']:
            raise ValueError("Gender must be 'male' or 'female'.")
        try:
            weight = float(data.get('weight'))
            height = float(data.get('height'))
            age = int(data.get('age'))
            activity_level = float(data.get('activity_level'))
        except (ValueError, TypeError):
            raise ValueError("Weight, height, age, and activity level must be numeric.")
        if weight <= 0 or height <= 0 or age <= 0:
            raise ValueError("Weight, height, and age must be positive.")
        if activity_level < 1.0 or activity_level > 2.5:
            raise ValueError("Activity level must be between 1.0 and 2.5.")

        bmr = (88.36 + (13.4 * weight) + (4.8 * height) - (5.7 * age) if gender == 'male'
               else 447.6 + (9.2 * weight) + (3.1 * height) - (4.3 * age))
        return round(bmr * activity_level, 2)

# Клас-репозиторій для роботи з базою даних
class DatabaseRepository:
    def __init__(self, db_name: str):
        self.db_name = db_name

    def execute_query(self, query: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False) -> Optional[Any]:
        """Виконує SQL-запит і повертає результат."""
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
        """Ініціалізує базу даних, створюючи таблиці лише якщо їх немає."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        tables = [
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL  -- Повертаємося до TEXT, без хешування
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS basic_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                age INTEGER,
                gender TEXT,
                weight REAL,
                height REAL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS health_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                pulse INTEGER,
                blood_pressure TEXT,
                duration_sleep INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS activity_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                activity_type TEXT,
                duration INTEGER,
                water_intake REAL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS calculator_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                calculator_type TEXT NOT NULL,
                result REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            '''
        ]

        for table_query in tables:
            cursor.execute(table_query)

        conn.commit()
        conn.close()

# Клас для управління користувачами
class UserRepository:
    def __init__(self, db_repo: DatabaseRepository):
        self.db_repo = db_repo

    def get_user_by_email(self, email: str) -> Optional[tuple]:
        """Отримує користувача за email."""
        return self.db_repo.execute_query(
            "SELECT * FROM users WHERE email = ?", (email,), fetchone=True
        )

    def register_user(self, username: str, email: str, password: str) -> bool:
        """Реєструє нового користувача без хешування пароля."""
        try:
            self.db_repo.execute_query(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            return True
        except sqlite3.IntegrityError:
            return False

# Основний клас додатку Health Tracker
class HealthTrackerApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.secret_key = os.urandom(24)  # Генеруємо випадковий secret_key
        self.db_repo = DatabaseRepository('health_tracker.db')
        self.user_repo = UserRepository(self.db_repo)
        self.calculators = {
            'bmi': BMICalculator(),
            'body_fat': BodyFatCalculator(),
            'calories': CalorieCalculator(),
        }
        self.db_repo.initialize_db()
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/home', methods=['GET', 'POST'])
        def home():
            if 'user_id' not in session:
                return redirect(url_for('login'))

            section = request.args.get('section', 'welcome')
            user = self.db_repo.execute_query(
                "SELECT username, email FROM users WHERE id = ?",
                (session['user_id'],),
                fetchone=True
            )

            username = user[0] if user else 'Користувач'
            user_email = user[1] if user else 'Немає електронної пошти'

            bmi_result, fat_result, calorie_result = None, None, None

            if request.method == 'POST':
                if section == 'indicators':
                    form_type = request.form.get('form_type')
                    if form_type == 'basic_data':
                        result = self.save_basic_data(request)
                        if result:  # Якщо повертається redirect, виконуємо його
                            return result
                    elif form_type == 'health_data':
                        result = self.save_health_data(request)
                        if result:
                            return result
                    elif form_type == 'activity_data':
                        result = self.save_activity_data(request)
                        if result:
                            return result
                    return redirect(url_for('home', section='indicators'))

                elif section == 'calculators':
                    calculator_type = request.form.get('calculator_type')
                    if calculator_type in self.calculators:
                        try:
                            calculator = self.calculators[calculator_type]
                            result = calculator.calculate(request.form)
                            self.db_repo.execute_query(
                                "INSERT INTO calculator_results (user_id, calculator_type, result) VALUES (?, ?, ?)",
                                (session['user_id'], calculator_type, result)
                            )
                            if calculator_type == 'bmi':
                                bmi_result = result
                            elif calculator_type == 'body_fat':
                                fat_result = result
                            elif calculator_type == 'calories':
                                calorie_result = result
                        except ValueError as e:
                            flash(str(e), 'error')

            return render_template(
                'home.html',
                username=username,
                user_email=user_email,
                section=section,
                bmi_result=bmi_result,
                fat_result=fat_result,
                calorie_result=calorie_result
            )

        @self.app.route('/profile')
        def profile():
            if 'user_id' not in session:
                return redirect(url_for('login'))

            user = self.db_repo.execute_query(
                "SELECT username, email FROM users WHERE id = ?",
                (session['user_id'],),
                fetchone=True
            )
            username = user[0] if user else 'Користувач'
            user_email = user[1] if user else 'Немає електронної пошти'

            chart_data = {}
            metrics = [
                {'id': 'weight', 'label': 'Вага (кг)', 'color': 'blue'},
                {'id': 'pulse', 'label': 'Пульс (уд/хв)', 'color': 'red'},
                {'id': 'pressure', 'label': 'Систолічний тиск (мм рт. ст.)', 'color': 'purple'},
                {'id': 'water_intake', 'label': 'Випита вода (л)', 'color': 'cyan'},
                {'id': 'sleep', 'label': 'Тривалість сну (год)', 'color': 'green'}
            ]

            for metric in metrics:
                chart_data[metric['id']] = self.plot_metric_chart(
                    metric['id'],
                    metric['label'],
                    metric['color']
                )

            return render_template(
                'home.html',
                section='profile',
                username=username,
                user_email=user_email,
                chart_data=chart_data
            )

        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            error_email, error_password = None, None
            if request.method == 'POST':
                email, password = request.form['email'], request.form['password']
                user = self.user_repo.get_user_by_email(email)
                if user is None:
                    error_email = "Користувач не існує. Зареєструйтеся."
                elif user[3] != password:  # Порівнюємо пароль напряму
                    error_password = "Невірний пароль."
                else:
                    session['user_id'] = user[0]
                    return redirect(url_for('home'))
            return render_template(
                'login.html',
                error_email=error_email,
                error_password=error_password
            )

        @self.app.route('/register', methods=['GET', 'POST'])
        def register():
            if request.method == 'POST':
                username = request.form['username']
                email = request.form['email']
                password = request.form['password']
                if not all([username, email, password]):
                    flash('Усі поля обов’язкові!', 'error')
                    return redirect(url_for('register'))
                if len(password) < 8:
                    flash('Пароль має бути довшим за 8 символів!', 'error')
                    return redirect(url_for('register'))
                if self.user_repo.register_user(username, email, password):
                    flash('Реєстрація успішна! Увійдіть у систему.', 'success')
                    return redirect(url_for('login'))
                flash('Користувач із таким email або ім’ям вже існує!', 'error')
            return render_template('register.html')

        @self.app.route('/logout')
        def logout():
            session.pop('user_id', None)
            flash('Ви вийшли з системи.', 'info')
            return redirect(url_for('login'))

    def save_basic_data(self, request):
        """Зберігає основні дані користувача з валідацією."""
        date = request.form.get('date')
        age = request.form.get('age')
        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')

        # Перевіряємо, чи всі поля заповнені
        if not all([date, age, gender, weight, height]):
            flash('Усі поля обов’язкові!', 'error')
            return redirect(url_for('home', section='indicators'))

        # Валідація формату дати
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            flash('Невірний формат дати. Використовуйте РРРР-ММ-ДД.', 'error')
            return redirect(url_for('home', section='indicators'))

        # Валідація числових значень
        try:
            age = int(age)
            weight = float(weight)
            height = float(height)
            if age <= 0:
                raise ValueError("Вік має бути додатним числом.")
            if weight <= 0:
                raise ValueError("Вага має бути додатною.")
            if height <= 0:
                raise ValueError("Зріст має бути додатним.")
            if gender not in ['male', 'female']:
                raise ValueError("Стать має бути 'male' або 'female'.")
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('home', section='indicators'))

        self.db_repo.execute_query(
            '''INSERT INTO basic_data (user_id, date, age, gender, weight, height)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (session['user_id'], date, age, gender, weight, height)
        )
        flash('Основні дані успішно збережено.', 'success')
        return None

    def save_health_data(self, request):
        """Зберігає дані про здоров’я користувача з валідацією."""
        date = request.form.get('date')
        pulse = request.form.get('pulse')
        blood_pressure = request.form.get('blood_pressure')
        duration_sleep = request.form.get('duration_sleep')

        if not all([date, pulse, blood_pressure, duration_sleep]):
            flash('Усі поля обов’язкові!', 'error')
            return redirect(url_for('home', section='indicators'))

        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            flash('Невірний формат дати. Використовуйте РРРР-ММ-ДД.', 'error')
            return redirect(url_for('home', section='indicators'))

        try:
            pulse = int(pulse)
            duration_sleep = int(duration_sleep)
            systolic, diastolic = map(int, blood_pressure.split('/'))
            if pulse <= 0:
                raise ValueError("Пульс має бути додатним.")
            if duration_sleep <= 0:
                raise ValueError("Тривалість сну має бути додатною.")
            if systolic <= 0 or diastolic <= 0:
                raise ValueError("Тиск має бути додатним (наприклад, 120/80).")
        except (ValueError, TypeError) as e:
            flash(str(e) if str(e) else 'Невірний формат даних.', 'error')
            return redirect(url_for('home', section='indicators'))

        self.db_repo.execute_query(
            '''INSERT INTO health_data (user_id, date, pulse, blood_pressure, duration_sleep)
               VALUES (?, ?, ?, ?, ?)''',
            (session['user_id'], date, pulse, blood_pressure, duration_sleep)
        )
        flash('Показники здоров’я успішно збережено.', 'success')
        return None

    def save_activity_data(self, request):
        """Зберігає дані про активність користувача з валідацією."""
        date = request.form.get('date')
        activity_type = request.form.get('activity_type')
        duration = request.form.get('duration')
        water_intake = request.form.get('water_intake')

        if not all([date, activity_type, duration, water_intake]):
            flash('Усі поля обов’язкові!', 'error')
            return redirect(url_for('home', section='indicators'))

        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            flash('Невірний формат дати. Використовуйте РРРР-ММ-ДД.', 'error')
            return redirect(url_for('home', section='indicators'))

        try:
            duration = int(duration)
            water_intake = float(water_intake)
            if duration <= 0:
                raise ValueError("Тривалість має бути додатною.")
            if water_intake <= 0:
                raise ValueError("Кількість води має бути додатною.")
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('home', section='indicators'))

        self.db_repo.execute_query(
            '''INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake)
               VALUES (?, ?, ?, ?, ?)''',
            (session['user_id'], date, activity_type, duration, water_intake)
        )
        flash('Дані про активність успішно збережено.', 'success')
        return None

    def plot_metric_chart(self, metric_name: str, ylabel: str, color: str = 'blue') -> str:
        """Генерує графік метрики та повертає його у форматі base64."""
        metric_to_table = {
            'weight': 'basic_data',
            'pulse': 'health_data',
            'pressure': 'health_data',
            'sleep': 'health_data',
            'water_intake': 'activity_data'
        }
        column_map = {
            'weight': 'weight',
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
            f"SELECT date, {column} FROM {table} WHERE user_id = ? ORDER BY date",
            (session['user_id'],),
            fetchall=True
        )

        if not data or all(row[1] is None for row in data):
            return None

        dates = []
        values = []
        for row in data:
            date, value = row[0], row[1]
            if value is None:
                continue
            try:
                if metric_name == 'pressure':
                    val = float(value.split('/')[0]) if value else 0.0
                else:
                    val = float(value)
                # Фільтруємо від’ємні значення
                if val <= 0:
                    continue
                dates.append(date)
                values.append(val)
            except (ValueError, AttributeError):
                continue

        if not values or not dates:
            return None

        plt.figure(figsize=(8, 4))
        plt.plot(dates, values, marker='o', linestyle='-', color=color)
        plt.xlabel('Дата')
        plt.ylabel(ylabel)
        plt.title(f'Графік: {ylabel}')
        plt.grid(True)
        plt.xticks(rotation=45)

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()
        buf.close()

        return img_base64

    def run(self):
        """Запускає Flask-додаток."""
        self.app.run(debug=True, port=5001)

if __name__ == "__main__":
    app = HealthTrackerApp()
    app.run()