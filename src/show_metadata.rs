//! Parsing of the `{audio_key}.metadata.json` sidecar written upstream by
//! `extract_shows_rthk`: the `show` object and the `chapters` array.

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, PartialEq, Eq)]
pub struct ShowMetadata {
    pub name: String,
    pub aired_on: NaiveDate,
    /// `HHMM_HHMM` when both `show.start` and `show.end` are `HH:MM`.
    pub time_slot: Option<String>,
}

#[derive(Debug, PartialEq, Eq, Clone, Copy, thiserror::Error)]
pub enum ShowMetadataError {
    #[error("missing_show_object")]
    MissingShowObject,
    #[error("missing_name")]
    MissingName,
    #[error("missing_date")]
    MissingDate,
    #[error("invalid_date")]
    InvalidDate,
}

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Chapter {
    pub title: String,
    pub start: i64,
    pub end: i64,
}

fn is_hh_mm(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 5
        && b[2] == b':'
        && [0, 1, 3, 4].iter().all(|&i| b[i].is_ascii_digit())
}

fn format_time_slot(start: Option<&Value>, end: Option<&Value>) -> Option<String> {
    let start = start?.as_str()?;
    let end = end?.as_str()?;
    if !is_hh_mm(start) || !is_hh_mm(end) {
        return None;
    }
    Some(format!("{}_{}", start.replace(':', ""), end.replace(':', "")))
}

pub fn extract_show_metadata(meta: &Value) -> Result<ShowMetadata, ShowMetadataError> {
    let show = meta
        .get("show")
        .and_then(Value::as_object)
        .ok_or(ShowMetadataError::MissingShowObject)?;

    let name = show
        .get("name")
        .and_then(Value::as_str)
        .filter(|n| !n.is_empty())
        .ok_or(ShowMetadataError::MissingName)?;

    let date_raw = show
        .get("date")
        .and_then(Value::as_str)
        .filter(|d| !d.is_empty())
        .ok_or(ShowMetadataError::MissingDate)?;
    let aired_on = NaiveDate::parse_from_str(date_raw, "%Y-%m-%d")
        .map_err(|_| ShowMetadataError::InvalidDate)?;

    Ok(ShowMetadata {
        name: name.to_string(),
        aired_on,
        time_slot: format_time_slot(show.get("start"), show.get("end")),
    })
}

