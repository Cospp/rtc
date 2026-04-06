package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

const (
	defaultPort               = "8080"
	defaultRelayID            = "relay-dev"
	defaultPublicEndpoint     = ""
	defaultInternalAddress    = "relay:8080"
	defaultMaxSessions        = 50
	defaultRedisURL           = "redis://redis:6379/0"
	defaultRelayTTLSeconds    = 15
	defaultHeartbeatSecs      = 5
	defaultSessionTTLSecs     = 15
	defaultSessionRefreshSecs = 5
)

type Config struct {
	Port                          string
	RelayID                       string
	PublicEndpoint                string
	InternalEndpoint              string
	MaxSessions                   int
	RedisURL                      string
	RelayTTLSeconds               int
	HeartbeatSeconds              int
	SessionTTLSeconds             int
	SessionRefreshIntervalSeconds int
}

func Load() (Config, error) {
	maxSessionsRaw := getEnv("RELAY_MAX_SESSIONS", strconv.Itoa(defaultMaxSessions))
	maxSessions, err := strconv.Atoi(maxSessionsRaw)
	if err != nil || maxSessions <= 0 {
		return Config{}, fmt.Errorf("invalid RELAY_MAX_SESSIONS value: %q", maxSessionsRaw)
	}

	relayTTLRaw := getEnv("RELAY_TTL_SECONDS", strconv.Itoa(defaultRelayTTLSeconds))
	relayTTLSeconds, err := strconv.Atoi(relayTTLRaw)
	if err != nil || relayTTLSeconds <= 0 {
		return Config{}, fmt.Errorf("invalid RELAY_TTL_SECONDS value: %q", relayTTLRaw)
	}

	heartbeatRaw := getEnv("RELAY_HEARTBEAT_INTERVAL_SECONDS", strconv.Itoa(defaultHeartbeatSecs))
	heartbeatSeconds, err := strconv.Atoi(heartbeatRaw)
	if err != nil || heartbeatSeconds <= 0 {
		return Config{}, fmt.Errorf("invalid RELAY_HEARTBEAT_INTERVAL_SECONDS value: %q", heartbeatRaw)
	}

	sessionTTLRaw := getEnv("SESSION_TTL_SECONDS", strconv.Itoa(defaultSessionTTLSecs))
	sessionTTLSeconds, err := strconv.Atoi(sessionTTLRaw)
	if err != nil || sessionTTLSeconds <= 0 {
		return Config{}, fmt.Errorf("invalid SESSION_TTL_SECONDS value: %q", sessionTTLRaw)
	}

	refreshRaw := getEnv("SESSION_REFRESH_INTERVAL_SECONDS", strconv.Itoa(defaultSessionRefreshSecs))
	sessionRefreshSeconds, err := strconv.Atoi(refreshRaw)
	if err != nil || sessionRefreshSeconds <= 0 {
		return Config{}, fmt.Errorf("invalid SESSION_REFRESH_INTERVAL_SECONDS value: %q", refreshRaw)
	}

	cfg := Config{
		Port:                          getEnv("PORT", defaultPort),
		RelayID:                       getEnv("RELAY_ID", defaultRelayID),
		PublicEndpoint:                getEnv("RELAY_PUBLIC_ENDPOINT", defaultPublicEndpoint),
		InternalEndpoint:              getEnv("RELAY_INTERNAL_ENDPOINT", defaultInternalAddress),
		MaxSessions:                   maxSessions,
		RedisURL:                      getEnv("REDIS_URL", defaultRedisURL),
		RelayTTLSeconds:               relayTTLSeconds,
		HeartbeatSeconds:              heartbeatSeconds,
		SessionTTLSeconds:             sessionTTLSeconds,
		SessionRefreshIntervalSeconds: sessionRefreshSeconds,
	}

	if strings.TrimSpace(cfg.Port) == "" {
		return Config{}, fmt.Errorf("PORT must not be empty")
	}

	if strings.TrimSpace(cfg.RelayID) == "" {
		return Config{}, fmt.Errorf("RELAY_ID must not be empty")
	}

	return cfg, nil
}

func (c Config) ListenAddr() string {
	return ":" + c.Port
}

func getEnv(key string, fallback string) string {
	value, ok := os.LookupEnv(key)
	if !ok {
		return fallback
	}

	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return fallback
	}

	return trimmed
}
