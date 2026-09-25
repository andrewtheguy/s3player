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
/// (`"404"`) for error responses without a parseable body.
pub fn error_code<E: ProvideErrorMetadata>(e: &SdkError<E, HttpResponse>) -> Option<String> {
    e.code()
        .map(str::to_string)
        .or_else(|| e.raw_response().map(|r| r.status().as_u16().to_string()))
}
