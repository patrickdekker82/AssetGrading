#!/usr/bin/env bash
# Run on the Synology after `docker load`: starts an empty container of every image and checks it.
# The DSM kernel is old and the Celeron J4125 has no AVX/AVX2, so this must pass before go-live.
set -uo pipefail
fail=0
check() { local label=$1; shift; if "$@"; then echo "OK   $label"; else echo "FOUT $label"; fail=1; fi; }

echo "Kernel: $(uname -r)"
grep -qw avx /proc/cpuinfo && echo "CPU heeft AVX" || echo "CPU zonder AVX (verwacht op DS920+)"

check "rekenserver (NumPy, pandas, TA-Lib)" docker run --rm --entrypoint python graadmeter-server:latest -c "
from app.system import compute_smoke_test, library_versions, numpy_simd
import numpy as np
assert compute_smoke_test()
a = np.random.default_rng(0).normal(size=(300, 300))
assert np.linalg.eigvalsh(a @ a.T)[-1] > 0
print(library_versions(), 'numpy AVX:', numpy_simd())
"
check "databronnen bereikbaar" docker run --rm --entrypoint python graadmeter-server:latest -c "
import httpx, sys
urls = {
    'Binance spot': 'https://data-api.binance.vision/api/v3/ping',
    'Coinbase': 'https://api.exchange.coinbase.com/products/BTC-USD',
    'CoinGecko': 'https://api.coingecko.com/api/v3/ping',
    'DefiLlama': 'https://api.llama.fi/v2/chains',
    'Coin Metrics': 'https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?assets=btc&page_size=1',
    'Frankfurter': 'https://api.frankfurter.dev/v1/latest',
    'FRED': 'https://api.stlouisfed.org/',
    'Binance futures (fase 2)': 'https://fapi.binance.com/fapi/v1/ping',
    'Bybit (fase 2)': 'https://api.bybit.com/v5/market/time',
}
bad = 0
for name, url in urls.items():
    try:
        code = httpx.get(url, timeout=15).status_code
    except Exception as exc:
        code = type(exc).__name__
    # FRED answers without a key with a redirect or an error page; any answer means reachable.
    ok = isinstance(code, int) and code < 500 if name == 'FRED' else code == 200
    later = 'fase 2' in name
    bad += not ok and not later
    label = 'ok  ' if ok else ('LET OP' if later else 'FOUT')
    print(f'  {label} {name}: {code}')
sys.exit(1 if bad else 0)
"
check "webinterface (Node)" docker run --rm --entrypoint node graadmeter-web:latest -e "console.log('node', process.version)"
check "database (PostgreSQL)" docker run --rm --entrypoint postgres postgres:16-alpine --version

exit $fail
