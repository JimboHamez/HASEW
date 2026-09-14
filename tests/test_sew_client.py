"""Offline tests for ``sew_client`` against recorded portal response shapes."""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Any
from urllib.parse import parse_qs

import aiohttp
from aioresponses import aioresponses
import pytest
from yarl import URL

from custom_components.sew_water.sew_client import (
    USAGE_BATCH_SIZE,
    AccountIds,
    SewAuthError,
    SewClient,
    SewConnectionError,
    SewProtocolError,
)

from .conftest import (
    AURA_TOKEN,
    BASE,
    BILLING_ACCOUNT_ID,
    FWUID_HOME,
    FWUID_LOGIN,
    HASH_HOME,
    METER_ID,
    METER_SERIAL,
    VIEWSTATE_1,
    VIEWSTATE_2,
    aura_envelope,
    home_headers,
    home_page,
    login_page,
    mfa_channel_page,
    mfa_code_page,
    usage_day,
)

AURA_URL = re.compile(rf"^{re.escape(BASE)}/s/sfsites/aura(\?.*)?$")
FRONTDOOR = f"{BASE}/secur/frontdoor.jsp?sid=FAKE-SID&retURL=%2F"
IDS = AccountIds(billing_account_id=BILLING_ACCOUNT_ID, meter_id=METER_ID)


def posted_form(mocked: aioresponses, url_pattern: str | re.Pattern[str], index: int = 0) -> dict[str, str]:
    """Return the decoded form body of the *index*-th POST whose URL matches."""
    posts = [
        (key, calls)
        for key, calls in mocked.requests.items()
        if key[0] == "POST"
        and (re.search(url_pattern, str(key[1])) if isinstance(url_pattern, re.Pattern) else url_pattern in str(key[1]))
    ]
    calls = [call for _, calls in posts for call in calls]
    data = calls[index].kwargs["data"]
    if isinstance(data, str):
        return {k: v[0] for k, v in parse_qs(data).items()}
    return {str(k): str(v) for k, v in data.items()}


def aura_message(form: dict[str, str]) -> dict[str, Any]:
    """Decode the ``message`` field of an Aura form post."""
    return json.loads(form["message"])


def mock_home(mocked: aioresponses, repeat: bool = False) -> None:
    """Serve the logged-in home page with a token cookie."""
    mocked.get(f"{BASE}/s/", status=200, body=home_page(), headers=home_headers(), repeat=repeat)


def mock_dead_home(mocked: aioresponses) -> None:
    """Serve a home page that bounces to the login page, as an expired session does."""
    mocked.get(f"{BASE}/s/", status=302, headers={"Location": f"{BASE}/s/login/?ec=302&startURL=%2Fs%2F"})
    mocked.get(f"{BASE}/s/login/?ec=302&startURL=%2Fs%2F", status=200, body=login_page())


async def login_to_mfa(client: SewClient, mocked: aioresponses) -> None:
    """Drive a successful credential login up to the channel-choice page."""
    mocked.get(f"{BASE}/s/login/", status=200, body=login_page())
    mocked.post(AURA_URL, status=200, payload=aura_envelope(FRONTDOOR))
    mocked.get(FRONTDOOR, status=302, headers={"Location": f"{BASE}/apex/PortalMFALoginFlow?retURL=%2F"})
    mocked.get(f"{BASE}/apex/PortalMFALoginFlow?retURL=%2F", status=200, body=mfa_channel_page())
    result = await client.async_login("user@example.com", "hunter2")
    assert result.mfa_required is True
    assert result.channels == ("Email", "SMS")


# ----------------------------------------------------------------------------- login


async def test_login_sends_credentials_with_login_context(client: SewClient, mocked: aioresponses) -> None:
    await login_to_mfa(client, mocked)
    form = posted_form(mocked, "/s/sfsites/aura")
    assert form["aura.token"] == "null"
    assert form["aura.pageURI"] == "/s/login/"
    context = json.loads(form["aura.context"])
    assert context["app"] == "siteforce:loginApp2"
    assert context["fwuid"] == FWUID_LOGIN
    (action,) = aura_message(form)["actions"]
    assert action["descriptor"] == "apex://cm_LoginAURA/ACTION$login"
    assert action["params"] == {"password": "hunter2", "startUrl": "/", "username": "user@example.com"}


