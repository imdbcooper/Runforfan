# Runforfan

Runforfan - персональная система для хранения беговых активностей, импорта тренировок из скриншотов и CSV, построения тренировочных планов, анализа нагрузки, зон, performance, goals и readiness. Проект находится в alpha-стадии: основной UI расположен в React/Vite admin frontend, backend построен на FastAPI/PostgreSQL, старый локальный прототип в `app/` сохранен как legacy.

## Документация

- `Docs/runforfan-professional-documentation.md` - полноценная профессиональная документация: архитектура, запуск, API, data model, product flows, safety, формулы, validation, troubleshooting и glossary.
- `Docs/alpha-tester-guide.html` - отдельный автономный HTML-гайд для альфа-тестеров со скриншотами, сценариями проверки, формулами, criteria checklist и шаблоном баг-репорта.
- `Docs/assets/alpha-guide/` - локальные скриншоты admin UI, используемые HTML-гайдом.
- `Docs/runforfan-professional-specification.md` - продуктовая спецификация и acceptance criteria.

## Полноценный backend

Добавлен новый backend-слой в `backend/`. Старый локальный прототип в `app/` сохранен, но новая основа проекта теперь рассчитана на многопользовательское приложение.

Стек backend:

- Python.
- FastAPI.
- PostgreSQL.
- SQLAlchemy 2.
- Pydantic.
- Docker Compose.

Запуск backend:

```bash
docker compose up backend
```

Backend будет доступен по адресу:

```text
http://127.0.0.1:8080
```

PostgreSQL в Docker Compose проброшен на локальный порт `55432`, чтобы не конфликтовать с уже занятым `5432`.

Проверка здоровья:

```text
GET /health
```

Основные backend-модули:

- `backend/app/main.py` — FastAPI-приложение и подключение роутеров.
- `backend/app/models/entities.py` — SQLAlchemy-модели.
- `backend/app/api/routes/` — API-роутеры.
- `backend/app/services/` — бизнес-логика: auth, analytics/load, performance, recognition, planning, calculations, profile/zones.
- `backend/app/seed/demo.py` — перенос текущих тренировок в demo-user.
- `backend/app/storage/uploads/` — uploads volume для скриншотов.
- `frontend/` — новый React/Vite frontend на Tailwind и shadcn-style компонентах.

Роутеры backend:

- `POST /api/auth/dev-login` — dev/demo вход.
- `POST /api/auth/telegram` — Telegram login validation.
- `GET /api/activities` — тренировки текущего пользователя.
- `GET /api/activities/{id}` — одна тренировка.
- `DELETE /api/activities/{id}` — удаление тренировки.
- `GET /api/dashboard/summary` — агрегированный Dashboard: активный план, текущая неделя, readiness, alerts, recent activities.
- `GET /api/calendar?from=&to=` — календарь плановых workouts активного плана и фактических activities за диапазон до 42 дней.
- `POST /api/imports/screenshots` — загрузка скриншотов и запуск LLM/template recognition pipeline.
- `GET /api/imports` — история импортов.
- `GET /api/goals` — цели пользователя.
- `POST /api/goals` — создание цели.
- `DELETE /api/goals/{id}` — удаление цели.
- `GET /api/analytics/summary?from=&to=` — обзорная аналитика пользователя за период: KPI, weighted pace, HR, adherence, consistency, best efforts и VO2max/VDOT estimate.
- `GET /api/analytics/timeseries?metric=&granularity=&from=&to=` — недельные/месячные ряды для distance, duration, workouts, pace, HR и load.
- `GET /api/analytics/insights?from=&to=` — 3-5 explainable analytics notes для выбранного периода.
- `GET /api/analytics/load/daily?from=&to=` — daily load points с primary method, hard/recovery flags и sRPE fallback metadata.
- `GET /api/analytics/load/weekly?from=&to=` — weekly load, monotony, strain, hard sessions, recovery days и long-run share.
- `GET /api/analytics/load/fitness-fatigue?from=&to=` — CTL/ATL/TSB EWMA heuristics с объяснением.
- `GET /api/analytics/load/warnings?from=&to=` — load/recovery alerts: monotony, fatigue balance, intensity share, hard-session spacing и recovery days.
- `GET /api/analytics/zones/distribution?granularity=&from=&to=` — HR/pace/RPE zone distribution, Seiler 3-zone split, time-in-zones buckets и planned-vs-actual intensity split.
- `GET /api/performance/results` — сохраненные race/time trial результаты текущего пользователя.
- `POST /api/performance/results` — добавить race/time trial результат с условиями, noisy flag и optional activity link.
- `GET /api/performance/vdot` — VDOT estimate из race/time trial source, threshold trend и pace zones.
- `GET /api/performance/predictions` — Riegel equivalent race predictions с confidence/extrapolation warnings.
- `GET /api/performance/pbs` — personal bests по стандартным дистанциям.
- `GET /api/profile` — профиль спортсмена текущего пользователя.
- `PUT /api/profile` — обновление физиологических параметров, порогов и safety-настроек.
- `GET /api/profile/completeness` — оценка полноты данных для расчетов.
- `POST /api/profile/safety-check` — safety warnings для планировщика.
- `GET /api/profile/measurements` — история измерений спортсмена.
- `POST /api/profile/measurements` — добавление измерения и обновление профиля.
- `GET /api/zones` — расчетные и сохраненные зоны по пульсу, темпу и RPE с threshold/VDOT fallback metadata.
- `POST /api/zones/recalculate` — пересчитать и сохранить расчетные зоны.
- `PUT /api/zones/hr` — заменить ручные HR-зоны.
- `PUT /api/zones/pace` — заменить ручные pace-зоны.
- `PUT /api/zones/rpe` — заменить ручные RPE-зоны.
- `POST /api/planning/preview` — безопасный Plan Builder preview без записи в БД: baseline, volume curve, intensity split и risk flags.
- `POST /api/planning/generate` — генерация тренировочной программы.
- `GET /api/planning/current-week` — текущая календарная неделя активного плана с today/next workout и adherence.
- `GET /api/planning/plans` — список программ.
- `GET /api/planning/plans/{id}` — детальная программа с workouts, adherence и weekly adherence.
- `PATCH /api/planning/plans/{id}` — обновить название или статус программы (`draft/active/completed/archived`).
- `POST /api/planning/plans/{id}/duplicate` — создать draft-копию программы без linked activities/feedback.
- `DELETE /api/planning/plans/{id}` — удалить неактивную программу.
- `GET /api/planning/plans/{id}/adherence` — агрегированное и недельное соблюдение плана.
- `GET /api/planning/plans/{id}/recommendations` — read-only coach recommendations по adherence, missed workouts и planned-vs-actual load.
- `POST /api/planning/plans/{id}/recommendations/preview` — preview безопасных автоматических корректировок без изменения плана.
- `POST /api/planning/plans/{id}/recommendations/apply` — применить preview/apply корректировки к будущим незавершенным workouts и записать audit.
- `GET /api/planning/plans/{id}/recommendations/audit` — история примененных coach adjustments для плана.
- `POST /api/planning/plans/{id}/activate` — сделать программу активной.
- `GET /api/planning/workouts/{id}` — детальная planned workout card со структурой, feedback и execution score.
- `PATCH /api/planning/workouts/{id}` — обновить дату, статус или привязанную фактическую тренировку.
- `POST /api/planning/workouts/{id}/complete` — вручную завершить workout, создать manual activity, сохранить фактические метрики и feedback.
- `GET /api/planning/workouts/{id}/feedback` — получить субъективный feedback по planned workout.
- `PUT /api/planning/workouts/{id}/feedback` — заменить RPE/fatigue/pain/sleep/weather/notes и обновить execution score в выдаче плана.
- `PATCH /api/planning/workouts/{id}/feedback` — частично обновить workout feedback без сброса незаданных полей.
- `GET /api/planning/workouts/{id}/match-candidates` — кандидаты фактических тренировок для planned workout.
- `POST /api/planning/workouts/{id}/link-activity` — привязать фактическую тренировку к planned workout и отметить `done`.
- `POST /api/planning/workouts/{id}/attach-activity` — алиас привязки фактической тренировки для Workout Detail completion flow.
- `GET /api/planning/activities/{id}/match-candidates` — planned workout candidates для активности.

Авторизация:

- Основной целевой вариант — Telegram login.
- Для разработки есть `POST /api/auth/dev-login`, который создает/возвращает `Demo Runner`.
- Все пользовательские API используют Bearer token.

AI provider settings:

- Пользователь сам добавляет provider/model/api key в интерфейсе.
- Поддержаны `OpenAI compatible` и `Anthropic`.
- API-ключи не возвращаются на frontend и хранятся зашифрованно через Fernet.
- Один provider можно пометить как default.
- Recognition pipeline берет default provider текущего пользователя.

API настроек AI:

- `GET /api/settings/llm-providers` — список provider-настроек текущего пользователя.
- `POST /api/settings/llm-providers` — добавить provider.
- `POST /api/settings/llm-providers/{id}/default` — сделать provider дефолтным.
- `DELETE /api/settings/llm-providers/{id}` — отключить provider.

