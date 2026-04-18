# execution/__init__.py
# ExecutionEngine is imported eagerly here for convenience.
# All internal imports in execution_engine.py are lazy (deferred)
# to prevent circular import chains.
from execution.execution_engine import ExecutionEngine

__all__ = ["ExecutionEngine"]
