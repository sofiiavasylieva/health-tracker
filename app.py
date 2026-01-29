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
                password TEXT NOT NULL 
            )''',
            '''CREATE TABLE IF NOT EXISTS basic_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                age INTEGER,
                gender TEXT,
                weight REAL,
                height REAL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''',
            '''CREATE TABLE IF NOT EXISTS health_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                pulse INTEGER,
                blood_pressure TEXT,
                duration_sleep INTEGER,
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
                calculator_type TEXT NOT NULL,
                result REAL NOT NULL,
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

    def register_user(self, username: str, email: str, password: str) -> bool:
        try:
            self.db_repo.execute_query(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            return True
        except sqlite3.IntegrityError:
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
        self.setup_routes()

    def setup_routes(self):
        
        # dashboard 
        @self.app.route('/')
        @self.app.route('/dashboard')
        def dashboard():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            
            # Отримуємо ім'я користувача
            user = self.db_repo.execute_query(
                "SELECT username FROM users WHERE id = ?", (session['user_id'],), fetchone=True
            )
            username = user[0] if user else 'Користувач'

            # Генерація графіків
            chart_data = {}
            metrics = [
                {'id': 'weight', 'label': 'Вага (кг)', 'color': '#499BED'},      
                {'id': 'pulse', 'label': 'Пульс (уд/хв)', 'color': '#ef4444'},   
                {'id': 'sleep', 'label': 'Сон (год)', 'color': '#022E5B'},       
                {'id': 'pressure', 'label': 'Тиск', 'color': '#f59e0b'},         
                {'id': 'water_intake', 'label': 'Вода (л)', 'color': '#06b6d4'}
            ]
            
            for metric in metrics:
                chart_data[metric['id']] = self.plot_metric_chart(
                    metric['id'], metric['label'], metric['color']
                )

            return render_template('dashboard.html', username=username, chart_data=chart_data, page='dashboard')

        # tracker
        @self.app.route('/tracker', methods=['GET', 'POST'])
        def tracker():
            if 'user_id' not in session:
                return redirect(url_for('login'))

            bmi_result, fat_result, calorie_result = None, None, None

            if request.method == 'POST':
                form_type = request.form.get('form_type')
                
                # Обробка форм введення даних
                if form_type == 'basic_data':
                    self.save_basic_data(request)
                elif form_type == 'health_data':
                    self.save_health_data(request)
                elif form_type == 'activity_data':
                    self.save_activity_data(request)
                
                # Обробка калькуляторів
                elif form_type == 'calculator':
                    calc_type = request.form.get('calculator_type')
                    if calc_type in self.calculators:
                        try:
                            calculator = self.calculators[calc_type]
                            result = calculator.calculate(request.form)
                            self.db_repo.execute_query(
                                "INSERT INTO calculator_results (user_id, calculator_type, result) VALUES (?, ?, ?)",
                                (session['user_id'], calc_type, result)
                            )
                            if calc_type == 'bmi':
                                bmi_result = result
                            elif calc_type == 'body_fat':
                                fat_result = result
                            elif calc_type == 'calories':
                                calorie_result = result
                            flash(f'Результат розрахунку: {result}', 'success')
                        except ValueError as e:
                            flash(str(e), 'error')
                
                # Якщо це не калькулятор, робимо редірект, щоб очистити форму
                if form_type != 'calculator':
                    return redirect(url_for('tracker'))

            return render_template('tracker.html', 
                                   page='tracker',
                                   bmi_result=bmi_result,
                                   fat_result=fat_result,
                                   calorie_result=calorie_result)

        # agent
        @self.app.route('/ai-agent')
        def ai_agent():
            if 'user_id' not in session:
                return redirect(url_for('login'))
            return render_template('ai_agent.html', page='ai_agent')



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
                    return redirect(url_for('dashboard'))
            return render_template('login.html', error_email=error_email, error_password=error_password)

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
        date = request.form.get('date')
        age = request.form.get('age')
        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')

        if not all([date, age, gender, weight, height]):
            flash('Усі поля обов’язкові!', 'error')
            return

        try:
            datetime.strptime(date, '%Y-%m-%d')
            age = int(age)
            weight = float(weight)
            height = float(height)
            if any(x <= 0 for x in [age, weight, height]):
                raise ValueError
        except ValueError:
            flash('Невірні дані.', 'error')
            return

        self.db_repo.execute_query(
            '''INSERT INTO basic_data (user_id, date, age, gender, weight, height)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (session['user_id'], date, age, gender, weight, height)
        )
        flash('Основні дані збережено.', 'success')

    def save_health_data(self, request):
        date = request.form.get('date')
        pulse = request.form.get('pulse')
        blood_pressure = request.form.get('blood_pressure')
        duration_sleep = request.form.get('duration_sleep')

        if not all([date, pulse, blood_pressure, duration_sleep]):
            flash('Усі поля обов’язкові!', 'error')
            return

        try:
            datetime.strptime(date, '%Y-%m-%d')
            pulse = int(pulse)
            duration_sleep = int(duration_sleep)
            if pulse <= 0 or duration_sleep <= 0: raise ValueError
        except ValueError:
            flash('Невірні дані.', 'error')
            return

        self.db_repo.execute_query(
            '''INSERT INTO health_data (user_id, date, pulse, blood_pressure, duration_sleep)
               VALUES (?, ?, ?, ?, ?)''',
            (session['user_id'], date, pulse, blood_pressure, duration_sleep)
        )
        flash('Показники здоров’я збережено.', 'success')

    def save_activity_data(self, request):
        date = request.form.get('date')
        activity_type = request.form.get('activity_type')
        duration = request.form.get('duration')
        water_intake = request.form.get('water_intake')

        if not all([date, activity_type, duration, water_intake]):
            flash('Усі поля обов’язкові!', 'error')
            return

        try:
            datetime.strptime(date, '%Y-%m-%d')
            duration = int(duration)
            water_intake = float(water_intake)
            if duration <= 0 or water_intake < 0: raise ValueError
        except ValueError:
            flash('Невірні дані.', 'error')
            return

        self.db_repo.execute_query(
            '''INSERT INTO activity_data (user_id, date, activity_type, duration, water_intake)
               VALUES (?, ?, ?, ?, ?)''',
            (session['user_id'], date, activity_type, duration, water_intake)
        )
        flash('Активність збережено.', 'success')

    def plot_metric_chart(self, metric_name: str, ylabel: str, color: str = '#499BED') -> Optional[str]:
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
            f"SELECT date, {column} FROM {table} WHERE user_id = ? ORDER BY date DESC LIMIT 10",
            (session['user_id'],),
            fetchall=True
        )

        if not data or all(row[1] is None for row in data):
            return None

        data.reverse() 

        dates = []
        values = []
        for row in data:
            date_str, value = row[0], row[1]
            if value is None:
                continue
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')

                if metric_name == 'pressure':
                    val = float(value.split('/')[0]) if value else 0.0
                else:
                    val = float(value)
                if val <= 0: continue
                dates.append(dt)
                values.append(val)
            except (ValueError, AttributeError):
                continue

        if not values or not dates:
            return None

        # 3. Побудова графіка
        plt.figure(figsize=(10, 5))
        ax = plt.gca()
        plt.plot(dates, values, 
                 color=color, 
                 linewidth=3,     
                 marker='o',       
                 markersize=8, 
                 markerfacecolor='white',
                 markeredgewidth=2,       
                 label=ylabel)
        
        # Заливка під графіком
        plt.fill_between(dates, values, color=color, alpha=0.1)
        
        # Стилізація сітки та рамок
        plt.grid(axis='y', linestyle='--', alpha=0.3, color='#94a3b8')
        plt.grid(axis='x', visible=False)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_color('#cbd5e1')
        
        # Заголовок (один раз!)
        plt.title(ylabel, fontsize=14, fontweight='bold', color='#1e293b', loc='left', pad=15)
        
        # Форматування дат (День.Місяць)
        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
        plt.xticks(fontsize=10, color='#64748b')
        plt.yticks(fontsize=10, color='#64748b')
        
        # Прибираємо зайві засічки
        ax.tick_params(axis='both', which='both', length=0)

        # Збереження
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', transparent=True, dpi=100)
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()
        buf.close()

        return img_base64

    def run(self):
        self.app.run(debug=True, port=5001)

if __name__ == "__main__":
    app = HealthTrackerApp()
    app.run()