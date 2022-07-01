package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os/exec"
	"time"
)

type DownloadRequest struct {
	SubmissionID string `json:"submission_id"`
}

type SubmissionPasser struct {
	submissions chan string
}

func (p *SubmissionPasser) handlePost(writer http.ResponseWriter, request *http.Request) {
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
	p.submissions <- req.SubmissionID
	log.Printf("Accepted request for submission: %s", req.SubmissionID)
}

func flush(queue []string) []string {
	batch := make([]string, len(queue))
	copy(batch, queue)

	go runScript(batch)

	return make([]string, 0, 10)
}

func runScript(batch []string) {
	args := []string{"download.py"}
	args = append(args, batch...)
	cmd := exec.Command("python3", args...)
	log.Printf("Running: %s", cmd)
	stdOutStdErr, err := cmd.CombinedOutput()
	if err != nil {
		log.Printf("Running download script failed: %s", err)
	}

	log.Printf("Script output: %s", stdOutStdErr)
}

func (p *SubmissionPasser) batchRequests() {
	queue := make([]string, 0, 10)
	ticker := time.NewTicker(time.Minute)

	for {
		select {
		case submission, ok := <-p.submissions:
			if ok {
				if len(queue) >= 10 {
					queue = flush(queue)
				}

				queue = append(queue, submission)
			}
		case <-ticker.C:
			if len(queue) > 0 {
				queue = flush(queue)
			}
		}
	}
}

func main() {
	log.Print("Starting...")

	passer := &SubmissionPasser{submissions: make(chan string)}
	go passer.batchRequests()

	http.HandleFunc("/", passer.handlePost)

	if err := http.ListenAndServe(":6984", nil); err != nil {
		log.Printf("Server stopped: %s", err)
	}
}
