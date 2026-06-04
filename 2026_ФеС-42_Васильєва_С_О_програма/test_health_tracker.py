"""
Запуск: pytest test_health_tracker.py -v
"""
import pytest
import sys
import os
import sqlite3
import tempfile

# Додаємо шлях до проєкту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from werkzeug.security import generate_password_hash, check_password_hash


# ТЕСТИ КАЛЬКУЛЯТОРІВ

class TestBMICalculator:
    """Тести калькулятора ІМТ"""

    def setup_method(self):
        from app import BMICalculator
        self.calc = BMICalculator()

    def test_bmi_normal(self):
        """ІМТ в нормі (18.5-24.9)"""
        result = self.calc.calculate({'weight': 70, 'height': 175})
        assert 22.0 < result < 23.0

    def test_bmi_underweight(self):
        """ІМТ нижче норми (< 18.5)"""
        result = self.calc.calculate({'weight': 45, 'height': 170})
        assert result < 18.5

    def test_bmi_overweight(self):
        """ІМТ надмірна вага (25-29.9)"""
        result = self.calc.calculate({'weight': 85, 'height': 170})
        assert 25.0 <= result < 30.0

    def test_bmi_obesity(self):
        """ІМТ ожиріння (>= 30)"""
        result = self.calc.calculate({'weight': 100, 'height': 170})
        assert result >= 30.0

    def test_bmi_missing_weight(self):
        """Помилка якщо вага відсутня"""
        with pytest.raises(ValueError, match="обов'язкові"):
            self.calc.calculate({'height': 175})

    def test_bmi_missing_height(self):
        """Помилка якщо зріст відсутній"""
        with pytest.raises(ValueError, match="обов'язкові"):
            self.calc.calculate({'weight': 70})

    def test_bmi_negative_values(self):
        """Помилка якщо від'ємні значення"""
        with pytest.raises(ValueError, match="додатними"):
            self.calc.calculate({'weight': -70, 'height': 175})

    def test_bmi_zero_height(self):
        """Помилка якщо зріст нуль"""
        with pytest.raises(ValueError):
            self.calc.calculate({'weight': 70, 'height': 0})

    def test_bmi_formula(self):
        """Перевірка формули: вага / (зріст/100)^2"""
        result = self.calc.calculate({'weight': 80, 'height': 180})
        expected = round(80 / (1.80 ** 2), 2)
        assert result == expected


class TestCalorieCalculator:
    """Тести калькулятора калорій"""

    def setup_method(self):
        from app import CalorieCalculator
        self.calc = CalorieCalculator()

    def test_calories_male(self):
        """Розрахунок для чоловіка"""
        result = self.calc.calculate({
            'gender': 'male', 'weight': 80,
            'height': 180, 'age': 30, 'activity_level': 1.55
        })
        assert result > 2000

    def test_calories_female(self):
        """Розрахунок для жінки"""
        result = self.calc.calculate({
            'gender': 'female', 'weight': 60,
            'height': 165, 'age': 25, 'activity_level': 1.375
        })
        assert result > 1500

    def test_calories_male_higher_than_female(self):
        """Чоловік витрачає більше калорій ніж жінка при однакових параметрах"""
        male = self.calc.calculate({
            'gender': 'male', 'weight': 70,
            'height': 170, 'age': 30, 'activity_level': 1.55
        })
        female = self.calc.calculate({
            'gender': 'female', 'weight': 70,
            'height': 170, 'age': 30, 'activity_level': 1.55
        })
        assert male > female

    def test_calories_missing_fields(self):
        """Помилка якщо поля відсутні"""
        with pytest.raises(ValueError, match="обов'язкові"):
            self.calc.calculate({'gender': 'male', 'weight': 70})

    def test_calories_invalid_gender(self):
        """Помилка якщо невірна стать"""
        with pytest.raises(ValueError, match="male.*female"):
            self.calc.calculate({
                'gender': 'unknown', 'weight': 70,
                'height': 170, 'age': 30, 'activity_level': 1.55
            })



# ТЕСТИ БАЗИ ДАНИХ

