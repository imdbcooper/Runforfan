# Runforfan Professional Product Specification

Дата: 2026-06-06

Статус: спецификация для дальнейшей реализации. Документ описывает целевой профессиональный продукт, расширяющий текущий FastAPI/PostgreSQL backend и React/Vite admin frontend.

## 1. Цель продукта

Runforfan должен стать персональной системой для бегуна, которая собирает тренировки из скриншотов и ручного ввода, строит безопасные тренировочные планы, показывает прогресс, объясняет результаты и помогает адаптировать нагрузку без превращения приложения в медицинский сервис.

Главные задачи:

- Хранить историю тренировок, результатов, целей, планов, зон и настроек пользователя.
- Импортировать данные из скриншотов через LLM или проверенные template/mask fallback-механизмы.
- Не загрязнять аналитику непроверенными распознаваниями.
- Строить тренировочные планы на основе текущей формы, цели, доступных дней, ограничений и авторитетных расчетных методик.
- Показывать понятную аналитику: объем, темп, пульс, зоны, нагрузка, тренды, выполнение плана, прогнозы результатов.
- Давать объяснимые рекомендации: что изменилось, почему план адаптирован, где риск перегруза, где прогресс.

## 2. Продуктовые принципы

- Safety first: приложение не должно назначать агрессивные нагрузки при недостатке данных, резком росте объема, симптомах риска или близкой цели.
- Explainability first: каждый расчет должен иметь метод, единицы измерения, исходные данные и источник методики.
- User confirmation first: любые данные, распознанные LLM, должны попадать в analytics только после validation pass и подтверждения пользователя либо явного auto-accept для известных шаблонов.
- Multi-user isolation: все пользовательские данные строго фильтруются по `user_id`.
- Dark compact admin UI: текущий black/orange shadcn-style интерфейс сохранить как основную визуальную систему.
- No medical diagnosis: приложение может показывать спортивную аналитику и предупреждения, но не ставит диагнозы и не заменяет врача или тренера.

## 3. Границы безопасности

Runforfan должен показывать дисклеймер на onboarding, planning и readiness pages:

```text
Runforfan не является медицинским устройством и не заменяет врача. Если есть боль в груди, головокружение, одышка вне нормы, обмороки, травма, хроническое заболевание или резкое ухудшение самочувствия, прекратите тренировку и обратитесь к специалисту.
```

Системные safety gates:

- Если пользователь указал травму, болезнь, боль или восстановление после перерыва, планировщик снижает нагрузку и запрещает высокоинтенсивные тренировки по умолчанию.
- Если данных меньше 2 недель, планировщик использует conservative mode.
- Если недельный объем за последние 14 дней резко вырос, планировщик предлагает разгрузку.
- Если цель слишком близко, приложение не обещает достижение результата и показывает реалистичный диапазон.
- Если нет HRmax, resting HR, threshold или race result, зоны считаются приблизительными и помечаются `estimated`.

## 4. Целевые пользователи

### 4.1. Beginner runner

Пользователь бегает 1-3 раза в неделю, хочет безопасно увеличить регулярность и не перегрузиться.

Ключевые функции:

- Простая цель: регулярность, 5 км, 10 км.
- Планы 2-4 дня в неделю.
- Минимум сложной терминологии.
- Акцент на easy pace, recovery, consistency.

### 4.2. Intermediate runner

Пользователь имеет историю тренировок, интересуется темпом, пульсом, зонами, прогрессом.

Ключевые функции:

- Планы 4-6 дней в неделю.
- Threshold, interval, long run, race pace workouts.
- Аналитика load, fatigue, intensity distribution, execution quality.
- Адаптация после пропусков.

### 4.3. Advanced amateur

Пользователь готовит забеги, следит за лактатным порогом, VDOT, прогнозами.

Ключевые функции:

- Структурные тренировки с блоками.
- Планирование мезоциклов.
- Сравнение race results.
- Подробные графики по зонам, нагрузке, taper readiness.

### 4.4. Data-first user

Пользователь импортирует данные из разных приложений и хочет контроль качества.

Ключевые функции:

- Import inbox.
- Validation report.
- Duplicate detection.
- Manual correction.
- Source traceability.

## 5. Навигация frontend

Базовый путь Vite: `/admin/`.

Целевые routes:

- `/admin/` - Dashboard.
- `/admin/onboarding` - первичная настройка профиля.
- `/admin/activities` - список тренировок.
- `/admin/activities/:id` - детальная тренировка.
- `/admin/imports` - импорт и подтверждение распознавания.
- `/admin/calendar` - календарь тренировок и плана.
- `/admin/plans` - список планов.
- `/admin/plans/new` - мастер создания плана.
- `/admin/plans/:id` - план по неделям.
- `/admin/workouts/:id` - запланированная тренировка и факт выполнения.
- `/admin/analytics` - общий analytics hub.
- `/admin/analytics/performance` - результаты, VDOT, прогнозы.
- `/admin/analytics/load` - нагрузка, fatigue, monotony, strain.
- `/admin/analytics/zones` - зоны, распределение интенсивности.
- `/admin/goals` - цели и забеги.
- `/admin/profile` - профиль, физиология, ограничения.
- `/admin/settings/llm` - LLM providers.
- `/admin/settings/integrations` - источники данных.
- `/admin/settings/data` - экспорт, удаление, audit.

## 6. Страницы и профессиональный функционал

### 6.1. Onboarding

Цель страницы: собрать минимальные данные, без которых профессиональный планировщик и зоны будут слишком приблизительными.

Блоки:

- Account: display name, Telegram username, locale, timezone.
- Athlete profile: дата рождения или возраст, пол для формул TRIMP, рост, вес.
- Physiology: resting HR, measured HRmax, lactate threshold HR, lactate threshold pace, preferred measurement method.
- Running history: текущий недельный объем, самый длинный бег за 8 недель, опыт бега, недавние результаты.
- Availability: доступные дни недели, максимальная длительность будни/выходные, предпочтительный день long run.
- Constraints: травмы, запрещенные дни, поверхности, доступ к стадиону, погода/сезон.
- Goal quick start: regularity, 5K, 10K, half marathon, marathon, custom.

Профессиональная логика:

- Если пользователь не знает HRmax, показывать Tanaka estimate `208 - 0.7 * age` с пометкой `estimated`.
- Если пользователь не знает resting HR, не использовать HR reserve zones.
- Если нет race result или threshold, строить план по RPE и easy pace, без точных темповых предписаний.
- Если пользователь указал травму или перерыв более 4 недель, включать conservative mode.

API:

- `GET /api/profile`
- `PUT /api/profile`
- `GET /api/profile/completeness`
- `POST /api/profile/safety-check`

Acceptance criteria:

- Пользователь может закончить onboarding с минимальными данными.
- Все оценочные поля помечены `estimated`.
- Планировщик получает structured athlete context.

### 6.2. Dashboard

Цель страницы: быстрый ответ на вопросы: что делать сегодня, как идет прогресс, есть ли риск перегруза.

Блоки:

- Today card: следующая тренировка, цель, длительность, темп/HR/RPE, кнопки `Start`, `Mark done`, `Reschedule`.
- Weekly snapshot: выполнено тренировок, километры, время, long run, adherence.
- Readiness summary: form, fatigue, last hard workout, sleep/rest notes if available.
- Fitness trend: CTL или internal fitness score за 6 недель.
- Goal progress: ближайшая цель и вероятность готовности.
- Recent activities table: последние 5-8 тренировок.
- Alerts: missing threshold, no LLM provider, high monotony, validation pending.

Профессиональная логика:

- Dashboard не должен показывать один общий score без объяснения. Любой score раскрывается через факторы.
- Если план есть, показывать plan adherence и planned vs actual.
- Если плана нет, показывать CTA `Create plan` и recommended next safe step.

API:

- `GET /api/dashboard/summary`
- `GET /api/planning/current-week`
- `GET /api/analytics/load/summary`
- `GET /api/imports?status=pending_confirmation`

### 6.3. Activities List

Цель страницы: профессиональный журнал тренировок.

Функции:

- Фильтры: дата, месяц, тип, источник, дистанция, темп, HR zone, planned/unplanned, validation status.
- Сортировка: дата, дистанция, duration, avg pace, avg HR, training load, execution score.
- Bulk actions: export CSV, delete selected with confirmation, attach to plan workout.
- Quick edit: title, date, distance, duration, average HR, notes.
- Duplicate warnings: одинаковая дата/дистанция/длительность/source hash.
- Data quality badges: `verified`, `estimated`, `llm_pending`, `manual`, `inconsistent`.

Таблица:

- Date.
- Title/type.
- Distance.
- Duration.
- Weighted pace.
- Avg HR.
- Load.
- Zones.
- Source.
- Plan match.

API:

- `GET /api/activities?from=&to=&type=&source=&quality=&page=&limit=&sort=`
- `POST /api/activities`
- `PATCH /api/activities/{id}`
- `DELETE /api/activities/{id}`
- `POST /api/activities/bulk/export`

### 6.4. Activity Detail

Цель страницы: детальный разбор одной тренировки и проверка качества данных.

Блоки:

- Header: title, date, source, quality status, edit/delete.
- Summary metrics: distance, duration, weighted pace, calories, avg HR, max HR if available, cadence, elevation, training load.
- Planned vs actual: если тренировка связана с plan workout, сравнить target blocks и фактическое выполнение.
- Splits table: distance, time, pace, HR, cadence, elevation, zone.
- Charts: pace by segment, HR by segment, cadence, elevation if available.
- Intensity distribution: time/distance in zones.
- Execution notes: RPE, soreness, sleep, subjective comments.
- Recognition sources: связанные скриншоты, raw candidate, validation report.
- Calculations drawer: какие метрики рассчитаны, какие импортированы, какие estimated.

Профессиональная логика:

- Weighted average pace всегда считать как `sum(duration_seconds) / sum(distance_km)`, если есть сегменты.
- Если activity pace не совпадает с distance/duration более чем на tolerance, показывать data warning.
- Если последний неполный сегмент слишком быстрый и менее 0.3 км, не использовать его для best pace без пометки.
- Если средний HR выше threshold на easy workout, показывать `possible over-effort` только как спортивный сигнал, не диагноз.

API:

- `GET /api/activities/{id}`
- `GET /api/activities/{id}/derived-metrics`
- `GET /api/activities/{id}/validation`
- `PATCH /api/activities/{id}`
- `POST /api/activities/{id}/notes`

### 6.5. Imports

Цель страницы: безопасный импорт скриншотов и контроль распознавания.

Функции:

- Upload drag-and-drop, до 6 файлов на batch в MVP.
- Source app selector: Huawei Health, Garmin, Strava, manual, unknown.
- Recognition mode: default provider, selected provider, template only.
- Batch status: uploaded, recognizing, recognized_candidate, pending_confirmation, validation_failed, rejected_no_template, confirmed.
- Candidate review: пользователь видит распознанные поля до записи в analytics.
- Field-level confidence: distance, duration, pace, HR, date, segments.
- Manual corrections: редактирование candidate до подтверждения.
- Validation report: consistency checks.
- Confirm creates activity.
- Reject keeps screenshots but не создает activity.

Validation checks:

- `duration_seconds / distance_km` должен совпадать с pace в пределах 2-5 секунд/км или иметь объяснение rounding.
- Сумма сегментов по дистанции должна отличаться от activity distance не более чем на 0.05 км или 1%.
- Сумма сегментов по времени должна отличаться от duration не более чем на 10 секунд или 1%.
- HR должен быть в физиологически допустимом диапазоне 35-230 bpm.
- Cadence для бега обычно 120-240 spm, outliers помечаются.
- started_at не должен быть в далеком будущем.
- Duplicate detection по user_id, started_at, distance, duration, source hash.

