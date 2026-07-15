# Roadmap AI-тренера Runforfan

## Цель

Превратить Runforfan из детерминированного планировщика в объяснимого AI-тренера с замкнутым циклом:

`состояние спортсмена -> безопасное решение -> выполнение -> обратная связь -> адаптация`.

Детерминированное доменное ядро остаётся источником истины для нагрузки, периодизации и safety constraints. LLM отвечает за диалог, объяснение, сбор контекста и выбор только среди допустимых типизированных действий.

## Принципы

- Никаких скрытых изменений программы: сначала рекомендация или preview, затем подтверждение пользователя.
- Боль, болезнь и профильные ограничения имеют приоритет над тренировочной целью и readiness-метриками.
- Ни один readiness score, HRV, ACWR, CTL/ATL/TSB или LLM-ответ не считается предсказанием травмы.
- Свободный текст не используется для медицинской диагностики.
- Каждое решение содержит причины, версию правил, использованные сигналы и audit trail.
- При неполных или устаревших данных система снижает уверенность, но не увеличивает нагрузку.
- LLM не получает прямого инструмента для записи произвольной нагрузки в план.

## Этап 1. Daily Coach Foundation

Статус: завершён 12 июля 2026 года (`cc04bbc`).

### Результат

Утренняя карточка состояния, которая даёт безопасную рекомендацию для сегодняшней тренировки без автоматического изменения плана.

### Scope

- Один check-in на локальную дату пользователя.
- Сигналы: сон, усталость, soreness, стресс, боль, симптомы болезни и комментарий.
- Детерминированные действия: выполнить по плану, выполнить консервативно, сократить, заменить лёгкой нагрузкой, отдохнуть, остановиться и обратиться за рекомендацией специалиста.
- Сохранённый snapshot рекомендации с версией правил и причинами.
- API `GET /api/readiness/today` и `PUT /api/readiness/today`.
- Карточка check-in и результата на Overview.
- Никакой мутации workout или плана.

### Acceptance criteria

- Дата определяется timezone профиля, а не временем сервера или клиента.
- Повторный `PUT` обновляет check-in этого дня, не создавая дубликат.
- Check-in и рекомендация всегда изолированы по `user_id`.
- Боль, болезнь и `recovery_status=injured` имеют максимальный приоритет.
- Рекомендация никогда не повышает объём или интенсивность относительно плана.
- Правила покрыты unit/API тестами; frontend проходит TypeScript build.

### Метрики

- Доля активных пользователей, заполнивших check-in.
- Доля дней с просмотренной рекомендацией.
- Доля рекомендаций `modify/rest`, после которых пользователь не выполнил исходную тяжёлую нагрузку.
- Ошибки сохранения и unsafe suggestion rate.

## Этап 2. Event-Driven Adaptation

Статус: завершён 13 июля 2026 года. Подтверждаемые readiness-действия реализуют канонические действия `shorten` и `replace_easy`; generic Coach Actions реализуют `skip` и `reschedule`. Все четыре действия используют server preview, explicit confirmation, stale revalidation, immutable pre/post snapshots, audit и plan version. Action-derived версии поддерживают отдельный compensating rollback preview/apply с повторной safety-проверкой. Изменившийся post-workout feedback и новый импорт активности создают persisted read-only recalculation assessment без автоматической мутации плана.

### Результат

Пользователь может одним подтверждением безопасно применить рекомендацию на сегодня и видеть последствия для недели.

### Scope

- Типизированные coach actions: `shorten`, `replace_easy`, `skip`, `reschedule`.
- Preview изменения workout и недельной нагрузки до применения.
- Plan version и rollback для каждого применённого действия.
- Причина пропуска или переноса.
- Повторная оценка после импорта активности и post-workout feedback.
- Защита от «догоняния» пропущенного объёма и stacking тяжёлых тренировок.

### Acceptance criteria

- Любая мутация проходит существующие safety constraints.
- Пользователь видит before/after и явно подтверждает изменение.
- Применение идемпотентно и оставляет audit/version record.
- После переноса автоматически проверяются 48-часовые интервалы между hard sessions.

## Этап 3. Athlete State и Weekly Review

Статус: завершён 13 июля 2026 года. Athlete State дополнен historical resolver для завершённых локальных Monday-Sunday недель, immutable Weekly Review с evidence/coverage/freshness и подтверждаемыми стратегиями `hold`, `deload`, `resume`, `conservative_progression`. Неполная реконструкция явно маркируется `partial_legacy`; она не может использоваться как положительный readiness signal. Mutation проходит persisted TTL preview, explicit confirmation, повторную safety/stale-проверку, immutable audit/event и plan version только при фактическом изменении плана.

### Результат

Единая объяснимая модель текущего состояния спортсмена и еженедельный coaching cycle.

### Scope

- Athlete State с freshness/confidence для каждого сигнала.
- Event Timeline: check-ins, workouts, activities, feedback, изменения плана и цели.
- Тренды сна, усталости, soreness, стресса, adherence и execution quality.
- Weekly review: что выполнено, что изменилось, риски и стратегия следующей недели.
- Детерминированный выбор стратегии: hold, deload, resume, conservative progression.
- Отдельное хранение фактов, вычисленных метрик, пользовательских утверждений и гипотез.