async def test_login_rejects_bad_credentials(client: SewClient, mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/s/login/", status=200, body=login_page())
    mocked.post(AURA_URL, status=200, payload=aura_envelope("Your login attempt has failed. Please try again."))
    with pytest.raises(SewAuthError, match="login attempt has failed"):
        await client.async_login("user@example.com", "wrong")


async def test_login_without_mfa_lands_on_home(client: SewClient, mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/s/login/", status=200, body=login_page())
    mocked.post(AURA_URL, status=200, payload=aura_envelope(FRONTDOOR))
    mocked.get(FRONTDOOR, status=302, headers={"Location": f"{BASE}/s/"})
    mock_home(mocked)
    result = await client.async_login("user@example.com", "hunter2")
    assert result.mfa_required is False
    assert result.channels == ()


async def test_login_page_without_context_is_protocol_error(client: SewClient, mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/s/login/", status=200, body="<html><body>maintenance</body></html>")
    with pytest.raises(SewProtocolError, match="Aura context"):
        await client.async_login("user@example.com", "hunter2")


async def test_server_error_is_connection_error(client: SewClient, mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/s/login/", status=503, body="unavailable")
    with pytest.raises(SewConnectionError, match="503"):
        await client.async_login("user@example.com", "hunter2")


async def test_network_failure_is_connection_error(client: SewClient, mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/s/login/", exception=aiohttp.ClientConnectionError("dns"))
    with pytest.raises(SewConnectionError, match="dns"):
        await client.async_login("user@example.com", "hunter2")


# ------------------------------------------------------------------------------- mfa


async def test_request_code_posts_channel_and_viewstate(client: SewClient, mocked: aioresponses) -> None:
    await login_to_mfa(client, mocked)
    mocked.post(f"{BASE}/PortalMFALoginFlow", status=200, body=mfa_code_page(), content_type="text/xml")
    await client.async_request_code("SMS")
    form = posted_form(mocked, "/PortalMFALoginFlow")
    assert form["AJAXREQUEST"] == "_viewRoot"
    assert form["j_id0:mfaForm"] == "j_id0:mfaForm"
    assert form["channel"] == "SMS"
    assert form["j_id0:mfaForm:channelRadio"] == "SMS"
    assert form["j_id0:mfaForm:j_id26"] == "Send code"
    for key, value in VIEWSTATE_1.items():
        assert form[key] == value
    assert "otpBox1" not in form


async def test_request_code_rejects_unknown_channel(client: SewClient, mocked: aioresponses) -> None:
    await login_to_mfa(client, mocked)
    with pytest.raises(SewProtocolError, match="Unknown MFA channel"):
        await client.async_request_code("Carrier pigeon")


async def test_request_code_before_login_is_protocol_error(client: SewClient) -> None:
    with pytest.raises(SewProtocolError, match="async_login"):
        await client.async_request_code("Email")


async def test_submit_code_carries_refreshed_viewstate_and_completes_login(
    client: SewClient, mocked: aioresponses
) -> None:
    await login_to_mfa(client, mocked)
    mocked.post(f"{BASE}/PortalMFALoginFlow", status=200, body=mfa_code_page(), content_type="text/xml")
    await client.async_request_code("Email")
    mocked.post(
        f"{BASE}/PortalMFALoginFlow",
        status=200,
        body='<?xml version="1.0"?><html><head><meta name="Location" content="/s/" /></head></html>',
        headers={"Location": f"{BASE}/s/"},
        content_type="text/xml",
    )
    mock_home(mocked)
    await client.async_submit_code("12 34-56")
    form = posted_form(mocked, "/PortalMFALoginFlow", index=1)
    assert form["j_id0:mfaForm:otpHidden"] == "123456"
    assert [form[f"otpBox{n}"] for n in range(1, 7)] == list("123456")
    assert form["j_id0:mfaForm:j_id34"] == "Verify"
    for key, value in VIEWSTATE_2.items():
        assert form[key] == value
    assert form["com.salesforce.visualforce.ViewState"] != VIEWSTATE_1["com.salesforce.visualforce.ViewState"]


async def test_submit_wrong_code_raises_auth_error_and_allows_retry(client: SewClient, mocked: aioresponses) -> None:
    await login_to_mfa(client, mocked)
    mocked.post(f"{BASE}/PortalMFALoginFlow", status=200, body=mfa_code_page(), content_type="text/xml")
    await client.async_request_code("Email")
    mocked.post(
        f"{BASE}/PortalMFALoginFlow",
        status=200,
        body=mfa_code_page(error="The code you entered is invalid. Please try again."),
        content_type="text/xml",
    )
    with pytest.raises(SewAuthError, match="invalid"):
        await client.async_submit_code("000000")
    # The form is re-parsed so a second attempt can be made without restarting the flow.
    mocked.post(f"{BASE}/PortalMFALoginFlow", status=200, headers={"Location": f"{BASE}/s/"}, body="")
    mock_home(mocked)
    await client.async_submit_code("123456")


async def test_submit_code_with_wrong_length_is_rejected_locally(client: SewClient, mocked: aioresponses) -> None:
    await login_to_mfa(client, mocked)
    mocked.post(f"{BASE}/PortalMFALoginFlow", status=200, body=mfa_code_page(), content_type="text/xml")
    await client.async_request_code("Email")
    with pytest.raises(SewAuthError, match="6 digits"):
        await client.async_submit_code("1234")


async def test_submit_code_before_request_is_protocol_error(client: SewClient, mocked: aioresponses) -> None:
    await login_to_mfa(client, mocked)
    with pytest.raises(SewProtocolError, match="async_request_code"):
        await client.async_submit_code("123456")


# --------------------------------------------------------------------------- session


async def test_is_alive_true_when_home_issues_token(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    assert await client.async_is_alive() is True


async def test_is_alive_false_when_bounced_to_login(client: SewClient, mocked: aioresponses) -> None:
    mock_dead_home(mocked)
    assert await client.async_is_alive() is False


async def test_is_alive_false_when_home_has_no_token(client: SewClient, mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/s/", status=200, body=home_page())
    assert await client.async_is_alive() is False


async def test_cookie_export_import_round_trip(session: aiohttp.ClientSession, client: SewClient) -> None:
    session.cookie_jar.update_cookies({"sid": "SESSION-ID", "renderCtx": "ctx"}, URL(f"{BASE}/"))
    session.cookie_jar.update_cookies({"_ga": "analytics"}, URL("https://www.southeastwater.com.au/"))
    session.cookie_jar.update_cookies({"unrelated": "x"}, URL("https://example.com/"))
    exported = client.export_cookies()
    names = {c["name"] for c in exported}
    assert "sid" in names and "renderCtx" in names
    assert "unrelated" not in names
    assert all(isinstance(c["value"], str) for c in exported)
    json.dumps(exported)  # must be serialisable for config-entry storage

    async with aiohttp.ClientSession() as fresh:
        restored = SewClient(fresh, BASE)
        restored.import_cookies(exported)
        jar = fresh.cookie_jar.filter_cookies(URL(f"{BASE}/s/"))
        assert jar["sid"].value == "SESSION-ID"
        assert jar["renderCtx"].value == "ctx"
        assert "unrelated" not in jar


# -------------------------------------------------------------------------- discovery


async def test_discover_ids_uses_home_token_and_finds_records(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    accounts = [
        {
            "attributes": {
                "type": "Billing_Account__c",
                "url": f"/services/data/v60.0/sobjects/Billing_Account__c/{BILLING_ACCOUNT_ID}",
            },
            "Id": BILLING_ACCOUNT_ID,
            "HiAF_Account_Number_Check_Digit__c": "1234567890",
        }
    ]
    meters = [
        {
            "attributes": {
                "type": "Meter_Details__c",
                "url": f"/services/data/v60.0/sobjects/Meter_Details__c/{METER_ID}",
            },
            "Id": METER_ID,
            "Name": METER_SERIAL,
        }
    ]
    mocked.post(AURA_URL, status=200, payload=aura_envelope(accounts))
    mocked.post(AURA_URL, status=200, payload=aura_envelope(meters))
    ids = await client.async_discover_ids()
    assert ids == AccountIds(billing_account_id=BILLING_ACCOUNT_ID, meter_id=METER_ID, meter_serial=METER_SERIAL)

    first = posted_form(mocked, "/s/sfsites/aura", index=0)
    assert first["aura.token"] == AURA_TOKEN
    context = json.loads(first["aura.context"])
    assert context["app"] == "siteforce:communityApp"
    assert context["fwuid"] == FWUID_HOME
    assert context["loaded"] == {"APPLICATION@markup://siteforce:communityApp": HASH_HOME}
    (action,) = aura_message(first)["actions"]
    assert action["descriptor"] == "apex://cm_AccountBillingUsageAURA/ACTION$retrieveBillingAccounts"

    second = posted_form(mocked, "/s/sfsites/aura", index=1)
    (action,) = aura_message(second)["actions"]
    assert action["descriptor"] == "apex://cm_AccountBillingUsageAURA/ACTION$retrieveSObject"
    assert action["params"]["objectToReturn"] == "Meter_Details__c"
    assert BILLING_ACCOUNT_ID in action["params"]["whereClause"]


async def test_discover_ids_without_accounts_is_protocol_error(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    mocked.post(AURA_URL, status=200, payload=aura_envelope([]))
    with pytest.raises(SewProtocolError, match="No billing account"):
        await client.async_discover_ids()


async def test_discover_ids_when_not_logged_in_is_auth_error(client: SewClient, mocked: aioresponses) -> None:
    mock_dead_home(mocked)
    with pytest.raises(SewAuthError):
        await client.async_discover_ids()


# ------------------------------------------------------------------------------ usage


async def test_fetch_usage_sums_hourly_readings(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    readings = [0, 14, 4, 0, 0, 0, 4, 0, 42, 128, 53, 37, 35, 40, 81, 69, 213, 207, 25, 56, 151, 15, 1, 5]
    mocked.post(
        AURA_URL,
        status=200,
        payload=aura_envelope(usage_day("2026-09-12", [10] * 24), usage_day("2026-09-13", readings)),
    )
    usage = await client.async_fetch_usage(IDS, date(2026, 9, 12), date(2026, 9, 13))
    assert [u.day for u in usage] == [date(2026, 9, 12), date(2026, 9, 13)]
    assert usage[0].litres == 240
    assert usage[1].litres == 1180
    assert usage[1].readings == tuple(readings)
    assert usage[1].serial == METER_SERIAL
    assert usage[1].message == "Ok"
    assert all(u.available for u in usage)

    form = posted_form(mocked, "/s/sfsites/aura")
    actions = aura_message(form)["actions"]
    assert [a["id"] for a in actions] == ["1;a", "2;a"]
    assert all(a["descriptor"] == "aura://ApexActionController/ACTION$execute" for a in actions)
    assert actions[0]["params"]["classname"] == "MysewUsageBillingGraphController"
    assert actions[0]["params"]["method"] == "getUsageData"
    assert actions[0]["params"]["params"] == {
        "baId": BILLING_ACCOUNT_ID,
        "dateFrom": "2026-09-12",
        "dateTo": "2026-09-12",
        "meterId": METER_ID,
        "resolution": "hourly",
    }
    assert form["aura.pageURI"] == "/s/"


async def test_fetch_usage_marks_missing_days_unavailable(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    mocked.post(AURA_URL, status=200, payload=aura_envelope(usage_day("2026-09-13", None), {"returnValue": []}))
    usage = await client.async_fetch_usage(IDS, date(2026, 9, 13), date(2026, 9, 14))
    assert [u.available for u in usage] == [False, False]
    assert [u.litres for u in usage] == [0, 0]


async def test_fetch_usage_batches_large_ranges(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    start = date(2026, 6, 1)
    total_days = USAGE_BATCH_SIZE + 5
    days = [date.fromordinal(start.toordinal() + n) for n in range(total_days)]
    first_batch = [usage_day(d.isoformat(), [1] * 24) for d in days[:USAGE_BATCH_SIZE]]
    second_batch = [usage_day(d.isoformat(), [2] * 24) for d in days[USAGE_BATCH_SIZE:]]
    mocked.post(AURA_URL, status=200, payload=aura_envelope(*first_batch))
    mocked.post(AURA_URL, status=200, payload=aura_envelope(*second_batch))
    usage = await client.async_fetch_usage(IDS, days[0], days[-1])
    assert len(usage) == total_days
    assert usage[0].litres == 24 and usage[-1].litres == 48
    first = aura_message(posted_form(mocked, "/s/sfsites/aura", index=0))["actions"]
    second = aura_message(posted_form(mocked, "/s/sfsites/aura", index=1))["actions"]
    assert len(first) == USAGE_BATCH_SIZE and len(second) == 5


async def test_fetch_usage_rejects_reversed_range(client: SewClient) -> None:
    with pytest.raises(ValueError):
        await client.async_fetch_usage(IDS, date(2026, 9, 14), date(2026, 9, 13))


async def test_fetch_usage_invalid_session_is_auth_error(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    mocked.post(
        AURA_URL,
        status=200,
        payload={"exceptionEvent": True, "event": {"descriptor": "markup://aura:invalidSession"}},
    )
    with pytest.raises(SewAuthError, match="invalidSession"):
        await client.async_fetch_usage(IDS, date(2026, 9, 13), date(2026, 9, 13))


async def test_fetch_usage_action_error_is_protocol_error(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    payload = aura_envelope(None, state="ERROR")
    payload["actions"][0]["error"] = [{"message": "Attempt to de-reference a null object"}]
    mocked.post(AURA_URL, status=200, payload=payload)
    with pytest.raises(SewProtocolError, match="null object"):
        await client.async_fetch_usage(IDS, date(2026, 9, 13), date(2026, 9, 13))


async def test_fetch_usage_non_json_is_protocol_error(client: SewClient, mocked: aioresponses) -> None:
    mock_home(mocked)
    mocked.post(AURA_URL, status=200, body="<html>oops</html>", content_type="text/html")
    with pytest.raises(SewProtocolError, match="not JSON"):
        await client.async_fetch_usage(IDS, date(2026, 9, 13), date(2026, 9, 13))
