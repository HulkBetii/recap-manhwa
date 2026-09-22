# -*- coding: utf-8 -*-
"""
Pipeline Interfaces & Domain Contracts (SOLID Principles)
Defines abstract base classes for stages, episode processors, and pipeline runners.
"""

import abc
from typing import Optional, Dict, Any, List
from workflow_base import WorkflowContext, WorkflowTask, StageState


class IStage(abc.ABC):
    """Base interface for all pipeline stages (Single Responsibility)."""
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Display name of the stage."""
        pass

    @property
    @abc.abstractmethod
    def phase_code(self) -> str:
        """Standard Phase Code: P1_VISUAL, P2_SCRIPT, P3_AUDIO, P4_RENDER, P5_EXPORT."""
        pass

    @property
    @abc.abstractmethod
    def weight(self) -> float:
        """Weight contributing to overall project progress (sum = 1.0)."""
        pass

    @abc.abstractmethod
    async def execute(self, context: WorkflowContext) -> bool:
        """Executes stage logic. Returns True on success, False on failure."""
        pass


class IEpisodeProcessor(abc.ABC):
    """Interface for operations executed per episode (Interface Segregation)."""
    @abc.abstractmethod
    async def process_episode(self, ep: int, context: WorkflowContext, **kwargs) -> bool:
        """Executes processing for a single episode."""
        pass
