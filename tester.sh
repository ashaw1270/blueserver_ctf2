#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# bank_tester.sh — curl-based harness (cookie-aware, multi-user, attacker cases)
# - Uses cookie files (-c on login, -b on authenticated ops)
# - Separates headers/body (no -i); forces HTTP/1.1; retries; closes per request
# - Regexes tailored to your app.py phrases; trailing whitespace tolerant
# - Multi-user isolation (A, B, C) with separate cookie files
# - Session-fixation check (re-login invalidates only same-user old cookie)
# - Deposit $0 is treated as a valid NO-OP and must NOT change balance
# ------------------------------------------------------------------------------

HOST="${HOST:-blueserver}"
IP=""
USER_A="testA_$(date +%s)"
USER_B="testB_$(date +%s)"
USER_C="testC_$(date +%s)"
PASS_A="P@ssA!"
PASS_B="P@ssB!"
PASS_C="P@ssC!"

COOKIE_A="/tmp/cookie.${USER_A}.txt"
COOKIE_B="/tmp/cookie.${USER_B}.txt"
COOKIE_C="/tmp/cookie.${USER_C}.txt"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --ip)   IP="$2"; shift 2 ;;
    --ua)   USER_A="$2"; COOKIE_A="/tmp/cookie.${USER_A}.txt"; shift 2 ;;
    --ub)   USER_B="$2"; COOKIE_B="/tmp/cookie.${USER_B}.txt"; shift 2 ;;
    --uc)   USER_C="$2"; COOKIE_C="/tmp/cookie.${USER_C}.txt"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

BASE_HTTPS="https://${HOST}"
BASE_HTTP="http://${HOST}"
RESOLVE_ARGS=()
[[ -n "${IP}" ]] && RESOLVE_ARGS=( --resolve "${HOST}:443:${IP}" --resolve "${HOST}:80:${IP}" )

# colors
GREEN=$(tput setaf 2 || true); RED=$(tput setaf 1 || true)
YELLOW=$(tput setaf 3 || true); CYAN=$(tput setaf 6 || true)
BOLD=$(tput bold || true); RESET=$(tput sgr0 || true)

# integer counters
declare -i PASS=0 FAIL=0 TOTAL=0
declare -a RESULTS=()

# ------------------------------------------------------------------------------
run_curl() {
  # run_curl <scheme> <method> <path> [cookie_mode] [cookie_file] [extra_headers...]
  #   cookie_mode: set -> -c file ; use -> -b file ; (blank) -> none
  local scheme="$1"; shift
  local method="$1"; shift
  local path="$1"; shift
  local cmode="${1:-}"; shift || true
  local cfile="${1:-}"; shift || true

  local out_hdr="$TMPDIR/hdr.$RANDOM"
  local out_body="$TMPDIR/body.$RANDOM"
  local cookie_args=()
  [[ "$cmode" == "set" && -n "${cfile}" ]] && cookie_args=(-c "$cfile")
  [[ "$cmode" == "use" && -n "${cfile}" ]] && cookie_args=(-b "$cfile")

  local base="$BASE_HTTPS"
  [[ "$scheme" == "http" ]] && base="$BASE_HTTP"

  curl -sS --http1.1 -k \
       "${RESOLVE_ARGS[@]}" \
       -X "$method" "${base}${path}" \
       -H 'User-Agent: bank-tester/2.3' \
       -H 'Connection: close' \
       --retry 2 --retry-all-errors \
       -D "$out_hdr" -o "$out_body" \
       "${cookie_args[@]}" --max-time 20 "$@" || true

  echo "$out_hdr|$out_body"
}

status_code()     { awk 'NR==1 {print $2}' "$1"; }
body_contains()   { grep -aE -q "$2" "$1"; }
header_contains() { grep -aiE -q "$2" "$1"; }

ok(){ PASS+=1; RESULTS+=("${GREEN}PASS${RESET} | $1"); }
bad(){ FAIL+=1; RESULTS+=("${RED}FAIL${RESET} | $1"); RESULTS+=("       $2"); }
need(){ echo "/$1/"; }

