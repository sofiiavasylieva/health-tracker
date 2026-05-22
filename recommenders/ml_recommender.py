import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import IsolationForest

# Медичні межі для аномалій
MEDICAL_BOUNDS = {
    'pulse':    (50, 100),
    'systolic': (80, 145),
    'sleep':    (4.0, 11.0),
}

SLEEP_MIN    = 7.0
SLEEP_CRIT   = 6.0
BP_ELEVATED  = 130
BP_HIGH      = 140
ANOMALY_PTS  = 7
TREND_PTS    = 3
N_CLUSTERS   = 3
FEATURES     = ['Age', 'BMI', 'Sleep_Hours', 'Resting_Heart_Rate', 'Systolic_BP', 'Activity_Score']


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
            sub  = df[df['cluster'] == cid]
            name = self.cluster_risk[cid]
            self.cluster_means[name] = {col: round(sub[col].mean(), 1) for col in FEATURES}

        self.ready = True
        print(f"MLRecommender: навчено на {len(df)} записах")

    def _get_cluster(self, features):
        x = pd.DataFrame([[features.get(f, 0) for f in FEATURES]], columns=FEATURES)
        cid = self.kmeans.predict(self.scaler.transform(x))[0]
        return self.cluster_risk.get(cid, 'moderate')

    def _fit_trend(self, values, days_ahead=7):
        if len(values) < TREND_PTS:
            return None, None
        x         = np.arange(len(values)).reshape(-1, 1)
        model     = LinearRegression().fit(x, values)
        trend     = round(float(model.coef_[0]), 3)
        predicted = round(float(model.predict([[len(values) - 1 + days_ahead]])[0]), 1)
        if abs(trend * 7) > 3.0:
            return trend, None
        return trend, predicted

    def _activity_score(self, activity_level):
        mapping = {1.2: 1, 1.375: 2, 1.55: 3, 1.725: 4, 1.9: 4}
        return mapping[min(mapping, key=lambda k: abs(k - activity_level))]

    def _anomaly_indices(self, values, metric):
        if len(values) < ANOMALY_PTS:
            return []
        lo, hi = MEDICAL_BOUNDS.get(metric, (None, None))
        X      = np.array(values).reshape(-1, 1)
        labels = IsolationForest(contamination=0.1, random_state=42).fit_predict(X)
        mean, std = np.mean(values), np.std(values)
        if std == 0:
            return []
        result = []
        for i, (label, v) in enumerate(zip(labels, values)):
            stat_out = label == -1 and abs(v - mean) > 2 * std
            med_out  = (lo is not None and v < lo) or (hi is not None and v > hi)
            if stat_out and med_out:
                result.append((i, round(v, 1)))
        return result

    def generate(self, user_id, db):
        if not self.ready:
            return {}

        user = db.execute_query(
            "SELECT age, gender, height, goal, activity_level FROM users WHERE id=?",
            (user_id,), fetchone=True
        )
        if not user:
            return {}

        age, gender, height, goal, activity_level = user

        weight_rows = db.execute_query(
            "SELECT weight FROM basic_data WHERE user_id=? AND weight IS NOT NULL ORDER BY date DESC LIMIT 7",
            (user_id,), fetchall=True
        )
        sleep_rows = db.execute_query(
            "SELECT duration_sleep FROM health_data WHERE user_id=? AND duration_sleep IS NOT NULL ORDER BY date DESC, id DESC LIMIT 14",
            (user_id,), fetchall=True
        )
        pulse_rows = db.execute_query(
            "SELECT pulse FROM health_data WHERE user_id=? AND pulse IS NOT NULL ORDER BY date DESC, id DESC LIMIT 14",
            (user_id,), fetchall=True
        )
        bp_rows = db.execute_query(
            "SELECT blood_pressure FROM health_data WHERE user_id=? AND blood_pressure IS NOT NULL ORDER BY date DESC, id DESC LIMIT 14",
            (user_id,), fetchall=True
        )

        water_rows = db.execute_query(
            "SELECT water_intake FROM activity_data WHERE user_id=? AND water_intake IS NOT NULL ORDER BY date DESC LIMIT 14",
            (user_id,), fetchall=True
        )

        weights   = list(reversed([float(r[0]) for r in weight_rows]))  if weight_rows else []
        sleeps    = list(reversed([float(r[0]) for r in sleep_rows]))   if sleep_rows  else []
        pulses    = list(reversed([int(r[0])   for r in pulse_rows]))   if pulse_rows  else []
        systolics = []
        if bp_rows:
            for r in reversed(bp_rows):
                if r[0] and '/' in r[0]:
                    systolics.append(int(r[0].split('/')[0]))

        waters    = list(reversed([float(r[0]) for r in water_rows])) if water_rows else []
        avg_water = round(float(np.mean(waters)), 2) if waters else None

        weight       = weights[-1]                            if weights   else None
        last_sleep   = sleeps[-1]                             if sleeps    else None
        avg_sleep    = round(np.mean(sleeps), 1)              if sleeps    else None
        last_pulse   = pulses[-1]                             if pulses    else None
        avg_pulse    = round(np.mean(pulses))                 if pulses    else None
        last_sys     = systolics[-1]                          if systolics else None
        avg_systolic = round(np.mean(systolics))              if systolics else None
        bmi          = round(weight / (height / 100) ** 2, 1) if weight and height else None
        act_score    = self._activity_score(activity_level or 1.375)

        cluster     = self._get_cluster({
            'Age': age or 35, 'BMI': bmi or 25,
            'Sleep_Hours': avg_sleep or 7,
            'Resting_Heart_Rate': avg_pulse or 72,
            'Systolic_BP': avg_systolic or 120,
            'Activity_Score': act_score,
        })
        cavg = self.cluster_means.get(cluster, {})

        # Попередній кластер — беремо з першої половини даних
        prev_cluster = None
        if len(sleeps) >= 6 and len(pulses) >= 6:
            half_sleep = round(float(np.mean(sleeps[:len(sleeps)//2])), 1)
            half_pulse = round(np.mean(pulses[:len(pulses)//2]))
            half_sys   = round(np.mean(systolics[:len(systolics)//2])) if len(systolics) >= 4 else (avg_systolic or 120)
            prev_cluster = self._get_cluster({
                'Age': age or 35, 'BMI': bmi or 25,
                'Sleep_Hours': half_sleep,
                'Resting_Heart_Rate': half_pulse,
                'Systolic_BP': half_sys,
                'Activity_Score': act_score,
            })

        results = {}

        # ──  ВАГА: тренд + прогноз + відхилення від цілі ────────
        if weights:
            trend, predicted = self._fit_trend(weights)
            parts = []

            if trend is not None:
                weekly = round(trend * 7, 2)
                sign   = '+' if weekly > 0 else ''

                # Фізіологічно неможливий тренд — не показуємо
                if abs(weekly) > 3.0:
                    parts.append("Недостатньо стабільних даних для визначення тренду ваги.")
                elif goal == 'lose':
                    if weekly > 0.1:
                        parts.append(f"Вага зростає на {weekly} кг/тиждень — суперечить цілі схуднення.")
                    elif weekly < -0.05:
                        parts.append(f"Вага знижується на {abs(weekly)} кг/тиждень — темп відповідає цілі.")
                    else:
                        parts.append("Вага стабільна — прогресу до цілі немає.")
                elif goal == 'gain':
                    if weekly < -0.05:
                        parts.append(f"Вага знижується — суперечить цілі набору маси.")
                    elif weekly > 0.05:
                        parts.append(f"Вага зростає на {weekly} кг/тиждень — відповідає цілі.")
                    else:
                        parts.append("Вага стабільна.")
                else:
                    parts.append(f"Тренд ваги: {sign}{weekly} кг/тиждень.")

                if predicted:
                    parts.append(f"Прогноз через 7 днів: {predicted} кг.")

            anom = self._anomaly_indices(weights, 'weight')
            if anom:
                vals = ', '.join(str(v) for _, v in anom)
                parts.append(f"Виявлено нетипові значення: {vals} кг.")

            if parts:
                results['weight'] = ' '.join(parts)

        # ── СОН ────────────────────────────────────────────────
        if sleeps:
            cluster_sleep = cavg.get('Sleep_Hours')
            sleep_trend, _ = self._fit_trend(sleeps)
            own_avg = round(float(np.mean(sleeps[:-1])), 1) if len(sleeps) >= 2 else None
            diff_own = round(last_sleep - own_avg, 1) if own_avg else None
            msg = None

            # Пріоритет 1: критичне медичне відхилення
            if last_sleep < SLEEP_CRIT:
                msg = f"Сон {last_sleep} год — критично мало. Хронічне недосипання підвищує пульс і знижує імунітет."
            # Пріоритет 2: значне відхилення від особистої норми
            elif own_avg and diff_own is not None and abs(diff_own) >= 1.0:
                direction = "менше" if diff_own < 0 else "більше"
                status = "нижче рекомендованих 7 год — " if last_sleep < SLEEP_MIN else ""
                msg = f"Сьогодні {last_sleep} год сну — на {abs(diff_own)} год {direction} вашого звичного показника ({own_avg} год). {status}Рекомендується стабільний режим."
            # Пріоритет 3: нижче медичної норми без особистих даних
            elif last_sleep < SLEEP_MIN:
                cluster_ctx = f" Для людей вашого профілю норма — {cluster_sleep} год." if cluster_sleep else ""
                msg = f"Сон {last_sleep} год — нижче рекомендованих 7 год.{cluster_ctx}"
            # Пріоритет 4: норма, але є цікавий кластерний інсайт
            elif cluster_sleep and avg_sleep:
                diff_cl = round(avg_sleep - cluster_sleep, 1)
                if diff_cl > 0.8:
                    msg = f"Ваш середній сон {avg_sleep} год — на {diff_cl} год більше норми людей вашого профілю ({cluster_sleep} год). Це позитивно."
                else:
                    msg = f"Сон {avg_sleep} год — в межах норми. Продовжуйте підтримувати режим."
            else:
                msg = f"Сон {last_sleep} год — в межах норми."

            # Додаємо тренд якщо є критичне падіння
            if sleep_trend and sleep_trend < -0.2:
                weekly_sl = round(abs(sleep_trend * 7), 1)
                msg += f" Увага: сон скорочується на {weekly_sl} год/тиждень."

            if msg:
                results['sleep'] = msg

        # ── ПУЛЬС ───────────────────────────────────────────────
        if pulses:
            cluster_pulse = cavg.get('Resting_Heart_Rate')
            own_avg_p = round(float(np.mean(pulses[:-1]))) if len(pulses) >= 2 else None
            diff_own_p = last_pulse - own_avg_p if own_avg_p else None
            msg = None

            # Пріоритет 1: медична аномалія
            if last_pulse > MEDICAL_BOUNDS['pulse'][1]:
                msg = f"Пульс {last_pulse} уд/хв — тахікардія (норма до 100). Уникайте кофеїну та стресу, зверніться до лікаря."
            elif last_pulse < MEDICAL_BOUNDS['pulse'][0]:
                msg = f"Пульс {last_pulse} уд/хв — нижче норми (брадикардія). Зверніться до лікаря."
            # Пріоритет 2: значне відхилення від особистого показника
            elif own_avg_p and diff_own_p is not None and abs(diff_own_p) >= 8:
                direction = "вище" if diff_own_p > 0 else "нижче"
                cause = " Можливо, вплив стресу або підвищеного навантаження." if diff_own_p > 0 else ""
                msg = f"Пульс {last_pulse} уд/хв — на {abs(diff_own_p)} уд/хв {direction} вашого звичного ({own_avg_p} уд/хв).{cause}"
            # Пріоритет 3: порівняння з кластером
            elif cluster_pulse and avg_pulse:
                diff_cl = round(avg_pulse - cluster_pulse)
                if diff_cl > 6:
                    msg = (f"Середній пульс {avg_pulse} уд/хв — на {diff_cl} уд/хв вище норми "
                           f"для людей вашого профілю ({int(cluster_pulse)} уд/хв). "
                           f"Регулярне кардіо допоможе його знизити.")
                elif diff_cl < -6:
                    msg = (f"Пульс {avg_pulse} уд/хв — нижче середнього по вашій групі "
                           f"({int(cluster_pulse)} уд/хв). Це ознака доброї серцевої форми.")
                else:
                    msg = f"Пульс у спокої {avg_pulse} уд/хв — в нормі для вашого профілю ({int(cluster_pulse)} уд/хв)."
            else:
                msg = f"Пульс {last_pulse} уд/хв — в межах норми."

            if msg:
                results['pulse'] = msg

        # ── ТИСК ────────────────────────────────────────────────
        if systolics:
            bp_trend, bp_pred = self._fit_trend(systolics)
            weekly_bp = round(bp_trend * 7, 1) if bp_trend else None
            msg = None

            # Пріоритет 1: критично підвищений
            if last_sys and last_sys >= BP_HIGH:
                trend_ctx = f" Тренд: зростає на {weekly_bp} мм/тиждень." if weekly_bp and weekly_bp > 0 else ""
                msg = f"Тиск {last_sys} мм рт.ст. — підвищений (норма до 130).{trend_ctx} Обмежте сіль, зверніться до лікаря."
            # Пріоритет 2: помірно підвищений + тренд зростання
            elif last_sys and last_sys >= BP_ELEVATED:
                if weekly_bp and weekly_bp > 1:
                    pred_ctx = f" Прогноз через 7 днів: {bp_pred} мм рт.ст." if bp_pred else ""
                    msg = f"Тиск {last_sys} мм рт.ст. — помірно підвищений і зростає на {weekly_bp} мм/тиждень.{pred_ctx}"
                else:
                    msg = f"Тиск {last_sys} мм рт.ст. — помірно підвищений. Зменшіть споживання солі та стрес."
            # Пріоритет 3: норма але є позитивний тренд зниження
            elif weekly_bp and weekly_bp < -1 and bp_pred:
                msg = f"Тиск знижується на {abs(weekly_bp)} мм/тиждень. Прогноз через 7 днів: {bp_pred} мм рт.ст. — позитивна динаміка."
            # Пріоритет 4: норма
            elif last_sys:
                msg = f"Тиск {last_sys} мм рт.ст. — у нормі."

            if msg:
                results['pressure'] = msg

        # ── HYDRATION: аналіз вживання води ────────────────────
        WATER_MIN = 1.5   # мінімальна норма (л)
        WATER_OPT = 2.0   # оптимум без активності
        WATER_ACTIVE = 2.5  # оптимум при активності

        if waters and avg_water is not None:
            parts = []
            norm = WATER_ACTIVE if act_score >= 3 else WATER_OPT

            if avg_water < WATER_MIN:
                parts.append(
                    f"Середнє вживання води {avg_water} л — значно нижче норми ({norm} л). "
                    f"Зневоднення погіршує метаболізм і концентрацію."
                )
            elif avg_water < norm:
                diff = round(norm - avg_water, 1)
                parts.append(
                    f"Вода: {avg_water} л/день — нижче рекомендованих {norm} л. "
                    f"Рекомендується додати ~{diff} л на день."
                )
            else:
                parts.append(
                    f"Норма води витримується: {avg_water} л/день — відповідає рекомендованим {norm} л."
                )

            # Тренд вживання води
            if len(waters) >= 5:
                water_trend = round(float(np.polyfit(np.arange(len(waters)), waters, 1)[0]) * 7, 2)
                if water_trend < -0.3:
                    parts.append(f"Тенденція до зниження вживання води ({abs(water_trend):.1f} л/тиждень).")
                elif water_trend > 0.3:
                    parts.append(f"Вживання води поступово зростає (+{water_trend:.1f} л/тиждень) — позитивна динаміка.")

            # Порівняння з кластером
            cluster_water_norm = norm  # використовуємо норму по активності
            if avg_water < cluster_water_norm * 0.85:
                parts.append(
                    f"Для людей вашого рівня активності норма — {cluster_water_norm} л, "
                    f"ваш показник нижче на {round(cluster_water_norm - avg_water, 1)} л."
                )

            if parts:
                results['hydration'] = ' '.join(parts)

        # ── INSIGHTS: кореляція + динаміка кластера ────────────
        insights = []

        # Кореляція сон-пульс: порівнюємо дні з коротким сном і пульсом
        if len(sleeps) >= 5 and len(pulses) >= 5:
            n = min(len(sleeps), len(pulses))
            sl = np.array(sleeps[-n:])
            pu = np.array(pulses[-n:])
            corr = np.corrcoef(sl, pu)[0, 1]
            if corr < -0.4:
                short_sleep_days = sl < SLEEP_MIN
                if short_sleep_days.any() and (~short_sleep_days).any():
                    avg_pulse_short = round(float(np.mean(pu[short_sleep_days])))
                    avg_pulse_norm  = round(float(np.mean(pu[~short_sleep_days])))
                    diff = avg_pulse_short - avg_pulse_norm
                    if diff > 3:
                        insights.append(
                            f"Виявлено зв'язок: у дні з коротким сном ваш пульс "
                            f"вищий на {diff} уд/хв ({avg_pulse_short} vs {avg_pulse_norm} уд/хв у звичайні дні)."
                        )

        # Динаміка кластера
        cluster_labels = {'low': 'низький ризик', 'moderate': 'помірний ризик', 'high': 'високий ризик'}
        if prev_cluster and prev_cluster != cluster:
            prev_label = cluster_labels.get(prev_cluster, prev_cluster)
            curr_label = cluster_labels.get(cluster, cluster)
            risk_order = {'low': 0, 'moderate': 1, 'high': 2}
            if risk_order.get(cluster, 1) > risk_order.get(prev_cluster, 1):
                insights.append(
                    f"Профіль ризику змінився: раніше {prev_label} → тепер {curr_label}. "
                    f"Рекомендується звернути увагу на показники."
                )
            else:
                insights.append(
                    f"Профіль ризику покращився: {prev_label} → {curr_label}. "
                    f"Продовжуйте підтримувати поточний режим."
                )

        # Кореляція вода-активність
        if waters and len(waters) >= 5:
            steps_rows = db.execute_query(
                "SELECT steps FROM basic_data WHERE user_id=? AND steps IS NOT NULL ORDER BY date DESC LIMIT 10",
                (user_id,), fetchall=True
            )
            if steps_rows and len(steps_rows) >= 5:
                steps_list = list(reversed([int(r[0]) for r in steps_rows]))
                n = min(len(waters), len(steps_list))
                w_arr = np.array(waters[-n:])
                s_arr = np.array(steps_list[-n:])
                corr_ws = np.corrcoef(w_arr, s_arr)[0, 1]
                if abs(corr_ws) > 0.5:
                    direction = "більше п'єте" if corr_ws > 0 else "менше п'єте"
                    insights.append(
                        f"Виявлено зв'язок: у дні з більшою кількістю кроків ви {direction} води (кореляція {round(float(corr_ws), 2)})."
                    )

        if insights:
            results['insights'] = ' '.join(insights)

        # Перевірка типів перед поверненням
        for k, v in list(results.items()):
            if not isinstance(v, str):
                print(f"[WARN] generate: results[{k}] має тип {type(v)}")
                del results[k]

        return results