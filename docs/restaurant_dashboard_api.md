# Restaurant simulation dashboard API

These read-only endpoints expose run artifacts (`run_manifest.json`, `profiles_used.json`, `dining_trace.jsonl`, and `round_summary.jsonl`) to a restaurant dashboard. The run directory is read from `COMPETEAI_RUNS_DIR`, or from the repository's `logs/` directory by default. Configure that environment variable when the API server and simulation logs live on different hosts or paths.

Base path: `/api/v1`

## List runs

`GET /api/v1/runs/`

Returns runs with a manifest and profile snapshot.

## Select a restaurant

`GET /api/v1/runs/{run_id}/restaurants/`

Returns restaurant IDs, display names, categories, cities, baseline score/count, the latest round and simulated visit count. Use the returned `restaurant_id` in the following endpoints.

## Restaurant snapshot

`GET /api/v1/runs/{run_id}/restaurants/{restaurant_id}/`

Returns static restaurant profile fields, current simulation state and rating history. The rating scale is included as stored in the run profile; scores are not converted.

## Visitors for a round

`GET /api/v1/runs/{run_id}/restaurants/{restaurant_id}/rounds/{round}/visits/?limit=100&offset=0`

Each item represents a simulated customer who selected this restaurant in that round. It includes the anonymous run-local customer ID, the public portrait fields, review score and comment. `limit` is capped at 500. Raw source customer IDs are not returned. City, province and occupation fields are omitted from the displayed customer profile.

## Live events

`GET /api/v1/runs/{run_id}/restaurants/{restaurant_id}/events/?after_seq=0`

Server-Sent Events stream. Event types are `visit.completed` and `round.completed`. Pass the last received SSE ID as `after_seq` when reconnecting. A completed or failed run closes the stream after its available events have been sent.

The API does not synthesize minute-level arrival times, seat positions, queues, orders or bills; those are not recorded by the current round-based simulation.
