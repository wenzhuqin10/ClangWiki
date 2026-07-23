import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analyzer import RepositoryAnalyzer, repository_id
from .database import Database
from .generator import GeneratorGateway
from .models import AnalysisSummary, WikiPlan, WikiPagePlan
from .retrieval import HybridRetriever


WIKI_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["id", "title", "description", "query"],
            },
        },
    },
    "required": ["title", "description", "pages"],
}


class RepositoryService:
    def __init__(
        self,
        database: Database,
        analyzer: RepositoryAnalyzer,
        retriever: HybridRetriever,
        generator: GeneratorGateway,
        max_context_chars: int = 80000,
    ):
        self.database = database
        self.analyzer = analyzer
        self.retriever = retriever
        self.generator = generator
        self.max_context_chars = max_context_chars

    async def analyze(
        self, root_path: str, compile_database: Optional[str] = None
    ) -> AnalysisSummary:
        root = Path(root_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Repository path does not exist or is not a directory: %s" % root)
        compile_db = Path(compile_database).expanduser().resolve() if compile_database else None
        result = self.analyzer.analyze(root, compile_db)
        repo_id = repository_id(root)
        self.database.replace_repository(
            repo_id, str(root), result.mode, result.confidence, result.errors
        )

        symbol_ids: Dict[tuple, str] = {}
        symbols = []
        for row in result.symbols:
            symbol_id = "%s:%s" % (
                repo_id,
                row.get("id") or row["qualified_name"] + ":" + row["file_path"] + ":" + str(row["line_start"]),
            )
            symbol_ids[(row["qualified_name"], row["file_path"], row["line_start"])] = symbol_id
            symbols.append(dict(row, id=symbol_id, repository_id=repo_id))
        relations = [dict(row, repository_id=repo_id) for row in result.relations]
        chunks = []
        for row in result.chunks:
            chunk = dict(row, repository_id=repo_id)
            symbol_key = chunk.pop("symbol_key", None)
            chunk["symbol_id"] = symbol_ids.get(symbol_key)
            chunks.append(chunk)

        self.database.insert_symbols(symbols)
        self.database.insert_relations(relations)
        self.database.insert_chunks(chunks)
        await self.retriever.index(repo_id)
        counts = self.database.counts(repo_id)
        return AnalysisSummary(
            repository_id=repo_id,
            root_path=str(root),
            mode=result.mode,
            confidence=result.confidence,
            symbol_count=counts["symbols"],
            relation_count=counts["relations"],
            chunk_count=counts["chunks"],
            errors=result.errors,
        )

    def summary(self, repository_id_value: str) -> AnalysisSummary:
        repository = self.database.repository(repository_id_value)
        if not repository:
            raise KeyError(repository_id_value)
        counts = self.database.counts(repository_id_value)
        return AnalysisSummary(
            repository_id=repository_id_value,
            root_path=repository["root_path"],
            mode=repository["mode"],
            confidence=repository["confidence"],
            symbol_count=counts["symbols"],
            relation_count=counts["relations"],
            chunk_count=counts["chunks"],
            errors=json.loads(repository["errors_json"]),
        )

    async def plan_wiki(
        self, repository_id_value: str, language: str, page_count: int
    ) -> WikiPlan:
        repository = self.database.repository(repository_id_value)
        if not repository:
            raise KeyError(repository_id_value)
        hits = await self.retriever.search(
            repository_id_value, "architecture modules entry points public API build system", 20, True
        )
        evidence = self._evidence(hits)
        prompt = (
            "你是 C/C++ 软件架构文档规划器。根据证据规划 %d 个 Wiki 页面。"
            "输出语言为 %s。页面必须覆盖项目概览、构建系统、模块关系、核心调用流程和 API。"
            "query 字段用于检索生成该页面所需的代码。不要编造证据中不存在的组件。\n\n%s"
        ) % (page_count, language, evidence)
        payload = await self.generator.complete_json(
            prompt, WIKI_PLAN_SCHEMA, repository["root_path"]
        )
        return WikiPlan.model_validate(payload)

    async def generate_page(
        self, repository_id_value: str, page: WikiPagePlan, language: str = "zh-CN"
    ) -> str:
        repository = self.database.repository(repository_id_value)
        if not repository:
            raise KeyError(repository_id_value)
        hits = await self.retriever.search(repository_id_value, page.query, 12, True)
        evidence = self._evidence(hits)
        prompt = (
            "你是严谨的 C/C++ 技术文档作者。生成 Markdown 页面《%s》。\n"
            "目标：%s\n输出语言：%s\n"
            "规则：只依据给定证据；每个重要事实后使用 `[文件:起始行-结束行]` 引用；"
            "代码标识符保持原文；需要时使用 Mermaid；不确定的间接调用必须写成候选关系。\n\n%s"
        ) % (page.title, page.description, language, evidence)
        return await self.generator.complete_text(prompt, repository["root_path"])

    def _evidence(self, hits: List[Dict[str, Any]]) -> str:
        blocks = []
        used = 0
        for hit in hits:
            block = "\n---\nEvidence [%s:%d-%d]\n%s" % (
                hit["file_path"], hit["line_start"], hit["line_end"], hit["content"]
            )
            if used + len(block) > self.max_context_chars:
                break
            blocks.append(block)
            used += len(block)
        return "".join(blocks)
