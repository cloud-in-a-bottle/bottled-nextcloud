#!/bin/bash
# Runs last of the before-starting hooks, after the upstream entrypoint
# has finished installing or upgrading Nextcloud and right before it
# execs Apache.  Touching the marker tells start.sh that the slow,
# must-not-be-interrupted part of the boot is over, so it can start
# its (short) Apache readiness deadline.  Never fails the boot: if the
# marker can't be written, start.sh falls back to waiting for Apache.
set -u

if [[ -n "${OPENHOST_ENTRYPOINT_DONE_FILE:-}" ]]; then
    touch "$OPENHOST_ENTRYPOINT_DONE_FILE" \
        || printf '[before-starting] warning: could not write %s\n' "$OPENHOST_ENTRYPOINT_DONE_FILE" >&2
fi
exit 0
