ASSIGN_WORKER_TO_SESSION_LUA = """
local warm_set_key = KEYS[1]

local session_id = ARGV[1]
local worker_ttl = tonumber(ARGV[2])

local worker_id = redis.call("SPOP", warm_set_key)
if not worker_id then
    return {err = "NO_WARM_WORKER"}
end

local worker_key = "worker:" .. worker_id
local worker_raw = redis.call("GET", worker_key)

if not worker_raw then
    return {err = "WORKER_NOT_FOUND:" .. worker_id}
end

local worker = cjson.decode(worker_raw)

if worker["status"] ~= "warm" then
    return {err = "WORKER_NOT_WARM:" .. worker_id}
end

worker["status"] = "reserved"
worker["assigned_session_id"] = session_id

local updated_worker_payload = cjson.encode(worker)
redis.call("SET", worker_key, updated_worker_payload, "KEEPTTL")

return {worker_id, updated_worker_payload}
"""