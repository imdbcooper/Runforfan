# Runforfan Professional Documentation

Версия документа: 2026-07-02

Статус продукта: alpha, локальное/dev-окружение

Основные языки интерфейса: RU/EN

Основной UI: `http://127.0.0.1:5173/app/`

Backend API: `http://127.0.0.1:8080/api`

## 1. Назначение продукта

Runforfan - это персональная система для беговых тренировок, импорта активностей, построения тренировочных планов, анализа нагрузки и контроля готовности. Приложение ориентировано на объяснимые расчеты и безопасную адаптацию тренировок, а не на автоматические медицинские рекомендации.

Главные задачи продукта:

- хранить беговые активности, сплиты, интервальные блоки, источники импорта и derived metrics;
- импортировать тренировки из скриншотов и CSV с обязательной валидацией;
- вести профиль спортсмена, зоны HR/pace/RPE, измерения и safety-факторы;
- строить планы под цели, гонки и базовую подготовку;
- сопоставлять плановые тренировки с фактическими активностями;
- показывать analytics, performance, load/recovery, zone distribution и goal readiness;
- объяснять ключевые формулы через source/method/confidence metadata.

Runforfan не является медицинским устройством, не ставит диагнозы и не заменяет врача или тренера. Safety warnings в интерфейсе являются спортивными эвристиками и сигналами для осторожности.

## 2. Карта документации

- `README.md` - быстрый старт, текущий статус проекта и исторический контекст.
- `Docs/runforfan-professional-specification.md` - продуктовая спецификация и acceptance criteria.
- `Docs/runforfan-professional-documentation.md` - этот документ, практический профессиональный справочник по реализации.
- `Docs/alpha-tester-guide.html` - автономный HTML-гайд для альфа-тестеров со скриншотами.
- `Docs/assets/alpha-guide/*.png` - локальные скриншоты app UI для HTML-гайда.

## 3. Архитектура

### 3.1. Слои системы

| Слой | Технологии | Назначение |
|---|---|---|
| Frontend | React, Vite, TypeScript, Tailwind v4, shadcn-style UI | App UI `/app/`, формы, таблицы, графики, i18n, alpha workflows, online-first PWA shell |
| Backend | FastAPI, SQLAlchemy 2, Pydantic | API, валидация, расчеты, импорты, auth, planning, analytics |
| Database | PostgreSQL 16 | Пользователи, активности, планы, зоны, goals, imports, audit, daily loads |
| Storage | Local upload directory | Скриншоты импорта и batch sources |
| LLM integrations | OpenAI-compatible, Anthropic | Vision recognition неизвестных скриншотов |
| Legacy prototype | Python local server, static HTML, SQLite | Исторический локальный прототип, не основной admin UI |

### 3.2. Основные backend-файлы

| Область | Файл |
|---|---|
| FastAPI app и startup | `backend/app/main.py` |
| ORM-модели | `backend/app/models/entities.py` |
| Pydantic-схемы | `backend/app/schemas/common.py` |
| Базовые формулы | `backend/app/services/calculations.py` |
| Activity derived metrics | `backend/app/services/activity_metrics.py` |
| Training zones | `backend/app/services/zones.py` |
| Zone analytics | `backend/app/services/zone_analytics.py` |
| Load/recovery | `backend/app/services/training_load.py` |
| Analytics | `backend/app/services/analytics.py` |
| Performance | `backend/app/services/performance.py` |
| Goals | `backend/app/services/goals.py` |
| Planning | `backend/app/services/planning.py` |
| Calendar | `backend/app/services/calendar.py` |
| Recognition | `backend/app/services/recognition.py` |
| CSV import | `backend/app/services/csv_imports.py` |
| Data export/delete | `backend/app/services/data_management.py` |
| Migrations runner | `backend/app/db/migrations/runner.py` |

### 3.3. Основные frontend-файлы

| Область | Файл |
|---|---|
| Основное SPA и все экраны | `frontend/src/App.tsx` |
| React entrypoint и service worker registration | `frontend/src/main.tsx` |
| API client и типы | `frontend/src/lib/api.ts` |
| RU/EN i18n | `frontend/src/lib/i18n.ts` |
| Metric cards и explanations | `frontend/src/components/ui/metric-card.tsx` |
| Таблицы | `frontend/src/components/ui/data-table.tsx` |
| Calculation explainer | `frontend/src/components/ui/calculation-explainer.tsx` |
| Тема и CSS tokens | `frontend/src/index.css` |
| PWA manifest | `frontend/public/manifest.webmanifest` |
| Online-first service worker | `frontend/public/sw.js` |
| Offline fallback page | `frontend/public/offline.html` |
| PWA icons | `frontend/public/icons/*` |

## 4. Запуск и окружение

### 4.1. Backend и база данных

Основной dev-запуск через Docker Compose:

```bash
docker compose up --build
```

Ожидаемые сервисы:

