/**
 * Water Portal - Browserless Puppeteer script
 *
 * Supports South East Water and Yarra Valley Water (both Salesforce Experience
 * Cloud / Aura portals sharing the same architecture).
 *
 * This script is executed inside Browserless Chrome via the /function endpoint.
 *
 * Flow:
 *   1. Log into the portal (Salesforce Experience Cloud).
 *   2. Navigate to /s/usage so the Aura framework initialises fully.
 *   3. Extract auraToken and fwuid from the page's JS context.
 *   4. Discover billingAccountId and meterId from localStorage if not supplied.
 *   5. Build a SINGLE batched Aura request containing one action per day in
 *      the requested date range and POST it once to the Aura endpoint.
 *   6. Unpack the per-action responses and return structured JSON.
 *
 * Context variables (supplied via the Browserless `context` field):
 *   username          {string}  Portal login email
 *   password          {string}  Portal login password
 *   portal            {string}  "sew" | "yvw"  (default: "sew")
 *   billingAccountId  {string}  (optional) cached billing account ID
 *   meterId           {string}  (optional) cached meter ID
 *   startDate         {string}  ISO date "YYYY-MM-DD"
 *   endDate           {string}  ISO date "YYYY-MM-DD"
 */

// ---------------------------------------------------------------------------
// Portal configuration map
// Both portals are Salesforce Experience Cloud with identical Aura structure;
// only the base URL, Apex class name, and fallback fwuid differ.
// ---------------------------------------------------------------------------
const PORTALS = {
  sew: {
    baseUrl:       "https://my.southeastwater.com.au",
    apexClassname: "MysewUsageBillingGraphController",
    fallbackFwuid: "REdtNUF5ejJUNWxpdVllUjQtUzV4UTFLcUUxeUY3ZVB6dE9hR0VheDVpb2cxMy4zMzU1NDQzMi41MDMzMTY0OA",
    loadedAppHash: "1422_wotCJi-4iLy4EgTPC6RQ4g",
  },
  yvw: {
    baseUrl:       "https://my.yvw.com.au",
    apexClassname: "MyyvwUsageBillingGraphController",
    fallbackFwuid: "",   // extracted at runtime; no known fallback yet
    loadedAppHash: "",   // extracted at runtime
  },
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
// Helper: build a single batched Aura request body.
//
// The Aura framework supports multiple actions in one POST – each action gets
// its own entry in the `actions` array with a unique id.  The server returns
// an `actions` array in the same order so we can correlate by index or id.
//
// This exactly mirrors the req_body function from the original pyscript
// implementation, extended to cover multiple dates in one call.
// ---------------------------------------------------------------------------
const buildBatchedAuraBody = (dates, meterSerial, accountNum, auraToken, fwuid, apexClassname, loadedAppHash) => {
  const contextObj = {
    mode:   "PROD",
    fwuid:  fwuid,
    app:    "siteforce:communityApp",
    loaded: loadedAppHash
      ? { [`APPLICATION@markup://siteforce:communityApp`]: loadedAppHash }
      : {},
    dn:      [],
    globals: { srcdoc: true },
    uad:     true,
  };

  const actions = dates.map((dateFor, idx) => ({
    // Use incrementing IDs in the same format the portal uses: "1084;a", "1085;a" …
    id:                `${1084 + idx};a`,
    descriptor:        "aura://ApexActionController/ACTION$execute",
    callingDescriptor: "UNKNOWN",
    params: {
      namespace:      "",
      classname:      apexClassname,
      method:         "getUsageData",
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
  }));

  const messageObj = { actions };

  return (
    "message="       + encodeURIComponent(JSON.stringify(messageObj)) +
    "&aura.context=" + encodeURIComponent(JSON.stringify(contextObj)) +
    "&aura.pageURI=" + encodeURIComponent("/s/usage") +
    "&aura.token="   + encodeURIComponent(auraToken)
  );
};

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------
export default async ({ page, context }) => {
  const {
    username,
    password,
    portal:              portalKey = "sew",
    billingAccountId:    suppliedAccountId = "",
    meterId:             suppliedMeterId   = "",
    startDate,
    endDate,
  } = context;

  const portalCfg = PORTALS[portalKey] || PORTALS["sew"];
  const BASE_URL  = portalCfg.baseUrl;
  const AURA_URL  = `${BASE_URL}/s/sfsites/aura`;

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
  // 2. Navigate to /s/usage so Aura and LWC components fully initialise,
  //    which also causes the portal to write account data to localStorage.
  // -------------------------------------------------------------------------
  await page.goto(`${BASE_URL}/s/usage`, { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForTimeout(6000);

  // -------------------------------------------------------------------------
  // 3. Extract auraToken, fwuid, and loadedAppHash
  //
  //    Priority:
  //      a) $A.getContext() – the canonical Aura JS API
  //      b) Inline <script> tag scanning for embedded JSON blobs
  //      c) Performance resource URL scanning (prior Aura calls leave traces)
  // -------------------------------------------------------------------------
  const auraInfo = await page.evaluate(() => {
    let auraToken    = null;
    let fwuid        = null;
    let loadedAppHash = null;

    // (a) Aura JS API
    try {
      if (typeof $A !== "undefined" && $A.getContext) {
        const ctx = $A.getContext();
        if (ctx.getToken)  auraToken    = ctx.getToken();
        if (ctx.getFwuid)  fwuid        = ctx.getFwuid();
        // Try to pull loadedAppHash from the loaded map
        if (ctx.getLoaded) {
          const loaded = ctx.getLoaded();
          const appKey = Object.keys(loaded || {}).find(k => k.startsWith("APPLICATION@"));
          if (appKey) loadedAppHash = loaded[appKey];
        }
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
        if (!loadedAppHash) {
          const m = src.match(/"APPLICATION@markup:\/\/siteforce:communityApp"\s*:\s*"([^"]+)"/);
          if (m) loadedAppHash = m[1];
        }
        if (auraToken && fwuid && loadedAppHash) break;
      }
    }

    // (c) Performance entry scanning
    if (!auraToken) {
      for (const e of performance.getEntriesByType("resource")) {
        if (e.name.includes("aura.token=")) {
          const m = e.name.match(/aura\.token=([^&]+)/);
          if (m) { auraToken = decodeURIComponent(m[1]); }
        }
        if (e.name.includes("aura.context=") && (!fwuid || !loadedAppHash)) {
          const m = e.name.match(/aura\.context=([^&]+)/);
          if (m) {
            try {
              const ctx = JSON.parse(decodeURIComponent(m[1]));
              if (ctx.fwuid && !fwuid) fwuid = ctx.fwuid;
              if (ctx.loaded && !loadedAppHash) {
                const appKey = Object.keys(ctx.loaded).find(k => k.startsWith("APPLICATION@"));
                if (appKey) loadedAppHash = ctx.loaded[appKey];
              }
            } catch (_) {}
          }
        }
        if (auraToken && fwuid && loadedAppHash) break;
      }
    }

    return { auraToken, fwuid, loadedAppHash };
  });

  const fwuid        = auraInfo.fwuid        || portalCfg.fallbackFwuid;
  const loadedAppHash = auraInfo.loadedAppHash || portalCfg.loadedAppHash;
  const auraToken    = auraInfo.auraToken;

  if (!auraToken) {
    return {
      error: "Could not extract Aura token from page. Ensure login succeeded and the /s/usage page loaded correctly.",
    };
  }

  // -------------------------------------------------------------------------
  // 4. Discover billingAccountId and meterId from localStorage if not supplied
  // -------------------------------------------------------------------------
  let billingAccountId = suppliedAccountId;
  let meterId          = suppliedMeterId;

  if (!billingAccountId || !meterId) {
    const discovered = await page.evaluate(() => {
      let baId = null;
      let mId  = null;
      for (let i = 0; i < localStorage.length; i++) {
        const val = localStorage.getItem(localStorage.key(i));
        if (!val) continue;
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
  // 5. Build and POST a single batched Aura request for all dates at once.
  //
  //    Aura supports multiple actions[] entries in one POST – we include one
  //    action per day.  The response actions[] is returned in the same order,
  //    so we zip dates ↔ actions by index.
  //
  //    For very large ranges (>60 days) we split into chunks of 60 to keep
  //    individual request bodies manageable and avoid Aura server timeouts.
  // -------------------------------------------------------------------------
  const CHUNK_SIZE = 60;
  const allDates   = dateRange(startDate, endDate);
  const records    = [];

  // Chunk the dates
  const chunks = [];
  for (let i = 0; i < allDates.length; i += CHUNK_SIZE) {
    chunks.push(allDates.slice(i, i + CHUNK_SIZE));
  }

  for (const chunkDates of chunks) {
    const requestBody = buildBatchedAuraBody(
      chunkDates,
      meterId,
      billingAccountId,
      auraToken,
      fwuid,
      portalCfg.apexClassname,
      loadedAppHash
    );

    const chunkResults = await page.evaluate(
      async (auraUrl, body, dates) => {
        try {
          const resp = await fetch(auraUrl, {
            method:  "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body:    body,
          });

          if (!resp.ok) {
            // Return an error entry for every date in this chunk
            return dates.map(d => ({ date: d, error: `HTTP ${resp.status} ${resp.statusText}` }));
          }

          const json = await resp.json();

          if (!json.actions || !Array.isArray(json.actions)) {
            return dates.map(d => ({
              date: d,
              error: "Unexpected Aura response shape: " + JSON.stringify(json).slice(0, 150),
            }));
          }

          // Zip response actions with the dates we requested (same order guaranteed)
          return json.actions.map((action, idx) => {
            const dateFor = dates[idx] || "unknown";
            if (action.state !== "SUCCESS") {
              return {
                date:   dateFor,
                error:  `Aura action state: ${action.state}`,
                errors: action.error,
              };
            }
            return { date: dateFor, data: action.returnValue };
          });
        } catch (e) {
          return dates.map(d => ({ date: d, error: e.message }));
        }
      },
      AURA_URL,
      requestBody,
      chunkDates
    );

    for (const r of chunkResults) {
      if (r.error) {
        console.warn(`Water portal: error for ${r.date}: ${r.error}`);
      }
      records.push(r);
    }
  }

  // -------------------------------------------------------------------------
  // 6. Return structured result
  // -------------------------------------------------------------------------
  return {
    portal: portalKey,
    billingAccountId,
    meterId,
    startDate,
    endDate,
    fwuid,
    usage: records,
  };
};
