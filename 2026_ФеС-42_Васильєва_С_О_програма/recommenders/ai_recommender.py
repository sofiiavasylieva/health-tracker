import os
import numpy as np
from groq import Groq

# Модель: llama-3.3-70b-versatile
# Ліміт безкоштовного тарифу: 14400 запитів/день, 30 запитів/хвилину
MODEL = "llama-3.3-70b-versatile"

ACTIVITY_LABELS = {
    1.2:   'sedentary (desk job, no exercise)',
    1.375: 'lightly active (1–3 workouts/week)',
    1.55:  'moderately active (3–5 workouts/week)',
    1.725: 'highly active (6–7 workouts/week)',
    1.9:   'very highly active (physical job + sport)',
}

GOAL_LABELS = {
    'lose':     'weight loss',
    'gain':     'muscle gain',
    'maintain': 'weight maintenance',
}

SYSTEM_PROMPT = """You are a professional health assistant inside a health tracking app.
Analyze the user profile and health metrics, then provide short personalized recommendations.
Rules:
- Write recommendation text in Ukrainian language
- Category labels MUST always be in English (WEIGHT, SLEEP, PULSE, PRESSURE, HYDRATION)
- Be specific — use actual numbers from the data
- Each recommendation must be 1 sentence
- No greetings, no conclusions
- Format: ENGLISH_CATEGORY: recommendation in Ukrainian
- Example: SLEEP: Ваш середній сон 7 годин — намагайтесь спати 8 годин."""

CATEGORY_PROMPTS = {
    'weight': "Weight: {weight} kg, BMI: {bmi}, trend: {trend}, goal: {goal}. Give 1 weight recommendation.",
    'sleep':  "Sleep avg: {avg_sleep}h (min {min_sleep}, max {max_sleep}). Give 1 sleep recommendation.",
    'pulse':  "Avg resting heart rate: {avg_pulse} bpm, activity: {activity}. Give 1 heart rate recommendation.",
    'pressure': "Avg systolic BP: {avg_systolic} mmHg, trend: {bp_trend}. Give 1 blood pressure recommendation.",
    'hydration': "Avg water intake: {avg_water} L/day, activity: {activity}. Give 1 hydration recommendation.",
}