| Сервис | Адрес |
|---|---|
| Backend | `http://127.0.0.1:8080` |
| Healthcheck | `GET http://127.0.0.1:8080/health` |
| API prefix | `http://127.0.0.1:8080/api` |
| PostgreSQL external | `127.0.0.1:55432` |

Ключевые переменные окружения:

| Переменная | Назначение |
|---|---|
| `RUNFORFAN_DATABASE_URL` | SQLAlchemy URL PostgreSQL |
| `RUNFORFAN_APP_ENV` | `development`, `production`, test modes |
| `RUNFORFAN_AUTO_CREATE_SCHEMA` | Автосоздание схемы в dev |
| `RUNFORFAN_DEMO_SEED` | Demo user/data seed |
| `RUNFORFAN_UPLOAD_DIR` | Директория загрузок screenshots |

Startup backend выполняет:

- создание upload directory;
- создание схемы при включенном dev-флаге;
- запуск migrations runner;
- demo seed при включенном флаге;
- backfill derived activity metrics;
- backfill daily training loads.

### 4.2. Frontend

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

App UI открывается по адресу:

```text
http://127.0.0.1:5173/app/
```

Production build check:

```bash
cd frontend
npm run build
```

Vite настроен с `base: "/app/"`, поэтому frontend должен обслуживаться под `/app/`.

Online-first PWA:

- `frontend/public/manifest.webmanifest` задает `id`, `scope` и `start_url` как `/app/`, поэтому установленное приложение не пытается контролировать корень сайта.
- `frontend/src/main.tsx` регистрирует service worker только в production build через `import.meta.env.BASE_URL`, чтобы не сломать dev-сервер.
- `frontend/public/sw.js` делает network-first navigation для `/app/` и показывает `/app/offline.html`, если сеть недоступна.
- Service worker кеширует только статические frontend assets, icons, manifest и offline fallback. `/api/*` не перехватывается и не кешируется.
- PWA не является offline-first: Telegram login, profile, plans, imports, recognition, calculations, LLM provider settings и exports требуют backend.

### 4.3. Auth в alpha/dev

Поддерживаются три режима:

- Telegram bot registration для production: пользователь открывает бота, нажимает `/start`, backend получает webhook, создает или обновляет `User`, отправляет одноразовую ссылку `/app/?telegram_login_code=...`, а frontend обменивает code на Bearer session;
- Telegram Login Widget для production-like auth;
- dev login/demo user в development или при включенном `VITE_ENABLE_DEV_LOGIN=true`.

Frontend хранит access token в `localStorage` под ключом `runforfan_token`. При 401 token очищается, и пользователь возвращается на login gate.

## 5. Продуктовые принципы

### 5.1. Safety first

Runforfan показывает предупреждения о риске, усталости, высокой нагрузке, слишком частых hard sessions и проблемах профиля. Эти предупреждения не являются медицинскими заключениями.

Safety-факторы:

- injury notes;
- health conditions;
- recovery status `tired`, `strained`, `injured`;
- conservative mode;
- high fatigue balance;
- high monotony/strain;
- hard sessions closer than 48h;
- too much intensity;
- too few recovery days.

### 5.2. Explainability first

Расчеты должны иметь объяснение, источник или метод:

- `method` - алгоритм или источник значения;
- `source_reference` - формула, модель или imported source;
- `confidence` - `low`, `medium`, `high`;
- `computed_at` - время расчета;
- `input_hash` - hash входных данных для derived metrics.

В UI часть формул раскрывается через `Why?` на карточках метрик.

### 5.3. User confirmation first

LLM-recognition не должен безоговорочно превращать скриншот в activity. Pipeline строится вокруг кандидата, валидации и подтверждения пользователя:

1. upload screenshots;
2. template recognition или LLM recognition;
3. candidate payload;
4. backend validation;
5. user correction if needed;
6. confirmation or rejection;
7. activity creation;
8. optional auto-match to planned workout.

### 5.4. Multi-user isolation

Все пользовательские сущности привязаны к `user_id`. API ownership tests проверяют, что пользователь не может читать или изменять чужие activities, plans, goals, imports, providers и profile data.

## 6. Экранная карта admin UI

