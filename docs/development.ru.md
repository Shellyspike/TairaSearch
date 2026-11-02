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
.venv\Scripts\python taira_search.py search --query "поисковый запрос" --db work/index.sqlite3
```

Существующая SQLite привязана к сохранённому `corpus_root`. Попытка использовать
её с другой папкой отклоняется до изменения базы; для другой библиотеки нужна
отдельная SQLite. Декодирование учитывает BOM, UTF-8 и надёжные признаки
устаревших кодировок. Для неоднозначного корпуса TXT, Markdown или JSON можно
явно передать кодировку, например `--text-encoding cp1251`; при этом все
поддерживаемые текстовые файлы обрабатываются заново.

Профильное исследование для Codex:

```powershell
.venv\Scripts\python taira_search.py research-findings --db work/index.sqlite3 --profile research_profile.json --used-finds used_finds.csv --output work/research/candidates.json --preview
```

Команда сохраняет полный `candidates.json` без потери данных и одновременно
создаёт компактный пакет первого просмотра `candidates.editorial.json`. После
выбора ID соберите все полные контексты одним вызовом, не печатая и не
перечитывая большой результат. Связанные кандидаты вне видимого пакета
сохраняются один раз в полном JSON и добавляются автоматически:

```powershell
.venv\Scripts\python taira_search.py research-context work/research/candidates.json --chunk-id ID1 --chunk-id ID2 --include-required-review --output work/research/review.json
```

Действующий сценарий использует `research-findings` и при необходимости
`--continue-from`. Интересы и персонажи берутся из `research_profile.json`;
индексации и обычному поиску больше не нужны глобальные справочники персон,
алиасов и тем.

Правила классификации источников необязательны и относятся к конкретной
библиотеке. Если нужны явные метки `historical`, `literary` и `scholarship`,
сохраните игнорируемый локальный `source_types.json` рядом с проектом или
передайте `build_index.py` параметр `--source-types ПУТЬ`. Без файла PDF
классифицируются как `scholarship`, остальные файлы — как `other`. Пример
находится в `examples/source-types.medieval-japan.json`.

При обновлении существующей установки сначала сохраните прежний
`source_types.json`, а после обновления верните его как локальный игнорируемый
файл. Если его отсутствие изменило бы уже записанную классификацию, индексатор
остановится до изменения SQLite и попросит вернуть файл или передать его через
`--source-types`.

Python индексирует, ранжирует, собирает контекст и выполняет воспроизводимые
проверки. Codex исследует источники, оценивает смысловую новизну и пишет
карточки. Публикация и запись в `used_finds.csv` — отдельная операция через
JSON-манифест и `record-publication`; preview журнал не меняет.

Для проверки пользовательской выдачи зарегистрируйте манифест в изолированном
тестовом журнале, а затем отрисуйте его:

```powershell
.venv\Scripts\python taira_search.py record-publication work/publications/test.json --used-finds work/test-used.csv
.venv\Scripts\python taira_search.py render-publication work/publications/test.json --used-finds work/test-used.csv
.venv\Scripts\python taira_search.py publication-status work/publications/test.json --used-finds work/test-used.csv --json
```

Команда отрисовки работает только на чтение и выводит все полные
`card_markdown`, лишь когда все карточки совпадают с записями журнала. Статус намеренно
оставляет доставку неподтверждённой: показать ответ может только поверхность
задачи/чата Codex, а CLI не получает подтверждение отображения. Поэтому
восстановление повторно использует и выводит тот же манифест без новой
регистрации.

## Проверка прав запланированной публикации

До включения автоматизации выпуска выполните команду именно из окружения
запланированной задачи, а не только из интерактивного терминала:

```powershell
.venv\Scripts\python taira_search.py check-publication-access --db work/index.sqlite3 --used-finds used_finds.csv
```

Она открывает SQLite только для чтения, читает существующий журнал и проверяет
создание с атомарным переименованием двух безопасных временных файлов в каталоге
журнала. Существующий `.used_finds.csv.lock` открывается для чтения и записи без
записи, усечения или удаления; отсутствующий lock-файл не создаётся. Содержимое
настоящего журнала и lock-файла не изменяется. Успех подтверждает эффективные
права процесса; одной записи пути в
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

Подробнее: [onboarding](research-onboarding.ru.md),
[пополнение библиотеки](source-acquisition.ru.md).



## Режимы и обзор источников

См. [retrieval-discovery.md](retrieval-discovery.md). В профиле сохраняется
`search_mode`: `open` или `focused_people`. Переключение через агента не требует
переиндексации; старый профиль не переписывается автоматически. `preferred_kinds`
участвует в мягких поисковых подсказках, а coverage.discovery показывает охват
и причины пропуска источников. Для отдельного аудита доступен необязательный
`research-findings --preview --discovery-path <relative-prefix>` с continuation.
Типы материалов и фильтры профиля продолжают действовать.