API:

- `POST /api/imports/screenshots`
- `GET /api/imports`
- `GET /api/imports/{id}`
- `PATCH /api/imports/{id}/candidate`
- `POST /api/imports/{id}/confirm`
- `POST /api/imports/{id}/reject`
- `GET /api/imports/{id}/validation`

### 6.6. Calendar

Цель страницы: видеть план и факт по дням.

Функции:

- Month/week view.
- Planned workouts, completed activities, missed workouts.
- Drag-and-drop reschedule.
- Conflict detection: две hard sessions подряд, long run слишком близко к interval session.
- Quick completion: mark as done, attach activity.
- Load heatmap by day.

Профессиональная логика:

- Если пользователь переносит hard workout ближе чем за 48 часов к другой hard session, показывать warning.
- Если missed easy workout, не переносить автоматически поверх recovery.
- Если missed quality workout, предложить skip или replace, а не stack.

API:

- `GET /api/calendar?from=&to=`
- `PATCH /api/planning/workouts/{id}/schedule`
- `POST /api/planning/workouts/{id}/complete`
- `POST /api/planning/workouts/{id}/attach-activity`

### 6.7. Plans List

Цель страницы: управлять тренировочными программами.

Функции:

- Список планов: draft, active, completed, archived.
- Метрики: weeks, race distance, target date, adherence, current week, total planned distance.
- Actions: activate, duplicate, archive, delete, export.
- Plan comparison: два плана рядом по volume/intensity/risk.

API:

- `GET /api/planning/plans`
- `POST /api/planning/plans/{id}/activate`
- `POST /api/planning/plans/{id}/duplicate`
- `PATCH /api/planning/plans/{id}`
- `DELETE /api/planning/plans/{id}`

### 6.8. Plan Builder Wizard

Цель страницы: создать безопасный, объяснимый тренировочный план.

Шаги:

- Goal: 5K, 10K, half marathon, marathon, custom, base building.
- Target: target date, target time optional, priority.
- Baseline: detected weekly volume, user override, longest recent run, recent race result.
- Availability: days per week, preferred days, time budget.
- Intensity preferences: HR-based, pace-based, RPE-based, mixed.
- Constraints: injury, no hard workouts, max long run duration, terrain.
- Preview: weekly volume curve, long run curve, intensity split, risk flags.
- Confirm: create draft or activate.

Профессиональная логика baseline:

- `observed_weekly_volume` = сумма дистанций за каждую из последних 6 недель.
- `current_weekly_volume` = median последних 4 недель с тренировками, если есть минимум 2 недели данных.
- Если данных мало, брать user input, но cap long run и intensity.
- `recent_long_run` = max distance за последние 8 недель.
- `training_age_level` определяется по истории: beginner, intermediate, advanced.

Risk flags:

- Цель слишком близко.
- Marathon requested при объеме меньше 20 км/нед.
- Long run progression слишком резкий.
- Больше 2 hard sessions в неделю.
- Нет recovery day после hard session.
- Нет исходных данных для темповых зон.

API:

- `POST /api/planning/preview`
- `POST /api/planning/generate`
- `GET /api/planning/recommendations/context`

### 6.9. Plan Detail

Цель страницы: профессиональное отображение программы по неделям.

Блоки:

- Plan header: status, goal, target date, target time, current week.
- Week summary: planned km, planned time, hard sessions, long run, deload marker.
- Workout cards: type, target, blocks, intensity, notes, safety warnings.
- Volume chart: weekly planned vs actual.
- Intensity split: easy/steady/hard.
- Adaptation panel: что изменить после последней недели.
- Version history: created, edited, adapted.

Workout card fields:

- Type: recovery, easy, long, strides, hill, tempo, threshold, interval, race pace, rest, strength.
- Target mode: distance, duration, pace, HR, RPE.
- Structured blocks: warmup, repeats, recovery, cooldown.
- Purpose: why this workout exists.
- Safety note: when to reduce/skip.

API:

- `GET /api/planning/plans/{id}`
- `GET /api/planning/plans/{id}/weeks`
- `POST /api/planning/plans/{id}/adapt`
- `GET /api/planning/plans/{id}/recommendations`
- `POST /api/planning/plans/{id}/recommendations/preview`
- `POST /api/planning/plans/{id}/recommendations/apply`
- `GET /api/planning/plans/{id}/recommendations/audit`
- `PATCH /api/planning/workouts/{id}`

### 6.10. Workout Detail and Completion

Цель страницы: превратить план в выполнимую тренировку и собрать обратную связь.

Функции:

- Structured workout view.
- Target ranges: pace, HR, RPE.
- Manual completion form.
- Attach imported/completed activity.
- RPE 0-10.
- Notes: сон, усталость, боль, погода.
- Execution score: completed volume, intensity compliance, notes.

Execution score:

- Volume score = actual distance or duration vs planned target.
- Intensity score = доля времени в целевой зоне.
- Adherence status: completed, partial, overdone, missed, moved.
- Если overdone hard workout, следующий hard workout candidate for downshift.

API:

- `GET /api/planning/workouts/{id}`
- `POST /api/planning/workouts/{id}/complete`
- `POST /api/planning/workouts/{id}/attach-activity`
- `PATCH /api/planning/workouts/{id}/feedback`
- `GET /api/planning/workouts/{id}/feedback`
- `PUT /api/planning/workouts/{id}/feedback`

### 6.11. Analytics Overview

Цель страницы: главный аналитический центр.

Блоки:

