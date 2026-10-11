"""Runtime facts used by the health check; mainly to verify the Synology (no AVX/AVX2)."""

import platform
from pathlib import Path


def cpu_flags() -> dict[str, bool]:
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return {}
    flags_line = next((line for line in text.splitlines() if line.startswith("flags")), "")
    flags = set(flags_line.split(":", 1)[-1].split())
    return {name: name in flags for name in ("sse4_2", "avx", "avx2")}


def numpy_simd() -> list[str]:
    """AVX-family instructions NumPy detected at runtime; empty on the Synology's J4125."""
    from numpy._core._multiarray_umath import __cpu_features__

    return sorted(k for k, v in __cpu_features__.items() if v and k.startswith("AVX"))


def library_versions() -> dict[str, str]:
    import numpy
    import pandas
    import talib

    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "talib": talib.__version__,
    }


def compute_smoke_test() -> bool:
    """Exercise NumPy and TA-Lib once, so missing CPU instructions crash here and not at night."""
    import numpy as np
    import talib

    closes = np.arange(1.0, 61.0)
    sma = talib.SMA(closes, timeperiod=10)
    return bool(abs(sma[-1] - 55.5) < 1e-9)
