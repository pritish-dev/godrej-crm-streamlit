/**
 * WhatsApp Order-Status Chatbot for Interio by Godrej (4S Interiors, Patia)
 * ------------------------------------------------------------------------
 * Runs 100% free on Google Apps Script as a WhatsApp Cloud API webhook.
 *
 * What it does
 *   1. Customer messages the WhatsApp business number.
 *   2. Bot asks the language (English / हिंदी / ଓଡ଼ିଆ).
 *   3. Bot asks for Order No / Contact Number / Customer Name.
 *   4. It finds the order in the CRM order tabs -> reads the GODREJ SO NO.
 *   5. It looks that SO up in MIS_Daily -> computes the *committed status*
 *      and the *expected commitment date* (time it will take to get committed).
 *   6. It replies in the chosen language. No price / value is ever shown.
 *
 * Data model (matches the Streamlit CRM code):
 *   - Order tabs live in the CRM spreadsheet. Their names are listed in the
 *     "SHEET_DETAILS" tab, columns "Franchise_sheets" and "four_s_sheets".
 *     Each order tab has: ORDER NO, GODREJ SO NO, CUSTOMER NAME,
 *     CONTACT NUMBER, DELIVERY STATUS, ...
 *   - MIS_Daily lives in the OPS spreadsheet with columns:
 *     "Sales Order No.", "Sales Order Qty", "Sales Order Committed Qty",
 *     "Inventory Commitment Date".
 *   - An SO is FULLY COMMITTED when every line item has
 *     Sales Order Qty == Sales Order Committed Qty (see delivery_readiness.py).
 *     Commit date = MAX "Inventory Commitment Date" across the SO's items.
 *
 * SETUP: see whatsapp_bot/SETUP_GUIDE.md. Fill CONFIG below, then deploy
 * this script as a Web App (Execute as: Me, Access: Anyone).
 */

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG  — fill these in (see SETUP_GUIDE.md). Prefer Script Properties for
// the secret token, but plain constants work too for a quick start.
// ═══════════════════════════════════════════════════════════════════════════

var CONFIG = {
  // --- WhatsApp Cloud API (from Meta) ---
  // Best practice: store WHATSAPP_TOKEN and PHONE_NUMBER_ID in Script
  // Properties (Project Settings > Script Properties) and leave these blank.
  WHATSAPP_TOKEN:  '',            // e.g. 'EAAG...'  (Permanent access token)
  PHONE_NUMBER_ID: '',            // e.g. '123456789012345'
  // You invent this string; paste the SAME value into Meta's webhook setup.
  VERIFY_TOKEN:    'interio4s-verify',

  // --- Google Sheets (from services/sheet_config.py) ---
  CRM_SPREADSHEET_ID: '1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54',
  // If your OPS sheets (MIS_Daily, SHEET_DETAILS) live in a SEPARATE
  // spreadsheet, put its ID here. If everything is in one file, leave this
  // equal to CRM_SPREADSHEET_ID.
  OPS_SPREADSHEET_ID: '1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54',

  // --- Sheet/tab + column names (change only if your headers differ) ---
  MIS_TAB:            'MIS_Daily',
  SHEET_DETAILS_TAB:  'SHEET_DETAILS',
  // Column headers used for lookup (matched case-insensitively, spaces collapsed)
  COL_ORDER_NO:       'ORDER NO',
  COL_GODREJ_SO:      'GODREJ SO NO',
  COL_CUSTOMER:       'CUSTOMER NAME',
  COL_CONTACT:        'CONTACT NUMBER',
  COL_DELIVERY:       'DELIVERY STATUS',
  // MIS columns
  MIS_SO:             'Sales Order No.',
  MIS_QTY:            'Sales Order Qty',
  MIS_COMMITTED_QTY:  'Sales Order Committed Qty',
  MIS_COMMIT_DATE:    'Inventory Commitment Date',

  // Session time-to-live (seconds). 1 hour is plenty for one conversation.
  SESSION_TTL: 3600
};

function _prop(key, fallback) {
  var v = PropertiesService.getScriptProperties().getProperty(key);
  return (v && String(v).trim()) ? v : fallback;
}
function waToken()  { return _prop('WHATSAPP_TOKEN',  CONFIG.WHATSAPP_TOKEN); }
function phoneId()  { return _prop('PHONE_NUMBER_ID', CONFIG.PHONE_NUMBER_ID); }
function verifyTok(){ return _prop('VERIFY_TOKEN',    CONFIG.VERIFY_TOKEN); }

