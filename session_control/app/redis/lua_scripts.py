ASSIGN_RELAY_AND_WORKER_TO_SESSION_LUA = """
local available_relays_key = KEYS[1]
local warm_workers_key = KEYS[2]

local session_id = ARGV[1]

local relay_ids = redis.call("SMEMBERS", available_relays_key)
local selected_relay_id = nil
local selected_relay = nil
local selected_relay_sessions = nil

local function rollback_relay(relay_id)
    local rollback_relay_key = "relay:" .. relay_id
    local rollback_relay_raw = redis.call("GET", rollback_relay_key)
    if rollback_relay_raw then
        local rollback_relay = cjson.decode(rollback_relay_raw)
        local rollback_sessions = tonumber(rollback_relay["current_sessions"]) or 0
        if rollback_sessions > 0 then
            rollback_relay["current_sessions"] = rollback_sessions - 1
        end
        rollback_relay["status"] = "warm"
        redis.call("SET", rollback_relay_key, cjson.encode(rollback_relay), "KEEPTTL")
        redis.call("SADD", available_relays_key, relay_id)
    end
end

for _, relay_id in ipairs(relay_ids) do
    local relay_key = "relay:" .. relay_id
    local relay_raw = redis.call("GET", relay_key)

    if relay_raw then
        local relay = cjson.decode(relay_raw)
        local current_sessions = tonumber(relay["current_sessions"]) or 0
        local max_sessions = tonumber(relay["max_sessions"]) or 0

        if relay["status"] == "warm" and current_sessions < max_sessions then
            if selected_relay_sessions == nil or current_sessions < selected_relay_sessions then
                selected_relay_id = relay_id
                selected_relay = relay
                selected_relay_sessions = current_sessions
            end
        end
    else
        redis.call("SREM", available_relays_key, relay_id)
    end
end

if not selected_relay_id then
    return {err = "NO_WARM_RELAY"}
end

selected_relay["current_sessions"] = selected_relay_sessions + 1

if selected_relay["current_sessions"] >= (tonumber(selected_relay["max_sessions"]) or 0) then
    selected_relay["status"] = "full"
    redis.call("SREM", available_relays_key, selected_relay_id)
else
    selected_relay["status"] = "warm"
    redis.call("SADD", available_relays_key, selected_relay_id)
end

redis.call("SET", "relay:" .. selected_relay_id, cjson.encode(selected_relay), "KEEPTTL")

local worker_id = nil
local worker = nil

while true do
    local candidate_worker_id = redis.call("SPOP", warm_workers_key)
    if not candidate_worker_id then
        rollback_relay(selected_relay_id)
        return {err = "NO_WARM_WORKER"}
    end

    local candidate_worker_key = "worker:" .. candidate_worker_id
    local candidate_worker_raw = redis.call("GET", candidate_worker_key)

    if candidate_worker_raw then
        local candidate_worker = cjson.decode(candidate_worker_raw)

        if candidate_worker["status"] == "warm" then
            worker_id = candidate_worker_id
            worker = candidate_worker
            break
        end
    end
end

local worker_key = "worker:" .. worker_id
worker["status"] = "reserved"
worker["assigned_session_id"] = session_id

redis.call("SET", worker_key, cjson.encode(worker), "KEEPTTL")

return {
    selected_relay_id,
    selected_relay["internal_endpoint"],
    worker_id
}
"""


RELEASE_RELAY_AND_WORKER_LUA = """
local available_relays_key = KEYS[1]
local warm_workers_key = KEYS[2]

local relay_id = ARGV[1]
local worker_id = ARGV[2]
local session_id = ARGV[3]

if relay_id and relay_id ~= "" then
    local relay_key = "relay:" .. relay_id
    local relay_raw = redis.call("GET", relay_key)
    if relay_raw then
        local relay = cjson.decode(relay_raw)
        local current_sessions = tonumber(relay["current_sessions"]) or 0
        if current_sessions > 0 then
            relay["current_sessions"] = current_sessions - 1
        end

        local max_sessions = tonumber(relay["max_sessions"]) or 0
        if relay["current_sessions"] < max_sessions and relay["status"] ~= "dead" then
            relay["status"] = "warm"
            redis.call("SADD", available_relays_key, relay_id)
        end

        redis.call("SET", relay_key, cjson.encode(relay), "KEEPTTL")
    end
end

if worker_id and worker_id ~= "" then
    local worker_key = "worker:" .. worker_id
    local worker_raw = redis.call("GET", worker_key)
    if worker_raw then
        local worker = cjson.decode(worker_raw)
        if worker["assigned_session_id"] == session_id then
            worker["status"] = "warm"
            worker["assigned_session_id"] = cjson.null
            redis.call("SET", worker_key, cjson.encode(worker), "KEEPTTL")
            redis.call("SADD", warm_workers_key, worker_id)
        end
    end
end

return "OK"
"""