Импорт скриншотов в новом backend:

- Если настроен LLM с vision-моделью, backend отправляет скрины на распознавание.
- После LLM выполняются sanity-checks: дистанция, длительность, темп, пульс, сумма сегментов.
- Если данные проходят проверку, создается тренировка.
- Если LLM не настроен, backend принимает только поддержанные template fallback-сценарии. Сейчас поддержан Huawei interval template для `scrins/training3`; неизвестные скрины возвращают `rejected_no_llm_template`.
- Это сделано специально, чтобы не загрязнять аналитику ошибочными тренировками.
- Новый frontend содержит страницу `Imports`: загрузка нескольких скриншотов, результат recognition, auto-match с активным планом и ручной match review, если уверенной авто-привязки нет.

Профиль, расчеты и зоны:

- Профиль спортсмена хранит дату рождения, пол, рост, вес, timezone/locale, пульс покоя, HRmax, lactate threshold HR/pace, conservative mode и injury notes.
- История измерений хранится отдельно в `athlete_measurements` и может обновлять актуальные поля профиля.
- `GET /api/profile/measurements` отдает bounded timeline с `limit`/`offset` и включает legacy `lactate_threshold_measurements`, чтобы старые импортированные пороги были видны рядом с новыми ручными измерениями.
- Расчеты вынесены в `backend/app/services/calculations.py` и возвращают `value`, `unit`, `method`, `confidence`, `source_reference`.
- Source reference map для расчетов: pace/speed/weighted pace and HRmax zones use `ACSM Position Stand 2011, PMID 21694556`; HRmax estimate uses `Tanaka, Monahan, Seals 2001, PMID 11153730`; HRR zones use `Karvonen et al. 1957 heart-rate reserve method`; threshold HR zones use `Lactate-threshold heart-rate zone model`; threshold pace zones and VDOT use `Daniels/Gilbert oxygen power VDOT model`; race predictions use `Riegel 1981 race prediction power law`; sRPE, monotony and strain use `Foster et al. 2001 session RPE, PMID 11708692`; HR TRIMP and CTL/ATL/TSB use `Banister impulse-response fitness/fatigue model`; RPE zones use `Modified Borg CR10 session-RPE scale`.
- HR-зоны считаются через HRR/Karvonen, если есть HRmax и пульс покоя; иначе через HRmax/Tanaka-derived estimate при наличии даты рождения.
- Pace-зоны считаются от lactate threshold pace.
- Ручные зоны сохраняются отдельно и имеют приоритет над расчетными зонами соответствующего типа.
- При изменении полей профиля, влияющих на зоны, сохраненные расчетные зоны инвалидируются и пересчитываются из актуальных входов.

Миграции backend:

- Для локальной разработки по умолчанию включен `RUNFORFAN_AUTO_CREATE_SCHEMA=true`, поэтому пустая база может быть создана через SQLAlchemy metadata.
- Новые таблицы profile/measurements/zones также создаются явной версионированной миграцией `20260607_0001_profile_measurements_zones` через `schema_migrations`.
- Для production/deploy сценария можно выставить `RUNFORFAN_AUTO_CREATE_SCHEMA=false` и полагаться на migration runner вместо ad-hoc `create_all`.

Планировщик программ:

- Первая версия — гибридная архитектура.
- Rule-based слой создает безопасный черновик программы: легкие, интервальные, темповые, steady/RPE и длинные тренировки.
- Планировщик использует профиль спортсмена, completeness, safety-check, последние тренировки и доступные HR/pace зоны.
- Если включен conservative mode, указаны injury notes, история короче 14 дней или зоны недостаточно точные, hard workouts заменяются аэробной/RPE работой.
- Описание каждой тренировки содержит target по pace/HR zone, а если точных зон нет — fallback по RPE.
- У planned workouts есть календарная дата, статус `planned/done/missed/skipped/rescheduled`, связь с фактической тренировкой и adherence summary.
- Plan Builder preview перед созданием черновика показывает baseline за 6 недель, median текущего объема, recent long run, training age level, недельную volume curve, intensity split и safety/risk flags.
- Wizard inputs учитывают target time/priority, preferred weekdays, time budget, HR/pace/RPE/mixed intensity mode, injury/no-hard constraints, max long run distance/duration, terrain и recent race context.
- Confirm flow поддерживает создание draft-плана или создание сразу active-плана с архивированием предыдущего active.
- Plan Detail показывает header с goal/status/current week/target time, недельные summary, planned vs actual volume chart, intensity split, structured workout blocks, purpose/safety notes, matching/reschedule/link controls, manual completion form и adaptation history.
- API поддерживает активацию, переименование, архивирование, завершение, дублирование и удаление неактивных планов, обновление статусов planned workouts, ручную привязку фактических тренировок и динамический поиск match candidates.
- Matching учитывает близость даты, сходство дистанции и тип тренировки: interval-структуру, long/easy/tempo/steady эвристики.
- После импорта скриншотов новая активность автоматически связывается с активным планом только при высоком и однозначном score; спорные совпадения остаются кандидатами для ручного выбора.
- Adherence analytics показывает completion rate, distance completion rate, linked/unlinked выполненные тренировки, предупреждения и недельный breakdown.
- Coach recommendations дают подсказки и безопасный preview/apply: удержать объем, снизить следующую неделю, осторожно перенести ключевую тренировку или не повышать интенсивность при safety gate. Применение меняет будущие незавершенные workouts; исключение — missed/skipped key workout может быть переведен в `rescheduled` на новую дату. Каждое применение сохраняет audit history.
- Workout feedback сохраняет RPE, fatigue, pain, sleep quality, weather и notes для выполненных/пропущенных workouts; plan output показывает volume score, intensity score, adherence status и subjective risk рядом с workout card.
- High pain/fatigue/RPE feedback за последние 14 дней усиливает coach recommendations и может дать `reduce_intensity` для следующей hard workout.
- Dashboard summary объединяет активный план, текущую неделю, readiness signals, pending imports, профильные safety alerts и последние активности для стартовой страницы.
- Calendar показывает planned workouts, фактические activities по timezone профиля, linked/unlinked state, inline match/reschedule, быстрые статусы missed/skipped и предупреждения о hard sessions ближе 48 часов.
- Analytics Overview показывает выбор периода, KPI, weekly/monthly trends, best efforts, consistency, explainable insights и VO2max/VDOT estimate с confidence/source.
- Training Load & Recovery показывает daily/weekly load, CTL/ATL/TSB, monotony/strain, hard-session spacing, recovery days и explainable load alerts.
- Zones Analytics показывает HR/pace/RPE zones, 3-zone Seiler distribution, 5-zone detailed distribution, time-in-zones by week/month и planned-vs-actual intensity split.
- Performance Analytics хранит race/time trial results, считает VDOT только из eligible hard sources, показывает Riegel predictions, PBs, threshold trend и pace zones derived from threshold/VDOT.
- LLM-слой предусмотрен для будущих пояснений, адаптации и корректировок.
- Поддерживаются разные цели и дистанции: 5K, 10K, полумарафон, марафон и custom distance.

## Новый frontend

Новый frontend находится в `frontend/`.

Стек frontend:

- React.
- Vite.
- TypeScript.
- Tailwind CSS 4 через `@tailwindcss/vite`.
- shadcn/ui-style компоненты, добавленные в код проекта.

Запуск frontend:

```bash
cd frontend
npm install
npm run dev
```

Frontend будет доступен по адресу:

```text
http://127.0.0.1:5173
```

Так как Vite `base` настроен на `/app/`, рабочий адрес приложения:

```text
http://127.0.0.1:5173/app/
```

Сборка frontend:

```bash
cd frontend
npm run build
```

Страницы нового frontend:

- Панель: today/next workout, current week, readiness alerts и recent activities.
- Тренировки.
- Imports.
- Calendar: week/month range view до 42 дней для плана и факта по дням.
- Аналитика.
- Load & Recovery: daily/weekly load, CTL/ATL/TSB, monotony, strain, hard spacing и recovery alerts.
- Zones Analytics: HR/pace/RPE distribution, Seiler 3-zone split, time-in-zones buckets и planned-vs-actual intensity split.
- Performance: race/time trial results, VDOT, Riegel predictions, PBs, threshold trend и pace zones.
- Profile & zones.
- Планы: Plan Builder wizard preview/generate, create draft/create active, Plan Detail, список программ, actions и workout execution/matching.
- AI настройки.

Страница `AI настройки` позволяет пользователю добавить OpenAI-compatible или Anthropic provider, выбрать модель, указать base URL и сохранить API key.

Страница `Profile & zones` позволяет редактировать физиологические параметры, видеть полноту профиля, safety warnings, расчетные HR/pace зоны с method/source/confidence metadata и добавлять измерения.

Страница `Imports` позволяет загрузить до 6 скриншотов одной тренировки, увидеть статус recognition, созданную activity, auto-linked planned workout или кандидатов для ручной привязки.

UI-стиль frontend:

- compact dark-first admin shell.
- Desktop sidebar 14rem.
- Mobile burger menu/sheet.
- Sticky topbar высотой около 48px.
- Черный/zinc фон и orange primary/accent.
- OKLCH CSS tokens.
- Тонкие borders, почти без shadows.
- Плотные таблицы и карточки в стиле shadcn/ui `new-york`.

## Что уже обработано

В папке `scrins/` лежат исходные скриншоты тренировок и измерения порога.

- `scrins/photo_2026-06-06_17-35-22.jpg` — вкладка темпа тренировки.
- `scrins/photo_2026-06-06_17-35-21.jpg` — вкладка сегментов тренировки.
- `scrins/photo_2026-06-06_17-35-20.jpg` — подробности тренировки.
- `scrins/photo_2026-06-06_17-35-08.jpg` — измерение лактатного порога.
- `scrins/training2/photo_2026-06-06_18-13-29.jpg` — вкладка темпа второй тренировки.
- `scrins/training2/photo_2026-06-06_18-13-30.jpg` — вкладка сегментов второй тренировки.
- `scrins/training2/photo_2026-06-06_18-13-32.jpg` — подробности второй тренировки.
- `scrins/training3/photo_2026-06-06_23-23-46.jpg` — вкладка темпа интервальной тренировки.
- `scrins/training3/photo_2026-06-06_23-23-49.jpg` — вкладка структурных сегментов интервальной тренировки.
- `scrins/training3/photo_2026-06-06_23-23-53.jpg` — подробности интервальной тренировки.

Из них внесены данные по трем тренировкам `Бег на улице`, включая интервальную тренировку `3 x 2 км`, и одному измерению лактатного порога.

Сейчас в базе:

| Дата | Дистанция | Длительность | Средний темп | Средний пульс | Сегменты |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 июня 2026, 20:13 | 10.27 км | 01:06:31 | 6'29"/км | 141 уд/мин | 11 |
| 31 мая 2026, 17:45 | 5.23 км | 00:28:27 | 5'26"/км | 158 уд/мин | 6 |
| 6 июня 2026, 20:16 | 11.74 км | 01:14:02 | 6'18"/км | 152 уд/мин | 12 + 8 интервальных блоков |

## Файлы базы

- `data/schema.sql` — схема SQLite-базы.
- `data/seed.sql` — данные, вручную извлеченные со скриншотов.
- `data/runforfan.sqlite` — готовая SQLite-база.
- `scripts/init_db.py` — скрипт пересборки базы из `schema.sql` и `seed.sql`.
- `app/server.py` — локальный Python-сервер с API и раздачей интерфейса.
- `app/static/index.html` — страница списка тренировок.
- `app/static/activity.html` — страница детального разбора тренировки.
- `app/static/analytics.html` — страница аналитики и статистики.
- `app/static/goals.html` — страница целей пользователя.
- `app/static/import.html` — страница загрузки скриншотов.
- `app/static/styles.css` — стили интерфейса.
- `app/static/app.js` — загрузка данных из API, отрисовка страниц и обработка действий пользователя.

Пересобрать базу можно командой:

```bash
python3 scripts/init_db.py
```

В окружении нет системной команды `sqlite3`, поэтому база создается через стандартный Python-модуль `sqlite3`.

## Интерфейс просмотра

Добавлен простой локальный веб-интерфейс для просмотра тренировок и измерений лактатного порога. Интерфейс разделен на страницу списка тренировок и отдельную страницу детального разбора.

Запуск:

```bash
python3 app/server.py
```

После запуска открыть в браузере:

```text
http://127.0.0.1:8000/
```

Основные страницы:

- `/` — список тренировок с фильтром по месяцам.
- `/activities` — тот же список тренировок.
- `/activity?id=<id>` — детальная страница конкретной тренировки.
- `/analytics` — аналитика и статистика.
- `/goals` — цели пользователя и прогресс.
- `/import` — загрузка скриншотов и попытка распознавания.

Что показывает список тренировок:

- Сводные карточки: количество тренировок, общая дистанция, лучший темп лактатного порога, пульс лактатного порога.
- Фильтры по месяцам, например `май 2026` и `июнь 2026`.
- Карточки тренировок: дата, дистанция, длительность, средний темп, средний пульс, аэробный стресс и количество сегментов.
- Кнопку удаления тренировки. Удаление также удаляет сегменты, сплиты и связи со скриншотами.

Что показывает страница тренировки:

- Карточку тренировки: дата, дистанция, длительность, средний темп, средний пульс, калории, скорость, каденс, шаги.
- Таблицу сегментов: номер километра, дистанция, время, темп, пульс, каденс.
- Графические бары темпа по километрам.
- Сплит-блоки по 5 км.
- Карточку измерения лактатного порога: пороговый пульс, пороговый темп, длительность, средний пульс, средний темп, каденс.
- Ссылки на исходные скриншоты, из которых взяты данные.

