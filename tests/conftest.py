import pytest
import config


@pytest.fixture(autouse=True)
def reset_config_dry_run():
    """Reset config.DRY_RUN and TradingMode singleton before each test for isolation."""
    original = config.DRY_RUN
    config.DRY_RUN = True

    # Reset TradingMode singleton so tests don't bleed state
    try:
        from control.trading_mode import TradingMode
        TradingMode._singleton = None
    except ImportError:
        pass

    yield

    config.DRY_RUN = original
    try:
        from control.trading_mode import TradingMode
        TradingMode._singleton = None
    except ImportError:
        pass