| Раздел | Назначение | Основные проверки |
|---|---|---|
| Dashboard | Сегодняшняя готовность, активный план, неделя, последние активности | Active plan, readiness, current week, quick links |
| Activities | Таблица активностей, manual activity, detail, validation, derived metrics | Create/edit activity, validation report, splits/blocks |
| Imports | Screenshots/CSV import, candidate review, history, match candidates | LLM/template recognition, confirm/reject, CSV duplicates |
| Calendar | План и факт по дням, warnings, reschedule, match | Date range, hard-session warnings, link activity/workout |
| Analytics | Summary, trends, best efforts, insights | Period filters, weighted metrics, VDOT source, insights |
| Load & Recovery | Daily/weekly load, CTL/ATL/TSB, monotony, strain, warnings | Materialization, backfill, fatigue warnings |
| Zones Analytics | HR/pace/RPE distribution, Seiler split, planned vs actual | Coverage, low-intensity target, classification notes |
| Performance | Race/time trial results, VDOT, Riegel predictions, PBs | Add result, noisy source, predictions, pace zones |
| Goals & races | Race goals, habits, readiness, milestones | Goal lifecycle, predicted range, plan adherence |
| Profile & zones | Athlete profile, completeness, safety, zones, measurements | Save profile, recalc zones, manual HR override |
| Plans | Plan builder, preview, saved plans, workouts, adaptation | Preview/create/activate, feedback, completion, recommendations |
| Settings & data | LLM providers, integrations, export, delete data, audit log | Provider test, secrets hidden, export, danger zone |

## 7. API reference summary

Все endpoints ниже находятся под `/api`, кроме `/health`.

### 7.1. Auth

| Method | Endpoint | Назначение |
|---|---|---|
| `POST` | `/auth/dev-login` | Dev/demo login |
| `POST` | `/auth/telegram` | Telegram auth callback |
| `GET` | `/auth/telegram/bot-link` | Public bot start link для login gate |
| `POST` | `/auth/telegram/webhook` | Telegram Bot API webhook, обрабатывает `/start` |
| `POST` | `/auth/telegram/start-code` | Обмен одноразового bot code на session token |

### 7.2. Activities

| Method | Endpoint | Назначение |
|---|---|---|
| `POST` | `/activities` | Создать activity |
| `GET` | `/activities` | Список activities текущего пользователя |
| `GET` | `/activities/{activity_id}` | Детали activity |
| `PATCH` | `/activities/{activity_id}` | Обновить activity |
| `GET` | `/activities/{activity_id}/validation` | Validation report |
| `DELETE` | `/activities/{activity_id}` | Удалить activity |

### 7.3. Imports

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/imports` | История import batches |
| `POST` | `/imports/screenshots` | Upload screenshots |
| `POST` | `/imports/{batch_id}/confirm` | Confirm candidate и создать activity |
| `PATCH` | `/imports/{batch_id}/candidate` | Исправить candidate до confirm |
| `POST` | `/imports/{batch_id}/reject` | Reject candidate |
| `POST` | `/imports/csv` | CSV import |

Ограничения import:

- screenshot extensions: `.jpg`, `.jpeg`, `.png`, `.webp`;
- максимум 6 screenshots на batch;
- CSV extensions: `.csv`, `.txt`;
- CSV size limit: 5 MB;
- duplicate detection: `started_at + distance_km + duration_seconds`.

### 7.4. Analytics, load, zones

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/analytics/summary` | Summary metrics |
| `GET` | `/analytics/timeseries` | Timeseries by metric/granularity |
| `GET` | `/analytics/insights` | Insight cards |
| `GET` | `/analytics/load/daily` | Daily load |
| `GET` | `/analytics/load/weekly` | Weekly load |
| `GET` | `/analytics/load/fitness-fatigue` | CTL/ATL/TSB series |
| `GET` | `/analytics/load/warnings` | Load/recovery warnings |
| `GET` | `/analytics/load/materialization` | Daily load materialization status |
| `POST` | `/analytics/load/backfill` | Rebuild materialized daily loads |
| `GET` | `/analytics/zones/distribution` | Zone distribution and planned vs actual |

### 7.5. Performance

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/performance/results` | Race/time trial results |
| `POST` | `/performance/results` | Add performance result |
| `GET` | `/performance/vdot` | Current VDOT source |
| `GET` | `/performance/predictions` | Equivalent race predictions |
| `GET` | `/performance/pbs` | Personal bests |

### 7.6. Goals

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/goals` | List goals |
| `POST` | `/goals` | Create goal |
| `PATCH` | `/goals/{goal_id}` | Update goal/status |
| `POST` | `/goals/{goal_id}/complete` | Mark complete |
| `DELETE` | `/goals/{goal_id}` | Delete goal |

### 7.7. Planning

