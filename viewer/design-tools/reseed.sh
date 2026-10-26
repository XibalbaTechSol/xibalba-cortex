#!/bin/bash
# fresh committed fixture + API restart (the token DB lives beside the sqlite and is kept)
S=${DESIGN_WORK:-.}; H=${CORTEX_HOME:-$S/cortex-home}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
export PYTHONPATH=$REPO/src
${PYTHON:-python3} $REPO/scripts/dev_seed_console.py --home $H --reset --scenario "${1:-both}" 2>&1 | tail -1
(nohup env PYTHONPATH=$PYTHONPATH ${PYTHON:-python3} -m xibalba_cortex.local_api --home $H --port 8420 > $S/api.log 2>&1 &)
sleep 4
