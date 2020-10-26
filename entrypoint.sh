#!/usr/bin/env bash
set -e

# Allow literal or volume mounted tokens based on env
# In multi-servo mode, the config file contains optimizer + token details
exec servo \
    --config-file ${SERVO_CONFIG_FILE:-/servo/servo.yaml} \
    $(if [ ! -z ${OPSANI_OPTIMIZER} ]; then \
        echo "--optimizer ${OPSANI_TOKEN}"; \
      fi) \
    $(if [ ! -z ${OPSANI_TOKEN} ]; then \
        echo "--token ${OPSANI_TOKEN}"; \
      elif [ -f /servo/opsani.token ]; then \
        echo "--token-file /servo/opsani.token"; \
      fi) \
    "$@"
