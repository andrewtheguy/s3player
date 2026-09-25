//! One-shot S3 → Postgres indexer. Each `{audio_key}.metadata.json` sidecar
//! under `shows/<station>/` that has its audio file beside it becomes an
//! episode; keys no longer seen are soft-deleted and reappearing ones restored.
//! Safe to re-run: every write is an upsert or a conditional update.

use std::collections::{HashMap, HashSet};

use anyhow::Context;
use aws_sdk_s3::error::DisplayErrorContext;
use log::{info, warn};
use serde_json::Value;
use sqlx::PgPool;
use sqlx::types::Json;

use crate::s3::S3;
use crate::show_metadata::{ShowMetadata, ShowMetadataError, extract_show_metadata, normalize_chapters};

const SHOWS_ROOT_PREFIX: &str = "shows/";
const METADATA_SUFFIX: &str = ".metadata.json";
const AUDIO_EXTENSIONS: &[&str] = &[".m4a", ".ogg"];

const SHOW_UPSERT: &str = "
INSERT INTO shows (station, name) VALUES ($1, $2)
ON CONFLICT (station, name) DO UPDATE SET name = EXCLUDED.name
RETURNING id";

const EPISODE_INSERT: &str = "
INSERT INTO episodes (s3_key, show_id, aired_on, time_slot)
VALUES ($1, $2, $3, $4)
ON CONFLICT (s3_key) DO NOTHING
RETURNING id";

const EPISODE_UPSERT: &str = "
INSERT INTO episodes (s3_key, show_id, aired_on, time_slot)
VALUES ($1, $2, $3, $4)
ON CONFLICT (s3_key) DO UPDATE SET
    show_id = EXCLUDED.show_id,
    aired_on = EXCLUDED.aired_on,
    time_slot = EXCLUDED.time_slot
RETURNING id, (xmax = 0) AS inserted";

const EPISODE_SET_CHAPTERS: &str = "UPDATE episodes SET chapters = $1 WHERE id = $2";

const EPISODE_SOFT_DELETE_MISSING: &str = "
UPDATE episodes SET deleted = TRUE
WHERE deleted = FALSE AND s3_key <> ALL($1::text[])";

const EPISODE_RESTORE_PRESENT: &str = "
UPDATE episodes SET deleted = FALSE
WHERE deleted = TRUE AND s3_key = ANY($1::text[])";

#[derive(Default)]
struct Stats {
    scanned: usize,
    skipped_non_metadata: usize,
    skipped_missing_audio: usize,
    skipped_invalid_metadata: usize,
    skipped_missing_show_date: usize,
    inserted: usize,
    updated: usize,
    already_present: usize,
    chapters_filled: usize,
    chapters_cleared: usize,
    soft_deleted: u64,
    restored: u64,
}

/// `(prefix, station)` for each `shows/<station>/` directory, sorted.
async fn list_station_prefixes(s3: &S3) -> anyhow::Result<Vec<(String, String)>> {
    let mut pages = s3
        .client
        .list_objects_v2()
        .bucket(&s3.bucket)
        .prefix(SHOWS_ROOT_PREFIX)
        .delimiter("/")
        .into_paginator()
        .send();
    let mut results = Vec::new();
    while let Some(page) = pages.next().await {
        let page = page.map_err(|e| anyhow::anyhow!("ListObjectsV2 {SHOWS_ROOT_PREFIX}: {}", DisplayErrorContext(e)))?;
        for prefix in page.common_prefixes().iter().filter_map(|p| p.prefix()) {
            let station = prefix
                .strip_prefix(SHOWS_ROOT_PREFIX)
                .unwrap_or(prefix)
                .trim_end_matches('/');
            if !station.is_empty() {
                results.push((prefix.to_string(), station.to_string()));
            }
        }
    }
    results.sort();
    Ok(results)
}

/// The sidecar as a JSON object, or `None` (logged) if it can't be used.
async fn fetch_metadata(s3: &S3, key: &str) -> Option<Value> {
    let body = match s3.get_bytes(key).await {
        Ok(body) => body,
        Err(e) => {
            warn!("metadata fetch failed for {key}: {e:#}");
            return None;
        }
    };
    match serde_json::from_slice::<Value>(&body) {
        Ok(v) if v.is_object() => Some(v),
        Ok(_) => {
            warn!("metadata top-level is not an object for {key}");
            None
        }
        Err(e) => {
            warn!("metadata is not valid JSON for {key}: {e}");
            None
        }
    }
}

