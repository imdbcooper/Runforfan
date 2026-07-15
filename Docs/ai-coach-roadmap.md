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

**Статус: в работе. Инкременты 6.1, 6.2, 6.3a, default-off foundation 6.3b, operational controls 6.3c и evaluation foundation 6.4 завершены; полный этап 6 не завершён.**

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

### Инкремент 6.3a: athlete-facing safety escalation boundary

- Добавлен deterministic escalation lifecycle `open → acknowledged → superseded` для существующих readiness-классов `profile_injured`, `pain_or_illness_stop` и pain-driven `rest_required`. Один спортсмен может иметь только один активный case; повторное чтение или сохранение той же классификации не сбрасывает acknowledgement, а повторное появление после supersession открывает новый case.
- Acknowledgement фиксирует только факт прочтения stop/rest guidance. Оно не снимает ограничение, не является medical clearance, не меняет профиль, workout или plan version и не запускает Telegram/LLM/preview/apply.
- В продукте пока нет staff/reviewer identity, RBAC, назначения ответственного, SLA, trusted recipient или on-call service. UI прямо сообщает об отсутствии мониторинга и гарантированного человеческого ответа; staffed review нельзя имитировать системным статусом.
- Ledger хранит только bounded trigger/severity/status, rule/source identity fingerprints и lifecycle timestamps. Pain level, illness/injury/health notes, biometrics, activity metadata, chat content и raw event payload в case/API не копируются; export исключает internal source key/fingerprint, delete удаляет case и append-oriented lifecycle events.
- Feature закрыт независимым default-off flag `RUNFORFAN_SAFETY_ESCALATION_ENABLED=false`. Выключение UI/ledger не отключает существующие readiness safety rules. Rule version: `safety-escalation-v1`. Миграция: `20260715_0032_safety_escalations`.
- Staffed review не включён этим инкрементом: operational staffing, documented coverage window, incident ownership и controlled audience остаются обязательными до enablement.

### Инкремент 6.3b: default-off staffed review foundation

- Добавлена operator-provisioned reviewer identity поверх обычного authenticated non-demo user. Self-enrollment и admin HTTP endpoint отсутствуют; grant/revoke выполняются локальным operator CLI и пишут user-scoped audit. Revoked grant terminal, active claims атомарно возвращаются в очередь.
- Athlete отдельно принимает versioned policy `safety-review-consent-v1`, затем отдельным действием создаёт request. Consent можно отозвать в любой момент; это немедленно закрывает reviewer access. Supersession safety case также закрывает consent и request.
- Request lifecycle ограничен состояниями `requested`, `claimed`, `completed`, `withdrawn`, `cancelled_consent_revoked`, `cancelled_case_superseded`, `unable_to_review`. Atomic claim сериализован row lock; self-review запрещён ORM/service/API/DB boundaries.
- До claim reviewer видит только opaque request ID/status/time. После claim доступен только bounded context: trigger, severity, case status, rule/source rule ID, local date и уже показанная athlete guidance. Athlete identity, Telegram/contact details, profile/check-in, pain/illness/injury notes, biometrics, activities, chat, raw payload и plan data не передаются.
- Completion принимает только allowlisted disposition code: `reviewed_guidance_reiterated`, `seek_local_professional_support`, `insufficient_information` или `unable_to_review`. Free text, diagnosis, medical clearance, contact и plan mutation отсутствуют.
- Actor-aware event ledger фиксирует request/claim/view/release/completion/withdrawal/supersession. PostgreSQL проверяет ownership, active consent/case/grant, legal transitions, event-state pairing, no-self-review и immutable event updates. Privacy erasure удаляет athlete lifecycle; export исключает reviewer/actor user IDs.
- UI прямо сообщает, что review асинхронный, не является emergency/on-call monitoring, не имеет гарантированного срока ответа, не даёт medical clearance и не меняет plan. Reviewer workspace появляется только после server capability check.
- Два независимых default-off kill switch: `RUNFORFAN_SAFETY_REVIEW_ENABLED=false` и `RUNFORFAN_SAFETY_REVIEW_REVIEWER_API_ENABLED=false`; athlete request доступен только при включённых escalation, review и reviewer API flags. Миграция: `20260715_0033_safety_review_workflow`. Export schema: `2026-07-15.0033`.
- Foundation нельзя включать только наличием кода. До controlled enablement нужны именованные и обученные reviewers, расписание фактической доступности без недоказанного SLA, incident owner/runbook, регулярная проверка queue age/access ledger, small allowlisted audience и подтверждённый kill-switch drill.

### Инкремент 6.3c: operational controls