// ═══════════════════════════════════════════════════════════════════════════
// WEBHOOK ENTRY POINTS
// ═══════════════════════════════════════════════════════════════════════════

/** Meta calls this once to verify the webhook (hub.challenge handshake). */
function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p['hub.mode'] === 'subscribe' && p['hub.verify_token'] === verifyTok()) {
    return ContentService.createTextOutput(p['hub.challenge'] || '');
  }
  return ContentService.createTextOutput('OK');
}

/** Meta POSTs incoming messages here. */
function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    var entry = (body.entry || [])[0] || {};
    var change = (entry.changes || [])[0] || {};
    var value = change.value || {};
    var messages = value.messages || [];
    if (!messages.length) {
      return _ok(); // status callbacks etc. — nothing to do
    }
    var msg = messages[0];
    var from = msg.from;                 // customer's WhatsApp number (wa_id)
    var text = _extractText(msg);        // typed text or button/list reply id
    handleMessage(from, text);
  } catch (err) {
    console.error('doPost error: ' + err);
  }
  return _ok(); // ALWAYS return 200 fast so Meta doesn't retry
}

function _ok() { return ContentService.createTextOutput('OK'); }

/** Pull user intent out of any WhatsApp message type. */
function _extractText(msg) {
  if (msg.type === 'text' && msg.text) return (msg.text.body || '').trim();
  if (msg.type === 'interactive' && msg.interactive) {
    var it = msg.interactive;
    if (it.button_reply) return (it.button_reply.id || it.button_reply.title || '').trim();
    if (it.list_reply)   return (it.list_reply.id   || it.list_reply.title   || '').trim();
  }
  if (msg.type === 'button' && msg.button) return (msg.button.text || '').trim();
  return '';
}

// ═══════════════════════════════════════════════════════════════════════════
// CONVERSATION FLOW
// ═══════════════════════════════════════════════════════════════════════════

function handleMessage(from, text) {
  var s = getSession(from);
  var lower = (text || '').toLowerCase();

  // Global reset commands
  if (['hi', 'hello', 'hey', 'start', 'menu', 'namaste', 'namaskar'].indexOf(lower) >= 0) {
    s.step = 'await_lang';
    saveSession(from, s);
    askLanguage(from);
    return;
  }

  // Language selection (button ids: lang_en / lang_hi / lang_or)
  if (text.indexOf('lang_') === 0 || s.step === 'await_lang') {
    var lang = parseLang(text);
    if (!lang) { askLanguage(from); return; }
    s.lang = lang;
    s.step = 'await_query';
    saveSession(from, s);
    sendText(from, t(lang, 'ask_query'));
    return;
  }

  // Not started yet -> greet + ask language
  if (!s.lang) {
    s.step = 'await_lang';
    saveSession(from, s);
    askLanguage(from);
    return;
  }

  // Step 1: expecting an order identifier (Order No / Name) or a contact number
  if (s.step === 'await_query') {
    if (!text) { sendText(from, t(s.lang, 'ask_query')); return; }
    startLookup(from, s, text);
    return;
  }

  // Step 2: expecting the registered contact number to verify identity
  if (s.step === 'await_verify') {
    if (!text) { sendText(from, t(s.lang, 'ask_verify')); return; }
    verifyAndReply(from, s, text);
    return;
  }

  // Fallback
  askLanguage(from);
}

function parseLang(text) {
  var x = (text || '').toLowerCase();
  if (x === 'lang_en' || x.indexOf('eng') >= 0 || x === '1') return 'en';
  if (x === 'lang_hi' || x.indexOf('hind') >= 0 || x === '2') return 'hi';
  if (x === 'lang_or' || x.indexOf('odi') >= 0 || x.indexOf('oriy') >= 0 || x === '3') return 'or';
  return null;
}

/** Send the 3-language selector as interactive buttons. */
function askLanguage(from) {
  var payload = {
    messaging_product: 'whatsapp',
    to: from,
    type: 'interactive',
    interactive: {
      type: 'button',
      body: { text: 'Please choose your language\nकृपया अपनी भाषा चुनें\nଦୟାକରି ଆପଣଙ୍କ ଭାଷା ବାଛନ୍ତୁ' },
      action: {
        buttons: [
          { type: 'reply', reply: { id: 'lang_en', title: 'English' } },
          { type: 'reply', reply: { id: 'lang_hi', title: 'हिंदी' } },
          { type: 'reply', reply: { id: 'lang_or', title: 'ଓଡ଼ିଆ' } }
        ]
      }
    }
  };
  waSend(payload);
}