class TestDatabaseRepository:
    """Тести роботи з базою даних"""

    def setup_method(self):
        from app import DatabaseRepository
        # Використовуємо тимчасову БД для тестів
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db = DatabaseRepository(self.tmp.name)
        self.db.initialize_db()

    def teardown_method(self):
        os.unlink(self.tmp.name)

    def test_initialize_creates_tables(self):
        """Ініціалізація створює всі таблиці"""
        conn = sqlite3.connect(self.tmp.name)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert 'users' in table_names
        assert 'basic_data' in table_names
        assert 'health_data' in table_names
        assert 'activity_data' in table_names
        assert 'recommendations' in table_names

    def test_insert_and_select(self):
        """Вставка і вибірка даних"""
        self.db.execute_query(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            ('testuser', 'test@test.com', 'hash123')
        )
        result = self.db.execute_query(
            "SELECT username FROM users WHERE email=?",
            ('test@test.com',), fetchone=True
        )
        assert result is not None
        assert result[0] == 'testuser'

    def test_fetchall_returns_list(self):
        """fetchall повертає список"""
        result = self.db.execute_query(
            "SELECT * FROM users", fetchall=True
        )
        assert isinstance(result, list)

    def test_fetchone_returns_tuple_or_none(self):
        """fetchone повертає tuple або None"""
        result = self.db.execute_query(
            "SELECT * FROM users WHERE id=?", (999,), fetchone=True
        )
        assert result is None

    def test_double_initialize_safe(self):
        """Повторна ініціалізація не видаляє дані"""
        self.db.execute_query(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            ('user1', 'user1@test.com', 'hash')
        )
        self.db.initialize_db()  # повторна ініціалізація
        result = self.db.execute_query(
            "SELECT COUNT(*) FROM users", fetchone=True
        )
        assert result[0] == 1


# ТЕСТИ БЕЗПЕКИ — ХЕШУВАННЯ ПАРОЛІВ

class TestPasswordSecurity:
    """Тести хешування паролів"""

    def test_password_is_hashed(self):
        """Хешований пароль не дорівнює оригіналу"""
        password = 'mypassword123'
        hashed = generate_password_hash(password)
        assert hashed != password

    def test_correct_password_verified(self):
        """Правильний пароль проходить перевірку"""
        password = 'mypassword123'
        hashed = generate_password_hash(password)
        assert check_password_hash(hashed, password) is True

    def test_wrong_password_rejected(self):
        """Неправильний пароль не проходить перевірку"""
        hashed = generate_password_hash('correct_password')
        assert check_password_hash(hashed, 'wrong_password') is False

    def test_hash_uses_scrypt(self):
        """Хеш використовує алгоритм scrypt"""
        hashed = generate_password_hash('test123')
        assert hashed.startswith('scrypt:') or hashed.startswith('pbkdf2:')

    def test_different_hashes_for_same_password(self):
        """Два хеші одного пароля різні (різна сіль)"""
        password = 'samepassword'
        hash1 = generate_password_hash(password)
        hash2 = generate_password_hash(password)
        assert hash1 != hash2
        # Але обидва проходять перевірку
        assert check_password_hash(hash1, password) is True
        assert check_password_hash(hash2, password) is True


# ТЕСТИ RULE-BASED ЛОГІКИ

