use axum::Json;
use axum::extract::rejection::{FormRejection, JsonRejection, PathRejection, QueryRejection};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use log::error;

/// API errors. Every variant renders as `{"detail": "..."}` so clients can read
/// one shape; internal errors hide their chain from the client and log it.
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("{0}")]
    Unauthorized(&'static str),

    #[error("{0}")]
    NotFound(&'static str),

    #[error("{0}")]
    Conflict(&'static str),

    #[error("range not satisfiable")]
    RangeNotSatisfiable,

    #[error("{0}")]
    Unprocessable(String),

    #[error(transparent)]
    BadGateway(anyhow::Error),

    #[error(transparent)]
    Internal(#[from] anyhow::Error),
}

impl AppError {
    pub fn unprocessable(msg: impl Into<String>) -> Self {
        Self::Unprocessable(msg.into())
    }
}

impl From<sqlx::Error> for AppError {
    fn from(e: sqlx::Error) -> Self {
        Self::Internal(anyhow::Error::new(e).context("database error"))
    }
}

impl From<PathRejection> for AppError {
    fn from(e: PathRejection) -> Self {
        Self::unprocessable(e.body_text())
    }
}

impl From<QueryRejection> for AppError {
    fn from(e: QueryRejection) -> Self {
        Self::unprocessable(e.body_text())
    }
}

impl From<JsonRejection> for AppError {
    fn from(e: JsonRejection) -> Self {
        Self::unprocessable(e.body_text())
    }
}

impl From<FormRejection> for AppError {
    fn from(e: FormRejection) -> Self {
        Self::unprocessable(e.body_text())
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, detail) = match self {
            AppError::Unauthorized(msg) => (StatusCode::UNAUTHORIZED, msg.to_string()),
            AppError::NotFound(msg) => (StatusCode::NOT_FOUND, msg.to_string()),
            AppError::Conflict(msg) => (StatusCode::CONFLICT, msg.to_string()),
            AppError::RangeNotSatisfiable => (
                StatusCode::RANGE_NOT_SATISFIABLE,
                "range not satisfiable".to_string(),
            ),
            AppError::Unprocessable(msg) => (StatusCode::UNPROCESSABLE_ENTITY, msg),
            AppError::BadGateway(err) => {
                error!("upstream error: {err:#}");
                (StatusCode::BAD_GATEWAY, "upstream error".to_string())
            }
            AppError::Internal(err) => {
                error!("internal error: {err:#}");
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "internal server error".to_string(),
                )
            }
        };
        (status, Json(serde_json::json!({ "detail": detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::to_bytes;

    async fn response_parts(error: AppError) -> (StatusCode, serde_json::Value) {
        let response = error.into_response();
        let status = response.status();
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        (status, serde_json::from_slice(&body).unwrap())
    }

    #[tokio::test]
    async fn client_errors_return_status_and_detail() {
        let cases = [
            (AppError::NotFound("show not found"), StatusCode::NOT_FOUND, "show not found"),
            (AppError::Conflict("session displaced"), StatusCode::CONFLICT, "session displaced"),
            (AppError::RangeNotSatisfiable, StatusCode::RANGE_NOT_SATISFIABLE, "range not satisfiable"),
            (AppError::Unauthorized("unauthenticated"), StatusCode::UNAUTHORIZED, "unauthenticated"),
            (AppError::unprocessable("bad limit"), StatusCode::UNPROCESSABLE_ENTITY, "bad limit"),
        ];
        for (error, expected_status, expected_detail) in cases {
            let (status, body) = response_parts(error).await;
            assert_eq!(status, expected_status);
            assert_eq!(body, serde_json::json!({ "detail": expected_detail }));
        }
    }

    #[tokio::test]
    async fn internal_errors_hide_error_chain_from_clients() {
        let (status, body) =
            response_parts(AppError::Internal(anyhow::anyhow!("database password leaked"))).await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(body, serde_json::json!({ "detail": "internal server error" }));

        let (status, body) =
            response_parts(AppError::BadGateway(anyhow::anyhow!("s3 secret in error"))).await;
        assert_eq!(status, StatusCode::BAD_GATEWAY);
        assert_eq!(body, serde_json::json!({ "detail": "upstream error" }));
    }
}