- Date range selector: 7d, 28d, 90d, year, custom.
- KPI cards: distance, time, workouts, weighted pace, avg HR, load, adherence.
- Trend charts: weekly volume, monthly volume, pace trend, HR trend.
- Best efforts: 1 km, 5 km, 10 km, half marathon estimates if supported by data.
- Consistency: days trained per week, missed planned sessions.
- Insights: 3-5 explainable notes.

Профессиональная логика:

- Weighted metrics use duration or distance weighting, not simple average unless explicitly labeled.
- Pace trend should compare similar workout types, not all runs blindly.
- Easy pace improvement should use easy runs only.

API:

- `GET /api/analytics/summary?from=&to=`
- `GET /api/analytics/timeseries?metric=&granularity=`
- `GET /api/analytics/insights`

### 6.12. Performance Analytics

Цель страницы: понять текущую спортивную форму и прогнозы результатов.

Блоки:

- Race results table.
- Time trials.
- VDOT estimate with source.
- Equivalent race predictions.
- Personal bests.
- Threshold trend.
- Pace zones derived from VDOT or threshold.

Профессиональная логика:

- VDOT считается только из race/time trial или clearly hard effort, не из easy runs.
- Riegel predictions показываются с confidence и ограничением extrapolation distance.
- Если данные старше 12 недель, prediction confidence снижается.
- Если race result был на трейле/жаре/большом наборе высоты, prediction помечается как noisy.

API:

- `GET /api/performance/results`
- `POST /api/performance/results`
- `GET /api/performance/vdot`
- `GET /api/performance/predictions`
- `GET /api/performance/pbs`

### 6.13. Training Load and Recovery Analytics

Цель страницы: отслеживать нагрузку, усталость и риск неудачной периодизации.

Блоки:

- Daily load chart.
- Weekly load chart.
- CTL, ATL, TSB with explanation.
- Monotony and strain.
- Hard sessions spacing.
- Recovery days.
- Alerts: high monotony, too much intensity, long run share too high.

Профессиональная логика:

- Training load может считаться несколькими методами: sRPE, HR TRIMP, pace-based fallback.
- Основной method выбирается по доступности данных и показывается пользователю.
- CTL/ATL/TSB являются эвристиками, а не медицинским прогнозом.
- Monotony и strain используются как warning signals, не как абсолютный запрет.

API:

- `GET /api/analytics/load/daily`
- `GET /api/analytics/load/weekly`
- `GET /api/analytics/load/fitness-fatigue`
- `GET /api/analytics/load/warnings`

### 6.14. Zones Analytics

Цель страницы: управлять зонами и видеть распределение интенсивности.

Блоки:

- HR zones.
- Pace zones.
- RPE scale.
- 3-zone Seiler distribution.
- 5-zone detailed distribution.
- Time in zones by week/month.
- Planned vs actual zone distribution.

Профессиональная логика:

- Если есть threshold HR/pace, использовать threshold-based zones как preferred.
- Если есть VDOT, использовать VDOT pace zones.
- Если есть только возраст, использовать HRmax estimate и помечать zones as low confidence.
- Пользователь может вручную override any zone.

API:

- `GET /api/zones`
- `PUT /api/zones/hr`
- `PUT /api/zones/pace`
- `POST /api/zones/recalculate`
- `GET /api/analytics/zones/distribution`

### 6.15. Goals and Races

Цель страницы: связать цели, планы и аналитику.

Функции:

- Goal types: race, weekly consistency, monthly distance, long run, custom habit, health.
- Race goal: distance, date, target time, priority, course notes.
- Progress: plan adherence, current fitness, predicted time range.
- Milestones: tune-up races, threshold test, longest run.
- Goal status: active, paused, completed, missed, archived.

API:

- `GET /api/goals`
- `POST /api/goals`
- `PATCH /api/goals/{id}`
- `DELETE /api/goals/{id}`
- `POST /api/goals/{id}/complete`

### 6.16. Profile

Цель страницы: все данные, влияющие на расчеты.

Блоки:

- Personal: age/date of birth, sex, timezone.
- Body: weight, height.
- Physiology: resting HR, HRmax, lactate threshold HR/pace, VO2max if known.
- Preferences: metric units, training days, long run day, max duration.
- Safety: injuries, conditions, recovery status, conservative mode.
- Measurement history: threshold tests, HRmax tests, weight changes.

API:

- `GET /api/profile`
- `PUT /api/profile`
- `POST /api/profile/measurements`
- `GET /api/profile/measurements`

### 6.17. LLM Providers

Цель страницы: пользователь сам управляет AI provider для распознавания и пояснений.

Функции:

- Add OpenAI-compatible provider.
- Add Anthropic provider.
- Base URL, model, API key.
- Test connection with safe prompt.
- Vision support check.
- Default provider.
- Delete/disable provider.
- Key never returned to frontend.

API уже частично есть:

- `GET /api/settings/llm-providers`
- `POST /api/settings/llm-providers`
- `POST /api/settings/llm-providers/{id}/default`
- `DELETE /api/settings/llm-providers/{id}`

Нужно добавить:

- `POST /api/settings/llm-providers/{id}/test`
- `PATCH /api/settings/llm-providers/{id}`

### 6.18. Integrations and Data Management

Цель страницы: будущие источники данных и контроль приватности.

Функции:

- Manual import.
- Screenshot import.
- CSV import/export.
- Future: Garmin/Strava/Telegram bot.
- Data export: activities, plans, goals, settings without secrets.
- Delete account data.
- Audit log: imports, provider changes, deletes.

API:

- `GET /api/settings/integrations`
- `POST /api/imports/csv`
- `GET /api/export`
- `DELETE /api/account/data`
- `GET /api/audit-log`

## 7. Данные и модель хранения

Текущие модели уже есть: users, sessions, activities, segments, split blocks, screenshots, imports, goals, llm providers, training plans, plan workouts.

Нужно добавить целевые модели.

### 7.1. `athlete_profiles`

Поля:

