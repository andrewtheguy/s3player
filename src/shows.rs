//! Browse hierarchy (stations → shows → months → episodes), episode detail, and
//! favorites. `/api/shows/*`.

use axum::Json;
use axum::extract::State;
use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use sqlx::types::Json as SqlJson;
use sqlx::{FromRow, PgPool};

use crate::error::AppError;
use crate::server::{ApiPath, ApiQuery, AppState, limit_param, positive_id};
use crate::show_metadata::Chapter;

#[derive(Serialize, FromRow)]
pub struct Station {
    #[sqlx(rename = "station")]
    id: String,
    show_count: i32,
}

#[derive(Serialize)]
pub struct StationsResponse {
    stations: Vec<Station>,
}

#[derive(Serialize, FromRow)]
pub struct Show {
    id: i32,
    name: String,
    episode_count: i32,
    is_favorite: bool,
}

#[derive(Serialize)]
pub struct ShowsResponse {
    shows: Vec<Show>,
}

#[derive(Serialize, FromRow)]
pub struct ShowDetail {
    id: i32,
    station: String,
    name: String,
    episode_count: i32,
}

#[derive(Serialize, FromRow)]
pub struct FavoriteShow {
    id: i32,
    station: String,
    name: String,
    episode_count: i32,
    favorited_at: DateTime<Utc>,
    latest_aired_on: Option<NaiveDate>,
}

#[derive(Serialize)]
pub struct FavoritesResponse {
    favorites: Vec<FavoriteShow>,
}

#[derive(Serialize, FromRow)]
pub struct ShowEpisode {
    id: i32,
    aired_on: NaiveDate,
    time_slot: Option<String>,
    show_id: i32,
    show_name: String,
    station: String,
    position_ms: i64,
    duration_ms: Option<i64>,
    completed: bool,
    last_played_at: Option<DateTime<Utc>>,
}

#[derive(Serialize)]
pub struct RecentShowEpisodesResponse {
    show: ShowDetail,
    episodes: Vec<ShowEpisode>,
}

#[derive(Serialize, FromRow)]
pub struct MonthBucket {
    year: i32,
    month: i32,
    episode_count: i32,
}

#[derive(Serialize)]
pub struct MonthsResponse {
    show: ShowDetail,
    months: Vec<MonthBucket>,
}

#[derive(Serialize, FromRow)]
pub struct Episode {
    id: i32,
    aired_on: NaiveDate,
    time_slot: Option<String>,
    s3_key: String,
    chapters: Option<SqlJson<Vec<Chapter>>>,
}

#[derive(Serialize)]
pub struct EpisodesResponse {
    show: ShowDetail,
    episodes: Vec<Episode>,
}

#[derive(Serialize)]
pub struct EpisodeDetail {
    #[serde(flatten)]
    episode: Episode,
    show: ShowDetail,
}

#[derive(Serialize)]
pub struct StatusOk {
    status: &'static str,
}

pub const OK: Json<StatusOk> = Json(StatusOk { status: "ok" });

async fn show_detail(pool: &PgPool, show_id: i32) -> Result<ShowDetail, AppError> {
    sqlx::query_as(
        "SELECT s.id, s.station, s.name,
                COUNT(e.id) FILTER (WHERE e.deleted = FALSE)::int AS episode_count
         FROM shows s LEFT JOIN episodes e ON e.show_id = s.id
         WHERE s.id = $1 GROUP BY s.id, s.station, s.name",
    )
    .bind(show_id)
    .fetch_optional(pool)
    .await?
    .ok_or(AppError::NotFound("show not found"))
}

/// The S3 key of a live (not soft-deleted) episode.
pub async fn episode_s3_key(pool: &PgPool, episode_id: i32) -> Result<String, AppError> {
    sqlx::query_scalar("SELECT s3_key FROM episodes WHERE id = $1 AND deleted = FALSE")
        .bind(episode_id)
        .fetch_optional(pool)
        .await?
        .ok_or(AppError::NotFound("episode not found"))
}

/// `GET /api/shows/stations` — every station and its show count.
pub async fn list_stations(State(state): State<AppState>) -> Result<Json<StationsResponse>, AppError> {
    let stations = sqlx::query_as(
        "SELECT station, COUNT(*)::int AS show_count FROM shows GROUP BY station ORDER BY station",
    )
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(StationsResponse { stations }))
}

