//! Playback state and the single global player session. `/api/player/*`.
//!
//! `player_session` has exactly one row: claiming issues a new token and
//! displaces the previous one. Every player write presents its token in
//! `X-Player-Session` (401 when missing) and is refused with 409 once
//! displaced.

use axum::Json;
use axum::extract::State;
use axum::http::HeaderMap;
use chrono::{DateTime, NaiveDate, Utc};
use rand::Rng;
use serde::{Deserialize, Serialize};
use sqlx::{FromRow, PgConnection};

use crate::error::AppError;
use crate::server::{ApiJson, ApiPath, ApiQuery, AppState, limit_param, positive_id};
use crate::shows::{OK, StatusOk};

const SESSION_HEADER: &str = "x-player-session";

const CLAIM_SQL: &str = "
INSERT INTO player_session (id, session_token)
VALUES (1, $1)
ON CONFLICT (id) DO UPDATE
  SET session_token = EXCLUDED.session_token,
      claimed_at = now(),
      last_seen_at = now()";

const TOUCH_SQL: &str = "
UPDATE player_session
SET last_seen_at = now()
WHERE id = 1 AND session_token = $1
RETURNING 1";

const GUARD_SQL: &str = "
SELECT 1
FROM player_session
WHERE id = 1 AND session_token = $1
FOR UPDATE";

const PROGRESS_UPSERT_SQL: &str = "
INSERT INTO episode_play_state (episode_id, position_ms, duration_ms, last_played_at, completed)
VALUES ($1, $2, $3, now(), $4)
ON CONFLICT (episode_id) DO UPDATE
  SET position_ms = EXCLUDED.position_ms,
      duration_ms = COALESCE(EXCLUDED.duration_ms, episode_play_state.duration_ms),
      last_played_at = EXCLUDED.last_played_at,
      completed = EXCLUDED.completed";

const LIST_SQL_BASE: &str = "
SELECT eps.episode_id AS id, e.aired_on, e.time_slot,
       s.id AS show_id, s.name AS show_name, s.station,
       eps.position_ms, eps.duration_ms, eps.last_played_at
FROM episode_play_state eps
JOIN episodes e ON e.id = eps.episode_id
JOIN shows s ON s.id = e.show_id
WHERE e.deleted = FALSE";

#[derive(Serialize)]
pub struct ClaimResponse {
    session_token: String,
}

#[derive(Deserialize)]
pub struct ProgressRequest {
    position_ms: i64,
    duration_ms: Option<i64>,
    #[serde(default)]
    completed: bool,
}

#[derive(Serialize, FromRow)]
pub struct ProgressResponse {
    position_ms: i64,
    duration_ms: Option<i64>,
    completed: bool,
    last_played_at: Option<DateTime<Utc>>,
}

#[derive(Serialize, FromRow)]
pub struct RecentEpisode {
    id: i32,
    aired_on: NaiveDate,
    time_slot: Option<String>,
    show_id: i32,
    show_name: String,
    station: String,
    position_ms: i64,
    duration_ms: Option<i64>,
    last_played_at: DateTime<Utc>,
}

#[derive(Serialize)]
pub struct RecentResponse {
    episodes: Vec<RecentEpisode>,
}

#[derive(Deserialize)]
pub struct LimitQuery {
    limit: Option<i64>,
}

fn session_token(headers: &HeaderMap) -> Result<&str, AppError> {
    headers
        .get(SESSION_HEADER)
        .and_then(|v| v.to_str().ok())
        .filter(|t| !t.is_empty())
        .ok_or(AppError::Unauthorized("missing session token"))
}

const DISPLACED: AppError = AppError::Conflict("session displaced");

async fn touch_session(conn: &mut PgConnection, token: &str) -> Result<(), AppError> {
    let ok: Option<i32> = sqlx::query_scalar(TOUCH_SQL).bind(token).fetch_optional(conn).await?;
    ok.map(|_| ()).ok_or(DISPLACED)
}

/// Lock the session row for the rest of the transaction if `token` still owns it.
async fn guard_session(conn: &mut PgConnection, token: &str) -> Result<(), AppError> {
    let ok: Option<i32> = sqlx::query_scalar(GUARD_SQL).bind(token).fetch_optional(conn).await?;
    ok.map(|_| ()).ok_or(DISPLACED)
}

/// `POST /api/player/session/claim` — issue a new token, displacing the
/// previous one. Needs no token itself.
pub async fn claim_session(State(state): State<AppState>) -> Result<Json<ClaimResponse>, AppError> {
    let token = hex::encode(rand::rng().random::<[u8; 24]>());
    sqlx::query(CLAIM_SQL).bind(&token).execute(&state.pool).await?;
    Ok(Json(ClaimResponse { session_token: token }))
}

