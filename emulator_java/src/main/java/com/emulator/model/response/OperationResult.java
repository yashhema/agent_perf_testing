package com.emulator.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

public class OperationResult {
    private String operation;
    private String status;
    @JsonProperty("duration_ms")
    private long durationMs;
    private Map<String, Object> details;

    public OperationResult() {}

    public OperationResult(String operation, String status, long durationMs, Map<String, Object> details) {
        this.operation = operation;
        this.status = status;
        this.durationMs = durationMs;
        this.details = details;
    }

    public String getOperation() { return operation; }
    public void setOperation(String v) { this.operation = v; }
    public String getStatus() { return status; }
    public void setStatus(String v) { this.status = v; }
    public long getDurationMs() { return durationMs; }
    public void setDurationMs(long v) { this.durationMs = v; }
    public Map<String, Object> getDetails() { return details; }
    public void setDetails(Map<String, Object> v) { this.details = v; }
}