- `user_id`
- `date_of_birth`
- `sex`: male, female, other, unspecified.
- `height_cm`
- `weight_kg`
- `timezone`
- `locale`
- `resting_heart_rate_bpm`
- `max_heart_rate_bpm`
- `max_hr_source`: measured, tanaka_estimated, manual.
- `lactate_threshold_hr_bpm`
- `lactate_threshold_pace_seconds_per_km`
- `conservative_mode`
- `injury_notes`
- `created_at`, `updated_at`

### 7.2. `athlete_measurements`

Поля:

- `id`, `user_id`
- `measurement_type`: weight, resting_hr, max_hr, lactate_threshold, vo2max, note.
- `measured_at`
- `value_numeric`
- `value_json`
- `source`: manual, screenshot, device, calculated.
- `confidence`

### 7.3. `race_results`

Поля:

- `id`, `user_id`
- `activity_id` nullable.
- `event_name`
- `distance_km`
- `duration_seconds`
- `event_date`
- `surface`, `elevation_gain_m`, `weather_notes`
- `is_time_trial`
- `effort_level`: race, time_trial, hard_workout.
- `source`
- `created_at`

### 7.4. `training_zones`

Поля:

- `id`, `user_id`
- `zone_type`: hr, pace, rpe.
- `method`: manual, hrr, hrmax, lthr, vdot, threshold_pace.
- `zone_key`: z1, z2, z3, z4, z5, easy, marathon, threshold, interval, repetition.
- `lower_value`, `upper_value`
- `unit`: bpm, seconds_per_km, rpe.
- `confidence`: high, medium, low.
- `source_reference`

### 7.5. `derived_activity_metrics`

Поля:

- `activity_id`
- `metric_key`
- `metric_value`
- `unit`
- `method`
- `source_reference`
- `input_hash`
- `computed_at`

Назначение: расчетные метрики можно пересчитать и объяснить.

### 7.6. `daily_training_loads`

Поля:

- `user_id`
- `date`
- `load_value`
- `method`: srpe, hr_trimp, pace_fallback, manual.
- `duration_minutes`
- `activity_ids`
- `ctl`
- `atl`
- `tsb`
- `monotony_window_value`
- `strain_window_value`

### 7.7. `planned_workout_blocks`

Поля:

- `id`, `workout_id`
- `block_index`
- `block_type`: warmup, work, recovery, cooldown, rest, strength.
- `repeat_count`
- `target_distance_km`
- `target_duration_seconds`
- `target_pace_min_seconds_per_km`
- `target_pace_max_seconds_per_km`
- `target_hr_min_bpm`
- `target_hr_max_bpm`
- `target_rpe_min`, `target_rpe_max`
- `description`

### 7.8. `plan_versions`

Поля:

- `id`, `plan_id`
- `version_number`
- `reason`: initial, manual_edit, auto_adaptation, user_request.
- `summary`
- `created_at`
- `snapshot_json`

### 7.9. `workout_feedback`

Поля:

- `workout_id`
- `activity_id` nullable.
- `completion_status`
- `rpe`
- `soreness_0_10`
- `sleep_quality_0_10`
- `pain_notes`
- `user_notes`
- `created_at`

## 8. API архитектура

### 8.1. Общие правила

- Все endpoints кроме auth требуют Bearer token.
- Все queries фильтруются по `current_user.id`.
- Все write endpoints валидируют ownership.
- Все расчетные endpoints возвращают `method`, `source`, `confidence` там, где применимо.
- Ошибки возвращаются в формате `{ code, message, details }`.

### 8.2. Endpoint groups

- Auth: `/api/auth/*`
- Profile: `/api/profile/*`
- Activities: `/api/activities/*`
- Imports: `/api/imports/*`
- Calendar: `/api/calendar/*`
- Planning: `/api/planning/*`
- Workouts: `/api/planning/workouts/*`
- Analytics: `/api/analytics/*`
- Performance: `/api/performance/*`
- Zones: `/api/zones/*`
- Goals: `/api/goals/*`
- Settings: `/api/settings/*`
- Export/audit: `/api/export`, `/api/audit-log`

## 9. Стандарт расчетов

Все длительности хранятся в секундах. Все темпы хранятся в секундах на километр. Все дистанции хранятся в километрах. Расчетные значения округляются только на presentation layer, если это не field persistence requirement.

### 9.1. Pace, speed, distance

Формулы:

- `pace_seconds_per_km = duration_seconds / distance_km`
- `speed_kmh = distance_km / (duration_seconds / 3600)`
- `duration_seconds = pace_seconds_per_km * distance_km`
- `weighted_average_pace = sum(duration_seconds) / sum(distance_km)`

Правила:

- Для списка тренировок средний темп считать weighted, а не average of averages.
- Если distance отсутствует, pace не рассчитывать.
- Если distance меньше 0.1 км, не использовать activity для performance predictions.

### 9.2. Heart rate max

Preferred order:

- Measured HRmax from user.
- User manual HRmax.
- Tanaka estimate.

Tanaka equation:

```text
HRmax = 208 - 0.7 * age
```

Источник: Tanaka, Monahan, Seals, 2001, Journal of the American College of Cardiology, PMID 11153730.

### 9.3. Heart rate reserve zones

Karvonen method:

```text
HRR = HRmax - HRrest
TargetHR = HRrest + intensity_fraction * HRR
```

Initial app zones using ACSM-informed intensity categories:

- Z1 recovery: 30-39% HRR.
- Z2 aerobic/moderate: 40-59% HRR.
- Z3 steady/vigorous low: 60-74% HRR.
- Z4 threshold/vigorous high: 75-84% HRR.
- Z5 very hard: 85-95% HRR.

Правила:

- Если HRrest неизвестен, HRR zones не строить.
- Если HRmax estimated, zones confidence = low.
- Пользовательские zones имеют приоритет.

