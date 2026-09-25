//! Router-level test helpers. The pool is lazy and never connects, so only
//! requests answered before any query (auth, validation) are testable here.

use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use axum::response::Response;
use sqlx::postgres::PgPoolOptions;
use tower::ServiceExt;

use crate::auth::{COOKIE_NAME, expected_token};
use crate::s3::S3;
use crate::server::{AppState, router};

pub const PASSWORD: &str = "test-password";

pub fn test_state() -> AppState {
    let pool = PgPoolOptions::new()
        .connect_lazy("postgres://test@localhost:5432/test")
        .unwrap();
    let config = aws_sdk_s3::Config::builder()
        .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
        .region(aws_sdk_s3::config::Region::new("us-east-1"))
        .build();
    let s3 = S3 {
        client: aws_sdk_s3::Client::from_conf(config),
        bucket: "test-bucket".to_string(),
    };
    AppState::new(pool, s3, PASSWORD)
}

pub async fn body_json(response: Response) -> serde_json::Value {
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    serde_json::from_slice(&body).unwrap()
}

/// Send `req` with the auth cookie set.
pub async fn authed_request(mut req: Request<Body>) -> Response {
    req.headers_mut().insert(
        header::COOKIE,
        format!("{COOKIE_NAME}={}", expected_token(PASSWORD)).parse().unwrap(),
    );
    router(test_state()).oneshot(req).await.unwrap()
}

pub async fn authed_get(path: &str) -> (StatusCode, serde_json::Value) {
    let response = authed_request(Request::get(path).body(Body::empty()).unwrap()).await;
    let status = response.status();
    (status, body_json(response).await)
}
