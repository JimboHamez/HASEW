/**
 * South East Water - Browserless Puppeteer script
 *
 * This script is executed inside Browserless Chrome via the /function endpoint.
 *
 * Flow:
 *   1. Log into the SEW portal (Salesforce Experience Cloud).
 *   2. Navigate to /s/usage so the Aura framework initialises fully.
 *   3. Extract the Aura token (auraToken) and framework UID (fwuid) from the
 *      page's JS context – both are required to authenticate Aura API calls.
 *   4. If billingAccountId / meterId were not supplied, discover them from
 *      LSSIndex entries in localStorage written by the SEW LWC components.
 *   5. For each date in startDate..endDate POST to the Salesforce Aura endpoint
 *      using the exact URL-encoded body expected by
 *      MysewUsageBillingGraphController.getUsageData.
 *   6. Return all usage records as a structured JSON object.
 *
 * Context variables (supplied via the Browserless `context` field):
 *   username          {string}  SEW login email
 *   password          {string}  SEW login password
 *   billingAccountId  {string}  (optional) cached billing account ID
 *   meterId           {string}  (optional) cached meter ID
 *   startDate         {string}  ISO date "YYYY-MM-DD"
 *   endDate           {string}  ISO date "YYYY-MM-DD"
 */

// ---------------------------------------------------------------------------
// Helper: build the URL-encoded Aura request body for getUsageData.
//
// This exactly mirrors the req_body function from the original pyscript
// implementation.  The portal's backend is a Salesforce Aura endpoint that
// expects application/x-www-form-urlencoded with three fields:
//   message      – JSON-encoded Aura actions descriptor
//   aura.context – JSON-encoded Aura framework context (must include fwuid)
//   aura.pageURI – the page path the request originates from
//   aura.token   – the user's Aura session token
// ---------------------------------------------------------------------------
const buildAuraRequestBody = (dateFor, meterSerial, accountNum, auraToken, fwuid) => {
  // Fixed production value for the "loaded" APPLICATION hash.
  // This is baked into the portal's JS bundle; update if the portal is redeployed.
  const LOADED_APP_HASH = "1422_wotCJi-4iLy4EgTPC6RQ4g";

  const messageObj = {
    actions: [
      {
        id: "1084;a",
        descriptor: "aura://ApexActionController/ACTION$execute",
        callingDescriptor: "UNKNOWN",
        params: {
          namespace: "",
          classname: "MysewUsageBillingGraphController",
          method: "getUsageData",
          params: {
            baId:       accountNum,
            meterId:    meterSerial,
            dateFrom:   dateFor,
            dateTo:     dateFor,
            resolution: "hourly",
          },
          cacheable:      false,
          isContinuation: false,
        },
      },
    ],
  };

  const contextObj = {
    mode:   "PROD",
    fwuid:  fwuid,
    app:    "siteforce:communityApp",
    loaded: {
      [`APPLICATION@markup://siteforce:communityApp`]: LOADED_APP_HASH,
    },
    dn:      [],
    globals: { srcdoc: true },
    uad:     true,
  };

  return (
    "message="        + encodeURIComponent(JSON.stringify(messageObj)) +
    "&aura.context="  + encodeURIComponent(JSON.stringify(contextObj)) +
    "&aura.pageURI="  + encodeURIComponent("/s/usage") +
    "&aura.token="    + encodeURIComponent(auraToken)
  );
};

