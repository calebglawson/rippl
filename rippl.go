package main

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/vartanbeno/go-reddit/v2/reddit"
	_ "net/http/pprof"
)

func stream(
	ctx context.Context,
	wg *sync.WaitGroup,
	redditClient *reddit.Client,
	downloadClient *http.Client,
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

			resp, err := downloadClient.Post(
				os.Getenv("RIPPL_DOWNLOAD_SERVER_URL"),
				"application/json",
				bytes.NewBuffer([]byte(fmt.Sprintf("{\"submission_id\": \"%s\"}", post.ID))),
			)
			if err != nil {
				log.Printf("Request to download submission %s failed: %s", post.ID, err)

				if err = resp.Body.Close(); err != nil {
					log.Printf("Failed to close response body: %s", err)
				}
			}

			if err = resp.Body.Close(); err != nil {
				log.Printf("Failed to close response body: %s", err)
			}
		case err, ok := <-errs:
			if !ok {
				return
			}
			log.Printf("Streaming failure: %s", err)
		case <-ctx.Done():
			log.Printf("Context cancelled, %s stream stopping", subreddit)
			return
		}
	}
}

func main() {
	go func() {
		log.Println(http.ListenAndServe("0.0.0.0:6060", nil))
	}()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	wg := sync.WaitGroup{}

	subredditsStr := os.Getenv("RIPPL_SUBREDDITS")
	subreddits := strings.Split(subredditsStr, ",")

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

	downloadClient := &http.Client{Transport: &http.Transport{DisableKeepAlives: true}}

	interval, err := strconv.Atoi(os.Getenv("RIPPL_INTERVAL"))
	if err != nil {
		interval = len(subreddits)
	}

	searchTerms := make([]string, 0)
	searchTermsStr := os.Getenv("RIPPL_SEARCH_TERMS")
	if len(searchTermsStr) > 0 {
		parts := strings.Split(searchTermsStr, ",")

		for _, part := range parts {
			searchTerms = append(searchTerms, strings.TrimSpace(part))
		}
	}

	for i := range subreddits {
		subreddit := subreddits[i]
		wg.Add(1)

		go stream(ctx, &wg, redditClient, downloadClient, subreddit, time.Duration(interval)*time.Second, searchTerms)
	}

	wg.Wait()
}