- Controlled audience provision-ится только operator CLI и обязательна поверх трёх rollout flags. Enrollment terminal после revoke; self-enrollment и admin HTTP endpoint отсутствуют.
- Audience revoke атомарно переводит active request в `cancelled_audience_revoked`, пишет system event и немедленно закрывает reviewer context. Claim/revoke сериализованы единым lock order и PostgreSQL enforcement.
- Operator status выводит active grant/enrollment counts, queue counts/age buckets и aggregate access events. Отчёт не содержит request/user/reviewer IDs, context или health data и прямо не утверждает reviewer presence, monitoring, coverage или SLA.
- Runbook `Docs/safety-review-operations.md` фиксирует обязательные staffing, coverage, incident owner, observation cadence, stop criteria и kill-switch drill. Незаполненные operational поля блокируют enablement.
- Миграция: `20260715_0034_safety_review_operational_controls`. Export schema: `2026-07-15.0034`. Production rollout остаётся default-off.

### Инкремент 6.4: evaluation dashboard и incident review

- Operator-only CLI материализует immutable aggregate evaluation run за явный UTC window. Публичный admin API не добавлен, потому что отдельной admin identity/RBAC в продукте нет.
- Dashboard агрегирует latest immutable Weekly Review на athlete/week, automated progression mutations, active safety-case overlap, LLM failure classes и bounded safety-review outcomes. User/request/reviewer/plan IDs, free text и health context не сохраняются.
- Release thresholds versioned как `coach-release-thresholds-v1`. Safety violation блокирует release немедленно; малая выборка возвращает `insufficient_data`, а не pass.
- Safety и product evidence разделены. Retention и user trust пока `not_measured`, поэтому Stage 6 software gate не заявляет доказанное улучшение этих outcomes.
- PostgreSQL запрещает update/delete evaluation runs. Миграция: `20260715_0035_coach_evaluation_runs`. Evaluation version: `coach-evaluation-v1`.

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

На 15 июля 2026 года этапы 1-5 и инкременты Stage 6.1, 6.2, 6.3a, default-off foundation 6.3b, operational controls 6.3c и evaluation foundation 6.4 завершены. Полный Stage 6 остаётся в работе. Текущий код включает immutable action ledger, compensating rollback, event-driven recalculation assessments, historical resolver, deterministic Weekly Review, Hybrid Conversational Coach, normalized Recovery/Wearable Signals, controlled read-only Telegram loops, athlete-facing safety escalation boundary, bounded reviewer workflow, operator-controlled audience и immutable aggregate evaluation runs.

Stage 4 реализован как русскоязычный explanation/clarification layer с typed bounded context, strict provider output, citation/safety validation, provider repair/fallback, explicit memory confirmation и отдельным preview handoff. Turn endpoint не создаёт preview и не применяет mutation; preview повторно авторизуется сервером, а apply остаётся в существующих deterministic services. Provider attempts сохраняют только metadata/fingerprints, feature flag по умолчанию выключен. Пройдены unit, PostgreSQL, runtime, adversarial и desktop/mobile gates. Production rollout этапов 3-4 выполнен 14 июля 2026 года через отдельно собранные immutable OCI digests; Coach включён обратимым production feature flag.

Stage 5 добавляет normalized sleep duration/efficiency, HRV RMSSD и resting-HR observations с canonical units, provenance, atomic idempotent import, quality policy, freshness, personal baseline по разным дням, anomaly/conflict handling и data export/delete lifecycle. Missing/stale/low-quality data не ухудшают пользователя; qualified anomaly блокирует только progression, а subjective pain/illness/restrictions имеют приоритет. Raw vendor payloads и client labels не попадают в Athlete State или LLM context. Погода, покрытие и доступное время остаются allowlisted soft constraints без автоматической mutation.

Следующая точка продолжения: финальный deterministic experiment/replay и Stage 6 software release gate. Controlled staffed review по-прежнему заблокирован до заполнения реального staffing/coverage/incident ownership checklist; software controls не заменяют людей. Retention/trust outcome claims также заблокированы до валидного измерения.

## Порядок ближайших инкрементов

1. Зафиксировать deterministic experiment/replay corpus для ограниченного strategy space.
2. Выпустить Stage 6 software baseline после replay и kill-switch gates; controlled human review остаётся отдельным operational enablement decision.

## Release gates

- Backend tests и frontend build обязательны для каждого инкремента.
- Любое новое действие сначала выпускается read-only, затем preview, затем apply.
- Красные safety-сценарии тестируются отдельно и блокируют релиз при регрессии.
- Изменение правил получает новую `rule_version` и replay на зафиксированных сценариях.
- Production rollout начинается с наблюдаемого ограниченного контура и возможности быстрого отключения.