// ═══════════════════════════════════════════════════════════════════════════
// LOOKUP: order -> Godrej SO -> MIS committed status
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Step 1. The customer sent an Order No / Name, or a contact number.
 *
 * - If the query is a phone number (>=10 digits), it IS the verification:
 *   match it against CONTACT NUMBER and reveal directly.
 * - Otherwise it's an identifier (order no / Godrej SO / name): find the
 *   candidate orders but DO NOT reveal anything yet — ask for the registered
 *   contact number first (two-factor). Candidates are stashed in the session.
 */
function startLookup(from, s, query) {
  var lang = s.lang;
  var q = String(query || '').trim();

  // Path A — customer typed a phone number: self-verifying lookup.
  if (digits10(q).length >= 10) {
    var byContact = searchOrders(q, 'contact');
    if (!byContact.length) {
      sendText(from, t(lang, 'not_found'));
      return; // stay in await_query
    }
    revealOrders(from, lang, byContact);
    return;
  }

  // Path B — identifier lookup. Find candidates, then require verification.
  var candidates = searchOrders(q, 'identifier');
  if (!candidates.length) {
    sendText(from, t(lang, 'not_found'));
    return; // stay in await_query
  }

  // Stash a compact copy of candidates (avoid re-scanning + avoid revealing).
  s.pending = candidates.map(function (o) {
    return { orderNo: o.orderNo, godrejSO: o.godrejSO, customer: o.customer,
             contact: o.contact, delivery: o.delivery };
  });
  s.attempts = 0;
  s.step = 'await_verify';
  saveSession(from, s);
  sendText(from, t(lang, 'ask_verify'));
}

/**
 * Step 2. The customer sent a contact number to verify. Only orders whose
 * CONTACT NUMBER matches the number they entered are revealed.
 */
function verifyAndReply(from, s, entered) {
  var lang = s.lang;
  var enteredDigits = digits10(entered);
  var pending = s.pending || [];

  if (enteredDigits.length < 10) {
    sendText(from, t(lang, 'ask_verify'));
    return;
  }

  var matched = pending.filter(function (o) {
    return digits10(o.contact) === enteredDigits;
  });

  if (!matched.length) {
    s.attempts = (s.attempts || 0) + 1;
    if (s.attempts >= 3) {
      // Give up on this identifier; reset to a fresh query.
      s.step = 'await_query';
      s.pending = null;
      s.attempts = 0;
      saveSession(from, s);
      sendText(from, t(lang, 'verify_giveup'));
      return;
    }
    saveSession(from, s);
    sendText(from, t(lang, 'verify_fail'));
    return; // stay in await_verify for another attempt
  }

  // Verified — reveal, then reset for the next query.
  s.step = 'await_query';
  s.pending = null;
  s.attempts = 0;
  saveSession(from, s);
  revealOrders(from, lang, matched);
}

/** Compose and send the committed-status reply for a set of orders. */
function revealOrders(from, lang, orders) {
  var replies = [];
  var seenSO = {};
  for (var i = 0; i < orders.length && replies.length < 5; i++) {
    var o = orders[i];
    var so = o.godrejSO;
    if (!so || seenSO[so]) continue;
    seenSO[so] = true;
    replies.push(buildStatusReply(lang, o));
  }
  if (!replies.length) {
    sendText(from, t(lang, 'no_so'));
    return;
  }
  sendText(from, replies.join('\n\n──────────\n\n') + '\n\n' + t(lang, 'footer'));
}

/**
 * Scan all order tabs and return candidate rows as
 * {orderNo, godrejSO, customer, contact, delivery}.
 *
 * mode:
 *   'contact'    — match rows whose CONTACT NUMBER equals `query` (digit match).
 *                  This path is self-verifying: the customer supplied the number.
 *   'identifier' — match rows on ORDER NO (exact), GODREJ SO (exact) or
 *                  CUSTOMER NAME (substring). These are NOT revealed until the
 *                  customer also passes contact-number verification.
 */