/// `POST /api/player/session/validate` — confirm the token still owns the session.
pub async fn validate_session(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<StatusOk>, AppError> {
    let token = session_token(&headers)?;
    let mut conn = state.pool.acquire().await?;
    touch_session(&mut conn, token).await?;
    Ok(OK)
}

/// `POST /api/player/episodes/{episode_id}/progress` — save the position;
/// `completed: true` marks the episode fully played. 404 if the episode is missing.
pub async fn save_progress(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
    headers: HeaderMap,
    ApiJson(body): ApiJson<ProgressRequest>,
) -> Result<Json<StatusOk>, AppError> {
    let episode_id = positive_id(episode_id)?;
    if body.position_ms < 0 || body.duration_ms.is_some_and(|d| d < 0) {
        return Err(AppError::unprocessable("position_ms and duration_ms must be >= 0"));
    }
    let token = session_token(&headers)?;
    let mut tx = state.pool.begin().await?;
    guard_session(&mut tx, token).await?;
    let exists: Option<i32> = sqlx::query_scalar("SELECT 1 FROM episodes WHERE id = $1 AND deleted = FALSE")
        .bind(episode_id)
        .fetch_optional(&mut *tx)
        .await?;
    if exists.is_none() {
        return Err(AppError::NotFound("episode not found"));
    }
    touch_session(&mut tx, token).await?;
    sqlx::query(PROGRESS_UPSERT_SQL)
        .bind(episode_id)
        .bind(body.position_ms)
        .bind(body.duration_ms)
        .bind(body.completed)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(OK)
}

/// `DELETE /api/player/episodes/{episode_id}/progress` — drop the play state
/// so the episode leaves the home rows. Idempotent.
pub async fn delete_progress(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
    headers: HeaderMap,
) -> Result<Json<StatusOk>, AppError> {
    let episode_id = positive_id(episode_id)?;
    let token = session_token(&headers)?;
    let mut tx = state.pool.begin().await?;
    guard_session(&mut tx, token).await?;
    touch_session(&mut tx, token).await?;
    sqlx::query("DELETE FROM episode_play_state WHERE episode_id = $1")
        .bind(episode_id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(OK)
}

/// `GET /api/player/episodes/{episode_id}/progress` — saved position,
/// defaulting to zero/incomplete when nothing is recorded.
pub async fn get_progress(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
) -> Result<Json<ProgressResponse>, AppError> {
    let progress = sqlx::query_as(
        "SELECT position_ms, duration_ms, completed, last_played_at
         FROM episode_play_state WHERE episode_id = $1",
    )
    .bind(positive_id(episode_id)?)
    .fetch_optional(&state.pool)
    .await?
    .unwrap_or(ProgressResponse {
        position_ms: 0,
        duration_ms: None,
        completed: false,
        last_played_at: None,
    });
    Ok(Json(progress))
}

/// `GET /api/player/recent-completed?limit=` — completed episodes, most
/// recently played first. Mutually exclusive with `/in-progress`.
pub async fn list_recent_completed(
    State(state): State<AppState>,
    ApiQuery(query): ApiQuery<LimitQuery>,
) -> Result<Json<RecentResponse>, AppError> {
    let limit = limit_param(query.limit, 10)?;
    let episodes = sqlx::query_as(&format!(
        "{LIST_SQL_BASE} AND eps.completed = TRUE ORDER BY eps.last_played_at DESC LIMIT $1"
    ))
    .bind(limit)
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(RecentResponse { episodes }))
}

/// `GET /api/player/in-progress?limit=` — incomplete episodes with a known
/// duration and more than 30s left.
pub async fn list_in_progress(
    State(state): State<AppState>,
    ApiQuery(query): ApiQuery<LimitQuery>,
) -> Result<Json<RecentResponse>, AppError> {
    let limit = limit_param(query.limit, 10)?;
    let episodes = sqlx::query_as(&format!(
        "{LIST_SQL_BASE} AND eps.completed = FALSE
           AND eps.duration_ms IS NOT NULL
           AND eps.position_ms < eps.duration_ms - 30000
         ORDER BY eps.last_played_at DESC LIMIT $1"
    ))
    .bind(limit)
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(RecentResponse { episodes }))
}

#[cfg(test)]
mod tests {
    use crate::test_support::{authed_request, body_json};
    use axum::body::Body;
    use axum::http::{Method, StatusCode, header};

    #[tokio::test]
    async fn writes_without_session_token_are_401() {
        for (method, path, body) in [
            (Method::POST, "/api/player/session/validate", "{}"),
            (Method::POST, "/api/player/episodes/1/progress", r#"{"position_ms": 5}"#),
            (Method::DELETE, "/api/player/episodes/1/progress", ""),
        ] {
            let response = authed_request(
                axum::http::Request::builder()
                    .method(method)
                    .uri(path)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(body))
                    .unwrap(),
            )
            .await;
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{path}");
            assert_eq!(
                body_json(response).await,
                serde_json::json!({ "detail": "missing session token" })
            );
        }
    }

    #[tokio::test]
    async fn negative_position_is_422() {
        let response = authed_request(
            axum::http::Request::post("/api/player/episodes/1/progress")
                .header(header::CONTENT_TYPE, "application/json")
                .header("X-Player-Session", "t")
                .body(Body::from(r#"{"position_ms": -1}"#))
                .unwrap(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }
}
