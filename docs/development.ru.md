# TairaSearch: разработка и ручной запуск

[English version](development.md)

Этот документ содержит технические команды. Обычному пользователю достаточно
попросить агента установить и настроить проект, как описано в
[README](../README.ru.md).

## Требования и установка

- Windows, Linux или macOS;
- Python 3.11;
- Git нужен только разработчикам. Исходный архив можно скачать через GitHub →
  Code → Download ZIP.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -c "import sys; assert sys.prefix != sys.base_prefix"
.venv\Scripts\python -m pip --version
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run_demo.py
```

Linux и macOS:

```bash
python3.11 -m venv .venv
.venv/bin/python -c 'import sys; assert sys.prefix != sys.base_prefix'
.venv/bin/python -m pip --version
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_demo.py
```

Не продолжайте установку в системный Python, если проверка `sys.prefix` или
`pip --version` завершилась ошибкой. В глубоко вложенных Windows-путях Codex
стандартный `.venv` иногда создаётся неполно. Агент должен один раз повторить
установку в новой отдельной папке с более коротким путём, не удаляя неудачную
копию. Если это не помогло, создайте окружение в обычном PowerShell и снова
откройте папку в Codex.

## Основные команды

Безопасно просканировать папку, не создавая индекс:

```powershell
.venv\Scripts\python build_index.py "ПУТЬ_К_КОРПУСУ" --scan-only
```

Построение нового индекса и поиск:

```powershell
.venv\Scripts\python build_index.py "ПУТЬ_К_КОРПУСУ" --db work/index.sqlite3
.venv\Scripts\python taira_search.py search "поисковый запрос" --db work/index.sqlite3
```

Профильное исследование для Codex:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates.json --preview
```

Команда сохраняет полный `candidates.json` без потери данных и одновременно
создаёт компактный пакет первого просмотра `candidates.editorial.json`. После
выбора ID соберите все полные контексты одним вызовом, не печатая и не
перечитывая большой результат:

```powershell
.venv\Scripts\python taira_search.py research-context work/research/candidates.json --chunk-id ID1 --chunk-id ID2 --include-required-review --output work/research/review.json
```

`daily-five` сохранён для обратной совместимости. Новый сценарий использует
`research-findings` и при необходимости `--continue-from`.

Python индексирует, ранжирует, собирает контекст и выполняет воспроизводимые
проверки. Codex исследует источники, оценивает смысловую новизну и пишет
карточки. Публикация и запись в `used_finds.csv` — отдельная операция через
JSON-манифест и `record-publication`; preview журнал не меняет.

## Проверка прав запланированной публикации

До включения автоматизации выпуска выполните команду именно из окружения
запланированной задачи, а не только из интерактивного терминала:

```powershell
.venv\Scripts\python taira_search.py check-publication-access --db work/index.sqlite3 --used-finds used_finds.csv
```

Она открывает SQLite только для чтения, читает существующий журнал и проверяет
создание с атомарным переименованием двух безопасных временных файлов в каталоге
журнала. Настоящий журнал и `.used_finds.csv.lock` не открываются и не
изменяются. Успех подтверждает эффективные права процесса; одной записи пути в
`config.toml` недостаточно. Если окружение планировщика пока недоступно,
пометьте проверку как ожидающую и не активируйте публикацию.

При ошибке добавьте каталог проекта в эффективные writable roots окружения
планировщика и повторите проверку после перезапуска Codex. Альтернатива —
отдельный доступный для записи проект и безопасная перепривязка существующей
автоматизации после проверки отсутствия дубликата. Ошибка Windows `windows
unelevated restricted-token sandbox cannot enforce split writable root sets
directly` относится к окружению. Не отключайте песочницу, не удаляйте lock-файл
и не обходите синхронизацию.

## Проверки

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python run_demo.py
.venv\Scripts\python run_research_demo.py
.venv\Scripts\python run_dedup_audit.py --check
.venv\Scripts\python make_release.py --check-only
```

GitHub Actions выполняет поддерживаемый набор на Python 3.11 в Windows и Linux.
Публичная сборка создаётся только по allowlist из `release_manifest.toml`; в неё
не входят личные книги, рабочая SQLite, `used_finds.csv`, локальный профиль или
секреты.

Подробнее: [AI-демо](ai-demo.ru.md),
[onboarding](research-onboarding.ru.md),
[пополнение библиотеки](source-acquisition.ru.md).
