package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/vartanbeno/go-reddit/v2/reddit"
)

type Downloader struct {
	queue    []string
	interval time.Duration
	lock     sync.Mutex
}

func (d *Downloader) run(ctx context.Context) {
	if len(d.queue) > 0 {
		d.flush()
	}

	select {
	case <-ctx.Done():

		return
	}

	time.Sleep(d.interval)
}

func (d *Downloader) flush() {
	d.lock.Lock()
	defer d.lock.Unlock()

	args := []string{"download.py"}
	args = append(args, d.queue...)
	cmd := exec.Command("python3", args...)
	log.Printf("Running: %s", cmd)
	stdOutStdErr, err := cmd.CombinedOutput()
	if err != nil {
		log.Printf("Running download script failed: %s", err)
	}

	if len(stdOutStdErr) > 0 {
		log.Printf("Script output: %s", stdOutStdErr)
	}

	d.queue = []string{}
}

func (d *Downloader) add(submissionID string) {
	d.lock.Lock()
	defer d.lock.Unlock()

	d.queue = append(d.queue, submissionID)
}

func stream(ctx context.Context, wg *sync.WaitGroup, redditClient *reddit.Client, downloader *Downloader, subreddit string, interval time.Duration, searchTerms []string) {
	defer wg.Done()

	posts, errs, stop := redditClient.Stream.Posts(
		strings.TrimSpace(subreddit),
		reddit.StreamInterval(interval),
		reddit.StreamDiscardInitial,
	)
	defer stop()

	log.Printf("Stream %s started", subreddit)

	for {
		select {
		case post, ok := <-posts:
			if !ok {
				return
			}
			match := false
			if len(searchTerms) > 0 {
				for _, term := range searchTerms {
					if strings.Contains(post.Title, term) {
						match = true

						break
					}
				}

				if !match {
					continue
				}
			}

			downloader.add(post.ID)
		case err, ok := <-errs:
			if !ok {
				return
			}

			log.Printf("Streaming failure: %s", err)

			if er, ok := err.(*reddit.ErrorResponse); ok && er.Response.StatusCode == http.StatusUnauthorized {
				log.Printf("Received Unauthorized response status code, stream stopping")

				return
			}
		case <-ctx.Done():
			log.Printf("Context cancelled, %s stream stopping", subreddit)

			return
		}
	}
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	wg := sync.WaitGroup{}

	redditClient, err := reddit.NewClient(
		reddit.Credentials{
			ID:       os.Getenv("RIPPL_CLIENT_ID"),
			Secret:   os.Getenv("RIPPL_CLIENT_SECRET"),
			Username: os.Getenv("RIPPL_USERNAME"),
			Password: os.Getenv("RIPPL_PASSWORD"),
		},
	)
	if err != nil {
		log.Printf("Reddit Client failure: %s", err)

		return
	}

	subredditsStr := os.Getenv("RIPPL_SUBREDDITS")
	subreddits := strings.Split(subredditsStr, ",")

	searchTerms := make([]string, 0)
	searchTermsStr := os.Getenv("RIPPL_SEARCH_TERMS")
	if len(searchTermsStr) > 0 {
		parts := strings.Split(searchTermsStr, ",")

		for _, part := range parts {
			searchTerms = append(searchTerms, strings.TrimSpace(part))
		}
	}

	intervalInt, err := strconv.Atoi(os.Getenv("RIPPL_INTERVAL"))
	if err != nil {
		intervalInt = len(subreddits)
	}

	interval := time.Duration(intervalInt) * time.Second

	downloader := &Downloader{interval: interval}
	go downloader.run(ctx)

	for i := range subreddits {
		subreddit := subreddits[i]
		wg.Add(1)

		go stream(ctx, &wg, redditClient, downloader, subreddit, interval, searchTerms)
	}

	wg.Wait()
}
