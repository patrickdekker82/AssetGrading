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
check "webinterface (Node)" docker run --rm --entrypoint node graadmeter-web:latest -e "console.log('node', process.version)"
check "database (PostgreSQL)" docker run --rm --entrypoint postgres postgres:16-alpine --version

exit $fail
