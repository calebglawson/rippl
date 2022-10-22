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
	submissions chan string
	interval    time.Duration
}

func (d *Downloader) run(ctx context.Context) {
	for {
		submissions := make([]string, 0)
		for {
			select {
			case submission := <-d.submissions:
				submissions = append(submissions, submission)

				continue
			default:
			}

			break
		}

		if len(submissions) > 0 {
			go download(submissions)
		}

		select {
		case <-ctx.Done():
			return
		default:
			time.Sleep(d.interval)
		}
	}
}

func (d *Downloader) add(submission string) {
	select {
	case d.submissions <- submission:
		break
	default:
		log.Print("Submission buffer overflow: increase RIPPL_BUFFER_SIZE or reduce RIPPL_INTERVAL")
	}
}

func download(submissions []string) {
	args := []string{"download.py"}
	args = append(args, submissions...)
	cmd := exec.Command("python3", args...)
	if combinedOutput, err := cmd.CombinedOutput(); err != nil {
		log.Printf("Running `%s` failed: %s: %s", cmd, err, combinedOutput)
	}
}

func stream(
	ctx context.Context,
	wg *sync.WaitGroup,
	redditClient *reddit.Client,
	downloader *Downloader,
	subreddit string,
	interval time.Duration,
	searchTerms []string,
) {
	defer wg.Done()

	posts, errs, stop := redditClient.Stream.Posts(
		strings.TrimSpace(subreddit),
		reddit.StreamInterval(interval),
		reddit.StreamDiscardInitial,
	)
	defer stop()

	log.Printf("[subreddit=%s] Stream started", subreddit)

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

			er, ok := err.(*reddit.ErrorResponse)
			if !ok {
				log.Printf("[subreddit=%s] Streaming failure: %s", subreddit, err)

				continue
			}

			switch er.Response.StatusCode {
			case http.StatusUnauthorized, http.StatusNotFound:
				log.Printf(
					"[subreddit=%s] [response_code=%d] Terminating HTTP Response code received, stream stopping",
					subreddit,
					er.Response.StatusCode,
				)

				return
			default:
				log.Printf(
					"[subreddit=%s] [response_code=%d] Streaming failure: %s",
					subreddit,
					er.Response.StatusCode,
					er,
				)
			}
		case <-ctx.Done():
			log.Printf("[subreddit=%s] Context cancelled, stream stopping", subreddit)

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

	downloadBufferSize, err := strconv.Atoi(os.Getenv("RIPPL_BUFFER_SIZE"))
	if err != nil {
		downloadBufferSize = len(subreddits) * 100
	}

	interval := time.Duration(intervalInt) * time.Second

	downloader := &Downloader{submissions: make(chan string, downloadBufferSize), interval: interval}
	go downloader.run(ctx)

	for i := range subreddits {
		subreddit := subreddits[i]
		wg.Add(1)

		go stream(ctx, &wg, redditClient, downloader, subreddit, interval, searchTerms)
	}

	wg.Wait()
}
