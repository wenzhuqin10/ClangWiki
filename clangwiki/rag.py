from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database, json_dumps, json_loads
from .errors import OpenCodeError
from .indexing import IndexService
from .opencode import OpenCodeRunner
from .registry import Registry


CITATION_RE = re.compile(r"\[([WCGM]\d+)\]")


class RagService:
    def __init__(self, database: Database, registry: Registry, indexer: IndexService) -> None:
        self.db = database
        self.registry = registry
        self.indexer = indexer

    def create_conversation(self, scope_type: str, scope_id: str, title: str = "新建知识问答") -> dict[str, Any]:
        self._scope_settings(scope_type, scope_id)
        conversation_id = f"conv-{uuid.uuid4().hex}"
        now = time.time()
        self.db.execute(
            "INSERT INTO conversations(id,scope_type,scope_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (conversation_id, scope_type, scope_id, title.strip() or "新建知识问答", now, now),
        )
        return self.get_conversation(conversation_id)

    def list_conversations(self) -> list[dict[str, Any]]:
        return [self._public_conversation(row) for row in self.db.all(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 200"
        )]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM conversations WHERE id=?", (conversation_id,))
        if not row:
            raise KeyError("会话不存在")
        result = self._public_conversation(row)
        result["turns"] = [self._public_turn(item) for item in self.db.all(
            "SELECT * FROM turns WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
        )]
        for turn in result["turns"]:
            turn["citations"] = self.db.all(
                "SELECT citation_key,chunk_id,source_uri,title FROM citations WHERE turn_id=? ORDER BY citation_key",
                (turn["id"],),
            )
        return result

    def ask(
        self,
        conversation_id: str,
        question: str,
        limit: int = 12,
    ) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        query = question.strip()
        if not query:
            raise ValueError("问题不能为空。")
        settings, cwd = self._scope_settings(conversation["scope_type"], conversation["scope_id"])
        search = self.indexer.search(query, conversation["scope_type"], conversation["scope_id"], limit=limit)
        evidence = self._evidence(search["results"])
        if not evidence:
            answer = "根据当前可访问的代码、文档和知识索引无法确定。请先为该范围生成并建立索引。"
            return self._persist_turn(conversation_id, query, answer, "insufficient_evidence", search, [])
        model = str(settings.get("model") or "").strip()
        if not model:
            raise OpenCodeError("当前范围没有配置 OpenCode 模型标识。")
        turn_id = f"turn-{uuid.uuid4().hex}"
        task_root = self.db.data_root / "tmp" / "rag" / conversation_id / turn_id
        task_root.mkdir(parents=True, exist_ok=True)
        context_file = task_root / "context.md"
        context_file.write_text(self._context(conversation, query, evidence), encoding="utf-8")
        runner = OpenCodeRunner(
            str(settings.get("opencode_executable") or "opencode"), model,
            str(settings.get("agent") or "") or None, int(settings.get("timeout_seconds") or 900),
        )
        prompt = (
            "你是 ClangWiki 有证据约束的基带代码问答助手。仅依据附件证据回答问题。"
            "每个可核验结论必须使用附件中已有的 [Wn]/[Cn]/[Gn]/[Mn] 引用；不得创建新引用。"
            "区分编译器事实、源码事实、人工知识和候选关系。证据不足时明确写出无法确定及所需材料。"
            "只输出最终中文 Markdown 答案。"
        )
        answer = runner.run_prompt(
            cwd, context_file, task_root / "answer.stdout.txt", task_root / "answer.stderr.txt", prompt,
        ).strip()
        valid, invalid = validate_citations(answer, set(evidence))
        status = "completed"
        if not valid:
            repair_file = task_root / "repair.md"
            repair_file.write_text(
                context_file.read_text(encoding="utf-8")
                + "\n\n## 待修复回答\n\n" + answer
                + "\n\n## 校验问题\n\n无效或缺失引用：" + ", ".join(invalid),
                encoding="utf-8",
            )
            repair_prompt = (
                "修复附件中的待修复回答。只能使用证据清单中存在的引用，删除无证据结论。"
                "如果证据不足，明确说明无法确定。只输出修复后的最终 Markdown。"
            )
            answer = runner.run_prompt(
                cwd, repair_file, task_root / "repair.stdout.txt", task_root / "repair.stderr.txt", repair_prompt,
            ).strip()
            valid, invalid = validate_citations(answer, set(evidence))
            if not valid:
                answer = "回答校验失败：OpenCode 返回内容包含无效引用或未引用可用证据。为避免展示未经验证的结论，本轮回答已阻止。"
                status = "citation_validation_failed"
        used = sorted(set(CITATION_RE.findall(answer))) if status == "completed" else []
        citations = [
            {"citation_key": key, **evidence[key]}
            for key in used if key in evidence
        ]
        return self._persist_turn(conversation_id, query, answer, status, search, citations, turn_id=turn_id)

    def _evidence(self, results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        counters = {"W": 0, "C": 0, "G": 0, "M": 0}
        evidence: dict[str, dict[str, Any]] = {}
        for result in results:
            prefix = {"wiki": "W", "code": "C", "graph": "G", "manual": "M", "annotation": "M"}.get(result["kind"], "W")
            counters[prefix] += 1
            key = f"{prefix}{counters[prefix]}"
            evidence[key] = {
                "chunk_id": result["id"], "source_uri": result["source_uri"], "title": result["title"],
                "content": result["content"], "kind": result["kind"], "metadata": result.get("metadata", {}),
                "channels": result.get("channels", []), "score": result.get("score"),
            }
        return evidence

    def _context(
        self,
        conversation: dict[str, Any],
        question: str,
        evidence: dict[str, dict[str, Any]],
    ) -> str:
        blocks = [
            "# ClangWiki RAG Evidence", "", "## 当前问题", question,
            "", "## 回答规则",
            "- 只能依据本文件的证据回答。",
            "- 每个仓库实现结论必须引用对应证据编号。",
            "- `candidate`、`lexical` 和 `POSSIBLE_CALL` 不能表述为确定调用。",
            "- 通用协议知识不得冒充当前代码仓实现。",
            "- 无法确认时说明缺失的源码、日志、配置、测试或设计材料。",
            "", "## 最近会话上下文",
        ]
        history = conversation.get("turns", [])[-4:]
        if history:
            for turn in history:
                blocks.extend([
                    f"### 问：{str(turn['question'])[:500]}",
                    str(turn["answer"])[:1200],
                ])
        else:
            blocks.append("无。")
        blocks.extend(["", "## 证据清单"])
        for key, item in evidence.items():
            blocks.extend([
                f"### [{key}] {item['title']}",
                f"- 来源：`{item['source_uri']}`",
                f"- 类型：{item['kind']}",
                f"- 召回通道：{', '.join(item['channels'])}",
                "", item["content"][:12000], "",
            ])
        return "\n".join(blocks)

    def _scope_settings(self, scope_type: str, scope_id: str) -> tuple[dict[str, Any], Path]:
        if scope_type == "repository":
            repository = self.registry.get_repository(scope_id)
            return repository["config"], Path(repository["path"])
        if scope_type == "collection":
            collection = self.registry.get_collection(scope_id)
            if not collection["repositories"]:
                raise ValueError("知识空间没有成员仓库。")
            settings = {**collection["repositories"][0]["config"], **collection.get("config", {})}
            return settings, Path(collection["repositories"][0]["path"])
        raise ValueError("scope_type 必须是 repository 或 collection")

    def _persist_turn(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        status: str,
        retrieval: dict[str, Any],
        citations: list[dict[str, Any]],
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        turn_id = turn_id or f"turn-{uuid.uuid4().hex}"
        now = time.time()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO turns(id,conversation_id,question,answer,status,retrieval_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (turn_id, conversation_id, question, answer, status, json_dumps(retrieval), now),
            )
            for citation in citations:
                connection.execute(
                    "INSERT INTO citations(id,turn_id,citation_key,chunk_id,source_uri,title) VALUES(?,?,?,?,?,?)",
                    (
                        f"citation-{uuid.uuid4().hex}", turn_id, citation["citation_key"], citation.get("chunk_id"),
                        citation["source_uri"], citation["title"],
                    ),
                )
            connection.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        result = self._public_turn(self.db.one("SELECT * FROM turns WHERE id=?", (turn_id,)) or {})
        result["citations"] = citations
        return result

    @staticmethod
    def _public_conversation(row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _public_turn(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["retrieval"] = json_loads(result.pop("retrieval_json", None), {})
        return result


def validate_citations(answer: str, allowed: set[str]) -> tuple[bool, list[str]]:
    used = set(CITATION_RE.findall(answer))
    invalid = sorted(used - allowed)
    if invalid:
        return False, invalid
    if allowed and not used:
        return False, ["缺少引用"]
    return True, []