/// `GET /api/shows/stations/{station}/shows` — shows of a station with episode counts.
pub async fn list_shows(
    State(state): State<AppState>,
    ApiPath(station): ApiPath<String>,
) -> Result<Json<ShowsResponse>, AppError> {
    let shows = sqlx::query_as(
        "SELECT s.id, s.name, COUNT(e.id)::int AS episode_count,
                (f.show_id IS NOT NULL) AS is_favorite
         FROM shows s
         LEFT JOIN episodes e ON e.show_id = s.id AND e.deleted = FALSE
         LEFT JOIN favorite_shows f ON f.show_id = s.id
         WHERE s.station = $1
         GROUP BY s.id, s.name, f.show_id ORDER BY s.name",
    )
    .bind(station)
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(ShowsResponse { shows }))
}

/// `GET /api/shows/favorites` — favorite shows, latest-aired first.
pub async fn list_favorites(State(state): State<AppState>) -> Result<Json<FavoritesResponse>, AppError> {
    let favorites = sqlx::query_as(
        "SELECT s.id, s.station, s.name,
                COUNT(e.id) FILTER (WHERE e.deleted = FALSE)::int AS episode_count,
                MAX(e.aired_on) FILTER (WHERE e.deleted = FALSE) AS latest_aired_on,
                f.favorited_at
         FROM favorite_shows f
         JOIN shows s ON s.id = f.show_id
         LEFT JOIN episodes e ON e.show_id = s.id
         GROUP BY s.id, s.station, s.name, f.favorited_at
         ORDER BY MAX(e.aired_on) FILTER (WHERE e.deleted = FALSE) DESC NULLS LAST,
                  f.favorited_at DESC",
    )
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(FavoritesResponse { favorites }))
}

/// `GET /api/shows/{show_id}` — station, name, and episode count. 404 if missing.
pub async fn get_show(
    State(state): State<AppState>,
    ApiPath(show_id): ApiPath<i32>,
) -> Result<Json<ShowDetail>, AppError> {
    Ok(Json(show_detail(&state.pool, positive_id(show_id)?).await?))
}

/// `POST /api/shows/{show_id}/favorite` — idempotent. 404 if the show is missing.
pub async fn add_favorite(
    State(state): State<AppState>,
    ApiPath(show_id): ApiPath<i32>,
) -> Result<Json<StatusOk>, AppError> {
    let show_id = positive_id(show_id)?;
    let mut tx = state.pool.begin().await?;
    let exists: Option<i32> = sqlx::query_scalar("SELECT 1 FROM shows WHERE id = $1")
        .bind(show_id)
        .fetch_optional(&mut *tx)
        .await?;
    if exists.is_none() {
        return Err(AppError::NotFound("show not found"));
    }
    sqlx::query("INSERT INTO favorite_shows (show_id) VALUES ($1) ON CONFLICT (show_id) DO NOTHING")
        .bind(show_id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(OK)
}

/// `DELETE /api/shows/{show_id}/favorite` — idempotent.
pub async fn remove_favorite(
    State(state): State<AppState>,
    ApiPath(show_id): ApiPath<i32>,
) -> Result<Json<StatusOk>, AppError> {
    sqlx::query("DELETE FROM favorite_shows WHERE show_id = $1")
        .bind(positive_id(show_id)?)
        .execute(&state.pool)
        .await?;
    Ok(OK)
}

#[derive(Deserialize)]
pub struct LimitQuery {
    limit: Option<i64>,
}

/// `GET /api/shows/{show_id}/recent-episodes?limit=` — latest episodes (default
/// 20, max 50) with their play state. 404 if the show is missing.
pub async fn list_recent_episodes(
    State(state): State<AppState>,
    ApiPath(show_id): ApiPath<i32>,
    ApiQuery(query): ApiQuery<LimitQuery>,
) -> Result<Json<RecentShowEpisodesResponse>, AppError> {
    let show_id = positive_id(show_id)?;
    let limit = limit_param(query.limit, 20)?;
    let show = show_detail(&state.pool, show_id).await?;
    let episodes = sqlx::query_as(
        "SELECT e.id, e.aired_on, e.time_slot,
                s.id AS show_id, s.name AS show_name, s.station,
                COALESCE(ps.position_ms, 0) AS position_ms,
                ps.duration_ms,
                COALESCE(ps.completed, FALSE) AS completed,
                ps.last_played_at
         FROM episodes e
         JOIN shows s ON s.id = e.show_id
         LEFT JOIN episode_play_state ps ON ps.episode_id = e.id
         WHERE e.show_id = $1 AND e.deleted = FALSE
         ORDER BY e.aired_on DESC, e.time_slot DESC NULLS LAST
         LIMIT $2",
    )
    .bind(show_id)
    .bind(limit)
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(RecentShowEpisodesResponse { show, episodes }))
}

