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
)

func stream(ctx context.Context, wg *sync.WaitGroup, subreddit string, interval time.Duration) {
	defer wg.Done()

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

	searchTerms := make([]string, 0)
	searchTermsStr := os.Getenv("RIPPL_SEARCH_TERMS")
	if len(searchTermsStr) > 0 {
		parts := strings.Split(searchTermsStr, ",")

		for _, part := range parts {
			searchTerms = append(searchTerms, strings.TrimSpace(part))
		}
	}

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
			postData := bytes.NewBuffer([]byte(fmt.Sprintf("{\"submission_id\": \"%s\"}", post.ID)))

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

			_, err := downloadClient.Post(
				os.Getenv("RIPPL_DOWNLOAD_SERVER_URL"),
				"application/json",
				postData,
			)
			if err != nil {
				log.Printf("Request to download submission %s failed: %s", post.ID, err)
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
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	wg := sync.WaitGroup{}

	subredditsStr := os.Getenv("RIPPL_SUBREDDITS")
	subreddits := strings.Split(subredditsStr, ",")

	interval, err := strconv.Atoi(os.Getenv("RIPPL_INTERVAL"))
	if err != nil {
		interval = len(subreddits)
	}

	for i := range subreddits {
		subreddit := subreddits[i]
		wg.Add(1)

		go stream(ctx, &wg, subreddit, time.Duration(interval)*time.Second)
	}

	wg.Wait()
}