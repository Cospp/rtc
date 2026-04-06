package main

import (
	"log"

	"relay/internal/app"
)

func main() {
	application, err := app.New()
	if err != nil {
		log.Fatalf("relay startup failed: %v", err)
	}

	log.Printf(
		"relay starting id=%s listen=%s internal=%s max_sessions=%d",
		application.Config.RelayID,
		application.Config.ListenAddr(),
		application.Config.InternalEndpoint,
		application.Config.MaxSessions,
	)

	if err := application.Run(); err != nil {
		log.Fatalf("relay server stopped: %v", err)
	}
}