// ---------------------------------------------------------------------------
// Helper: produce an array of "YYYY-MM-DD" strings for every day in range
// ---------------------------------------------------------------------------
const dateRange = (startDateStr, endDateStr) => {
  const dates = [];
  const start = new Date(startDateStr + "T00:00:00");
  const end   = new Date(endDateStr   + "T00:00:00");
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates;
};

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------
export default async ({ page, context }) => {
  const {
    username,
    password,
    billingAccountId: suppliedAccountId,
    meterId: suppliedMeterId,
    startDate,
    endDate,
  } = context;

  const BASE_URL = "https://my.southeastwater.com.au";
  const AURA_URL = `${BASE_URL}/s/sfsites/aura`;

  // Fallback fwuid – the known production value embedded in the portal JS bundle.
  // Used only when $A.getContext() and DOM scanning both fail.
  const FALLBACK_FWUID =
    "REdtNUF5ejJUNWxpdVllUjQtUzV4UTFLcUUxeUY3ZVB6dE9hR0VheDVpb2cxMy4zMzU1NDQzMi41MDMzMTY0OA";

  // -------------------------------------------------------------------------
  // 1. Log in
  // -------------------------------------------------------------------------
  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle2", timeout: 60000 });

  await page.waitForSelector(
    'input[type="email"], input[name="username"], input[id*="username"]',
    { timeout: 30000 }
  );

  await page.type(
    'input[type="email"], input[name="username"], input[id*="username"]',
    username,
    { delay: 40 }
  );
  await page.type(
    'input[type="password"], input[name="password"], input[id*="password"]',
    password,
    { delay: 40 }
  );

  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle2", timeout: 60000 }),
    page.click('button[type="submit"], input[type="submit"], button[id*="login"]'),
  ]);

  // -------------------------------------------------------------------------
  // 2. Navigate to /s/usage so the Aura framework and LWC components boot,
  //    which also populates localStorage with account / meter data.
  // -------------------------------------------------------------------------
  await page.goto(`${BASE_URL}/s/usage`, { waitUntil: "networkidle2", timeout: 60000 });

  // Allow extra time for async LWC initialisation
  await page.waitForTimeout(6000);

  // -------------------------------------------------------------------------
  // 3. Extract auraToken and fwuid
  //
  //    Priority:
  //      a) $A.getContext() – the canonical Aura JS API
  //      b) Inline <script> scanning for embedded JSON blobs
  //      c) Performance resource URL scanning (if a previous Aura call was made)
  // -------------------------------------------------------------------------
  const auraInfo = await page.evaluate(() => {
    let auraToken = null;
    let fwuid     = null;

    // (a) Aura JS API
    try {
      if (typeof $A !== "undefined" && $A.getContext) {
        const ctx = $A.getContext();
        if (ctx.getToken) auraToken = ctx.getToken();
        if (ctx.getFwuid) fwuid     = ctx.getFwuid();
      }
    } catch (_) {}

    // (b) DOM script scanning
    if (!auraToken || !fwuid) {
      for (const s of Array.from(document.querySelectorAll("script"))) {
        const src = s.textContent || "";
        if (!auraToken) {
          const m = src.match(/"token"\s*:\s*"([^"]{20,})"/);
          if (m) auraToken = m[1];
        }
        if (!fwuid) {
          const m = src.match(/"fwuid"\s*:\s*"([^"]{10,})"/);
          if (m) fwuid = m[1];
        }
        if (auraToken && fwuid) break;
      }
    }

    // (c) Performance entry scanning
    if (!auraToken) {
      for (const e of performance.getEntriesByType("resource")) {
        if (e.name.includes("aura.token=")) {
          const m = e.name.match(/aura\.token=([^&]+)/);
          if (m) { auraToken = decodeURIComponent(m[1]); break; }
        }
        if (e.name.includes("aura.context=") && !fwuid) {
          const m = e.name.match(/aura\.context=([^&]+)/);
          if (m) {
            try {
              const ctx = JSON.parse(decodeURIComponent(m[1]));
              if (ctx.fwuid) fwuid = ctx.fwuid;
            } catch (_) {}
          }
        }
      }
    }

    return { auraToken, fwuid };
  });

  const fwuid     = auraInfo.fwuid     || FALLBACK_FWUID;
  const auraToken = auraInfo.auraToken;

  if (!auraToken) {
    return {
      error:
        "Could not extract Aura token from page. " +
        "Ensure login succeeded and the /s/usage page loaded correctly.",
    };
  }

  // -------------------------------------------------------------------------
  // 4. Discover billingAccountId and meterId from localStorage if not supplied
  // -------------------------------------------------------------------------
  let billingAccountId = suppliedAccountId || "";
  let meterId          = suppliedMeterId   || "";

  if (!billingAccountId || !meterId) {
    const discovered = await page.evaluate(() => {
      let baId = null;
      let mId  = null;

      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        const val = localStorage.getItem(key);
        if (!val) continue;

        // Scan every localStorage value for the patterns we need.
        // SEW stores data under LSSIndex:LOCAL{"namespace":"c"} style keys.
        if (!baId) {
          const m = val.match(/"(?:baId|billingAccountId)"\s*:\s*"([^"]+)"/);
          if (m) baId = m[1];
        }
        if (!mId) {
          const m = val.match(/"meterId"\s*:\s*"([^"]+)"/);
          if (m) mId = m[1];
        }
        if (baId && mId) break;
      }
      return { billingAccountId: baId, meterId: mId };
    });

    billingAccountId = billingAccountId || discovered.billingAccountId || "";
    meterId          = meterId          || discovered.meterId          || "";
  }

  if (!billingAccountId || !meterId) {
    return {
      error:
        "Could not determine billingAccountId or meterId. " +
        "Please provide them explicitly in the integration options.",
      auraTokenFound: true,
    };
  }

  // -------------------------------------------------------------------------
  // 5. Fetch usage data for each date in the requested range
  //
  //    We POST the Aura request body to /s/sfsites/aura for each individual
  //    day (matching the original pyscript behaviour: one request per date).
  //    The Aura response wraps the return value inside:
  //      response.actions[0].returnValue
  // -------------------------------------------------------------------------
  const dates   = dateRange(startDate, endDate);
  const records = [];

  for (const dateFor of dates) {
    const requestBody = buildAuraRequestBody(
      dateFor,
      meterId,
      billingAccountId,
      auraToken,
      fwuid
    );

    const result = await page.evaluate(
      async (auraUrl, body, dateFor) => {
        try {
          const resp = await fetch(auraUrl, {
            method:  "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body:    body,
          });

          if (!resp.ok) {
            return { error: `HTTP ${resp.status} ${resp.statusText}`, date: dateFor };
          }

          const json = await resp.json();

          // Validate the Aura response envelope
          if (!json.actions || !Array.isArray(json.actions) || json.actions.length === 0) {
            return { error: "Unexpected Aura response shape", raw: JSON.stringify(json).slice(0, 200), date: dateFor };
          }

          const action = json.actions[0];

          if (action.state !== "SUCCESS") {
            return {
              error:  `Aura action state: ${action.state}`,
              errors: action.error,
              date:   dateFor,
            };
          }

          return { date: dateFor, data: action.returnValue };
        } catch (e) {
          return { error: e.message, date: dateFor };
        }
      },
      AURA_URL,
      requestBody,
      dateFor
    );

    if (result.error) {
      // Log but don't abort – continue with remaining dates
      console.warn(`SEW: error for ${dateFor}: ${result.error}`);
      records.push({ date: dateFor, error: result.error });
    } else {
      records.push(result);
    }

    // Brief pause between requests to avoid overwhelming the portal
    await page.waitForTimeout(500);
  }

  // -------------------------------------------------------------------------
  // 6. Return structured result
  // -------------------------------------------------------------------------
  return {
    billingAccountId,
    meterId,
    startDate,
    endDate,
    fwuid,
    usage: records,
  };
};
