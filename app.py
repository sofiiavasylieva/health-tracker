import matplotlib
matplotlib.use('Agg')  # Використовуємо неінтерактивний бекенд для серверного рендерингу
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import io
import base64
import matplotlib.pyplot as plt
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any


# Абстрактний клас для калькуляторів (патерн Стратегія)
class Calculator(ABC):
    @abstractmethod
    def calculate(self, data: Dict[str, Any]) -> float:
        pass


class BMICalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        weight = float(data.get('weight', 0))
        height = float(data.get('height', 0))
        if height <= 0:
            raise ValueError("Height must be positive")
        return round(weight / ((height / 100) ** 2), 2)


class BodyFatCalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        gender = data.get('gender', 'male').lower()
        age = int(data.get('age', 0))
        chest = float(data.get('chest', 0))
        abdomen = float(data.get('abdomen', 0))
        thigh = float(data.get('thigh', 0))

        if chest <= 0 or abdomen <= 0 or thigh <= 0 or age <= 0:
            raise ValueError("All measurements and age must be positive")

        fat_result = 1.097 - (0.00046971 * (chest + abdomen + thigh)) + \
                     (0.00000056 * (chest + abdomen + thigh) ** 2) - \
                     (0.00012828 * age) - (5.4 if gender == 'female' else 0)
        return max(0, round(fat_result, 2))  # Корекція від'ємних значень


class CalorieCalculator(Calculator):
    def calculate(self, data: Dict[str, Any]) -> float:
        gender = data.get('gender', 'male').lower()
        weight = float(data.get('weight', 0))
        height = float(data.get('height', 0))
        age = int(data.get('age', 0))
        activity_level = float(data.get('activity_level', 0))
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

        # Список SQL-запитів для створення таблиць
        tables = [
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
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

        # Виконуємо створення таблиць, якщо їх немає
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
        """Реєструє нового користувача."""
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
        self.app.secret_key = 'your_secret_key_123'
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
                        self.save_basic_data(request)
                    elif form_type == 'health_data':
                        self.save_health_data(request)
                    elif form_type == 'activity_data':
                        self.save_activity_data(request)
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
                    error_email = "User does not exist. Please register."
                elif user[3] != password:
                    error_password = "Invalid password."
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
                if self.user_repo.register_user(username, email, password):
                    flash('Registration successful! You can now log in.', 'success')
                    return redirect(url_for('login'))
                flash('User with this email or username already exists!', 'error')
            return render_template('register.html')

        @self.app.route('/logout')
        def logout():
            session.pop('user_id', None)
            flash('You have been logged out.', 'info')
            return redirect(url_for('login'))

    def save_basic_data(self, request):
        """Зберігає основні дані користувача."""
        date = request.form.get('date')
        self.db_repo.execute_query(
            '''INSERT INTO basic_data (user_id, date, age, gender, weight, height)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                session['user_id'],
                date,
                request.form.get('age'),
                request.form.get('gender'),
                request.form.get('weight'),
                request.form.get('height')
            )
        )
        flash('Основні дані успішно збережено.', 'success')

    def save_health_data(self, request):
        """Зберігає дані про здоров’я користувача."""
        date = request.form.get('date')
        self.db_repo.execute_query(
            '''INSERT INTO health_data (user_id, date, pulse, blood_pressure, duration_sleep)
               VALUES (?, ?, ?, ?, ?)''',
            (
                session['user_id'],
                date,
                request.form.get('pulse'),
                request.form.get('blood_pressure'),
                request.form.get('duration_sleep')
            )
        )
        flash('Показники здоров’я успішно збережено.', 'success')

    def save_activity_data(self, request):
        """Зберігає дані про активність користувача."""
        date = request.form.get('date')
        self.db_repo.execute_query(
            '''INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake)
               VALUES (?, ?, ?, ?, ?)''',
            (
                session['user_id'],
                date,
                request.form.get('activity_type'),
                request.form.get('duration'),
                request.form.get('water_intake')
            )
        )
        flash('Дані про активність успішно збережено.', 'success')

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

        dates = [row[0] for row in data if row[1] is not None]
        values = []
        for row in data:
            value = row[1]
            if value is None:
                continue
            try:
                if metric_name == 'pressure':
                    values.append(float(value.split('/')[0]) if value else 0.0)
                else:
                    values.append(float(value))
            except (ValueError, AttributeError):
                values.append(0.0)

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