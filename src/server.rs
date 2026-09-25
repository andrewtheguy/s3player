use std::sync::Arc;

use anyhow::Context;
use axum::extract::{FromRequest, FromRequestParts};
use axum::routing::{any, get, post};
use axum::{Router, middleware};
use log::info;
use sqlx::PgPool;

use crate::s3::S3;
use crate::error::AppError;
use crate::{assets, audio, auth, player, shows, summaries};

#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,
    pub s3: S3,
    pub site_password: Arc<str>,
    /// `auth::expected_token(site_password)`, computed once.
    pub auth_token: Arc<str>,
}

impl AppState {
    pub fn new(pool: PgPool, s3: S3, site_password: &str) -> Self {
        Self {
            pool,
            s3,
            site_password: site_password.into(),
            auth_token: auth::expected_token(site_password).into(),
        }
    }
}

/// `axum::extract::Path` with a JSON 422 rejection.
#[derive(FromRequestParts)]
#[from_request(via(axum::extract::Path), rejection(AppError))]
pub struct ApiPath<T>(pub T);

/// `axum::extract::Query` with a JSON 422 rejection.
#[derive(FromRequestParts)]
#[from_request(via(axum::extract::Query), rejection(AppError))]
pub struct ApiQuery<T>(pub T);

/// `axum::Json` with a JSON 422 rejection.
#[derive(FromRequest)]
#[from_request(via(axum::Json), rejection(AppError))]
pub struct ApiJson<T>(pub T);

/// `axum::Form` with a JSON 422 rejection.
#[derive(FromRequest)]
#[from_request(via(axum::Form), rejection(AppError))]
pub struct ApiForm<T>(pub T);

/// Reject a database id below 1 the way a malformed path is rejected.
pub fn positive_id(id: i32) -> Result<i32, AppError> {
    if id < 1 {
        return Err(AppError::unprocessable("id must be >= 1"));
    }
    Ok(id)
}

/// Validate an optional `limit` query parameter against `1..=50`.
pub fn limit_param(limit: Option<i64>, default: i64) -> Result<i64, AppError> {
    let limit = limit.unwrap_or(default);
    if !(1..=50).contains(&limit) {
        return Err(AppError::unprocessable("limit must be between 1 and 50"));
    }
    Ok(limit)
}

async fn api_not_found() -> AppError {
    AppError::NotFound("not found")
}

pub fn router(state: AppState) -> Router {
    Router::new()
        // Internal: HTML login form and browser auth cookie.
        .route("/login", get(auth::login_page).post(auth::login_submit))
        // Public JSON API.
        .route("/api/auth/login", post(auth::api_login))
        .route("/api/shows/stations", get(shows::list_stations))
        .route("/api/shows/stations/{station}/shows", get(shows::list_shows))
        .route("/api/shows/favorites", get(shows::list_favorites))
        .route("/api/shows/{show_id}", get(shows::get_show))
        .route(
            "/api/shows/{show_id}/favorite",
            post(shows::add_favorite).delete(shows::remove_favorite),
        )
        .route("/api/shows/{show_id}/recent-episodes", get(shows::list_recent_episodes))
        .route("/api/shows/{show_id}/months", get(shows::list_months))
        .route(
            "/api/shows/{show_id}/months/{year}/{month}/episodes",
            get(shows::list_episodes),
        )
        .route("/api/shows/episodes/{episode_id}", get(shows::get_episode))
        .route("/api/shows/episodes/{episode_id}/audio_url", get(audio::audio_url))
        .route("/api/shows/episodes/{episode_id}/audio", get(audio::stream_audio))
        .route(
            "/api/shows/episodes/{episode_id}/chapter_summaries",
            get(summaries::list_chapter_summaries),
        )
        .route("/api/player/session/claim", post(player::claim_session))
        .route("/api/player/session/validate", post(player::validate_session))
        .route(
            "/api/player/episodes/{episode_id}/progress",
            get(player::get_progress)
                .post(player::save_progress)
                .delete(player::delete_progress),
        )
        .route("/api/player/recent-completed", get(player::list_recent_completed))
        .route("/api/player/in-progress", get(player::list_in_progress))
        // Unknown API paths are JSON 404s, not the SPA.
        .route("/api/{*rest}", any(api_not_found))
        .fallback(assets::static_handler)
        .layer(middleware::from_fn_with_state(state.clone(), auth::site_password_gate))
        .with_state(state)
}

pub async fn serve(state: AppState, host: &str, port: u16) -> anyhow::Result<()> {
    let addr = if host.contains(':') {
        format!("[{host}]:{port}")
    } else {
        format!("{host}:{port}")
    };
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .with_context(|| format!("failed to bind to {addr}"))?;
    info!("listening on http://{addr}");
    axum::serve(listener, router(state))
        .with_graceful_shutdown(shutdown_signal())
        .await
        .context("server error")
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut sig) => {
                sig.recv().await;
            }
            Err(_) => std::future::pending::<()>().await,
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! {
        () = ctrl_c => {}
        () = terminate => {}
    }
    info!("shutting down");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn positive_id_rejects_zero_and_negatives() {
        assert_eq!(positive_id(1).unwrap(), 1);
        assert!(matches!(positive_id(0), Err(AppError::Unprocessable(_))));
        assert!(matches!(positive_id(-5), Err(AppError::Unprocessable(_))));
    }

    #[test]
    fn limit_param_defaults_and_bounds() {
        assert_eq!(limit_param(None, 20).unwrap(), 20);
        assert_eq!(limit_param(Some(1), 20).unwrap(), 1);
        assert_eq!(limit_param(Some(50), 20).unwrap(), 50);
        for bad in [0, 51, -1] {
            assert!(limit_param(Some(bad), 20).is_err(), "{bad}");
        }
    }
}