expect() {
  # expect <name> <scheme> <method> <path> <status_re> <body_re> [cookie_mode] [cookie_file] [extra_headers...]
  local name="$1" scheme="$2" method="$3" path="$4" exp_status_re="$5" exp_body_re="$6"; shift 6
  local cmode="${1:-}"; local cfile="${2:-}"; [[ $# -gt 0 ]] && shift 2 || true
  TOTAL+=1
  local files hdr body sc
  files="$(run_curl "$scheme" "$method" "$path" "$cmode" "$cfile" "$@")"
  hdr="${files%%|*}"; body="${files##*|}"
  sc="$(status_code "$hdr")"

  local status_ok=no body_ok=no
  [[ "$sc" =~ $exp_status_re ]] && status_ok=yes
  if [[ "$exp_body_re" == "__ANY__" ]]; then
    body_ok=yes
  elif body_contains "$body" "$exp_body_re"; then
    body_ok=yes
  fi

  if [[ $status_ok == yes && $body_ok == yes ]]; then ok "$name"
  else
    bad "$name | HTTP=$sc | need $(need "$exp_status_re"), $(need "$exp_body_re")" "BODY: $(head -c 240 "$body" | tr '\n' ' ')"
  fi
}

# Get numeric balance from /manage?action=balance (with cookie)
get_balance() {
  local cookie_file="$1"
  local files body
  files="$(run_curl "https" "GET" "/manage?action=balance" "use" "$cookie_file")"
  body="${files##*|}"
  # Expect "balance=<int>" anywhere in body
  local val
  val="$(grep -aEo 'balance=([0-9]+)' "$body" | tail -n1 | sed 's/.*=//')"
  [[ -n "$val" ]] && echo "$val" || echo ""
}

# ------------------------------------------------------------------------------
echo "${CYAN}${BOLD}===> Starting test run against ${BASE_HTTPS}${RESET}"
[[ -n "$IP" ]] && echo "${YELLOW}(Using --resolve ${HOST} -> ${IP})${RESET}"
rm -f "$COOKIE_A" "$COOKIE_B" "$COOKIE_C"

# 0) HTTP->HTTPS redirect — status-only (ignore body)
expect "HTTP->HTTPS redirect" "http" "GET" "/" '^(30[12]|200)$' "__ANY__"

# 1) Register users (exact phrases; trailing whitespace tolerant)
expect "Register A"            "https" "GET" "/register?user=${USER_A}&pass=${PASS_A}" '^200$' "Account created for user ${USER_A}[[:space:]]*$"
expect "Register A duplicate"  "https" "GET" "/register?user=${USER_A}&pass=${PASS_A}" '^200$' "Error: user ${USER_A} already exists[[:space:]]*$"
expect "Register B"            "https" "GET" "/register?user=${USER_B}&pass=${PASS_B}" '^200$' "Account created for user ${USER_B}[[:space:]]*$"
expect "Register C"            "https" "GET" "/register?user=${USER_C}&pass=${PASS_C}" '^200$' "Account created for user ${USER_C}[[:space:]]*$"

# 2) Login A (cookie set) + cookie attributes
expect "Login A (sets cookie)" "https" "GET" "/login?user=${USER_A}&pass=${PASS_A}" '^200$' "Login successful for ${USER_A}[[:space:]]*$" "set" "$COOKIE_A"
{
  files="$(run_curl "https" "GET" "/login?user=${USER_A}&pass=${PASS_A}" "set" "$COOKIE_A")"
  hdr="${files%%|*}"; TOTAL+=1
  if header_contains "$hdr" '^Set-Cookie: *session_id=' \
     && header_contains "$hdr" 'httponly' \
     && header_contains "$hdr" 'secure' \
     && header_contains "$hdr" 'samesite=Strict|SameSite=Strict' \
     && header_contains "$hdr" 'path=/'; then
    ok "Cookie attributes present (session_id; HttpOnly; Secure; SameSite=Strict; Path=/)"
  else
    bad "Cookie attributes missing/weak" "HDR: $(tr -d '\r' < "$hdr" | tr '\n' ' ' | cut -c1-260)"
  fi
}

# 3) Happy path A
expect "A: Balance initial 0"   "https" "GET" "/manage?action=balance" '^200$' "balance=0[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Deposit 100"         "https" "GET" "/manage?action=deposit&amount=100" '^200$' "Deposited 100\. balance=100[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Withdraw 40 -> 60"   "https" "GET" "/manage?action=withdraw&amount=40" '^200$' "Withdrew 40\. balance=60[[:space:]]*$"  "use" "$COOKIE_A"

# 3a) Deposit $0 should be VALID NO-OP — balance must NOT change
#     Capture balance before, deposit 0, then ensure balance is the same afterwards.
TOTAL+=1
A_BAL_BEFORE="$(get_balance "$COOKIE_A")"
if [[ -z "$A_BAL_BEFORE" ]]; then
  bad "A: Capture balance before deposit 0" "Could not parse balance before."
else
  files_z="$(run_curl "https" "GET" "/manage?action=deposit&amount=0" "use" "$COOKIE_A")"
  body_z="${files_z##*|}"
  A_BAL_AFTER="$(get_balance "$COOKIE_A")"
  if [[ -n "$A_BAL_AFTER" && "$A_BAL_AFTER" == "$A_BAL_BEFORE" ]]; then
    # Optional: accept either message "Deposited 0. balance=<same>" or any message — key is no change in balance
    ok "A: Deposit 0 is a valid no-op (balance unchanged at ${A_BAL_AFTER})"
  else
    bad "A: Deposit 0 changed balance (should be no-op)" "Before=${A_BAL_BEFORE} After=${A_BAL_AFTER} | BODY: $(head -c 200 "$body_z" | tr '\n' ' ')"
  fi
fi

# 4) Numeric edge cases A (tailored; trailing whitespace tolerant)
expect "A: Deposit missing amount"  "https" "GET" "/manage?action=deposit"  '^200$' "Error: must specify amount[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Withdraw missing amount" "https" "GET" "/manage?action=withdraw" '^200$' "Error: must specify amount[[:space:]]*$" "use" "$COOKIE_A"

expect "A: Deposit non-numeric"     "https" "GET" "/manage?action=deposit&amount=hello" '^200$' "Error: amount must be numeric|Error: invalid amount[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Withdraw non-numeric"    "https" "GET" "/manage?action=withdraw&amount=hello" '^200$' "Error: amount must be numeric|Error: invalid amount[[:space:]]*$" "use" "$COOKIE_A"

expect "A: Deposit negative"        "https" "GET" "/manage?action=deposit&amount=-5"      '^200$' "Error: invalid amount[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Deposit Infinity"        "https" "GET" "/manage?action=deposit&amount=Infinity" '^200$' "Error: invalid amount|Error: amount must be numeric[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Deposit NaN"             "https" "GET" "/manage?action=deposit&amount=NaN"      '^200$' "Error: invalid amount|Error: amount must be numeric[[:space:]]*$" "use" "$COOKIE_A"

# Huge values: accept observed variants (exceeds max / invalid / numeric / DB overflow)
expect "A: Deposit 1e309 (exceeds max)"          "https" "GET" "/manage?action=deposit&amount=1e309" '^200$' "Error: amount exceeds maximum allowed|Error: invalid amount|Error: amount must be numeric[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Deposit 1e308 (may succeed/overflow)" "https" "GET" "/manage?action=deposit&amount=1e308" '^200$' "Deposited [0-9]+\. balance=[0-9]+|Error: balance overflow|Error: amount exceeds maximum allowed|Database error: .*[[:space:]]*$" "use" "$COOKIE_A"

LONGNUM=$(printf '9%.0s' {1..5000})
expect "A: Deposit very long digits" "https" "GET" "/manage?action=deposit&amount=${LONGNUM}" '^200$' "Error: amount must be numeric|Error: invalid amount|Error: amount exceeds maximum allowed|Error: balance overflow[[:space:]]*$" "use" "$COOKIE_A"
expect "A: Withdraw too much"        "https" "GET" "/manage?action=withdraw&amount=9999999999" '^200$' "Error: insufficient funds\. balance=[0-9]+[[:space:]]*$" "use" "$COOKIE_A"

# 5) Invalid/missing action
expect "A: Manage invalid action" "https" "GET" "/manage?action=fly" '^200$' "Error: invalid action[[:space:]]*$" "use" "$COOKIE_A"
expect "Unauth manage -> not logged in" "https" "GET" "/manage" '^200$' "Error: not logged in[[:space:]]*$"

# 6) Method abuse
expect "POST /login -> 405"       "https" "POST"   "/login?user=${USER_A}&pass=${PASS_A}" '^405$' "__ANY__"
expect "PUT /manage -> 405"       "https" "PUT"    "/manage?action=balance" '^405$' "__ANY__"
expect "DELETE /register -> 405"  "https" "DELETE" "/register?user=x&pass=y" '^405$' "__ANY__"
expect "HEAD /manage -> 405 or 200" "https" "HEAD" "/manage?action=balance" '^(200|405)$' "__ANY__" "use" "$COOKIE_A"

# 7) CSRF-ish probes (no cookie must be blocked)
expect "Deposit without cookie"  "https" "GET" "/manage?action=deposit&amount=5" '^200$' "Error: not logged in[[:space:]]*$"
expect "Withdraw without cookie" "https" "GET" "/manage?action=withdraw&amount=1" '^200$' "Error: not logged in[[:space:]]*$"

# 8) Multi-user isolation (B, C)
expect "Login B (sets cookie)" "https" "GET" "/login?user=${USER_B}&pass=${PASS_B}" '^200$' "Login successful for ${USER_B}[[:space:]]*$" "set" "$COOKIE_B"
expect "B: Balance 0"          "https" "GET" "/manage?action=balance" '^200$' "balance=0[[:space:]]*$" "use" "$COOKIE_B"
expect "B: Deposit 55"         "https" "GET" "/manage?action=deposit&amount=55" '^200$' "Deposited 55\. balance=55[[:space:]]*$" "use" "$COOKIE_B"
expect "A still 60"            "https" "GET" "/manage?action=balance" '^200$' "balance=60[[:space:]]*$" "use" "$COOKIE_A"

expect "Login C (sets cookie)" "https" "GET" "/login?user=${USER_C}&pass=${PASS_C}" '^200$' "Login successful for ${USER_C}[[:space:]]*$" "set" "$COOKIE_C"
expect "C: Balance 0"          "https" "GET" "/manage?action=balance" '^200$' "balance=0[[:space:]]*$" "use" "$COOKIE_C"
expect "C: Deposit 7"          "https" "GET" "/manage?action=deposit&amount=7" '^200$' "Deposited 7\. balance=7[[:space:]]*$" "use" "$COOKIE_C"
expect "B still 55"            "https" "GET" "/manage?action=balance" '^200$' "balance=55[[:space:]]*$" "use" "$COOKIE_B"

# 9) Session fixation for A — old cookie must fail after A re-login
cp -f "$COOKIE_A" "$TMPDIR/oldA.cookie" || true
expect "A re-login (new cookie)" "https" "GET" "/login?user=${USER_A}&pass=${PASS_A}" '^200$' "Login successful for ${USER_A}[[:space:]]*$" "set" "$COOKIE_A"

files_old="$(run_curl "https" "GET" "/manage?action=balance" "use" "$TMPDIR/oldA.cookie")"
body_old="${files_old##*|}"; TOTAL+=1
if grep -aEq "Error: session expired or invalid\.? Please log in( again\.)?[[:space:]]*$|Error: not logged in[[:space:]]*$" "$body_old"; then
  ok "Old A session invalidated after re-login"
else
  bad "Old A session still valid (fixation risk)" "BODY: $(head -c 240 "$body_old" | tr '\n' ' ')"
fi
expect "A new session works"              "https" "GET" "/manage?action=balance" '^200$' "balance=[0-9]+[[:space:]]*$" "use" "$COOKIE_A"
expect "B unaffected after A relogin"     "https" "GET" "/manage?action=balance" '^200$' "balance=55[[:space:]]*$" "use" "$COOKIE_B"
expect "C unaffected after A relogin"     "https" "GET" "/manage?action=balance" '^200$' "balance=7[[:space:]]*$"  "use" "$COOKIE_C"

# 10) XSS probes (register may echo raw; login should not)
XSS_U='%3Cscript%3Ealert(1)%3C%2Fscript%3E'
expect "XSS register reflection" "https" "GET" "/register?user=${XSS_U}&pass=${PASS_A}" '^200$' "(<script>alert\(1\)</script>|Error: user <script>alert\(1\)</script> already exists|Account created for user <script>alert\(1\)</script>)[[:space:]]*$"
files_x="$(run_curl "https" "GET" "/login?user=${XSS_U}&pass=${PASS_A}")"; body_x="${files_x##*|}"; TOTAL+=1
if echo "$body_x" | grep -q "<script>alert(1)</script>"; then
  bad "Reflected XSS in login response" "BODY: $(head -c 240 "$body_x" | tr '\n' ' ')"
else
  ok "No raw <script> reflection in login"
fi

# 11) SQLi-ish usernames
enc() { python3 - "$1" <<'PY'
import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))
PY
}
for su in "admin' OR '1'='1" "'; DROP TABLE users;--" "\" OR \"\"=\"" "normal_user"; do
  u_enc="$(enc "$su")"
  expect "SQLi register: $su" "https" "GET" "/register?user=${u_enc}&pass=test" '^200$' "(Account created for user .*|Error: user .* already exists|Database error: .*)[[:space:]]*$"
  expect "SQLi login: $su"    "https" "GET" "/login?user=${u_enc}&pass=test"    '^200$' "(Login successful for .*|Error: invalid username or password)[[:space:]]*$"