/// Upsert the show and the episode. `Some((episode_id, inserted))` when the
/// row was written, `None` when it already existed and `overwrite` is off.
async fn index_one(
    pool: &PgPool,
    show_cache: &mut HashMap<(String, String), i32>,
    station: &str,
    s3_key: &str,
    meta: &ShowMetadata,
    overwrite: bool,
) -> anyhow::Result<Option<(i32, bool)>> {
    let cache_key = (station.to_string(), meta.name.clone());
    let show_id = match show_cache.get(&cache_key) {
        Some(id) => *id,
        None => {
            let id: i32 = sqlx::query_scalar(SHOW_UPSERT)
                .bind(station)
                .bind(&meta.name)
                .fetch_one(pool)
                .await
                .with_context(|| format!("shows upsert failed for station={station:?} show={:?}", meta.name))?;
            show_cache.insert(cache_key, id);
            id
        }
    };
    if overwrite {
        let row: (i32, bool) = sqlx::query_as(EPISODE_UPSERT)
            .bind(s3_key)
            .bind(show_id)
            .bind(meta.aired_on)
            .bind(&meta.time_slot)
            .fetch_one(pool)
            .await
            .with_context(|| format!("episode upsert failed for {s3_key}"))?;
        return Ok(Some(row));
    }
    let new_id: Option<i32> = sqlx::query_scalar(EPISODE_INSERT)
        .bind(s3_key)
        .bind(show_id)
        .bind(meta.aired_on)
        .bind(&meta.time_slot)
        .fetch_optional(pool)
        .await
        .with_context(|| format!("episode insert failed for {s3_key}"))?;
    Ok(new_id.map(|id| (id, true)))
}

