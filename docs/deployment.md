# Model connections and deployment

The example, evidence, approval history and file exports run independently of model availability. Requesting advice sends up to eight proposed actions and short excerpts of their linked source records to the configured model. A reviewer decides which actions to approve. Source files, deployment keys and credentials stay out of the repository.

| Connection | Environment on the server |
| --- | --- |
| Ollama | Set `MODEL_PROVIDER=local`, `MODEL_BASE_URL=http://127.0.0.1:11434/v1` and `MODEL_ID` to a pulled chat model. |
| LM Studio | Start its local server, set `MODEL_PROVIDER=local`, `MODEL_BASE_URL=http://127.0.0.1:1234/v1` and use its loaded model identifier for `MODEL_ID`. |
| Azure OpenAI | Set `MODEL_PROVIDER=azure`, `MODEL_BASE_URL=https://YOUR-RESOURCE.openai.azure.com`, `MODEL_API_KEY` and `MODEL_ID` to your chat deployment name. The client uses Azure's v1 chat completion endpoint. |
| Amazon Bedrock | Install `requirements.txt`, set `MODEL_PROVIDER=bedrock`, `AWS_REGION` and `MODEL_ID` to a Converse-supported model or inference profile available to your identity. The standard boto3 credential chain signs requests. |
| Compatible API | Set `MODEL_PROVIDER=api`, an HTTPS `MODEL_BASE_URL` including its API root (often `/v1`), `MODEL_API_KEY` and `MODEL_ID`. |

Restart the server after changing its environment. A container's loopback address refers to the container. With Docker Desktop, use `host.docker.internal` for the model on your computer. On Linux, provide a reachable host and configure the model server to listen on that interface.

## Deploy

Launch the Render blueprint from the README or build the Dockerfile. In the Render dashboard, copy the generated `WORKSPACE_KEY` into **Saved revisions → Deployment key** in the app. The public preview supports source analysis, approvals and exports. The key enables model requests and persistent workspace operations. Use HTTPS for hosted access and share the key only with trusted collaborators.

For Docker, set the server-side key and persist the database in a named volume. Run the following in a POSIX shell after setting `WORKSPACE_KEY` to a long secret in your environment. Docker Desktop PowerShell also accepts `-e WORKSPACE_KEY` when you set `$env:WORKSPACE_KEY` before running the commands.

```sh
docker build -t review-studio .
docker run --rm -p 127.0.0.1:8000:8000 -e WORKSPACE_KEY -v voice-session-director-data:/data review-studio
```

Give each repository its own named volume. Set `WORKSPACE_DB` to move the SQLite database. Render's default free filesystem is ephemeral across redeploys. Download a release ZIP to retain the source and approved decisions, or configure a persistent disk for the database.

## Review history and API

Saving assigns a random workspace ID. Copy it to reopen the project. Each save appends a revision and rejects stale edits with HTTP 409. Compare two revisions to identify newly approved or removed actions, changed review notes and source changes. To branch from an old revision, open it and choose **Start separate workspace**.

The browser and HTTP clients use the same JSON API. POST requests use `Content-Type: application/json`. For private operations pass the deployment key in `X-Workspace-Key`. Use `GET /api/example` for the bundled input.

| POST endpoint | JSON fields | Result |
| --- | --- | --- |
| `/api/analyze` | `source` | Metrics, records, proposed actions and source IDs |
| `/api/artifacts` | `source, choices` | Text previews of the native output files |
| `/api/recommend` | `source`, optionally `focus` | Suggested IDs and validated source citations |
| `/api/save` | `source, choices`, optionally `workspace, base` | Workspace ID and saved revision |
| `/api/read` | `workspace`, optionally `revision` | Source and approvals at that revision |
| `/api/history` | `workspace` | Revision numbers and timestamps |
| `/api/compare` | `workspace, before, after` | Decision and note differences |
| `/api/export` | `source, choices` or `workspace, revision` | ZIP with native output, source and SHA-256 checksums |

`choices` is an object mapping approved candidate IDs to optional notes, for example `{"candidate-id": "Checked against the original."}`. Use IDs from the latest analysis. The model can only recommend available actions with matching evidence IDs. Citations validate the reference, while their interpretation still needs human review.
