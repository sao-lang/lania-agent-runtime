"""
向量嵌入与相似度计算模块。

提供可插拔的 EmbeddingProvider 协议与内置的纯 Python 实现
（HashEmbeddingProvider，基于特征哈希，无外部依赖），
供 SemanticKnowledgeStore 做向量语义检索。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """向量嵌入提供者协议。

    实现类将文本编码为固定维度的稠密向量。
    """

    async def embed(self, text: str) -> list[float]:
        """将单段文本编码为向量。

        Args:
            text: 输入文本。

        Returns:
            归一化后的稠密向量。
        """
        ...


class HashEmbeddingProvider:
    """基于特征哈希的确定性向量嵌入（无外部依赖）。

    将文本按字符 n-gram 做特征哈希（有符号计数）后 L2 归一化。
    相同输入恒得相同向量；适合离线知识索引与关键词近邻检索。
    生产环境可替换为真实 embedding 模型（OpenAI / 本地模型等），
    只需满足 EmbeddingProvider 协议。

    Attributes:
        _dim: 向量维度。
        _ngram: 字符 n-gram 大小。
    """

    _TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")

    def __init__(self, dim: int = 256, *, ngram: int = 3) -> None:
        """初始化 HashEmbeddingProvider。

        Args:
            dim: 向量维度，默认 256。
            ngram: 字符 n-gram 大小，默认 3。
        """
        if dim <= 0:
            raise ValueError(f"dim 必须为正整数，收到 {dim}")
        if ngram <= 0:
            raise ValueError(f"ngram 必须为正整数，收到 {ngram}")
        self._dim = dim
        self._ngram = ngram

    async def embed(self, text: str) -> list[float]:
        """将文本编码为归一化向量。

        Args:
            text: 输入文本。

        Returns:
            L2 归一化的稠密向量（空文本返回全零向量）。
        """
        vector = [0.0] * self._dim
        for token in self._TOKEN_RE.findall(text.lower()):
            padded = f"^{token}$"
            for i in range(max(1, len(padded) - self._ngram + 1)):
                gram = padded[i : i + self._ngram]
                digest = hashlib.md5(gram.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "big") % self._dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。

    Args:
        a: 向量 a。
        b: 向量 b。

    Returns:
        0.0 ~ 1.0 的相似度；任一向量为零向量或维度不一致时返回 0.0。
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))
