#!/usr/bin/env bash
set -e

# Allow literal or volume mounted tokens
cat /servo/servo.yaml
exec servo \
    --config-file ${SERVO_CONFIG_FILE:-/servo/servo.yaml} \
    "$@"
