import unittest
from unittest.mock import patch, MagicMock
from app import HealthTrackerApp, BMICalculator, BodyFatCalculator, CalorieCalculator, UserRepository, DatabaseRepository
from flask import Flask, session

class TestHealthTracker(unittest.TestCase):
    def setUp(self):
        """Ініціалізація перед кожним тестом."""
        self.app = Flask(__name__)
        self.app.secret_key = 'test_key'
        self.health_tracker = HealthTrackerApp(self.app)  # Передача Flask-додатку
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

    def tearDown(self):
        """Очищення після кожного тесту."""
        self.client.__exit__(None, None, None)

    # Тести для калькуляторів
    def test_bmi_calculation(self):
        """Перевірка розрахунку ІМТ."""
        calc = BMICalculator()
        result = calc.calculate({'weight': '70', 'height': '170'})
        self.assertAlmostEqual(result, 24.22, places=2)

    def test_bmi_invalid_input(self):
        """Перевірка некоректних даних для ІМТ."""
        calc = BMICalculator()
        with self.assertRaises(ValueError):
            calc.calculate({'weight': '0', 'height': '170'})  # Нульова вага
        with self.assertRaises(ValueError):
            calc.calculate({'weight': '70', 'height': '0'})  # Нульова висота

    def test_body_fat_calculation(self):
        """Перевірка розрахунку відсотка жиру."""
        calc = BodyFatCalculator()
        result = calc.calculate({
            'gender': 'male',
            'age': '25',
            'chest': '95',
            'abdomen': '85',
            'thigh': '60'
        })
        self.assertAlmostEqual(result, 1.01, places=2)

    def test_calorie_calculation(self):
        """Перевірка розрахунку калорій."""
        calc = CalorieCalculator()
        result = calc.calculate({
            'gender': 'male',
            'weight': '70',
            'height': '170',
            'age': '25',
            'activity_level': '1.2'
        })
        self.assertAlmostEqual(result, 2039.83, places=2)

    # Тести для роботи з базою даних
    @patch('sqlite3.connect')
    def test_user_registration(self, mock_connect):
        """Перевірка реєстрації користувача."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        db_repo = DatabaseRepository('test.db')
        user_repo = UserRepository(db_repo)
        result = user_repo.register_user('testuser', 'test@example.com', 'password123')

        mock_cursor.execute.assert_called_with(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            ('testuser', 'test@example.com', 'password123')
        )
        mock_conn.commit.assert_called_once()
        self.assertTrue(result)

    @patch('sqlite3.connect')
    def test_save_health_data(self, mock_connect):
        """Перевірка збереження даних про здоров'я."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        request_data = MagicMock()
        request_data.form = {
            'date': '2025-05-17',
            'pulse': '72',
            'blood_pressure': '120/80',
            'duration_sleep': '7'
        }
        with patch.object(self.health_tracker.db_repo, 'execute_query') as mock_execute:
            self.health_tracker.save_health_data(request_data)
            mock_execute.assert_called_with(
                "INSERT INTO health_data (user_id, date, pulse, blood_pressure, duration_sleep) VALUES (?, ?, ?, ?, ?)",
                (1, '2025-05-17', 72, '120/80', 7)
            )

    # Тести для маршрутів Flask
    def test_login_route_success(self):
        """Перевірка успішного входу."""
        with self.client as c:
            with patch.object(self.health_tracker.user_repo, 'get_user_by_email', return_value=(1, 'testuser', 'test@example.com', 'password123')):
                response = c.post('/login', data={'email': 'test@example.com', 'password': 'password123'})
                self.assertEqual(response.status_code, 302)
                with c.session_transaction() as sess:
                    self.assertIn('user_id', sess)
                    self.assertEqual(sess['user_id'], 1)

    def test_login_route_failure(self):
        """Перевірка невдалого входу."""
        with self.client as c:
            with patch.object(self.health_tracker.user_repo, 'get_user_by_email', return_value=None):
                response = c.post('/login', data={'email': 'wrong@example.com', 'password': 'wrongpass'})
                self.assertEqual(response.status_code, 200)

    def test_profile_route(self):
        """Перевірка відображення профілю."""
        with self.client as c:
            with patch.object(self.health_tracker.db_repo, 'execute_query', return_value=('testuser', 'test@example.com')):
                with patch.object(self.health_tracker, 'plot_metric_chart', return_value='data:image/png;base64,fakebase64'):
                    response = c.get('/profile')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b'testuser', response.data)

    # Тести для генерації графіків
    @patch('matplotlib.pyplot.savefig')
    def test_plot_metric_chart(self, mock_savefig):
        """Перевірка генерації графіку."""
        with self.client as c:
            with patch.object(self.health_tracker.db_repo, 'execute_query', return_value=[
                ('2025-05-15', 70), ('2025-05-16', 71), ('2025-05-17', 70)
            ]):
                chart_data = self.health_tracker.plot_metric_chart('weight', 'Вага (кг)', user_id=1)
                self.assertTrue(chart_data.startswith('data:image/png;base64,'))
                mock_savefig.assert_called_once()

if __name__ == '__main__':
    unittest.main()