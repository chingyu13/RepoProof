"""Representative requirement/rubric recall for the fixed point catalog.

This is a product acceptance corpus, not training data.  The sentences avoid
copying catalog names verbatim and exercise common wording from software and
data-engineering assignments.  A hit means the intended point is in the first
five locally mapped candidates.
"""
from collections import defaultdict

from app.blueprint import assessment_point_distribution


CASES = [
    ("architecture", "Use pandas to construct the tabular result used by the notebook.", {"package_purpose"}),
    ("architecture", "Keep ingestion, processing, and dashboard concerns in separate modules.", {"component_responsibility", "module_dependency_boundary"}),
    ("project_logic", "The loader accepts a file path and returns a DataFrame with the documented columns.", {"function_io_contract"}),
    ("api", "Collect the source records from the provider's REST service.", {"data_source_acquisition"}),
    ("api", "Publish a JSON payload on the agreed MQTT topic for subscribers.", {"external_interface_contract"}),
    ("data_flow", "Convert the returned JSON fields into correctly typed DataFrame columns.", {"data_format_schema"}),
    ("data_flow", "Remove duplicate rows and handle null measurements before analysis.", {"cleaning_missing_values"}),
    ("data_flow", "Group readings by region and hour and calculate the total generation.", {"transformation_aggregation"}),
    ("data_flow", "Merge facility records with emissions records using the facility identifier.", {"integration_entity_matching"}),
    ("api", "Add latitude and longitude obtained from a geocoding service to each facility.", {"augmentation_enrichment"}),
    ("data_flow", "Move records from extraction through validation and storage to visualisation.", {"pipeline_data_flow"}),
    ("database", "Persist records with primary and foreign-key constraints at the required grain.", {"persistence_schema_integrity", "entity_relationship_keys"}),
    ("data_flow", "Reuse a saved local result so repeated notebook runs do not call the service again.", {"cache_materialisation"}),
    ("data_flow", "Send new readings continuously while preserving event timestamp order.", {"streaming_event_behavior", "ordering_deduplication"}),
    ("project_logic", "When stop becomes true, disconnect the client and update the runtime state.", {"condition_state_behavior", "resource_lifecycle"}),
    ("api", "Recover from a request timeout with bounded retries and close the client on failure.", {"failure_recovery", "retry_idempotency"}),
    ("security", "Load runtime settings from environment variables and reject invalid values.", {"configuration_security_validation", "configuration_deployment"}),
    ("testing", "Assert that invalid and missing readings fail the data-quality checks.", {"testing_quality_verification", "boundary_failure_testing"}),
    ("complexity", "Identify the repeated network operation that limits throughput as data volume grows.", {"performance_scalability"}),
    ("architecture", "Explain the consequence of replacing the message broker on downstream components.", {"design_decision_change_impact", "dependency_change_impact"}),
    ("architecture", "Imports must point from the presentation layer toward the service interface, not its implementation.", {"module_dependency_boundary"}),
    ("architecture", "The main routine initializes clients before work begins and releases them during shutdown.", {"entrypoint_lifecycle", "resource_lifecycle"}),
    ("architecture", "Use a different host and port in production without modifying source code.", {"configuration_deployment"}),
    ("api", "Check the HTTP status before decoding the response body and propagating its values.", {"request_response_handling"}),
    ("api", "Follow the next-page cursor while staying within the provider's request quota.", {"pagination_rate_limits"}),
    ("api", "Repeating a failed POST must not create a second payment or duplicate record.", {"retry_idempotency"}),
    ("data_flow", "Run extraction hourly only after the upstream preparation task succeeds.", {"orchestration_scheduling"}),
    ("data_flow", "Retain one reading per identifier and timestamp, then sort the result deterministically.", {"ordering_deduplication"}),
    ("data_flow", "Aggregate events in five-minute sliding intervals while accounting for late arrivals.", {"window_buffer_processing"}),
    ("data_flow", "Trace every reported metric back through its transformations to the original source.", {"data_lineage_quality"}),
    ("project_logic", "Iterate until the convergence condition is met, then return the calculated result.", {"algorithm_control_logic"}),
    ("project_logic", "The function appends to shared state, which changes what the next caller observes.", {"state_mutation_side_effect"}),
    ("project_logic", "Open the database connection, use it, and guarantee it closes when an exception occurs.", {"resource_lifecycle"}),
    ("project_logic", "Define the exact result for an empty collection and a missing key.", {"edge_case_boundary"}),
    ("database", "Model the one-to-many relationship using a foreign key to the parent record.", {"entity_relationship_keys"}),
    ("database", "Select active facilities, join their readings, and exclude rows outside the date range.", {"query_join_filter"}),
    ("database", "All ledger writes must commit together or be rolled back after any failure.", {"transaction_atomicity"}),
    ("database", "Add a required field without breaking consumers of records written under the old version.", {"schema_evolution_migration"}),
    ("security", "Only authenticated users with the instructor role may publish an assessment.", {"authentication_authorization"}),
    ("security", "Use parameters for untrusted search text rather than concatenating it into SQL.", {"input_validation_injection"}),
    ("security", "API credentials must not appear in source control, responses, or application logs.", {"secret_sensitive_data"}),
    ("testing", "Mock the remote service in unit tests but exercise the real adapter in integration tests.", {"test_scope_isolation"}),
    ("testing", "Verify timeout, malformed payload, empty input, and recovery paths.", {"boundary_failure_testing"}),
    ("complexity", "Determine how nested iteration changes running time and how materialisation changes memory use.", {"time_space_complexity"}),
    ("oop", "Keep account balance invariants inside a cohesive class instead of exposing mutable fields.", {"object_design_principles"}),
    ("oop", "Use a common interface so alternative storage implementations can be substituted.", {"class_collaboration_polymorphism"}),
    ("api", "Stop requesting pages when the cursor is absent and delay after a throttling response.", {"pagination_rate_limits"}),
    ("api", "Map a non-success response into the project's documented error result.", {"request_response_handling"}),
    ("data_flow", "A daily DAG coordinates download, cleaning, validation, and publication tasks.", {"orchestration_scheduling"}),
    ("data_flow", "Document the origin and validation history of every warehouse column.", {"data_lineage_quality"}),
    ("project_logic", "Predict the final counter and returned collection after all branches and loop iterations.", {"algorithm_control_logic", "condition_state_behavior"}),
    ("project_logic", "Handle zero-length, maximum-size, malformed, and absent inputs explicitly.", {"edge_case_boundary"}),
    ("database", "A failed second insert must leave neither of the two related rows stored.", {"transaction_atomicity"}),
    ("database", "Explain why the left join retains unmatched source rows in the result.", {"query_join_filter"}),
    ("security", "Reject a request when its session lacks permission for the protected resource.", {"authentication_authorization"}),
    ("security", "Prevent passwords and personal identifiers from being emitted by debug logging.", {"secret_sensitive_data"}),
    ("testing", "Choose assertions that expose both the invalid-input branch and timeout fallback.", {"boundary_failure_testing"}),
    ("testing", "A fake repository isolates business rules from persistence in the unit suite.", {"test_scope_isolation"}),
    ("complexity", "Avoid loading the complete dataset into memory when processing can be chunked.", {"time_space_complexity", "performance_scalability"}),
    ("oop", "Prefer composition when one object delegates persistence to another service.", {"class_collaboration_polymorphism"}),
]


def _top_points(text, focus_id, limit=5):
    target = {
        "id": "coverage",
        "label": "Requirement",
        "description": text,
        "weight": 1,
    }
    distribution = assessment_point_distribution(
        [target], [{"id": focus_id, "weight": 5}]
    )
    return list(distribution)[:limit]


def test_representative_document_point_recall_is_at_least_ninety_percent():
    hits = sum(bool(expected & set(_top_points(text, focus)))
               for focus, text, expected in CASES)
    assert hits / len(CASES) >= 0.90


def test_no_focus_family_has_a_large_coverage_hole():
    results = defaultdict(list)
    for focus, text, expected in CASES:
        results[focus].append(bool(expected & set(_top_points(text, focus))))
    for focus, hits in results.items():
        assert sum(hits) / len(hits) >= 0.80, focus