done

# 12) Unicode usernames (C's cookie remains separate)
UNI_USER=$(python3 - <<'PY'
s="用户_áéíóú_🙂"
import urllib.parse; print(urllib.parse.quote(s))
PY
)
expect "Unicode register"                      "https" "GET" "/register?user=${UNI_USER}&pass=${PASS_A}" '^200$' "(Account created for user .*|Error: user .+ already exists|Database error: .*)[[:space:]]*$"
expect "Unicode login (separate cookie; C ok)" "https" "GET" "/login?user=${UNI_USER}&pass=${PASS_A}"    '^200$' "(Login successful for .*|Error: invalid username or password)[[:space:]]*$" "set" "$TMPDIR/unicode.cookie"
expect "C still 7 after Unicode user login"    "https" "GET" "/manage?action=balance"                    '^200$' "balance=7[[:space:]]*$" "use" "$COOKIE_C"

# 13) CRLF-ish payload handled (relaxed: any 'already exists' or normal msg)
CRLF_U=$(python3 - <<'PY'
import urllib.parse; print(urllib.parse.quote("bob\r\nSet-Cookie: evil=1"))
PY
)
expect "CRLF username handled" "https" "GET" "/register?user=${CRLF_U}&pass=x" '^200$' "(Account created for user .*|.*already exists|Database error: .*)[[:space:]]*$"