pub async fn run(pool: &PgPool, s3: &S3, overwrite: bool) -> anyhow::Result<()> {
    let mut stats = Stats::default();
    let mut present_keys: HashSet<String> = HashSet::new();
    let mut show_cache = HashMap::new();

    let stations = list_station_prefixes(s3).await?;
    if stations.is_empty() {
        warn!("no stations discovered under {SHOWS_ROOT_PREFIX}");
    } else {
        let names: Vec<&str> = stations.iter().map(|(_, s)| s.as_str()).collect();
        info!(
            "discovered {} station(s) under {SHOWS_ROOT_PREFIX}: {}",
            stations.len(),
            names.join(", ")
        );
    }

    for (prefix, station) in &stations {
        info!("scanning {prefix} (station={station})");
        let keys = s3
            .list_keys(prefix)
            .await
            .map_err(|e| anyhow::anyhow!("ListObjectsV2 {prefix}: {}", DisplayErrorContext(e)))?;
        let audio_keys: HashSet<&str> = keys
            .iter()
            .filter(|k| AUDIO_EXTENSIONS.iter().any(|ext| k.ends_with(ext)))
            .map(String::as_str)
            .collect();
        let metadata_keys: Vec<&str> = keys
            .iter()
            .filter(|k| k.ends_with(METADATA_SUFFIX))
            .map(String::as_str)
            .collect();
        stats.scanned += keys.len();
        stats.skipped_non_metadata += keys.len() - metadata_keys.len();
        info!(
            "found {} keys under {prefix} ({} metadata sidecars, {} audio files)",
            keys.len(),
            metadata_keys.len(),
            audio_keys.len()
        );

        let meta_total = metadata_keys.len();
        for (i, metadata_key) in metadata_keys.iter().enumerate() {
            let progress = format!("[{}/{meta_total}]", i + 1);
            let audio_key = &metadata_key[..metadata_key.len() - METADATA_SUFFIX.len()];
            if !audio_keys.contains(audio_key) {
                stats.skipped_missing_audio += 1;
                warn!("{progress} sidecar without audio file: {metadata_key}");
                continue;
            }
            let Some(meta) = fetch_metadata(s3, metadata_key).await else {
                stats.skipped_invalid_metadata += 1;
                continue;
            };
            let show = match extract_show_metadata(&meta) {
                Ok(show) => show,
                Err(ShowMetadataError::MissingDate) => {
                    stats.skipped_missing_show_date += 1;
                    info!("{progress} skipping (no show.date): {metadata_key}");
                    continue;
                }
                Err(e) => {
                    stats.skipped_invalid_metadata += 1;
                    warn!("{progress} invalid show metadata ({e}): {metadata_key}");
                    continue;
                }
            };
            present_keys.insert(audio_key.to_string());
            let Some((episode_id, was_inserted)) =
                index_one(pool, &mut show_cache, station, audio_key, &show, overwrite).await?
            else {
                stats.already_present += 1;
                info!("{progress} already indexed: {audio_key}");
                continue;
            };
            let verb = if was_inserted {
                stats.inserted += 1;
                "inserted"
            } else {
                stats.updated += 1;
                "updated"
            };
            if let Some(raw_chapters) = meta.get("chapters").and_then(Value::as_array) {
                sqlx::query(EPISODE_SET_CHAPTERS)
                    .bind(Json(normalize_chapters(raw_chapters)))
                    .bind(episode_id)
                    .execute(pool)
                    .await
                    .with_context(|| format!("failed to set chapters for {audio_key}"))?;
                stats.chapters_filled += 1;
                info!("{progress} {verb} with chapters: {audio_key}");
            } else {
                warn!("{progress} metadata chapters missing or not a list: {metadata_key}");
                if !was_inserted {
                    sqlx::query(EPISODE_SET_CHAPTERS)
                        .bind(None::<Json<()>>)
                        .bind(episode_id)
                        .execute(pool)
                        .await
                        .with_context(|| format!("failed to clear chapters for {audio_key}"))?;
                    stats.chapters_cleared += 1;
                }
                info!("{progress} {verb} (no chapters): {audio_key}");
            }
        }
    }

    let present: Vec<String> = present_keys.into_iter().collect();
    stats.soft_deleted = sqlx::query(EPISODE_SOFT_DELETE_MISSING)
        .bind(&present)
        .execute(pool)
        .await
        .context("failed to soft-delete missing episodes")?
        .rows_affected();
    stats.restored = sqlx::query(EPISODE_RESTORE_PRESENT)
        .bind(&present)
        .execute(pool)
        .await
        .context("failed to restore reappeared episodes")?
        .rows_affected();

    let Stats {
        scanned,
        skipped_non_metadata,
        skipped_missing_audio,
        skipped_invalid_metadata,
        skipped_missing_show_date,
        inserted,
        updated,
        already_present,
        chapters_filled,
        chapters_cleared,
        soft_deleted,
        restored,
    } = stats;
    info!(
        "done: overwrite={overwrite} scanned={scanned} inserted={inserted} updated={updated} \
         already_present={already_present} skipped_invalid_metadata={skipped_invalid_metadata} \
         skipped_missing_show_date={skipped_missing_show_date} skipped_non_metadata={skipped_non_metadata} \
         skipped_missing_audio={skipped_missing_audio} chapters_filled={chapters_filled} \
         chapters_cleared={chapters_cleared} soft_deleted={soft_deleted} restored={restored}"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::mock_s3;
    use aws_sdk_s3::operation::get_object::{GetObjectError, GetObjectOutput};
    use aws_sdk_s3::operation::list_objects_v2::ListObjectsV2Output;
    use aws_sdk_s3::primitives::ByteStream;
    use aws_sdk_s3::types::CommonPrefix;
    use aws_smithy_mocks::{RuleMode, mock, mock_client};

    #[tokio::test]
    async fn station_prefixes_are_sorted_directories_under_shows() {
        let list = mock!(aws_sdk_s3::Client::list_objects_v2)
            .match_requests(|r| r.prefix() == Some("shows/") && r.delimiter() == Some("/"))
            .then_output(|| {
                ListObjectsV2Output::builder()
                    .set_common_prefixes(Some(
                        ["shows/rthk-radio2/", "shows/rthk-radio1/", "shows//"]
                            .into_iter()
                            .map(|p| CommonPrefix::builder().prefix(p).build())
                            .collect(),
                    ))
                    .build()
            });
        let s3 = mock_s3(mock_client!(aws_sdk_s3, [&list]));
        assert_eq!(
            list_station_prefixes(&s3).await.unwrap(),
            vec![
                ("shows/rthk-radio1/".to_string(), "rthk-radio1".to_string()),
                ("shows/rthk-radio2/".to_string(), "rthk-radio2".to_string()),
            ]
        );
    }

    #[tokio::test]
    async fn station_listing_failure_is_an_error() {
        let list = mock!(aws_sdk_s3::Client::list_objects_v2)
            .then_error(|| aws_sdk_s3::operation::list_objects_v2::ListObjectsV2Error::unhandled("down"));
        let s3 = mock_s3(mock_client!(aws_sdk_s3, [&list]));
        let error = list_station_prefixes(&s3).await.unwrap_err().to_string();
        assert!(error.starts_with("ListObjectsV2 shows/: "), "{error}");
    }

    #[tokio::test]
    async fn only_json_object_sidecars_are_used() {
        let body = |key: &'static str, body: &'static [u8]| {
            mock!(aws_sdk_s3::Client::get_object)
                .match_requests(move |r| r.key() == Some(key))
                .then_output(move || GetObjectOutput::builder().body(ByteStream::from_static(body)).build())
        };
        let object = body("object", br#"{"show": {"name": "X"}}"#);
        let array = body("array", b"[1]");
        let invalid = body("invalid", b"{nope");
        let failing = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| r.key() == Some("failing"))
            .then_error(|| GetObjectError::unhandled("boom"));
        let s3 = mock_s3(mock_client!(
            aws_sdk_s3,
            RuleMode::MatchAny,
            [&object, &array, &invalid, &failing]
        ));
        assert_eq!(
            fetch_metadata(&s3, "object").await,
            Some(serde_json::json!({"show": {"name": "X"}}))
        );
        for key in ["array", "invalid", "failing"] {
            assert_eq!(fetch_metadata(&s3, key).await, None, "{key}");
        }
    }
}