/// `GET /api/shows/{show_id}/months` — (year, month) buckets with episode counts.
pub async fn list_months(
    State(state): State<AppState>,
    ApiPath(show_id): ApiPath<i32>,
) -> Result<Json<MonthsResponse>, AppError> {
    let show_id = positive_id(show_id)?;
    let show = show_detail(&state.pool, show_id).await?;
    let months = sqlx::query_as(
        "SELECT EXTRACT(YEAR FROM aired_on)::int AS year,
                EXTRACT(MONTH FROM aired_on)::int AS month,
                COUNT(*)::int AS episode_count
         FROM episodes WHERE show_id = $1 AND deleted = FALSE
         GROUP BY year, month ORDER BY year DESC, month DESC",
    )
    .bind(show_id)
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(MonthsResponse { show, months }))
}

/// First day of the month and of the month after.
fn month_range(year: i32, month: u32) -> Option<(NaiveDate, NaiveDate)> {
    if !(1900..=2999).contains(&year) {
        return None;
    }
    let start = NaiveDate::from_ymd_opt(year, month, 1)?;
    let end = if month == 12 {
        NaiveDate::from_ymd_opt(year + 1, 1, 1)?
    } else {
        NaiveDate::from_ymd_opt(year, month + 1, 1)?
    };
    Some((start, end))
}

/// `GET /api/shows/{show_id}/months/{year}/{month}/episodes` — the month's episodes.
pub async fn list_episodes(
    State(state): State<AppState>,
    ApiPath((show_id, year, month)): ApiPath<(i32, i32, u32)>,
) -> Result<Json<EpisodesResponse>, AppError> {
    let show_id = positive_id(show_id)?;
    let (start, end) = month_range(year, month)
        .ok_or_else(|| AppError::unprocessable("year must be 1900-2999 and month 1-12"))?;
    let show = show_detail(&state.pool, show_id).await?;
    let episodes = sqlx::query_as(
        "SELECT id, aired_on, time_slot, s3_key, chapters
         FROM episodes
         WHERE show_id = $1 AND aired_on >= $2 AND aired_on < $3 AND deleted = FALSE
         ORDER BY aired_on, time_slot NULLS LAST",
    )
    .bind(show_id)
    .bind(start)
    .bind(end)
    .fetch_all(&state.pool)
    .await?;
    Ok(Json(EpisodesResponse { show, episodes }))
}

#[derive(FromRow)]
struct EpisodeRow {
    #[sqlx(flatten)]
    episode: Episode,
    show_id: i32,
}

/// `GET /api/shows/episodes/{episode_id}` — episode with chapters and parent show.
pub async fn get_episode(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
) -> Result<Json<EpisodeDetail>, AppError> {
    let row: EpisodeRow = sqlx::query_as(
        "SELECT id, aired_on, time_slot, s3_key, chapters, show_id
         FROM episodes WHERE id = $1 AND deleted = FALSE",
    )
    .bind(positive_id(episode_id)?)
    .fetch_optional(&state.pool)
    .await?
    .ok_or(AppError::NotFound("episode not found"))?;
    let show = show_detail(&state.pool, row.show_id).await?;
    Ok(Json(EpisodeDetail {
        episode: row.episode,
        show,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::authed_get;
    use axum::http::StatusCode;

    #[test]
    fn month_range_wraps_december() {
        assert_eq!(
            month_range(2025, 12),
            Some((
                NaiveDate::from_ymd_opt(2025, 12, 1).unwrap(),
                NaiveDate::from_ymd_opt(2026, 1, 1).unwrap()
            ))
        );
        assert_eq!(month_range(2025, 13), None);
        assert_eq!(month_range(2025, 0), None);
        assert_eq!(month_range(1800, 1), None);
    }

    #[tokio::test]
    async fn invalid_path_params_are_422() {
        for path in [
            "/api/shows/1/months/2026/13/episodes",
            "/api/shows/abc",
            "/api/shows/0",
            "/api/shows/1/recent-episodes?limit=51",
            "/api/shows/1/recent-episodes?limit=x",
        ] {
            let (status, _) = authed_get(path).await;
            assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{path}");
        }
    }

    #[tokio::test]
    async fn unknown_api_path_is_json_404() {
        let (status, body) = authed_get("/api/nope").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body, serde_json::json!({ "detail": "not found" }));
    }
}
