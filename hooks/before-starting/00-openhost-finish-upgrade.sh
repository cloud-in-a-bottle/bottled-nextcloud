#!/bin/bash
# Runs on every container start, first of the before-starting hooks,
# after the upstream entrypoint's own install/upgrade step.
#
# Finishes an upgrade that a previous boot started but didn't complete.
# The upstream entrypoint decides whether to run ``occ upgrade`` by
# comparing version.php with the image's version, and it copies the new
# version.php into place BEFORE running ``occ upgrade``.  start.sh
# persists version.php when the container stops, so if a container is
# stopped mid-upgrade the next boot sees matching versions and skips
# the upgrade, while the database is still on the old version: every
# request would then get "update needed", with the web updater
# disabled.  ``occ status`` reports that as ``needsDbUpgrade``, so we
# run ``occ upgrade`` here when it's set, then turn maintenance mode
# off: the interrupted upgrade left it on, and ``occ upgrade`` keeps it
# on if it was already on.  On a normal boot neither runs.
#
# Not handled: a stop in the last seconds of ``occ upgrade``, after the
# database is migrated but before maintenance mode is switched off,
# leaves maintenance on with no upgrade pending.  We can't tell that
# apart from maintenance mode an admin turned on, so we only log it.
#
# Unlike 00-openhost-overwrite.sh, a failed ``occ upgrade`` fails the
# boot: the instance is unusable until it succeeds, and a restart
# retries it.
set -uo pipefail

log() { printf '[before-starting:upgrade] %s\n' "$*" >&2; }

# Same uid handling as 00-openhost-overwrite.sh.
occ() {
    if [[ "$(id -u)" == "0" ]]; then
        runuser -u www-data -- php /var/www/html/occ "$@"
    else
        php /var/www/html/occ "$@"
    fi
}

if ! STATUS=$(occ --no-warnings status --output=json 2>/dev/null); then
    log "warning: occ status failed; not checking for an unfinished upgrade"
    exit 0
fi

# occ may print notices before the JSON, so parse from the first "{".
NEEDS_UPGRADE=$(printf '%s' "$STATUS" | python3 -c '
import json, sys
text = sys.stdin.read()
status = json.loads(text[text.index("{"):])
if status.get("needsDbUpgrade") is True:
    print("yes")
elif status.get("maintenance") is True:
    print("maintenance")
else:
    print("no")
' 2>/dev/null) || NEEDS_UPGRADE=unknown

case "$NEEDS_UPGRADE" in
    no)
        exit 0
        ;;
    maintenance)
        log "warning: maintenance mode is on with no upgrade pending; leaving it on. If an upgrade was interrupted, turn it off with: occ maintenance:mode --off"
        exit 0
        ;;
    yes)
        log "Nextcloud needs an upgrade that a previous boot didn't finish; running occ upgrade"
        if ! occ upgrade; then
            log "FATAL: occ upgrade failed"
            exit 1
        fi
        log "upgrade finished; turning maintenance mode off"
        if ! occ maintenance:mode --off; then
            log "FATAL: could not turn maintenance mode off"
            exit 1
        fi
        exit 0
        ;;
    *)
        log "warning: could not parse occ status output; not checking for an unfinished upgrade"
        exit 0
        ;;
esac