Что показывает аналитика:

- Общий объем.
- Средний темп по общему времени и дистанции.
- Самую длинную тренировку.
- Средний пульс.
- Объемы по месяцам.

Что показывает страница целей:

- Форму добавления цели.
- Типы целей: забег, километры за период, количество тренировок, длинная тренировка, личная причина.
- Расчет прогресса по сохраненным тренировкам.
- Удаление цели.

Что делает страница импорта:

- Загружает JPG, PNG или WebP скриншоты.
- Сохраняет загруженные файлы в `uploads/`.
- Создает запись импорта в базе.
- Если настроен LLM, отправляет скриншоты на распознавание и пытается создать тренировку.
- Если LLM не настроен или недоступен, сохраняет скрины как `fallback_pending` для ручной обработки позже.

Настройка LLM-распознавания через переменные окружения:

- `RUNFORFAN_LLM_URL` — URL OpenAI-compatible chat completions endpoint.
- `RUNFORFAN_LLM_MODEL` — модель с поддержкой изображений.
- `RUNFORFAN_LLM_API_KEY` — API-ключ, если нужен.
- `RUNFORFAN_LLM_TIMEOUT` — таймаут запроса в секундах, по умолчанию `45`.

API сервера:

- `GET /` — страница списка тренировок.
- `GET /analytics` — страница аналитики.
- `GET /goals` — страница целей.
- `GET /import` — страница загрузки скриншотов.
- `GET /activity?id=<id>` — страница детального разбора тренировки.
- `GET /api/activities` — список тренировок с сегментами, сплитами и источниками-скриншотами.
- `GET /api/lactate-thresholds` — список измерений лактатного порога с источником-скриншотом.
- `GET /api/import-batches` — история импортов скриншотов.
- `POST /api/import-screenshots` — загрузка скриншотов и запуск LLM/fallback обработки.
- `DELETE /api/activities/<id>` — удаление тренировки.
- `GET /api/goals` — список целей.
- `POST /api/goals` — создание цели.
- `DELETE /api/goals/<id>` — удаление цели.
- `GET /scrins/<file>` — просмотр исходного скриншота.
- `GET /uploads/<file>` — просмотр загруженного скриншота.

Интерфейс адаптивный: на мобильных экранах раскладка становится одноколоночной, а горизонтальная прокрутка остается только у таблицы сегментов.

## Единицы измерения

- Все длительности хранятся в секундах.
- Все темпы хранятся в секундах на километр.
- Дистанция хранится в километрах.
- Пульс хранится в ударах в минуту.
- Каденс хранится в шагах в минуту.
- Длина шага хранится в сантиметрах.
- Набор и спуск высоты хранятся в метрах.
- Калории хранятся в килокалориях.

Примеры перевода:

- `01:06:31` хранится как `3991` секунд.
- `6'29"/км` хранится как `389` секунд на километр.
- `5'24"/км` хранится как `324` секунды на километр.

## Таблица `screenshot_sources`

Хранит исходные скриншоты, из которых были получены данные.

Поля:

- `id` — внутренний идентификатор источника.
- `file_path` — путь к скриншоту в проекте.
- `screen_type` — тип экрана, например `workout_pace_tab`, `workout_segments_tab`, `workout_details_tab`, `lactate_threshold_details_tab`.
- `captured_at` — дата и время файла скриншота, взятые из имени файла.
- `notes` — короткое описание, что видно на скрине.

## Таблица `training_activities`

Хранит общую информацию о тренировке.

Поля:

- `id` — внутренний идентификатор тренировки.
- `activity_type` — тип активности, сейчас `outdoor_run`.
- `title` — название активности, сейчас `Outdoor run`.
- `started_at` — дата и время старта тренировки, сейчас `2026-06-01 20:13:00`.
- `distance_km` — дистанция, сейчас `10.27` км.
- `duration_seconds` — длительность, сейчас `3991` секунд.
- `calories_kcal` — калории, сейчас `862` ккал.
- `average_pace_seconds_per_km` — средний темп, сейчас `389` секунд на км.
- `fastest_pace_seconds_per_km` — самый быстрый темп, сейчас `359` секунд на км.
- `average_speed_kmh` — средняя скорость, сейчас `9.26` км/ч.
- `average_cadence_spm` — средний каденс, сейчас `177` шаг/мин.
- `average_stride_cm` — средний шаг, сейчас `87` см.
- `steps_count` — количество шагов, сейчас `11838`.
- `average_heart_rate_bpm` — средний пульс, сейчас `141` уд/мин.
- `elevation_gain_m` — набор высоты, сейчас `23.2` м.
- `elevation_loss_m` — общий спуск, сейчас `24.4` м.
- `aerobic_training_stress` — стресс от аэробной тренировки, например `2.7` для второй тренировки.
- `aerobic_training_effect` — текстовая оценка эффекта, например `На прежнем уровне` для второй тренировки.
- `source_note` — пояснение о происхождении данных.
- `created_at` — дата добавления записи в базу.