/// Keep chapters with integer, non-negative, non-empty `start_ms_in_show` /
/// `end_ms_in_show` ranges; a missing or non-string title becomes "".
pub fn normalize_chapters(raw: &[Value]) -> Vec<Chapter> {
    raw.iter()
        .filter_map(|c| {
            let c = c.as_object()?;
            let start = c.get("start_ms_in_show")?.as_i64()?;
            let end = c.get("end_ms_in_show")?.as_i64()?;
            if start < 0 || end <= start {
                return None;
            }
            let title = c.get("title").and_then(Value::as_str).unwrap_or_default();
            Some(Chapter {
                title: title.to_string(),
                start,
                end,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn chapter(title: &str, start: i64, end: i64) -> Chapter {
        Chapter {
            title: title.to_string(),
            start,
            end,
        }
    }

    #[test]
    fn happy_path() {
        let meta = json!({"show": {"name": "管理新思維", "date": "2026-04-05", "start": "14:00", "end": "16:00"}});
        assert_eq!(
            extract_show_metadata(&meta),
            Ok(ShowMetadata {
                name: "管理新思維".to_string(),
                aired_on: NaiveDate::from_ymd_opt(2026, 4, 5).unwrap(),
                time_slot: Some("1400_1600".to_string()),
            })
        );
    }

    #[test]
    fn structural_errors() {
        use ShowMetadataError::*;
        let cases = [
            (json!({}), MissingShowObject),
            (json!({"show": "nope"}), MissingShowObject),
            (json!({"show": {"date": "2026-04-05"}}), MissingName),
            (json!({"show": {"name": "", "date": "2026-04-05"}}), MissingName),
            (json!({"show": {"name": 123, "date": "2026-04-05"}}), MissingName),
            (json!({"show": {"name": "X"}}), MissingDate),
            (json!({"show": {"name": "X", "date": "2026/04/05"}}), InvalidDate),
            (json!({"show": {"name": "X", "date": "04-05-2026"}}), InvalidDate),
            (json!({"show": {"name": "X", "date": "2026-02-30"}}), InvalidDate),
        ];
        for (meta, expected) in cases {
            assert_eq!(extract_show_metadata(&meta), Err(expected), "{meta}");
        }
    }

    #[test]
    fn time_slot_is_none_unless_both_times_are_hh_mm() {
        for (start, end) in [
            (json!(null), json!(null)),
            (json!("14:00"), json!(null)),
            (json!("6:00"), json!("10:00")),
            (json!("0600"), json!("1000")),
            (json!("14:0"), json!("16:00")),
            (json!(1400), json!(1600)),
        ] {
            let meta = json!({"show": {"name": "X", "date": "2026-04-05", "start": start, "end": end}});
            assert_eq!(extract_show_metadata(&meta).unwrap().time_slot, None, "{meta}");
        }
    }

    #[test]
    fn midnight_boundary() {
        let meta = json!({"show": {"name": "X", "date": "2026-04-05", "start": "00:00", "end": "02:00"}});
        assert_eq!(
            extract_show_metadata(&meta).unwrap().time_slot.as_deref(),
            Some("0000_0200")
        );
    }

    #[test]
    fn normalize_basic_sidecar_shape() {
        let raw = json!([
            {"index": 0, "start_ms_in_show": 0, "end_ms_in_show": 1454362, "title": "00:05:45 - 00:30:00 [show1]"},
            {"index": 1, "start_ms_in_show": 1454362, "end_ms_in_show": 3211415, "title": "00:30:00 - 00:59:17 [show2]"},
        ]);
        assert_eq!(
            normalize_chapters(raw.as_array().unwrap()),
            vec![
                chapter("00:05:45 - 00:30:00 [show1]", 0, 1454362),
                chapter("00:30:00 - 00:59:17 [show2]", 1454362, 3211415),
            ]
        );
    }

    #[test]
    fn normalize_title_defaults_to_empty() {
        let raw = json!([
            {"start_ms_in_show": 1000, "end_ms_in_show": 2000},
            {"start_ms_in_show": 1000, "end_ms_in_show": 2000, "title": 42},
        ]);
        assert_eq!(
            normalize_chapters(raw.as_array().unwrap()),
            vec![chapter("", 1000, 2000), chapter("", 1000, 2000)]
        );
    }

    #[test]
    fn normalize_skips_invalid_entries() {
        let raw = json!([
            "not a dict", 42, null,
            {"title": "missing times"},
            {"start_ms_in_show": 3000},
            {"start_ms_in_show": "1000", "end_ms_in_show": 2000, "title": "string start"},
            {"start_ms_in_show": 1000, "end_ms_in_show": 2.5, "title": "float end"},
            {"start_ms_in_show": -1, "end_ms_in_show": 1000, "title": "neg start"},
            {"start_ms_in_show": 0, "end_ms_in_show": -1, "title": "neg end"},
            {"start_ms_in_show": 1000, "end_ms_in_show": 1000, "title": "zero length"},
            {"start_ms_in_show": 2000, "end_ms_in_show": 1500, "title": "end before start"},
            {"start_ms_in_show": 1000, "end_ms_in_show": 2000, "title": "ok"},
        ]);
        assert_eq!(
            normalize_chapters(raw.as_array().unwrap()),
            vec![chapter("ok", 1000, 2000)]
        );
        assert_eq!(normalize_chapters(&[]), vec![]);
    }
}