| Method | Endpoint | Назначение |
|---|---|---|
| `POST` | `/planning/preview` | Preview plan without saving |
| `POST` | `/planning/generate` | Create draft/active plan |
| `GET` | `/planning/plans` | List plans |
| `GET` | `/planning/current-week` | Current active week |
| `GET` | `/planning/plans/{plan_id}` | Plan detail |
| `GET` | `/planning/plans/{plan_id}/adherence` | Plan adherence |
| `GET` | `/planning/plans/{plan_id}/weeks` | Week grouping |
| `POST` | `/planning/plans/{plan_id}/adapt` | Adapt plan |
| `GET` | `/planning/plans/{plan_id}/recommendations` | Coach recommendations |
| `POST` | `/planning/plans/{plan_id}/recommendations/preview` | Preview recommendation diff |
| `POST` | `/planning/plans/{plan_id}/recommendations/apply` | Apply recommendations |
| `GET` | `/planning/plans/{plan_id}/recommendations/audit` | Recommendation audit |
| `GET` | `/planning/plans/{plan_id}/versions` | Plan versions |
| `POST` | `/planning/plans/{plan_id}/activate` | Activate plan |
| `PATCH` | `/planning/plans/{plan_id}` | Rename/update status |
| `POST` | `/planning/plans/{plan_id}/duplicate` | Duplicate plan |
| `DELETE` | `/planning/plans/{plan_id}` | Delete plan |
| `PATCH` | `/planning/workouts/{workout_id}` | Update workout status/date |
| `GET` | `/planning/workouts/{workout_id}` | Workout detail |
| `POST` | `/planning/workouts/{workout_id}/complete` | Manual completion |
| `GET` | `/planning/workouts/{workout_id}/feedback` | Get feedback |
| `PUT` | `/planning/workouts/{workout_id}/feedback` | Replace feedback |
| `PATCH` | `/planning/workouts/{workout_id}/feedback` | Patch feedback |
| `GET` | `/planning/workouts/{workout_id}/match-candidates` | Activities for workout |
| `POST` | `/planning/workouts/{workout_id}/link-activity` | Link activity |
| `POST` | `/planning/workouts/{workout_id}/attach-activity` | Attach/unlink activity |
| `GET` | `/planning/activities/{activity_id}/match-candidates` | Workouts for activity |

### 7.8. Profile and zones

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/profile` | Athlete profile |
| `PUT` | `/profile` | Save profile |
| `GET` | `/profile/completeness` | Completeness/readiness |
| `POST` | `/profile/safety-check` | Safety messages |
| `GET` | `/profile/measurements` | Measurements |
| `POST` | `/profile/measurements` | Add measurement |
| `GET` | `/zones` | Current zones |
| `POST` | `/zones/recalculate` | Recalculate zones |
| `PUT` | `/zones/hr` | Manual HR override |
| `PUT` | `/zones/pace` | Manual pace zones |
| `PUT` | `/zones/rpe` | Manual RPE zones |

### 7.9. Settings and integrations

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/settings/llm-providers` | List current user's active LLM providers |
| `POST` | `/settings/llm-providers` | Create OpenAI-compatible or Anthropic provider |
| `PATCH` | `/settings/llm-providers/{provider_id}` | Update display name, base URL, model, key or default flag |
| `POST` | `/settings/llm-providers/{provider_id}/default` | Set provider as default |
| `POST` | `/settings/llm-providers/{provider_id}/test` | Run safe provider connectivity test |
| `DELETE` | `/settings/llm-providers/{provider_id}` | Soft-delete provider and rotate default if needed |
| `GET` | `/settings/integrations` | List available integrations and configuration status |

Provider API keys are encrypted by backend services and are never returned to frontend responses. Provider test executes a safe short prompt and returns `ok`, `status`, `response_ms`, `supports_vision` and a bounded message.

### 7.10. Calendar, dashboard, export, account

| Method | Endpoint | Назначение |
|---|---|---|
| `GET` | `/dashboard/summary` | Dashboard cards and readiness |
| `GET` | `/calendar` | Planned and actual events by day |
| `GET` | `/export` | JSON export without secrets |
| `GET` | `/export/activities.csv` | Activities CSV export |
| `DELETE` | `/account/data` | Delete current user data |
| `GET` | `/audit-log` | Audit log |

## 8. Data model summary

| Таблица | Назначение |
|---|---|
| `users` | Пользователь, Telegram/dev auth identity |
| `auth_sessions` | Auth sessions/tokens |
| `athlete_profiles` | Профиль спортсмена, physiology, preferences, safety |
| `athlete_measurements` | Вес, HR, VO2max, threshold measurements |
| `training_zones` | HR/pace/RPE zones, calculated or manual |
| `activities` | Основная активность |
| `activity_segments` | Splits/segments |
| `activity_split_blocks` | Split block structure |
| `activity_workout_blocks` | Interval/workout blocks |
| `activity_screenshots` | Screenshot metadata, safe source info |
| `derived_activity_metrics` | Derived metrics with method/source/hash |
| `daily_training_loads` | Materialized load, CTL/ATL/TSB, monotony, strain |
| `performance_results` | Race/time trial results |
| `screenshot_sources` | Uploaded screenshot files and source metadata |
| `import_batches` | Import batch lifecycle |
| `import_batch_sources` | Batch to source links |
| `import_recognition_attempts` | Recognition attempts and status |
| `running_goals` | Goals, races, habits, health goals |
| `training_plans` | Training plan header |
| `plan_versions` | Version snapshots |
| `training_plan_workouts` | Planned workouts |
| `planned_workout_blocks` | Planned workout structure |
| `training_plan_workout_feedback` | RPE, pain, sleep, subjective feedback |
| `training_plan_recommendation_audits` | Recommendation/apply audit |