function searchOrders(query, mode) {
  var q = String(query || '').trim();
  var qUpper = q.toUpperCase();
  var qDigits = digits10(q);
  var results = [];

  var tabs = getOrderTabNames();
  var ss = SpreadsheetApp.openById(CONFIG.CRM_SPREADSHEET_ID);

  for (var ti = 0; ti < tabs.length; ti++) {
    var sheet = ss.getSheetByName(tabs[ti]);
    if (!sheet) continue;
    var values = sheet.getDataRange().getValues();
    if (values.length < 2) continue;
    var idx = headerIndex(values[0]);
    var iOrder = idx[norm(CONFIG.COL_ORDER_NO)];
    var iSO    = idx[norm(CONFIG.COL_GODREJ_SO)];
    var iCust  = idx[norm(CONFIG.COL_CUSTOMER)];
    var iCont  = idx[norm(CONFIG.COL_CONTACT)];
    var iDel   = idx[norm(CONFIG.COL_DELIVERY)];
    if (iSO === undefined) continue; // this tab has no Godrej SO column

    for (var r = 1; r < values.length; r++) {
      var row = values[r];
      var orderNo = iOrder !== undefined ? String(row[iOrder] || '').trim() : '';
      var cust    = iCust  !== undefined ? String(row[iCust]  || '').trim() : '';
      var cont    = iCont  !== undefined ? String(row[iCont]  || '').trim() : '';
      var so      = String(row[iSO] || '').trim();
      var del     = iDel   !== undefined ? String(row[iDel]   || '').trim() : '';

      var match = false;
      if (mode === 'contact') {
        // Self-verifying lookup by registered contact number.
        if (qDigits && digits10(cont) === qDigits) match = true;
      } else {
        // Identifier lookup (order no / Godrej SO / name). Contact NOT used here.
        if (orderNo && orderNo.toUpperCase() === qUpper) match = true;
        else if (so && so.toUpperCase() === qUpper) match = true;
        else if (q.length >= 3 && cust && cust.toUpperCase().indexOf(qUpper) >= 0) match = true;
      }

      if (match) {
        results.push({
          orderNo: orderNo, godrejSO: so, customer: cust,
          contact: cont, delivery: del
        });
      }
    }
  }
  return results;
}

/** Read SHEET_DETAILS -> unique list of order-tab names. */
function getOrderTabNames() {
  var cache = CacheService.getScriptCache();
  var cached = cache.get('order_tabs');
  if (cached) { try { return JSON.parse(cached); } catch (e) {} }

  var names = [];
  try {
    var ss = SpreadsheetApp.openById(CONFIG.OPS_SPREADSHEET_ID);
    var sheet = ss.getSheetByName(CONFIG.SHEET_DETAILS_TAB);
    if (sheet) {
      var values = sheet.getDataRange().getValues();
      if (values.length >= 2) {
        var idx = headerIndex(values[0]);
        var iF = idx[norm('Franchise_sheets')];
        var i4 = idx[norm('four_s_sheets')];
        for (var r = 1; r < values.length; r++) {
          [iF, i4].forEach(function (ci) {
            if (ci === undefined) return;
            var v = String(values[r][ci] || '').trim();
            if (v && names.indexOf(v) < 0) names.push(v);
          });
        }
      }
    }
  } catch (e) {
    console.error('getOrderTabNames: ' + e);
  }
  cache.put('order_tabs', JSON.stringify(names), 300); // 5-min cache
  return names;
}

/**
 * Compute committed status for one Godrej SO from MIS_Daily.
 * Returns {found, allReady, totalQty, committedQty, commitDate(Date|null)}.
 */
function getCommitment(soNo) {
  var target = String(soNo || '').trim().toUpperCase();
  var out = { found: false, allReady: false, totalQty: 0, committedQty: 0, commitDate: null };
  if (!target) return out;

  var ss = SpreadsheetApp.openById(CONFIG.OPS_SPREADSHEET_ID);
  var sheet = ss.getSheetByName(CONFIG.MIS_TAB);
  if (!sheet) return out;
  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return out;

  var idx = headerIndex(values[0]);
  var iSO   = idx[norm(CONFIG.MIS_SO)];
  var iQty  = idx[norm(CONFIG.MIS_QTY)];
  var iCom  = idx[norm(CONFIG.MIS_COMMITTED_QTY)];
  var iDate = idx[norm(CONFIG.MIS_COMMIT_DATE)];
  if (iSO === undefined) return out;

  var lines = 0, readyLines = 0, maxDate = null;
  for (var r = 1; r < values.length; r++) {
    var so = String(values[r][iSO] || '').trim().toUpperCase();
    if (so !== target) continue;
    out.found = true;
    lines++;
    var qty = toNum(iQty  !== undefined ? values[r][iQty]  : '');
    var com = toNum(iCom  !== undefined ? values[r][iCom]  : '');
    out.totalQty += isNaN(qty) ? 0 : qty;
    out.committedQty += isNaN(com) ? 0 : com;
    if (!isNaN(qty) && !isNaN(com) && qty === com) readyLines++;
    var d = iDate !== undefined ? parseDate(values[r][iDate]) : null;
    if (d && (!maxDate || d > maxDate)) maxDate = d;
  }
  out.allReady = lines > 0 && readyLines === lines;
  out.commitDate = maxDate;
  return out;
}

