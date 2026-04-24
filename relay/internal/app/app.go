package app

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"

	"relay/internal/config"
	"relay/internal/relay"
	"relay/internal/server"
)

type App struct {
	Config  config.Config
	service *relay.Service
	server  *http.Server
}

func New() (*App, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, err
	}

	redisOptions, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}

	redisClient := redis.NewClient(redisOptions)
	if err := redisClient.Ping(context.Background()).Err(); err != nil {
		return nil, fmt.Errorf("ping redis: %w", err)
	}

	service := relay.NewService(cfg, redisClient)
	handler := server.NewHandler(service)

	httpServer := &http.Server{
		Addr:              cfg.ListenAddr(),
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	return &App{
		Config:  cfg,
		service: service,
		server:  httpServer,
	}, nil
}

func (a *App) Run() error {
	if a.server == nil {
		return fmt.Errorf("http server is not initialized")
	}

	if err := a.service.Start(context.Background()); err != nil {
		return fmt.Errorf("start relay service: %w", err)
	}

	log.Printf("relay heartbeat started for %s", a.Config.RelayID)

	return a.server.ListenAndServe()
}
