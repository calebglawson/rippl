package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os/exec"
)

type DownloadRequest struct {
	SubmissionID string `json:"submission_id"`
}

func main() {
	http.HandleFunc("/", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			writer.WriteHeader(http.StatusMethodNotAllowed)

			return
		}

		data, err := io.ReadAll(request.Body)
		if err != nil {
			log.Printf("Could not read request body: %s", err)
			writer.WriteHeader(http.StatusInternalServerError)

			return
		}

		if err = request.Body.Close(); err != nil {
			log.Printf("Could not close request body: %s", err)
			writer.WriteHeader(http.StatusInternalServerError)

			return
		}

		req := &DownloadRequest{}
		if err = json.Unmarshal(data, req); err != nil {
			log.Printf("Could not unmarshal request body: %s", err)
			writer.WriteHeader(http.StatusBadRequest)

			return
		}

		writer.WriteHeader(http.StatusAccepted)

		go func() {
			cmd := exec.Command("python3", "download.py", req.SubmissionID)
			stdOutStdErr, err := cmd.CombinedOutput()
			if err != nil {
				log.Printf("Running download script failed: %s", err)
			}

			log.Printf("Script output: %s", stdOutStdErr)
		}()

	})

	log.Print("Starting...")

	if err := http.ListenAndServe(":6984", nil); err != nil {
		log.Printf("Server stopped: %s", err)
	}
}