## 9. Import lifecycle

### 9.1. Screenshot import

```text
Upload images
  -> create import batch and sources
  -> deterministic template recognition if known template
  -> vision LLM recognition if provider configured
  -> candidate JSON
  -> validation checks
  -> pending confirmation or rejection
  -> user corrections
  -> confirm candidate
  -> create activity, segments, blocks, screenshots
  -> compute derived metrics
  -> sync daily load
  -> auto-match to active plan if confident
```

Validation checks include:

- distance between 0.05 and 300 km;
- duration between 60 and 86400 seconds;
- pace between 120 and 1200 sec/km;
- HR between 40 and 230 bpm;
- imported pace consistency against distance/duration;
- segment distance sum consistency;
- workout block distance/duration consistency.

### 9.2. CSV import

CSV import supports common aliases for title, type, start time, distance, duration, calories, pace, HR, elevation and cadence. Duration can be raw seconds, `MM:SS` or `HH:MM:SS`. Dates support ISO, `YYYY-MM-DD HH:MM`, `DD.MM.YYYY HH:MM` and date-only formats. Distances above 1000 are interpreted as meters and converted to kilometers.

## 10. Planning lifecycle

### 10.1. Plan builder

Plan builder принимает:

- goal type and target distance/date/time;
- plan length 4-24 weeks;
- available days 2-7;
- current weekly volume and recent long run;
- recent race/time trial context;
- aggressiveness cap;
- intensity mode: mixed, pace, HR, RPE;
- time budget and max long run constraints;
- strength/mobility support sessions;
- injury/constraints flags.

Preview не сохраняет план. Generate создает draft или active plan.

### 10.2. Plan statuses

| Status | Значение |
|---|---|
| `draft` | План создан, но не активен |
| `active` | План используется Dashboard/Calendar/matching |
| `completed` | Завершен |
| `archived` | Архивирован |

### 10.3. Workout statuses

| Status | Значение |
|---|---|
| `planned` | Плановая тренировка |
| `rescheduled` | Перенесенная тренировка |
| `done` | Выполнена, manual completion или linked activity |
| `missed` | Пропущена |
| `skipped` | Осознанно пропущена |

### 10.4. Matching lifecycle

Activity-workout matching строится на score/confidence/reasons. Auto-match применяется только к active plan, в окне 3 дней, при score >= 0.78 и без близкого второго кандидата. Manual candidates доступны в окне 7 дней и показываются в Calendar/Plans/Imports.

## 11. Calculation reference

Этот раздел фиксирует формулы, которые критичны для документации, alpha testing и объяснения результатов пользователю.

### 11.1. Pace and speed

```text
pace_seconds_per_km = round(duration_seconds / distance_km)
speed_kmh = round(distance_km / (duration_seconds / 3600), 2)
weighted_pace = sum(duration_seconds) / sum(distance_km)
```

Используется в Activities, Analytics, Performance, Planning. Weighted pace применяется для нескольких активностей или сегментов, чтобы короткие выбросы не искажали среднее.

### 11.2. HRmax Tanaka

```text
estimated_hrmax = round(208 - 0.7 * age)
```

Источник: Tanaka, Monahan, Seals 2001. Используется как fallback, если пользователь не указал measured max HR. Confidence ниже, чем у ручного или лабораторного значения.

### 11.3. HRR zones, Karvonen

```text
heart_rate_reserve = max_hr - resting_hr
zone_boundary = resting_hr + percent * heart_rate_reserve
```

Зоны:

| Zone | %HRR | Label |
|---|---:|---|
| z1 | 30-39% | Recovery |
| z2 | 40-59% | Aerobic |
| z3 | 60-74% | Steady |
| z4 | 75-84% | Threshold |
| z5 | 85-95% | Very hard |

### 11.4. HRmax zones

```text
zone_boundary = percent * max_hr
```

Зоны:

| Zone | %HRmax | Label |
|---|---:|---|
| z1 | 60-69% | Easy |
| z2 | 70-79% | Aerobic |
| z3 | 80-87% | Steady |
| z4 | 88-92% | Threshold |
| z5 | 93-100% | Hard |

### 11.5. Lactate threshold HR zones

Границы считаются от lactate threshold HR:

| Zone | Upper boundary |
|---|---:|
| z1 | 84% LTHR |
| z2 | 89% LTHR |
| z3 | 94% LTHR |
| z4 | 99% LTHR |
| z5 | open upper |

### 11.6. Pace zones

От threshold pace in seconds per km:

| Zone | Formula |
|---|---|
| easy | threshold +45 to +95 sec/km |
| steady | threshold +20 to +44 sec/km |
| threshold | threshold -5 to +10 sec/km |
| interval | threshold -35 to -6 sec/km |
| rep | threshold -60 to -36 sec/km |

