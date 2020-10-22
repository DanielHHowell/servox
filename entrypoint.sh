#!/usr/bin/env bash
set -e

# Allow literal or volume mounted tokens
exec servo \
    --config-file ${SERVO_CONFIG_FILE:-/servo/servo.yaml} \
    "$@"
