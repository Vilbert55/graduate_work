# Сводка — неделя 3

Контекст и общая идея — `mentor_week2.md` §1. Здесь только **что добавилось на неделе 3**:
неделя 2 дала минимальный сквозной контур, неделя 3 закрыла пять отложенных требований
(ФТ-2, ФТ-3, ФТ-8, НФТ-3, НФТ-6) и довела движок до «полного».

---

## 1. Что закрыто (ровно то, что неделя 2 откладывала)

| Требование | Было (нед. 2) | Стало (нед. 3) |
|---|---|---|
| **ФТ-2** per-user context в письмо | executor читал только `user_id`; жанры по дефолту шаблона | SQL-`context` каждого юзера → `audience.params_by_user` → scheduler notifications мерджит поверх общих `params` при рендере. В демо у каждого письма **свои** top-3 жанра. |
| **ФТ-3** двухуровневый frequency cap | не применялся (`after_cap = matched`) | `per_rule_per_user_days` + `per_user_per_day` по `t_dispatch_history`. Повторный запуск правила → `after_cap=0`, писем нет. |
| **ФТ-8** история доставки + партиции | писался только агрегат в `t_runs` | построчная запись `t_dispatch_history`, таблица `PARTITION BY RANGE (sent_at)` по неделям, retention через `maint_dispatch_partitions`. |
| **НФТ-3** recovery | прерванный run «зависал» в `running` | при старте движок дозавершает `running`-запуски старше grace тем же `run_id`. |
| **НФТ-6** тесты | только ручной e2e | юнит-тесты бизнес-логики (`pytest`, 18 тестов) + сквозной прогон (`demo.md`). |

---

## 2. Ключевое решение недели 3 — одна атомарная транзакция

Схемы `alerting` и `notifications` живут в **одной БД** `movies`, движок ходит туда под
`postgres`. Поэтому «применить cap → записать `t_dispatch_history` →
`notifications.adm_create_task` → финализировать `t_runs` + `last_run_at`» сведено в **одну
транзакцию Postgres** (`src/services/executor.py`, фаза 3).

Это фундамент сразу двух требований:
- **идемпотентность/recovery (НФТ-3):** статус `running` ⟺ ничего не закоммичено ⟺ повтор
  с тем же `run_id` безопасен. Идемпотентный ключ `alerting:{rule_id}:{run_id}` — вторая страховка.
- **корректность cap (ФТ-3):** чтение истории и запись новых строк — в одной транзакции.

Выборка из StarRocks делается ДО транзакции (внешний запрос не держит Postgres-блокировку).

---

## 3. Карта изменений кода

| Путь | Что изменилось |
|---|---|
| `alerting-service/src/services/executor.py` | Переписан: 3 фазы (mark running → выборка StarRocks → атомарная транзакция). `_fetch_audience` (user_id + context), `_filter_by_cap`/`_blocked_by_cap` (cap, чистая логика под тесты), запись `t_dispatch_history`, per-user `params_by_user`. |
| `alerting-service/src/workers/engine.py` | `_recover_interrupted_runs` при старте + ежедневный job `maint_dispatch_partitions`. Синхронизация jobs теперь трогает только job-ы правил (`rule:*`). |
| `alerting-service/sql/functions/007_maint_dispatch_partitions.sql` | Нарезка недельных партиций + retention (`DROP` старше N дней). |
| `alerting-service/alembic/versions/0001_initial.py` | `t_dispatch_history` — партиционированная; `t_runs.is_dry_run`; первичная нарезка партиций. |
| `alerting-service/sql/functions/000_helpers.sql`, `sql/views/002_v_runs.sql` | `_enqueue_rule_run` проставляет `is_dry_run`; `v_runs` его показывает. |
| `alerting-service/tests/` | Юнит-тесты (`pytest`): контракт колонок, разбор context, frequency cap. |
| `alerting-service/src/core/config.py`, `.env.template` | `ALERTING_DISPATCH_RETENTION_DAYS`, `ALERTING_RECOVERY_GRACE_SEC`. |
| `notifications-service/src/workers/scheduler.py` | Мерджит `audience.params_by_user[user_id]` поверх `task.params` при рендере (обратносовместимо). |

> Доработка `notifications` — единственная правка чужого сервиса по сути недели 3: один
> опциональный ключ в `audience`, без изменения сигнатур публичных функций. Это сознательное
> расширение ФТ-12 (иначе ФТ-2 невыполним), согласовано.

---

## 4. Что проверено живым прогоном (`docker compose up --build`)

50 демо-юзеров → 384 события win-back → 20 под правило. Результаты:
- dry-run: `matched=20, after_cap=20, dispatched=0, is_dry_run=t`;
- боевой запуск: `dispatched=20`, 20 строк в партиции `t_dispatch_history_p2026...`, **20 писем с per-user жанрами**;
- повторный запуск: `after_cap=0`, писем нет (cap);
- recovery: вставлен `running`-запуск → рестарт движка → `running → success`, `dispatched=20`, без дублей;
- retention: партиция старше 90 дней дропается вызовом `maint_dispatch_partitions(90)`.

Юнит-тесты — `cd alerting-service && poetry run pytest` (18 passed). Линт — `ruff` чистый.

---

## 5. Чем демонстрировать

Единый файл **`demo.md`** — полная пошаговая демонстрация недель 2–3 (стек → seed → события →
refresh MV → правило → dry-run → рассылка с per-user жанрами → cap → история/партиции →
recovery → доп. сценарии → Superset). Готовые SQL — `alerting-service/examples.sql`.

---

## 6. Возможные вопросы — заготовки (в дополнение к `mentor_week2.md` §7)

- **«Почему cap может слегка „протечь“ при одновременных правилах?»** — единственный экземпляр
  движка + APScheduler; глобальный `per_user_per_day` между двумя одновременно сработавшими
  правилами теоретически даёт гонку на 1 письмо. Для MVP приемлемо (отмечено в докстринге);
  строгая защита — advisory-lock на пользователя, вынесено в улучшения вместе с leader election.
- **«Партиции своим кодом, не `pg_partman`?»** — для учебного объёма самописная
  `maint_dispatch_partitions` (~40 строк, недельная нарезка + `DROP` по retention) проще и
  прозрачнее; при росте числа партиций заменяется на `pg_partman` без смены схемы.
- **«Почему recovery не „дошлёт“ прерванный dry-run?»** — `t_runs.is_dry_run`: recovery берёт
  только боевые `running`-запуски, тестовые прогоны не порождают рассылку.
