package relay

import (
	"testing"

	"github.com/redis/go-redis/v9"

	"relay/internal/config"
)

func TestComputeStatusUsesCapacity(t *testing.T) {
	service := NewService(config.Config{
		RelayID:          "relay-test",
		PublicEndpoint:   "public.test:443",
		InternalEndpoint: "relay.test:8080",
		MaxSessions:      1,
	}, redis.NewClient(&redis.Options{Addr: "localhost:0"}))

	service.sessions["sess-1"] = SessionBinding{SessionID: "sess-1", WorkerID: "worker-1"}

	if status := service.computeStatusLocked(); status != StatusFull {
		t.Fatalf("expected relay status full, got %s", status)
	}
}

func TestSnapshotReflectsCurrentSessions(t *testing.T) {
	service := NewService(config.Config{
		RelayID:          "relay-test",
		PublicEndpoint:   "public.test:443",
		InternalEndpoint: "relay.test:8080",
		MaxSessions:      2,
	}, redis.NewClient(&redis.Options{Addr: "localhost:0"}))

	service.sessions["sess-1"] = SessionBinding{SessionID: "sess-1", WorkerID: "worker-1"}
	service.status = StatusWarm

	snapshot := service.Snapshot()
	if snapshot.CurrentSessions != 1 {
		t.Fatalf("expected 1 session, got %d", snapshot.CurrentSessions)
	}

	if snapshot.RelayID != "relay-test" {
		t.Fatalf("expected relay-test, got %s", snapshot.RelayID)
	}
}

func TestBindSessionValidatesInput(t *testing.T) {
	service := NewService(config.Config{
		RelayID:          "relay-test",
		PublicEndpoint:   "public.test:443",
		InternalEndpoint: "relay.test:8080",
		MaxSessions:      2,
	}, redis.NewClient(&redis.Options{Addr: "localhost:0"}))

	if _, err := service.BindSession("", "worker-1"); err == nil {
		t.Fatal("expected empty session id to fail")
	}

	if _, err := service.BindSession("sess-1", ""); err == nil {
		t.Fatal("expected empty worker id to fail")
	}
}
