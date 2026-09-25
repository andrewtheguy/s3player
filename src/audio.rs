//! Episode audio: the backend proxy stream (with `Range` forwarding) and the
//! presigned direct-fetch URL.

use std::time::Duration;

use anyhow::Context;
use aws_sdk_s3::config::http::HttpResponse;
use aws_sdk_s3::error::{DisplayErrorContext, SdkError};
use aws_sdk_s3::operation::get_object::GetObjectError;
use aws_sdk_s3::presigning::PresigningConfig;
use axum::Json;
use axum::body::Body;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::Response;
use futures::StreamExt;
use log::warn;
use serde::Serialize;
use tokio_util::io::ReaderStream;

use crate::error::AppError;
use crate::s3::{S3, error_code};
use crate::server::{ApiPath, AppState, positive_id};
use crate::shows::episode_s3_key;

const AUDIO_CHUNK_SIZE: usize = 64 * 1024;
const AUDIO_URL_EXPIRES_IN: u64 = 3600;

fn media_type_for_key(key: &str) -> &'static str {
    if key.ends_with(".m4a") {
        "audio/mp4"
    } else if key.ends_with(".ogg") {
        "audio/ogg"
    } else {
        "application/octet-stream"
    }
}

#[derive(Serialize)]
pub struct AudioUrlResponse {
    url: String,
    expires_in: u64,
}

/// `GET /api/shows/episodes/{episode_id}/audio_url` — a presigned S3 URL for
/// clients that fetch media directly. 404 if the episode is missing, 502 if
/// presigning fails.
pub async fn audio_url(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
) -> Result<Json<AudioUrlResponse>, AppError> {
    let key = episode_s3_key(&state.pool, positive_id(episode_id)?).await?;
    Ok(Json(presign_audio_url(&state.s3, &key).await?))
}

async fn presign_audio_url(s3: &S3, key: &str) -> Result<AudioUrlResponse, AppError> {
    let config = PresigningConfig::expires_in(Duration::from_secs(AUDIO_URL_EXPIRES_IN))
        .context("invalid presigning config")?;
    let presigned = s3
        .client
        .get_object()
        .bucket(&s3.bucket)
        .key(key)
        .presigned(config)
        .await
        .map_err(|e| AppError::BadGateway(anyhow::anyhow!("presign {key}: {}", DisplayErrorContext(e))))?;
    Ok(AudioUrlResponse {
        url: presigned.uri().to_string(),
        expires_in: AUDIO_URL_EXPIRES_IN,
    })
}

fn classify_get_error(key: &str, e: SdkError<GetObjectError, HttpResponse>) -> AppError {
    match error_code(&e).as_deref() {
        Some("InvalidRange" | "InvalidArgument" | "416") => AppError::RangeNotSatisfiable,
        Some("NoSuchKey" | "NotFound" | "404") => AppError::NotFound("audio not found"),
        _ => AppError::BadGateway(anyhow::anyhow!("GetObject {key}: {}", DisplayErrorContext(e))),
    }
}

/// `GET /api/shows/episodes/{episode_id}/audio` — proxy the audio bytes from
/// S3. Forwards `Range`; answers 206 with `Content-Range` when S3 does,
/// otherwise 200. 404 if the episode or object is missing, 416 for an
/// unsatisfiable range, 502 for other upstream failures.
pub async fn stream_audio(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    let key = episode_s3_key(&state.pool, positive_id(episode_id)?).await?;
    let range = headers.get(header::RANGE).and_then(|v| v.to_str().ok());
    proxy_object(&state.s3, key, range).await
}

