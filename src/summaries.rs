//! Per-chapter markdown summaries stored in S3 beside the audio tree:
//! `shows/<...>/<basename>.m4a` → `summaries/<...>/<basename>_summary/chapter_NN.md`.

use axum::Json;
use axum::extract::State;
use aws_sdk_s3::error::DisplayErrorContext;
use futures::future::join_all;
use log::warn;
use serde::Serialize;

use crate::error::AppError;
use crate::s3::{S3, error_code};
use crate::server::{ApiPath, AppState, positive_id};
use crate::shows::episode_s3_key;

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct ChapterSummary {
    /// The `NN` of `chapter_NN.md`: 1-based under the canonical naming.
    index: u32,
    content: String,
}

#[derive(Serialize)]
pub struct ChapterSummariesResponse {
    summaries: Vec<ChapterSummary>,
}

/// The summaries directory for an audio key, or `None` unless the key is
/// `shows/…​.m4a`.
pub fn derive_summary_prefix(audio_key: &str) -> Option<String> {
    let rest = audio_key.strip_prefix("shows/")?.strip_suffix(".m4a")?;
    Some(format!("summaries/{rest}_summary/"))
}

/// The index of a `chapter_NN.md` object key.
fn chapter_index(key: &str) -> Option<u32> {
    let basename = key.rsplit('/').next()?;
    let digits = basename.strip_prefix("chapter_")?.strip_suffix(".md")?;
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

/// Every summary for the audio key, sorted by index. Empty when the key maps
/// to no prefix or nothing is there. A file that fails to fetch or isn't
/// UTF-8 is skipped; a failed listing is an error.
pub async fn fetch_chapter_summaries(s3: &S3, audio_key: &str) -> anyhow::Result<Vec<ChapterSummary>> {
    let Some(prefix) = derive_summary_prefix(audio_key) else {
        return Ok(Vec::new());
    };
    let keys = match s3.list_keys(&prefix).await {
        Ok(keys) => keys,
        Err(e) => {
            if matches!(error_code(&e).as_deref(), Some("NoSuchKey" | "NoSuchBucket" | "NotFound" | "404")) {
                return Ok(Vec::new());
            }
            anyhow::bail!("ListObjectsV2 {prefix}: {}", DisplayErrorContext(e));
        }
    };

    let mut indexed: Vec<(u32, String)> = keys
        .into_iter()
        .filter_map(|k| chapter_index(&k).map(|i| (i, k)))
        .collect();
    indexed.sort_by_key(|(i, _)| *i);

    let fetches = indexed.into_iter().map(|(index, key)| async move {
        let bytes = match s3.get_bytes(&key).await {
            Ok(bytes) => bytes,
            Err(e) => {
                warn!("chapter summary fetch failed for {key}: {e:#}");
                return None;
            }
        };
        match String::from_utf8(bytes) {
            Ok(content) => Some(ChapterSummary { index, content }),
            Err(e) => {
                warn!("chapter summary not utf-8 for {key}: {e}");
                None
            }
        }
    });
    Ok(join_all(fetches).await.into_iter().flatten().collect())
}

/// `GET /api/shows/episodes/{episode_id}/chapter_summaries` — 404 if the
/// episode is missing, 502 if listing the summaries fails.
pub async fn list_chapter_summaries(
    State(state): State<AppState>,
    ApiPath(episode_id): ApiPath<i32>,
) -> Result<Json<ChapterSummariesResponse>, AppError> {
    let key = episode_s3_key(&state.pool, positive_id(episode_id)?).await?;
    let summaries = fetch_chapter_summaries(&state.s3, &key)
        .await
        .map_err(AppError::BadGateway)?;
    Ok(Json(ChapterSummariesResponse { summaries }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use aws_sdk_s3::operation::get_object::GetObjectOutput;
    use aws_sdk_s3::operation::list_objects_v2::ListObjectsV2Output;
    use aws_sdk_s3::primitives::ByteStream;
    use aws_sdk_s3::types::Object;
    use aws_smithy_mocks::{RuleMode, mock, mock_client};

    fn summary(index: u32, content: &str) -> ChapterSummary {
        ChapterSummary {
            index,
            content: content.to_string(),
        }
    }

    fn listing(keys: &[String]) -> ListObjectsV2Output {
        ListObjectsV2Output::builder()
            .set_contents(Some(keys.iter().map(|k| Object::builder().key(k).build()).collect()))
            .build()
    }

    #[test]
    fn derive_summary_prefix_maps_shows_m4a_keys() {
        assert_eq!(
            derive_summary_prefix(
                "shows/rthk-radio1/2026/03/22/20260322_0600_0700_Beautiful_Sunday_(與第二台聯播).m4a"
            )
            .as_deref(),
            Some("summaries/rthk-radio1/2026/03/22/20260322_0600_0700_Beautiful_Sunday_(與第二台聯播)_summary/")
        );
        assert_eq!(derive_summary_prefix("shows/x/y.m4a").as_deref(), Some("summaries/x/y_summary/"));
        assert_eq!(derive_summary_prefix("other/x.m4a"), None);
        assert_eq!(derive_summary_prefix("shows/x.mp3"), None);
    }

    #[test]
    fn chapter_index_parses_only_chapter_files() {
        assert_eq!(chapter_index("p/chapter_01.md"), Some(1));
        assert_eq!(chapter_index("p/chapter_10.md"), Some(10));
        assert_eq!(chapter_index("p/chapter_aa.md"), None);
        assert_eq!(chapter_index("p/chapter_.md"), None);
        assert_eq!(chapter_index("p/index.md"), None);
        assert_eq!(chapter_index("p/README"), None);
    }

    #[tokio::test]
    async fn sorts_by_index_skips_non_chapter_and_failed_fetches() {
        let prefix = "summaries/r/y_summary/";
        let keys: Vec<String> = ["chapter_02.md", "chapter_10.md", "chapter_01.md", "chapter_03.md", "index.md", "chapter_aa.md"]
            .iter()
            .map(|n| format!("{prefix}{n}"))
            .collect();
        let list = mock!(aws_sdk_s3::Client::list_objects_v2).then_output(move || listing(&keys));
        let get = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| !r.key().unwrap().ends_with("chapter_03.md"))
            .then_output(|| {
                GetObjectOutput::builder()
                    .body(ByteStream::from_static(b"body"))
                    .build()
            });
        let get_fail = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| r.key().unwrap().ends_with("chapter_03.md"))
            .then_error(|| aws_sdk_s3::operation::get_object::GetObjectError::unhandled("boom"));
        let client = mock_client!(aws_sdk_s3, RuleMode::MatchAny, [&list, &get, &get_fail]);
        let s3 = S3 {
            client,
            bucket: "b".to_string(),
        };

        let result = fetch_chapter_summaries(&s3, "shows/r/y.m4a").await.unwrap();
        assert_eq!(result, vec![summary(1, "body"), summary(2, "body"), summary(10, "body")]);
    }

    #[tokio::test]
    async fn unmappable_key_is_empty_without_listing() {
        let client = mock_client!(aws_sdk_s3, []);
        let s3 = S3 {
            client,
            bucket: "b".to_string(),
        };
        assert_eq!(fetch_chapter_summaries(&s3, "notshows/x.mp3").await.unwrap(), vec![]);
    }

    #[tokio::test]
    async fn listing_errors() {
        use aws_sdk_s3::operation::list_objects_v2::ListObjectsV2Error;
        use aws_sdk_s3::error::ErrorMetadata;
        use aws_sdk_s3::types::error::NoSuchBucket;

        let missing = mock!(aws_sdk_s3::Client::list_objects_v2)
            .then_error(|| {
                ListObjectsV2Error::NoSuchBucket(
                    NoSuchBucket::builder()
                        .meta(ErrorMetadata::builder().code("NoSuchBucket").build())
                        .build(),
                )
            });
        let s3 = S3 {
            client: mock_client!(aws_sdk_s3, [&missing]),
            bucket: "b".to_string(),
        };
        assert_eq!(fetch_chapter_summaries(&s3, "shows/r/y.m4a").await.unwrap(), vec![]);

        // A bodyless 404, which the SDK codes as "NotFound".
        let bare_404 = mock!(aws_sdk_s3::Client::list_objects_v2).then_http_response(|| {
            aws_sdk_s3::config::http::HttpResponse::new(
                404.try_into().unwrap(),
                aws_sdk_s3::primitives::SdkBody::empty(),
            )
        });
        let s3 = S3 {
            client: mock_client!(aws_sdk_s3, [&bare_404]),
            bucket: "b".to_string(),
        };
        assert_eq!(fetch_chapter_summaries(&s3, "shows/r/y.m4a").await.unwrap(), vec![]);

        let denied = mock!(aws_sdk_s3::Client::list_objects_v2)
            .then_error(|| ListObjectsV2Error::unhandled("AccessDenied"));
        let s3 = S3 {
            client: mock_client!(aws_sdk_s3, [&denied]),
            bucket: "b".to_string(),
        };
        assert!(fetch_chapter_summaries(&s3, "shows/r/y.m4a").await.is_err());
    }
}
