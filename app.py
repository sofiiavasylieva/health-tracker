from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3

class DatabaseManager:
    def __init__(self, db_name):
        self.db_name = db_name

    def execute_query(self, query, params=(), fetchone=False, fetchall=False):
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetchone:
                result = cursor.fetchone()
            elif fetchall:
                result = cursor.fetchall()
            else:
                result = None
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            result = None
        finally:
            conn.close()
        return result

    def initialize_db(self):
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        self.execute_query('''
            CREATE TABLE IF NOT EXISTS basic_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                age INTEGER,
                gender TEXT,
                weight REAL,
                height REAL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                UNIQUE(user_id)
            )
        ''')

        self.execute_query('''
            CREATE TABLE IF NOT EXISTS health_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                pulse INTEGER,
                blood_pressure TEXT,
                duration_sleep INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')

        self.execute_query('''
            CREATE TABLE IF NOT EXISTS activity_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity_type TEXT,
                duration INTEGER,
                water_intake REAL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')

class UserManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def get_user_by_email(self, email):
        return self.db_manager.execute_query(
            "SELECT * FROM users WHERE email = ?", (email,), fetchone=True
        )

    def register_user(self, username, email, password):
        try:
            self.db_manager.execute_query(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            return True
        except sqlite3.IntegrityError:
            return False

class HealthTrackerApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'your_secret_key'
        self.db_manager = DatabaseManager('health_tracker.db')
        self.user_manager = UserManager(self.db_manager)
        self.db_manager.initialize_db()
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/home', methods=['GET', 'POST'])
        def home():
            if 'user_id' not in session:
                return redirect(url_for('login'))

            section = request.args.get('section', 'welcome')
            user = self.db_manager.execute_query(
                "SELECT username FROM users WHERE id = ?", (session['user_id'],), fetchone=True
            )
            username = user[0] if user else 'Користувач'

            if request.method == 'POST':
                form_type = request.form.get('form_type')

                if form_type == 'basic_data':
                    self.save_basic_data(request)
                elif form_type == 'health_data':
                    self.save_health_data(request)
                elif form_type == 'activity_data':
                    self.save_activity_data(request)

            return render_template('home.html', username=username, section=section)

        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            error_email, error_password = None, None
            if request.method == 'POST':
                email, password = request.form['email'], request.form['password']
                user = self.user_manager.get_user_by_email(email)
                if user is None:
                    error_email = "User does not exist. Please register."
                elif user[3] != password:
                    error_password = "Invalid password."
                else:
                    session['user_id'] = user[0]
                    return redirect(url_for('home'))
            return render_template('login.html', error_email=error_email, error_password=error_password)

        @self.app.route('/register', methods=['GET', 'POST'])
        def register():
            if request.method == 'POST':
                username = request.form['username']
                email = request.form['email']
                password = request.form['password']
                if self.user_manager.register_user(username, email, password):
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
        self.db_manager.execute_query(
            '''INSERT INTO basic_data (user_id, age, gender, weight, height) VALUES (?, ?, ?, ?, ?)''',
            (
                session['user_id'],
                request.form.get('age'),
                request.form.get('gender'),
                request.form.get('weight'),
                request.form.get('height')
            )
        )
        flash('Основні дані успішно збережено.', 'success')

    def save_health_data(self, request):
        self.db_manager.execute_query(
            '''INSERT INTO health_data (user_id, pulse, blood_pressure, duration_sleep) VALUES (?, ?, ?, ?)''',
            (
                session['user_id'],
                request.form.get('pulse'),
                request.form.get('blood_pressure'),
                request.form.get('duration_sleep')
            )
        )
        flash('Показники здоров’я успішно збережено.', 'success')

    def save_activity_data(self, request):
        self.db_manager.execute_query(
            '''INSERT INTO activity_data (user_id, activity_type, duration, water_intake) VALUES (?, ?, ?, ?)''',
            (
                session['user_id'],
                request.form.get('activity_type'),
                request.form.get('duration'),
                request.form.get('water_intake')
            )
        )
        flash('Дані про активність успішно збережено.', 'success')

    def run(self):
        self.app.run(debug=True, port=5001)

if __name__ == "__main__":
    app = HealthTrackerApp()
    app.run()