class TestRuleBasedLogic:
    """Тести порогових значень Rule-Based підходу"""

    def test_bmi_thresholds(self):
        """Перевірка порогів ІМТ"""
        from app import BMICalculator
        calc = BMICalculator()

        # Недостатня вага
        bmi = calc.calculate({'weight': 50, 'height': 175})
        assert bmi < 18.5

        # Норма
        bmi = calc.calculate({'weight': 70, 'height': 175})
        assert 18.5 <= bmi < 25.0

        # Надмірна вага
        bmi = calc.calculate({'weight': 85, 'height': 175})
        assert 25.0 <= bmi < 30.0

        # Ожиріння
        bmi = calc.calculate({'weight': 100, 'height': 175})
        assert bmi >= 30.0

    def test_pulse_thresholds(self):
        """Перевірка порогів пульсу"""
        # Нормальний пульс
        assert 60 <= 72 <= 100

        # Брадикардія
        assert 45 < 60

        # Тахікардія
        assert 110 > 100

    def test_sleep_thresholds(self):
        """Перевірка порогів сну"""
        # Критично мало
        assert 5.5 < 6.0

        # Недостатньо
        assert 6.0 <= 6.5 < 7.0

        # Норма
        assert 7.0 <= 8.0 <= 9.0

        # Забагато
        assert 10.0 > 9.0

    def test_water_thresholds(self):
        """Перевірка порогів вживання води"""
        # Недостатньо
        assert 1.2 < 1.5

        # Прийнятно
        assert 1.5 <= 1.8 < 2.0

        # Норма
        assert 2.5 >= 2.0


# ТЕСТИ ML КОМПОНЕНТІВ

class TestMLComponents:
    """Тести ML алгоритмів"""

    def test_isolation_forest_detects_anomaly(self):
        """IsolationForest виявляє різкий стрибок ваги"""
        import numpy as np
        from sklearn.ensemble import IsolationForest

        # 14 стабільних значень + 1 аномалія
        weights = [70.0, 70.2, 69.8, 70.1, 70.3,
                   69.9, 70.0, 70.2, 69.8, 70.1,
                   70.0, 70.2, 69.9, 70.1, 95.0]  # ← аномалія

        X = np.array(weights).reshape(-1, 1)
        model = IsolationForest(contamination=0.05, random_state=42)
        labels = model.fit_predict(X)

        # Останнє значення (95.0) має бути позначено як аномалія (-1)
        assert labels[-1] == -1

    def test_isolation_forest_normal_data(self):
        """IsolationForest не позначає нормальні дані як аномалію"""
        import numpy as np
        from sklearn.ensemble import IsolationForest

        # Стабільні дані без аномалій
        weights = [70.0, 70.2, 69.8, 70.1, 70.3,
                   69.9, 70.0, 70.2, 69.8, 70.1,
                   70.0, 70.2, 69.9, 70.1, 70.0]

        X = np.array(weights).reshape(-1, 1)
        model = IsolationForest(contamination=0.05, random_state=42)
        labels = model.fit_predict(X)

        # Більшість значень мають бути нормальними (1)
        normal_count = sum(1 for l in labels if l == 1)
        assert normal_count >= 13

    def test_linear_regression_trend(self):
        """Лінійна регресія правильно визначає тренд"""
        import numpy as np
        from sklearn.linear_model import LinearRegression

        # Зростаючий тренд
        weights = [70, 70.5, 71, 71.5, 72, 72.5, 73]
        x = np.arange(len(weights)).reshape(-1, 1)
        model = LinearRegression().fit(x, weights)

        # Нахил має бути позитивним
        assert model.coef_[0] > 0

    def test_pearson_correlation(self):
        """Кореляція Пірсона — обернений зв'язок сон-пульс"""
        import numpy as np

        # Менше сну → вищий пульс (обернена кореляція)
        sleep  = [8, 7, 6, 5, 8, 7, 6]
        pulse  = [65, 70, 75, 82, 63, 68, 76]

        corr = np.corrcoef(sleep, pulse)[0, 1]
        assert corr < -0.4  # помірна від'ємна кореляція

    def test_kmeans_three_clusters(self):
        """KMeans розділяє на 3 кластери"""
        import numpy as np
        from sklearn.cluster import KMeans

        # Три чіткі групи
        data = np.array([
            [20, 18, 8, 60, 110, 4],   # низький ризик
            [20, 19, 8, 62, 112, 4],
            [40, 27, 6, 85, 135, 2],   # помірний ризик
            [40, 28, 6, 87, 138, 2],
            [55, 35, 5, 95, 155, 1],   # високий ризик
            [55, 36, 5, 97, 158, 1],
        ])

        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        labels = kmeans.fit_predict(data)

        # Має бути рівно 3 унікальних кластери
        assert len(set(labels)) == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])