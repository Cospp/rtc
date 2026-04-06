package relay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"

	"relay/internal/config"
)

type Status string

const (
	StatusStarting Status = "starting"
	StatusWarm     Status = "warm"
	StatusFull     Status = "full"
)

type SessionBinding struct {
	SessionID            string    `json:"session_id"`
	WorkerID             string    `json:"worker_id"`
	WorkerEndpoint       string    `json:"worker_endpoint"`
	BoundAt              time.Time `json:"bound_at"`
	IngestedPackets      int       `json:"ingested_packets"`
	IngestedBytes        int       `json:"ingested_bytes"`
	LastIngestedAt       string    `json:"last_ingested_at,omitempty"`
	LastSessionRefreshAt string    `json:"last_session_refresh_at,omitempty"`
	LastStatsPersistAt   string    `json:"last_stats_persist_at,omitempty"`
}

type Snapshot struct {
	RelayID          string           `json:"relay_id"`
	Status           Status           `json:"status"`
	PublicEndpoint   string           `json:"public_endpoint"`
	InternalEndpoint string           `json:"internal_endpoint"`
	CurrentSessions  int              `json:"current_sessions"`
	MaxSessions      int              `json:"max_sessions"`
	Sessions         []SessionBinding `json:"sessions"`
}

type redisRelayRecord struct {
	RelayID          string `json:"relay_id"`
	Status           Status `json:"status"`
	PublicEndpoint   string `json:"public_endpoint"`
	InternalEndpoint string `json:"internal_endpoint"`
	LastHeartbeat    string `json:"last_heartbeat"`
	CurrentSessions  int    `json:"current_sessions"`
	MaxSessions      int    `json:"max_sessions"`
}

type redisWorkerRecord struct {
	WorkerID          string `json:"worker_id"`
	Status            string `json:"status"`
	Endpoint          string `json:"endpoint"`
	LastHeartbeat     string `json:"last_heartbeat"`
	AssignedSessionID string `json:"assigned_session_id"`
}

type relayMediaStatsRecord struct {
	SessionID       string `json:"session_id"`
	RelayID         string `json:"relay_id"`
	WorkerID        string `json:"worker_id"`
	TotalPackets    int    `json:"total_packets"`
	TotalBytes      int    `json:"total_bytes"`
	LastIngestedAt  string `json:"last_ingested_at"`
	LastPersistedAt string `json:"last_persisted_at"`
}

type Service struct {
	cfg        config.Config
	redis      *redis.Client
	httpClient *http.Client
	mu         sync.RWMutex
	status     Status
	sessions   map[string]SessionBinding
	started    bool
}

func NewService(cfg config.Config, redisClient *redis.Client) *Service {
	return &Service{
		cfg:        cfg,
		redis:      redisClient,
		httpClient: &http.Client{Timeout: 5 * time.Second},
		status:     StatusStarting,
		sessions:   make(map[string]SessionBinding),
	}
}

func (s *Service) Start(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.started {
		return nil
	}

	s.started = true
	s.status = s.computeStatusLocked()

	if err := s.persistLocked(ctx); err != nil {
		s.started = false
		return err
	}

	go s.heartbeatLoop()
	return nil
}

func (s *Service) Health() map[string]string {
	return map[string]string{
		"status": "ok",
	}
}

func (s *Service) Ready() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return s.started && (s.status == StatusWarm || s.status == StatusFull)
}

func (s *Service) BindSession(sessionID string, workerID string) (SessionBinding, error) {
	if sessionID == "" {
		return SessionBinding{}, fmt.Errorf("session_id must not be empty")
	}

	if workerID == "" {
		return SessionBinding{}, fmt.Errorf("worker_id must not be empty")
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if existing, exists := s.sessions[sessionID]; exists {
		return existing, nil
	}

	if len(s.sessions) >= s.cfg.MaxSessions {
		s.status = StatusFull
		return SessionBinding{}, fmt.Errorf("relay capacity reached")
	}

	workerEndpoint, err := s.markWorkerActiveLocked(context.Background(), workerID, sessionID)
	if err != nil {
		return SessionBinding{}, err
	}

	binding := SessionBinding{
		SessionID:      sessionID,
		WorkerID:       workerID,
		WorkerEndpoint: workerEndpoint,
		BoundAt:        time.Now().UTC(),
	}

	if err := s.bindWorkerMediaLocked(context.Background(), binding); err != nil {
		return SessionBinding{}, err
	}

	s.sessions[sessionID] = binding
	s.status = s.computeStatusLocked()

	if err := s.persistLocked(context.Background()); err != nil {
		delete(s.sessions, sessionID)
		s.status = s.computeStatusLocked()
		return SessionBinding{}, err
	}

	return binding, nil
}

func (s *Service) Snapshot() Snapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()

	sessions := make([]SessionBinding, 0, len(s.sessions))
	for _, session := range s.sessions {
		sessions = append(sessions, session)
	}

	return Snapshot{
		RelayID:          s.cfg.RelayID,
		Status:           s.status,
		PublicEndpoint:   s.cfg.PublicEndpoint,
		InternalEndpoint: s.cfg.InternalEndpoint,
		CurrentSessions:  len(s.sessions),
		MaxSessions:      s.cfg.MaxSessions,
		Sessions:         sessions,
	}
}

