#!/bin/sh
#
# Restore the baked YouTrack instance into empty volumes, so a brand-new
# environment gets a tracker that is already provisioned and already holds the
# token the gateway's MCP connection is encrypted with.
#
# Runs as the `youtrack-init` one-shot, ahead of `youtrack` itself
# (depends_on: service_completed_successfully). It must finish before YouTrack
# touches the volumes: YouTrack writes its own empty database on first start,
# and once it has, the volume is no longer empty, so this would decline to
# restore and the stack would come up on a blank tracker showing the setup
# wizard.
#
# Idempotent by the only test that matters -- is there already a database here.
# An existing instance is never touched, so this is safe on every
# `docker compose up` forever.
#
# The volumes are mounted under /restore (youtrack-data -> /restore/data,
# youtrack-conf -> /restore/conf) because that is the layout inside the
# archive, which lets the whole restore be one `tar -C /restore`. Running as
# root, tar restores the archived numeric uid/gid, so YouTrack still owns its
# own files afterwards.

set -eu

SEED=/seed/youtrack-seed.tar.gz

if [ -d /restore/data/youtrack ] || [ -d /restore/data/hub ]; then
  echo "youtrack-init: existing instance found, leaving it alone"
  exit 0
fi

if [ ! -f "$SEED" ]; then
  echo "youtrack-init: no seed at $SEED -- YouTrack will start empty and show the"
  echo "               setup wizard. Provision it by hand, then bake it with"
  echo "               scripts/youtrack-snapshot.sh so the next environment does"
  echo "               not have to."
  exit 0
fi

echo "youtrack-init: empty volumes, restoring seed"
tar xzf "$SEED" -C /restore
echo "youtrack-init: restored $(du -sh /restore/data | cut -f1)"