### 9.4. Daniels/Gilbert VDOT

Использовать только для race results или time trials с достаточной достоверностью.

Переменные:

- `v` = velocity in meters per minute.
- `t` = race duration in minutes.

Oxygen cost:

```text
VO2 = -4.60 + 0.182258 * v + 0.000104 * v^2
```

Fraction of VO2max sustainable for duration:

```text
percent_vo2max = 0.8 + 0.1894393 * exp(-0.012778 * t) + 0.2989558 * exp(-0.1932605 * t)
```

VDOT:

```text
VDOT = VO2 / percent_vo2max
```

Rules:

- Equivalent race predictions solve inverse equation numerically for each target distance.
- If source result is older than 12 weeks, confidence decreases.
- If target distance differs by more than 4x from source distance, confidence decreases.

Источник: Daniels and Gilbert oxygen power/VDOT model; V.O2/VDOT calculator definitions by Daniels Running Formula ecosystem.

### 9.5. Riegel race prediction

Formula:

```text
T2 = T1 * (D2 / D1)^k
```

Default:

```text
k = 1.06
```

Rules:

- Use as simple transparent baseline prediction.
- Do not use for medical or guaranteed result claims.
- For very different distances, show low confidence.
- If multiple race results exist, use most recent high-confidence result or weighted blend.

Источник: Pete Riegel, Athletic Records and Human Endurance, American Scientist, 1981.

### 9.6. ACSM running energy estimate

Использовать только если calories are missing and weight is known.

For running:

```text
VO2_ml_kg_min = 0.2 * speed_m_min + 0.9 * speed_m_min * grade + 3.5
kcal_min = VO2_ml_kg_min * body_mass_kg * 5 / 1000
total_kcal = kcal_min * duration_min
```

Rules:

- If grade unknown, use grade = 0 and mark estimated.
- If device calories exist, display imported value as primary.
- Do not compare calorie burn aggressively because devices and estimates vary.

Источник: ACSM metabolic equations.

### 9.7. Training load by session RPE

Formula:

```text
sRPE_load = duration_minutes * RPE_0_10
```

Rules:

- Preferred when user provides RPE.
- Works across running, strength, cross-training.
- Store as `method = srpe`.

Источник: Foster et al., 2001, A new approach to monitoring exercise training, PMID 11708692.

### 9.8. HR-based TRIMP

Use when HR data and sex are available.

Variables:

```text
HR_ratio = (HRavg - HRrest) / (HRmax - HRrest)
```

Banister-style TRIMP:

```text
TRIMP_male = duration_minutes * HR_ratio * 0.64 * exp(1.92 * HR_ratio)
TRIMP_female = duration_minutes * HR_ratio * 0.86 * exp(1.67 * HR_ratio)
```

Rules:

- Use time-in-zone TRIMP if stream data exists.
- If only avg HR exists, mark method confidence = medium/low.
- If HRrest or HRmax missing, do not calculate HR TRIMP.

Источник: Banister impulse-response/TRIMP model lineage.

### 9.9. CTL, ATL, TSB

Daily load feeds exponentially weighted moving averages.

Constants:

- CTL time constant: 42 days.
- ATL time constant: 7 days.

Formula:

```text
alpha = 1 - exp(-1 / tau)
ewma_today = ewma_yesterday + alpha * (load_today - ewma_yesterday)
TSB = CTL - ATL
```

Rules:

- Show as fitness/fatigue/form heuristic.
- Do not use as medical readiness.
- If less than 42 days of data, show warmup warning.

Источник: Banister impulse-response model; commonly used fitness/fatigue operationalization.

### 9.10. Monotony and strain

Formulas:

```text
weekly_load = sum(daily_loads_7d)
monotony = mean(daily_loads_7d) / standard_deviation(daily_loads_7d)
strain = weekly_load * monotony
```

Rules:

- If standard deviation is zero, cap monotony or mark undefined.
- Use only as warning signal.

Источник: Foster training monitoring literature.

### 9.11. Intensity distribution

3-zone model:

- Zone 1: below first threshold/easy aerobic.
- Zone 2: between first and second threshold.
- Zone 3: above second threshold.

Rules:

- If threshold data exists, use threshold-based boundaries.
- If only pace/HR zones exist, map 5 zones to 3-zone model.
- Show total time in each zone, not only distance.
- Weekly target for most endurance plans: majority low intensity, typically 75-85% easy time depending on phase and athlete level.

Источник: Seiler and Kjerland, 2006, intensity distribution in endurance athletes, PMID 16430681.

### 9.12. Plan adherence

Formulas:

```text
distance_adherence = actual_distance / planned_distance
duration_adherence = actual_duration / planned_duration
session_adherence = completed_sessions / planned_sessions
```

Execution status:

- `completed`: 80-120% target and intensity acceptable.
- `partial`: 40-79% target.
- `overdone`: >120% target or too much time above target intensity.
- `missed`: no completion.
- `moved`: rescheduled.

Rules:

- Do not punish user for intentionally reducing workout due to safety warning.
- Overdone hard workouts should trigger adaptation.

## 10. Training plan generator

### 10.1. Inputs

Required:

- Goal type.
- Race distance or custom goal.
- Target date or plan length.
- Available days per week.

Recommended:

- Current weekly volume.
- Recent long run.
- Recent race result.
- Resting HR and HRmax.
- Threshold HR/pace.
- Preferred days.
- Injury/constraint flags.

### 10.2. Athlete classification

Classification is used only for plan safety.

Beginner:

- Less than 3 consistent weeks, or current volume less than 15 км/нед, or longest recent run less than 6 км.

Intermediate:

- 4-12 consistent weeks, current volume 15-45 км/нед, long run 6-18 км.

Advanced amateur:

- More than 12 consistent weeks, current volume above 45 км/нед, regular quality sessions.

Rules:

- User can choose a lower aggressiveness level.
- App should not auto-upgrade aggressively from sparse data.

### 10.3. Weekly volume progression

Build weeks:

- Beginner: 0-5% weekly increase.
- Intermediate: 3-8% weekly increase.
- Advanced: 5-10% only if history supports it.

Deload:

- Every 3rd or 4th week reduce volume 15-25%.
- Deload also triggered by high fatigue, missed workouts, injury notes, high monotony.

Peak volume:

- Based on current volume, goal distance, available days, plan length, and safety constraints.
- Do not force marathon-level long runs if weekly volume cannot support them.

Rules:

- Long run should usually stay under 30-35% of weekly volume.
- For recreational marathon plans, long run cap should default to 28-32 км or 2.5-3 hours depending on athlete level.
- For half marathon plans, long run peak usually 16-22 км if supported.
- For 5K/10K, long run supports aerobic base but should not dominate plan.

### 10.4. Weekly workout composition

2 days/week:

- 1 easy or quality-lite.
- 1 long easy.

3 days/week:

- 1 easy.
- 1 quality or steady.
- 1 long easy.

4 days/week:

- 2 easy/recovery.
- 1 quality.
- 1 long.

5 days/week:

- 2-3 easy/recovery.
- 1-2 quality depending phase.
- 1 long.

6-7 days/week:

- Only for experienced runners.
- Include recovery days and optional rest.
- No more than 2 high-intensity sessions per week by default.

### 10.5. Workout types

Recovery:

- Purpose: restore, maintain habit.
- Intensity: easy HR/RPE.
- Duration: short.

Easy:

- Purpose: aerobic base.
- Intensity: conversational.
- Most weekly time should be here.

Long:

- Purpose: endurance and durability.
- Intensity: mostly easy.
- Avoid high-intensity long runs for beginners.

Strides:

- Purpose: neuromuscular speed and economy.
- Short fast relaxed repeats, full recovery.

Tempo/Threshold:

- Purpose: endurance near threshold.
- Work duration: conservative 10-40 minutes depending level.
- Avoid if threshold zones unknown and user is beginner.

Intervals:

- Purpose: VO2max/aerobic power.
- Repeats usually 3-5 minutes for interval pace.
- Total hard time conservative 10-25 minutes.

Hills:

- Purpose: strength, mechanics.
- Good replacement for speed work if pace zones unreliable.

Race pace:

- Purpose: specificity.
- Mostly later phases.

Strength:

- Purpose: injury prevention, durability.
- 2 days/week recommended by public health guidelines, but app should keep it optional and simple in MVP.

### 10.6. Periodization

Plan phases:

- Base: consistency, volume, easy running, strides.
- Build: introduce threshold/intervals, controlled long run progression.
- Specific: race pace, goal-specific workouts.
- Taper: reduce volume, keep controlled intensity.

Taper defaults:

- 5K/10K: 7-10 days.
- Half marathon: 10-14 days.
- Marathon: 14-21 days.

### 10.7. Adaptation engine

Triggers:

- Missed workout.
- Overdone workout.
- High fatigue score.
- High monotony/strain.
- Injury or pain note.
- Plan adherence below threshold for 2 weeks.
- Race date changed.

Rules:

- Missed easy run: skip or small reschedule, do not stack.
- Missed quality run: skip if another quality is within 72 hours.
- Overdone hard run: next quality becomes easy or reduced.
- High fatigue: reduce weekly volume 10-25% and remove high-intensity.
- Pain note: suggest rest/easy and show safety message.
- Low adherence: regenerate plan from current baseline.

Output:

- `adaptation_summary`: plain language explanation.
- `changes`: list of workout modifications.
- `risk_before`, `risk_after`.
- New `plan_version`.

## 11. Analytics insights logic

Insights should be explainable and source-backed.

Examples:

- `Объем растет стабильно`: weekly volume increased within safe planned range and adherence is high.
- `Слишком много интенсивности`: time above threshold exceeds planned share or easy/hard distribution is skewed.
- `Темп на easy runs улучшился`: easy-run weighted pace improved while HR stayed similar or lower.
- `Возможная усталость`: ATL rising faster than CTL, TSB negative, high monotony, recent overdone workouts.
- `Данные неполные`: zones estimated or imports pending confirmation.

Rules:

- Every insight includes `evidence` array.
- Every insight includes `confidence`.
- Do not generate fear-based medical advice.

## 12. LLM architecture

LLM use cases:

- Screenshot recognition.
- Human-readable explanations of plan and analytics.
- Optional natural language query later.

Non-negotiable rules:

- LLM never writes activity directly without validation.
- LLM output must be parsed into strict schema.
- Backend validates units and consistency.
- Unknown screenshots without provider and without template are rejected.
- API key is encrypted and never returned to frontend.

Recognition prompt requirements:

- Return JSON only.
- Include field confidence.
- Include uncertainty notes.
- Do not infer invisible fields unless explicitly marked estimated.

## 13. UI/UX requirements

Visual style:

- Dark-first compact admin.
- Near-black/zinc background.
- Orange primary/accent.
- Thin borders.
- Minimal shadows.
- Dense tables/cards.
- shadcn/ui new-york style via local components.

Interaction principles:

- Important calculations have `Why?` popovers.
- Dangerous actions require confirmation.
- Empty states are actionable.
- API errors are visible and retryable.
- Mobile layout avoids document horizontal overflow.
- Tables scroll inside containers only.

Components needed:

- DataTable with sorting, filters, pagination.
- MetricCard.
- ChartCard.
- ZoneBadge.
- QualityBadge.
- WorkoutCard.
- PlanWeekAccordion.
- ImportCandidateEditor.
- CalculationExplainer.
- SafetyAlert.
- Command/search palette optional.

Charts:

- Weekly volume bar chart.
- Load line chart.
- Pace/HR split chart.
- Zone stacked bars.
- Plan volume curve.
- Race prediction table.