func (s *Service) IngestPayload(sessionID string, payload []byte) (SessionBinding, error) {
	if sessionID == "" {
		return SessionBinding{}, fmt.Errorf("session_id must not be empty")
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	binding, exists := s.sessions[sessionID]
	if !exists {
		return SessionBinding{}, fmt.Errorf("unknown session: %s", sessionID)
	}

	if err := s.forwardPayloadToWorkerLocked(binding, payload); err != nil {
		return SessionBinding{}, err
	}

	if err := s.refreshSessionTTLLocked(context.Background(), &binding); err != nil {
		return SessionBinding{}, err
	}

	binding.IngestedPackets++
	binding.IngestedBytes += len(payload)
	binding.LastIngestedAt = time.Now().UTC().Format(time.RFC3339Nano)

	if err := s.persistMediaStatsLocked(context.Background(), &binding, false); err != nil {
		return SessionBinding{}, err
	}

	s.sessions[sessionID] = binding

	return binding, nil
}

func (s *Service) heartbeatLoop() {
	ticker := time.NewTicker(time.Duration(s.cfg.HeartbeatSeconds) * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		s.mu.Lock()
		_ = s.cleanupExpiredSessionsLocked(context.Background())
		s.status = s.computeStatusLocked()
		_ = s.persistLocked(context.Background())
		s.mu.Unlock()
	}
}

func (s *Service) cleanupExpiredSessionsLocked(ctx context.Context) error {
	for sessionID, binding := range s.sessions {
		exists, err := s.redis.Exists(ctx, "session:"+sessionID).Result()
		if err != nil {
			return fmt.Errorf("check session existence: %w", err)
		}

		if exists == 0 {
			_ = s.persistMediaStatsLocked(ctx, &binding, true)
			if err := s.releaseWorkerLocked(ctx, binding.WorkerID, sessionID); err != nil {
				return err
			}
			delete(s.sessions, sessionID)
		}
	}

	return nil
}

func (s *Service) markWorkerActiveLocked(ctx context.Context, workerID string, sessionID string) (string, error) {
	workerKey := "worker:" + workerID
	workerRaw, err := s.redis.Get(ctx, workerKey).Result()
	if err != nil {
		return "", fmt.Errorf("load worker %s: %w", workerID, err)
	}

	var worker redisWorkerRecord
	if err := json.Unmarshal([]byte(workerRaw), &worker); err != nil {
		return "", fmt.Errorf("decode worker %s: %w", workerID, err)
	}

	worker.Status = "active"
	worker.AssignedSessionID = sessionID

	updatedWorker, err := json.Marshal(worker)
	if err != nil {
		return "", fmt.Errorf("encode worker %s: %w", workerID, err)
	}

	if err := s.redis.SetArgs(ctx, workerKey, string(updatedWorker), redis.SetArgs{KeepTTL: true}).Err(); err != nil {
		return "", fmt.Errorf("persist worker %s: %w", workerID, err)
	}

	if err := s.redis.SRem(ctx, "workers:warm", workerID).Err(); err != nil {
		return "", fmt.Errorf("remove worker %s from warm set: %w", workerID, err)
	}

	return worker.Endpoint, nil
}

func (s *Service) releaseWorkerLocked(ctx context.Context, workerID string, sessionID string) error {
	workerKey := "worker:" + workerID
	workerRaw, err := s.redis.Get(ctx, workerKey).Result()
	if err == redis.Nil {
		return nil
	}
	if err != nil {
		return fmt.Errorf("load worker %s: %w", workerID, err)
	}

	var worker redisWorkerRecord
	if err := json.Unmarshal([]byte(workerRaw), &worker); err != nil {
		return fmt.Errorf("decode worker %s: %w", workerID, err)
	}

	if worker.AssignedSessionID != sessionID {
		return nil
	}

	worker.Status = "warm"
	worker.AssignedSessionID = ""

	updatedWorker, err := json.Marshal(worker)
	if err != nil {
		return fmt.Errorf("encode worker %s: %w", workerID, err)
	}

	if err := s.redis.SetArgs(ctx, workerKey, string(updatedWorker), redis.SetArgs{KeepTTL: true}).Err(); err != nil {
		return fmt.Errorf("persist worker %s: %w", workerID, err)
	}

	if err := s.redis.SAdd(ctx, "workers:warm", workerID).Err(); err != nil {
		return fmt.Errorf("add worker %s to warm set: %w", workerID, err)
	}

	return nil
}

func (s *Service) computeStatusLocked() Status {
	if len(s.sessions) >= s.cfg.MaxSessions {
		return StatusFull
	}

	return StatusWarm
}

func (s *Service) persistLocked(ctx context.Context) error {
	record := redisRelayRecord{
		RelayID:          s.cfg.RelayID,
		Status:           s.status,
		PublicEndpoint:   s.cfg.PublicEndpoint,
		InternalEndpoint: s.cfg.InternalEndpoint,
		LastHeartbeat:    time.Now().UTC().Format(time.RFC3339Nano),
		CurrentSessions:  len(s.sessions),
		MaxSessions:      s.cfg.MaxSessions,
	}

	payload, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("marshal relay record: %w", err)
	}

	relayKey := "relay:" + s.cfg.RelayID
	if err := s.redis.Set(ctx, relayKey, string(payload), time.Duration(s.cfg.RelayTTLSeconds)*time.Second).Err(); err != nil {
		return fmt.Errorf("persist relay record: %w", err)
	}

	if s.status == StatusWarm {
		if err := s.redis.SAdd(ctx, "relays:available", s.cfg.RelayID).Err(); err != nil {
			return fmt.Errorf("add relay to available set: %w", err)
		}
	} else {
		if err := s.redis.SRem(ctx, "relays:available", s.cfg.RelayID).Err(); err != nil {
			return fmt.Errorf("remove relay from available set: %w", err)
		}
	}

	return nil
}

