# This package is named 'signal', which shadows Python's stdlib signal module.
# Re-export every stdlib signal attribute so third-party libraries (anyio,
# anthropic, openai) that do `from signal import Signals` keep working.
import importlib.util as _ilu
import sys as _sys
import sysconfig as _sysconfig
import os as _os

def _bootstrap_stdlib_signal():
    stdlib_path = _os.path.join(_sysconfig.get_paths()["stdlib"], "signal.py")
    if not _os.path.isfile(stdlib_path):
        return

    # Temporarily replace ourselves in sys.modules with the real stdlib module
    # so that signal.py's `_IntEnum._convert_(..., __name__, ...)` lookup works.
    _us = _sys.modules.get("signal")
    spec = _ilu.spec_from_file_location("signal", stdlib_path)
    _stdlib = _ilu.module_from_spec(spec)
    _sys.modules["signal"] = _stdlib
    try:
        spec.loader.exec_module(_stdlib)
    finally:
        # Restore this package (or remove if we were never there)
        if _us is not None:
            _sys.modules["signal"] = _us
        else:
            _sys.modules.pop("signal", None)

    # Copy every public attribute from stdlib into this package's namespace
    for _attr in dir(_stdlib):
        if not _attr.startswith("__") and _attr not in globals():
            globals()[_attr] = getattr(_stdlib, _attr)

_bootstrap_stdlib_signal()
del _bootstrap_stdlib_signal, _ilu, _sys, _sysconfig, _os
