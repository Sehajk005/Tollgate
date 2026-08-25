-- Source: TRD v2 §6.3 -- one atomic call, executed once per score call:
--   1. idempotency SET NX
--   2. ZADD this attempt into every relevant window
--   3. trim every touched window against ingest_ms
--   4. read back the full raw window vector
--   5. increment event_id-reuse and the 24h card counter
--   6. increment the current CUSUM bucket counter
--   7. return everything to Python
--
-- Day-3 Plan Step 3. Pure script: no TIME, no RANDOMKEY, no wall-clock
-- read of any kind -- every timestamp arrives via ARGV from the injected
-- Clock, which is what keeps replay speed=0 and speed=60 producing
-- byte-identical decisions (TRD §4, Impl Plan §1.4 M6).
--
-- KEYS layout (fixed prefix, then one key per window):
--   KEYS[1] = idem key            (tg:{m}:idem:{digest})
--   KEYS[2] = eidr key            (tg:{m}:eidr:{event_id})
--   KEYS[3] = card24 key          (tg:{m}:card24:{card_hash})
--   KEYS[4] = cusum key           (tg:{m}:cusum) -- a Hash
--   KEYS[5 .. 5+N-1] = one sorted-set key per window, in request order
--
-- ARGV layout:
--   ARGV[1] = ingest_ms
--   ARGV[2] = attempt_uid
--   ARGV[3] = idem_ttl_ms
--   ARGV[4] = payload_digest
--   ARGV[5] = card24_ttl_ms
--   ARGV[6] = cusum_bucket_s
--   ARGV[7] = window_ttl_slack_ms
--   ARGV[8] = N (number of windows)
--   then, for each of the N windows, four ARGV values in order:
--     member, window_ms, read_mode ("count"|"members")
--   (3 ARGV per window, starting at ARGV[9])
--
-- Return (flat array, positions fixed):
--   [1] idempotent_replay   (0 or 1)
--   [2] stored_attempt_uid  (string, "" if not a replay)
--   [3] event_id_reuse_count
--   [4] card_seen_24h
--   [5] cusum_bucket_index
--   [6] cusum_bucket_count
--   [7 .. 7+N-1] one sub-array per window: {count, member1, member2, ...}
--     (member list is empty when read_mode == "count")

local idem_key = KEYS[1]
local eidr_key = KEYS[2]
local card24_key = KEYS[3]
local cusum_key = KEYS[4]

local ingest_ms = tonumber(ARGV[1])
local attempt_uid = ARGV[2]
local idem_ttl_ms = tonumber(ARGV[3])
local payload_digest = ARGV[4]
local card24_ttl_ms = tonumber(ARGV[5])
local cusum_bucket_s = tonumber(ARGV[6])
local window_ttl_slack_ms = tonumber(ARGV[7])
local n_windows = tonumber(ARGV[8])

-- Step 1: idempotency. SET NX PX; if it already exists, this is a replay
-- -- return immediately, touching nothing else (M7: windows unchanged).
local set_ok = redis.call("SET", idem_key, attempt_uid, "NX", "PX", idem_ttl_ms)
if not set_ok then
    local stored = redis.call("GET", idem_key)
    local reply = { 1, stored, 0, 0, 0, 0 }
    for i = 1, n_windows do
        table.insert(reply, { 0 })
    end
    return reply
end

-- Steps 2-4: every window, in order.
local window_results = {}
for i = 0, n_windows - 1 do
    local key = KEYS[5 + i]
    local base = 9 + (i * 3)
    local member = ARGV[base]
    local window_ms = tonumber(ARGV[base + 1])
    local read_mode = ARGV[base + 2]

    redis.call("ZADD", key, ingest_ms, member)
    local floor = ingest_ms - window_ms
    redis.call("ZREMRANGEBYSCORE", key, "-inf", floor)
    redis.call("PEXPIRE", key, window_ms + window_ttl_slack_ms)

    if read_mode == "members" then
        local members = redis.call("ZRANGE", key, 0, -1)
        local sub = { #members }
        for _, m in ipairs(members) do
            table.insert(sub, m)
        end
        table.insert(window_results, sub)
    else
        local count = redis.call("ZCARD", key)
        table.insert(window_results, { count })
    end
end

-- Step 5a: event_id reuse -- distinct payload digests seen per event_id.
redis.call("SADD", eidr_key, payload_digest)
local event_id_reuse_count = redis.call("SCARD", eidr_key)

-- Step 5b: the 24h card counter -- INCR + TTL, the only 24h datum.
local card_seen_24h = redis.call("INCR", card24_key)
if card_seen_24h == 1 then
    redis.call("PEXPIRE", card24_key, card24_ttl_ms)
end

-- Step 6: CUSUM bucket counter. Bucket rolls over on a new
-- floor(ingest_ms / bucket_ms); the raw per-bucket attempt count is
-- built here -- gating on p_calibrated >= tau_flag (TRD §6.5) is a Day-6
-- concern, deferred per Day-3 Plan §2 D3.
local bucket_ms = cusum_bucket_s * 1000
local bucket_index = math.floor(ingest_ms / bucket_ms)
local last_bucket = redis.call("HGET", cusum_key, "last_bucket")
local bucket_count
if last_bucket == false or tonumber(last_bucket) ~= bucket_index then
    bucket_count = 1
    redis.call("HSET", cusum_key, "last_bucket", bucket_index, "bucket_count", bucket_count)
else
    bucket_count = redis.call("HINCRBY", cusum_key, "bucket_count", 1)
end

-- Step 7: return everything in one round trip.
local reply = { 0, "", event_id_reuse_count, card_seen_24h, bucket_index, bucket_count }
for _, sub in ipairs(window_results) do
    table.insert(reply, sub)
end
return reply