## 14. Testing and verification

### 14.1. Calculation tests

Add unit tests for:

- Pace, speed, weighted pace.
- Distance/time/pace validation tolerance.
- Tanaka HRmax.
- Karvonen HRR zones.
- VDOT from known race examples.
- Riegel prediction.
- ACSM kcal estimate.
- sRPE load.
- TRIMP.
- CTL/ATL/TSB EWMA.
- Monotony/strain.
- Zone distribution aggregation.
- Plan volume progression and deload weeks.

### 14.2. Backend tests

- Auth and user isolation.
- Activity CRUD.
- Import candidate lifecycle.
- LLM provider encryption and masking.
- Plan generation safety gates.
- Plan adaptation.
- Analytics endpoints.

### 14.3. Frontend tests

- Dashboard loads with demo user.
- Activities filter/sort/pagination.
- Activity detail charts and validation warnings.
- Import review and confirm flow.
- Plan builder wizard.
- Plan detail adaptation flow.
- Mobile burger menu.
- No horizontal overflow on 375px width.

### 14.4. Acceptance criteria

- No calculation is shown without method and units.
- No LLM-recognized unknown screenshot enters analytics without validation and confirmation.
- Plan generator never creates impossible weekly schedules for selected availability.
- Plan generator respects rest spacing between hard workouts.
- Analytics uses weighted averages for pace and HR where appropriate.
- User can override estimated zones.
- All user data is isolated by token user.

## 15. Implementation roadmap

### Phase 1. Foundation and calculations

- Add database migrations mechanism.
- Add athlete profile and measurements.
- Add calculation service with tested formulas.
- Add zones service.
- Add derived metrics table.
- Expand analytics summary with methods and confidence.

### Phase 2. Activity and import professionalism

- Add activity create/edit.
- Add activity detail endpoint with validation.
- Change import flow to candidate confirmation.
- Add duplicate detection.
- Add frontend Imports page and Activity Detail page.

### Phase 3. Analytics hub

- Add performance results.
- Add VDOT and Riegel prediction endpoints.
- Add load calculation endpoints.
- Add zone distribution endpoints.
- Build Analytics Overview, Performance, Load, Zones pages.

### Phase 4. Professional planning

- Add structured workout blocks.
- Add plan preview endpoint.
- Replace MVP generator with baseline-aware generator.
- Add plan risk flags.
- Add plan versioning.
- Build Plan Builder Wizard and Plan Detail.

### Phase 5. Adaptation loop

- Add workout feedback.
- Add planned vs actual matching.
- Add adaptation engine.
- Add calendar view.
- Add dashboard today card and readiness summary.

### Phase 6. Integrations and polish

- Add CSV export/import.
- Add Telegram login production mode.
- Add provider test endpoint.
- Add audit log.
- Add documentation for formulas and source references.

## 16. Source references

Primary sources to cite in implementation docs and calculation metadata:

- ACSM Position Stand: Garber et al., 2011, Quantity and quality of exercise for developing and maintaining cardiorespiratory, musculoskeletal, and neuromotor fitness, Medicine and Science in Sports and Exercise, DOI `10.1249/MSS.0b013e318213fefb`, PMID `21694556`.
- CDC adult physical activity guidelines: at least 150 minutes moderate or 75 minutes vigorous aerobic activity weekly plus 2 days strength training.
- Tanaka, Monahan, Seals, 2001, Age-predicted maximal heart rate revisited, Journal of the American College of Cardiology, DOI `10.1016/S0735-1097(00)01054-8`, PMID `11153730`.
- Karvonen et al., 1957, heart rate reserve method for exercise prescription.
- Daniels and Gilbert oxygen power/VDOT model, later popularized in Daniels Running Formula and V.O2 calculator ecosystem.
- Riegel, Pete, Athletic Records and Human Endurance, American Scientist, 1981, race prediction power law.
- Foster et al., 2001, A new approach to monitoring exercise training, Journal of Strength and Conditioning Research, PMID `11708692`.
- Banister impulse-response and TRIMP training load model lineage.
- Seiler and Kjerland, 2006, Quantifying training intensity distribution in elite endurance athletes, Scandinavian Journal of Medicine and Science in Sports, DOI `10.1111/j.1600-0838.2004.00418.x`, PMID `16430681`.

## 17. Current project delta

Текущий проект уже имеет:

- FastAPI backend.
- PostgreSQL via Docker Compose.
- User/session auth with dev login and Telegram placeholder.
- Activities, segments, split blocks.
- Import batches and screenshot sources.
- Goals.
- LLM provider settings with encrypted keys.
- MVP planning generator.
- React/Vite/Tailwind compact admin UI.

Главные недостающие части:

- Athlete profile and physiological inputs.
- Calculation engine with unit tests and source metadata.
- Professional activity detail and import confirmation.
- Zones and training load services.
- Performance/race results/VDOT predictions.
- Baseline-aware planning generator.
- Plan versioning and adaptation engine.
- Calendar and workout feedback.
- Full analytics pages.

## 18. Definition of done for the professional MVP

Professional MVP считается готовым, когда:

- Пользователь проходит onboarding и получает estimated/manual zones.
- Пользователь импортирует скриншоты, проверяет candidate и подтверждает activity.
- Activity detail показывает validation, splits, source screenshots and derived metrics.
- Analytics показывает volume, pace, HR, zones, load, performance predictions.
- Plan Builder создает safe plan with risk flags and preview.
- Plan Detail показывает structured weeks and workout blocks.
- Workout completion собирает RPE and notes.
- Adaptation engine корректирует план после missed/overdone/high fatigue cases через preview/apply flow с audit history; missed/skipped key workouts допускают отдельный reschedule path с явным diff.
- Все формулы покрыты тестами и имеют source references.
- UI стабилен на desktop and mobile.