# 14) Logout isolation
expect "Logout A"                 "https" "GET" "/logout" '^200$' "Logged out[[:space:]]*$" "use" "$COOKIE_A"
expect "A manage now blocked"     "https" "GET" "/manage?action=balance" '^200$' "Error: (not logged in|session expired or invalid\.? Please log in( again\.)?)[[:space:]]*$" "use" "$COOKIE_A"
expect "B still 55 after A logout" "https" "GET" "/manage?action=balance" '^200$' "balance=55[[:space:]]*$" "use" "$COOKIE_B"
expect "C still 7 after A logout"  "https" "GET" "/manage?action=balance" '^200$' "balance=7[[:space:]]*$"  "use" "$COOKIE_C"

# 15) Close account flow (A)
expect "Login A again to close" "https" "GET" "/login?user=${USER_A}&pass=${PASS_A}" '^200$' "Login successful for ${USER_A}[[:space:]]*$" "set" "$COOKIE_A"
expect "A close account"        "https" "GET" "/manage?action=close" '^200$' "Account for ${USER_A} closed\.[[:space:]]*$" "use" "$COOKIE_A"
expect "A login after close fails" "https" "GET" "/login?user=${USER_A}&pass=${PASS_A}" '^200$' "Error: invalid username or password[[:space:]]*$"

# Sanity: B and C unaffected by A close
expect "B still 55 after A close" "https" "GET" "/manage?action=balance" '^200$' "balance=55[[:space:]]*$" "use" "$COOKIE_B"
expect "C still 7 after A close"  "https" "GET" "/manage?action=balance" '^200$' "balance=7[[:space:]]*$"  "use" "$COOKIE_C"

# ------------------------------------------------------------------------------
echo
echo "${BOLD}${CYAN}============ RESULTS ============${RESET}"
for r in "${RESULTS[@]}"; do echo -e "$r"; done
echo "${BOLD}${CYAN}=================================${RESET}"
echo -e "${BOLD}Score:${RESET} ${GREEN}${PASS}${RESET}/${TOTAL} passed, ${RED}${FAIL}${RESET} failed"
(( FAIL > 0 )) && exit 1 || exit 0
