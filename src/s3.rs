use std::time::Duration;

use aws_config::retry::RetryConfig;
use aws_config::timeout::TimeoutConfig;
use aws_sdk_s3::config::http::HttpResponse;
use aws_sdk_s3::config::{Credentials, RequestChecksumCalculation, ResponseChecksumValidation};
use aws_sdk_s3::error::{ProvideErrorMetadata, SdkError};
use aws_sdk_s3::operation::list_objects_v2::ListObjectsV2Error;

use crate::cli::S3Args;

#[derive(Clone)]
pub struct S3 {
    pub client: aws_sdk_s3::Client,
    pub bucket: String,
}

impl S3Args {
    pub async fn build(&self) -> S3 {
        let creds = Credentials::new(
            &self.s3_access_key_id,
            &self.s3_secret_access_key,
            None,
            None,
            "env",
        );
        let config = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .credentials_provider(creds)
            .region(aws_config::Region::new(self.s3_region.clone()))
            .endpoint_url(&self.s3_endpoint)
            .timeout_config(
                TimeoutConfig::builder()
                    .connect_timeout(Duration::from_secs(10))
                    .read_timeout(Duration::from_secs(60))
                    .build(),
            )
            .retry_config(RetryConfig::standard().with_max_attempts(3))
            // S3-compatible stores don't all speak the SDK's default checksums.
            .request_checksum_calculation(RequestChecksumCalculation::WhenRequired)
            .response_checksum_validation(ResponseChecksumValidation::WhenRequired)
            .load()
            .await;
        // Path-style, as boto3 used against a custom endpoint: S3-compatible
        // stores don't all serve virtual-hosted bucket names.
        let config = aws_sdk_s3::config::Builder::from(&config)
            .force_path_style(true)
            .build();
        S3 {
            client: aws_sdk_s3::Client::from_conf(config),
            bucket: self.s3_bucket.clone(),
        }
    }
}

impl S3 {
    /// Every object key under `prefix`, across all pages.
    pub async fn list_keys(
        &self,
        prefix: &str,
    ) -> Result<Vec<String>, Box<SdkError<ListObjectsV2Error, HttpResponse>>> {
        let mut pages = self
            .client
            .list_objects_v2()
            .bucket(&self.bucket)
            .prefix(prefix)
            .into_paginator()
            .send();
        let mut keys = Vec::new();
        while let Some(page) = pages.next().await {
            keys.extend(page?.contents().iter().filter_map(|o| o.key().map(str::to_string)));
        }
        Ok(keys)
    }

    /// The whole body of one object.
    pub async fn get_bytes(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let output = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| anyhow::anyhow!("GetObject {key}: {}", aws_sdk_s3::error::DisplayErrorContext(e)))?;
        let body = output.body.collect().await?;
        Ok(body.into_bytes().to_vec())
    }
}

/// The S3 error code of a failed call, falling back to the bare HTTP status
/// (`"416"`) for error responses without a parseable body. The SDK itself
/// codes a bodyless 404 as `"NotFound"`.
pub fn error_code<E: ProvideErrorMetadata>(e: &SdkError<E, HttpResponse>) -> Option<String> {
    e.code()
        .map(str::to_string)
        .or_else(|| e.raw_response().map(|r| r.status().as_u16().to_string()))
}

#[cfg(test)]
mod tests {
    use crate::test_support::mock_s3;
    use aws_sdk_s3::operation::get_object::{GetObjectError, GetObjectOutput};
    use aws_sdk_s3::operation::list_objects_v2::ListObjectsV2Output;
    use aws_sdk_s3::primitives::ByteStream;
    use aws_sdk_s3::types::Object;
    use aws_smithy_mocks::{RuleMode, mock, mock_client};

    fn page(keys: &[&str], next: Option<&str>) -> ListObjectsV2Output {
        ListObjectsV2Output::builder()
            .set_contents(Some(keys.iter().map(|k| Object::builder().key(*k).build()).collect()))
            .is_truncated(next.is_some())
            .set_next_continuation_token(next.map(str::to_string))
            .build()
    }

    #[tokio::test]
    async fn list_keys_follows_continuation_tokens() {
        let first = mock!(aws_sdk_s3::Client::list_objects_v2)
            .match_requests(|r| r.prefix() == Some("p/") && r.continuation_token().is_none())
            .then_output(|| page(&["p/1", "p/2"], Some("t1")));
        let second = mock!(aws_sdk_s3::Client::list_objects_v2)
            .match_requests(|r| r.continuation_token() == Some("t1"))
            .then_output(|| page(&["p/3"], Some("t2")));
        let last = mock!(aws_sdk_s3::Client::list_objects_v2)
            .match_requests(|r| r.continuation_token() == Some("t2"))
            .then_output(|| page(&[], None));
        let s3 = mock_s3(mock_client!(aws_sdk_s3, RuleMode::MatchAny, [&first, &second, &last]));
        assert_eq!(s3.list_keys("p/").await.unwrap(), vec!["p/1", "p/2", "p/3"]);
        assert_eq!((first.num_calls(), second.num_calls(), last.num_calls()), (1, 1, 1));
    }

    #[tokio::test]
    async fn get_bytes_collects_the_body_or_names_the_key() {
        let ok = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| r.bucket() == Some("b") && r.key() == Some("good"))
            .then_output(|| GetObjectOutput::builder().body(ByteStream::from_static(b"hello")).build());
        let bad = mock!(aws_sdk_s3::Client::get_object)
            .match_requests(|r| r.key() == Some("bad"))
            .then_error(|| GetObjectError::unhandled("boom"));
        let s3 = mock_s3(mock_client!(aws_sdk_s3, RuleMode::MatchAny, [&ok, &bad]));
        assert_eq!(s3.get_bytes("good").await.unwrap(), b"hello");
        let error = s3.get_bytes("bad").await.unwrap_err().to_string();
        assert!(error.starts_with("GetObject bad: "), "{error}");
    }
}