Threshold pace может быть указан в профиле или оценен из performance result через VDOT/threshold fallback.

### 11.7. RPE zones

| Zone | RPE |
|---|---|
| z1 | 0-2 |
| z2 | 3-4 |
| z3 | 5-6 |
| z4 | 7-8 |
| z5 | 9-10 |

### 11.8. VDOT

```text
time_min = duration_seconds / 60
velocity_m_min = distance_km * 1000 / time_min
vo2 = -4.60 + 0.182258 * velocity_m_min + 0.000104 * velocity_m_min^2
percent_vo2max = 0.8
  + 0.1894393 * exp(-0.012778 * time_min)
  + 0.2989558 * exp(-0.1932605 * time_min)
vdot = round(vo2 / percent_vo2max, 1)
```

Используется для race/time trial performance, best efforts, predictions и pace zone fallback. Easy runs не должны использоваться как основной VDOT source.

### 11.9. Riegel prediction

```text
predicted_time = source_time * (target_distance / source_distance) ^ 1.06
```

Confidence считается ниже, если extrapolation ratio вне диапазона `0.25..4`. Noisy или старый source result также снижает confidence.

### 11.10. ACSM running energy

```text
duration_minutes = duration_seconds / 60
speed_m_min = distance_km * 1000 / duration_minutes
grade_value = clamp(grade, 0.0, 0.2)
vo2_ml_kg_min = 0.2 * speed_m_min + 0.9 * speed_m_min * grade_value + 3.5
kcal = vo2_ml_kg_min * weight_kg / 1000 * 5 * duration_minutes
```

Используется только для running-like activities, если импортированные calories отсутствуют и известен вес пользователя.

### 11.11. HR TRIMP, Banister

```text
hrr = max_hr - resting_hr
hr_ratio = clamp((average_hr - resting_hr) / hrr, 0, 1)

male:   coefficient = 0.64, exponent = 1.92
female: coefficient = 0.86, exponent = 1.67

trimp = duration_minutes * hr_ratio * coefficient * exp(exponent * hr_ratio)
```

TRIMP доступен только при наличии resting HR, max HR, average HR и sex `male` или `female`. При `other/unspecified` backend не рассчитывает HR TRIMP и использует fallback methods.

### 11.12. sRPE load

```text
session_rpe_load = duration_minutes * rpe_0_10
```

Используется, если linked workout имеет feedback RPE. Это простая субъективная модель нагрузки.

### 11.13. Training load fallback priority

Backend выбирает метод нагрузки в таком порядке:

1. imported `aerobic_training_stress`;
2. `srpe`, если есть linked workout feedback;
3. `hr_trimp`, если хватает HR/profile inputs;
4. support duration load для strength/OFP/mobility/prehab/cross training;
5. pace-based fallback;
6. `0.0`, если расчет невозможен.

Support load factors:

| Type marker | Factor |
|---|---:|
| strength | 0.75 |
| OFP | 0.70 |
| core | 0.50 |
| mobility | 0.25 |
| prehab | 0.25 |
| cross training | 0.90 |

Pace fallback:

```text
factor = clamp(threshold_pace / activity_pace, 0.75, 1.6)
load = duration_minutes * factor
```

### 11.14. CTL, ATL, TSB

EWMA:

```text
alpha = 1 - exp(-1 / tau_days)
ewma_today = ewma_yesterday + alpha * (load_today - ewma_yesterday)
```

Параметры:

- CTL tau = 42 days;
- ATL tau = 7 days;
- TSB = CTL - ATL.

Есть warmup warning, если истории нагрузки меньше 42 дней.

### 11.15. Monotony and strain

```text
monotony = mean(daily_loads) / population_stddev(daily_loads)
strain = sum(daily_loads) * monotony
```

Если в окне меньше 2 дней или standard deviation равен 0, monotony/strain не рассчитываются.

### 11.16. Zone distribution and Seiler split

Classification priority:

1. threshold HR;
2. threshold pace;
3. HR;
4. pace;
5. RPE.

Five zones агрегируются в Seiler 3-zone split:

| Five-zone | Seiler zone |
|---|---|
| z1, z2 | low |
| z3 | moderate |
| z4, z5 | high |

Default low-intensity target: 75-85% low.

### 11.17. Analytics formulas

```text
adherence = done_workouts / planned_workouts
weighted_hr = sum(avg_hr * duration) / sum(duration with avg_hr)
weighted_pace = total_duration / total_distance
training_days_per_week = unique_training_dates / selected_weeks
```

Best efforts use whole activity when distance is within +/-5% of target or 1K segment when segment distance is close to 1 km. Targets: 1K, 5K, 10K, 21.1K.

### 11.18. Performance confidence

Race starts with high confidence, time trial starts with medium confidence. Confidence is degraded if:

