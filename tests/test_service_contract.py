from kagent.service.contract import service_openapi


def test_service_contract_documents_runtime_streaming_endpoint():
    payload = service_openapi()
    operation = payload["paths"]["/runtime/run/stream"]["post"]

    assert operation["operationId"] == "postRuntimeRunStream"
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RuntimeRunRequest"
    }
    assert "text/event-stream" in operation["responses"]["200"]["content"]
    assert "Idempotency-Key" not in str(operation)


def test_service_contract_documents_trace_permission_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]
    expected_properties = {
        "trace_directory_permissions": {"type": "string", "const": "0700"},
        "trace_file_permissions": {"type": "string", "const": "0600"},
        "trace_probe_file_permissions": {"type": "string", "const": "0600"},
    }

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        for property_name, expected_schema in expected_properties.items():
            assert schema_properties[property_name] == expected_schema


def test_service_contract_documents_internal_auth_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        assert schema_properties["auth_subject_count"] == {"type": "string"}
        assert schema_properties["idempotency_cache_backend"] == {
            "type": "string",
            "enum": ["memory", "sqlite"],
        }
        assert schema_properties["idempotency_cache_path_configured"] == {
            "type": "string",
            "enum": ["true", "false"],
        }
        assert schema_properties["runtime_allowed_tools"] == {"type": "string"}
        assert schema_properties["runtime_allowed_tools_by_subject_count"] == {
            "type": "string"
        }
        assert schema_properties["runtime_pending_approval_stale_seconds"] == {
            "type": "string"
        }
        assert schema_properties["runtime_instance_heartbeat_seconds"] == {
            "type": "string"
        }
        assert schema_properties["runtime_orphaned_run_stale_seconds"] == {
            "type": "string"
        }


def test_service_contract_documents_runtime_progress_sink_failure_metric():
    payload = service_openapi()
    schema_properties = payload["components"]["schemas"]["MetricsResponse"]["properties"]

    assert schema_properties["runtime_progress_event_sink_failures_total"] == {
        "type": "string"
    }
    assert schema_properties["runtime_hook_failures_total"] == {"type": "string"}
    assert (
        "runtime_progress_event_sink_failures_total"
        not in payload["components"]["schemas"]["ConfigResponse"]["properties"]
    )
    assert (
        "runtime_hook_failures_total"
        not in payload["components"]["schemas"]["ConfigResponse"]["properties"]
    )


def test_service_contract_documents_runtime_reconciliation_metrics():
    payload = service_openapi()
    schema_properties = payload["components"]["schemas"]["MetricsResponse"]["properties"]

    for metric in [
        "runtime_reconciliation_runs_total",
        "runtime_reconciliation_traces_scanned_total",
        "runtime_reconciliation_errors_total",
    ]:
        assert schema_properties[metric] == {"type": "string"}
    for metric in [
        "runtime_reconciliation_runs_by_status",
        "runtime_reconciliation_outcomes",
    ]:
        assert schema_properties[metric] == {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }


def test_service_contract_documents_runtime_llm_provider_metrics():
    payload = service_openapi()
    schema_properties = payload["components"]["schemas"]["MetricsResponse"]["properties"]
    string_metrics = [
        "runtime_llm_provider_requests_total",
        "runtime_llm_provider_request_attempts_total",
        "runtime_llm_provider_request_retries_total",
        "runtime_llm_provider_request_duration_seconds_count",
        "runtime_llm_provider_request_duration_seconds_sum",
        "average_runtime_llm_provider_request_duration_seconds",
        "max_runtime_llm_provider_request_duration_seconds",
    ]
    map_metrics = [
        "runtime_llm_provider_requests_by_status",
        "runtime_llm_provider_request_errors_by_type",
        "runtime_llm_provider_request_http_status",
        "runtime_llm_provider_request_retryable_reason",
        "runtime_llm_provider_request_duration_seconds_bucket",
    ]

    for metric_name in string_metrics:
        assert schema_properties[metric_name] == {"type": "string"}

    for metric_name in map_metrics:
        assert schema_properties[metric_name] == {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }

        assert (
            metric_name
            not in payload["components"]["schemas"]["ConfigResponse"]["properties"]
        )


def test_service_contract_documents_llm_provider_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]
    expected_properties = {
        "llm_provider": {
            "type": "string",
            "enum": [
                "openai_compatible",
                "deepseek",
                "qwen_openai_compatible",
                "ollama_openai_compatible",
                "unconfigured",
            ],
        },
        "llm_provider_display_name": {"type": "string"},
        "llm_base_url": {"type": "string"},
        "llm_base_url_configured": {
            "type": "string",
            "enum": ["true", "false"],
        },
        "llm_model": {"type": "string"},
        "llm_api_key_configured": {
            "type": "string",
            "enum": ["true", "false"],
        },
        "llm_timeout_seconds": {"type": "string"},
        "llm_max_retries": {"type": "string"},
        "llm_retry_backoff_seconds": {"type": "string"},
    }

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        for property_name, expected_schema in expected_properties.items():
            assert schema_properties[property_name] == expected_schema


def test_service_contract_documents_embedding_provider_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]
    expected_properties = {
        "embedding_provider": {
            "type": "string",
            "enum": ["openai_compatible", "unconfigured"],
        },
        "embedding_base_url": {"type": "string"},
        "embedding_base_url_configured": {
            "type": "string",
            "enum": ["true", "false"],
        },
        "embedding_model": {"type": "string"},
        "embedding_api_key_configured": {
            "type": "string",
            "enum": ["true", "false"],
        },
        "embedding_timeout_seconds": {"type": "string"},
        "embedding_max_retries": {"type": "string"},
        "embedding_retry_backoff_seconds": {"type": "string"},
    }

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        for property_name, expected_schema in expected_properties.items():
            assert schema_properties[property_name] == expected_schema


def test_service_contract_documents_structured_readiness_failed_checks():
    payload = service_openapi()
    readiness_schema = payload["components"]["schemas"]["ReadinessResponse"]

    assert readiness_schema["required"] == ["status", "checks", "failed_checks"]
    assert readiness_schema["properties"]["error_code"] == {
        "type": "string",
        "const": "readiness_failed",
    }
    assert readiness_schema["properties"]["failed_checks"] == {
        "type": "array",
        "items": {"type": "string"},
    }