class AIRecommender:

    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            print("[WARN] AIRecommender: GROQ_API_KEY не знайдено в .env")
            self.client = None
        else:
            self.client = Groq(api_key=api_key)

    def _activity_label(self, level):
        closest = min(ACTIVITY_LABELS, key=lambda k: abs(k - (level or 1.375)))
        return ACTIVITY_LABELS[closest]

    def _call_api(self, user_prompt):
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=300,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] Groq API: {e}")
            return None

    def generate(self, user_id, db, categories=None):
        if not self.client:
            return {}

        user = db.execute_query(
            "SELECT age, gender, height, goal, activity_level FROM users WHERE id=?",
            (user_id,), fetchone=True
        )
        if not user:
            return {}

        age, gender, height, goal, activity_level = user
        activity = self._activity_label(activity_level)
        goal_label = GOAL_LABELS.get(goal, goal)

        # Збираємо дані з БД
        last_weight = db.execute_query(
            "SELECT weight FROM basic_data WHERE user_id=? AND weight IS NOT NULL ORDER BY date DESC, id DESC LIMIT 1",
            (user_id,), fetchone=True
        )
        weight_rows = db.execute_query(
            "SELECT weight FROM basic_data WHERE user_id=? AND weight IS NOT NULL ORDER BY date DESC LIMIT 7",
            (user_id,), fetchall=True
        )
        sleep_rows = db.execute_query(
            "SELECT duration_sleep FROM health_data WHERE user_id=? AND duration_sleep IS NOT NULL ORDER BY date DESC, id DESC LIMIT 7",
            (user_id,), fetchall=True
        )
        pulse_rows = db.execute_query(
            "SELECT pulse FROM health_data WHERE user_id=? AND pulse IS NOT NULL ORDER BY date DESC LIMIT 7",
            (user_id,), fetchall=True
        )
        bp_rows = db.execute_query(
            "SELECT blood_pressure FROM health_data WHERE user_id=? AND blood_pressure IS NOT NULL ORDER BY date DESC LIMIT 7",
            (user_id,), fetchall=True
        )
        water_rows = db.execute_query(
            "SELECT water_intake FROM activity_data WHERE user_id=? AND water_intake IS NOT NULL ORDER BY date DESC LIMIT 7",
            (user_id,), fetchall=True
        )

        # Формуємо промпти для кожної категорії
        tasks = {}

        if last_weight and (not categories or 'weight' in categories):
            w = float(last_weight[0])
            bmi = round(w / (height / 100) ** 2, 1) if height else '—'
            trend = 'insufficient data'
            if weight_rows and len(weight_rows) >= 3:
                weights = list(reversed([float(r[0]) for r in weight_rows]))
                t = round(float(np.polyfit(np.arange(len(weights)), weights, 1)[0]) * 7, 2)
                direction = 'increasing' if t > 0 else 'decreasing'
                trend = f"{direction} by {abs(t):.2f} kg/week"
            tasks['weight'] = CATEGORY_PROMPTS['weight'].format(
                weight=w, bmi=bmi, trend=trend, goal=goal_label
            )

        if sleep_rows and (not categories or 'sleep' in categories):
            sleeps = [float(r[0]) for r in sleep_rows]
            tasks['sleep'] = CATEGORY_PROMPTS['sleep'].format(
                avg_sleep=round(float(np.mean(sleeps)), 1),
                min_sleep=round(min(sleeps), 1),
                max_sleep=round(max(sleeps), 1),
            )

        if pulse_rows and (not categories or 'pulse' in categories):
            pulses = [int(r[0]) for r in pulse_rows]
            tasks['pulse'] = CATEGORY_PROMPTS['pulse'].format(
                avg_pulse=round(float(np.mean(pulses))),
                activity=activity,
            )

        if bp_rows and (not categories or 'pressure' in categories):
            systolics = [int(r[0].split('/')[0]) for r in bp_rows if r[0] and '/' in r[0]]
            if systolics:
                avg_sys = round(float(np.mean(systolics)))
                bp_trend = 'insufficient data'
                if len(systolics) >= 3:
                    t = round(float(np.polyfit(np.arange(len(systolics)), systolics, 1)[0]) * 7, 1)
                    bp_trend = f"{'increasing' if t > 0 else 'decreasing'} by {abs(t)} mmHg/week"
                tasks['pressure'] = CATEGORY_PROMPTS['pressure'].format(
                    avg_systolic=avg_sys, bp_trend=bp_trend,
                )

        if water_rows and (not categories or 'hydration' in categories):
            waters = [float(r[0]) for r in water_rows]
            tasks['hydration'] = CATEGORY_PROMPTS['hydration'].format(
                avg_water=round(float(np.mean(waters)), 1),
                activity=activity,
            )

        if not tasks:
            return {}

        # Один запит з усіма категоріями
        combined = "Analyze and give one recommendation per category:\n\n"
        for cat, prompt in tasks.items():
            combined += f"{cat.upper()}: {prompt}\n"
        combined += "\nRespond with:\nCATEGORY: recommendation (in Ukrainian)"

        response = self._call_api(combined)
        print(f"[DEBUG] Groq відповідь:\n{response}")
        if not response:
            return {}

        cat_aliases = {
            'weight':    ['weight'],
            'sleep':     ['sleep', 'sleep hours'],
            'pulse':     ['pulse', 'heart rate'],
            'pressure':  ['pressure', 'blood pressure'],
            'hydration': ['hydration', 'water'],
        }

        # Всі можливі префікси що AI може вставити у текст
        all_prefixes = set()
        for aliases in cat_aliases.values():
            for a in aliases:
                all_prefixes.add(a.upper() + ':')

        def strip_cat_prefix(text):
            """Знімає зайвий 'КАТЕГОРІЯ:' на початку тексту."""
            upper = text.upper()
            for prefix in all_prefixes:
                if upper.startswith(prefix):
                    return text[len(prefix):].strip().lstrip('*').strip()
            return text

        results = {}
        for line in response.split('\n'):
            line = line.strip()
            if not line:
                continue
            clean = line.lstrip('*-# ').strip()
            clean_upper = clean.upper()
            for cat in tasks:
                for alias in cat_aliases.get(cat, [cat]):
                    prefix = alias.upper() + ':'
                    if clean_upper.startswith(prefix):
                        text = clean[len(alias)+1:].strip().lstrip('*').strip()
                        text = strip_cat_prefix(text)  # знімаємо подвійний префікс
                        if text:
                            results[cat] = text
                        break

        # Якщо парсинг не спрацював — зберігаємо всю відповідь як є
        if not results and len(tasks) == 1:
            cat = list(tasks.keys())[0]
            text = response.strip()
            if text:
                results[cat] = text

        print(f"[DEBUG] Groq розпарсено: {list(results.keys())}")
        return results