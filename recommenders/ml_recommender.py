import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import IsolationForest

BMI_UNDERWEIGHT = 18.5
BMI_NORMAL      = 25.0
BMI_OVERWEIGHT  = 30.0
SLEEP_MIN       = 7.0
SLEEP_CRITICAL  = 6.0
BP_ELEVATED     = 130
BP_HIGH         = 140
ANOMALY_MIN_PTS = 7       # мінімум точок для виявлення аномалій
TREND_MIN_PTS   = 3       # мінімум для регресії
N_CLUSTERS      = 3
FEATURES        = ['Age', 'BMI', 'Sleep_Hours', 'Resting_Heart_Rate', 'Systolic_BP', 'Activity_Score']


class MLRecommender:

    def __init__(self, csv_path):
        self.ready         = False
        self.kmeans        = None
        self.scaler        = None
        self.cluster_risk  = {}
        self.cluster_means = {}
        self._train(csv_path)

    def _train(self, csv_path):
        df = pd.read_csv(csv_path).dropna(subset=FEATURES)

        self.scaler = StandardScaler()
        X = self.scaler.fit_transform(df[FEATURES])

        self.kmeans   = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
        df['cluster'] = self.kmeans.fit_predict(X)

        means = df.groupby('cluster')['Risk_Label'].mean().sort_values()
        self.cluster_risk = {
            means.index[0]: 'low',
            means.index[1]: 'moderate',
            means.index[2]: 'high',
        }

        for cid in range(N_CLUSTERS):
            sub = df[df['cluster'] == cid]
            name = self.cluster_risk[cid]
            self.cluster_means[name] = {col: round(sub[col].mean(), 1) for col in FEATURES}

        self.ready = True
        print(f"MLRecommender: навчено на {len(df)} записах")

    # ── Кластер ────────────────────────────────────────────────────

    def _get_cluster(self, features):
        x = pd.DataFrame([[features.get(f, 0) for f in FEATURES]], columns=FEATURES)
        cid = self.kmeans.predict(self.scaler.transform(x))[0]
        return self.cluster_risk.get(cid, 'moderate')

    # ── Регресія — тренд і прогноз ─────────────────────────────────

    def _fit_trend(self, values, days_ahead=7):
        if len(values) < TREND_MIN_PTS:
            return None, None
        x = np.arange(len(values)).reshape(-1, 1)
        model = LinearRegression().fit(x, values)
        trend     = round(float(model.coef_[0]), 3)
        predicted = round(float(model.predict([[len(values) - 1 + days_ahead]])[0]), 1)
        return trend, predicted

    # ── Виявлення аномалій — IsolationForest на даних юзера ────────

    def _detect_anomalies(self, values):
        if len(values) < ANOMALY_MIN_PTS:
            return []
        X = np.array(values).reshape(-1, 1)
        model = IsolationForest(contamination=0.1, random_state=42)
        iso_labels = model.fit_predict(X)

        # Додатковий фільтр Z-score — показуємо тільки якщо відхилення > 2σ
        mean = np.mean(values)
        std  = np.std(values)
        if std == 0:
            return []

        anomalies = []
        for i, (label, val) in enumerate(zip(iso_labels, values)):
            if label == -1 and abs(val - mean) > 2 * std:
                anomalies.append(i)
        return anomalies

    def _activity_score(self, activity_level):
        mapping = {1.2: 1, 1.375: 2, 1.55: 3, 1.725: 4, 1.9: 4}
        closest = min(mapping, key=lambda k: abs(k - activity_level))
        return mapping[closest]

    # ── Головний метод ──────────────────────────────────────────────

    def generate(self, user_id, db):
        if not self.ready:
            return None

        user = db.execute_query(
            "SELECT age, gender, height, goal, activity_level FROM users WHERE id=?",
            (user_id,), fetchone=True
        )
        if not user:
            return None

        age, gender, height, goal, activity_level = user

        weight_rows = db.execute_query(
            "SELECT weight FROM basic_data WHERE user_id=? AND weight IS NOT NULL ORDER BY date ASC",
            (user_id,), fetchall=True
        )
        sleep_rows = db.execute_query(
            "SELECT duration_sleep FROM health_data WHERE user_id=? AND duration_sleep IS NOT NULL ORDER BY date ASC",
            (user_id,), fetchall=True
        )
        pulse_rows = db.execute_query(
            "SELECT pulse FROM health_data WHERE user_id=? AND pulse IS NOT NULL ORDER BY date ASC",
            (user_id,), fetchall=True
        )
        bp_rows = db.execute_query(
            "SELECT blood_pressure FROM health_data WHERE user_id=? AND blood_pressure IS NOT NULL ORDER BY date ASC",
            (user_id,), fetchall=True
        )

        weights  = [float(r[0]) for r in weight_rows] if weight_rows else []
        sleeps   = [float(r[0]) for r in sleep_rows]  if sleep_rows  else []
        pulses   = [int(r[0])   for r in pulse_rows]  if pulse_rows  else []
        systolics = []
        if bp_rows:
            for r in bp_rows:
                if r[0] and '/' in r[0]:
                    systolics.append(int(r[0].split('/')[0]))

        weight       = weights[-1]             if weights   else None
        avg_sleep    = round(np.mean(sleeps), 1) if sleeps  else None
        avg_pulse    = round(np.mean(pulses))    if pulses  else None
        avg_systolic = round(np.mean(systolics)) if systolics else None
        bmi          = round(weight / (height / 100) ** 2, 1) if weight and height else None

        act_score = self._activity_score(activity_level or 1.375)

        cluster     = self._get_cluster({
            'Age': age or 35, 'BMI': bmi or 25,
            'Sleep_Hours': avg_sleep or 7,
            'Resting_Heart_Rate': avg_pulse or 72,
            'Systolic_BP': avg_systolic or 120,
            'Activity_Score': act_score,
        })
        cluster_avg = self.cluster_means.get(cluster, {})
        parts = []

        # ── 1. Тренд і прогноз ваги ────────────────────────────────
        if weights:
            trend, predicted = self._fit_trend(weights)
            if trend is not None:
                weekly = round(trend * 7, 2)
                sign   = '+' if weekly > 0 else ''

                if goal == 'lose' and weekly < -0.05:
                    parts.append(
                        f"Вага знижується на {abs(weekly)} кг/тиждень — темп відповідає цілі. "
                        f"Прогноз через 7 днів: {predicted} кг."
                    )
                elif goal == 'lose' and weekly > 0.05:
                    parts.append(
                        f"Вага зростає на {weekly} кг/тиждень — це суперечить цілі схуднення. "
                        f"Прогноз через 7 днів: {predicted} кг."
                    )
                elif goal == 'gain' and weekly > 0.05:
                    parts.append(
                        f"Вага зростає на {weekly} кг/тиждень — відповідає цілі набору маси. "
                        f"Прогноз через 7 днів: {predicted} кг."
                    )
                else:
                    parts.append(
                        f"Тренд ваги: {sign}{weekly} кг/тиждень. Прогноз через 7 днів: {predicted} кг."
                    )

        # ── 2. Тренд сну ───────────────────────────────────────────
        if sleeps:
            sleep_trend, sleep_pred = self._fit_trend(sleeps)
            sleep_std = round(float(np.std(sleeps)), 1)
            cluster_sleep = cluster_avg.get('Sleep_Hours')

            if sleep_std > 1.5:
                parts.append(
                    f"Сон нестабільний: від {min(sleeps):.1f} до {max(sleeps):.1f} год "
                    f"(відхилення {sleep_std} год). Нерегулярний режим знижує якість відновлення."
                )
            elif sleep_trend is not None and sleep_trend < -0.1:
                weekly_sleep = round(sleep_trend * 7, 1)
                parts.append(
                    f"Тривалість сну скорочується на {abs(weekly_sleep)} год/тиждень. "
                    f"Прогноз через 7 днів: {sleep_pred} год — це нижче норми."
                )
            elif avg_sleep and cluster_sleep and avg_sleep < cluster_sleep - 0.5:
                parts.append(
                    f"Середній сон {avg_sleep} год — на {round(cluster_sleep - avg_sleep, 1)} год "
                    f"менше від середнього у вашій групі ({cluster_sleep} год)."
                )
            elif avg_sleep and avg_sleep < SLEEP_MIN:
                parts.append(f"Середній сон {avg_sleep} год — нижче рекомендованих 7 год.")

        # ── 3. Тренд тиску ─────────────────────────────────────────
        if systolics:
            bp_trend, bp_pred = self._fit_trend(systolics)
            if bp_trend is not None and bp_trend > 0.5:
                weekly_bp = round(bp_trend * 7, 1)
                parts.append(
                    f"Систолічний тиск зростає на {weekly_bp} мм рт.ст./тиждень. "
                    f"Прогноз через 7 днів: {bp_pred} мм рт.ст."
                    + (" Рекомендується консультація лікаря." if bp_pred and bp_pred >= BP_HIGH else "")
                )
            elif avg_systolic and avg_systolic >= BP_ELEVATED:
                cluster_bp = cluster_avg.get('Systolic_BP')
                if cluster_bp and avg_systolic > cluster_bp + 10:
                    parts.append(
                        f"Тиск {avg_systolic} мм рт.ст. — на {round(avg_systolic - cluster_bp)} "
                        f"вище середнього по вашій групі ({int(cluster_bp)} мм рт.ст.)."
                    )
                else:
                    parts.append(f"Середній тиск {avg_systolic} мм рт.ст. — підвищений.")

        # ── 4. Пульс — порівняння з кластером ─────────────────────
        if pulses and avg_pulse:
            cluster_pulse = cluster_avg.get('Resting_Heart_Rate')
            if cluster_pulse:
                diff = avg_pulse - cluster_pulse
                if diff > 8:
                    parts.append(
                        f"Пульс у спокої {avg_pulse} уд/хв — на {round(diff)} вище "
                        f"середнього для вашої групи ({int(cluster_pulse)} уд/хв). "
                        f"Рекомендуються регулярні кардіонавантаження."
                    )

        # ── 5. Аномалії — IsolationForest ─────────────────────────
        anomalies = []

        weight_anom = self._detect_anomalies(weights)
        if weight_anom:
            vals = [weights[i] for i in weight_anom]
            anomalies.append(f"вага ({', '.join(str(v) for v in vals)} кг)")

        pulse_anom = self._detect_anomalies(pulses)
        if pulse_anom:
            vals = [pulses[i] for i in pulse_anom]
            anomalies.append(f"пульс ({', '.join(str(v) for v in vals)} уд/хв)")

        bp_anom = self._detect_anomalies(systolics)
        if bp_anom:
            vals = [systolics[i] for i in bp_anom]
            anomalies.append(f"тиск ({', '.join(str(v) for v in vals)} мм рт.ст.)")

        sleep_anom = self._detect_anomalies(sleeps)
        if sleep_anom:
            vals = [round(sleeps[i], 1) for i in sleep_anom]
            anomalies.append(f"сон ({', '.join(str(v) for v in vals)} год)")

        if anomalies:
            parts.append(
                f"Виявлено нетипові значення: {'; '.join(anomalies)}. "
                f"Перевірте коректність введених даних або зверніть увагу на ці показники."
            )

        if not parts:
            return None

        return ' '.join(parts)