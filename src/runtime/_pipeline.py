"""
向后兼容导入——pipeline 相关类型已迁移至 src/runtime/pipeline/ 子包。

请更新导入路径：
  from src.runtime.pipeline import Pipeline, Stage, ...
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
