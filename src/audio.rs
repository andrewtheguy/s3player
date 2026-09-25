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
use crate::s3::error_code;
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
    let config = PresigningConfig::expires_in(Duration::from_secs(AUDIO_URL_EXPIRES_IN))
        .context("invalid presigning config")?;
    let presigned = state
        .s3
        .client
        .get_object()
        .bucket(&state.s3.bucket)
        .key(&key)
        .presigned(config)
        .await
        .map_err(|e| AppError::BadGateway(anyhow::anyhow!("presign {key}: {}", DisplayErrorContext(e))))?;
    Ok(Json(AudioUrlResponse {
        url: presigned.uri().to_string(),
        expires_in: AUDIO_URL_EXPIRES_IN,
    }))
}

fn classify_get_error(key: &str, e: SdkError<GetObjectError, HttpResponse>) -> AppError {
    match error_code(&e).as_deref() {
        Some("InvalidRange" | "InvalidArgument" | "416") => AppError::RangeNotSatisfiable,
        Some("NoSuchKey" | "404") => AppError::NotFound("audio not found"),
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
    let output = state
        .s3
        .client
        .get_object()
        .bucket(&state.s3.bucket)
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

    #[test]
    fn media_type_follows_extension() {
        assert_eq!(media_type_for_key("shows/a/b.m4a"), "audio/mp4");
        assert_eq!(media_type_for_key("shows/a/b.ogg"), "audio/ogg");
        assert_eq!(media_type_for_key("shows/a/b.mp3"), "application/octet-stream");
    }
}