async fn proxy_object(s3: &S3, key: String, range: Option<&str>) -> Result<Response, AppError> {
    let output = s3
        .client
        .get_object()
        .bucket(&s3.bucket)
        .key(&key)
        .set_range(range.map(str::to_string))
        .send()
        .await
        .map_err(|e| classify_get_error(&key, e))?;

    let mut builder = Response::builder()
        .header(header::CONTENT_TYPE, media_type_for_key(&key))
        .header(header::ACCEPT_RANGES, "bytes");
    if let Some(len) = output.content_length() {
        builder = builder.header(header::CONTENT_LENGTH, len);
    }
    builder = match output.content_range() {
        Some(content_range) => builder
            .status(StatusCode::PARTIAL_CONTENT)
            .header(header::CONTENT_RANGE, content_range),
        None => builder.status(StatusCode::OK),
    };

    // A broken upstream stream aborts the response (the client sees a
    // truncated body); log where it broke. A client hanging up mid-playback
    // just drops the stream and is not logged.
    let mut sent: u64 = 0;
    let stream = ReaderStream::with_capacity(output.body.into_async_read(), AUDIO_CHUNK_SIZE)
        .inspect(move |chunk| match chunk {
            Ok(bytes) => sent += bytes.len() as u64,
            Err(e) => warn!("audio stream for {key} failed after {sent} bytes: {e}"),
        });
    builder
        .body(Body::from_stream(stream))
        .context("failed to build audio response")
        .map_err(AppError::from)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{mock_s3, offline_s3};
    use aws_sdk_s3::error::ErrorMetadata;
    use aws_sdk_s3::operation::get_object::GetObjectOutput;
    use aws_sdk_s3::primitives::{ByteStream, SdkBody};
    use aws_sdk_s3::types::error::NoSuchKey;
    use aws_smithy_mocks::{mock, mock_client};
    use axum::body::to_bytes;
    use axum::response::IntoResponse;

    #[test]
    fn media_type_follows_extension() {
        assert_eq!(media_type_for_key("shows/a/b.m4a"), "audio/mp4");
        assert_eq!(media_type_for_key("shows/a/b.ogg"), "audio/ogg");
        assert_eq!(media_type_for_key("shows/a/b.mp3"), "application/octet-stream");
    }

    #[tokio::test]
    async fn full_object_is_200_with_length() {
        let get = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| r.range().is_none() && r.key() == Some("shows/a/b.m4a"))
            .then_output(|| {
                GetObjectOutput::builder()
                    .body(ByteStream::from_static(b"0123456789"))
                    .content_length(10)
                    .build()
            });
        let s3 = mock_s3(mock_client!(aws_sdk_s3, [&get]));
        let response = proxy_object(&s3, "shows/a/b.m4a".to_string(), None).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "audio/mp4");
        assert_eq!(response.headers()[header::ACCEPT_RANGES], "bytes");
        assert_eq!(response.headers()[header::CONTENT_LENGTH], "10");
        assert!(response.headers().get(header::CONTENT_RANGE).is_none());
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(body.as_ref(), b"0123456789");
    }

    #[tokio::test]
    async fn range_is_forwarded_and_answered_206() {
        let get = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| r.range() == Some("bytes=2-4"))
            .then_output(|| {
                GetObjectOutput::builder()
                    .body(ByteStream::from_static(b"234"))
                    .content_length(3)
                    .content_range("bytes 2-4/10")
                    .build()
            });
        let s3 = mock_s3(mock_client!(aws_sdk_s3, [&get]));
        let response = proxy_object(&s3, "x.ogg".to_string(), Some("bytes=2-4")).await.unwrap();
        assert_eq!(response.status(), StatusCode::PARTIAL_CONTENT);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "audio/ogg");
        assert_eq!(response.headers()[header::CONTENT_RANGE], "bytes 2-4/10");
        assert_eq!(response.headers()[header::CONTENT_LENGTH], "3");
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(body.as_ref(), b"234");
    }

    async fn proxy_error_status(rule: aws_smithy_mocks::Rule) -> StatusCode {
        let s3 = mock_s3(mock_client!(aws_sdk_s3, [&rule]));
        let Err(error) = proxy_object(&s3, "k.m4a".to_string(), Some("bytes=0-")).await else {
            panic!("expected an error");
        };
        error.into_response().status()
    }

    #[tokio::test]
    async fn s3_errors_map_to_client_statuses() {
        let coded = |code: &'static str| {
            mock!(aws_sdk_s3::Client::get_object)
                .then_error(move || GetObjectError::generic(ErrorMetadata::builder().code(code).build()))
        };
        assert_eq!(proxy_error_status(coded("InvalidRange")).await, StatusCode::RANGE_NOT_SATISFIABLE);
        assert_eq!(proxy_error_status(coded("InvalidArgument")).await, StatusCode::RANGE_NOT_SATISFIABLE);
        assert_eq!(proxy_error_status(coded("AccessDenied")).await, StatusCode::BAD_GATEWAY);
        let no_such_key = mock!(aws_sdk_s3::Client::get_object).then_error(|| {
            GetObjectError::NoSuchKey(
                NoSuchKey::builder()
                    .meta(ErrorMetadata::builder().code("NoSuchKey").build())
                    .build(),
            )
        });
        assert_eq!(proxy_error_status(no_such_key).await, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn bodyless_error_responses_map_by_status() {
        let raw = |status: u16| {
            mock!(aws_sdk_s3::Client::get_object)
                .then_http_response(move || HttpResponse::new(status.try_into().unwrap(), SdkBody::empty()))
        };
        assert_eq!(proxy_error_status(raw(416)).await, StatusCode::RANGE_NOT_SATISFIABLE);
        assert_eq!(proxy_error_status(raw(404)).await, StatusCode::NOT_FOUND);
        assert_eq!(proxy_error_status(raw(403)).await, StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn presigned_url_is_an_hour_long_get() {
        let response = presign_audio_url(&offline_s3(), "shows/r/a b.m4a").await.unwrap();
        assert_eq!(response.expires_in, 3600);
        assert!(
            response.url.starts_with("http://s3.invalid:9000/b/shows/r/a%20b.m4a?"),
            "{}",
            response.url
        );
        assert!(response.url.contains("X-Amz-Expires=3600"), "{}", response.url);
        assert!(response.url.contains("X-Amz-Signature="), "{}", response.url);
    }
}
