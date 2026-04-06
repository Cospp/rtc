package server

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"relay/internal/relay"
)

type Handler struct {
	service *relay.Service
	mux     *http.ServeMux
}

type bindSessionRequest struct {
	SessionID string `json:"session_id"`
	WorkerID  string `json:"worker_id"`
}

type errorResponse struct {
	Error string `json:"error"`
}

func NewHandler(service *relay.Service) *Handler {
	handler := &Handler{
		service: service,
		mux:     http.NewServeMux(),
	}

	handler.routes()
	return handler
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.mux.ServeHTTP(w, r)
}

func (h *Handler) routes() {
	h.mux.HandleFunc("/healthz", h.handleHealth)
	h.mux.HandleFunc("/readyz", h.handleReady)
	h.mux.HandleFunc("/internal/v1/sessions/bind", h.handleBindSession)
	h.mux.HandleFunc("/internal/v1/media/ingest/", h.handleIngestPayload)
	h.mux.HandleFunc("/internal/v1/state", h.handleState)
}

func (h *Handler) handleHealth(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeMethodNotAllowed(w, http.MethodGet)
		return
	}

	writeJSON(w, http.StatusOK, h.service.Health())
}

func (h *Handler) handleReady(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeMethodNotAllowed(w, http.MethodGet)
		return
	}

	if !h.service.Ready() {
		writeJSON(w, http.StatusServiceUnavailable, errorResponse{Error: "relay is not ready"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

func (h *Handler) handleBindSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeMethodNotAllowed(w, http.MethodPost)
		return
	}

	var request bindSessionRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "invalid json payload"})
		return
	}

	binding, err := h.service.BindSession(request.SessionID, request.WorkerID)
	if err != nil {
		writeJSON(w, http.StatusConflict, errorResponse{Error: err.Error()})
		return
	}

	writeJSON(w, http.StatusCreated, binding)
}

func (h *Handler) handleState(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeMethodNotAllowed(w, http.MethodGet)
		return
	}

	writeJSON(w, http.StatusOK, h.service.Snapshot())
}

func (h *Handler) handleIngestPayload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeMethodNotAllowed(w, http.MethodPost)
		return
	}

	sessionID := r.URL.Path[len("/internal/v1/media/ingest/"):]
	if sessionID == "" {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "missing session id"})
		return
	}

	payload, err := io.ReadAll(r.Body)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "failed to read payload"})
		return
	}

	binding, err := h.service.IngestPayload(sessionID, payload)
	if err != nil {
		status := http.StatusInternalServerError
		switch {
		case strings.HasPrefix(err.Error(), "unknown session:"):
			status = http.StatusNotFound
		case strings.HasPrefix(err.Error(), "worker ingest failed:"):
			status = http.StatusBadGateway
		case strings.HasPrefix(err.Error(), "forward payload to worker:"):
			status = http.StatusBadGateway
		}
		writeJSON(w, status, errorResponse{Error: err.Error()})
		return
	}

	writeJSON(w, http.StatusAccepted, map[string]any{
		"status":           "accepted",
		"session_id":       binding.SessionID,
		"worker_id":        binding.WorkerID,
		"ingested_packets": binding.IngestedPackets,
		"ingested_bytes":   binding.IngestedBytes,
		"last_ingested_at": binding.LastIngestedAt,
		"payload_size":     len(payload),
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)

	_ = json.NewEncoder(w).Encode(payload)
}

func writeMethodNotAllowed(w http.ResponseWriter, allowedMethod string) {
	w.Header().Set("Allow", allowedMethod)
	writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
}