## Таблица `activity_screenshot_sources`

Связывает тренировку с несколькими скриншотами-источниками.

Поля:

- `activity_id` — ссылка на тренировку из `training_activities`.
- `source_id` — ссылка на скриншот из `screenshot_sources`.

Для каждой тренировки привязаны 3 скрина: вкладка темпа, вкладка сегментов и подробности.

## Таблица `activity_segments`

Хранит километровые сегменты тренировки.

Поля:

- `id` — внутренний идентификатор сегмента.
- `activity_id` — ссылка на тренировку.
- `segment_index` — номер сегмента.
- `distance_km` — дистанция сегмента.
- `duration_seconds` — длительность сегмента.
- `pace_seconds_per_km` — темп сегмента.
- `average_heart_rate_bpm` — средний пульс на сегменте.
- `average_cadence_spm` — средний каденс на сегменте.

Сегменты первой тренировки:

| Сегмент | Дистанция | Длительность | Темп | Пульс | Каденс |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.00 км | 00:06:17 | 6'17"/км | 133 | 178 |
| 2 | 1.00 км | 00:06:50 | 6'50"/км | 137 | 181 |
| 3 | 1.00 км | 00:06:46 | 6'46"/км | 137 | 180 |
| 4 | 1.00 км | 00:06:55 | 6'55"/км | 138 | 177 |
| 5 | 1.00 км | 00:06:50 | 6'50"/км | 138 | 176 |
| 6 | 1.00 км | 00:06:42 | 6'42"/км | 141 | 175 |
| 7 | 1.00 км | 00:06:42 | 6'42"/км | 140 | 174 |
| 8 | 1.00 км | 00:06:28 | 6'28"/км | 143 | 176 |
| 9 | 1.00 км | 00:06:08 | 6'08"/км | 145 | 177 |
| 10 | 1.00 км | 00:05:59 | 5'59"/км | 146 | 178 |
| 11 | 0.27 км | 00:00:54 | 3'24"/км | 178 | 191 |

Сегменты второй тренировки:

| Сегмент | Дистанция | Длительность | Темп | Пульс | Каденс |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.00 км | 00:05:24 | 5'24"/км | 143 | 170 |
| 2 | 1.00 км | 00:04:30 | 4'30"/км | 176 | 178 |
| 3 | 1.00 км | 00:06:29 | 6'29"/км | 151 | 172 |
| 4 | 1.00 км | 00:05:49 | 5'49"/км | 149 | 176 |
| 5 | 1.00 км | 00:05:15 | 5'15"/км | 167 | 177 |
| 6 | 0.23 км | 00:01:00 | 4'20"/км | 181 | 181 |

## Таблица `activity_split_blocks`

Хранит крупные блоки сплитов, которые видны на вкладке темпа.

Поля:

- `id` — внутренний идентификатор блока.
- `activity_id` — ссылка на тренировку.
- `block_index` — номер блока.
- `start_km` — начало блока в километрах.
- `end_km` — конец блока в километрах.
- `distance_km` — дистанция блока.
- `duration_seconds` — длительность блока.
- `cumulative_duration_seconds` — накопленное время к концу блока.
- `notes` — пояснение.

Текущие блоки:

| Блок | Диапазон | Дистанция | Время блока | Накопленное время |
| --- | --- | ---: | ---: | ---: |
| 1, первая тренировка | 0-5 км | 5.00 км | 00:33:38 | 00:33:38 |
| 2, первая тренировка | 5-10 км | 5.00 км | 00:31:59 | 01:05:37 |
| 1, вторая тренировка | 0-5 км | 5.00 км | 00:27:27 | 00:27:27 |

## Таблица `lactate_threshold_measurements`

Хранит отдельные измерения лактатного порога.

Поля:

- `id` — внутренний идентификатор измерения.
- `source_id` — ссылка на скриншот-источник.
- `measured_at` — дата и время измерения, сейчас `NULL`, потому что на скрине дата не видна.
- `duration_seconds` — длительность измерения, сейчас `1190` секунд.
- `calories_kcal` — калории, сейчас `259` ккал.
- `average_pace_seconds_per_km` — средний темп, сейчас `389` секунд на км.
- `average_speed_kmh` — средняя скорость, сейчас `9.26` км/ч.
- `average_cadence_spm` — средний каденс, сейчас `176` шаг/мин.
- `average_stride_cm` — средний шаг, сейчас `88` см.
- `steps_count` — количество шагов, сейчас `3494`.
- `average_heart_rate_bpm` — средний пульс, сейчас `145` уд/мин.
- `elevation_gain_m` — набор высоты, сейчас `1.3` м.
- `elevation_loss_m` — общий спуск, сейчас `2.3` м.
- `threshold_heart_rate_bpm` — пульс лактатного порога, сейчас `163` уд/мин.
- `threshold_pace_seconds_per_km` — темп лактатного порога, сейчас `324` секунды на км.
- `distance_km` — дистанция измерения, сейчас `NULL`, потому что на скрине она не видна.
- `distance_is_estimated` — признак расчетной дистанции, сейчас `0`, потому что дистанция не сохранялась как расчетная.
- `notes` — пояснение по неполным данным.

## Таблица `import_batches`

Хранит группы загруженных через веб-интерфейс скриншотов и состояние распознавания.

Поля:

- `id` — внутренний идентификатор импорта.
- `status` — состояние, например `uploaded`, `recognized`, `fallback_pending`.
- `recognition_engine` — чем обрабатывали импорт, например `llm:<model>` или `fallback`.
- `recognition_message` — текстовое пояснение результата.
- `raw_result_json` — сырой ответ LLM или нормализованный JSON-кандидат.
- `created_activity_id` — ссылка на созданную тренировку, если распознавание прошло успешно.
- `created_at` — дата создания импорта.
- `updated_at` — дата последнего обновления импорта.

## Таблица `import_batch_sources`

Связывает импорт с загруженными скриншотами из `screenshot_sources`.

Поля:

- `batch_id` — ссылка на импорт.
- `source_id` — ссылка на скриншот.

## Таблица `running_goals`

Хранит пользовательские цели и причины, зачем он бегает.

Поля:

- `id` — внутренний идентификатор цели.
- `title` — название цели.
- `goal_type` — тип цели: `race`, `monthly_distance`, `workout_count`, `longest_run`, `custom`.
- `target_value` — числовая цель, если есть.
- `unit` — единица цели, например `км` или `тренировок`.
- `period_start` — начало периода цели.
- `period_end` — конец периода цели.
- `reason` — личная причина или описание.
- `status` — состояние цели, сейчас по умолчанию `active`.
- `created_at` — дата создания.
- `updated_at` — дата обновления.

## Что не внесено

- Маршрут и GPS-трек не внесены, потому что на текущих скринах нет координат.
- Дата измерения лактатного порога не внесена, потому что она не видна на скрине.
- Дистанция измерения лактатного порога не внесена, потому что она не видна на скрине.
- Недельная строка `На этой неделе уже сожжено 1 647 ккал` не внесена в тренировку, потому что это общий недельный показатель, а не метрика конкретной активности.
- Для первой тренировки эффективность и аэробный стресс не внесены, потому что нижняя часть экрана обрезана и значения не видны полностью.

## Зачем такая структура

Сейчас база сделана простой, но уже разделяет разные типы данных.

- `training_activities` подойдет для общего списка тренировок.
- `activity_segments` подойдет для анализа темпа, пульса и каденса по километрам.
- `activity_split_blocks` подойдет для сравнения крупных отрезков, например первые 5 км против вторых 5 км.
- `activity_workout_blocks` подойдет для структурных тренировок: разминка, рабочие интервалы, восстановления и заминка.
- `lactate_threshold_measurements` подойдет для отслеживания изменения лактатного порога во времени.
- `screenshot_sources` позволит понимать, из какого скрина была взята каждая запись.
- `import_batches` и `import_batch_sources` нужны для загрузки скриншотов и хранения результата LLM/fallback обработки.
- `running_goals` нужна для хранения пользовательских целей и расчета прогресса.

## Возможные следующие шаги

- Добавить больше тренировок и измерений порога.
- Добавить полноценный редактор ручных тренировочных зон в frontend.
- Добавить миграции схемы вместо `Base.metadata.create_all`.
- Добавить расчет тренда формы, прогресса и отклонений от плана.
- Добавить планировщику учет запрещенных дней, максимальной длительности long run и поверхностей.
- Добавить ручное подтверждение и редактирование LLM-распознавания перед созданием тренировки.
