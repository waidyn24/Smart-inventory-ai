# SMART INVENTORY AI

**Умная система управления товарными запасами малого магазина (Казахстан).**

![status](https://img.shields.io/badge/edition-local%20DEMO-2563eb) ![stack](https://img.shields.io/badge/stack-Next.js%20%2B%20FastAPI%20%2B%20PostgreSQL-0d9488)

> Это полностью функционирующий **локальный DEMO MVP**, а не сертифицированная касса для реальной торговли. Показания прогнозов основываются на явно обозначенных синтетических данных и фактических действиях пользователя. Интеграций Kaspi/1C/UMAG/фискализация нет.

## Быстрый старт (Windows 10/11, macOS, Linux)

Необходимы [Docker Desktop](https://www.docker.com/products/docker-desktop/) с включённым Docker Compose v2 и интернет на **первую** сборку для скачивания образов и npm/pip-зависимостей.

### Windows PowerShell

```powershell
cd smart-inventory-ai
Copy-Item .env.example .env
# Для локального демо можно сохранить DEMO_PASSWORD; SESSION_SECRET рекомендуется заменить.
docker compose up --build -d
# Проверить запуск
Docker compose ps
```

### macOS / Linux

```bash
cd smart-inventory-ai
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Открыть:

- **Приложение:** http://localhost:3000
- **Интерактивная документация API (Swagger):** http://localhost:8000/docs
- **Проверка API:** http://localhost:8000/health

На первой установке PostgreSQL создаёт таблицы Alembic migration v1 и заполняется воспроизводимыми demo-данными (60 SKU и 90 дней синтетического спроса). На повторных запусках существующие данные сохраняются.

### Демо-учётные записи

| Роль | Логин | Пароль |
|---|---|---|
| Владелец | `owner@demo.kz` | `Demo2026!` |
| Менеджер | `manager@demo.kz` | `Demo2026!` |
| Кассир | `cashier@demo.kz` | `Demo2026!` |
| Сотрудник склада | `warehouse@demo.kz` | `Demo2026!` |

Если пароль меняли в `.env` после создания базы, у seed-пользователей останется исходный пароль. В этой версии смена пароля через UI не предусмотрена.

**Пробный штрихкод молока:** `2000000000015`. На кассе введите его и нажмите `Enter`. Другая возможность — камера браузера с разрешением (нужен `localhost` / HTTPS); при отсутствии камеры доступен ручной ввод и поиск. Поддерживаемые форматы определяются @zxing/browser; QR-URL не считается SKU, GS1 Digital Link разбор на этом этапе не реализован.

## Что умеет система

- **Обзор:** реальная сегодня POS-выручка, валовая маржа до расходов, стоимость физического остатка, риски дефицита и скорых сроков. График синтетической демо-истории отдельно от POS.
- **Товары:** создание/редактирование, SKU, GTIN, категории, цены, поставщики, срок хранения и кратность упаковки.
- **Касса:** сканер USB/камера/ручной ввод, корзина, транзакционное списание FEFO, возвраты, защита от повтора.
- **Остатки:** журнал движений, партии, остаток/доступный запас, списание партии и корректировки отдельными документами, экспорт CSV.
- **Приёмка:** номер накладной, партия, дата годности, источник, запись в ledger.
- **Инвентаризация:** snapshot всех SKU, пересчёт, отклонения, утверждение, запрет повторного применения и конфликт изменённого баланса.
- **Закупки:** объяснимый прогноз заказа по lead time + review + safety, supplier minimum / pack multiple / perishability, PO draft → approved → partial_received/received.
- **Прогноз AI:** базовая недельная/скользящая модель по истории, качество данных, WAPE/MAE для достаточной истории, сценарный диапазон (не обученная нейросеть).
- **Digital Twin:** моделирование запасов и денег на 7/14/30 дней под тремя сценариями с budget и спросом ±20%.
- **Ассистент:** локальные вопросы к расчётному движку (без API LLM), числовые ответы только из базы.
- **Настройки:** роли, аудит, импорт CSV, полный демонстрационный сброс для owner.

### Критическое замечание для инвесторов и преподавателя

В промпте предполагалась система уровня production. Этот релиз закрывает **полный рабочий локальный сценарий MVP**, но не весь production scope (подключение сторонних сервисов, advanced demand ML, мульти-магазинная ERP, фискальные сертификаты, Redis и edge-case конкуренции при инициализации SKU). См. подробные ограничения в `docs/ARCHITECTURE.md`.

## Проверка целостности

### Бэкенд

```bash
docker compose exec api pytest -q tests
```

В текущем наборе: 14 тестов на товар/штрихкод, списание POS, возврат, идемпотентность, oversell rejection, инвентаризацию, FEFO, формулу 71, бюджет, tenant isolation, низкую уверенность, PO, RBAC/CSRF и списание просроченного товара.

### UI end-to-end (опционально)

После запуска Docker, в отдельном терминале при наличии Node.js:

```bash
cd frontend
npm install
npx playwright install chromium
npm run test:e2e
```

Три браузерных сценария в `frontend/e2e/smoke.spec.ts` доступны для последующего запуска. **В сборочной среде эти UI-тесты не были выполнены** (npm registry недоступен). Логика backend и TSX-синтаксис были проверены отдельно. До сдачи или реального внедрения рекомендуется обязательно проверить браузерные сценарии на своей машине.

### Перезапуск

```bash
docker compose down
# Данные в PostgreSQL сохраняются

docker compose up -d
```

**Полностью удалить демо-базу и развернуть заново (все данные будут потеряны):**

```bash
docker compose down -v
docker compose up --build -d
```

## Локальный backend без Docker (SQLite)

Для отдельных тестов достаточно Python 3.12+; проект создан для PostgreSQL, но ORM поддерживает SQLite для демо:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

Frontend отдельно:

```bash
cd frontend
npm install
npm run dev
```

Тогда тоже откройте `http://localhost:3000`. Команды `python -m app.seed` и `alembic upgrade head` следует исполнять из папки backend. При первом запуске manual seed применяет `create_all`; Docker использует Alembic.

## Импорт и экспорт

Экспорт — `Остатки → CSV`. Импорт — `Настройки → CSV`, UTF-8:

- Товары: `sku,barcode,name,category,cost,price` (только новые SKU; импорт не перезаписывает имеющиеся карточки).
- Исторический спрос: `sku,date,quantity,stockout` (YYYY-MM-DD; следует выбирать даты/SKU, которых нет в demo seed). Импорт спроса не создаёт фискальных продаж.
- Повторный **идентичный** файл распознаётся по SHA-256; дубли невозможны из-за ограничения по датам/SKU.

Примеры в `samples/`.

## Структура проекта

```text
smart-inventory-ai/
├── backend/
│   ├── app/
│   │   ├── db.py               # SQLAlchemy engine/session
│   │   ├── models.py           # ORM schema + indexes
│   │   ├── main.py             # API, RBAC, cookie/CSRF, workflows
│   │   ├── engine.py           # FEFO, ledger, forecast, orders, twin
│   │   └── seed.py             # 60 SKU / 90d reproducible data
│   ├── alembic/                # versioned migration (initial v1)
│   ├── tests/test_workflows.py # backend integration tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── app/                    # Next.js App Router
│   ├── components/DashboardApp.tsx
│   ├── lib/api.ts
│   ├── e2e/smoke.spec.ts       # browser test scenarios
│   ├── Dockerfile
│   ├── package.json
│   └── tailwind.config.js
├── docs/
│   ├── ARCHITECTURE.md
│   └── DEMO_SCRIPT.md
├── samples/
├── .env.example
├── docker-compose.yml
└── README.md
```

## Этапы и критерии приёмки

| Этап | Критерий | Реализация |
|---|---|---|
| P0 | Проект + Docker + база + вход | Реализовано; Docker build требует внешних npm/pip registry |
| P1 | Товар → приёмка → касса → возврат → инвентаризация | Реализовано, серверная интеграция проверена |
| P2 | Аналитика → прогноз → количество заказа | Реализовано на deterministic baseline, 14 тестов |
| P3 | PO → approve → receive; budget → twin; assistant | Реализовано, серверные endpoints проверены |
| P4 | Responsive UI + документация + проверки | Реализован UI; TSX parse checked; браузерная сборка и Playwright не проверены здесь |

**Управление рисками:** Используйте только для учебного проекта/демо; прежде чем управлять реальным бизнесом, добавьте TLS, реальные резервные копии, регистрацию и управление пользователями, надежные интеграции с ККМ и бухгалтерией, нагрузочные тесты PostgreSQL, контроль операций по товарам с маркировкой и бухгалтерскую сверку.


## Исправление TypeScript build (11.10.2026)

В оригинальной первой версии архива обнаружена ошибка сборки в `frontend/components/DashboardApp.tsx` (строка с категориями, `Type unknown is not assignable to Key`). В этом архиве исправлена явная типизация списка категорий `string[]`.

Если используете ранее распакованный проект, можно заменить только файл `frontend/components/DashboardApp.tsx` из этого исправленного архива или запустить `FIX_TYPES_WINDOWS.bat` в корне старого проекта (при наличии обоих файлов FIX_TYPES_WINDOWS.bat и FIX_TYPES_WINDOWS.ps1). После этого: `docker compose up --build -d`.

Серверная логика не изменялась. Полная сборка Next.js в этой среде не подтверждена (npm registry недоступен). Если появится следующая ошибка TypeScript, пришлите лог для следующего исправления.


## Интернет-развёртывание (Render / Railway)

Готовая облачная конфигурация находится в корне проекта: `Dockerfile`, `render.yaml`, `railway.toml`, `cloud/start-online.sh`. Подробная пошаговая инструкция на русском: [README_ONLINE_RU.md](README_ONLINE_RU.md). **Обычная загрузка ZIP в Netlify Drop не запускает API и БД.**
