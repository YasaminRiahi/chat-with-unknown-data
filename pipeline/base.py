"""
pipeline/base.py
================
Base class that all pipeline layers inherit from.
Gives every layer access to the LLM, embeddings, and db_manager.
"""

from abc import ABC, abstractmethod


class BaseLayer(ABC):
    def __init__(self, llm, embeddings, db_manager):
        self.llm         = llm
        self.embeddings  = embeddings
        self.db_manager  = db_manager

    @abstractmethod
    def run(self, *args, **kwargs):
        """Each layer implements its own run() method."""
        pass
