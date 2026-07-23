from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    path: str
    compile_database: Optional[str] = None
    rebuild: bool = False


class AnalysisSummary(BaseModel):
    repository_id: str
    root_path: str
    mode: str
    confidence: float
    symbol_count: int
    relation_count: int
    chunk_count: int
    errors: List[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    expand_graph: bool = True


class SearchHit(BaseModel):
    chunk_id: str
    file_path: str
    symbol: Optional[str] = None
    line_start: int
    line_end: int
    content: str
    score: float
    signals: List[str] = Field(default_factory=list)


class WikiPlanRequest(BaseModel):
    language: str = "zh-CN"
    page_count: int = Field(default=6, ge=2, le=20)


class WikiPagePlan(BaseModel):
    id: str
    title: str
    description: str
    query: str


class WikiPlan(BaseModel):
    title: str
    description: str
    pages: List[WikiPagePlan]


class HealthReport(BaseModel):
    repository_id: str
    analyzer: Dict[str, Any]
    embedding: Dict[str, Any]
    generator: Dict[str, Any]
    database: Dict[str, Any]

