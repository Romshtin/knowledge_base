import sys
import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Any

# UTF-8 для Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="[KB-MCP] %(asctime)s %(levelname)s %(message)s"
)

from sentence_transformers import SentenceTransformer
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# === Конфигурация ===
MCP_DIR = Path(__file__).parent.resolve()
KB_DIR = MCP_DIR.parent
INDEX_DIR = KB_DIR / ".kb_index"
CHUNK_SIZE = 1000
OVERLAP = 200
MODEL_NAME = "all-MiniLM-L6-v2"

# === Модель ===
logging.info("Загрузка модели эмбеддингов...")
model = SentenceTransformer(MODEL_NAME, local_files_only=True)

# === Работа с индексом ===
def get_file_hash(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP):
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        if end == text_len:
            break
        start = end - overlap
    return chunks

def build_index():
    import lancedb
    logging.info(f"Сканирование {KB_DIR}...")
    md_files = list(KB_DIR.rglob("*.md"))
    # Исключаем служебные папки
    md_files = [f for f in md_files if ".kb_index" not in f.parts and ".mcp" not in f.parts]

    if not md_files:
        logging.warning("Markdown файлы не найдены.")
        return None

    records = []
    file_hashes = {}
    for fpath in md_files:
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception as e:
            logging.warning(f"Не удалось прочитать {fpath}: {e}")
            continue

        rel = fpath.relative_to(KB_DIR).as_posix()
        file_hashes[rel] = get_file_hash(fpath)
        chunks = chunk_text(text)
        for idx, chunk in enumerate(chunks):
            records.append({
                "id": f"{rel}::{idx}",
                "text": chunk,
                "source": rel,
                "chunk_index": idx,
            })

    if not records:
        return None

    logging.info(f"Создано {len(records)} чанков из {len(md_files)} файлов.")

    texts = [r["text"] for r in records]
    logging.info("Вычисление эмбеддингов...")
    vectors = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

    for i, vec in enumerate(vectors):
        records[i]["vector"] = vec.tolist()

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(INDEX_DIR))

    if "kb_chunks" in db.table_names():
        db.drop_table("kb_chunks")

    table = db.create_table("kb_chunks", records)

    meta = {
        "last_indexed": os.path.getmtime(str(INDEX_DIR / "kb_chunks")) if (INDEX_DIR / "kb_chunks").exists() else 0,
        "files": file_hashes,
        "total_chunks": len(records)
    }
    (INDEX_DIR / "index_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    logging.info("Индекс создан.")
    return table

def get_table():
    import lancedb
    if not INDEX_DIR.exists():
        return build_index()

    db = lancedb.connect(str(INDEX_DIR))
    if "kb_chunks" not in db.table_names():
        return build_index()

    # Проверяем необходимость переиндексации
    meta_path = INDEX_DIR / "index_meta.json"
    need_rebuild = False
    if not meta_path.exists():
        need_rebuild = True
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            known_files = meta.get("files", {})
            current_files = {}
            for f in KB_DIR.rglob("*.md"):
                if ".kb_index" in f.parts or ".mcp" in f.parts:
                    continue
                rel = f.relative_to(KB_DIR).as_posix()
                current_files[rel] = get_file_hash(f)

            if set(known_files.keys()) != set(current_files.keys()):
                need_rebuild = True
            else:
                for k, v in current_files.items():
                    if known_files.get(k) != v:
                        need_rebuild = True
                        break
        except Exception as e:
            logging.warning(f"Ошибка проверки meta: {e}")
            need_rebuild = True

    if need_rebuild:
        return build_index()

    return db.open_table("kb_chunks")

# === MCP Server ===
app = Server("knowledge_base")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_knowledge",
            description="Семантический поиск по базе знаний (Markdown-заметки). Возвращает наиболее релевантные фрагменты текста с указанием источника.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"},
                    "top_k": {"type": "integer", "default": 5, "description": "Количество результатов (1-20)"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="list_sources",
            description="Список всех проиндексированных источников (файлов Markdown) с количеством чанков.",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    table = get_table()
    if table is None:
        return [TextContent(type="text", text="База знаний пуста. Добавьте .md файлы в папку knowledge_base.")]

    if name == "search_knowledge":
        query = arguments.get("query", "")
        top_k = min(max(arguments.get("top_k", 5), 1), 20)
        if not query:
            return [TextContent(type="text", text="Пустой запрос.")]

        q_vec = model.encode(query, convert_to_numpy=True).tolist()
        df = table.search(q_vec).limit(top_k).to_pandas()

        results = []
        for _, row in df.iterrows():
            results.append({
                "source": row["source"],
                "chunk_index": int(row["chunk_index"]),
                "text": row["text"]
            })
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

    elif name == "list_sources":
        df = table.to_pandas()
        sources = df.groupby("source").size().reset_index(name="chunks").to_dict(orient="records")
        return [TextContent(type="text", text=json.dumps(sources, ensure_ascii=False, indent=2))]

    else:
        return [TextContent(type="text", text=f"Неизвестный инструмент: {name}")]

async def main():
    logging.info("Старт MCP-сервера knowledge_base")
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
