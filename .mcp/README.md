# Knowledge Base MCP Server

Локальный MCP-сервер для семантического поиска по Markdown-заметкам.

## Архитектура

- **LanceDB** — векторная БД без сервера (файлы в `.kb_index/`).
- **SentenceTransformers** (`all-MiniLM-L6-v2`) — эмбеддинги, ~80 МБ модель.
- **stdio MCP** — Claude Code запускает процесс сам, при выходе процесс умирает.

## Установка зависимостей

```powershell
cd .mcp
py -m pip install -r requirements.txt
```

Первая установка скачает PyTorch (~200–500 МБ) — это нормально.

> **Модель эмбеддингов:** сервер работает в оффлайн-режиме (`HF_HUB_OFFLINE=1`). Модель `all-MiniLM-L6-v2` (~90 МБ) должна быть предварительно скачана в кеш HuggingFace (`%USERPROFILE%\.cache\huggingface\hub`). При первой настройке запусти `run_server.cmd` — он скачает модель автоматически, если интернет доступен, или использует уже загруженную.

## Подключение к Claude Code

Добавь в конфигурацию MCP-серверов. Файл настроек Claude Code:

- **Windows:** `%APPDATA%\Claude\settings.json` или через UI Claude Code → Settings → MCP Servers
- **Через CLI:** `claude config add mcpServers.knowledge_base ...`

JSON-фрагмент:

```json
{
  "mcpServers": {
    "knowledge_base": {
      "command": "D:\\CC\\IdeaProjects\\knowledge_base\\.mcp\\run_server.cmd",
      "args": [],
      "env": {},
      "enabled": false
    }
  }
}
```

> `enabled: false` означает, что сервер по умолчанию выключен. Включай его вручную через `/mcp` в Claude Code, когда нужен доступ к базе знаний.

> **Важно:** используй прямые слэши `/` в путях, даже на Windows — Claude Code парсит их корректно.

## Как работает

1. При старте сессии Claude Code запускает `server.py`.
2. Сервер сканирует `../*.md` (все Markdown в `knowledge_base/`).
3. Если файлы изменились (проверка по MD5) — переиндексирует чанки.
4. Во время диалога Claude Code может вызывать:
   - `search_knowledge(query, top_k)` — семантический поиск.
   - `list_sources()` — список проиндексированных файлов.
5. При закрытии Claude Code процесс сервера завершается автоматически.

## Структура

```
knowledge_base/
├── .mcp/
│   ├── server.py          # MCP-сервер
│   ├── requirements.txt   # зависимости
│   └── README.md          # эта инструкция
├── .kb_index/             # векторный индекс (LanceDB)
│   └── kb_chunks/
└── <твои заметки>.md
```

## Отладка

Если что-то не работает, проверь логи в stderr Claude Code — сервер пишет туда префикс `[KB-MCP]`.

Ручной запуск для теста:

```powershell
$env:PYTHONIOENCODING = "utf-8"
py .mcp/server.py
```

(Ожидай пустого вывода — сервер ждёт JSON-RPC через stdin.)