### Acceptance criteria

- Для каждого вывода можно показать исходные данные и их актуальность.
- Неполные данные не интерпретируются как хорошие данные.
- Недельная адаптация не превышает ограничения volume/intensity engine.
- Есть offline replay на исторических данных и regression fixtures.
- `hold` фиксирует auditable acknowledgement без пустой plan version; остальные стратегии меняют только будущие незавершённые workouts целевой недели.
- `deload` снижает targets на 20-30% и заменяет hard sessions на easy; `resume` не превышает prior safe baseline; progression ограничен 5%.
- Strategy-derived versions поддерживают существующий compensating rollback без переписывания исходной истории.

## Этап 4. Hybrid Conversational Coach

### Результат

Русскоязычный тренер объясняет решения, задаёт уточняющие вопросы и запускает только разрешённые coach actions.

### Scope

- LLM orchestrator с типизированными tools.
- Coach memory: только явно подтверждённые allowlisted предпочтения, coaching focus и доступные дни; health restrictions и sensitive free text не сохраняются как memory.
- Диалоги перед тренировкой, после тренировки и при пропуске.
- Explanation layer поверх детерминированного решения.
- Structured output validation, retries, provider fallback и audit.
- Защита от prompt injection в пользовательских заметках и импортированных данных.

### Разрешённые LLM-действия

- Запросить уточнение.
- Объяснить готовое доменное решение.
- Выбрать одну из стратегий, разрешённых decision engine.
- Запросить preview изменения.
- Сформировать сообщение пользователю.

### Запрещённые LLM-действия

- Диагностировать заболевание или травму.
- Обходить safety gates.
- Записывать произвольную тренировку или нагрузку напрямую.
- Применять изменение без подтверждения пользователя.

### Acceptance criteria

- Все tool calls проходят schema validation и authorization.
- Ответ LLM не может расширить разрешённый диапазон нагрузки.
- При отказе provider сохраняется полностью рабочий детерминированный UX.
- Набор adversarial и safety evals проходит установленный порог.

## Этап 5. Recovery и Wearable Signals

**Статус: завершён 14 июля 2026 года.**

### Результат

Coach учитывает автоматические recovery-сигналы, не превращая один показатель в «истину».

### Scope

- Интеграции сна, HRV, resting HR и тренировок с явным provenance.
- Normalized signal model, freshness, baseline и anomaly detection.
- Согласование wearable data с субъективным check-in.
- Confidence calibration при пропусках, конфликте и низком качестве данных.
- Контекст погоды, покрытия и доступного времени как мягкие ограничения.

### Acceptance criteria

- Пользователь видит источник и время каждого сигнала.
- Конфликт wearable/self-report приводит к уточнению или консервативному решению.
- Один wearable signal не вызывает медицинский вывод или резкую адаптацию.
- Интеграция не привязывает продукт к одному vendor.

## Этап 6. Coaching OS

**Статус: в работе. Инкременты 6.1 и 6.2 завершены; полный этап 6 не завершён.**

### Инкремент 6.1: deterministic daily brief

- Добавлен read-only Telegram-бриф поверх существующих Athlete State и daily readiness, без новой mutation authority.
- Private `/start` подтверждает destination только при открытом controlled rollout; explicit opt-in выполняется отдельно в authenticated web Settings.
- Delivery ledger идемпотентен по user/channel/type/local date/rule version и не хранит message body, chat ID, raw provider response или vendor message ID.
- Отдельный worker использует `FOR UPDATE SKIP LOCKED`, dual kill switch и fail-closed at-most-once policy для неоднозначного Telegram send boundary. Автоматический retry разрешён только после явного `429`.
- Web UI показывает rollout/link/consent state, local schedule и server-owned timezone. При закрытом rollout destination metadata не собирается, linking CTA и delivery controls скрыты.
- Rule version: `coach-daily-brief-v1`. Миграции: `20260714_0029_coach_delivery`, `20260714_0030_coach_delivery_constraints`.

### Инкремент 6.2: post-workout и weekly delivery loops

