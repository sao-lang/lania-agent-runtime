"""
Memory 向量/图检索测试。

覆盖 HashEmbeddingProvider、余弦相似度、SemanticKnowledgeStore 的向量检索
（排序/阈值/关键词回退/批量嵌入）、图扩展检索（search_related），
以及 MemoryService 的 provider 注入与 recall_graph 入口。
"""

from __future__ import annotations

import math

import pytest

from src.memory import HashEmbeddingProvider, MemoryService
from src.memory._backends._sqlite import SQLitePersistence
from src.memory._embedding import cosine_similarity
from src.memory._stores import SemanticKnowledgeStore
from src.memory._types import SemanticNode


class TestHashEmbeddingProvider:
    """HashEmbeddingProvider 基础行为。"""

    async def test_deterministic_and_normalized(self) -> None:
        provider = HashEmbeddingProvider(dim=64)
        first = await provider.embed("Python 编程语言")
        second = await provider.embed("Python 编程语言")
        assert first == second
        assert len(first) == 64
        norm = math.sqrt(sum(v * v for v in first))
        assert norm == pytest.approx(1.0, abs=1e-6)

    async def test_different_texts_differ(self) -> None:
        provider = HashEmbeddingProvider(dim=128)
        a = await provider.embed("Python 编程")
        b = await provider.embed("Java 后端")
        assert a != b
        assert cosine_similarity(a, b) < 0.9

    async def test_empty_text_zero_vector(self) -> None:
        provider = HashEmbeddingProvider(dim=32)
        vector = await provider.embed("")
        assert vector == [0.0] * 32

    def test_invalid_params(self) -> None:
        with pytest.raises(ValueError, match="dim"):
            HashEmbeddingProvider(dim=0)
        with pytest.raises(ValueError, match="ngram"):
            HashEmbeddingProvider(ngram=0)


class TestCosineSimilarity:
    """余弦相似度边界。"""

    def test_identical(self) -> None:
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_and_zero(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_dim_mismatch(self) -> None:
        assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0


@pytest.fixture
async def vector_store() -> SemanticKnowledgeStore:
    """带 HashEmbeddingProvider 的语义 Store。"""
    persistence = SQLitePersistence(":memory:")
    store = SemanticKnowledgeStore(persistence, embedding_provider=HashEmbeddingProvider())
    yield store
    await persistence.close()


class TestVectorSearch:
    """SemanticKnowledgeStore 向量检索。"""

    async def test_ensure_embeddings_and_rank(self, vector_store: SemanticKnowledgeStore) -> None:
        await vector_store.create_node(
            SemanticNode(name="Python", description="编程语言", aliases=["python"])
        )
        await vector_store.create_node(
            SemanticNode(name="Java", description="后端语言", aliases=[])
        )
        count = await vector_store.ensure_embeddings()
        assert count == 2
        # 幂等：第二次不再生成
        assert await vector_store.ensure_embeddings() == 0

        result = await vector_store.search_nodes(
            "Python 编程语言 python",
            top_k=2,
            threshold=0.0,
        )
        assert result[0].name == "Python"

    async def test_threshold_filters_low_similarity(
        self, vector_store: SemanticKnowledgeStore
    ) -> None:
        await vector_store.create_node(SemanticNode(name="Python", description="编程语言"))
        await vector_store.create_node(SemanticNode(name="Rust", description="系统编程"))
        await vector_store.ensure_embeddings()
        result = await vector_store.search_nodes("Python", top_k=5, threshold=0.95)
        assert [n.name for n in result] == ["Python"]

    async def test_keyword_fallback_without_embeddings(
        self, vector_store: SemanticKnowledgeStore
    ) -> None:
        # 未执行 ensure_embeddings：无 embedding，走关键词匹配
        await vector_store.create_node(
            SemanticNode(name="Python", description="编程语言", aliases=["py"])
        )
        result = await vector_store.search_nodes("python", top_k=5)
        assert [n.name for n in result] == ["Python"]


class TestGraphRetrieval:
    """图扩展检索。"""

    async def test_search_related_expands_neighbors(
        self, vector_store: SemanticKnowledgeStore
    ) -> None:
        python = SemanticNode(name="Python", description="编程语言")
        numpy = SemanticNode(name="NumPy", description="数值计算")
        scipy = SemanticNode(name="SciPy", description="科学计算")
        for node in (python, numpy, scipy):
            await vector_store.create_node(node)
        await vector_store.create_edge(python.id, numpy.id, "depends_on")
        await vector_store.create_edge(numpy.id, scipy.id, "depends_on")
        await vector_store.ensure_embeddings()

        related = await vector_store.search_related(
            "Python",
            top_k=1,
            max_depth=2,
        )
        names = {node.name for node, _ in related}
        assert names == {"Python", "NumPy", "SciPy"}
        relations = {node.name: rels for node, rels in related}
        assert "depends_on" in relations["NumPy"]

    async def test_search_related_relation_filter(
        self, vector_store: SemanticKnowledgeStore
    ) -> None:
        a = SemanticNode(name="Alpha")
        b = SemanticNode(name="Beta")
        c = SemanticNode(name="Gamma")
        for node in (a, b, c):
            await vector_store.create_node(node)
        await vector_store.create_edge(a.id, b.id, "likes")
        await vector_store.create_edge(a.id, c.id, "knows")
        await vector_store.ensure_embeddings()

        related = await vector_store.search_related(
            "Alpha",
            top_k=1,
            max_depth=1,
            relation="knows",
        )
        names = {node.name for node, _ in related}
        assert names == {"Alpha", "Gamma"}


class TestMemoryServiceEmbedding:
    """MemoryService 向量/图检索接入。"""

    async def test_provider_injected_and_recall_graph(self) -> None:
        provider = HashEmbeddingProvider()
        memory = MemoryService(
            SQLitePersistence(":memory:"),
            embedding_provider=provider,
        )
        try:
            assert memory.semantic._embedding_provider is provider
            python = SemanticNode(name="Python", description="编程语言")
            numpy = SemanticNode(name="NumPy", description="数值计算")
            await memory.semantic.create_node(python)
            await memory.semantic.create_node(numpy)
            await memory.semantic.create_edge(python.id, numpy.id, "related")
            await memory.semantic.ensure_embeddings()

            graph = await memory.recall_graph("Python", top_k=1, max_depth=1)
            assert {n.name for n, _ in graph} == {"Python", "NumPy"}

            concepts = await memory.recall_raw("s1", query="Python 编程")
            assert any(c["name"] == "Python" for c in concepts.concepts)
        finally:
            await memory.close()

    def test_lazy_export(self) -> None:
        import src.memory as memory_pkg

        assert memory_pkg.HashEmbeddingProvider is HashEmbeddingProvider
        assert callable(memory_pkg.cosine_similarity)