/** Build a single order's status message in the chosen language. */
function buildStatusReply(lang, order) {
  var so = order.godrejSO;
  var label = order.orderNo ? order.orderNo : so;
  var c = getCommitment(so);

  if (!c.found) {
    // SO not in the current MIS snapshot -> either already dispatched or not
    // yet appearing. Fall back to the CRM delivery status if we have one.
    if (order.delivery) {
      return fill(t(lang, 'status_crm'), {
        order: label, so: so, status: translateStatus(lang, order.delivery)
      });
    }
    return fill(t(lang, 'status_not_in_mis'), { order: label, so: so });
  }

  if (c.allReady) {
    return fill(t(lang, 'status_committed'), {
      order: label, so: so,
      date: c.commitDate ? fmtDate(c.commitDate) : t(lang, 'soon')
    });
  }

  // Partially / not yet committed -> expected commitment date + days remaining
  var when, days = '';
  if (c.commitDate) {
    when = fmtDate(c.commitDate);
    var d = daysFromToday(c.commitDate);
    if (d > 0) days = fill(t(lang, 'in_days'), { n: d });
    else days = '';
  } else {
    when = t(lang, 'not_available');
  }
  return fill(t(lang, 'status_pending'), {
    order: label, so: so,
    committed: c.committedQty, total: c.totalQty,
    date: when, days: days
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// LANGUAGE TEMPLATES
// ═══════════════════════════════════════════════════════════════════════════

var STR = {
  en: {
    ask_query:  'Welcome to Interio by Godrej (Patia) 🛋️\n\nTo check your order status, please send *any one* of:\n• Registered Contact Number\n• Order Number\n• Customer Name',
    ask_verify: 'For your privacy, please enter the *mobile number registered with this order* to confirm it is you.',
    verify_fail:'That number does not match the mobile number registered with this order. Please enter the correct *registered mobile number*.',
    verify_giveup:'Sorry, I could not verify the registered mobile number for that order. Please contact the showroom, or type *hi* to start again.',
    not_found:  "Sorry, I couldn't find any order matching that. Please check and resend your Registered Contact Number, Order Number, or Name — or type *hi* to restart.",
    no_so:      'Your order was found but the Godrej SO number is not yet recorded. Please contact the showroom.',
    status_committed:  '✅ *Order {order}* (Godrej SO {so})\nYour order is *fully committed* by Godrej as of *{date}*. It will be scheduled for delivery shortly.',
    status_pending:    '🕒 *Order {order}* (Godrej SO {so})\nStatus: *In process* — {committed} of {total} committed so far.\nExpected full commitment date: *{date}*{days}.',
    status_not_in_mis: 'ℹ️ *Order {order}* (Godrej SO {so})\nThis order is not in the latest Godrej MIS update. It may already be committed & dispatched, or not yet loaded. Please contact the showroom for the latest update.',
    status_crm:        'ℹ️ *Order {order}* (Godrej SO {so})\nCurrent delivery status: *{status}*.',
    in_days:    ' (about {n} day(s))',
    soon:       'soon',
    not_available: 'not available yet',
    footer:     'To check another order, send its Order/Contact/Name. Type *hi* to change language.'
  },
  hi: {
    ask_query:  'Interio by Godrej (Patia) में आपका स्वागत है 🛋️\n\nअपने ऑर्डर की स्थिति जानने के लिए, कृपया इनमें से *कोई एक* भेजें:\n• रजिस्टर्ड मोबाइल नंबर\n• ऑर्डर नंबर\n• ग्राहक का नाम',
    ask_verify: 'आपकी गोपनीयता के लिए, कृपया इस ऑर्डर के साथ *रजिस्टर्ड मोबाइल नंबर* दर्ज करें ताकि पुष्टि हो सके कि यह आप ही हैं।',
    verify_fail:'यह नंबर इस ऑर्डर के रजिस्टर्ड मोबाइल नंबर से मेल नहीं खाता। कृपया सही *रजिस्टर्ड मोबाइल नंबर* दर्ज करें।',
    verify_giveup:'क्षमा करें, इस ऑर्डर का रजिस्टर्ड मोबाइल नंबर सत्यापित नहीं हो सका। कृपया शोरूम से संपर्क करें, या फिर से शुरू करने के लिए *hi* लिखें।',
    not_found:  'क्षमा करें, इससे मेल खाता कोई ऑर्डर नहीं मिला। कृपया अपना रजिस्टर्ड मोबाइल नंबर, ऑर्डर नंबर या नाम दोबारा भेजें — या फिर से शुरू करने के लिए *hi* लिखें।',
    no_so:      'आपका ऑर्डर मिल गया, लेकिन Godrej SO नंबर अभी दर्ज नहीं है। कृपया शोरूम से संपर्क करें।',
    status_committed:  '✅ *ऑर्डर {order}* (Godrej SO {so})\nआपका ऑर्डर *{date}* को Godrej द्वारा *पूरी तरह कमिटेड* हो चुका है। जल्द ही डिलीवरी शेड्यूल की जाएगी।',
    status_pending:    '🕒 *ऑर्डर {order}* (Godrej SO {so})\nस्थिति: *प्रक्रिया में* — अब तक {total} में से {committed} कमिटेड।\nपूर्ण कमिटमेंट की अनुमानित तारीख: *{date}*{days}।',
    status_not_in_mis: 'ℹ️ *ऑर्डर {order}* (Godrej SO {so})\nयह ऑर्डर नवीनतम Godrej MIS अपडेट में नहीं है। संभव है यह पहले ही कमिटेड/डिस्पैच हो चुका हो, या अभी लोड न हुआ हो। ताज़ा जानकारी के लिए शोरूम से संपर्क करें।',
    status_crm:        'ℹ️ *ऑर्डर {order}* (Godrej SO {so})\nवर्तमान डिलीवरी स्थिति: *{status}*।',
    in_days:    ' (लगभग {n} दिन)',
    soon:       'जल्द',
    not_available: 'अभी उपलब्ध नहीं',
    footer:     'दूसरा ऑर्डर देखने के लिए उसका ऑर्डर/मोबाइल/नाम भेजें। भाषा बदलने के लिए *hi* लिखें।'
  },
  or: {
    ask_query:  'Interio by Godrej (Patia) କୁ ସ୍ୱାଗତ 🛋️\n\nଆପଣଙ୍କ ଅର୍ଡରର ସ୍ଥିତି ଜାଣିବା ପାଇଁ, ଦୟାକରି ଏଥିମଧ୍ୟରୁ *ଯେକୌଣସି ଗୋଟିଏ* ପଠାନ୍ତୁ:\n• ପଞ୍ଜୀକୃତ ମୋବାଇଲ ନମ୍ବର\n• ଅର୍ଡର ନମ୍ବର\n• ଗ୍ରାହକଙ୍କ ନାମ',
    ask_verify: 'ଆପଣଙ୍କ ଗୋପନୀୟତା ପାଇଁ, ଏହା ଆପଣ ହିଁ ବୋଲି ନିଶ୍ଚିତ କରିବାକୁ ଦୟାକରି ଏହି ଅର୍ଡର ସହ *ପଞ୍ଜୀକୃତ ମୋବାଇଲ ନମ୍ବର* ଦିଅନ୍ତୁ।',
    verify_fail:'ଏହି ନମ୍ବର ଏହି ଅର୍ଡରର ପଞ୍ଜୀକୃତ ମୋବାଇଲ ନମ୍ବର ସହ ମେଳ ଖାଉନାହିଁ। ଦୟାକରି ସଠିକ୍ *ପଞ୍ଜୀକୃତ ମୋବାଇଲ ନମ୍ବର* ଦିଅନ୍ତୁ।',
    verify_giveup:'କ୍ଷମା କରନ୍ତୁ, ଏହି ଅର୍ଡରର ପଞ୍ଜୀକୃତ ମୋବାଇଲ ନମ୍ବର ଯାଞ୍ଚ ହୋଇପାରିଲା ନାହିଁ। ଦୟାକରି ଶୋରୁମ ସହ ଯୋଗାଯୋଗ କରନ୍ତୁ, କିମ୍ବା ପୁନଃ ଆରମ୍ଭ ପାଇଁ *hi* ଲେଖନ୍ତୁ।',
    not_found:  'କ୍ଷମା କରନ୍ତୁ, ସେଥିସହ ମେଳ ଖାଉଥିବା କୌଣସି ଅର୍ଡର ମିଳିଲା ନାହିଁ। ଦୟାକରି ଆପଣଙ୍କ ପଞ୍ଜୀକୃତ ମୋବାଇଲ ନମ୍ବର, ଅର୍ଡର ନମ୍ବର କିମ୍ବା ନାମ ପୁଣି ପଠାନ୍ତୁ — କିମ୍ବା ପୁନଃ ଆରମ୍ଭ ପାଇଁ *hi* ଲେଖନ୍ତୁ।',
    no_so:      'ଆପଣଙ୍କ ଅର୍ଡର ମିଳିଲା, କିନ୍ତୁ Godrej SO ନମ୍ବର ଏବେ ରେକର୍ଡ ହୋଇନାହିଁ। ଦୟାକରି ଶୋରୁମ ସହ ଯୋଗାଯୋଗ କରନ୍ତୁ।',
    status_committed:  '✅ *ଅର୍ଡର {order}* (Godrej SO {so})\nଆପଣଙ୍କ ଅର୍ଡର *{date}* ରେ Godrej ଦ୍ୱାରା *ସମ୍ପୂର୍ଣ୍ଣ କମିଟେଡ୍* ହୋଇଛି। ଶୀଘ୍ର ଡେଲିଭରି ସିଡ୍ୟୁଲ ହେବ।',
    status_pending:    '🕒 *ଅର୍ଡର {order}* (Godrej SO {so})\nସ୍ଥିତି: *ପ୍ରକ୍ରିୟାରେ* — ଏପର୍ଯ୍ୟନ୍ତ {total} ମଧ୍ୟରୁ {committed} କମିଟେଡ୍।\nସମ୍ପୂର୍ଣ୍ଣ କମିଟମେଣ୍ଟର ଆନୁମାନିକ ତାରିଖ: *{date}*{days}।',
    status_not_in_mis: 'ℹ️ *ଅର୍ଡର {order}* (Godrej SO {so})\nଏହି ଅର୍ଡର ସର୍ବଶେଷ Godrej MIS ଅପଡେଟରେ ନାହିଁ। ଏହା ପୂର୍ବରୁ କମିଟେଡ୍/ଡିସ୍ପ୍ୟାଚ ହୋଇଥାଇପାରେ, କିମ୍ବା ଏବେ ଲୋଡ ହୋଇନଥାଇପାରେ। ସର୍ବଶେଷ ସୂଚନା ପାଇଁ ଶୋରୁମ ସହ ଯୋଗାଯୋଗ କରନ୍ତୁ।',
    status_crm:        'ℹ️ *ଅର୍ଡର {order}* (Godrej SO {so})\nବର୍ତ୍ତମାନ ଡେଲିଭରି ସ୍ଥିତି: *{status}*।',
    in_days:    ' (ପ୍ରାୟ {n} ଦିନ)',
    soon:       'ଶୀଘ୍ର',
    not_available: 'ଏବେ ଉପଲବ୍ଧ ନାହିଁ',
    footer:     'ଅନ୍ୟ ଏକ ଅର୍ଡର ଦେଖିବାକୁ ତାହାର ଅର୍ଡର/ମୋବାଇଲ/ନାମ ପଠାନ୍ତୁ। ଭାଷା ବଦଳାଇବାକୁ *hi* ଲେଖନ୍ତୁ।'
  }
};

// Human-readable delivery statuses per language (fallback: original text).
var STATUS_MAP = {
  hi: { 'PENDING': 'लंबित', 'SCHEDULED FOR DELIVERY': 'डिलीवरी के लिए शेड्यूल',
        'DELIVERED': 'डिलीवर हो गया', 'INSTALLATION DONE': 'इंस्टॉलेशन पूर्ण' },
  or: { 'PENDING': 'ବିଚାରାଧୀନ', 'SCHEDULED FOR DELIVERY': 'ଡେଲିଭରି ପାଇଁ ସିଡ୍ୟୁଲ',
        'DELIVERED': 'ଡେଲିଭର ହୋଇଛି', 'INSTALLATION DONE': 'ଇନଷ୍ଟଲେସନ ସମ୍ପୂର୍ଣ୍ଣ' }
};
function translateStatus(lang, status) {
  var key = String(status || '').toUpperCase().replace(/\s+/g, ' ').trim();
  if (lang === 'en') return status;
  var m = STATUS_MAP[lang];
  return (m && m[key]) ? m[key] : status;
}

function t(lang, key) {
  var l = STR[lang] ? lang : 'en';
  return STR[l][key] != null ? STR[l][key] : STR.en[key] || '';
}
function fill(tpl, vars) {
  return String(tpl).replace(/\{(\w+)\}/g, function (_, k) {
    return vars[k] != null ? String(vars[k]) : '';
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION STATE  (CacheService, keyed by WhatsApp number)
// ═══════════════════════════════════════════════════════════════════════════

function getSession(from) {
  var raw = CacheService.getScriptCache().get('sess_' + from);
  if (raw) { try { return JSON.parse(raw); } catch (e) {} }
  return { lang: null, step: null };
}
function saveSession(from, s) {
  CacheService.getScriptCache().put('sess_' + from, JSON.stringify(s), CONFIG.SESSION_TTL);
}

// ═══════════════════════════════════════════════════════════════════════════
// WHATSAPP SEND
// ═══════════════════════════════════════════════════════════════════════════

function sendText(to, text) {
  waSend({
    messaging_product: 'whatsapp',
    to: to,
    type: 'text',
    text: { preview_url: false, body: text }
  });
}

function waSend(payload) {
  var url = 'https://graph.facebook.com/v20.0/' + phoneId() + '/messages';
  var res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + waToken() },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  if (code >= 300) {
    console.error('WhatsApp send failed (' + code + '): ' + res.getContentText());
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// SMALL HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/** Normalize a header for matching: uppercase + collapse internal spaces. */
function norm(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toUpperCase(); }

/** Build {normalizedHeader: colIndex} from a header row. First wins on dupes. */
function headerIndex(headerRow) {
  var idx = {};
  for (var i = 0; i < headerRow.length; i++) {
    var k = norm(headerRow[i]);
    if (k && idx[k] === undefined) idx[k] = i;
  }
  return idx;
}

function toNum(v) {
  if (v === null || v === undefined) return NaN;
  if (typeof v === 'number') return v;
  return parseFloat(String(v).replace(/[, ]/g, ''));
}

/** Last 10 digits of a phone value (drops +91 / spaces / leading 0). */
function digits10(v) {
  var d = String(v == null ? '' : v).replace(/\D/g, '');
  return d.length > 10 ? d.slice(-10) : d;
}

/** Parse a Google Sheets Date object or a d-m-y / d-b-y string. Returns Date|null. */
function parseDate(v) {
  if (v instanceof Date && !isNaN(v.getTime())) return v;
  var s = String(v == null ? '' : v).trim();
  if (!s) return null;
  var months = { jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11 };
  var m;
  // d-m-y or d/m/y
  m = s.match(/^(\d{1,2})[-\/](\d{1,2})[-\/](\d{2,4})/);
  if (m) {
    var yr = m[3].length === 2 ? 2000 + parseInt(m[3], 10) : parseInt(m[3], 10);
    return new Date(yr, parseInt(m[2], 10) - 1, parseInt(m[1], 10));
  }
  // d-Mon-y
  m = s.match(/^(\d{1,2})[-\/ ]([A-Za-z]{3})[A-Za-z]*[-\/ ](\d{2,4})/);
  if (m) {
    var mon = months[m[2].toLowerCase()];
    var yr2 = m[3].length === 2 ? 2000 + parseInt(m[3], 10) : parseInt(m[3], 10);
    if (mon !== undefined) return new Date(yr2, mon, parseInt(m[1], 10));
  }
  // y-m-d
  m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return new Date(parseInt(m[1],10), parseInt(m[2],10)-1, parseInt(m[3],10));
  var d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function fmtDate(d) {
  var tz = Session.getScriptTimeZone() || 'Asia/Kolkata';
  return Utilities.formatDate(d, tz, 'dd MMM yyyy');
}

function daysFromToday(d) {
  var today = new Date();
  today.setHours(0, 0, 0, 0);
  var target = new Date(d.getTime());
  target.setHours(0, 0, 0, 0);
  return Math.round((target - today) / (1000 * 60 * 60 * 24));
}

// ═══════════════════════════════════════════════════════════════════════════
// TEST HELPERS  (run manually from the Apps Script editor)
// ═══════════════════════════════════════════════════════════════════════════

/** Try a lookup without WhatsApp — check the Execution Log for output. */
function testLookup() {
  var q = 'REPLACE_WITH_AN_ORDER_NO_OR_NAME_OR_NUMBER';
  var orders = searchOrders(q);
  console.log('Matches: ' + JSON.stringify(orders, null, 2));
  orders.slice(0, 3).forEach(function (o) {
    console.log('EN => ' + buildStatusReply('en', o));
  });
}

/** Verify both spreadsheets + key tabs are reachable. */
function testConfig() {
  console.log('Order tabs from SHEET_DETAILS: ' + JSON.stringify(getOrderTabNames()));
  var mis = SpreadsheetApp.openById(CONFIG.OPS_SPREADSHEET_ID).getSheetByName(CONFIG.MIS_TAB);
  console.log('MIS tab found: ' + (mis ? 'yes, ' + mis.getLastRow() + ' rows' : 'NO'));
}
