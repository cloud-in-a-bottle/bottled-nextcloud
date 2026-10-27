import time

import requests
from openhost_test_harness import OpenhostStack


def test_app_serves_owner(stack: OpenhostStack) -> None:
    # The app is marked running once its health check passes; "/" can take a little longer to come up.
    deadline = time.monotonic() + 60
    while True:
        # Accept like a browser navigation: some apps only redirect "/" to their UI for HTML requests (eg pihole).
        response = stack.owner_session.get(f"{stack.url}/", headers={"Accept": "text/html"}, timeout=30)
        if response.status_code < 400 or time.monotonic() > deadline:
            break
        time.sleep(2)
    assert response.status_code < 400, (
        f"GET / returned {response.status_code}: {response.text[:500]}\n\napp logs:\n{stack.app_logs()[-5000:]}"
    )


def test_redirects_stay_on_router_url(stack: OpenhostStack) -> None:
    # Nextcloud builds absolute redirect URLs from overwriteprotocol/overwritehost, which start.sh derives from
    # OPENHOST_ZONE_DOMAIN. The harness zone is "harness.localhost:<port>", served over plain http, so redirects
    # must point back at the router URL (http, with the port), not https.
    # "/" serves a 200 placeholder until Nextcloud's slow first boot finishes; then it redirects (to the login
    # or the default app).
    # The connection can also drop while Apache comes up, so retry that too.
    deadline = time.monotonic() + 600
    while True:
        try:
            response = stack.owner_session.get(
                f"{stack.url}/", headers={"Accept": "text/html"}, allow_redirects=False, timeout=30
            )
        except requests.ConnectionError:
            if time.monotonic() > deadline:
                raise
        else:
            if response.is_redirect or time.monotonic() > deadline:
                break
        time.sleep(5)
    assert response.is_redirect, (
        f"GET / never redirected; last status {response.status_code}: {response.text[:500]}\n\n"
        f"app logs:\n{stack.app_logs()[-5000:]}"
    )
    location = response.headers["Location"]
    assert location.startswith(f"{stack.url}/"), f"GET / redirected to {location!r}, expected under {stack.url}/"