- result is older than 84 days;
- terrain is trail;
- temperature >= 27 C;
- elevation gain >= 300 m;
- elevation gain per km >= 20 m/km;
- user manually marked result as noisy.

### 11.19. Goal progress and race readiness

```text
progress_percentage = clamp(done / target, 0, 1)
```

Race readiness:

- `on_track` if predicted upper bound is at or faster than target time;
- `at_risk` if predicted lower bound is slower than target time;
- `watch` for mixed signals or plan adherence below ideal;
- `unknown` if not enough data.

Predicted goal range margins:

| Confidence | Range margin |
|---|---:|
| high | +/-3% |
| medium | +/-6% |
| low/default | +/-10% |

### 11.20. Plan generation formulas

Training age:

- beginner: low history, current volume < 15 km/week, no recent long run or long run < 6 km;
- intermediate: consistent weeks >= 4, volume >= 15 km/week, recent long run >= 6 km;
- advanced: consistent weeks > 12, volume > 45 km/week, quality sessions >= 2.

Weekly growth caps:

| Level | Max weekly growth |
|---|---:|
| beginner | 5% |
| intermediate | 8% |
| advanced | 10% |

Long run shares:

| Level | Share |
|---|---:|
| beginner | 30% |
| intermediate | 33% |
| advanced | 35% |

Deload logic:

```text
every 4th non-taper week: week_volume *= 0.78
```

Taper multipliers:

| Taper length | Multipliers |
|---|---|
| 3 weeks | 0.85, 0.72, 0.60 |
| 2 weeks | 0.80, 0.65 |
| 1 week | 0.72 |

### 11.21. Workout execution score

Volume score:

```text
ratio = actual / planned
volume_score = clamp(1 - abs(ratio - 1) / 0.5, 0, 1)
```

Intensity score:

- inside target RPE range: 1.0;
- miss by 1: 0.7;
- larger miss: 0.4.

Subjective score caps:

- pain or pain_level >= 4: 0.35;
- RPE or fatigue >= 8: 0.45;
- RPE or fatigue >= 7: 0.70;
- sleep <= 3 caps at 0.75.

Final score is the average of available components. Status becomes `overdone`, `completed`, `partial` or `missed` depending on ratio and subjective/intensity signals.

## 12. Validation and constraints

### 12.1. Activity constraints

| Field | Constraint |
|---|---|
| duration | 60-86400 sec |
| distance | 0.05-300 km |
| average pace | 120-1200 sec/km |
| heart rate | 40-230 bpm |
| aerobic training stress | <= 1000 |

### 12.2. Profile constraints

| Field | Constraint |
|---|---|
| resting HR | 25-120 bpm |
| max HR | 80-240 bpm |
| threshold HR | 60-230 bpm |
| threshold pace | 120-1200 sec/km |
| VO2max | 10-100 |

### 12.3. Plan constraints

| Field | Constraint |
|---|---|
| plan length | 4-24 weeks |
| available days | 2-7 |
| weekly distance override | <= 250 km |
| max long run duration | 15-600 min |
| RPE/fatigue/soreness/sleep | 0-10 |

## 13. Security and privacy

### 13.1. Tokens

Frontend использует Bearer token. Токен хранится в browser `localStorage`. Это удобно для alpha/dev, но production окружение должно иметь строгую HTTPS-конфигурацию, корректную token expiry policy и защиту от XSS.

### 13.2. LLM provider secrets

API keys провайдеров сохраняются backend-ом и не возвращаются в frontend. UI показывает только флаги `key stored/missing`. JSON export исключает secrets.

### 13.3. Screenshot privacy

React admin UI показывает safe source metadata, но не должен раскрывать локальные filesystem paths. Экспорт данных также не должен включать локальные screenshot paths.

### 13.4. Data export and deletion

Settings предоставляет:

- JSON export без secrets;
- activities CSV export;
- danger zone для удаления пользовательских данных с подтверждением `DELETE`;
- audit log действий.

### 13.5. PWA cache boundaries

Runforfan PWA работает как online-first shell. Service worker не должен кешировать authenticated API responses, Telegram login code exchange, exports, screenshots/uploads или LLM provider settings. Пользовательские данные остаются backend-owned; offline fallback объясняет, что для работы нужен интернет.

Production nginx должен отдавать `/app/sw.js`, `/app/manifest.webmanifest`, `/app/offline.html` и `/app/icons/*` как реальные static files. Missing PWA files не должны fallback-иться в `/app/index.html`, иначе браузер получит HTML вместо service worker/manifest.

## 14. Alpha testing checklist

Минимальный smoke перед демонстрацией alpha:

- backend `/health` отвечает `ok`;
- frontend `/app/` загружается без white screen;
- dev login или Telegram login работает;
- RU/EN language toggle переключает `document.documentElement.lang` и сохраняется в localStorage;
- Dashboard показывает readiness и current week без ошибок console;
- Profile сохраняется и zones recalculated;
- Manual activity creates activity and recalculates derived metrics;
- Screenshot import создает candidate или понятный rejection;
- CSV import показывает created/duplicates/failed counters;
- Plan preview не сохраняет план;
- Plan generate создает draft/active;
- Calendar range <= 42 days работает;
- Performance result >= 3 km создает VDOT source;
- Load backfill обновляет materialization status;
- JSON/CSV export скачиваются;
- API keys не отображаются обратно;
- `/app/` устанавливается как PWA, manifest scope/start URL равны `/app/`, standalone launch открывает приложение;
- offline mode показывает понятное online-required сообщение и не показывает stale user data;
- mobile sidebar открывается и таблицы не создают horizontal page overflow.

## 15. Known limitations

- Alpha status: UX и расчеты могут изменяться.
- LLM recognition зависит от настроенного provider, модели и качества скриншота.
- Unknown screenshot без LLM provider может быть rejected.
- CTL/ATL/TSB, monotony и strain являются спортивными эвристиками.
- VDOT и Riegel predictions требуют race/time trial quality source.
- HR TRIMP требует sex `male` или `female` и корректные HR inputs.
- Pace zones требуют threshold pace или performance-derived fallback.
- Auto-match может не сработать при неоднозначных candidates.
- PWA installable, но не offline-first: без backend-соединения нельзя войти, изменить данные, импортировать скриншоты или получить актуальные расчеты.
- Legacy `app/static/*` не является основным UI.

## 16. Troubleshooting

| Симптом | Что проверить |
|---|---|
| Backend не отвечает | `docker compose ps`, logs backend, `/health`, `RUNFORFAN_DATABASE_URL` |
| DB не healthy | Docker volume, port `55432`, Postgres logs |
| Frontend показывает API ERROR | backend URL, CORS/dev proxy, token, `/health` |
| PWA не устанавливается | HTTPS, `/app/manifest.webmanifest`, `/app/sw.js`, manifest icons, scope `/app/` |
| Offline открывает старые данные | service worker не должен кешировать `/api/*`; проверить cache storage и sw version |
| Login возвращает на gate | 401, expired token, Telegram env, dev login flag |
| Screenshot rejected | provider missing, unsupported image, validation mismatch, batch history message |
| CSV failed rows | encoding, delimiter, duration/date format, required fields |
| Zones missing | profile HRmax/DOB/resting HR/threshold pace, manual override state |
| VDOT missing | нет race/time trial >= 3 km, source noisy/old, missing duration/distance |
| Load metrics missing | нет activities, no stress/HR/RPE fallback, warmup history < 42 days |
| Plan too conservative | profile conservative mode, injury flags, low history, time budget, max long run cap |
| Export contains no secrets | Expected behavior, keys intentionally omitted |

## 17. Glossary

| Термин | Значение |
|---|---|
| Activity | Фактическая тренировка или активность |
| Planned workout | Плановая тренировка внутри training plan |
| Candidate | Предварительно распознанная тренировка до подтверждения |
| Validation | Проверка согласованности distance/duration/pace/HR/segments/blocks |
| RPE | Субъективная тяжесть 0-10 |
| HR | Heart rate, пульс |
| HRmax | Максимальный пульс |
| HRR | Heart rate reserve, `HRmax - resting HR` |
| LTHR | Lactate threshold heart rate |
| Threshold pace | Темп около порога, sec/km |
| VDOT | Оценка беговой формы по Daniels/Gilbert формулам |
| Riegel | Формула эквивалентного времени на другой дистанции |
| TRIMP | Training impulse по HR и длительности |
| sRPE | Session RPE load, `duration * RPE` |
| CTL | Chronic Training Load, долгосрочная EWMA нагрузки |
| ATL | Acute Training Load, краткосрочная EWMA нагрузки |
| TSB | Training Stress Balance, `CTL - ATL` |
| Monotony | Однообразие нагрузки, `mean / stddev` |
| Strain | Недельная нагрузка с учетом monotony |
| Seiler split | 3-zone intensity split: low, moderate, high |
| Adherence | Доля выполненных плановых тренировок |
| Execution score | Оценка выполнения workout по объему, интенсивности и субъективным факторам |
| Readiness | UI-сигнал готовности: ok, watch, risk |
| Confidence | Уровень доверия к расчету или source: low, medium, high |
| PWA | Installable web app shell для `/app/`; Runforfan использует online-first режим без offline-синхронизации пользовательских данных |

## 18. Release discipline

Для каждого нетривиального изменения рекомендуется:

1. обновить или добавить тесты в backend/frontend при изменении поведения;
2. выполнить `npm run build` для frontend изменений;
3. выполнить релевантный backend test suite для backend изменений;
4. выполнить `git diff --check`;
5. провести local review перед commit;
6. обновить этот документ или alpha guide, если меняются формулы, flows, screens или safety behavior.
