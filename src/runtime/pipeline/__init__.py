"""
管线子包——Pipeline[T] 通用管线框架。

应用于：ContextManager 五阶段管线、StepRunner 单步管线、Memory 读写管线。
"""

from src.runtime.pipeline._pipeline import (
    Pipeline,
    PipelineResult,
    Stage,
    StageInfo,
    StopPipelineError,
)

__all__ = [
    "Pipeline",
    "PipelineResult",
    "Stage",
    "StageInfo",
    "StopPipelineError",
]