func (s *Service) bindWorkerMediaLocked(ctx context.Context, binding SessionBinding) error {
	url := fmt.Sprintf("http://%s/internal/v1/media/bind/%s", binding.WorkerEndpoint, binding.SessionID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, nil)
	if err != nil {
		return fmt.Errorf("create worker bind request: %w", err)
	}

	resp, err := s.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("bind worker media session: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf(
			"bind worker media session failed: status=%d body=%s",
			resp.StatusCode,
			strings.TrimSpace(string(body)),
		)
	}

	return nil
}

func (s *Service) forwardPayloadToWorkerLocked(binding SessionBinding, payload []byte) error {
	url := fmt.Sprintf("http://%s/internal/v1/media/ingest/%s", binding.WorkerEndpoint, binding.SessionID)
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("create worker ingest request: %w", err)
	}
	req.Header.Set("Content-Type", "application/octet-stream")

	resp, err := s.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("forward payload to worker: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf(
			"worker ingest failed: status=%d body=%s",
			resp.StatusCode,
			strings.TrimSpace(string(body)),
		)
	}

	return nil
}

func (s *Service) refreshSessionTTLLocked(ctx context.Context, binding *SessionBinding) error {
	now := time.Now().UTC()
	if binding.LastSessionRefreshAt != "" {
		lastRefresh, err := time.Parse(time.RFC3339Nano, binding.LastSessionRefreshAt)
		if err == nil && now.Sub(lastRefresh) < time.Duration(s.cfg.SessionRefreshIntervalSeconds)*time.Second {
			return nil
		}
	}

	if err := s.redis.Expire(ctx, "session:"+binding.SessionID, time.Duration(s.cfg.SessionTTLSeconds)*time.Second).Err(); err != nil {
		return fmt.Errorf("refresh session ttl for %s: %w", binding.SessionID, err)
	}

	binding.LastSessionRefreshAt = now.Format(time.RFC3339Nano)
	return nil
}

func (s *Service) persistMediaStatsLocked(ctx context.Context, binding *SessionBinding, force bool) error {
	now := time.Now().UTC()
	if !force && binding.LastStatsPersistAt != "" {
		lastPersist, err := time.Parse(time.RFC3339Nano, binding.LastStatsPersistAt)
		if err == nil && now.Sub(lastPersist) < time.Duration(s.cfg.SessionRefreshIntervalSeconds)*time.Second {
			return nil
		}
	}

	record := relayMediaStatsRecord{
		SessionID:       binding.SessionID,
		RelayID:         s.cfg.RelayID,
		WorkerID:        binding.WorkerID,
		TotalPackets:    binding.IngestedPackets,
		TotalBytes:      binding.IngestedBytes,
		LastIngestedAt:  binding.LastIngestedAt,
		LastPersistedAt: now.Format(time.RFC3339Nano),
	}

	payload, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("marshal relay media stats: %w", err)
	}

	ttlSeconds := s.cfg.SessionTTLSeconds + (s.cfg.SessionRefreshIntervalSeconds * 3)
	if ttlSeconds < s.cfg.RelayTTLSeconds {
		ttlSeconds = s.cfg.RelayTTLSeconds
	}

	key := "session-media-relay:" + binding.SessionID
	if err := s.redis.Set(ctx, key, string(payload), time.Duration(ttlSeconds)*time.Second).Err(); err != nil {
		return fmt.Errorf("persist relay media stats for %s: %w", binding.SessionID, err)
	}

	binding.LastStatsPersistAt = record.LastPersistedAt
	return nil
}
