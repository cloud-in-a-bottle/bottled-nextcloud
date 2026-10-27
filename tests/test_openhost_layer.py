import time
import urllib.parse
import uuid

import pytest
import requests
from openhost_test_harness import OpenhostStack

HTML = {"Accept": "text/html,application/xhtml+xml"}
PRECONFIGURED_APPS = ("calendar", "contacts", "notes", "tasks", "deck")


def _context(stack: OpenhostStack, response: requests.Response | None) -> str:
    seen = "no response" if response is None else f"{response.status_code} {response.url} {response.text[:800]}"
    return f"last response: {seen}\n\napp logs:\n{stack.app_logs()[-5000:]}"


@pytest.fixture(scope="module")
def nextcloud(stack: OpenhostStack) -> OpenhostStack:
    """Waits for Nextcloud's slow first boot: until then the auth proxy serves a 200 placeholder on "/"."""
    deadline = time.monotonic() + 900
    response = None
    while time.monotonic() < deadline:
        try:
            response = stack.owner_session.get(f"{stack.url}/", headers=HTML, allow_redirects=False, timeout=30)
        except requests.ConnectionError:
            response = None
        if response is not None and response.is_redirect:
            return stack
        time.sleep(5)
    pytest.fail(f"Nextcloud never finished booting\n{_context(stack, response)}")


def _path(response: requests.Response) -> str:
    return urllib.parse.urlparse(response.url).path


def test_owner_is_signed_in_as_admin(nextcloud: OpenhostStack) -> None:
    # Without the auth proxy's X-Openhost-User header, user_saml doesn't sign anyone in and this redirects to /login.
    response = nextcloud.owner_session.get(
        f"{nextcloud.url}/index.php/settings/admin/overview", headers=HTML, timeout=60
    )
    assert response.status_code == 200, _context(nextcloud, response)
    assert _path(response) == "/index.php/settings/admin/overview", _context(nextcloud, response)
    assert 'data-user="admin"' in response.text, _context(nextcloud, response)


def test_preconfigured_apps_are_enabled(nextcloud: OpenhostStack) -> None:
    for app in PRECONFIGURED_APPS:
        response = nextcloud.owner_session.get(f"{nextcloud.url}/index.php/apps/{app}/", headers=HTML, timeout=60)
        assert response.status_code == 200, f"app {app}\n{_context(nextcloud, response)}"
        assert _path(response).startswith(f"/index.php/apps/{app}"), f"app {app}\n{_context(nextcloud, response)}"


def test_anonymous_gets_nextcloud_login(nextcloud: OpenhostStack) -> None:
    # Every path is public at the router, so the auth proxy alone decides who's the owner.
    response = requests.get(
        f"{nextcloud.url}/index.php/settings/user", headers=HTML, allow_redirects=False, timeout=60
    )
    assert response.is_redirect and "/login" in response.headers["Location"], (
        f"anonymous request: {response.status_code} {response.headers}"
    )


def test_native_clients_can_pair_and_sync(nextcloud: OpenhostStack) -> None:
    # Login Flow v2 is how desktop and mobile clients pair; the login URL it hands out must be the public app URL.
    response = requests.post(f"{nextcloud.url}/index.php/login/v2", timeout=60)
    assert response.status_code == 200, f"login flow v2: {response.status_code} {response.text[:300]}"
    assert response.json()["login"].startswith(f"{nextcloud.url}/"), response.text[:300]

    # Clients then sync over WebDAV with Basic auth, which the auth proxy passes through untouched.
    password = (nextcloud.data_dir / "admin_password.txt").read_text().strip()
    url = f"{nextcloud.url}/remote.php/dav/files/admin/upstream-coverage-{uuid.uuid4().hex[:8]}.txt"
    body = b"synced through the auth proxy\n"
    put = requests.put(url, data=body, auth=("admin", password), timeout=60)
    assert put.status_code in (201, 204), f"WebDAV PUT: {put.status_code} {put.text[:300]}"
    get = requests.get(url, auth=("admin", password), timeout=60)
    assert get.status_code == 200 and get.content == body, f"WebDAV GET: {get.status_code} {get.text[:300]}"
    assert requests.get(url, timeout=60).status_code == 401, "WebDAV without credentials wasn't refused"