- Post-workout debrief создаётся только после отдельного explicit opt-in и только для persisted `workout_completed`/`activity_imported` facts, записанных после согласия. Matched import и completion дедуплицируются до одного сообщения по activity; позднее удаление completion отменяет ещё не отправленный brief.
- Исторический импорт получает отдельную нейтральную формулировку, а устаревшее manual completion не выдаётся за только что завершённую тренировку. Feedback notes, activity title/source note и raw event payload никогда не попадают в шаблон или ledger.
- Weekly brief материализует существующий immutable Weekly Review только за последнюю завершённую локальную Monday-Sunday неделю. `partial_legacy` всегда использует консервативный шаблон без progression language; Telegram не создаёт strategy preview и не вызывает apply.
- Daily, post-workout и weekly циклы имеют отдельные opt-in. Post-workout и weekly дополнительно закрыты независимыми default-off flags `RUNFORFAN_COACH_POST_WORKOUT_DELIVERY_ENABLED` и `RUNFORFAN_COACH_WEEKLY_REVIEW_DELIVERY_ENABLED` поверх global/worker kill switches.
- Source identity уникальна независимо от rule version: один daily brief на локальную дату, один post-workout debrief на activity и один weekly brief на локальную неделю. Delivery worker повторно проверяет global, worker, per-loop flags и consent непосредственно перед Telegram send.
- Невалидное local wall time в DST gap детерминированно переносится на первую существующую локальную минуту; ambiguous fold использует ранний offset. Rule versions: `coach-post-workout-v1`, `coach-weekly-review-v1`. Миграция: `20260715_0031_coach_event_delivery`.

### Результат

Полный ежедневный и событийный цикл персонального тренера с измеряемым качеством решений.

### Scope

- Утренний check-in, pre-workout brief, post-workout debrief и weekly review.
- Goal-aware periodization с ограниченным набором оптимизационных стратегий.
- Несколько каналов: web и Telegram.
- Human-in-the-loop для red flags, возврата после травмы и спорных сценариев.
- Эксперименты и персонализация на основе принятых действий, adherence и результата.
- Coach evaluation dashboard и incident review.

### Acceptance criteria

- Решения воспроизводимы из event timeline и версии правил.
- Есть rollback, kill switch и conservative fallback.
- Unsafe suggestion rate близок к нулю и контролируется release gate.
- Улучшаются adherence, completion quality, retention и user trust без роста pain/overload flags.

## Сквозная техническая архитектура

- `Athlete State`: актуальное состояние и уверенность в сигналах.
- `Event Timeline`: append-oriented история фактов и решений.
- `Readiness Service`: check-in и оценка текущего дня.
- `Decision Engine`: детерминированный выбор допустимой стратегии.
- `Constraint Engine`: safety, volume, intensity, spacing и recovery constraints.
- `Coach Action API`: типизированные preview/apply операции.
- `LLM Orchestrator`: диалог и tool use, но не источник истины.
- `Explanation Layer`: причины и понятное описание решения.
- `Memory`: подтверждённые предпочтения и долгосрочный контекст.
- `Evaluation/Audit`: replay, regression, safety evals и продуктовые метрики.

## Точка остановки

На 15 июля 2026 года этапы 1-5 и инкременты Stage 6.1-6.2 завершены. Полный Stage 6 остаётся в работе. Текущий код включает immutable action ledger, compensating rollback, event-driven recalculation assessments, historical resolver, deterministic Weekly Review, Hybrid Conversational Coach, normalized Recovery/Wearable Signals и controlled read-only Telegram daily/post-workout/weekly loops.

Stage 4 реализован как русскоязычный explanation/clarification layer с typed bounded context, strict provider output, citation/safety validation, provider repair/fallback, explicit memory confirmation и отдельным preview handoff. Turn endpoint не создаёт preview и не применяет mutation; preview повторно авторизуется сервером, а apply остаётся в существующих deterministic services. Provider attempts сохраняют только metadata/fingerprints, feature flag по умолчанию выключен. Пройдены unit, PostgreSQL, runtime, adversarial и desktop/mobile gates. Production rollout этапов 3-4 выполнен 14 июля 2026 года через отдельно собранные immutable OCI digests; Coach включён обратимым production feature flag.

Stage 5 добавляет normalized sleep duration/efficiency, HRV RMSSD и resting-HR observations с canonical units, provenance, atomic idempotent import, quality policy, freshness, personal baseline по разным дням, anomaly/conflict handling и data export/delete lifecycle. Missing/stale/low-quality data не ухудшают пользователя; qualified anomaly блокирует только progression, а subjective pain/illness/restrictions имеют приоритет. Raw vendor payloads и client labels не попадают в Athlete State или LLM context. Погода, покрытие и доступное время остаются allowlisted soft constraints без автоматической mutation.

Следующая точка продолжения: Stage 6.3, human-in-the-loop escalation для red flags и спорных return-to-run сценариев. Telegram остаётся read-only каналом, а любые изменения плана проходят существующий preview/apply boundary.

## Порядок ближайших инкрементов

1. Добавить human-in-the-loop escalation для red flags и спорных return-to-run сценариев.
2. Добавить evaluation dashboard, incident review и измеримые quality/safety release thresholds.
3. Сохранить goal-aware periodization в ограниченном deterministic strategy space.
4. Выпустить Stage 6 только после replay, kill-switch и controlled rollout gates.

## Release gates

- Backend tests и frontend build обязательны для каждого инкремента.
- Любое новое действие сначала выпускается read-only, затем preview, затем apply.
- Красные safety-сценарии тестируются отдельно и блокируют релиз при регрессии.
- Изменение правил получает новую `rule_version` и replay на зафиксированных сценариях.
- Production rollout начинается с наблюдаемого ограниченного контура и возможности быстрого отключения.
